"""score_runs append-only narrowing (NFR-3 hardening; audit finding A2#8).

score_runs is deliberately NOT a fully immutable ledger — `_finish_score_run`
stamps `finished_at` once via a direct UPDATE. Migration 0010 installs
`forbid_score_runs_mutation`, which permits exactly that stamp and bars
everything else: any UPDATE that touches another column, and any DELETE, raises.
These tests prove the trigger fires (the schema-level "is it installed" guard
lives in test_migrations.py::test_append_only_triggers_present).

DB-backed: requests `db_conn`, so it skips cleanly when no Postgres is running
(keeping `make check` green without Docker). Every case rolls back — nothing
persists. Requires migration 0010 applied (CI runs migrate before the suite).
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest


def _seed_score_run(cur: psycopg.Cursor[Any], *, trigger: str = "demo") -> int:
    """Insert a bare score_runs row (no child scores) and return its id."""
    cur.execute(
        "insert into score_runs (methodology_version, trigger, notes) "
        "values ('v1.1', %s, 'a2-8 probe') returning id",
        (trigger,),
    )
    return int(cur.fetchone()[0])  # type: ignore[index]


def test_finished_at_update_is_allowed(db_conn: psycopg.Connection[Any]) -> None:
    """The one permitted mutation: stamping finished_at (what _finish_score_run does)."""
    with db_conn.cursor() as cur:
        run_id = _seed_score_run(cur)
        # Must not raise — this is the live finalize path.
        cur.execute("update score_runs set finished_at = now() where id = %s", (run_id,))
        cur.execute("select finished_at from score_runs where id = %s", (run_id,))
        assert cur.fetchone()[0] is not None  # type: ignore[index]
    db_conn.rollback()


def test_idempotent_finished_at_restamp_is_allowed(db_conn: psycopg.Connection[Any]) -> None:
    """Re-stamping finished_at (no other column changes) stays allowed."""
    with db_conn.cursor() as cur:
        run_id = _seed_score_run(cur)
        cur.execute("update score_runs set finished_at = now() where id = %s", (run_id,))
        # A second finished_at write still only changes finished_at -> allowed.
        cur.execute("update score_runs set finished_at = now() where id = %s", (run_id,))
    db_conn.rollback()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("methodology_version", "'v9.9'"),
        # A literal, not now(): now() is constant within a txn, so set started_at
        # = now() would be a true no-op the trigger correctly allows (is distinct
        # from). A backdated literal is a real change and must raise.
        ("started_at", "'2000-01-01T00:00:00+00'::timestamptz"),
        ("trigger", "'nightly'"),
        ("notes", "'tampered'"),
    ],
)
def test_non_finished_at_update_is_rejected(
    db_conn: psycopg.Connection[Any], column: str, value: str
) -> None:
    """Any UPDATE that changes a column other than finished_at must raise (NFR-3)."""
    with db_conn.cursor() as cur:
        run_id = _seed_score_run(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            cur.execute(f"update score_runs set {column} = {value} where id = %s", (run_id,))
    db_conn.rollback()


def test_mixed_update_touching_finished_at_and_notes_is_rejected(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Stamping finished_at does not license smuggling another column edit alongside it."""
    with db_conn.cursor() as cur:
        run_id = _seed_score_run(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
            cur.execute(
                "update score_runs set finished_at = now(), notes = 'tampered' where id = %s",
                (run_id,),
            )
    db_conn.rollback()


def test_delete_is_rejected(db_conn: psycopg.Connection[Any]) -> None:
    """A score_run is the archive anchor for its scores; DELETE must raise (NFR-3)."""
    with db_conn.cursor() as cur:
        run_id = _seed_score_run(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="never deleted"):
            cur.execute("delete from score_runs where id = %s", (run_id,))
    db_conn.rollback()
