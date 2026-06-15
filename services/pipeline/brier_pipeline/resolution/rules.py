"""The published resolution rule library (FR-302, METHODOLOGY.md §2).

Every resolution row records the rule_id that produced it, so each outcome is
reproducible and citable. v0 (E1-T3) covers the happy-path rules; the full
library including default-horizon materialisation, conditional activation, and
explicit reversal (EC-11) lands with E4-T1.

Conditional claims (METHODOLOGY.md §2):
  Activate only when the trigger fires; the underlying claim then scores over
  the default horizon measured from the activation date.  The
  ``conditionality`` JSONB dict optionally carries a structured trigger for
  the claim's OWN asset:
    {
        "condition": "<text>",            # always present
        "trigger_asset": "BTC",           # must match claim.asset for own-asset triggers
        "trigger_price": 75000.0,
        "trigger_direction": "above"|"below"
    }
  Cross-asset triggers (trigger on a different asset than the claim) are OUT
  of MVP scope; they are deferred to QA (rule returns None).

Never-fires conventions (published, METHODOLOGY.md §2.2):
  - Trigger never fires and the observation window is still open  -> defer (None).
  - Trigger never fires and the full observation window has elapsed -> void
    (not scored; the claim never activated).  Call-site marks status=void.

Default-horizon materialisation (METHODOLOGY.md §2.1, Table 1):
  horizon_basis         deadline
  "default_30d"   ->    uttered_at.date() + 30 days
  "default_90d"   ->    uttered_at.date() + 90 days
  "default_eoy"   ->    December 31 of the utterance year
  "stated"        ->    as stored; if still None the claim cannot resolve (defer)

EC-11 reversal (PRD §12 EC-11, METHODOLOGY.md §2.3):
  Explicit reversal closes the original claim at the reversal date, scored to
  date.  Represented on the NEW claim as flags["reverses_claim_id"] = <int>.
  The original claim receives a resolution appended with rule_id
  "reversal_close.v0"; its effective deadline is clamped to the reversal date.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from brier_pipeline.config import METHODOLOGY_VERSION
from brier_pipeline.models import Claim, ClaimStatus, PriceDaily, Resolution, SpecificityClass

# ---------------------------------------------------------------------------
# Default-horizon materialisation (METHODOLOGY.md §2.1)
# ---------------------------------------------------------------------------


def materialise_horizon_deadline(claim: Claim) -> date | None:
    """Return the effective horizon deadline for a claim, computing it when
    the basis is a default convention.

    Returns None for "stated" claims whose horizon_deadline is already set to
    None (cannot resolve; defer).  Does not mutate the claim.

    Basis table (METHODOLOGY.md §2.1, Table 1):
      "default_30d"  -> uttered_at.date() + 30 days
      "default_90d"  -> uttered_at.date() + 90 days
      "default_eoy"  -> December 31 of the utterance year
      "stated"       -> claim.horizon_deadline as-is (None -> defer)
    """
    if claim.horizon_deadline is not None:
        # Already populated — respect it regardless of basis.
        return claim.horizon_deadline

    basis = claim.horizon_basis
    uttered_day = claim.uttered_at.date()

    if basis == "default_30d":
        return uttered_day + timedelta(days=30)
    if basis == "default_90d":
        return uttered_day + timedelta(days=90)
    if basis == "default_eoy":
        return date(uttered_day.year, 12, 31)
    # "stated" with no stored deadline, or no basis at all -> defer.
    return None


# ---------------------------------------------------------------------------
# Core resolution rules (E1-T3)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Conditional activation (METHODOLOGY.md §2.2, E4-T1)
# ---------------------------------------------------------------------------


def _extract_structured_trigger(
    conditionality: dict[str, Any] | None,
    claim_asset: str,
) -> dict[str, Any] | None:
    """Extract and validate the structured trigger from the conditionality dict.

    Returns the trigger dict if present, valid, and for the claim's own asset.
    Returns None if:
      - conditionality is None or has no structured keys -> text-only; defer to QA.
      - trigger_asset != claim_asset -> cross-asset trigger; defer to QA (out of scope).
    """
    if not conditionality:
        return None
    trigger_asset = conditionality.get("trigger_asset")
    trigger_price = conditionality.get("trigger_price")
    trigger_direction = conditionality.get("trigger_direction")
    if trigger_asset is None or trigger_price is None or trigger_direction is None:
        return None
    if str(trigger_asset) != claim_asset:
        # Cross-asset trigger: out of MVP scope; route to QA by returning None.
        return None
    return {
        "trigger_asset": str(trigger_asset),
        "trigger_price": float(trigger_price),
        "trigger_direction": str(trigger_direction),
    }


def _find_activation(
    closes: list[PriceDaily],
    uttered_day: date,
    trigger: dict[str, Any],
    observation_end: date,
) -> tuple[date | None, bool]:
    """Scan closes for the first trigger-qualifying close after uttered_day and
    at or before observation_end.

    Returns ``(activation_date, window_elapsed)``:
      - (date, _)     : the activation date (first qualifying close).
      - (None, True)  : trigger never fired and the window has fully elapsed -> void.
      - (None, False) : trigger has not fired yet and the window is still open -> defer.
    """
    trigger_price: float = trigger["trigger_price"]
    trigger_direction: str = trigger["trigger_direction"]

    latest_available = max((c.day for c in closes), default=None) if closes else None
    window_elapsed = (latest_available is not None) and (latest_available >= observation_end)

    for c in sorted(closes, key=lambda x: x.day):
        if c.day <= uttered_day:
            continue
        if c.day > observation_end:
            break
        if c.data_gap:
            continue
        if trigger_direction == "above" and c.close_usd > trigger_price:
            return c.day, window_elapsed
        if trigger_direction == "below" and c.close_usd < trigger_price:
            return c.day, window_elapsed

    # Trigger did not fire in the window.
    return None, window_elapsed


def _default_horizon_from_date(basis: str | None, anchor: date) -> date | None:
    """Return the default horizon from an anchor date using the published table.

    Used for conditional claims where the horizon is measured from the activation
    date, not from uttered_at.
    """
    if basis == "default_30d":
        return anchor + timedelta(days=30)
    if basis == "default_90d":
        return anchor + timedelta(days=90)
    if basis == "default_eoy":
        return date(anchor.year, 12, 31)
    # "stated" or unknown: no computable default from an anchor.
    return None


def resolve_conditional(claim: Claim, closes: list[PriceDaily]) -> Resolution | None:
    """Conditional claims activate only if the trigger fires, then score over
    the default horizon measured from the activation date (METHODOLOGY.md §2.2).

    Trigger representation (conditionality JSONB dict, optional structured keys):
        {
            "condition": "<text>",          # always present (human-readable)
            "trigger_asset": "BTC",         # must equal claim.asset for own-asset trigger
            "trigger_price": 75000.0,
            "trigger_direction": "above" | "below"
        }

    Behaviour:
      1. If the conditionality dict has no structured trigger keys, or the trigger
         is for a different asset (cross-asset), return None (defer / route to QA).
      2. Scan the provided closes (for claim.asset) for the first daily close
         after uttered_at where the trigger fires.
      3. Trigger fires -> activation_date is that close's day.  Then resolve the
         underlying claim using the existing rule helpers over the default horizon
         measured from activation_date:
           - target_price set         -> resolve_target_by_deadline
           - target_price not set     -> resolve_directional_at_horizon
         The "default horizon" is determined from claim.horizon_basis using
         the published table (default_30d=30d, default_90d=90d, default_eoy=Dec 31
         of activation year).  If horizon_basis is "stated" and horizon_deadline
         is set, the STATED deadline is used as-is (the analyst already said when).
      4. Trigger never fires and the observation window is still open -> None
         (defer; claim remains open).
      5. Trigger never fires and the full observation window has elapsed ->
         return None AND the call-site (resolver) must mark the claim void
         (never scored; it is NOT a miss; METHODOLOGY.md §2.2 never-fires convention).
         This function signals void by returning a Resolution with outcome=-1.0
         and rule_id="conditional_void.v0".  The resolver treats outcome<0 as void.

    Rationale records: basis of horizon, activation date, trigger that fired,
    so the resolution is auditable (NFR-2).

    Cross-asset triggers (trigger_asset != claim.asset) are out of MVP scope and
    return None (defer to QA).

    rule_id = "conditional_at_horizon.v0"  (fired)
    rule_id = "conditional_void.v0"        (never-fires + window elapsed)
    """
    assert claim.asset is not None
    assert claim.direction is not None

    # ------------------------------------------------------------------
    # 1. Extract and validate the structured trigger.
    # ------------------------------------------------------------------
    trigger = _extract_structured_trigger(claim.conditionality, claim.asset)
    if trigger is None:
        # Text-only trigger or cross-asset trigger: defer to QA.
        return None

    uttered_day = claim.uttered_at.date()

    # ------------------------------------------------------------------
    # 2. Determine the observation window end.
    #    We use the effective horizon_deadline (materialised if needed)
    #    as the boundary by which the trigger must have fired.  If no
    #    deadline can be materialised, the full price history is the window.
    # ------------------------------------------------------------------
    effective_deadline = materialise_horizon_deadline(claim)
    if effective_deadline is None:
        # No observation window can be established; defer.
        return None

    # ------------------------------------------------------------------
    # 3. Scan for activation.
    # ------------------------------------------------------------------
    activation_date, window_elapsed = _find_activation(
        closes, uttered_day, trigger, effective_deadline
    )

    if activation_date is None:
        if window_elapsed:
            # The trigger never fired and the window has fully elapsed.
            # The claim never activated -> void, not scored (NOT a miss).
            trigger_desc = f"{trigger['trigger_direction']} {trigger['trigger_price']:.2f}"
            rationale = (
                f"VOID: conditional trigger ({claim.asset} {trigger_desc}) never fired"
                f" in the observation window [{uttered_day} .. {effective_deadline}]."
                f" Claim never activated; not scored (METHODOLOGY.md §2.2"
                f" never-fires convention)."
            )
            # outcome=-1 is the void signal; resolver maps this to status=void.
            return Resolution(
                claim_id=claim.id or 0,
                outcome=-1.0,
                resolved_at=datetime.now(UTC),
                rule_id="conditional_void.v0",
                rationale=rationale,
                price_citation={
                    "asset": claim.asset,
                    "observation_end": str(effective_deadline),
                    "trigger": trigger_desc,
                },
                methodology_version=METHODOLOGY_VERSION,
            )
        # Trigger not fired yet; window still open.
        return None

    # activation_date is a date (mypy narrows via the `is None` check above).

    # ------------------------------------------------------------------
    # 4. Compute the resolution horizon from the activation date.
    # ------------------------------------------------------------------
    basis = claim.horizon_basis
    resolution_deadline: date
    horizon_basis_note: str
    if basis == "stated" and claim.horizon_deadline is not None:
        # Analyst stated a concrete deadline; honour it.
        resolution_deadline = claim.horizon_deadline
        horizon_basis_note = f"stated deadline {resolution_deadline}"
    else:
        _maybe_deadline = _default_horizon_from_date(basis, activation_date)
        if _maybe_deadline is None:
            # Cannot compute a horizon; defer.
            return None
        resolution_deadline = _maybe_deadline
        horizon_basis_note = (
            f"basis={basis!r}, {resolution_deadline - activation_date} from"
            f" activation {activation_date}"
        )

    # ------------------------------------------------------------------
    # 5. Build a synthetic claim for the underlying rule, with activation
    #    date as the start and the computed resolution_deadline.
    # ------------------------------------------------------------------
    # We need a claim whose uttered_at = activation_date (for the price window)
    # and horizon_deadline = resolution_deadline.
    activation_dt = datetime.combine(activation_date, datetime.min.time()).replace(tzinfo=UTC)
    activated_claim = claim.model_copy(
        update={
            "uttered_at": activation_dt,
            "horizon_deadline": resolution_deadline,
        }
    )

    # Fetch closes from activation_date through resolution_deadline.
    resolution_closes = [c for c in closes if activation_date <= c.day <= resolution_deadline]

    # ------------------------------------------------------------------
    # 6. Apply the appropriate underlying rule.
    # ------------------------------------------------------------------
    trigger_desc = f"{trigger['trigger_direction']} {trigger['trigger_price']:.2f}"
    if claim.target_price is not None:
        base_res = resolve_target_by_deadline(activated_claim, resolution_closes)
    else:
        base_res = resolve_directional_at_horizon(activated_claim, resolution_closes)

    if base_res is None:
        # Underlying rule deferred (price data not yet available).
        return None

    # ------------------------------------------------------------------
    # 7. Augment the rationale with activation context (NFR-2 auditability).
    # ------------------------------------------------------------------
    activation_note = (
        f"CONDITIONAL: trigger ({claim.asset} {trigger_desc}) fired on"
        f" {activation_date} (first qualifying close after {uttered_day})."
        f" Scored over horizon [{activation_date} .. {resolution_deadline}]"
        f" ({horizon_basis_note}). "
    )
    augmented_rationale = activation_note + base_res.rationale

    return Resolution(
        claim_id=claim.id or 0,
        outcome=base_res.outcome,
        resolved_at=datetime.now(UTC),
        rule_id="conditional_at_horizon.v0",
        rationale=augmented_rationale,
        price_citation=dict(
            base_res.price_citation,
            activation_date=str(activation_date),
            trigger=trigger_desc,
        ),
        methodology_version=METHODOLOGY_VERSION,
    )


# ---------------------------------------------------------------------------
# EC-11 Reversal close (PRD §12 EC-11, METHODOLOGY.md §2.3, E4-T1)
# ---------------------------------------------------------------------------


def resolve_reversal_close(
    original_claim: Claim,
    closes: list[PriceDaily],
    reversal_date: date,
) -> Resolution | None:
    """Close the original claim at the reversal date, scored to that date.

    PRD EC-11: "Explicit reversal closes the original claim at the reversal date,
    scored to date; new claim opens."

    The original claim is resolved using its normal rule but with
    ``horizon_deadline`` clamped to the reversal_date (score-to-date).  The
    closes list should cover the original claim's utterance through
    reversal_date.

    rule_id = "reversal_close.v0"

    Returns None only if price data is insufficient to resolve even the clamped
    window (EC-8 deference).
    """
    assert original_claim.asset is not None
    assert original_claim.direction is not None

    # Clone the claim with the deadline clamped to the reversal date.
    clamped_claim = original_claim.model_copy(update={"horizon_deadline": reversal_date})

    sc = original_claim.specificity_class

    if sc == SpecificityClass.TARGET_DEADLINE or original_claim.target_price is not None:
        base_res = resolve_target_by_deadline(clamped_claim, closes)
    elif sc in (SpecificityClass.DIRECTION_ONLY, SpecificityClass.DIRECTION_MAGNITUDE):
        base_res = resolve_directional_at_horizon(clamped_claim, closes)
    elif sc == SpecificityClass.CONDITIONAL:
        base_res = resolve_conditional(clamped_claim, closes)
    else:
        # Non-falsifiable or unknown: cannot resolve.
        return None

    if base_res is None:
        return None

    # A reversed conditional original whose trigger never fired returns the void
    # sentinel (outcome=-1.0). It cannot be scored-to-date and must not be
    # inserted into the append-only ledger (resolutions.outcome CHECK is
    # {0, 0.5, 1}). Defer: the normal conditional path voids it on the main pass.
    if base_res.outcome < 0:
        return None

    # Prepend a reversal note to the rationale (NFR-2).
    reversal_note = (
        f"REVERSAL CLOSE (EC-11): original claim closed at reversal date"
        f" {reversal_date} (scored to date). "
    )
    augmented_rationale = reversal_note + base_res.rationale

    return Resolution(
        claim_id=original_claim.id or 0,
        outcome=base_res.outcome,
        resolved_at=datetime.now(UTC),
        rule_id="reversal_close.v0",
        rationale=augmented_rationale,
        price_citation=dict(
            base_res.price_citation,
            reversal_date=str(reversal_date),
        ),
        methodology_version=METHODOLOGY_VERSION,
    )


# ---------------------------------------------------------------------------
# Contradiction detection (EC-6, METHODOLOGY.md §2.4, E4-T4)
# ---------------------------------------------------------------------------


def _horizons_overlap_for_contradiction(a: Claim, b: Claim) -> bool:
    """Return True if two claims have overlapping horizon windows.

    A claim's window is [uttered_at.date(), materialised_deadline].
    When a materialised deadline cannot be computed (a "stated" claim with no
    stored deadline), the claim has no resolvable horizon — EC-6 requires an
    *overlapping horizon*, so overlap cannot be established and this returns
    False (the claim is left to the normal defer path, not voided as a hedge).
    A deadline-less claim never resolves, so it is not a functional hedge and
    excluding it opens no scoring dodge (METHODOLOGY.md §2.4).

    Uses materialise_horizon_deadline so that default-horizon claims (30d/90d/eoy)
    have their effective deadlines computed before the overlap test, consistent
    with the dedup overlap predicate in extraction/extractor.py (_horizons_overlap).
    """
    deadline_a = materialise_horizon_deadline(a)
    deadline_b = materialise_horizon_deadline(b)

    if deadline_a is None or deadline_b is None:
        # No computable horizon on at least one side -> overlap is not
        # establishable; not a contradiction (EC-6 needs overlapping horizons).
        return False

    start_a = a.uttered_at.date()
    start_b = b.uttered_at.date()
    # Intervals [start_a, deadline_a] and [start_b, deadline_b] overlap when
    # start_a <= deadline_b AND start_b <= deadline_a.
    return start_a <= deadline_b and start_b <= deadline_a


def detect_contradictions(claims: list[Claim]) -> list[Claim]:
    """EC-6: opposite-direction claims on the same asset with overlapping
    horizons void both and raise the hedging flag.

    Groups claims by (analyst_id, asset), then within each group finds pairs of
    claims with opposite directions (one bullish, one bearish) whose horizon
    windows overlap.  Both claims in each contradicting pair are returned with:
      - status = ClaimStatus.VOID
      - flags["hedging_contradiction"] = True
      - flags["void_rule_id"] = "contradiction_void.v0"  (NFR-2 audit trail)
      - flags["contradicts_claim_ids"] = [<ids of the contradicting claims>]

    Only open, publishable, falsifiable (not non_falsifiable, not already-void)
    claims are candidates for contradiction detection.  Claims already voided or
    having no direction are excluded.

    rule_id for the hedging void: "contradiction_void.v0"
    (METHODOLOGY.md §2.4)

    Precedence note: contradiction detection runs BEFORE the EC-11 reversal
    pre-pass.  A claim that is contradicted is voided here and will be skipped
    by the reversal pre-pass (which only acts on open claims).  Conversely, a
    claim whose original has already been reversal-closed is no longer open in
    the DB, so it will not appear in the candidate list passed to this function.

    Reversal claims exclusion: claims carrying flags["reverses_claim_id"] are
    position UPDATES (EC-11), not independent simultaneous bets; they are
    excluded from contradiction candidates so "bearish original + bullish
    reversal" is never treated as EC-6 hedging.

    Three-claim case precedence (documented choice):
      Given two bullish claims B1, B2 and one bearish claim X, all from the
      same analyst on the same asset with overlapping horizons: X contradicts
      BOTH B1 and B2 (pairwise).  All three claims are voided.  B1's flags
      record contradicts_claim_ids=[X.id], B2's flags record
      contradicts_claim_ids=[X.id], and X's flags record
      contradicts_claim_ids=[B1.id, B2.id].  This is the most conservative
      (analyst-protective) reading: every claim in a contradicting set is voided.

    This is a PURE function.  It does NOT touch the database.  It returns copies
    of the contradicting claims with in-memory mutations applied via model_copy.
    Input objects are never mutated.

    Args:
        claims: All open candidate claims for the current resolution run.

    Returns:
        A list of Claim objects (copies) with status=VOID and hedging flags set,
        one entry per claim that participates in at least one contradiction.
        Claims that do not contradict anything are NOT included.
    """
    # Only consider open, publishable claims that have a direction and are
    # falsifiable (non_falsifiable and already-void claims cannot contradict).
    # Reversal claims (flags["reverses_claim_id"] present) are explicitly
    # position updates, not independent simultaneous hedges; they are excluded
    # so that "bearish original + bullish reversal" is not treated as EC-6
    # hedging.  The EC-11 reversal pre-pass handles them separately.
    candidates: list[Claim] = [
        c
        for c in claims
        if c.status == ClaimStatus.OPEN
        and c.publishable
        and c.direction is not None
        and c.asset is not None
        and c.specificity_class != SpecificityClass.NON_FALSIFIABLE
        and c.flags.get("reverses_claim_id") is None
    ]

    # Group by (analyst_id, asset).
    # asset is not None for all candidates (filtered above); assert to narrow type.
    GroupKey = tuple[int, str]
    groups: dict[GroupKey, list[Claim]] = defaultdict(list)
    for claim in candidates:
        assert claim.asset is not None  # guaranteed by the filter above
        key: GroupKey = (claim.analyst_id, claim.asset)
        groups[key].append(claim)

    # For each group, find all pairwise contradictions:
    # opposite direction + overlapping horizons.
    # Build a mapping from claim id -> set of contradicting claim ids.
    # We use claim.id as the key; claims without an id are keyed by object identity.
    contradicted_by: dict[int | None, set[int | None]] = defaultdict(set)

    for group_claims in groups.values():
        bullish_claims = [c for c in group_claims if c.direction == "bullish"]
        bearish_claims = [c for c in group_claims if c.direction == "bearish"]

        for bull in bullish_claims:
            for bear in bearish_claims:
                if _horizons_overlap_for_contradiction(bull, bear):
                    contradicted_by[bull.id].add(bear.id)
                    contradicted_by[bear.id].add(bull.id)

    if not contradicted_by:
        return []

    # Build a lookup from claim id -> claim object (for the candidates).
    candidates_by_id: dict[int | None, Claim] = {c.id: c for c in candidates}

    # Return copies of every contradicting claim with status=VOID and flags set.
    result: list[Claim] = []
    for claim_id, contra_ids in contradicted_by.items():
        original = candidates_by_id.get(claim_id)
        if original is None:
            continue
        # Merge existing flags with hedging flags (do not lose prior flags).
        new_flags = dict(original.flags)
        new_flags["hedging_contradiction"] = True
        new_flags["void_rule_id"] = "contradiction_void.v0"  # NFR-2 audit trail (§2.4)
        new_flags["contradicts_claim_ids"] = sorted([cid for cid in contra_ids if cid is not None])
        voided_copy = original.model_copy(
            update={
                "status": ClaimStatus.VOID,
                "flags": new_flags,
            }
        )
        result.append(voided_copy)

    return result


# ---------------------------------------------------------------------------
# EC-1 Deletion persistence (PRD §12 EC-1, E4-T3)
# ---------------------------------------------------------------------------


def flag_source_deleted(flags: dict[str, Any]) -> dict[str, Any]:
    """EC-1: Mark a claim's flags to record that its source video was deleted/privated.

    The claim row itself is NEVER deleted (NFR-3 append-only ledger discipline).
    Any existing resolutions for the claim also persist.  Callers must write the
    returned dict back to claims.flags via _persist_claim_flags.

    PRD EC-1: "claim persists, source marked deleted, deletion flagged on receipt."
    The Video.source_status field (SourceStatus.DELETED / SourceStatus.PRIVATE) is
    the primary source-of-truth on the video row; this flag propagates the signal
    to the individual claim so receipt pages can surface it without a join.

    Returns:
        A new flags dict (copy) with source_deleted=True set.
    """
    new_flags = dict(flags)
    new_flags["source_deleted"] = True
    return new_flags


# ---------------------------------------------------------------------------
# EC-4 Sponsor segments (PRD §12 EC-4, E4-T3)
# ---------------------------------------------------------------------------


def flag_sponsor_segment(flags: dict[str, Any]) -> dict[str, Any]:
    """EC-4: Mark a claim as originating from a detected sponsor/ad segment.

    Claims inside sponsor reads are excluded from scoring (PRD EC-4: "perverse
    incentives").  The flag sets publishable=False upstream (extraction layer);
    the resolver never sees publishable=False claims (FR-203 gate).

    Callers must:
      1. Call this function on the claim's flags dict before the DB write.
      2. Set claim.publishable = False.

    Returns:
        A new flags dict (copy) with is_sponsor_segment=True set.
    """
    new_flags = dict(flags)
    new_flags["is_sponsor_segment"] = True
    return new_flags


# ---------------------------------------------------------------------------
# EC-9 Token death / stablecoin depeg (PRD §12 EC-9, E4-T3)
# ---------------------------------------------------------------------------


def resolve_token_death(claim: Claim, last_known_close: PriceDaily) -> Resolution:
    """EC-9: Resolve a claim on a dead or delisted token.

    PRD EC-9: "token death resolves bearish claims true / bullish false at deadline."
    This applies when an asset's price goes to (effectively) zero or is delisted
    (no further price data is available after a point).

    Convention (published, METHODOLOGY.md EC-9):
      - bearish claim  -> outcome 1.0  (price collapsed: the directional bet was correct)
      - bullish claim  -> outcome 0.0  (price collapsed: the target was never reached)

    This function is called when the call-site has established that the token is
    dead (e.g. the FakePriceSource / real price source returns no closes after a
    known delisting date, and the effective deadline has passed).  The
    last_known_close is the final available price data point, cited for auditability.

    rule_id = "token_death.v0"

    Args:
        claim:             The claim to resolve.
        last_known_close:  The last available daily close for this asset.

    Returns:
        A Resolution with outcome 1.0 (bearish) or 0.0 (bullish), citing the
        last known close and the token-death convention.
    """
    assert claim.asset is not None
    assert claim.direction is not None

    outcome = 1.0 if claim.direction == "bearish" else 0.0
    direction_result = "true" if claim.direction == "bearish" else "false"
    rationale = (
        f"TOKEN DEATH (EC-9): asset {claim.asset} delisted/dead after"
        f" {last_known_close.day} (last known close {last_known_close.close_usd:.4f})."
        f" {claim.direction.upper()} claim resolves {direction_result} per the"
        f" token-death convention (METHODOLOGY.md EC-9)."
    )
    return Resolution(
        claim_id=claim.id or 0,
        outcome=outcome,
        resolved_at=datetime.now(UTC),
        rule_id="token_death.v0",
        rationale=rationale,
        price_citation={
            "asset": claim.asset,
            "day": str(last_known_close.day),
            "close_usd": last_known_close.close_usd,
            "source": last_known_close.source,
            "convention": "token_death_v0",
        },
        methodology_version=METHODOLOGY_VERSION,
    )


# ---------------------------------------------------------------------------
# EC-10 Legal fast-track flag (PRD §12 EC-10, E4-T3)
# ---------------------------------------------------------------------------


def flag_legal_fast_track(flags: dict[str, Any], *, reason: str = "legal_review") -> dict[str, Any]:
    """EC-10: Mark a claim for fast-track legal/defamation review.

    PRD EC-10: "claim review fast-tracked; content stays up unless an extraction
    error is found; counsel notified per playbook."

    This flag routes the claim to the QA queue and suppresses publication
    until a reviewer with legal authority clears it.  Callers must also set
    claim.publishable = False.

    Args:
        flags:   Existing claim flags dict.
        reason:  Short description of why fast-track was triggered (default
                 "legal_review").  Must not contain buy/sell/hold language (AC-7).

    Returns:
        A new flags dict (copy) with legal_fast_track=True and
        legal_fast_track_reason=<reason>.
    """
    new_flags = dict(flags)
    new_flags["legal_fast_track"] = True
    new_flags["legal_fast_track_reason"] = reason
    return new_flags


# ---------------------------------------------------------------------------
# EC-12 Version-pinned dispute adjudication (PRD §12 EC-12, E4-T3)
# ---------------------------------------------------------------------------


def get_pinned_methodology_version(resolution: Resolution) -> str:
    """EC-12: Return the methodology_version pinned on a resolution at publication.

    PRD EC-12: "dispute adjudicated under the version in force at publication;
    both ledgers retained."  NFR-2: every published claim is reproducible.

    The Resolution row stamps methodology_version at insert time (append-only,
    NFR-3). A later methodology version bump does NOT retroactively change the
    pinned version on historical rows — the append-only ledger guarantees this.
    A dispute over a published outcome is always adjudicated against the version
    that was in force when that resolution row was written, not the current
    METHODOLOGY_VERSION.

    This is a trivial accessor by design: the guarantee is structural (NFR-3
    append-only), not algorithmic.  Having an explicit, named function makes
    the EC-12 contract testable and prevents callers from accidentally using
    config.METHODOLOGY_VERSION instead.

    Args:
        resolution:  A Resolution object (from the ledger or in-memory).

    Returns:
        The methodology_version string pinned on this resolution.
    """
    return resolution.methodology_version
