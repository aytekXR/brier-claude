"""E1-T2: FAS scoring engine tests.

Two categories:
  1. Pure (no DB): synthesise Analyst A and B from the worked examples in
     METHODOLOGY.md §8 and assert the required bounds and ordering.
  2. DB (db_conn fixture, rolled back): run_score_pass writes one score_runs
     row + per-analyst scores rows tagged v1.0; append-only enforcement.

Worked-example requirements (binding per METHODOLOGY.md §8):
  - FAS_A in [45, 60]
  - FAS_B in [60, 80]
  - FAS_B > FAS_A  (B outranks A despite lower raw hit rate)
  - B is provisional (20 <= 24 < 30) and ranked
  - A is ranked and NOT provisional (n=60 >= 30)
  - An n=19 analyst is NOT ranked
  - An n=30 analyst's provisional flag clears
  - SHRINKAGE_K == 25
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any, Literal

import psycopg
import pytest

from brier_pipeline.models import (
    Claim,
    ClaimStatus,
    Resolution,
    ReviewState,
    SpecificityClass,
)
from brier_pipeline.scoring.fas import (
    SHRINKAGE_K,
    AnalystComponents,
    _norm_ds,
    calibration,
    claim_weight,
    composite_fas,
    consistency,
    directional_skill,
    falsifiability,
    run_score_pass,
    score_analyst_pure,
)

# ---------------------------------------------------------------------------
# Helpers for building synthetic claims / resolutions
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    claim_id: int,
    analyst_id: int,
    specificity_class: SpecificityClass,
    uttered_at: datetime,
    stated_confidence: float | None = None,
    target_price: float | None = None,
    p0_price: float | None = None,
    horizon_deadline: date | None = None,
    direction: Literal["bullish", "bearish"] | None = "bullish",
    magnitude_pct: float | None = None,
) -> Claim:
    return Claim(
        id=claim_id,
        analyst_id=analyst_id,
        video_id=1,
        transcript_id=1,
        asset="BTC",
        direction=direction,
        target_price=target_price,
        magnitude_pct=magnitude_pct,
        horizon_deadline=horizon_deadline or date(2025, 3, 31),
        horizon_basis="stated",
        stated_confidence=stated_confidence,
        confidence_basis="stated" if stated_confidence is not None else None,
        conditionality=None,
        specificity_class=specificity_class,
        source_offset_seconds=0,
        quote=None,
        uttered_at=uttered_at,
        p0_price=p0_price,
        extraction_confidence=None,
        model_version="test-v0",
        prompt_version="test-v0",
        reviewer_id=None,
        review_state=ReviewState.APPROVED,
        publishable=True,
        status=ClaimStatus.RESOLVED,
        flags={},
    )


def _make_resolution(claim_id: int, outcome: float) -> Resolution:
    return Resolution(
        id=claim_id,
        claim_id=claim_id,
        outcome=outcome,
        resolved_at=datetime(2025, 4, 1, tzinfo=UTC),
        rule_id="test",
        rationale="test resolution",
        price_citation={},
        methodology_version="v1.0",
        supersedes_resolution_id=None,
    )


def _uttered(day_offset: int, analyst_id: int = 1) -> datetime:
    """Return a UTC datetime spread across different weeks to avoid spam grouping.

    Each claim is 7 days apart so each lands in its own ISO week, preventing
    spam-damping from reducing weights in the fixture.
    """
    from datetime import timedelta

    # analyst_id is accepted for call-site symmetry (multiple analysts use this)
    _ = analyst_id
    return datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(days=day_offset * 7)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _spread_outcomes(total: int, n_hits: int) -> list[float]:
    """Return a list of 'total' outcomes with 'n_hits' evenly spread.

    Hits and misses are interleaved uniformly (not bunched at the start) so
    that rolling-window DS values are stable and K is not artificially driven
    to zero by a hits-then-misses ordering artifact.
    """
    n_miss = total - n_hits
    if n_miss <= 0:
        return [1.0] * total
    # Spread misses at evenly spaced integer positions
    miss_positions: set[int] = {int(round(j * total / n_miss)) for j in range(n_miss)}
    return [0.0 if i in miss_positions else 1.0 for i in range(total)]


# ---------------------------------------------------------------------------
# Build Analyst A fixture
#
# Profile (per METHODOLOGY.md §8 "Hype Caller"):
#   - 60 resolved direction_only claims
#   - 41 hits (HIT), 19 misses (MISS) → raw hit rate ≈ 68%
#   - All base_rate = 0.61 → DS ≈ 0.073
#   - All stated_confidence = 0.9 → Brier ≈ 0.27 → C = 0 (overconfident)
#   - 60 scored / 240 prediction-like → F = 0.25
#   - Expected FAS in [45, 60]
#
# Outcomes are spread evenly across the 60 claims so that rolling-window
# DS values are near-constant → K ≈ 0.86 (high, not zero).
# ---------------------------------------------------------------------------

ANALYST_A_ID = 1


def _build_analyst_a() -> tuple[list[tuple[Claim, Resolution, float]], int]:
    """Return (resolved_triples, prediction_like_count)."""
    triples: list[tuple[Claim, Resolution, float]] = []
    n = 60
    hits = 41  # 41/60 ≈ 68.3%
    base_rate_a = 0.61
    conf_a = 0.9

    outcomes = _spread_outcomes(n, hits)

    for i in range(n):
        uttered = _uttered(i, ANALYST_A_ID)
        claim = _make_claim(
            claim_id=i + 1,
            analyst_id=ANALYST_A_ID,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            uttered_at=uttered,
            stated_confidence=conf_a,
        )
        outcome = outcomes[i]
        resolution = _make_resolution(i + 1, outcome)
        triples.append((claim, resolution, base_rate_a))

    # F = 60 / 240 = 0.25
    prediction_like_count = 240
    return triples, prediction_like_count


# ---------------------------------------------------------------------------
# Build Analyst B fixture
#
# Profile (per METHODOLOGY.md §8 "Precision Caller"):
#   - 24 resolved target_deadline claims
#   - 14 hits, 10 misses → raw hit rate ≈ 58.3%
#   - All base_rate = 0.34
#   - target_price=60680, p0=40000, sigma=0.7, T=455 days → d≈0.53
#   - DS = (hits - 0.34*24) / 24 ≈ 0.243 (v=2.0, all same d → cancels)
#   - Confidence tied to outcome: hits conf=0.7, misses conf=0.3
#     → Brier = 0.09 every claim → C = clamp(1 - 0.09/0.25, 0, 1) = 0.64
#   - 24 scored / 34 prediction-like → F ≈ 0.706
#   - Expected FAS in [60, 80], provisional (20 <= 24 < 30)
#
# Outcomes are spread evenly; confidence is tied to outcome (not index) so
# that the Brier score is stable regardless of outcome ordering.
# ---------------------------------------------------------------------------

ANALYST_B_ID = 2


def _build_analyst_b() -> tuple[list[tuple[Claim, Resolution, float]], int]:
    """Return (resolved_triples, prediction_like_count)."""
    triples: list[tuple[Claim, Resolution, float]] = []
    n = 24
    hits = 14  # 14/24 ≈ 58.3%
    base_rate_b = 0.34

    outcomes = _spread_outcomes(n, hits)

    for i in range(n):
        uttered = _uttered(i, ANALYST_B_ID)
        outcome = outcomes[i]
        # Confidence tied to outcome: well-calibrated (hits→0.7, misses→0.3)
        # Brier contribution per claim = (0.7-1)^2 or (0.3-0)^2 = 0.09 always
        conf = 0.7 if outcome == 1.0 else 0.3
        # target_deadline: v=2.0; d derived from price targets
        # P0=40000, P_target=60680, sigma=0.7, T≈455d (2024-01-01→2025-03-31)
        # d = clamp(|ln(60680/40000)| / (0.7*sqrt(1.2457)), 0.25, 2.0) ≈ 0.53
        claim = _make_claim(
            claim_id=100 + i + 1,
            analyst_id=ANALYST_B_ID,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
            uttered_at=uttered,
            stated_confidence=conf,
            target_price=60680.0,
            p0_price=40000.0,
            horizon_deadline=date(2025, 3, 31),
        )
        resolution = _make_resolution(100 + i + 1, outcome)
        triples.append((claim, resolution, base_rate_b))

    # F = 24 / 34 ≈ 0.706
    prediction_like_count = 34
    return triples, prediction_like_count


# ---------------------------------------------------------------------------
# Worked-example tests (pure, no DB)
# ---------------------------------------------------------------------------


class TestWorkedExamples:
    """Binding tests per METHODOLOGY.md §8."""

    def setup_method(self) -> None:
        self.a_triples, self.a_pred_count = _build_analyst_a()
        self.b_triples, self.b_pred_count = _build_analyst_b()

    def _r_prior(self, comp_a: AnalystComponents, comp_b: AnalystComponents) -> float:
        """ADR-0002 pin 3: fewer than 3 analysts → R_prior = 0.5."""
        return 0.5

    def test_fas_a_in_band(self) -> None:
        """Analyst A lands in [45, 60] band."""
        comp_a = score_analyst_pure(ANALYST_A_ID, self.a_triples, self.a_pred_count)
        comp_b = score_analyst_pure(ANALYST_B_ID, self.b_triples, self.b_pred_count)
        r_prior = self._r_prior(comp_a, comp_b)
        fas_a = composite_fas(comp_a.ds, comp_a.c, comp_a.k, comp_a.f, comp_a.n, r_prior)
        assert 45.0 <= fas_a <= 60.0, (
            f"FAS_A={fas_a:.2f} not in [45, 60]; "
            f"DS={comp_a.ds:.4f}, C={comp_a.c:.4f}, K={comp_a.k:.4f}, F={comp_a.f:.4f}"
        )

    def test_fas_b_in_band(self) -> None:
        """Analyst B lands in [60, 80] band."""
        comp_a = score_analyst_pure(ANALYST_A_ID, self.a_triples, self.a_pred_count)
        comp_b = score_analyst_pure(ANALYST_B_ID, self.b_triples, self.b_pred_count)
        r_prior = self._r_prior(comp_a, comp_b)
        fas_b = composite_fas(comp_b.ds, comp_b.c, comp_b.k, comp_b.f, comp_b.n, r_prior)
        assert 60.0 <= fas_b <= 80.0, (
            f"FAS_B={fas_b:.2f} not in [60, 80]; "
            f"DS={comp_b.ds:.4f}, C={comp_b.c:.4f}, K={comp_b.k:.4f}, F={comp_b.f:.4f}"
        )

    def test_fas_b_outranks_a(self) -> None:
        """B outranks A despite lower raw hit rate (58% vs 68%)."""
        comp_a = score_analyst_pure(ANALYST_A_ID, self.a_triples, self.a_pred_count)
        comp_b = score_analyst_pure(ANALYST_B_ID, self.b_triples, self.b_pred_count)
        r_prior = self._r_prior(comp_a, comp_b)
        fas_a = composite_fas(comp_a.ds, comp_a.c, comp_a.k, comp_a.f, comp_a.n, r_prior)
        fas_b = composite_fas(comp_b.ds, comp_b.c, comp_b.k, comp_b.f, comp_b.n, r_prior)
        assert fas_b > fas_a, (
            f"FAS_B={fas_b:.2f} should outrank FAS_A={fas_a:.2f}; raw hit rates A=68%, B=58%"
        )

    def test_analyst_b_is_provisional_and_ranked(self) -> None:
        """B (n=24): 20 <= 24 < 30 → ranked and provisional."""
        comp_b = score_analyst_pure(ANALYST_B_ID, self.b_triples, self.b_pred_count)
        assert comp_b.ranked(), "B (n=24) should be ranked (n >= 20)"
        assert comp_b.provisional(), "B (n=24) should be provisional (n < 30)"

    def test_analyst_a_is_ranked_not_provisional(self) -> None:
        """A (n=60): n >= 30 → ranked, NOT provisional."""
        comp_a = score_analyst_pure(ANALYST_A_ID, self.a_triples, self.a_pred_count)
        assert comp_a.ranked(), "A (n=60) should be ranked (n >= 20)"
        assert not comp_a.provisional(), "A (n=60) should NOT be provisional (n >= 30)"

    def test_n19_analyst_not_ranked(self) -> None:
        """n=19: below MIN_RANKED_N → not ranked."""
        triples = self.b_triples[:19]  # truncate to 19
        comp = score_analyst_pure(99, triples, 30)
        assert not comp.ranked(), "n=19 analyst should NOT be ranked"

    def test_n30_provisional_clears(self) -> None:
        """n=30: provisional flag clears exactly at PROVISIONAL_CLEARS_AT_N."""
        # Build 30 direction_only claims
        triples_30 = [
            (
                _make_claim(
                    claim_id=500 + i,
                    analyst_id=50,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i, 50),
                    stated_confidence=0.7,
                ),
                _make_resolution(500 + i, 1.0),
                0.5,
            )
            for i in range(30)
        ]
        comp = score_analyst_pure(50, triples_30, 30)
        assert comp.n == 30
        assert not comp.provisional(), "n=30 should NOT be provisional (flag clears)"
        assert comp.ranked(), "n=30 should be ranked"

    def test_shrinkage_k_constant(self) -> None:
        assert SHRINKAGE_K == 25


# ---------------------------------------------------------------------------
# Unit tests for individual components
# ---------------------------------------------------------------------------


class TestClaimWeight:
    """Unit tests for claim_weight and spam damping."""

    def test_direction_only_weight(self) -> None:
        """direction_only: v=1.0, d=0.5 → w=0.5."""
        c = _make_claim(
            claim_id=1,
            analyst_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            uttered_at=_uttered(0),
        )
        assert claim_weight(c) == pytest.approx(0.5)

    def test_target_deadline_weight(self) -> None:
        """target_deadline: v=2.0, d computed; w = v * d."""
        c = _make_claim(
            claim_id=2,
            analyst_id=1,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
            uttered_at=datetime(2024, 1, 1, tzinfo=UTC),
            target_price=60680.0,
            p0_price=40000.0,
            horizon_deadline=date(2024, 4, 1),
        )
        w = claim_weight(c, sigma_annual=0.7)
        assert w > 0.5, "target_deadline should weight more than direction_only"
        # v=2.0, so w = 2 * d; d is clamped to [0.25, 2.0]
        d = w / 2.0
        assert 0.25 <= d <= 2.0

    def test_non_falsifiable_weight_zero(self) -> None:
        """non_falsifiable always weighs zero."""
        c = _make_claim(
            claim_id=3,
            analyst_id=1,
            specificity_class=SpecificityClass.NON_FALSIFIABLE,
            uttered_at=_uttered(0),
        )
        assert claim_weight(c) == 0.0

    def test_spam_damping_applied_when_m_gt_3(self) -> None:
        """group_size > 3 → w / sqrt(m)."""
        c = _make_claim(
            claim_id=4,
            analyst_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            uttered_at=_uttered(0),
        )
        base_w = claim_weight(c, group_size=1)
        damped_w = claim_weight(c, group_size=9)
        assert damped_w == pytest.approx(base_w / math.sqrt(9))

    def test_spam_damping_not_applied_when_m_le_3(self) -> None:
        """group_size <= 3 → no damping."""
        c = _make_claim(
            claim_id=5,
            analyst_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            uttered_at=_uttered(0),
        )
        for m in (1, 2, 3):
            assert claim_weight(c, group_size=m) == claim_weight(c, group_size=1)


class TestDirectionalSkill:
    def test_empty_returns_zero(self) -> None:
        assert directional_skill([]) == 0.0

    def test_all_hits_above_base_rate(self) -> None:
        """All outcomes = 1, b = 0.5 → DS = +0.5."""
        triples = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                ),
                _make_resolution(i, 1.0),
                0.5,
            )
            for i in range(5)
        ]
        ds = directional_skill(triples)
        assert ds == pytest.approx(0.5)

    def test_non_falsifiable_excluded(self) -> None:
        """non_falsifiable claims must not contribute to DS."""
        falsifiable = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                ),
                _make_resolution(i, 1.0),
                0.5,
            )
            for i in range(3)
        ]
        nf_claim = _make_claim(
            claim_id=99,
            analyst_id=1,
            specificity_class=SpecificityClass.NON_FALSIFIABLE,
            uttered_at=_uttered(99),
        )
        nf_res = _make_resolution(99, 0.0)
        all_triples = falsifiable + [(nf_claim, nf_res, 0.0)]
        ds_all = directional_skill(all_triples)
        ds_fals = directional_skill(falsifiable)
        assert ds_all == pytest.approx(ds_fals)


class TestCalibration:
    def test_no_confidence_returns_zero(self) -> None:
        """ADR-0002: zero claims with confidence → C = 0."""
        triples = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                    stated_confidence=None,
                ),
                _make_resolution(i, 1.0),
            )
            for i in range(5)
        ]
        assert calibration(triples) == 0.0

    def test_coin_flip_quality_confidence_clamps_to_zero(self) -> None:
        """Coin-flip confidence (c=0.5) on 50/50 outcomes → C ≈ 0; on very
        wrong calls → C could go negative but is clamped to 0."""
        # Worst case: c=0.9 always, outcome=0 always → B=0.81 → C<0 → 0
        triples = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                    stated_confidence=0.9,
                ),
                _make_resolution(i, 0.0),
            )
            for i in range(5)
        ]
        c = calibration(triples)
        assert c == 0.0, f"Badly overconfident calls should clamp to 0, got {c}"

    def test_perfect_confidence_gives_high_c(self) -> None:
        """c_i = y_i for all claims → Brier = 0 → C = 1."""
        triples = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                    stated_confidence=1.0,
                ),
                _make_resolution(i, 1.0),
            )
            for i in range(5)
        ]
        c = calibration(triples)
        assert c == pytest.approx(1.0)

    def test_calibration_value_formula(self) -> None:
        """B = 0.09 → C = clamp(1 - 0.09/0.25, 0, 1) = 0.64."""
        # Hits: c=0.7 outcome=1 → (0.7-1)^2 = 0.09
        # Misses: c=0.3 outcome=0 → (0.3-0)^2 = 0.09
        hits = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                    stated_confidence=0.7,
                ),
                _make_resolution(i, 1.0),
            )
            for i in range(3)
        ]
        misses = [
            (
                _make_claim(
                    claim_id=10 + i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(10 + i),
                    stated_confidence=0.3,
                ),
                _make_resolution(10 + i, 0.0),
            )
            for i in range(2)
        ]
        c = calibration(hits + misses)
        assert c == pytest.approx(0.64, abs=1e-9)


class TestConsistency:
    def test_fewer_than_11_claims_returns_neutral(self) -> None:
        """n < 11 → K = 0.5 (neutral)."""
        triples = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                ),
                _make_resolution(i, 1.0),
                0.5,
            )
            for i in range(10)
        ]
        assert consistency(triples) == 0.5

    def test_identical_windows_give_k_one(self) -> None:
        """All windows produce the same DS → stdev=0 → K=1."""
        # 11 identical claims: all hit with same base rate → all windows same DS
        triples = [
            (
                _make_claim(
                    claim_id=i,
                    analyst_id=1,
                    specificity_class=SpecificityClass.DIRECTION_ONLY,
                    uttered_at=_uttered(i),
                ),
                _make_resolution(i, 1.0),
                0.5,
            )
            for i in range(11)
        ]
        k = consistency(triples)
        assert k == pytest.approx(1.0)

    def test_dispersed_windows_less_than_one(self) -> None:
        """Alternating hit/miss windows give stdev > 0 → K < 1."""
        # Create 20 claims alternating: first 10 all-hit, next 10 all-miss
        # This maximises dispersion between two windows
        triples = []
        for i in range(10):
            triples.append(
                (
                    _make_claim(
                        claim_id=i,
                        analyst_id=1,
                        specificity_class=SpecificityClass.DIRECTION_ONLY,
                        uttered_at=_uttered(i),
                    ),
                    _make_resolution(i, 1.0),
                    0.5,
                )
            )
        for i in range(10, 20):
            triples.append(
                (
                    _make_claim(
                        claim_id=i,
                        analyst_id=1,
                        specificity_class=SpecificityClass.DIRECTION_ONLY,
                        uttered_at=_uttered(i),
                    ),
                    _make_resolution(i, 0.0),
                    0.5,
                )
            )
        k = consistency(triples)
        assert k < 1.0, f"Dispersed windows should give K < 1, got {k}"

    def test_empty_returns_neutral(self) -> None:
        assert consistency([]) == 0.5


class TestFalsifiability:
    def test_basic_ratio(self) -> None:
        assert falsifiability(60, 240) == pytest.approx(0.25)

    def test_zero_denominator_returns_zero(self) -> None:
        assert falsifiability(0, 0) == 0.0

    def test_full_falsifiability(self) -> None:
        assert falsifiability(10, 10) == pytest.approx(1.0)

    def test_value_clamps_to_one(self) -> None:
        # scored > total is defensive; still clamps
        assert falsifiability(15, 10) == pytest.approx(1.0)


class TestNormDs:
    def test_zero_skill_maps_to_half(self) -> None:
        assert _norm_ds(0.0) == pytest.approx(0.5)

    def test_positive_ds_quarter_maps_to_one(self) -> None:
        assert _norm_ds(0.25) == pytest.approx(1.0)

    def test_negative_ds_quarter_maps_to_zero(self) -> None:
        assert _norm_ds(-0.25) == pytest.approx(0.0)

    def test_clamp_above_one(self) -> None:
        assert _norm_ds(1.0) == pytest.approx(1.0)

    def test_clamp_below_zero(self) -> None:
        assert _norm_ds(-1.0) == pytest.approx(0.0)


class TestCompositeFas:
    def test_formula_matches_spec(self) -> None:
        """R = 0.45*norm(DS) + 0.25*C + 0.15*K + 0.15*F;
        FAS = 100*(n*R + 25*R_prior)/(n+25)."""
        ds, c, k, f = 0.0, 0.5, 0.5, 0.5
        n = 25
        r_prior = 0.5
        norm_ds = _norm_ds(ds)  # 0.5
        r = 0.45 * norm_ds + 0.25 * c + 0.15 * k + 0.15 * f
        expected = 100.0 * (n * r + 25 * r_prior) / (n + 25)
        result = composite_fas(ds, c, k, f, n, r_prior)
        assert result == pytest.approx(expected)

    def test_shrinkage_pulls_toward_prior(self) -> None:
        """High n reduces shrinkage effect; low n pulls towards prior."""
        r_prior = 0.5
        # R > 0.5: high n should give higher FAS than low n
        fas_high_n = composite_fas(0.2, 0.8, 0.8, 0.8, 1000, r_prior)
        fas_low_n = composite_fas(0.2, 0.8, 0.8, 0.8, 5, r_prior)
        assert fas_high_n > fas_low_n


# ---------------------------------------------------------------------------
# DB tests (use db_conn fixture; all rolled back)
# ---------------------------------------------------------------------------


def _returned_id(cur: psycopg.Cursor[Any]) -> int:
    """Fetch the id from a RETURNING clause; the row is always present."""
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_scoring_data(cur: psycopg.Cursor[Any]) -> tuple[int, int]:
    """Insert minimal DB rows for two analysts with resolved claims.

    Returns (analyst_a_id, analyst_b_id).
    """
    # Analyst A
    cur.execute(
        """
        insert into analysts (channel_id, display_name, slug)
        values ('UC-fas-test-a', 'FAS Test Analyst A', 'fas-test-a')
        returning id
        """
    )
    analyst_a_id = _returned_id(cur)

    # Analyst B
    cur.execute(
        """
        insert into analysts (channel_id, display_name, slug)
        values ('UC-fas-test-b', 'FAS Test Analyst B', 'fas-test-b')
        returning id
        """
    )
    analyst_b_id = _returned_id(cur)

    for analyst_id in (analyst_a_id, analyst_b_id):
        cur.execute(
            """
            insert into videos (analyst_id, youtube_video_id, title, published_at)
            values (%s, %s, 'test video', now()) returning id
            """,
            (analyst_id, f"vid-fas-test-{analyst_id}"),
        )
        video_id = _returned_id(cur)
        cur.execute(
            """
            insert into transcripts (video_id, source, storage_pointer)
            values (%s, 'captions', 'local://test') returning id
            """,
            (video_id,),
        )
        transcript_id = _returned_id(cur)

        # Insert 25 resolved direction_only claims (n >= 20)
        for i in range(25):
            cur.execute(
                """
                insert into claims (
                    analyst_id, video_id, transcript_id, asset, direction,
                    specificity_class, source_offset_seconds,
                    model_version, prompt_version, uttered_at,
                    review_state, publishable, status,
                    stated_confidence, flags
                ) values (
                    %s, %s, %s, 'BTC', 'bullish',
                    'direction_only', %s,
                    'test-v0', 'test-v0', %s,
                    'approved', true, 'resolved',
                    0.7,
                    %s::jsonb
                ) returning id
                """,
                (
                    analyst_id,
                    video_id,
                    transcript_id,
                    i,
                    datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
                    '{"fixture_base_rate": 0.5}',
                ),
            )
            claim_id = _returned_id(cur)
            cur.execute(
                """
                insert into resolutions (claim_id, outcome, rule_id, rationale,
                                         price_citation, methodology_version)
                values (%s, 1, 'test', 'test', '{}'::jsonb, 'v1.0')
                """,
                (claim_id,),
            )

    return analyst_a_id, analyst_b_id


def test_run_score_pass_writes_score_run_row(db_conn: psycopg.Connection[Any]) -> None:
    """run_score_pass writes exactly one score_runs row tagged v1.0."""
    with db_conn.cursor() as cur:
        _seed_scoring_data(cur)

    run_id, scores = run_score_pass("demo", conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute("select methodology_version, trigger from score_runs where id = %s", (run_id,))
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "v1.0"
        assert row[1] == "demo"


def test_run_score_pass_writes_per_analyst_scores(db_conn: psycopg.Connection[Any]) -> None:
    """run_score_pass writes one scores row per analyst."""
    with db_conn.cursor() as cur:
        analyst_a_id, analyst_b_id = _seed_scoring_data(cur)

    run_id, scores = run_score_pass("demo", conn=db_conn)

    analyst_ids_in_scores = {s.analyst_id for s in scores}
    assert analyst_a_id in analyst_ids_in_scores
    assert analyst_b_id in analyst_ids_in_scores

    # Verify they are stored in DB
    with db_conn.cursor() as cur:
        cur.execute("select count(*) from scores where score_run_id = %s", (run_id,))
        count_row = cur.fetchone()
        assert count_row is not None
        assert count_row[0] >= 2


def test_run_score_pass_append_only(db_conn: psycopg.Connection[Any]) -> None:
    """Attempting UPDATE on a scores row raises the append-only trigger error."""
    with db_conn.cursor() as cur:
        _seed_scoring_data(cur)

    run_id, scores = run_score_pass("demo", conn=db_conn)
    assert len(scores) > 0
    score_id = scores[0].id
    assert score_id is not None

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with db_conn.cursor() as cur:
            cur.execute("update scores set fas = 99 where id = %s", (score_id,))

    db_conn.rollback()


def test_run_score_pass_rerun_appends_new_run(db_conn: psycopg.Connection[Any]) -> None:
    """Re-running score_pass appends a new score_runs row rather than mutating."""
    with db_conn.cursor() as cur:
        _seed_scoring_data(cur)

    run_id_1, _ = run_score_pass("demo", conn=db_conn)
    run_id_2, _ = run_score_pass("nightly", conn=db_conn)

    assert run_id_2 != run_id_1, "Second run must get a new score_run id"

    with db_conn.cursor() as cur:
        cur.execute(
            "select count(*) from score_runs where id in (%s, %s)",
            (run_id_1, run_id_2),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 2, "Both score_runs rows must exist"


def test_run_score_pass_methodology_version_tag(db_conn: psycopg.Connection[Any]) -> None:
    """Every scores row from a run is tagged with the methodology version."""
    with db_conn.cursor() as cur:
        _seed_scoring_data(cur)

    run_id, scores = run_score_pass("demo", conn=db_conn)

    for score in scores:
        assert score.methodology_version == "v1.0"
