"""Shared test fixtures. Database-backed tests skip when no dev DB is running."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from brier_pipeline.config import database_url


@pytest.fixture
def db_conn() -> Iterator[psycopg.Connection[Any]]:
    """A rolled-back connection to the dev database; skips if unreachable."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("dev database not running (docker compose up -d db && make seed)")
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
