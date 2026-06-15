"""Deletion sweep: detect deleted/private YouTube videos and propagate flags (EC-1, AC-6).

PRD EC-1: claims and resolutions PERSIST when a source disappears; the
deletion is flagged on the video row (videos.source_status) and on every
claim of that video (claims.flags['source_deleted']=True).

Architecture (mock-first):
  VideoStatusProbe — Protocol with check_video_status(youtube_video_id) -> SourceStatus.
  FakeYouTubeClient and DataApiYouTubeClient both implement this concrete method.
  The live job handler builds DataApiYouTubeClient; CI tests inject a fake probe.

Append-only ledger discipline (NFR-3):
  videos and claims are MUTABLE working state (UPDATEs are allowed).
  resolutions and scores are NEVER updated or deleted.

Handler registration (precedent: poller.py):
  'deletion_sweep' is registered at module load via worker.register_handler().
  Import this module before run_forever() to wire the handler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from brier_pipeline import config
from brier_pipeline.ingestion.youtube import DataApiYouTubeClient
from brier_pipeline.jobs import worker
from brier_pipeline.models import SourceStatus
from brier_pipeline.resolution.rules import flag_source_deleted

# ---------------------------------------------------------------------------
# VideoStatusProbe Protocol
# ---------------------------------------------------------------------------


class VideoStatusProbe(Protocol):
    """Minimal interface for checking the live status of a YouTube video (EC-1).

    Both FakeYouTubeClient and DataApiYouTubeClient implement check_video_status
    as a concrete method (not on the ABC so existing stubs are unbroken).
    """

    def check_video_status(self, youtube_video_id: str) -> SourceStatus:
        """Return the current SourceStatus of a YouTube video."""
        ...


# ---------------------------------------------------------------------------
# DeletionReport
# ---------------------------------------------------------------------------


@dataclass
class DeletionReport:
    """Summary of a deletion sweep run (EC-1).

    Attributes:
        checked:        Total live videos polled.
        newly_deleted:  Videos now set to DELETED.
        newly_private:  Videos now set to PRIVATE.
        unchanged:      Videos that remained LIVE.
    """

    checked: int
    newly_deleted: int
    newly_private: int
    unchanged: int


# ---------------------------------------------------------------------------
# Core sweep function
# ---------------------------------------------------------------------------


def run_deletion_sweep(
    probe: VideoStatusProbe,
    conn: Any,
    *,
    now: datetime | None = None,
) -> DeletionReport:
    """Check all live videos against the probe and update source_status + claim flags.

    Selects all videos WHERE source_status='live', calls probe.check_video_status
    for each.  When status != LIVE:
      1. UPDATE videos SET source_status = <new_status> WHERE id = <id>
         (videos is mutable working state, not the append-only ledger).
      2. For every claim of that video, propagate the EC-1 flag:
           new_flags = flag_source_deleted(existing_flags)
           UPDATE claims SET flags = <new_flags>::jsonb WHERE id = <claim_id>

    NEVER deletes or updates resolutions or scores (NFR-3).

    Args:
        probe:  VideoStatusProbe implementation (real or injected fake).
        conn:   psycopg connection; caller owns the transaction (no commit here).
        now:    Optional override for the current UTC time (unused in this
                implementation but accepted for parity with other sweep functions).

    Returns:
        DeletionReport with per-outcome counts.
    """
    _now = now or datetime.now(UTC)
    _ = _now  # accepted but not stored in this implementation

    with conn.cursor() as cur:
        cur.execute("SELECT id, youtube_video_id FROM videos WHERE source_status = 'live'")
        live_rows: list[tuple[int, str]] = cur.fetchall()

    newly_deleted = 0
    newly_private = 0
    unchanged = 0

    for video_id, yt_id in live_rows:
        status = probe.check_video_status(yt_id)

        if status == SourceStatus.LIVE:
            unchanged += 1
            continue

        # Update the video row (mutable working state, NFR-3 does not apply).
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE videos SET source_status = %s WHERE id = %s",
                (status.value, video_id),
            )

        # Propagate EC-1 flag to all claims for this video.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, flags FROM claims WHERE video_id = %s",
                (video_id,),
            )
            claim_rows: list[tuple[int, Any]] = cur.fetchall()

        for claim_id, raw_flags in claim_rows:
            # raw_flags may be a dict (psycopg JSONB) or a JSON string.
            if isinstance(raw_flags, str):
                existing_flags: dict[str, Any] = json.loads(raw_flags)
            elif isinstance(raw_flags, dict):
                existing_flags = raw_flags
            else:
                existing_flags = {}

            new_flags = flag_source_deleted(existing_flags)

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE claims SET flags = %s::jsonb WHERE id = %s",
                    (json.dumps(new_flags), claim_id),
                )

        if status == SourceStatus.DELETED:
            newly_deleted += 1
        else:
            newly_private += 1

    return DeletionReport(
        checked=len(live_rows),
        newly_deleted=newly_deleted,
        newly_private=newly_private,
        unchanged=unchanged,
    )


# ---------------------------------------------------------------------------
# Job handler (live path — CI uses an injected fake probe)
# ---------------------------------------------------------------------------


def _deletion_sweep_handler(payload: dict[str, Any], conn: Any) -> None:
    """Job handler for 'deletion_sweep' (live path only; CI injects a fake probe).

    Builds DataApiYouTubeClient from config.youtube_api_key() and calls
    run_deletion_sweep.  This handler is NOT invoked in tests.
    """
    client = DataApiYouTubeClient(config.youtube_api_key())
    run_deletion_sweep(client, conn)


# Register at module load so importing deletion wires the handler automatically.
worker.register_handler("deletion_sweep", _deletion_sweep_handler)
