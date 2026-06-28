"""T2: Failure-path and edge-regression tests for FAS scoring.

Boundary characterizations of the EXISTING formula per METHODOLOGY.md §6.
All tests are pure-function (no DB): they drive composite_fas and
AnalystComponents directly for determinism (NFR-2).

Binding constants under test:
  SHRINKAGE_K = 25              (METHODOLOGY.md §6, fas.py)
  MIN_RANKED_N = 20             (FR-305, fas.py)
  PROVISIONAL_CLEARS_AT_N = 30  (METHODOLOGY.md §6 two-tier rule, fas.py)

Test clusters:
  TestBindingConstants    — three boundary constants match METHODOLOGY.md §6
  TestShrinkageBoundary   — 100*(n*R + k*R_prior)/(n+k) concrete numerics
  TestRankedBoundary      — n=19 → not ranked; n=20 → ranked
  TestProvisionalBoundary — n=29 → provisional; n=30 → clears
"""

from __future__ import annotations

import pytest

from brier_pipeline.scoring.fas import (
    MIN_RANKED_N,
    PROVISIONAL_CLEARS_AT_N,
    SHRINKAGE_K,
    AnalystComponents,
    _norm_ds,
    composite_fas,
)

# ---------------------------------------------------------------------------
# Helper: build AnalystComponents with controlled n, all other params neutral
# ---------------------------------------------------------------------------


def _make_components(
    n: int,
    *,
    ds: float = 0.0,
    c: float = 0.5,
    k: float = 0.5,
    f: float = 0.5,
) -> AnalystComponents:
    """Return AnalystComponents with controlled n and scoring components.

    Parameters
    ----------
    n:
        Number of resolved scorable claims (the key boundary variable).
    ds, c, k, f:
        Scoring component overrides.  Defaults are neutral (mid-range) values.
    """
    return AnalystComponents(
        analyst_id=999,
        ds=ds,
        c=c,
        k=k,
        f=f,
        n=n,
        prediction_like_count=max(n, 1),
    )


# ---------------------------------------------------------------------------
# Binding constants match METHODOLOGY.md §6
# ---------------------------------------------------------------------------


class TestBindingConstants:
    """The three boundary constants must exactly match METHODOLOGY.md §6."""

    def test_shrinkage_k_is_25(self) -> None:
        """METHODOLOGY §6: shrinkage constant k = 25."""
        assert SHRINKAGE_K == 25

    def test_min_ranked_n_is_20(self) -> None:
        """METHODOLOGY §6 / FR-305: ranked eligibility starts at n = 20."""
        assert MIN_RANKED_N == 20

    def test_provisional_clears_at_n_30(self) -> None:
        """METHODOLOGY §6 two-tier: provisional flag clears at n = 30."""
        assert PROVISIONAL_CLEARS_AT_N == 30


# ---------------------------------------------------------------------------
# Shrinkage k=25 formula: concrete numeric boundary checks
# ---------------------------------------------------------------------------


