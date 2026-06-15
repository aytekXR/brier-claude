"""Tests for E3-T4: non-falsifiable classifier (FR-204).

No network calls, no DB dependency. The FR-204 invariant test uses fas.py's
public pure functions to prove end-to-end without modifying scoring.

FR-204: non-falsifiable statements count toward the falsifiability ratio
(F denominator) but never score (DS/C/K exclude them).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.extraction.extractor import (
    CandidateSpan,
    LlmExtractor,
    classify_non_falsifiable,
    is_excluded_span,
)
from brier_pipeline.models import (
    Claim,
    ClaimStatus,
    Resolution,
    ReviewState,
    SpecificityClass,
)
from brier_pipeline.scoring.fas import (
    directional_skill,
    falsifiability,
    score_analyst_pure,
)

FIXTURES = Path(__file__).parent.parent.parent.parent / "data" / "fixtures"
LLM_FIXTURES = FIXTURES / "llm"

_UTTERED_AT = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_completion(fixture_dict: dict[str, Any]) -> Any:
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
    return CandidateSpan(start_seconds=start, end_seconds=start + 5.0, text=text)


def _load_fixture(filename: str) -> dict[str, Any]:
    path = LLM_FIXTURES / filename
    return dict[str, Any](json.loads(path.read_text(encoding="utf-8")))


def _make_resolution(claim_id: int, outcome: float) -> Resolution:
    return Resolution(
        id=claim_id,
        claim_id=claim_id,
        outcome=outcome,
        resolved_at=datetime(2025, 6, 1, tzinfo=UTC),
        rule_id="directional_at_horizon.v0",
        rationale="fixture resolution",
        price_citation={"source": "fixture"},
        methodology_version="v1.0",
    )


def _make_direction_only_claim(
    analyst_id: int = 1,
    claim_id: int = 1,
    outcome: float = 1.0,
    stated_confidence: float | None = 0.75,
) -> tuple[Claim, Resolution, float]:
    claim = Claim(
        id=claim_id,
        analyst_id=analyst_id,
        video_id=1,
        transcript_id=1,
        asset="BTC",
        direction="bullish",
        specificity_class=SpecificityClass.DIRECTION_ONLY,
        source_offset_seconds=10,
        quote="BTC will go higher next quarter.",
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        uttered_at=_UTTERED_AT,
        stated_confidence=stated_confidence,
        confidence_basis="imputed_likely" if stated_confidence == 0.70 else "stated",
        status=ClaimStatus.RESOLVED,
        review_state=ReviewState.APPROVED,
        publishable=True,
        flags={"fixture_base_rate": 0.5},
        p0_price=70000.0,
    )
    return (claim, _make_resolution(claim_id, outcome), 0.5)


def _make_non_falsifiable_claim(
    analyst_id: int = 1,
    claim_id: int = 99,
) -> Claim:
    """A non_falsifiable claim — the analyst's own vague statement, persisted but never scored."""
    return Claim(
        id=claim_id,
        analyst_id=analyst_id,
        video_id=1,
        transcript_id=1,
        asset="ETH",
        direction="bullish",
        specificity_class=SpecificityClass.NON_FALSIFIABLE,
        source_offset_seconds=20,
        quote="ETH could go up at some point.",
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        uttered_at=_UTTERED_AT,
        stated_confidence=None,
        status=ClaimStatus.OPEN,
        review_state=ReviewState.UNREVIEWED,
        publishable=False,
        flags={},
    )


# ---------------------------------------------------------------------------
# Unit tests: classify_non_falsifiable — non-falsifiable inputs → True
# ---------------------------------------------------------------------------


def test_rule1_bare_could_is_non_falsifiable() -> None:
    """METHODOLOGY §1: 'could' with no condition → non-falsifiable."""
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction="bullish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="could",
            conditionality=None,
            quote="BTC could go higher.",
        )
        is True
    )


def test_rule1_bare_might_is_non_falsifiable() -> None:
    """'might' without a condition is non-falsifiable per Rule 1."""
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction="bearish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="might",
            conditionality=None,
            quote="ETH might drop.",
        )
        is True
    )


def test_rule1_bare_maybe_is_non_falsifiable() -> None:
    """'maybe' without a condition is non-falsifiable per Rule 1."""
    assert (
        classify_non_falsifiable(
            asset="SOL",
            direction="bullish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="maybe",
            conditionality=None,
            quote="SOL maybe recovers.",
        )
        is True
    )


def test_rule2_open_ended_eventually_no_direction() -> None:
    """Rule 2: open-ended 'eventually' + default_90d + no direction/target → non-falsifiable."""
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction=None,
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language=None,
            conditionality=None,
            quote="BTC will recover eventually.",
        )
        is True
    )


