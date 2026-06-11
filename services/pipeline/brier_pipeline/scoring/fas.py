"""Falsifiable Accuracy Score — signatures only; formulas in docs/METHODOLOGY.md.

The implementation (E1-T2) must match METHODOLOGY.md exactly and encode both
worked examples as unit tests: Analyst B outranks Analyst A despite a lower raw
hit rate; A lands in the 45-60 band; B lands in the 60-80 band and is flagged
provisional; shrinkage k=25; minimum n=20. Formula changes require an ADR and a
methodology version bump with full-history recompute (FR-304, AC-4).
"""

from __future__ import annotations

from brier_pipeline.models import Claim, Resolution, Score

SHRINKAGE_K = 25  # METHODOLOGY.md §6; change only via ADR + version bump
MIN_RANKED_N = 20  # FR-305
PROVISIONAL_CLEARS_AT_N = 30  # two-tier provisional rule, METHODOLOGY.md §6


def claim_weight(claim: Claim) -> float:
    """w = v x d with spam damping (METHODOLOGY.md §4)."""
    # TASK: E1-T2
    raise NotImplementedError


def directional_skill(resolved: list[tuple[Claim, Resolution, float]]) -> float:
    """DS = sum w_i (y_i - b_i) / sum w_i over (claim, resolution, base_rate)."""
    # TASK: E1-T2
    raise NotImplementedError


def calibration(resolved: list[tuple[Claim, Resolution]]) -> float:
    """C = clamp(1 - Brier/0.25, 0, 1) over claims with confidence (§5)."""
    # TASK: E1-T2
    raise NotImplementedError


def consistency(resolved: list[tuple[Claim, Resolution, float]]) -> float:
    """K = 1 - normalized dispersion of rolling 10-claim DS windows (§5)."""
    # TASK: E1-T2
    raise NotImplementedError


def falsifiability(scored_count: int, prediction_like_count: int) -> float:
    """F = scored claims / total extracted prediction-like statements (§5)."""
    # TASK: E1-T2
    raise NotImplementedError


def composite_fas(
    ds: float, c: float, k: float, f: float, n: int, population_median_r: float
) -> float:
    """R = 0.45 norm(DS) + 0.25 C + 0.15 K + 0.15 F;
    FAS = 100 (nR + k_shrink R_prior) / (n + k_shrink) with k_shrink=25 (§6)."""
    # TASK: E1-T2
    raise NotImplementedError


def score_analyst(analyst_id: int, methodology_version: str) -> Score:
    """Full per-analyst score row, including the two-tier provisional flag.

    n < 20: unranked + provisional; 20 <= n < 30: ranked, flagged provisional;
    n >= 30: flag clears (METHODOLOGY.md §6 reconciliation note).
    """
    # TASK: E1-T2
    raise NotImplementedError


def recompute_all(methodology_version: str) -> int:
    """Methodology version bump: full-history recompute into a new score_run;
    the prior ledger stays archived and queryable (FR-304, AC-4, HP-6)."""
    # TASK: E4-T5
    raise NotImplementedError