class TestShrinkageBoundary:
    """Concrete numeric checks of FAS = 100*(n*R + k*R_prior)/(n+k), k=25.

    Test fixture uses DS=0.25 (→ norm_ds=1.0), C=K_cons=F=1.0 so that R=1.0
    and R_prior=0.5.  With R > R_prior the shrinkage effect is fully visible and
    every FAS value is analytically simple.

    Note: in composite_fas(ds, c, k, f, n, r_prior), the parameter named 'k' is
    the CONSISTENCY component K, not the shrinkage constant.  The shrinkage
    constant is the module-level SHRINKAGE_K = 25.
    """

    # DS=0.25 → norm_ds = (0.25+0.25)/0.5 = 1.0
    # R = 0.45*1.0 + 0.25*1.0 + 0.15*1.0 + 0.15*1.0 = 1.0
    _DS = 0.25
    _C = 1.0
    _K_CONS = 1.0  # consistency component (not shrinkage k)
    _F = 1.0
    _R_PRIOR = 0.5

    def _fas(self, n: int) -> float:
        return composite_fas(self._DS, self._C, self._K_CONS, self._F, n, self._R_PRIOR)

    def test_n_zero_gives_pure_prior(self) -> None:
        """At n=0, FAS collapses to 100*R_prior — zero observations pull fully to prior.

        Formula: 100*(0*1.0 + 25*0.5)/(0+25) = 100*12.5/25 = 50.0.
        """
        result = self._fas(0)
        assert result == pytest.approx(100.0 * self._R_PRIOR, abs=1e-9)
        assert result == pytest.approx(50.0, abs=1e-9)

    def test_n_equals_shrinkage_k_equal_weight(self) -> None:
        """At n=SHRINKAGE_K=25, own R and R_prior carry exactly equal weight (50/50).

        Formula: 100*(25*1.0 + 25*0.5)/50 = 100*37.5/50 = 75.0.
        Equivalently: (100*R + 100*R_prior)/2 = (100 + 50)/2 = 75.0.
        """
        expected = 50.0 * (1.0 + self._R_PRIOR)  # 75.0
        result = self._fas(SHRINKAGE_K)
        assert result == pytest.approx(expected, abs=1e-9)
        assert result == pytest.approx(75.0, abs=1e-9)

    def test_n_far_below_k_dominated_by_prior(self) -> None:
        """At n=1 (far below k=25), result matches formula; prior dominates.

        Formula: 100*(1*1.0 + 25*0.5)/(1+25) = 100*13.5/26 ≈ 51.923.
        Prior weight = 25/26 ≈ 0.962.
        """
        expected = 100.0 * (1 * 1.0 + 25 * self._R_PRIOR) / (1 + 25)
        result = self._fas(1)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_n_far_above_k_dominated_by_own_r(self) -> None:
        """At n=100 (far above k=25), FAS is dominated by own R.

        Formula: 100*(100*1.0 + 25*0.5)/(100+25) = 100*112.5/125 = 90.0.
        Own-R weight = 100/125 = 0.80; prior weight = 0.20.
        """
        expected = 100.0 * (100 * 1.0 + 25 * self._R_PRIOR) / (100 + 25)
        result = self._fas(100)
        assert result == pytest.approx(expected, abs=1e-9)
        assert result == pytest.approx(90.0, abs=1e-9)

    def test_concrete_numeric_n7(self) -> None:
        """Concrete formula check: DS=0.0, C=0.8, K_cons=0.6, F=0.4, n=7, R_prior=0.5.

        norm_ds = (0.0+0.25)/0.5 = 0.5
        R = 0.45*0.5 + 0.25*0.8 + 0.15*0.6 + 0.15*0.4
          = 0.225 + 0.200 + 0.090 + 0.060 = 0.575
        FAS = 100*(7*0.575 + 25*0.5)/(7+25)
            = 100*(4.025 + 12.5)/32 = 100*16.525/32 = 51.640625

        Both the formula-derived expected value and the concrete literal must
        agree with composite_fas() to catch any future formula drift.
        """
        ds, c, k_cons, f = 0.0, 0.8, 0.6, 0.4
        n = 7
        r_prior = 0.5
        norm_ds_val = _norm_ds(ds)  # 0.5
        r = 0.45 * norm_ds_val + 0.25 * c + 0.15 * k_cons + 0.15 * f
        expected = 100.0 * (n * r + SHRINKAGE_K * r_prior) / (n + SHRINKAGE_K)
        result = composite_fas(ds, c, k_cons, f, n, r_prior)
        assert result == pytest.approx(expected, abs=1e-9)
        # Concrete literal guards against any future coefficient drift
        assert result == pytest.approx(51.640625, abs=1e-5)

    def test_r_equals_r_prior_fas_independent_of_n(self) -> None:
        """When R == R_prior, shrinkage has no effect: FAS = 100*R for any n.

        Identity: 100*(n*R + k*R)/(n+k) = 100*R*(n+k)/(n+k) = 100*R.
        DS=0.0 → norm_ds=0.5, C=K_cons=F=0.5 → R = 0.5 = R_prior → FAS = 50.0.
        """
        for n in (0, 1, 5, 20, 25, 100, 1000):
            result = composite_fas(0.0, 0.5, 0.5, 0.5, n, 0.5)
            assert result == pytest.approx(50.0, abs=1e-9), (
                f"n={n}: expected 50.0 when R==R_prior, got {result:.10f}"
            )

    def test_monotone_increasing_n_when_r_above_prior(self) -> None:
        """When R > R_prior, increasing n strictly increases FAS.

        Shrinkage pulls toward prior; more data reduces prior influence.
        Tested at six increasing n values with R=1.0 > R_prior=0.5.
        """
        ns = [1, 5, 10, 25, 50, 100]
        results = [self._fas(n) for n in ns]
        for i in range(len(results) - 1):
            assert results[i] < results[i + 1], (
                f"FAS not strictly monotone: fas(n={ns[i]})={results[i]:.6f} "
                f">= fas(n={ns[i + 1]})={results[i + 1]:.6f}"
            )


# ---------------------------------------------------------------------------
# Ranked boundary: MIN_RANKED_N = 20
# ---------------------------------------------------------------------------


