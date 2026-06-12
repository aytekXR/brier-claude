"""The published resolution rule library (FR-302, METHODOLOGY.md §2).

Every resolution row records the rule_id that produced it, so each outcome is
reproducible and citable. v0 (E1-T3) covers the happy-path rules; the full
library including edge cases EC-1..EC-12 lands with E4.
"""

from __future__ import annotations

from datetime import UTC, datetime

from brier_pipeline.config import METHODOLOGY_VERSION
from brier_pipeline.models import Claim, PriceDaily, Resolution


def resolve_target_by_deadline(claim: Claim, closes: list[PriceDaily]) -> Resolution | None:
    """ "Hits $X by D" resolves 1 if any daily close meets X before D.

    Close basis only — never wicks. Returns None while the claim is still open.
    (HP-2 is the canonical example: "BTC daily close above $80k by Jul 31".)

    Rules:
    - Bullish: outcome 1 if any close >= target in the window (strictly after
      uttered_at date) through horizon_deadline inclusive. Cite the FIRST
      qualifying close.
    - Bearish: outcome 1 if any close <= target in the same window.
    - If the deadline has passed (relative to the latest available close date)
      with no qualifying close: outcome 0, citing the deadline-day close.
    - If the deadline is in the future and no close qualifies yet: None.
    - If price data for the required window is missing/gapped (EC-8): None.
    """
    assert claim.target_price is not None
    assert claim.horizon_deadline is not None
    assert claim.direction is not None
    assert claim.asset is not None

    utterance_day = claim.uttered_at.date()
    deadline = claim.horizon_deadline
    target = claim.target_price
    direction = claim.direction

    # Window is strictly after the utterance date through the deadline inclusive.
    window = [c for c in closes if c.day > utterance_day and c.day <= deadline]
    # Latest available close across all provided closes (for staleness check).
    latest_day = max((c.day for c in closes), default=None) if closes else None

    # EC-8: no price data at all for this asset -> defer.
    if not closes:
        return None

    # Find the first qualifying close in the window.
    qualifying: PriceDaily | None = None
    for c in sorted(window, key=lambda x: x.day):
        if c.data_gap:
            continue
        if direction == "bullish" and c.close_usd >= target:
            qualifying = c
            break
        if direction == "bearish" and c.close_usd <= target:
            qualifying = c
            break

    if qualifying is not None:
        direction_word = "above" if direction == "bullish" else "below"
        rationale = (
            f"HIT: daily UTC close {qualifying.close_usd:.2f} on {qualifying.day}"
            f" met target {target:.2f} ({direction_word}) before deadline {deadline}."
        )
        return Resolution(
            claim_id=claim.id or 0,
            outcome=1.0,
            resolved_at=datetime.now(UTC),
            rule_id="target_by_deadline.v0",
            rationale=rationale,
            price_citation={
                "asset": claim.asset,
                "day": str(qualifying.day),
                "close_usd": qualifying.close_usd,
                "source": qualifying.source,
            },
            methodology_version=METHODOLOGY_VERSION,
        )

    # No qualifying close found. Was the deadline in the past relative to available data?
    if latest_day is None or deadline > latest_day:
        # Deadline is in the future (or no data at all) — still open.
        return None

    # Deadline has passed. Find the deadline-day close to cite.
    deadline_closes = [c for c in closes if c.day == deadline and not c.data_gap]
    if not deadline_closes:
        # EC-8: no close available on the deadline day itself -> defer.
        return None

    cite = deadline_closes[0]
    direction_word = "above" if direction == "bullish" else "below"
    rationale = (
        f"MISS: deadline {deadline} passed. No daily UTC close {direction_word}"
        f" {target:.2f} in window. Close on deadline day: {cite.close_usd:.2f}."
    )
    return Resolution(
        claim_id=claim.id or 0,
        outcome=0.0,
        resolved_at=datetime.now(UTC),
        rule_id="target_by_deadline.v0",
        rationale=rationale,
        price_citation={
            "asset": claim.asset,
            "day": str(cite.day),
            "close_usd": cite.close_usd,
            "source": cite.source,
        },
        methodology_version=METHODOLOGY_VERSION,
    )


