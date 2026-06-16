"""Migration-runner guard tests (launch-readiness, 2026-06-16).

The numbered SQL migrations must apply cleanly and *idempotently* to the
dev/CI database, every numbered file must be recorded, and the schema they
produce must contain the core ledger/ops tables plus the NFR-3 append-only
triggers. These guard two things every dev change can silently break:

  * `make seed` is safe to re-run — re-applying an already-applied migration is
    a no-op, never an error (the migrate runner records applied filenames).
  * a new migration that fails to apply, or that is added but not picked up by
    the runner, fails CI loudly instead of drifting the schema.

DB-backed: each test requests `db_conn` so it skips cleanly when no Postgres is
running (keeping `make check` green without Docker locally). In CI the Postgres
service container is up, so these run on every push.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "services" / "pipeline" / "migrations"
sys.path.insert(0, str(MIGRATIONS_DIR))

from migrate import run_migrations  # type: ignore[import-not-found]  # noqa: E402

# Core tables the schema must always contain (one or more migrations create
# each). Asserted as a subset of the live schema so adding new tables never
# breaks this test, but dropping a core one does.
_CORE_TABLES = {
    "analysts",
    "videos",
    "transcripts",
    "claims",
    "price_daily",
    "resolutions",
    "score_runs",
    "scores",
    "jobs",
    "disputes",
    "corrections",
    "alerts",
    "spend_ledger",
    "erasure_requests",
    "schema_migrations",
}


def test_migrations_apply_idempotently(db_conn: psycopg.Connection[Any]) -> None:
    """A second `run_migrations()` pass must apply nothing (pure no-op).

    `db_conn` is requested only so this skips when no DB is running;
    `run_migrations()` manages its own (committing) connection.
    """
    run_migrations()  # converge — applies nothing if already applied
    second_pass = run_migrations()
    assert second_pass == [], (
        f"migrations are not idempotent: a second pass re-applied {second_pass}"
    )


def test_every_numbered_migration_is_recorded(db_conn: psycopg.Connection[Any]) -> None:
    run_migrations()  # ensure converged
    sql_files = sorted(p.name for p in MIGRATIONS_DIR.glob("[0-9]*.sql"))
    assert len(sql_files) >= 8, f"expected >=8 numbered migrations, found {sql_files}"

    with db_conn.cursor() as cur:
        cur.execute("select filename from schema_migrations")
        recorded = {row[0] for row in cur.fetchall()}

    missing = [f for f in sql_files if f not in recorded]
    assert not missing, f"numbered migrations on disk but not recorded as applied: {missing}"


def test_core_tables_present(db_conn: psycopg.Connection[Any]) -> None:
    run_migrations()
    with db_conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables where table_schema = 'public'"
        )
        present = {row[0] for row in cur.fetchall()}

    missing = _CORE_TABLES - present
    assert not missing, f"core tables missing from the migrated schema: {sorted(missing)}"


def test_append_only_triggers_present(db_conn: psycopg.Connection[Any]) -> None:
    """NFR-3: resolutions and scores must carry the append-only mutation guard.

    The triggers' enforcement (UPDATE/DELETE raise) is proven in
    test_append_only_placeholder.py; this asserts they are actually installed
    by the migration so a dropped/renamed trigger is caught at the schema level.
    """
    run_migrations()
    with db_conn.cursor() as cur:
        cur.execute("select tgname from pg_trigger where not tgisinternal")
        triggers = {row[0] for row in cur.fetchall()}

    for required in ("resolutions_append_only", "scores_append_only"):
        assert required in triggers, f"NFR-3 append-only trigger {required!r} is not installed"
