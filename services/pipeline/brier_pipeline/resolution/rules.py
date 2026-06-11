"""The published resolution rule library (FR-302, METHODOLOGY.md §2).

Every resolution row records the rule_id that produced it, so each outcome is
reproducible and citable. v0 (E1-T3) covers the happy-path rules; the full
library including edge cases EC-1..EC-12 lands with E4.
"""

from __future__ import annotations

from brier_pipeline.models import Claim, PriceDaily, Resolution


def resolve_target_by_deadline(claim: Claim, closes: list[PriceDaily]) -> Resolution | None:
    """ "Hits $X by D" resolves 1 if any daily close meets X before D.

    Close basis only — never wicks. Returns None while the claim is still open.
    (HP-2 is the canonical example: "BTC daily close above $80k by Jul 31".)
    """
    # TASK: E1-T3
    raise NotImplementedError


def resolve_directional_at_horizon(claim: Claim, closes: list[PriceDaily]) -> Resolution | None:
    """Directional claims resolve against the close at T; partial credit 0.5
    when direction is right but stated magnitude is under half achieved."""
    # TASK: E1-T3
    raise NotImplementedError


def resolve_conditional(claim: Claim, closes: list[PriceDaily]) -> Resolution | None:
    """Conditional claims activate only if the condition triggers, then score
    over the default horizon (METHODOLOGY.md §2)."""
    # TASK: E4-T1
    raise NotImplementedError


def detect_contradictions(claims: list[Claim]) -> list[Claim]:
    """EC-6: opposite-direction claims on the same asset with overlapping
    horizons void both and raise the hedging flag."""
    # TASK: E4-T4
    raise NotImplementedError
