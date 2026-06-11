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

from brier_pipeline.extraction.extractor import FakeExtractor
from brier_pipeline.ingestion.youtube import FakeYouTubeClient
from brier_pipeline.models import Analyst, Claim, SpecificityClass
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.scoring import fas
from brier_pipeline.transcription.storage import LocalFSStorage
from brier_pipeline.transcription.transcriber import FakeTranscriber

FIXTURES = Path("does-not-exist-yet")


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


NOT_IMPLEMENTED_PROBES: list[tuple[str, Any]] = [
    ("E1-T1 FakeExtractor", lambda: FakeExtractor(FIXTURES).detect_candidates([])),
    ("E1-T1 FakeYouTubeClient", lambda: FakeYouTubeClient(FIXTURES).fetch_captions("vid")),
    ("E1-T1 FakeTranscriber", lambda: FakeTranscriber(FIXTURES).transcribe("audio://x")),
    ("E1-T1 LocalFSStorage", lambda: LocalFSStorage(FIXTURES).get("key")),
    (
        "E1-T1 FakePriceSource",
        lambda: FakePriceSource(FIXTURES).daily_closes(
            "BTC", datetime(2026, 1, 1, tzinfo=UTC).date(), datetime(2026, 1, 2, tzinfo=UTC).date()
        ),
    ),
    ("E1-T2 composite_fas", lambda: fas.composite_fas(0.1, 0.5, 0.5, 0.5, 24, 0.5)),
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
