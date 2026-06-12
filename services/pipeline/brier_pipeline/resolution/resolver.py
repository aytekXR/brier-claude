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
    resolve_directional_at_horizon,
    resolve_target_by_deadline,
)


def _load_open_claims(cur: psycopg.Cursor[Any]) -> list[Claim]:
    """Load open, publishable claims whose specificity_class is resolvable by v0 rules."""
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
          and specificity_class not in ('non_falsifiable', 'conditional')
        order by id
        """
    )
    rows = cur.fetchall()
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


def _dispatch(claim: Claim, prices: PriceSource, as_of: date) -> Resolution | None:
    """Route a claim to the appropriate rule and return a Resolution or None."""
    if claim.asset is None or claim.horizon_deadline is None:
        return None

    # Fetch the full window: utterance date to deadline (miss-detection needs the deadline day;
    # the rules themselves handle deadlines beyond as_of by returning None).
    all_closes = prices.daily_closes(claim.asset, claim.uttered_at.date(), claim.horizon_deadline)

    sc = claim.specificity_class

    # target_deadline or any claim with a target_price and a deadline
    if sc == SpecificityClass.TARGET_DEADLINE or (
        claim.target_price is not None and claim.horizon_deadline is not None
    ):
        return resolve_target_by_deadline(claim, all_closes)

    # direction_only or direction_magnitude
    if sc in (SpecificityClass.DIRECTION_ONLY, SpecificityClass.DIRECTION_MAGNITUDE):
        return resolve_directional_at_horizon(claim, all_closes)

    return None


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

        for claim in claims:
            # Idempotency: already-resolved claims are never re-resolved.
            # (_load_open_claims already filters for status='open', but be defensive.)
            if claim.status != ClaimStatus.OPEN:
                continue

            resolution = _dispatch(claim, prices, as_of)
            if resolution is None:
                # Open deadline or price gap (EC-8): defer, never improvise.
                continue

            # Append resolution and flip claim status.
            assert claim.id is not None
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
