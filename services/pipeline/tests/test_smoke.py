"""Skeleton smoke tests: every module imports, contracts construct, stubs are stubs.

These are placeholders by design (DoD: `make check` passes on stubs). Real
tests arrive with each task in TASKS.md and replace nothing here — stubs that
gain implementations simply drop out of NOT_IMPLEMENTED_PROBES.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.models import Analyst, Claim, SpecificityClass
from brier_pipeline.resolution import base_rates
from brier_pipeline.resolution.prices import CoinGeckoPriceSource, FakePriceSource
from brier_pipeline.scoring import fas

FIXTURES = Path("does-not-exist-yet")


def _stub_claim() -> Claim:
    return Claim(
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        specificity_class=SpecificityClass.CONDITIONAL,
        source_offset_seconds=0,
        model_version="fake-v0",
        prompt_version="fake-v0",
        uttered_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_models_construct() -> None:
    analyst = Analyst(channel_id="UC123", display_name="Test Analyst", slug="test-analyst")
    assert analyst.status == "active"

    claim = Claim(
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        specificity_class=SpecificityClass.TARGET_DEADLINE,
        source_offset_seconds=862,
        model_version="fake-v0",
        prompt_version="fake-v0",
        uttered_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    assert claim.publishable is False  # FR-203 default: nothing publishes implicitly


# E1 stubs are implemented and have dropped out; these are the E2-E4 stubs.
# E2-T4 probes (fetch_captions, WhisperTranscriber, DeepgramTranscriber) implemented and removed.
# E3-T1 probe (llm.completion) implemented and removed — completion seam is real (ADR-0005).
NOT_IMPLEMENTED_PROBES: list[tuple[str, Any]] = [
    (
        "base_rates.base_rate (E4-T2)",
        lambda: base_rates.base_rate(_stub_claim(), FakePriceSource(FIXTURES)),
    ),
    (
        "CoinGeckoPriceSource.daily_closes (E4-T2)",
        lambda: CoinGeckoPriceSource().daily_closes(
            "BTC", datetime(2026, 1, 1, tzinfo=UTC).date(), datetime(2026, 6, 1, tzinfo=UTC).date()
        ),
    ),
]


@pytest.mark.parametrize("name,probe", NOT_IMPLEMENTED_PROBES, ids=lambda v: str(v))
def test_stubs_raise_not_implemented(name: str, probe: Any) -> None:
    """The skeleton ships zero business logic; every stub must say so loudly."""
    with pytest.raises(NotImplementedError):
        probe()


def test_methodology_constants_match_spec() -> None:
    """METHODOLOGY.md §6: k=25, ranked at n>=20, provisional clears at n>=30."""
    assert fas.SHRINKAGE_K == 25
    assert fas.MIN_RANKED_N == 20
    assert fas.PROVISIONAL_CLEARS_AT_N == 30
