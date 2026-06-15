"""Nightly resolution job: open claims x prices -> appended outcomes (data flow 4)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from brier_pipeline.config import database_url
from brier_pipeline.models import Claim, ClaimStatus, Resolution, SpecificityClass
from brier_pipeline.resolution.prices import PriceSource
from brier_pipeline.resolution.rules import (
    detect_contradictions,
    materialise_horizon_deadline,
    resolve_conditional,
    resolve_directional_at_horizon,
    resolve_reversal_close,
    resolve_target_by_deadline,
)


def _load_open_claims(cur: psycopg.Cursor[Any]) -> list[Claim]:
    """Load open, publishable claims whose specificity_class is resolvable.

    Includes 'conditional' claims (E4-T1) while keeping 'non_falsifiable' excluded.
    """
    cur.execute(
        """
        select
            id, analyst_id, video_id, transcript_id,
            asset, direction, target_price, magnitude_pct,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            conditionality, specificity_class,
            source_offset_seconds, quote,
            uttered_at, p0_price,
            extraction_confidence, model_version, prompt_version,
            reviewer_id, review_state, publishable, status,
            dedup_cluster_id, flags
        from claims
        where status = 'open'
          and publishable = true
          and specificity_class != 'non_falsifiable'
        order by id
        """
    )
    rows = cur.fetchall()
    return _rows_to_claims(rows)


def _load_claims_by_ids(cur: psycopg.Cursor[Any], ids: list[int]) -> list[Claim]:
    """Load specific claims by ID (used by the reversal pre-pass)."""
    if not ids:
        return []
    cur.execute(
        """
        select
            id, analyst_id, video_id, transcript_id,
            asset, direction, target_price, magnitude_pct,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            conditionality, specificity_class,
            source_offset_seconds, quote,
            uttered_at, p0_price,
            extraction_confidence, model_version, prompt_version,
            reviewer_id, review_state, publishable, status,
            dedup_cluster_id, flags
        from claims
        where id = any(%s)
        order by id
        """,
        (ids,),
    )
    rows = cur.fetchall()
    return _rows_to_claims(rows)


def _rows_to_claims(rows: list[Any]) -> list[Claim]:
    """Build Claim objects from raw DB rows (shared by both load functions)."""
    claims: list[Claim] = []
    for row in rows:
        (
            claim_id,
            analyst_id,
            video_id,
            transcript_id,
            asset,
            direction,
            target_price,
            magnitude_pct,
            horizon_deadline,
            horizon_basis,
            stated_confidence,
            confidence_basis,
            conditionality,
            specificity_class,
            source_offset_seconds,
            quote,
            uttered_at,
            p0_price,
            extraction_confidence,
            model_version,
            prompt_version,
            reviewer_id,
            review_state,
            publishable,
            status,
            dedup_cluster_id,
            flags,
        ) = row
        claims.append(
            Claim(
                id=int(claim_id),
                analyst_id=int(analyst_id),
                video_id=int(video_id),
                transcript_id=int(transcript_id),
                asset=asset,
                direction=direction,
                target_price=float(target_price) if target_price is not None else None,
                magnitude_pct=float(magnitude_pct) if magnitude_pct is not None else None,
                horizon_deadline=horizon_deadline,
                horizon_basis=horizon_basis,
                stated_confidence=(
                    float(stated_confidence) if stated_confidence is not None else None
                ),
                confidence_basis=confidence_basis,
                conditionality=conditionality,
                specificity_class=SpecificityClass(specificity_class),
                source_offset_seconds=int(source_offset_seconds),
                quote=quote,
                uttered_at=uttered_at if uttered_at.tzinfo else uttered_at.replace(tzinfo=UTC),
                p0_price=float(p0_price) if p0_price is not None else None,
                extraction_confidence=float(extraction_confidence)
                if extraction_confidence is not None
                else None,
                model_version=str(model_version),
                prompt_version=str(prompt_version),
                reviewer_id=reviewer_id,
                review_state=review_state,
                publishable=bool(publishable),
                status=ClaimStatus(status),
                dedup_cluster_id=int(dedup_cluster_id) if dedup_cluster_id is not None else None,
                flags=flags if isinstance(flags, dict) else {},
            )
        )
    return claims


def _insert_resolution(cur: psycopg.Cursor[Any], res: Resolution) -> int:
    """Append a resolution row and return its DB id (append-only, NFR-3)."""
    cur.execute(
        """
        insert into resolutions (
            claim_id, outcome, resolved_at, rule_id, rationale,
            price_citation, methodology_version, supersedes_resolution_id
        ) values (%s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            res.claim_id,
            res.outcome,
            res.resolved_at or datetime.now(UTC),
            res.rule_id,
            res.rationale,
            json.dumps(res.price_citation),
            res.methodology_version,
            res.supersedes_resolution_id,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _mark_claim_resolved(cur: psycopg.Cursor[Any], claim_id: int) -> None:
    """Update the claim's status to 'resolved' (claims is mutable; ledger is not)."""
    cur.execute(
        "update claims set status = 'resolved' where id = %s",
        (claim_id,),
    )


def _mark_claim_void(cur: psycopg.Cursor[Any], claim_id: int) -> None:
    """Update the claim's status to 'void' (never activated; claims is mutable)."""
    cur.execute(
        "update claims set status = 'void' where id = %s",
        (claim_id,),
    )


def _persist_claim_flags(cur: psycopg.Cursor[Any], claim_id: int, flags: dict[str, Any]) -> None:
    """Write the full flags dict back to the claim row (claims is mutable)."""
    cur.execute(
        "update claims set flags = %s::jsonb where id = %s",
        (json.dumps(flags), claim_id),
    )


def _persist_horizon_deadline(cur: psycopg.Cursor[Any], claim_id: int, deadline: date) -> None:
    """Write the materialised horizon_deadline back to the claim row so
    receipts can display the computed deadline (claims is mutable)."""
    cur.execute(
        "update claims set horizon_deadline = %s where id = %s and horizon_deadline is null",
        (deadline, claim_id),
    )


def _dispatch(claim: Claim, prices: PriceSource, as_of: date) -> Resolution | None:
    """Route a claim to the appropriate rule and return a Resolution or None.

    E4-T1 additions:
    - Materialise horizon_deadline from horizon_basis before dispatching.
    - Include conditional claims: route to resolve_conditional.
    - Void signal: if resolve_conditional returns outcome=-1.0
      (conditional_void.v0), the resolver marks status=void.
    """
    # ------------------------------------------------------------------
    # Materialise default-horizon deadlines before the None guard.
    # ------------------------------------------------------------------
    effective_deadline = materialise_horizon_deadline(claim)
    asset = claim.asset
    if asset is None or effective_deadline is None:
        return None

    # Build a version of the claim with the effective deadline populated
    # so the rule functions see it.  We do NOT mutate the original object
    # here; DB persistence happens in the main loop.
    if claim.horizon_deadline != effective_deadline:
        claim = claim.model_copy(update={"horizon_deadline": effective_deadline})

    sc = claim.specificity_class

    # Conditional claims (E4-T1): the trigger is watched within the observation
    # window (to effective_deadline), but once it fires the scoring horizon runs
    # a FURTHER default horizon measured from the activation date, which can
    # extend past effective_deadline (METHODOLOGY.md §2.2). Fetch through as_of
    # (the latest available close) so a late-firing trigger still has its full
    # post-activation window; resolve_conditional enforces the observation
    # boundary itself. Truncating at effective_deadline would defer such claims
    # permanently.
    if sc == SpecificityClass.CONDITIONAL:
        cond_closes = prices.daily_closes(
            asset, claim.uttered_at.date(), max(effective_deadline, as_of)
        )
        return resolve_conditional(claim, cond_closes)

    # Fetch the full window: utterance date to deadline.
    all_closes = prices.daily_closes(asset, claim.uttered_at.date(), effective_deadline)

    # target_deadline or any claim with a target_price and a deadline.
    if sc == SpecificityClass.TARGET_DEADLINE or (
        claim.target_price is not None and claim.horizon_deadline is not None
    ):
        return resolve_target_by_deadline(claim, all_closes)

    # direction_only or direction_magnitude.
    if sc in (SpecificityClass.DIRECTION_ONLY, SpecificityClass.DIRECTION_MAGNITUDE):
        return resolve_directional_at_horizon(claim, all_closes)

    return None


def _run_contradiction_prepass(
    publishable_claims: list[Claim],
    active_conn: psycopg.Connection[Any],
) -> set[int]:
    """EC-6 contradiction pre-pass (E4-T4): detect hedging contradictions and
    void all claims that participate in them before the main resolution loop.

    Calls detect_contradictions (pure function in rules.py) over all open
    publishable claims.  For each returned (contradiction-voided) claim:
      1. Updates claims.status = 'void' in the DB.
      2. Persists the hedging flags (hedging_contradiction, contradicts_claim_ids)
         to claims.flags via UPDATE (claims is mutable; NFR-3 applies only to
         resolutions/scores).

    Returns the set of claim IDs that were voided by this pre-pass, so the main
    loop and the reversal pre-pass can skip them.

    Precedence vs EC-11 reversal pre-pass:
      Contradiction detection runs FIRST (before reversal).  A claim that is
      voided as a contradiction must not be reversal-closed too — that would
      produce a resolution row for a voided claim, which violates the rule that
      contradiction-voided claims are never scored.  The reversal pre-pass guards
      against double-processing by checking original.status != ClaimStatus.OPEN
      before acting; since we set status='void' here the reversal pre-pass
      naturally skips already-voided claims.  We additionally return the voided
      set so the main loop can skip them without a DB re-read.
    """
    contradicted: list[Claim] = detect_contradictions(publishable_claims)
    if not contradicted:
        return set()

    voided_ids: set[int] = set()
    for voided_claim in contradicted:
        if voided_claim.id is None:
            continue
        with active_conn.cursor() as cur:
            _mark_claim_void(cur, voided_claim.id)
            _persist_claim_flags(cur, voided_claim.id, voided_claim.flags)
        voided_ids.add(voided_claim.id)

    return voided_ids


def _run_reversal_prepass(
    publishable_claims: list[Claim],
    prices: PriceSource,
    active_conn: psycopg.Connection[Any],
) -> list[Resolution]:
    """EC-11 reversal pre-pass: for each publishable claim with
    flags["reverses_claim_id"], close the referenced original claim at the
    reversal date (scored to date) if the original is still open.

    Appends the reversal-close resolution and marks the original resolved.
    Returns the list of appended reversal resolutions.
    """
    appended: list[Resolution] = []

    # Collect original claim IDs referenced by reversal claims.
    reversal_pairs: list[tuple[Claim, int]] = []
    for claim in publishable_claims:
        reverses_id = claim.flags.get("reverses_claim_id")
        if reverses_id is not None:
            reversal_pairs.append((claim, int(reverses_id)))

    if not reversal_pairs:
        return appended

    original_ids = [orig_id for _, orig_id in reversal_pairs]
    with active_conn.cursor() as cur:
        originals = _load_claims_by_ids(cur, original_ids)

    originals_by_id = {c.id: c for c in originals if c.id is not None}

    # Guard against two reversal claims pointing at the same original: the
    # in-memory Claim status is not refreshed after the first close, so without
    # this set the second iteration would append a duplicate reversal_close.v0
    # row (the append-only ledger would not reject it).
    already_closed: set[int] = set()

    for reversal_claim, orig_id in reversal_pairs:
        if orig_id in already_closed:
            continue
        original = originals_by_id.get(orig_id)
        if original is None:
            # Original not found; skip.
            continue
        if original.status != ClaimStatus.OPEN:
            # Already resolved or voided; skip.
            continue

        # Reversal date = the new claim's uttered_at.
        reversal_date = reversal_claim.uttered_at.date()

        assert original.asset is not None
        # Fetch price data from original utterance through reversal date.
        closes = prices.daily_closes(original.asset, original.uttered_at.date(), reversal_date)

        res = resolve_reversal_close(original, closes, reversal_date)
        if res is None:
            # Price data insufficient; defer.
            continue

        assert original.id is not None
        res.claim_id = original.id
        with active_conn.cursor() as cur:
            res_id = _insert_resolution(cur, res)
            res.id = res_id
            _mark_claim_resolved(cur, original.id)
        already_closed.add(orig_id)
        appended.append(res)

    return appended


def resolve_open_claims(
    prices: PriceSource,
    conn: psycopg.Connection[Any] | None = None,
    as_of: date | None = None,
) -> list[Resolution]:
    """Join open claims against daily closes and append resolutions.

    Append-only: corrections never mutate; they append a superseding row
    (NFR-3). Stale or gapped price data defers resolution, never improvises
    (EC-8). Returns the resolutions appended in this run.

    Accepts an optional psycopg connection so tests can pass the rollback
    connection (db_conn fixture). When conn is None, opens a real connection.

    as_of defaults to the latest close date available from the price source.

    E4-T1 additions:
    - Reversal pre-pass: close original claims referenced by reverses_claim_id
      before the main dispatch loop.
    - Default-horizon materialisation: compute effective deadlines for claims
      whose horizon_deadline is None but horizon_basis is a default convention.
    - Persist materialised deadlines back to the claims table (claims is mutable).
    - Conditional claims now included in the open-claims query.
    - Conditional void signal (outcome=-1.0) marks the claim void (not resolved).
    """
    # Determine as_of from the price source if not supplied.
    if as_of is None:
        # Use BTC as the reference asset for the latest available date.
        sample_end = date(2030, 1, 1)
        sample_start = date(2024, 1, 1)
        all_btc = prices.daily_closes("BTC", sample_start, sample_end)
        if all_btc:
            as_of = max(c.day for c in all_btc)
        else:
            as_of = date.today()

    if conn is None:
        own_conn = True
        active_conn: psycopg.Connection[Any] = psycopg.connect(database_url())
    else:
        own_conn = False
        active_conn = conn

    appended: list[Resolution] = []

    try:
        with active_conn.cursor() as cur:
            claims = _load_open_claims(cur)

        # ------------------------------------------------------------------
        # EC-6 contradiction pre-pass (E4-T4): void hedging claims first.
        # Must run BEFORE the reversal pre-pass so that contradicted claims
        # are already voided when the reversal pre-pass checks their status.
        # ------------------------------------------------------------------
        contradiction_voided_ids: set[int] = _run_contradiction_prepass(claims, active_conn)

        # ------------------------------------------------------------------
        # EC-11 reversal pre-pass (E4-T1): close originals before main loop.
        # The reversal pre-pass guards against acting on already-voided claims
        # by checking original.status == ClaimStatus.OPEN; contradiction-voided
        # claims already have status='void' in the DB (set above) so they will
        # be skipped naturally.
        # ------------------------------------------------------------------
        reversal_resolutions = _run_reversal_prepass(claims, prices, active_conn)
        appended.extend(reversal_resolutions)

        # Track which claim IDs were closed by the reversal pre-pass so the
        # main loop skips them.
        reversal_closed_ids: set[int] = {r.claim_id for r in reversal_resolutions}

        for claim in claims:
            # Idempotency: already-resolved claims are never re-resolved.
            if claim.status != ClaimStatus.OPEN:
                continue
            assert claim.id is not None
            # Skip claims voided by the contradiction pre-pass.
            if claim.id in contradiction_voided_ids:
                continue
            if claim.id in reversal_closed_ids:
                continue

            resolution = _dispatch(claim, prices, as_of)
            if resolution is None:
                # Open deadline or price gap (EC-8): defer, never improvise.
                continue

            # ------------------------------------------------------------------
            # Handle conditional void signal (conditional_void.v0 rule_id).
            # The claim never activated; mark it void without inserting a
            # resolution row (the check constraint on resolutions.outcome
            # only permits 0, 0.5, 1; voids are not scored).
            # ------------------------------------------------------------------
            if resolution.rule_id == "conditional_void.v0":
                # Conditional claim never activated; mark void (not scored, not missed).
                resolution.claim_id = claim.id
                with active_conn.cursor() as cur:
                    _mark_claim_void(cur, claim.id)
                # Return the void sentinel in the appended list so callers
                # can detect it (outcome is not written to the DB).
                appended.append(resolution)
                continue

            # ------------------------------------------------------------------
            # Persist materialised horizon_deadline back to the claim (E4-T1).
            # This keeps the claims table in sync so receipts show the computed
            # deadline; claims is mutable (NFR-3 applies only to resolutions/scores).
            # materialise_horizon_deadline is pure and the original `claim` object
            # is never mutated, so this re-derives the same value _dispatch used.
            # ------------------------------------------------------------------
            materialised = materialise_horizon_deadline(claim)
            if materialised is not None and claim.horizon_deadline is None:
                with active_conn.cursor() as cur:
                    _persist_horizon_deadline(cur, claim.id, materialised)

            # Append resolution and flip claim status.
            resolution.claim_id = claim.id
            with active_conn.cursor() as cur:
                res_id = _insert_resolution(cur, resolution)
                resolution.id = res_id
                _mark_claim_resolved(cur, claim.id)
            appended.append(resolution)

        if own_conn:
            active_conn.commit()

    finally:
        if own_conn:
            active_conn.close()

    return appended
