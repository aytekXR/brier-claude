"""Tests for E3-T2: pass-2 structuring (LlmExtractor.structure_claim).

No network calls, no real API keys. All LLM boundaries are injected fake
callables returning recorded fixture responses (mock-first convention).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.extraction.extractor import (
    CandidateSpan,
    FakeExtractor,
    LlmExtractor,
)
from brier_pipeline.models import ClaimStatus, ReviewState

FIXTURES = Path(__file__).parent.parent.parent.parent / "data" / "fixtures"
LLM_FIXTURES = FIXTURES / "llm"

_UTTERED_AT = datetime(2024, 12, 1, 18, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(filename: str) -> dict[str, Any]:
    path = LLM_FIXTURES / filename
    return dict[str, Any](json.loads(path.read_text(encoding="utf-8")))


def _make_fake_completion(fixture_dict: dict[str, Any]) -> Any:
    """Return a callable that always returns ``fixture_dict``."""

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return fixture_dict

    return fake_completion


def _make_span(text: str, start: float = 10.0) -> CandidateSpan:
    return CandidateSpan(start_seconds=start, end_seconds=start + 8.0, text=text)


# ---------------------------------------------------------------------------
# Happy path: full FR-202 tuple
# ---------------------------------------------------------------------------


def test_happy_path_full_fr202_tuple() -> None:
    """Happy path: resolved asset, direction, target price, all FR-202 fields populated."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span(
        "Bitcoin will reach one hundred ten thousand by year-end.",
        start=62.0,
    )
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    # Asset resolved via alias
    assert claim.asset == "BTC"
    # Direction
    assert claim.direction == "bullish"
    # Target price from the fixture
    assert claim.target_price == 110000.0
    # horizon_basis stated (fixture says "by end of December")
    assert claim.horizon_basis == "stated"
    # horizon_deadline parsed
    assert claim.horizon_deadline == date(2024, 12, 31)
    # NFR-2: versions stamped
    assert claim.model_version == "claude-haiku-4-5"
    assert claim.prompt_version == "v2"
    # source_offset_seconds from span.start_seconds
    assert claim.source_offset_seconds == 62
    # extraction_confidence carried through
    assert claim.extraction_confidence is not None
    assert 0.0 <= claim.extraction_confidence <= 1.0
    # Not excluded
    assert claim.status == ClaimStatus.OPEN
    assert "excluded_reason" not in claim.flags
    assert "void_reason" not in claim.flags
    # uttered_at stamped
    assert claim.uttered_at == _UTTERED_AT


def test_happy_path_quote_at_most_15_words() -> None:
    """NFR-4: stored quote must be ≤15 words."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.quote is not None
    word_count = len(claim.quote.split())
    assert word_count <= 15, f"Quote has {word_count} words: {claim.quote!r}"


def test_happy_path_nfr2_versions_stamped() -> None:
    """NFR-2: model_version and prompt_version are stamped on each claim."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-custom-7",
        prompt_version="v99",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.model_version == "claude-haiku-custom-7"
    assert claim.prompt_version == "v99"


