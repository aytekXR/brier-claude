"""Historical backfill crawler: trailing 24 months per analyst (FR-104, G3, NFR-5).

Design notes
------------
- FR-104: Index the trailing 24-month window of public uploads for every analyst.
- G3: Keep ingestion costs within quota budgets.
- NFR-5: Hard per-run cap (max_videos) prevents a single crawl from exhausting
  quota or budget; residual videos are left for the next run (resumability).
- Resumable: each call skips youtube_video_ids already present in the DB,
  so re-running after an interruption continues from where the last run stopped.
- Caption-first transcription strategy is the TRANSCRIBE handler's concern (E2-T4);
  this module only ENQUEUEs 'transcribe' jobs and does NOT acquire audio/captions.
"""

from __future__ import annotations

from typing import Any

import psycopg
from pydantic import BaseModel

from brier_pipeline.ingestion import registry
from brier_pipeline.ingestion.youtube import YouTubeClient
from brier_pipeline.jobs.worker import enqueue_job

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class BackfillReport(BaseModel):
    """Summary returned by backfill_channel."""

    channel_id: str
    videos_in_window: int  # total videos returned by list_all_uploads
    new_videos: int  # videos inserted this run
    transcribe_jobs_enqueued: int
    capped: bool  # True when max_videos was hit and more remained
    remaining: int  # window videos not yet in the DB after this run


# ---------------------------------------------------------------------------
# Core backfill function
# ---------------------------------------------------------------------------


def backfill_channel(
    client: YouTubeClient,
    channel_id: str,
    conn: psycopg.Connection[Any] | None = None,
    *,
    months: int = 24,
    max_videos: int | None = None,
) -> BackfillReport:
    """Ingest all public uploads in the trailing *months* window for one channel.

    FR-104 / G3 / NFR-5:
      - Fetches the trailing *months* (default 24) window via
        client.list_all_uploads(channel_id, months).
      - RESUMABLE: videos whose youtube_video_id already exists in the DB are
        skipped; a re-run picks up where the previous run left off.
      - CAPPED: at most *max_videos* NEW videos are inserted per call (NFR-5
        cost guardrail).  If the cap is hit and more new videos remain, capped
        is set to True and remaining reflects the count still to be ingested.
      - Caption-first transcription is the 'transcribe' job handler's concern
        (E2-T4); this function only ENQUEUEs 'transcribe' jobs.

    Args:
        client: YouTubeClient implementation (FakeYouTubeClient in CI/demo;
                DataApiYouTubeClient in production, tested with injected http_get).
        channel_id: YouTube channel ID (must be registered in the analysts table).
        conn: Caller-owned psycopg connection; caller is responsible for
              commit/rollback.  When None, opens and owns its own connection.
        months: Trailing window size in months (default 24, FR-104).
        max_videos: Maximum NEW videos to insert this run (NFR-5 cost cap).
                    None means unlimited.

    Returns:
        BackfillReport with counts and cap/remaining info.

    Raises:
        ValueError: if channel_id is not registered in the analysts table.
    """
    if conn is not None:
        return _backfill_with_conn(client, channel_id, conn, months=months, max_videos=max_videos)

    from brier_pipeline.db import connect

    _conn: psycopg.Connection[Any] = connect()
    try:
        report = _backfill_with_conn(
            client, channel_id, _conn, months=months, max_videos=max_videos
        )
        _conn.commit()
        return report
    finally:
        _conn.close()


def _backfill_with_conn(
    client: YouTubeClient,
    channel_id: str,
    conn: psycopg.Connection[Any],
    *,
    months: int,
    max_videos: int | None,
) -> BackfillReport:
    """Internal: run the backfill on a provided connection (no commit)."""
    # 1. Resolve the analyst — must be registered.
    analyst = registry.get_analyst(conn, channel_id=channel_id)
    if analyst is None:
        raise ValueError(
            f"channel_id {channel_id!r} is not registered in the analysts table. "
            "Register it via registry.add_analyst() before backfilling."
        )
    assert analyst.id is not None
    analyst_id: int = analyst.id

    # 2. Fetch all uploads in the window.
    videos = client.list_all_uploads(channel_id, months)
    videos_in_window = len(videos)

    # 3. Check which youtube_video_ids already exist in the DB (resumability).
    #    Build the set from the DB to avoid O(N) queries inside the loop.
    existing_ids: set[str] = set()
    if videos:
        yt_ids = [v.youtube_video_id for v in videos]
        # Use ANY with a parameterised array — works for all list sizes.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT youtube_video_id FROM videos WHERE youtube_video_id = ANY(%s)",
                (yt_ids,),
            )
            existing_ids = {str(row[0]) for row in cur.fetchall()}

    # 4. Insert new videos up to the cap; enqueue 'transcribe' for each.
    new_videos = 0
    transcribe_jobs_enqueued = 0
    capped = False

    for video in videos:
        if video.youtube_video_id in existing_ids:
            continue  # already ingested — skip (resumability)

        if max_videos is not None and new_videos >= max_videos:
            # Cap hit — remaining videos left for the next run.
            capped = True
            break

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO videos
                    (analyst_id, youtube_video_id, title, published_at, source_status)
                VALUES (%s, %s, %s, %s, 'live')
                ON CONFLICT (youtube_video_id) DO NOTHING
                RETURNING id
                """,
                (analyst_id, video.youtube_video_id, video.title, video.published_at),
            )
            inserted_row = cur.fetchone()

        if inserted_row is not None:
            new_vid_id = int(inserted_row[0])
            enqueue_job(
                conn,
                "transcribe",
                {"video_id": new_vid_id, "youtube_video_id": video.youtube_video_id},
            )
            new_videos += 1
            transcribe_jobs_enqueued += 1
            existing_ids.add(video.youtube_video_id)  # keep the set consistent

    # 5. Compute remaining: window videos not yet in the DB after this run.
    #    Re-query existing to get the current state.
    remaining_count = 0
    if videos:
        yt_ids_all = [v.youtube_video_id for v in videos]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT youtube_video_id FROM videos WHERE youtube_video_id = ANY(%s)",
                (yt_ids_all,),
            )
            now_in_db = {str(row[0]) for row in cur.fetchall()}
        remaining_count = sum(1 for v in videos if v.youtube_video_id not in now_in_db)

    return BackfillReport(
        channel_id=channel_id,
        videos_in_window=videos_in_window,
        new_videos=new_videos,
        transcribe_jobs_enqueued=transcribe_jobs_enqueued,
        capped=capped,
        remaining=remaining_count,
    )
