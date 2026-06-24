"""Analyst registry operations — FR-101.

Plain SQL CRUD for the analysts table, a jurisdiction scope-lock guard,
an import-roster bulk upsert, and a small argparse CLI.

Scope-lock citation (PRD §4 Non-Goals + §13 Risks):
  "No coverage of Turkey-domiciled or BIST-focused influencers (legal
   posture, see Risks)." The _assert_in_scope function enforces this at
   write time so the guard is consistent across all entry points.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import psycopg

from brier_pipeline.db import connect
from brier_pipeline.models import Analyst, AnalystStatus

# ---------------------------------------------------------------------------
# Scope-lock: Turkey / BIST blocklist (PRD §4 Non-Goals, §13 Risks)
# ---------------------------------------------------------------------------

_TURKEY_BLOCKLIST: frozenset[str] = frozenset(
    {
        "TR",
        "TUR",
        "turkey",
        "türkiye",
        "turkiye",
        "BIST",
        "istanbul",
        "ankara",
    }
)


def _assert_youtube_channel(channel_id: str) -> None:
    """Raise ValueError if channel_id is not a YouTube channel ID (scope lock).

    Scope lock (CLAUDE.md): crypto + YouTube only. Real YouTube channel IDs begin
    with 'UC'. This is a PREFIX check, not a length check — fixture/test IDs use
    the 'UC' prefix with shorter bodies than the real 24-char form, and the
    guard's purpose is to reject non-YouTube identifiers (handles like '@name',
    other platforms), not to validate the full canonical length.
    """
    if not channel_id.startswith("UC"):
        raise ValueError(
            f"Scope-lock violation: channel_id {channel_id!r} is not a YouTube "
            "channel ID (must start with 'UC'). Brier covers YouTube only "
            "(crypto + YouTube; CLAUDE.md scope lock)."
        )


def _assert_in_scope(jurisdiction_flag: str | None) -> None:
    """Raise ValueError if jurisdiction_flag indicates Turkey / BIST coverage.

    PRD Non-Goal §4: No coverage of Turkey-domiciled or BIST-focused
    influencers (legal posture). Case-insensitive match against the
    blocklist defined in _TURKEY_BLOCKLIST.
    """
    if jurisdiction_flag is None:
        return
    if jurisdiction_flag.lower() in {v.lower() for v in _TURKEY_BLOCKLIST}:
        raise ValueError(
            f"Scope-lock violation: jurisdiction_flag {jurisdiction_flag!r} indicates "
            "Turkey/BIST coverage, which is excluded by PRD §4 Non-Goals. "
            "Remove this analyst from the roster."
        )


# ---------------------------------------------------------------------------
# Row reader helper
# ---------------------------------------------------------------------------


def _row_to_analyst(row: tuple[Any, ...]) -> Analyst:
    """Map a DB row (id, channel_id, display_name, slug, status, jurisdiction_flag,
    notify_email) to Analyst."""
    return Analyst(
        id=int(row[0]),
        channel_id=str(row[1]),
        display_name=str(row[2]),
        slug=str(row[3]),
        status=AnalystStatus(str(row[4])),
        jurisdiction_flag=str(row[5]) if row[5] is not None else None,
        notify_email=str(row[6]) if row[6] is not None else None,
    )


_BASE_SELECT = (
    "select id, channel_id, display_name, slug, status, jurisdiction_flag, notify_email "
    "from analysts"
)
_SELECT_BY_ID = _BASE_SELECT + " where id = %s"
_SELECT_BY_SLUG = _BASE_SELECT + " where slug = %s"
_SELECT_BY_CHANNEL = _BASE_SELECT + " where channel_id = %s"
_SELECT_BY_STATUS = _BASE_SELECT + " where status = %s order by id"
_SELECT_ALL = _BASE_SELECT + " order by id"


# ---------------------------------------------------------------------------
# Public API — all take conn; caller owns the transaction
# ---------------------------------------------------------------------------


def add_analyst(
    conn: psycopg.Connection[Any],
    channel_id: str,
    display_name: str,
    slug: str,
    status: str = "active",
    jurisdiction_flag: str | None = None,
    notify_email: str | None = None,
) -> int:
    """Insert a new analyst row and return the new id.

    notify_email is the optional AC-5/UF-3 adjudication-notice contact; None
    when unknown (the common case for public analysts).

    Raises:
        ValueError: if channel_id is not a YouTube ID or jurisdiction_flag
            indicates Turkey/BIST (scope lock).
        psycopg.errors.UniqueViolation: if channel_id or slug already exists.
    """
    _assert_youtube_channel(channel_id)
    _assert_in_scope(jurisdiction_flag)
    # Validate status against the enum before hitting the DB.
    AnalystStatus(status)
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into analysts
                (channel_id, display_name, slug, status, jurisdiction_flag, notify_email)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (channel_id, display_name, slug, status, jurisdiction_flag, notify_email),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def get_analyst(
    conn: psycopg.Connection[Any],
    *,
    analyst_id: int | None = None,
    slug: str | None = None,
    channel_id: str | None = None,
) -> Analyst | None:
    """Return an Analyst by exactly one selector, or None if not found.

    Raises:
        ValueError: if zero or more than one selector is provided.
    """
    selectors = {
        k: v
        for k, v in {"analyst_id": analyst_id, "slug": slug, "channel_id": channel_id}.items()
        if v is not None
    }
    if len(selectors) != 1:
        raise ValueError(
            "Exactly one selector required (analyst_id, slug, or channel_id); "
            f"got {list(selectors)}"
        )

    with conn.cursor() as cur:
        if analyst_id is not None:
            cur.execute(_SELECT_BY_ID, (analyst_id,))
        elif slug is not None:
            cur.execute(_SELECT_BY_SLUG, (slug,))
        else:
            cur.execute(_SELECT_BY_CHANNEL, (channel_id,))
        row = cur.fetchone()

    if row is None:
        return None
    return _row_to_analyst(row)


def list_analysts(
    conn: psycopg.Connection[Any],
    *,
    status: str | None = None,
) -> list[Analyst]:
    """Return all analysts ordered by id, optionally filtered by status."""
    with conn.cursor() as cur:
        if status is not None:
            AnalystStatus(status)  # validate
            cur.execute(_SELECT_BY_STATUS, (status,))
        else:
            cur.execute(_SELECT_ALL)
        rows = cur.fetchall()
    return [_row_to_analyst(r) for r in rows]


def update_status(
    conn: psycopg.Connection[Any],
    analyst_id: int,
    status: str,
) -> None:
    """Update the status of an analyst (active | paused | removed).

    Raises:
        ValueError: if status is not a valid AnalystStatus value.
    """
    AnalystStatus(status)  # validate before touching DB
    with conn.cursor() as cur:
        cur.execute(
            "update analysts set status = %s where id = %s",
            (status, analyst_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Analyst id={analyst_id} not found.")


def set_jurisdiction_flag(
    conn: psycopg.Connection[Any],
    analyst_id: int,
    jurisdiction_flag: str | None,
) -> None:
    """Set (or clear) the jurisdiction_flag for an analyst.

    Raises:
        ValueError: if the flag indicates Turkey/BIST (scope lock).
    """
    _assert_in_scope(jurisdiction_flag)
    with conn.cursor() as cur:
        cur.execute(
            "update analysts set jurisdiction_flag = %s where id = %s",
            (jurisdiction_flag, analyst_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Analyst id={analyst_id} not found.")


def remove_analyst(
    conn: psycopg.Connection[Any],
    analyst_id: int,
) -> None:
    """Soft-remove an analyst by setting status to 'removed'.

    Does NOT DELETE the row; videos and claims FK-reference analysts.
    """
    with conn.cursor() as cur:
        cur.execute(
            "update analysts set status = 'removed' where id = %s",
            (analyst_id,),
        )
        if cur.rowcount == 0:
            raise ValueError(f"Analyst id={analyst_id} not found.")


def import_roster(
    conn: psycopg.Connection[Any],
    roster_path: Path,
) -> dict[str, int]:
    """Upsert all analysts from a JSON roster file.

    The upsert is ON CONFLICT (channel_id) DO UPDATE matching seed.py's
    behaviour, so re-importing the same file is idempotent.

    Each entry is scope-lock checked before the upsert.

    Args:
        conn: Caller-owned connection; caller commits.
        roster_path: Path to a JSON file containing a list of analyst dicts.

    Returns:
        {"total": N, "inserted": x, "updated": y}

    Raises:
        ValueError: if any entry violates the scope lock.
    """
    data: list[dict[str, Any]] = json.loads(roster_path.read_text(encoding="utf-8"))

    total = len(data)
    inserted = 0
    updated = 0

    for entry in data:
        _assert_youtube_channel(str(entry["channel_id"]))
        jf: str | None = entry.get("jurisdiction_flag")
        _assert_in_scope(jf)
        AnalystStatus(str(entry.get("status", "active")))  # validate status (as in add_analyst)
        # notify_email is optional in the roster (AC-5/UF-3 contact); default None.
        entry.setdefault("notify_email", None)

        with conn.cursor() as cur:
            cur.execute(
                """
                insert into analysts
                    (channel_id, display_name, slug, status, jurisdiction_flag, notify_email)
                values
                    (%(channel_id)s, %(display_name)s, %(slug)s,
                     %(status)s, %(jurisdiction_flag)s, %(notify_email)s)
                on conflict (channel_id) do update set
                    display_name      = excluded.display_name,
                    slug              = excluded.slug,
                    status            = excluded.status,
                    jurisdiction_flag = excluded.jurisdiction_flag,
                    notify_email      = excluded.notify_email
                returning (xmax = 0) as is_insert
                """,
                entry,
            )
            row = cur.fetchone()
            assert row is not None
            if bool(row[0]):
                inserted += 1
            else:
                updated += 1

    return {"total": total, "inserted": inserted, "updated": updated}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Argparse CLI for analyst registry operations.

    Opens its own connection, commits its own transaction, and prints
    concise results. The DB connection is owned here; no caller above.
    """
    parser = argparse.ArgumentParser(
        prog="python -m brier_pipeline.ingestion.registry",
        description="Analyst registry management (FR-101).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Register a new analyst.")
    p_add.add_argument("--channel-id", required=True, help="YouTube channel ID.")
    p_add.add_argument("--display-name", required=True, help="Display name.")
    p_add.add_argument("--slug", required=True, help="URL slug (unique, kebab-case).")
    p_add.add_argument("--status", default="active", help="Status: active|paused|removed.")
    p_add.add_argument("--jurisdiction-flag", default=None, help="ISO jurisdiction code.")
    p_add.add_argument(
        "--notify-email",
        default=None,
        help="Optional contact email for AC-5/UF-3 adjudication notices.",
    )

    # list
    p_list = sub.add_parser("list", help="List analysts.")
    p_list.add_argument("--status", default=None, help="Filter by status.")

    # status
    p_status = sub.add_parser("status", help="Update analyst status.")
    p_status.add_argument("analyst_id", type=int, help="Analyst DB id.")
    p_status.add_argument("new_status", help="New status: active|paused|removed.")

    # set-jurisdiction
    p_jur = sub.add_parser("set-jurisdiction", help="Set or clear jurisdiction flag.")
    p_jur.add_argument("analyst_id", type=int, help="Analyst DB id.")
    p_jur.add_argument(
        "jurisdiction_flag",
        nargs="?",
        default=None,
        help="Jurisdiction code (omit to clear).",
    )

    # remove
    p_remove = sub.add_parser("remove", help="Soft-remove an analyst (sets status=removed).")
    p_remove.add_argument("analyst_id", type=int, help="Analyst DB id.")

    # import-roster
    p_import = sub.add_parser("import-roster", help="Upsert analysts from a JSON roster file.")
    p_import.add_argument("roster_path", help="Path to roster JSON file.")

    args = parser.parse_args(argv)

    try:
        with connect() as conn:
            if args.command == "add":
                new_id = add_analyst(
                    conn,
                    channel_id=args.channel_id,
                    display_name=args.display_name,
                    slug=args.slug,
                    status=args.status,
                    jurisdiction_flag=args.jurisdiction_flag,
                    notify_email=args.notify_email,
                )
                conn.commit()
                print(f"Added analyst id={new_id} slug={args.slug!r}.")

            elif args.command == "list":
                analysts = list_analysts(conn, status=args.status)
                if not analysts:
                    print("No analysts found.")
                else:
                    for a in analysts:
                        jf = a.jurisdiction_flag or "—"
                        print(f"  {a.id:>4}  {a.slug:<30}  {a.status:<8}  {jf}")

            elif args.command == "status":
                update_status(conn, args.analyst_id, args.new_status)
                conn.commit()
                print(f"Analyst id={args.analyst_id} status set to {args.new_status!r}.")

            elif args.command == "set-jurisdiction":
                set_jurisdiction_flag(conn, args.analyst_id, args.jurisdiction_flag)
                conn.commit()
                jf = args.jurisdiction_flag or "(cleared)"
                print(f"Analyst id={args.analyst_id} jurisdiction_flag set to {jf!r}.")

            elif args.command == "remove":
                remove_analyst(conn, args.analyst_id)
                conn.commit()
                print(f"Analyst id={args.analyst_id} marked as removed.")

            elif args.command == "import-roster":
                result = import_roster(conn, Path(args.roster_path))
                conn.commit()
                print(
                    f"Roster import complete: total={result['total']} "
                    f"inserted={result['inserted']} updated={result['updated']}."
                )

    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