def test_rule2_at_some_point_no_direction() -> None:
    """Rule 2: 'at some point' phrase + no resolvable tuple → non-falsifiable."""
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction=None,
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language=None,
            conditionality=None,
            quote="ETH will rise at some point.",
        )
        is True
    )


def test_rule2_long_term_no_direction() -> None:
    """Rule 2: 'long term' horizon phrase with no direction → non-falsifiable."""
    assert (
        classify_non_falsifiable(
            asset="SOL",
            direction=None,
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language=None,
            conditionality=None,
            quote="SOL is a long term hold.",
        )
        is True
    )


def test_rule3_pure_sentiment_no_asset_direction_target() -> None:
    """Rule 3: no asset, no direction, no target → pure sentiment assertion."""
    assert (
        classify_non_falsifiable(
            asset=None,
            direction=None,
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language=None,
            conditionality=None,
            quote="This changes everything for crypto.",
        )
        is True
    )


def test_rule3_no_asset_no_direction_no_target() -> None:
    """Rule 3: vague sentiment assertion with no falsifiable tuple."""
    assert (
        classify_non_falsifiable(
            asset=None,
            direction=None,
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis=None,
            confidence_language="will",
            conditionality=None,
            quote="Blockchain will transform finance.",
        )
        is True
    )


# ---------------------------------------------------------------------------
# Unit tests: classify_non_falsifiable — falsifiable inputs → False
# ---------------------------------------------------------------------------


def test_target_plus_deadline_is_falsifiable() -> None:
    """Explicit target + stated deadline → falsifiable (returns False)."""
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction="bullish",
            target_price=110000.0,
            magnitude_pct=None,
            horizon_deadline="2025-12-31",
            horizon_basis="stated",
            confidence_language="will",
            conditionality=None,
            quote="BTC will reach one hundred ten thousand by year-end.",
        )
        is False
    )


def test_direction_plus_horizon_is_falsifiable() -> None:
    """Direction + 30-day default horizon is falsifiable (returns False)."""
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction="bearish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_30d",
            confidence_language="will",
            conditionality=None,
            quote="ETH will drop over the next month.",
        )
        is False
    )


def test_direction_plus_eoy_horizon_is_falsifiable() -> None:
    """Direction + end-of-year default horizon is falsifiable (returns False)."""
    assert (
        classify_non_falsifiable(
            asset="SOL",
            direction="bullish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_eoy",
            confidence_language="likely",
            conditionality=None,
            quote="SOL will outperform by year-end.",
        )
        is False
    )


def test_could_with_condition_is_falsifiable() -> None:
    """METHODOLOGY §1: 'could' paired with a trigger condition → falsifiable."""
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction="bullish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="could",
            conditionality="if it breaks above eighty thousand",
            quote="BTC could rally if it breaks eighty thousand.",
        )
        is False
    )


def test_might_with_condition_is_falsifiable() -> None:
    """'might' paired with a condition (activating clause) → falsifiable."""
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction="bearish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="might",
            conditionality="if the market corrects further",
            quote="ETH might fall if market corrects further.",
        )
        is False
    )


def test_rule2_with_target_even_open_ended_horizon_falsifiable() -> None:
    """Rule 2 does not fire when there is an explicit target price, even without a deadline."""
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction="bullish",
            target_price=100000.0,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="will",
            conditionality=None,
            quote="BTC will reach one hundred thousand eventually.",
        )
        is False
    )


def test_rule2_with_direction_only_no_open_ended_phrase_falsifiable() -> None:
    """Rule 2 does not fire when direction is set and quote has no open-ended phrase."""
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction="bullish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language="will",
            conditionality=None,
            quote="ETH will go higher next quarter.",
        )
        is False
    )


# ---------------------------------------------------------------------------
# structure_claim integration: non-falsifiable fixture
# ---------------------------------------------------------------------------