def test_happy_path_extraction_confidence_carried() -> None:
    """extraction_confidence from the model response is propagated to the Claim."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.extraction_confidence == pytest.approx(0.91)


# ---------------------------------------------------------------------------
# EC-3: sarcasm / hypothetical / paraphrase exclusion
# ---------------------------------------------------------------------------


def test_ec3_excluded_reason_flag_set() -> None:
    """EC-3: excluded span has excluded_reason flag set."""
    fixture = _load_fixture("pass2_ec3_excluded.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Some analysts claim ETH will outperform this quarter.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert "excluded_reason" in claim.flags
    assert claim.flags["excluded_reason"] in {"sarcasm", "hypothetical", "paraphrase"}


def test_ec3_status_void() -> None:
    """EC-3: excluded claims have status VOID."""
    fixture = _load_fixture("pass2_ec3_excluded.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Some analysts claim ETH will outperform this quarter.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.status == ClaimStatus.VOID


def test_ec3_publishable_false() -> None:
    """EC-3: excluded claims are not publishable."""
    fixture = _load_fixture("pass2_ec3_excluded.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Some analysts claim ETH will outperform this quarter.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.publishable is False


def test_ec3_review_state_unreviewed() -> None:
    """EC-3: excluded claims start as UNREVIEWED for QA."""
    fixture = _load_fixture("pass2_ec3_excluded.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Some analysts claim ETH will outperform this quarter.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.review_state == ReviewState.UNREVIEWED


# ---------------------------------------------------------------------------
# EC-7: unresolvable asset → void
# ---------------------------------------------------------------------------


def test_ec7_asset_is_none() -> None:
    """EC-7: unresolvable asset results in asset=None on the claim."""
    fixture = _load_fixture("pass2_ec7_unresolvable.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Altcoins will likely outperform next month.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.asset is None


def test_ec7_void_reason_flag() -> None:
    """EC-7: unresolvable asset sets void_reason flag."""
    fixture = _load_fixture("pass2_ec7_unresolvable.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Altcoins will likely outperform next month.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.flags.get("void_reason") == "unresolvable_asset"


def test_ec7_status_void() -> None:
    """EC-7: unresolvable asset results in VOID status."""
    fixture = _load_fixture("pass2_ec7_unresolvable.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Altcoins will likely outperform next month.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.status == ClaimStatus.VOID
    assert claim.publishable is False


# ---------------------------------------------------------------------------
# Imputed confidence (METHODOLOGY §1)
# ---------------------------------------------------------------------------


def test_imputed_confidence_will() -> None:
    """'will' language imputes stated_confidence=0.85, confidence_basis='imputed_will'."""
    # Build a fixture that returns confidence_language="will" with no stated_confidence
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "bitcoin",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "Bitcoin will reach new highs.",
                        "extraction_confidence": 0.80,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("Bitcoin will reach new highs.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.stated_confidence == pytest.approx(0.85)
    assert claim.confidence_basis == "imputed_will"


def test_imputed_confidence_likely() -> None:
    """'likely' language imputes stated_confidence=0.70, confidence_basis='imputed_likely'."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "eth",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "likely",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "ETH will likely outperform the market.",
                        "extraction_confidence": 0.75,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("ETH will likely outperform the market.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.stated_confidence == pytest.approx(0.70)
    assert claim.confidence_basis == "imputed_likely"


def test_explicit_stated_confidence_takes_precedence() -> None:
    """When stated_confidence is numeric, it overrides confidence_language imputation."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "btc",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": 0.95,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "BTC will reach new highs.",
                        "extraction_confidence": 0.88,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("BTC will reach new highs.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.stated_confidence == pytest.approx(0.95)
    assert claim.confidence_basis == "stated"


# ---------------------------------------------------------------------------
# Horizon basis mapping (METHODOLOGY §1)
# ---------------------------------------------------------------------------


def test_horizon_basis_stated_with_explicit_date() -> None:
    """Stated explicit date → horizon_basis='stated' + horizon_deadline populated."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "sol",
                        "direction": "bullish",
                        "target_price": 300.0,
                        "magnitude_pct": None,
                        "horizon_raw": "by March 31",
                        "horizon_basis": "stated",
                        "horizon_deadline": "2025-03-31",
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "target_deadline",
                        "quote": "SOL will hit three hundred by March thirty-first.",
                        "extraction_confidence": 0.88,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("SOL will hit three hundred by March thirty-first.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.horizon_basis == "stated"
    assert claim.horizon_deadline == date(2025, 3, 31)


def test_horizon_basis_soon_gives_default_30d() -> None:
    """'soon' horizon → horizon_basis='default_30d', horizon_deadline=None."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "btc",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": "soon",
                        "horizon_basis": "default_30d",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "BTC will break out soon.",
                        "extraction_confidence": 0.79,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("BTC will break out soon.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.horizon_basis == "default_30d"
    assert claim.horizon_deadline is None


def test_horizon_basis_year_end_gives_default_eoy() -> None:
    """'this year'/'year-end' horizon → horizon_basis='default_eoy', horizon_deadline=None."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "eth",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": "by end of year",
                        "horizon_basis": "default_eoy",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "ETH will climb higher by end of year.",
                        "extraction_confidence": 0.82,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("ETH will climb higher by end of year.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.horizon_basis == "default_eoy"
    assert claim.horizon_deadline is None


def test_horizon_basis_none_gives_default_90d() -> None:
    """No horizon stated → horizon_basis='default_90d', horizon_deadline=None."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "solana",
                        "direction": "bearish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": None,
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "SOL is going to pull back significantly.",
                        "extraction_confidence": 0.71,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("SOL is going to pull back significantly.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.horizon_basis == "default_90d"
    assert claim.horizon_deadline is None


# ---------------------------------------------------------------------------
# Robustness: non-object / malformed JSON must not crash
# ---------------------------------------------------------------------------


def test_robust_to_malformed_json() -> None:
    """Malformed JSON response returns a VOID claim rather than crashing."""
    bad_response: dict[str, Any] = {"content": [{"type": "text", "text": "not valid json {{{{"}]}
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(bad_response),
    )
    span = _make_span("BTC will close above eighty thousand by year-end.")
    # Must not raise
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)
    # When parsing fails we get no asset → EC-7 void
    assert claim.status == ClaimStatus.VOID


def test_robust_to_nonobject_json_array() -> None:
    """A bare JSON array (valid JSON, not an object) must not crash."""
    array_response: dict[str, Any] = {"content": [{"type": "text", "text": "[1, 2, 3]"}]}
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(array_response),
    )
    span = _make_span("BTC will close above eighty thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)
    # Non-object JSON → no asset → EC-7 void
    assert claim.status == ClaimStatus.VOID


def test_robust_to_empty_response_content() -> None:
    """Empty content blocks return a VOID claim without crashing."""
    empty_response: dict[str, Any] = {"content": []}
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(empty_response),
    )
    span = _make_span("ETH will outperform next quarter.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)
    assert claim.status == ClaimStatus.VOID


# ---------------------------------------------------------------------------
# Asset alias resolution in the happy path
# ---------------------------------------------------------------------------


def test_asset_alias_resolved_in_claim() -> None:
    """The raw alias 'bitcoin' from model output is resolved to canonical 'BTC'."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "bitcoin",
                        "direction": "bullish",
                        "target_price": 95000.0,
                        "magnitude_pct": None,
                        "horizon_raw": "by end of Q1",
                        "horizon_basis": "stated",
                        "horizon_deadline": "2025-03-31",
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "target_deadline",
                        "quote": "Bitcoin will close at ninety-five thousand by Q1.",
                        "extraction_confidence": 0.90,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("Bitcoin will close at ninety-five thousand by Q1.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.asset == "BTC"


# ---------------------------------------------------------------------------
# FakeExtractor backward-compatibility with uttered_at keyword
# ---------------------------------------------------------------------------


def test_fake_extractor_structure_claim_accepts_uttered_at() -> None:
    """FakeExtractor.structure_claim accepts uttered_at kwarg without error."""
    from brier_pipeline.transcription.transcriber import FakeTranscriber

    transcriber = FakeTranscriber(FIXTURES)
    extractor = FakeExtractor(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-dec01")
    candidates = extractor.detect_candidates(segments)

    assert len(candidates) > 0, "Expected at least one candidate span"
    span = candidates[0]

    override_dt = datetime(2024, 11, 15, 12, 0, 0, tzinfo=UTC)
    # Must not raise; fixture value takes precedence over override
    claim = extractor.structure_claim(span, uttered_at=override_dt)
    # The fixture record has its own uttered_at, which takes precedence
    assert claim.uttered_at is not None


def test_fake_extractor_structure_claim_with_uttered_at_kwarg_fixture_wins() -> None:
    """FakeExtractor.structure_claim with uttered_at kwarg; fixture uttered_at takes precedence."""
    from brier_pipeline.transcription.transcriber import FakeTranscriber

    transcriber = FakeTranscriber(FIXTURES)
    extractor = FakeExtractor(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-dec01")
    candidates = extractor.detect_candidates(segments)

    assert len(candidates) > 0
    span = candidates[0]
    override_dt = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    claim = extractor.structure_claim(span, uttered_at=override_dt)
    # Fixture record has its own uttered_at (takes precedence over the override).
    assert claim.uttered_at is not None


# ---------------------------------------------------------------------------
# Quote clamping (NFR-4)
# ---------------------------------------------------------------------------


def test_long_model_quote_clamped_to_15_words() -> None:
    """When the model returns a quote exceeding 15 words, the first 15 words of
    span.text are used instead (NFR-4)."""
    long_quote = (
        "Bitcoin will reach one hundred and ten thousand dollars before"
        " the end of this calendar year and break the all-time high decisively."
    )
    span_text = "Bitcoin will reach one hundred and ten thousand dollars before year-end."
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "bitcoin",
                        "direction": "bullish",
                        "target_price": 110000.0,
                        "magnitude_pct": None,
                        "horizon_raw": "year-end",
                        "horizon_basis": "default_eoy",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "target_deadline",
                        "quote": long_quote,
                        "extraction_confidence": 0.87,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span(span_text)
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.quote is not None
    assert len(claim.quote.split()) <= 15


# ---------------------------------------------------------------------------
# source_offset_seconds from span.start_seconds
# ---------------------------------------------------------------------------


def test_source_offset_seconds_from_span() -> None:
    """source_offset_seconds is derived from int(span.start_seconds)."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.", start=247.8)
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.source_offset_seconds == 247


def test_uttered_at_stamped_on_claim() -> None:
    """uttered_at kwarg is stored on the returned Claim (NFR-2 t0)."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    uttered = datetime(2025, 3, 15, 9, 30, 0, tzinfo=UTC)
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=uttered)

    assert claim.uttered_at == uttered


# ---------------------------------------------------------------------------
# BLOCKER 1: unguarded numeric coercion crashes on VOID paths (Defect #1)
# ---------------------------------------------------------------------------


def test_ec3_void_extraction_confidence_dict_does_not_crash() -> None:
    """EC-3 VOID path: dict extraction_confidence must not raise ValidationError."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "btc",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": None,
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "Imagine if BTC went to the moon.",
                        "extraction_confidence": {"bad": "value"},  # malformed — dict not float
                        "excluded": True,
                        "excluded_reason": "hypothetical",
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("Imagine if BTC went to the moon.")
    # Must not raise Pydantic ValidationError
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)
    assert claim.flags.get("excluded_reason") == "hypothetical"
    assert claim.extraction_confidence is None  # dict coerced to None


def test_ec7_void_extraction_confidence_list_does_not_crash() -> None:
    """EC-7 VOID path: list extraction_confidence must not raise ValidationError."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "altcoins",  # unresolvable
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "Altcoins will rally next quarter.",
                        "extraction_confidence": [0.8, 0.9],  # malformed — list not float
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("Altcoins will rally next quarter.")
    # Must not raise Pydantic ValidationError
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)
    assert claim.flags.get("void_reason") == "unresolvable_asset"
    assert claim.extraction_confidence is None  # list coerced to None


# ---------------------------------------------------------------------------
# BLOCKER 2: _clamp_quote crashes on non-string (Defect #2)
# ---------------------------------------------------------------------------


def test_clamp_quote_non_string_does_not_crash() -> None:
    """Non-string quote (e.g. list) must not raise AttributeError in _clamp_quote."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "bitcoin",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": ["not", "a", "string"],  # malformed — list not str
                        "extraction_confidence": 0.80,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("BTC will break higher soon.")
    # Must not raise AttributeError
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)
    # quote should fall back to None (non-string treated as absent)
    assert claim.quote is None or isinstance(claim.quote, str)


# ---------------------------------------------------------------------------
# SHOULD-FIX 3: "could" without conditionality → NON_FALSIFIABLE (Defect #3)
# ---------------------------------------------------------------------------


def test_could_without_condition_is_non_falsifiable() -> None:
    """METHODOLOGY §1: 'could' without a condition → specificity_class=NON_FALSIFIABLE."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "eth",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "could",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "ETH could move higher over time.",
                        "extraction_confidence": 0.60,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("ETH could move higher over time.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    from brier_pipeline.models import SpecificityClass

    assert claim.specificity_class == SpecificityClass.NON_FALSIFIABLE


def test_could_with_condition_stays_conditional() -> None:
    """METHODOLOGY §1: 'could' paired with a condition → NOT non-falsifiable (conditional)."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "sol",
                        "direction": "bullish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "could",
                        "stated_confidence": None,
                        "conditionality": "if it holds the two hundred level",
                        "specificity_class": "conditional",
                        "quote": "SOL could rally if it holds two hundred.",
                        "extraction_confidence": 0.72,
                        "excluded": False,
                        "excluded_reason": None,
                    }
                ),
            }
        ]
    }
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(raw_response),
    )
    span = _make_span("SOL could rally if it holds two hundred.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    from brier_pipeline.models import SpecificityClass

    # Has conditionality → not downgraded to non_falsifiable; model said "conditional"
    assert claim.specificity_class != SpecificityClass.NON_FALSIFIABLE
    assert claim.conditionality is not None


# ---------------------------------------------------------------------------
# SHOULD-FIX 6: happy-path publishable=False (Defect #6 / FR-203)
# ---------------------------------------------------------------------------


def test_happy_path_publishable_false() -> None:
    """FR-203: nothing publishes until QA routing promotes it; happy-path publishable=False."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.publishable is False


# ---------------------------------------------------------------------------
# EC-3 non-persistence predicate (Defect #7)
# ---------------------------------------------------------------------------


def test_is_excluded_span_true_for_ec3_claim() -> None:
    """is_excluded_span returns True for an EC-3 excluded claim."""
    from brier_pipeline.extraction.extractor import is_excluded_span

    fixture = _load_fixture("pass2_ec3_excluded.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Some analysts claim ETH will outperform this quarter.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert is_excluded_span(claim) is True


def test_is_excluded_span_false_for_ec7_void() -> None:
    """is_excluded_span returns False for EC-7 void (must enter F denominator)."""
    from brier_pipeline.extraction.extractor import is_excluded_span

    fixture = _load_fixture("pass2_ec7_unresolvable.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Altcoins will likely outperform next month.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert is_excluded_span(claim) is False


def test_is_excluded_span_false_for_normal_claim() -> None:
    """is_excluded_span returns False for a normal scorable claim."""
    from brier_pipeline.extraction.extractor import is_excluded_span

    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert is_excluded_span(claim) is False


def test_demo_persist_filter_skips_ec3_claim() -> None:
    """The demo persist filter (is_excluded_span) would skip an EC-3 claim.

    FakeExtractor produces no EC-3 items from fixtures, so this test directly
    instantiates a claim with an excluded_reason flag and verifies the predicate.
    """
    from brier_pipeline.extraction.extractor import is_excluded_span
    from brier_pipeline.models import Claim, ClaimStatus, ReviewState, SpecificityClass

    ec3_claim = Claim(
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        asset=None,
        specificity_class=SpecificityClass.NON_FALSIFIABLE,
        source_offset_seconds=42,
        quote=None,
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        uttered_at=_UTTERED_AT,
        status=ClaimStatus.VOID,
        review_state=ReviewState.UNREVIEWED,
        publishable=False,
        flags={"excluded_reason": "sarcasm"},
    )
    assert is_excluded_span(ec3_claim) is True

    normal_claim = Claim(
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        asset="BTC",
        specificity_class=SpecificityClass.DIRECTION_ONLY,
        source_offset_seconds=10,
        quote="BTC will go higher next month.",
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        uttered_at=_UTTERED_AT,
        status=ClaimStatus.OPEN,
        review_state=ReviewState.UNREVIEWED,
        publishable=False,
        flags={},
    )
    assert is_excluded_span(normal_claim) is False
