"""Pipeline configuration. Environment-driven, no framework."""

from __future__ import annotations

import os

DEFAULT_DATABASE_URL = "postgresql://brier:brier@localhost:5432/brier"

METHODOLOGY_VERSION = "v1.1"  # bumped E4-T2 (ADR-0009): base rates from trailing history


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


def coingecko_api_key() -> str:
    """CoinGecko API key; empty string when not configured.

    Used only by CoinGeckoPriceSource at runtime (ADR-0009).
    Not used in CI: recorded fixtures + injected http_get are the test path.
    See docs/adr/0009-base-rates-from-trailing-history.md.
    """
    return os.environ.get("BRIER_COINGECKO_API_KEY", "")


def label_studio_url() -> str:
    """Label Studio base URL; empty string when not configured.

    Live QA queue seam (PRD §21). Used only by LabelStudioQueue at runtime;
    CI/tests use InMemoryReviewQueue and never touch this value.
    """
    return os.environ.get("BRIER_LABEL_STUDIO_URL", "")


def label_studio_token() -> str:
    """Label Studio API token; empty string when not configured.

    Live QA queue seam (PRD §21). Used only by LabelStudioQueue at runtime;
    CI/tests use InMemoryReviewQueue and never touch this value.
    """
    return os.environ.get("BRIER_LABEL_STUDIO_TOKEN", "")
