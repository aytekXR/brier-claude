"""Shared transcript/claim persistence helpers (plain SQL, caller owns the txn).

Single source of truth for the transcripts upsert and the FR-202 claims INSERT,
used by both the E1 demo thread (``brier_pipeline.demo``) and the live
transcribe/extract job handlers (``brier_pipeline.jobs.handlers``).  Keeping one
copy of the 24-column INSERT means a claims-schema change touches exactly one
SQL statement, and the demo and the production handler can never drift.

None of these helpers commit — the caller owns the transaction.  In the demo
each stage commits explicitly; under the worker (process_one) the whole job runs
inside one transaction that commits only on success (NFR-3 discipline for the
surrounding ledger writes; claims rows themselves are mutable).
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

from brier_pipeline.models import Claim


def upsert_transcript(
    cur: psycopg.Cursor[Any],
    video_id: int,
    source: str,
    storage_pointer: str,
    language: str = "en",
    quality_note: str | None = None,
) -> tuple[int, bool]:
    """Insert a transcript row if not already present; return (db_id, created).

    transcripts has UNIQUE(video_id, source), so a retried transcribe job reuses
    the existing row rather than raising a UniqueViolation (idempotent).
    """
    cur.execute(
        "select id from transcripts where video_id = %s and source = %s",
        (video_id, source),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row[0]), False

    cur.execute(
        """
        insert into transcripts (video_id, source, storage_pointer, language, quality_note)
        values (%s, %s, %s, %s, %s)
        returning id
        """,
        (video_id, source, storage_pointer, language, quality_note),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), True


def claim_exists(cur: psycopg.Cursor[Any], transcript_id: int, source_offset_seconds: int) -> bool:
    """Check whether a claim at this (transcript, offset) is already stored."""
    cur.execute(
        "select id from claims where transcript_id = %s and source_offset_seconds = %s",
        (transcript_id, source_offset_seconds),
    )
    return cur.fetchone() is not None


def insert_claim(
    cur: psycopg.Cursor[Any],
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    claim: Claim,
) -> int:
    """Insert a claim row and return its DB id."""
    conditionality = json.dumps(claim.conditionality) if claim.conditionality else None
    flags = json.dumps(claim.flags) if claim.flags else "{}"

    cur.execute(
        """
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction, target_price, magnitude_pct,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            conditionality, specificity_class,
            source_offset_seconds, quote,
            uttered_at, p0_price,
            extraction_confidence, model_version, prompt_version,
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s
        ) returning id
        """,
        (
            analyst_id,
            video_id,
            transcript_id,
            claim.asset,
            claim.direction,
            claim.target_price,
            claim.magnitude_pct,
            claim.horizon_deadline,
            claim.horizon_basis,
            claim.stated_confidence,
            claim.confidence_basis,
            conditionality,
            str(claim.specificity_class.value),
            claim.source_offset_seconds,
            claim.quote,
            claim.uttered_at,
            claim.p0_price,
            claim.extraction_confidence,
            claim.model_version,
            claim.prompt_version,
            str(claim.review_state.value),
            claim.publishable,
            str(claim.status.value),
            flags,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])