class TestRankedBoundary:
    """METHODOLOGY §6 / FR-305: ranked eligibility threshold at n = 20.

    n < 20  → ranked() returns False (excluded from the ranked board)
    n >= 20 → ranked() returns True
    """

    def test_n_19_not_ranked(self) -> None:
        """n=19 is one below MIN_RANKED_N=20: ranked() must be False."""
        comp = _make_components(19)
        assert not comp.ranked(), "n=19 should NOT be ranked (n < MIN_RANKED_N=20)"

    def test_n_20_ranked(self) -> None:
        """n=20 is exactly MIN_RANKED_N: ranked() must be True."""
        comp = _make_components(20)
        assert comp.ranked(), "n=20 should be ranked (n == MIN_RANKED_N=20)"

    def test_n_21_ranked(self) -> None:
        """n=21 is above MIN_RANKED_N: ranked() must be True."""
        comp = _make_components(21)
        assert comp.ranked(), "n=21 should be ranked (n > MIN_RANKED_N=20)"

    def test_n_0_not_ranked(self) -> None:
        """n=0 (no resolved claims): not ranked."""
        comp = _make_components(0)
        assert not comp.ranked(), "n=0 should NOT be ranked"

    def test_n_19_is_also_provisional(self) -> None:
        """METHODOLOGY §6: n < 20 is not ranked AND provisional (two-tier rule).

        The two-tier rule defines two separate flags: ranked (n>=20) and
        provisional (n<30).  At n=19 both conditions produce unfavourable values.
        """
        comp = _make_components(19)
        assert not comp.ranked(), "n=19: not ranked (n < MIN_RANKED_N=20)"
        assert comp.provisional(), "n=19: provisional (n < PROVISIONAL_CLEARS_AT_N=30)"


# ---------------------------------------------------------------------------
# Provisional two-tier boundary: PROVISIONAL_CLEARS_AT_N = 30
# ---------------------------------------------------------------------------


class TestProvisionalBoundary:
    """METHODOLOGY §6 two-tier rule: provisional flag clears at exactly n = 30.

    Tier 1: 20 <= n < 30 → ranked AND provisional
    Tier 2: n >= 30      → ranked AND NOT provisional
    n < 20 falls below both tiers: not ranked AND provisional.
    """

    def test_n_29_provisional_true(self) -> None:
        """n=29 is one below PROVISIONAL_CLEARS_AT_N=30: provisional() is True."""
        comp = _make_components(29)
        assert comp.provisional(), "n=29 should be provisional (29 < 30)"

    def test_n_30_provisional_clears(self) -> None:
        """n=30 is exactly PROVISIONAL_CLEARS_AT_N: provisional() is False.

        This is the binding test case from METHODOLOGY §6: 'n >= 30: flag clears.'
        """
        comp = _make_components(30)
        assert not comp.provisional(), "n=30 should NOT be provisional (flag clears at n=30)"

    def test_n_31_provisional_false(self) -> None:
        """n=31 is above PROVISIONAL_CLEARS_AT_N: provisional() is False."""
        comp = _make_components(31)
        assert not comp.provisional(), "n=31 should NOT be provisional"

    def test_n_20_ranked_and_provisional(self) -> None:
        """n=20 sits in the middle tier: ranked=True AND provisional=True.

        METHODOLOGY §6: '20 <= n < 30: ranked, but flagged provisional.'
        """
        comp = _make_components(20)
        assert comp.ranked(), "n=20 should be ranked (20 >= MIN_RANKED_N=20)"
        assert comp.provisional(), "n=20 should be provisional (20 < PROVISIONAL_CLEARS_AT_N=30)"

    def test_n_29_ranked_and_provisional(self) -> None:
        """n=29 is the last n in the middle tier: ranked=True AND provisional=True.

        This is the Analyst B scenario: 'flagged provisional until n >= 30'
        (METHODOLOGY §8 worked example).
        """
        comp = _make_components(29)
        assert comp.ranked(), "n=29 should be ranked (29 >= MIN_RANKED_N=20)"
        assert comp.provisional(), "n=29 should be provisional (29 < PROVISIONAL_CLEARS_AT_N=30)"

    def test_n_30_ranked_and_not_provisional(self) -> None:
        """n=30 exits the provisional tier: ranked=True AND provisional=False.

        METHODOLOGY §6: 'n >= 30: flag clears.'
        """
        comp = _make_components(30)
        assert comp.ranked(), "n=30 should be ranked (30 >= MIN_RANKED_N=20)"
        assert not comp.provisional(), "n=30 should NOT be provisional (flag clears)"
