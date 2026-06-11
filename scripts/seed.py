#!/usr/bin/env python3
"""Seed the dev database with the fixture analyst registry.

Skeleton scope: applies migrations (via the tiny runner) and upserts the three
fixture analysts from data/fixtures/analysts.json. No claims, no prices, no
scores — those fixtures arrive with epic E1 (see TASKS.md).

Run via `make seed` (uses the pipeline venv; requires the docker-compose db).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "services" / "pipeline" / "migrations"))

from migrate import database_url, run_migrations  # noqa: E402

FIXTURES = REPO_ROOT / "data" / "fixtures" / "analysts.json"

UPSERT = """
insert into analysts (channel_id, display_name, slug, status, jurisdiction_flag)
values (%(channel_id)s, %(display_name)s, %(slug)s, %(status)s, %(jurisdiction_flag)s)
on conflict (channel_id) do update set
    display_name = excluded.display_name,
    slug = excluded.slug,
    status = excluded.status,
    jurisdiction_flag = excluded.jurisdiction_flag
"""


def main() -> int:
    run_migrations()
    analysts = json.loads(FIXTURES.read_text(encoding="utf-8"))
    with psycopg.connect(database_url()) as conn:
        with conn.cursor() as cur:
            for analyst in analysts:
                cur.execute(UPSERT, analyst)
    print(f"seed: upserted {len(analysts)} analysts from {FIXTURES.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
