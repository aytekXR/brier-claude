"""Pydantic contracts mirroring the database schema (migrations/*.sql).

These are data shapes only — no behavior. Field semantics live next to the
schema in the migration files and in docs/METHODOLOGY.md.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalystStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REMOVED = "removed"


class SourceStatus(StrEnum):
    """EC-1: claims persist when the source disappears; the deletion is flagged."""

    LIVE = "live"
    DELETED = "deleted"
    PRIVATE = "private"


class SpecificityClass(StrEnum):
    """METHODOLOGY.md §4 — drives specificity weight v."""

    DIRECTION_ONLY = "direction_only"
    DIRECTION_MAGNITUDE = "direction_magnitude"
    TARGET_DEADLINE = "target_deadline"
    CONDITIONAL = "conditional"
    NON_FALSIFIABLE = "non_falsifiable"


class ClaimStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    VOID = "void"


class ReviewState(StrEnum):
    """US-009/HP-4 QA queue decisions."""

    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    CORRECTED = "corrected"
    VOIDED = "voided"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Analyst(BaseModel):
    id: int | None = None
    channel_id: str
    display_name: str
    slug: str
    status: AnalystStatus = AnalystStatus.ACTIVE
    jurisdiction_flag: str | None = None


class Video(BaseModel):
    id: int | None = None
    analyst_id: int
    youtube_video_id: str
    title: str
    published_at: datetime
    duration_seconds: int | None = None
    source_status: SourceStatus = SourceStatus.LIVE
    sponsor_segments: list[dict[str, Any]] | None = None  # EC-4


class Transcript(BaseModel):
    id: int | None = None
    video_id: int
    source: Literal["captions", "whisper", "deepgram"]
    storage_pointer: str  # body lives in object storage; audio is transient (FR-103)
    language: str | None = None
    quality_note: str | None = None


class Claim(BaseModel):
    """FR-202 structured claim. Reproducible per NFR-2."""

    id: int | None = None
    analyst_id: int
    video_id: int
    transcript_id: int
    asset: str | None = None  # controlled vocabulary; None -> void (EC-7)
    direction: Literal["bullish", "bearish"] | None = None
    target_price: float | None = None
    magnitude_pct: float | None = None
    horizon_deadline: date | None = None
    horizon_basis: Literal["stated", "default_30d", "default_90d", "default_eoy"] | None = None
    stated_confidence: float | None = None  # stated or imputed (METHODOLOGY.md §1)
    confidence_basis: Literal["stated", "imputed_will", "imputed_likely"] | None = None
    conditionality: dict[str, Any] | None = None
    specificity_class: SpecificityClass
    source_offset_seconds: int  # receipt seek point (FR-403)
    quote: str | None = None  # verbatim, <= 15 words (NFR-4)
    extraction_confidence: float | None = None  # FR-203 threshold routing
    model_version: str
    prompt_version: str
    reviewer_id: str | None = None  # set when QA-touched (NFR-2)
    review_state: ReviewState = ReviewState.UNREVIEWED
    publishable: bool = False
    status: ClaimStatus = ClaimStatus.OPEN
    dedup_cluster_id: int | None = None  # FR-205
    flags: dict[str, Any] = Field(default_factory=dict)
    uttered_at: datetime
    p0_price: float | None = None


class PriceDaily(BaseModel):
    """FR-301 daily UTC close from the published composite source."""

    asset: str
    day: date
    close_usd: float
    source: str
    data_gap: bool = False  # EC-8


class Resolution(BaseModel):
    """Append-only ledger row (NFR-3). Corrections append a superseding row."""

    id: int | None = None
    claim_id: int
    outcome: float  # 0 | 0.5 | 1 (METHODOLOGY.md §2)
    resolved_at: datetime | None = None
    rule_id: str  # rule-library entry (FR-302)
    rationale: str
    price_citation: dict[str, Any]
    methodology_version: str
    supersedes_resolution_id: int | None = None


class ScoreRun(BaseModel):
    id: int | None = None
    methodology_version: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    trigger: Literal["nightly", "methodology_bump", "correction", "demo"]
    notes: str | None = None


class Score(BaseModel):
    """Append-only, methodology-versioned score ledger row (FR-304, AC-4)."""

    id: int | None = None
    score_run_id: int
    analyst_id: int
    methodology_version: str
    fas: float
    directional_skill: float
    calibration: float
    consistency: float
    falsifiability: float
    n_resolved: int
    provisional: bool  # two-tier rule, METHODOLOGY.md §6
    ranked: bool  # n >= 20 (FR-305)
    supersedes_score_id: int | None = None


class Dispute(BaseModel):
    """US-006/AC-5: tracked ticket with a 7-day SLA."""

    id: int | None = None
    ticket_code: str
    claim_id: int
    submitted_by: str | None = None
    rationale: str
    state: Literal["open", "adjudicating", "upheld", "corrected", "rejected"] = "open"
    sla_deadline: datetime
    submitted_at: datetime | None = None
    adjudicated_at: datetime | None = None
    adjudication_note: str | None = None
    methodology_version_at_publication: str | None = None  # EC-12


class Correction(BaseModel):
    """Public corrections-log entry (FR-405, NFR-3)."""

    id: int | None = None
    claim_id: int
    dispute_id: int | None = None
    summary: str
    superseded_resolution_id: int | None = None
    superseding_resolution_id: int | None = None
    published_at: datetime | None = None


class Job(BaseModel):
    """Postgres-backed job queue row; cron-style worker, no Celery."""

    id: int | None = None
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    run_at: datetime | None = None
    state: JobState = JobState.QUEUED
    attempts: int = 0
    last_error: str | None = None
