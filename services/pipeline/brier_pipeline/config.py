"""Pipeline configuration. Environment-driven, no framework."""

from __future__ import annotations

import os

# 127.0.0.1 (not "localhost"): the DB is bound to the IPv4 loopback only
# (docker-compose 127.0.0.1:5432:5432). "localhost" resolves to ::1 first on
# this host, and the Node pg client does not fall back to IPv4 (psycopg does).
DEFAULT_DATABASE_URL = "postgresql://brier:brier@127.0.0.1:5432/brier"

METHODOLOGY_VERSION = "v1.1"  # bumped E4-T2 (ADR-0009): base rates from trailing history


def database_url() -> str:
    """Postgres DSN; matches docker-compose.yml unless overridden."""
    return os.environ.get("BRIER_DATABASE_URL", DEFAULT_DATABASE_URL)


def env() -> str:
    """Deployment environment: 'dev' (default), 'ci', or 'production'.

    Overridable via BRIER_ENV. CI/dev leave it unset, so the mock-first fakes
    stay the default path. Production hosts MUST set BRIER_ENV=production so the
    real-adapter guards (e.g. the price-source and transcriber seams) refuse to
    silently fall back to fixtures.
    """
    return os.environ.get("BRIER_ENV", "dev")


def is_production() -> bool:
    """True when BRIER_ENV=production (case-insensitive)."""
    return env().strip().lower() == "production"


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


def extraction_model() -> str:
    """Anthropic model id for LLM extraction (pass-1 + pass-2), Haiku-class per E3-T1.

    Single source of truth for the extraction model so the (gated) `extract`
    handler constructs ``LlmExtractor(model_version=config.extraction_model(), …)``
    rather than hard-coding a string. Default is the current Haiku model (cheap,
    fast, structured-output capable — the right tier for FR-201/FR-202 detection +
    structuring). Overridable via BRIER_EXTRACTION_MODEL. The fixture FakeExtractor
    stamps ``model_version='fixture-replay'`` and never reads this (CI path).
    """
    return os.environ.get("BRIER_EXTRACTION_MODEL", "claude-haiku-4-5-20251001")


def deepgram_api_key() -> str:
    """Deepgram API key for incremental transcription; empty when not configured.

    Used only by DeepgramTranscriber at runtime (incremental uploads, PRD §18).
    CI/dev use the fixture-backed FakeTranscriber; get_transcriber() selects the
    real adapter only when this key is set. No SDK dependency (stdlib REST).
    """
    return os.environ.get("BRIER_DEEPGRAM_API_KEY", "")


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


def transcription_monthly_cap_usd() -> float:
    """Hard monthly spend cap for transcription services in USD (NFR-5).

    PRD §18 backfill envelope. Overridable via BRIER_TRANSCRIPTION_MONTHLY_CAP_USD.
    The spend engine blocks further metered calls once this cap is reached.
    """
    return float(os.environ.get("BRIER_TRANSCRIPTION_MONTHLY_CAP_USD", "700.0"))


def llm_monthly_cap_usd() -> float:
    """Hard monthly spend cap for LLM services in USD (NFR-5).

    PRD §18 LLM envelope. Overridable via BRIER_LLM_MONTHLY_CAP_USD.
    The spend engine blocks further metered calls once this cap is reached.
    """
    return float(os.environ.get("BRIER_LLM_MONTHLY_CAP_USD", "300.0"))


def spend_alert_fraction() -> float:
    """Fraction of monthly cap that triggers a cost_threshold alert (NFR-5).

    Default 0.70 (70% alert). Overridable via BRIER_SPEND_ALERT_FRACTION.
    When month-to-date spend crosses cap * fraction, an alert is raised.
    """
    return float(os.environ.get("BRIER_SPEND_ALERT_FRACTION", "0.70"))


def monthly_spend_cap_usd(category: str) -> float:
    """Dispatch to per-category monthly cap (NFR-5).

    Args:
        category: 'transcription' or 'llm'.

    Returns:
        Monthly cap in USD for the given category.

    Raises:
        ValueError: For unknown categories.
    """
    if category == "transcription":
        return transcription_monthly_cap_usd()
    if category == "llm":
        return llm_monthly_cap_usd()
    raise ValueError(f"Unknown spend category: {category!r}. Expected 'transcription' or 'llm'.")


def better_stack_token() -> str:
    """Better Stack ingest token; empty string when not configured (ADR-0014).

    Used only by BetterStackAlerter at runtime. CI/tests use FakeAlerter.
    Raises RuntimeError when absent and the real alerter is instantiated.
    See docs/adr/0014-monitoring-alerting-via-stdlib-rest.md.
    """
    return os.environ.get("BRIER_BETTER_STACK_TOKEN", "")


def sentry_dsn() -> str:
    """Sentry DSN; empty string when not configured.

    Used only by the Sentry error-capture path at runtime (PRD §18).
    CI/tests do not require this value.
    See docs/adr/0014-monitoring-alerting-via-stdlib-rest.md.
    """
    return os.environ.get("BRIER_SENTRY_DSN", "")
