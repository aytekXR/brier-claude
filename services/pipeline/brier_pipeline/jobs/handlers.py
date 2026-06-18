"""Scheduled-ops job handlers: resolve_claims + score_analysts (runbook §7).

These two stages add NO ADR-gated dependency, so they are wired now: the
worker's run loop can process the scheduled `resolve_claims` and
`score_analysts` jobs.  They run on the fixture-backed FakePriceSource in CI/dev
and on CoinGeckoPriceSource (ADR-0009, stdlib urllib, no new dep) when
BRIER_COINGECKO_API_KEY is set.

NOT wired here (deliberately deferred to the human-gated backfill activation):
the `transcribe` and `extract` handlers.  Their real adapters need the still
PROPOSED heavy-dependency ADRs — 0003 faster-whisper, 0004 boto3/R2, 0008
sentence-transformers — plus the LLM key (0005).  Registering a fake-by-default
transcribe handler now would risk a silent fixture-in-prod path, so it waits for
ADR approval (docs/RUNBOOK-PRODUCTION.md §3/§5, EX-dept.md).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import psycopg

from brier_pipeline.config import coingecko_api_key
from brier_pipeline.jobs import worker
from brier_pipeline.resolution.prices import (
    CoinGeckoPriceSource,
    FakePriceSource,
    PriceSource,
)
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.scoring.fas import run_score_pass

logger = logging.getLogger(__name__)

# Repo-root/data/fixtures — the same canonical path run_score_pass derives when
# prices is None (services/pipeline/brier_pipeline/jobs -> repo root is 4 up).
_FIXTURES_DIR = Path(__file__).resolve().parents[4] / "data" / "fixtures"


def _get_price_source() -> PriceSource:
    """Return the configured price source: CoinGecko when keyed, else Fake.

    Mirrors get_alerter (E6): the fake is the CI/dev path; the real adapter
    activates only when BRIER_COINGECKO_API_KEY is set (ADR-0009, no new dep).
    Logs a warning on fallback so a misconfigured production host is caught
    rather than silently scoring against fixtures.
    """
    if coingecko_api_key():
        return CoinGeckoPriceSource()
    logger.warning(
        "No BRIER_COINGECKO_API_KEY set; resolve_claims/score_analysts are using "
        "FakePriceSource (fixtures). This is the CI/dev path — production must set the key."
    )
    return FakePriceSource(_FIXTURES_DIR)


def resolve_claims_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """`resolve_claims` job: append resolutions for every due open claim.

    The worker (process_one) owns the transaction; resolve_open_claims with conn
    set does not commit (NFR-3 append-only path).  payload is unused.
    """
    resolve_open_claims(_get_price_source(), conn=conn)


def score_analysts_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """`score_analysts` job: append a new nightly score_run + scores.

    Appends to the append-only ledger (a fresh score_run, NFR-3); run_score_pass
    with conn set does not commit.  payload is unused (the scheduled pass is
    always 'nightly'; methodology bumps use recompute_all separately).
    """
    run_score_pass("nightly", conn=conn, prices=_get_price_source())


# Self-register at import, matching the poller/deletion/freshness/sla/erasure
# convention.  bootstrap_handlers() also registers these explicitly so the
# production worker is deterministic even after a test clear_handlers().
worker.register_handler("resolve_claims", resolve_claims_handler)
worker.register_handler("score_analysts", score_analysts_handler)
