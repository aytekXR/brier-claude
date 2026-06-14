"""Pipeline configuration. Environment-driven, no framework."""

from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "postgresql://brier:brier@localhost:5432/brier"

METHODOLOGY_VERSION = "v1.0"  # bump only via ADR + full-history recompute (FR-304)


def database_url() -> str:
    """Postgres DSN; matches docker-compose.yml unless overridden."""
    return os.environ.get("BRIER_DATABASE_URL", DEFAULT_DATABASE_URL)


def youtube_api_key() -> str:
    """YouTube Data API v3 key; empty string when not configured."""
    return os.environ.get("BRIER_YOUTUBE_API_KEY", "")


def anthropic_api_key() -> str:
    """Anthropic Messages API key; empty string when not configured.

    Required at runtime by extraction/llm.py for the stdlib-REST completion seam.
    Not used in CI: recorded fixtures + injected completion boundary are the test path.
    See docs/adr/0005-llm-extraction-via-stdlib-rest.md.
    """
    return os.environ.get("BRIER_ANTHROPIC_API_KEY", "")