def resolve_directional_at_horizon(claim: Claim, closes: list[PriceDaily]) -> Resolution | None:
    """Directional claims resolve against the close at T; partial credit 0.5
    when direction is right but stated magnitude is under half achieved.

    Rules:
    - Resolve against the close exactly at horizon_deadline.
    - No close row for that exact day (or row flagged data_gap) -> None (EC-8).
    - Direction wrong -> 0.
    - Direction right: if magnitude_pct stated and the achieved move is under
      HALF the stated magnitude -> 0.5 (partial credit). Otherwise -> 1.
    - Achieved move = (close_at_T - p0)/p0 * 100, sign-aligned with direction
      (bearish moves count positive when price falls).
    """
    assert claim.horizon_deadline is not None
    assert claim.direction is not None
    assert claim.asset is not None

    deadline = claim.horizon_deadline
    direction = claim.direction
    p0 = claim.p0_price

    # Find the close exactly at the deadline.
    deadline_closes = [c for c in closes if c.day == deadline]
    if not deadline_closes:
        # EC-8: no data for the deadline day -> defer.
        return None
    close_at_t = deadline_closes[0]
    if close_at_t.data_gap:
        # EC-8: data gap flagged -> defer.
        return None

    close_usd = close_at_t.close_usd

    # Determine direction correctness.
    direction_correct: bool
    if direction == "bullish":
        direction_correct = close_usd > (p0 or 0.0)
    else:  # bearish
        direction_correct = close_usd < (p0 or 0.0)

    if not direction_correct:
        direction_word = "above" if direction == "bullish" else "below"
        rationale = (
            f"MISS: close at horizon {deadline} was {close_usd:.2f};"
            f" direction {direction} required price {direction_word} {p0:.2f}."
        )
        return Resolution(
            claim_id=claim.id or 0,
            outcome=0.0,
            resolved_at=datetime.now(UTC),
            rule_id="directional_at_horizon.v0",
            rationale=rationale,
            price_citation={
                "asset": claim.asset,
                "day": str(close_at_t.day),
                "close_usd": close_usd,
                "source": close_at_t.source,
            },
            methodology_version=METHODOLOGY_VERSION,
        )

    # Direction is correct. Check magnitude if stated.
    magnitude_pct = claim.magnitude_pct
    if magnitude_pct is not None and p0 is not None and p0 > 0:
        # Achieved move, sign-aligned with direction.
        if direction == "bullish":
            achieved_pct = (close_usd - p0) / p0 * 100.0
        else:  # bearish: positive when price falls
            achieved_pct = (p0 - close_usd) / p0 * 100.0

        half_stated = magnitude_pct / 2.0
        if achieved_pct < half_stated:
            rationale = (
                f"PARTIAL: direction {direction} correct at horizon {deadline}"
                f" (close {close_usd:.2f}); achieved move {achieved_pct:.2f}%"
                f" is under half of stated {magnitude_pct:.2f}% magnitude."
            )
            return Resolution(
                claim_id=claim.id or 0,
                outcome=0.5,
                resolved_at=datetime.now(UTC),
                rule_id="directional_at_horizon.v0",
                rationale=rationale,
                price_citation={
                    "asset": claim.asset,
                    "day": str(close_at_t.day),
                    "close_usd": close_usd,
                    "source": close_at_t.source,
                },
                methodology_version=METHODOLOGY_VERSION,
            )

    # Full credit.
    mag_note = ""
    if magnitude_pct is not None and p0 is not None and p0 > 0:
        if direction == "bullish":
            achieved_pct = (close_usd - p0) / p0 * 100.0
        else:
            achieved_pct = (p0 - close_usd) / p0 * 100.0
        mag_note = f" Achieved move: {achieved_pct:.2f}% vs stated {magnitude_pct:.2f}%."
    direction_word = "above" if direction == "bullish" else "below"
    rationale = (
        f"HIT: daily UTC close {close_usd:.2f} on {deadline}"
        f" was {direction_word} {p0:.2f} at utterance.{mag_note}"
    )
    return Resolution(
        claim_id=claim.id or 0,
        outcome=1.0,
        resolved_at=datetime.now(UTC),
        rule_id="directional_at_horizon.v0",
        rationale=rationale,
        price_citation={
            "asset": claim.asset,
            "day": str(close_at_t.day),
            "close_usd": close_usd,
            "source": close_at_t.source,
        },
        methodology_version=METHODOLOGY_VERSION,
    )


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