def test_structure_claim_non_falsifiable_fixture() -> None:
    """LlmExtractor.structure_claim with a recorded non-falsifiable pass-2 response
    → specificity_class == NON_FALSIFIABLE."""
    fixture = _load_fixture("pass2_non_falsifiable.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("BTC could go higher at some point.", start=25.0)
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.specificity_class == SpecificityClass.NON_FALSIFIABLE


def test_structure_claim_non_falsifiable_not_ec3_excluded() -> None:
    """Non-falsifiable claims are NOT EC-3-excluded; they persist (enter F denominator)."""
    fixture = _load_fixture("pass2_non_falsifiable.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("BTC could go higher at some point.", start=25.0)
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    # is_excluded_span must return False: these are the analyst's own statements
    # and must enter the F denominator (METHODOLOGY §6, FR-204).
    assert is_excluded_span(claim) is False
    assert "excluded_reason" not in claim.flags


def test_structure_claim_genuine_prediction_not_misclassified() -> None:
    """A genuine prediction with explicit target+deadline must NOT be non-falsifiable."""
    fixture = _load_fixture("pass2_happy_path.json")
    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v2",
        completion=_make_fake_completion(fixture),
    )
    span = _make_span("Bitcoin will reach one hundred ten thousand by year-end.", start=62.0)
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.specificity_class != SpecificityClass.NON_FALSIFIABLE
    assert claim.specificity_class == SpecificityClass.TARGET_DEADLINE


def test_structure_claim_could_with_no_condition_is_non_falsifiable() -> None:
    """Inline: 'could' + no condition via LlmExtractor → NON_FALSIFIABLE (Rule 1)."""
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

    assert claim.specificity_class == SpecificityClass.NON_FALSIFIABLE


def test_structure_claim_might_without_condition_is_non_falsifiable() -> None:
    """'might' + no condition via LlmExtractor → NON_FALSIFIABLE (Rule 1 generalised)."""
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "btc",
                        "direction": "bearish",
                        "target_price": None,
                        "magnitude_pct": None,
                        "horizon_raw": None,
                        "horizon_basis": "default_90d",
                        "horizon_deadline": None,
                        "confidence_language": "might",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "direction_only",
                        "quote": "BTC might drop from here.",
                        "extraction_confidence": 0.58,
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
    span = _make_span("BTC might drop from here.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    assert claim.specificity_class == SpecificityClass.NON_FALSIFIABLE


# ---------------------------------------------------------------------------
# FR-204 invariant test using fas.py's EXISTING public functions (no modification)
#
# Construct a small pure in-memory set of resolved claims including a
# NON_FALSIFIABLE one and verify:
#   1. The non_falsifiable claim is COUNTED in the falsifiability denominator.
#   2. The non_falsifiable claim is EXCLUDED from the scored numerator (n).
#   3. directional_skill() excludes non_falsifiable from DS computation.
# ---------------------------------------------------------------------------


def test_fr204_non_falsifiable_counted_in_f_denominator_not_in_scored_numerator() -> None:
    """FR-204 invariant: non_falsifiable claim counts in F denominator, never scores.

    Proof via fas.py's pure public functions (score_analyst_pure, falsifiability,
    directional_skill) without any modification to scoring code.

    Setup:
      - Analyst has 2 resolved direction_only claims (the scorable set, n=2).
      - Analyst also has 1 NON_FALSIFIABLE claim (NOT in the resolved set — it can
        never resolve — but it IS a prediction-like statement counted in the
        total_prediction_like_count denominator).
      - total_prediction_like_count = 3 (2 scorable + 1 non_falsifiable).
      - Expected F = 2 / 3 ≈ 0.667 (scored numerator = 2, denominator = 3).
      - If non_falsifiable were wrongly included in DS, it would alter the score.
    """
    resolved_1 = _make_direction_only_claim(analyst_id=1, claim_id=1, outcome=1.0)
    resolved_2 = _make_direction_only_claim(analyst_id=1, claim_id=2, outcome=0.0)

    # The non_falsifiable claim is the analyst's own vague statement.
    # It has no resolution (can't be scored), so it's NOT in the resolved list.
    # But it IS counted in the total_prediction_like_count.
    nf_claim = _make_non_falsifiable_claim(analyst_id=1, claim_id=99)
    assert nf_claim.specificity_class == SpecificityClass.NON_FALSIFIABLE
    assert is_excluded_span(nf_claim) is False  # it persists and counts in denominator

    resolved_claims = [resolved_1, resolved_2]
    # Total prediction-like = 2 resolved scorable + 1 non-falsifiable = 3
    total_prediction_like_count = 3

    components = score_analyst_pure(
        analyst_id=1,
        resolved=resolved_claims,
        prediction_like_count=total_prediction_like_count,
    )

    # n: only scorable claims count (non_falsifiable excluded from scored numerator)
    assert components.n == 2, f"Expected n=2 scorable claims, got {components.n}"

    # F = scored / total_prediction_like = 2 / 3 ≈ 0.667
    expected_f = falsifiability(scored_count=2, prediction_like_count=3)
    assert components.f == pytest.approx(expected_f, rel=1e-6)
    assert components.f == pytest.approx(2 / 3, rel=1e-4)

    # DS is computed only over scorable claims (the two direction_only ones).
    # One hit (outcome=1.0) and one miss (outcome=0.0) with base_rate=0.5 each.
    # DS = (1*(1.0-0.5) + 1*(0.0-0.5)) / (1+1) = 0.0
    expected_ds = directional_skill(resolved_claims)
    assert components.ds == pytest.approx(expected_ds, rel=1e-6)
    assert components.ds == pytest.approx(0.0, abs=1e-9)


def test_fr204_f_denominator_includes_non_falsifiable_count() -> None:
    """FR-204: adding more non_falsifiable claims lowers F, proving they count in denominator."""
    # 2 scorable claims, 8 non-falsifiable → F = 2/10 = 0.2
    resolved_1 = _make_direction_only_claim(analyst_id=2, claim_id=10, outcome=1.0)
    resolved_2 = _make_direction_only_claim(analyst_id=2, claim_id=11, outcome=1.0)

    total_prediction_like_count = 10  # 2 scored + 8 non-falsifiable

    components = score_analyst_pure(
        analyst_id=2,
        resolved=[resolved_1, resolved_2],
        prediction_like_count=total_prediction_like_count,
    )

    assert components.n == 2
    assert components.f == pytest.approx(2 / 10, rel=1e-4)


def test_fr204_non_falsifiable_does_not_enter_ds() -> None:
    """FR-204: a non_falsifiable tuple in resolved list is excluded from directional_skill."""
    # Build a tuple with a non_falsifiable claim as if it were passed in (edge-case guard):
    nf_claim = _make_non_falsifiable_claim(analyst_id=3, claim_id=200)
    nf_resolution = _make_resolution(200, outcome=1.0)
    nf_tuple: tuple[Claim, Resolution, float] = (nf_claim, nf_resolution, 0.5)

    # Normal claim for comparison
    normal_tuple = _make_direction_only_claim(analyst_id=3, claim_id=201, outcome=1.0)

    # DS computed only over the normal claim (non_falsifiable excluded by fas.py)
    ds_with_nf = directional_skill([normal_tuple, nf_tuple])
    ds_without_nf = directional_skill([normal_tuple])

    # DS must be identical regardless of the non_falsifiable claim's presence
    assert ds_with_nf == pytest.approx(ds_without_nf, rel=1e-9)


def test_fr204_non_falsifiable_persists_not_ec3_excluded() -> None:
    """FR-204: non_falsifiable claim has is_excluded_span==False (persists to DB, enters F denom).

    This tests the contract stated in is_excluded_span's docstring:
      - non_falsifiable → is_excluded_span == False → insert (enters F denominator)
    """
    nf_claim = _make_non_falsifiable_claim(analyst_id=4, claim_id=300)
    assert is_excluded_span(nf_claim) is False


def test_fr204_fas_score_reflects_lower_f_with_non_falsifiable() -> None:
    """FR-204 end-to-end: having non_falsifiable claims lowers F component of FAS.

    Analyst A: 2 scorable / 2 total → F = 1.0
    Analyst B: 2 scorable / 4 total (2 non-falsifiable) → F = 0.5
    Analyst B's FAS is lower due to worse falsifiability, all else equal.
    """
    # Analyst A — all claims are scorable
    comp_a = score_analyst_pure(
        analyst_id=10,
        resolved=[
            _make_direction_only_claim(analyst_id=10, claim_id=1, outcome=1.0),
            _make_direction_only_claim(analyst_id=10, claim_id=2, outcome=1.0),
        ],
        prediction_like_count=2,
    )

    # Analyst B — same scorable claims but 2 extra non_falsifiable in denominator
    comp_b = score_analyst_pure(
        analyst_id=11,
        resolved=[
            _make_direction_only_claim(analyst_id=11, claim_id=3, outcome=1.0),
            _make_direction_only_claim(analyst_id=11, claim_id=4, outcome=1.0),
        ],
        prediction_like_count=4,
    )

    assert comp_a.f == pytest.approx(1.0, rel=1e-4)
    assert comp_b.f == pytest.approx(0.5, rel=1e-4)
    # n and DS are identical (same scorable structure)
    assert comp_a.n == comp_b.n
    assert comp_a.ds == pytest.approx(comp_b.ds, rel=1e-6)
    # F is lower for B because of the non_falsifiable count
    assert comp_b.f < comp_a.f


# ---------------------------------------------------------------------------
# False-positive guard tests (ADR-0007 blocker fix — Rule 0 concrete override)
# ---------------------------------------------------------------------------


def test_rule0_target_price_and_deadline_with_might_is_falsifiable() -> None:
    """ADR-0007 Rule 0: target_price + horizon_deadline overrides 'might' → falsifiable.

    This is the scoring-integrity blocker: analysts must not be able to dodge
    scoring by hedging a concrete prediction. 'BTC might hit $100k by Dec 31'
    is a resolvable commitment that resolves on the stated date.
    """
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction="bullish",
            target_price=100000.0,
            magnitude_pct=None,
            horizon_deadline="2025-12-31",
            horizon_basis="stated",
            confidence_language="might",
            conditionality=None,
            quote="BTC might hit hundred thousand by year-end.",
        )
        is False
    )


