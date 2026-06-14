"""New-upload poller: registry channels -> ingestion events (FR-102, HP-1).

Polling discipline (NFR-1, PRD §20):
  - Uses playlistItems (1 unit/page), NEVER search (100 units).
  - Staleness > 48h raises the freshness flag (NFR-1).
  - Poll latency <= 2h is a cron cadence concern; this module only provides
    the function. The poll_channels job is scheduled by the worker.

CI/tests exercise poll_registered_channels directly with FakeYouTubeClient
or a small in-test stub — _poll_channels_handler (and DataApiYouTubeClient)
are NOT used in tests. This is the mock-first seam.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from pydantic import BaseModel

from brier_pipeline import config
from brier_pipeline.ingestion import registry
from brier_pipeline.ingestion.youtube import DataApiYouTubeClient, YouTubeClient
from brier_pipeline.jobs import worker
from brier_pipeline.jobs.worker import enqueue_job

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class PollReport(BaseModel):
    """Summary returned by poll_registered_channels."""

    polled_channels: int
    new_videos: int
    transcribe_jobs_enqueued: int
    stale_channel_ids: list[int]


# ---------------------------------------------------------------------------
# Core polling function
# ---------------------------------------------------------------------------


def poll_registered_channels(
    client: YouTubeClient,
    conn: psycopg.Connection[Any] | None = None,
    *,
    now: datetime | None = None,
    freshness_hours: int = 48,
    default_lookback_hours: int = 168,
) -> PollReport:
    """Poll every active registry channel for new uploads.

    Caller-owns-transaction when conn is passed; opens+owns when None.

    For each ACTIVE analyst:
      1. Watermark = max(published_at) over existing DB videos, else
         now - timedelta(hours=default_lookback_hours).
      2. Fetch list_uploads_since(channel_id, watermark).
      3. Upsert each video (idempotent: existing videos are skipped).
         For each NEWLY created video, enqueue a 'transcribe' job.
      4. Staleness check (NFR-1): if (now - most_recent_upload) > freshness_hours,
         enqueue a 'freshness_check' job and record the analyst in stale_channel_ids.

    Returns PollReport; does NOT commit when conn is passed.

    Staleness > 48h raises the freshness flag (NFR-1); the <= 2h poll latency
    guarantee is a cron scheduling concern (the poll_channels job is scheduled
    by the worker cron at the desired cadence).
    """
    _now: datetime = now if now is not None else datetime.now(UTC)
    if _now.tzinfo is None:
        _now = _now.replace(tzinfo=UTC)

    _conn: psycopg.Connection[Any]
    if conn is not None:
        _conn = conn
        result = _poll_with_conn(client, _conn, _now, freshness_hours, default_lookback_hours)
        return result
    else:
        from brier_pipeline.db import connect

        _conn = connect()
        try:
            result = _poll_with_conn(client, _conn, _now, freshness_hours, default_lookback_hours)
            _conn.commit()
            return result
        finally:
            _conn.close()


def _poll_with_conn(
    client: YouTubeClient,
    conn: psycopg.Connection[Any],
    now: datetime,
    freshness_hours: int,
    default_lookback_hours: int,
) -> PollReport:
    """Internal: run the poll loop on a provided connection (no commit)."""
    analysts = registry.list_analysts(conn, status="active")

    polled_channels = 0
    new_videos = 0
    transcribe_jobs_enqueued = 0
    stale_channel_ids: list[int] = []

    for analyst in analysts:
        assert analyst.id is not None
        polled_channels += 1

        # 1. Compute watermark from existing DB videos for this analyst.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(published_at) FROM videos WHERE analyst_id = %s",
                (analyst.id,),
            )
            row = cur.fetchone()

        watermark_raw = row[0] if row else None
        if watermark_raw is not None:
            watermark: datetime = watermark_raw
            if watermark.tzinfo is None:
                watermark = watermark.replace(tzinfo=UTC)
        else:
            watermark = now - timedelta(hours=default_lookback_hours)

        # 2. Fetch new uploads since the watermark.
        videos = client.list_uploads_since(analyst.channel_id, watermark)

        # 3. Upsert each video; enqueue transcribe for newly created ones.
        for video in videos:
            video.analyst_id = analyst.id
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO videos
                        (analyst_id, youtube_video_id, title, published_at, source_status)
                    VALUES (%s, %s, %s, %s, 'live')
                    ON CONFLICT (youtube_video_id) DO NOTHING
                    RETURNING id
                    """,
                    (analyst.id, video.youtube_video_id, video.title, video.published_at),
                )
                inserted_row = cur.fetchone()

            if inserted_row is not None:
                # Newly created — enqueue a transcription job.
                new_vid_id = int(inserted_row[0])
                enqueue_job(
                    conn,
                    "transcribe",
                    {"video_id": new_vid_id, "youtube_video_id": video.youtube_video_id},
                )
                new_videos += 1
                transcribe_jobs_enqueued += 1

        # 4. Staleness check (NFR-1): look at the freshest upload in the DB
        #    now that we may have just inserted some.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(published_at) FROM videos WHERE analyst_id = %s",
                (analyst.id,),
            )
            post_row = cur.fetchone()

        most_recent_raw = post_row[0] if post_row else None

        is_stale: bool
        if most_recent_raw is None:
            # No uploads at all -> definitely stale.
            is_stale = True
        else:
            most_recent: datetime = most_recent_raw
            if most_recent.tzinfo is None:
                most_recent = most_recent.replace(tzinfo=UTC)
            is_stale = (now - most_recent) > timedelta(hours=freshness_hours)

        if is_stale:
            stale_channel_ids.append(analyst.id)
            enqueue_job(
                conn,
                "freshness_check",
                {"analyst_id": analyst.id, "channel_id": analyst.channel_id},
            )

    return PollReport(
        polled_channels=polled_channels,
        new_videos=new_videos,
        transcribe_jobs_enqueued=transcribe_jobs_enqueued,
        stale_channel_ids=stale_channel_ids,
    )


# ---------------------------------------------------------------------------
# Job handler (live path — CI uses FakeYouTubeClient directly)
# ---------------------------------------------------------------------------


def _poll_channels_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """Job handler for 'poll_channels'.

    Builds a DataApiYouTubeClient from the configured API key and calls
    poll_registered_channels with the caller-provided connection.

    CI/tests exercise poll_registered_channels directly with FakeYouTubeClient
    or a small in-test stub — this handler (and DataApiYouTubeClient) are
    NOT invoked in tests. This is the mock-first seam described in CLAUDE.md.
    """
    api_client = DataApiYouTubeClient(config.youtube_api_key())
    poll_registered_channels(api_client, conn)


# Register at module load so importing poller wires the handler automatically.
# The worker's run_forever() docstring documents: import poller before calling
# run_forever() to activate this handler.
worker.register_handler("poll_channels", _poll_channels_handler)
