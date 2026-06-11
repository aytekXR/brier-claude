"""Thin psycopg helper. Plain SQL everywhere; no ORM (locked stack)."""

from __future__ import annotations

from typing import Any

import psycopg

from brier_pipeline.config import database_url


def connect() -> psycopg.Connection[Any]:
    """Open a connection to the pipeline database."""
    return psycopg.connect(database_url())
