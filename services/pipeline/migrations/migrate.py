#!/usr/bin/env python3
"""Tiny migration runner: numbered *.sql files, applied in order, once.

No framework — applied filenames are recorded in schema_migrations. Run via
`make seed` or directly: services/pipeline/.venv/bin/python migrations/migrate.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent

# Re-exported for scripts/seed.py; canonical definition lives in the package.
from brier_pipeline.config import database_url  # noqa: E402

__all__ = ["database_url", "run_migrations"]


def run_migrations() -> list[str]:
    """Apply unapplied migrations in filename order; returns those applied."""
    applied: list[str] = []
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                create table if not exists schema_migrations (
                    filename text primary key,
                    applied_at timestamptz not null default now()
                )
                """
            )
            cur.execute("select filename from schema_migrations")
            done = {row[0] for row in cur.fetchall()}
            for path in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
                if path.name in done:
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute("insert into schema_migrations (filename) values (%s)", (path.name,))
                applied.append(path.name)
    if applied:
        print("migrate: applied " + ", ".join(applied))
    else:
        print("migrate: up to date")
    return applied


if __name__ == "__main__":
    run_migrations()
    sys.exit(0)