def test_rule0_magnitude_with_default_horizon_and_might_is_falsifiable() -> None:
    """ADR-0007 Rule 0: magnitude_pct present → concrete override, falsifiable even with 'might'."""
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction="bullish",
            target_price=None,
            magnitude_pct=40.0,
            horizon_deadline=None,
            horizon_basis="default_30d",
            confidence_language="might",
            conditionality=None,
            quote="ETH might gain forty percent this month.",
        )
        is False
    )


def test_rule0_could_plus_target_and_stated_deadline_is_falsifiable() -> None:
    """ADR-0007 Rule 0: 'could' + target_price + horizon_deadline → falsifiable (not Rule 1)."""
    assert (
        classify_non_falsifiable(
            asset="SOL",
            direction="bullish",
            target_price=250.0,
            magnitude_pct=None,
            horizon_deadline="2025-06-30",
            horizon_basis="stated",
            confidence_language="could",
            conditionality=None,
            quote="SOL could reach two fifty by June end.",
        )
        is False
    )


# ---------------------------------------------------------------------------
# Rule 3 broadened: no-signal fires regardless of asset being named
# ---------------------------------------------------------------------------


def test_rule3_btc_named_but_no_direction_is_non_falsifiable() -> None:
    """Rule 3: asset named but direction=None → sentiment, non-falsifiable.

    'BTC is the future' has a named asset but no direction to resolve.
    The old Rule 3 required asset=None; the new Rule 3 fires on direction=None alone.
    """
    assert (
        classify_non_falsifiable(
            asset="BTC",
            direction=None,
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis="default_90d",
            confidence_language=None,
            conditionality=None,
            quote="BTC is the future of money.",
        )
        is True
    )


