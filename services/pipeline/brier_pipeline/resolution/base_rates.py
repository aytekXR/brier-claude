"""Base rates: the honesty mechanism (FR-303, METHODOLOGY.md §3)."""

from __future__ import annotations

from brier_pipeline.models import Claim
from brier_pipeline.resolution.prices import PriceSource


def base_rate(claim: Claim, prices: PriceSource) -> float:
    """Empirical probability that a naive position matching the claim's
    direction succeeded over horizon T on that asset, trailing 5-year history.

    Skill is what remains after subtracting this from the outcome.
    """
    # TASK: E4-T2 (E1 uses precomputed fixture base rates from E1-T1)
    raise NotImplementedError