# ---------------------------------------------------------------------------
# Rule 2 horizon_basis=None gap fix
# ---------------------------------------------------------------------------


def test_rule2_fires_when_horizon_basis_none_and_open_ended_phrase() -> None:
    """Rule 2: horizon_basis=None (not even default_90d) + 'eventually' → non-falsifiable.

    The old Rule 2 required horizon_basis == 'default_90d' explicitly, so when
    the model returned null horizon_basis the rule would not fire even with an
    open-ended phrase. This tests the fix: None basis also triggers.
    """
    assert (
        classify_non_falsifiable(
            asset="ETH",
            direction="bullish",
            target_price=None,
            magnitude_pct=None,
            horizon_deadline=None,
            horizon_basis=None,
            confidence_language=None,
            conditionality=None,
            quote="ETH will rise eventually.",
        )
        is True
    )


# ---------------------------------------------------------------------------
# Two-way specificity_class integration: model mislabels non_falsifiable → corrected
# ---------------------------------------------------------------------------


def test_two_way_correction_model_non_falsifiable_but_tuple_concrete() -> None:
    """ADR-0007 two-way correction: model returns specificity_class=non_falsifiable
    but the tuple has target_price + horizon_deadline → classifier says False →
    persisted claim must be TARGET_DEADLINE, not non_falsifiable.
    """
    from brier_pipeline.models import SpecificityClass

    # Model returns non_falsifiable but the tuple is clearly a target+deadline claim.
    raw_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "asset": "btc",
                        "direction": "bullish",
                        "target_price": 95000,
                        "magnitude_pct": None,
                        "horizon_raw": "by end of March",
                        "horizon_basis": "stated",
                        "horizon_deadline": "2025-03-31",
                        "confidence_language": "will",
                        "stated_confidence": None,
                        "conditionality": None,
                        "specificity_class": "non_falsifiable",
                        "quote": "BTC will hit ninety five thousand by March.",
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
    span = _make_span("BTC will hit ninety five thousand by March.")
    claim = extractor.structure_claim(span, uttered_at=_UTTERED_AT)

    # Classifier says falsifiable (target + deadline present) →
    # model's non_falsifiable label must be overridden to TARGET_DEADLINE.
    assert claim.specificity_class == SpecificityClass.TARGET_DEADLINE, (
        f"Expected TARGET_DEADLINE after two-way correction, got {claim.specificity_class}"
    )
