"""T2 regression: backfill boundary cases — max_videos=0, max_videos=1, resumability watermark.

Cluster: backfill | DB prefix: UC-t2-bf

All DB-backed tests request db_conn and rely on fixture rollback; no residue is left.
Mirrors style of tests/test_backfill.py — synthetic client, no network, no real YouTube API.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from brier_pipeline.ingestion.backfill import backfill_channel
from brier_pipeline.ingestion.registry import add_analyst
from brier_pipeline.ingestion.youtube import YouTubeClient
from brier_pipeline.models import Video

# ---------------------------------------------------------------------------
# Cluster-namespaced channel IDs (all must start with 'UC' for scope-lock guard)
# ---------------------------------------------------------------------------

_CHAN_ZERO_CAP = "UC-t2-bf-zero-0001"
_CHAN_ONE_CAP = "UC-t2-bf-one-0002"
_CHAN_RESUME = "UC-t2-bf-resume-0003"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _SyntheticClient(YouTubeClient):
    """Stub returning configured Videos for one channel, [] for any other."""

    def __init__(self, channel_id: str, videos: list[Video]) -> None:
        self._channel_id = channel_id
        self._videos = videos

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        raise NotImplementedError

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        if channel_id == self._channel_id:
            return list(self._videos)
        return []

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        raise NotImplementedError


def _make_videos(vid_prefix: str, n: int) -> list[Video]:
    """Return n synthetic Videos with cluster-namespaced youtube_video_ids."""
    base = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
    return [
        Video(
            analyst_id=0,
            youtube_video_id=f"{vid_prefix}-vid-{i:03d}",
            title=f"T2 Backfill Video {i}",
            published_at=base - timedelta(days=i),
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Test 1 — max_videos=0: degenerate cap (processes nothing, does not raise)
# ---------------------------------------------------------------------------


def test_backfill_max_videos_zero_enqueues_nothing(db_conn: Any) -> None:
    """max_videos=0 must not raise and must insert/enqueue zero videos.

    Guards the degenerate cap boundary: even when K>0 videos are available in
    the window, a cap of 0 means nothing is inserted or enqueued.
    """
    K = 4  # videos the client returns — all new, none in DB yet

    add_analyst(
        db_conn,
        channel_id=_CHAN_ZERO_CAP,
        display_name="T2 BF Zero Cap",
        slug="t2-bf-zero-0001",
        status="active",
    )
    videos = _make_videos("BF-t2bf-zero", K)
    client = _SyntheticClient(_CHAN_ZERO_CAP, videos)

    # Must not raise even though K new videos are available.
    report = backfill_channel(client, _CHAN_ZERO_CAP, db_conn, months=24, max_videos=0)

    assert report.videos_in_window == K
    assert report.new_videos == 0, f"Expected 0 new videos, got {report.new_videos}"
    assert report.transcribe_jobs_enqueued == 0, (
        f"Expected 0 jobs enqueued, got {report.transcribe_jobs_enqueued}"
    )
    # The cap was hit on the first candidate video, so capped=True and all K remain.
    assert report.capped is True
    assert report.remaining == K

    # Confirm no 'transcribe' jobs were inserted for our namespaced video IDs.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' LIKE 'BF-t2bf-zero%'",
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 0, f"Expected 0 transcribe jobs in DB, found {row[0]}"


# ---------------------------------------------------------------------------
# Test 2 — max_videos=1: exactly one video processed, not zero, not many
# ---------------------------------------------------------------------------


def test_backfill_max_videos_one_processes_exactly_one(db_conn: Any) -> None:
    """max_videos=1 must insert EXACTLY one video when several are available.

    Pins the single-video boundary: not zero (cap not applied before any insert),
    and not two or more (cap respected after the first insert).
    """
    K = 5  # several videos available — all new

    add_analyst(
        db_conn,
        channel_id=_CHAN_ONE_CAP,
        display_name="T2 BF One Cap",
        slug="t2-bf-one-0002",
        status="active",
    )
    videos = _make_videos("BF-t2bf-one", K)
    client = _SyntheticClient(_CHAN_ONE_CAP, videos)

    report = backfill_channel(client, _CHAN_ONE_CAP, db_conn, months=24, max_videos=1)

    assert report.videos_in_window == K
    assert report.new_videos == 1, f"Expected exactly 1 new video, got {report.new_videos}"
    assert report.transcribe_jobs_enqueued == 1, (
        f"Expected 1 transcribe job enqueued, got {report.transcribe_jobs_enqueued}"
    )
    assert report.capped is True, "Expected capped=True when cap was hit"
    assert report.remaining == K - 1, f"Expected {K - 1} remaining, got {report.remaining}"

    # Confirm exactly one transcribe job row in the DB for our namespace.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' LIKE 'BF-t2bf-one%'",
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 1, f"Expected 1 transcribe job in DB, found {row[0]}"

    # Confirm exactly one videos row was inserted.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM videos WHERE youtube_video_id LIKE 'BF-t2bf-one%'",
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 1, f"Expected 1 video row in DB, found {row[0]}"


# ---------------------------------------------------------------------------
# Test 3 — resumability watermark: pre-ingested videos are skipped
# ---------------------------------------------------------------------------


def test_backfill_resumability_watermark_skips_preingested(db_conn: Any) -> None:
    """Pre-existing DB videos are skipped; only genuinely new ones are inserted.

    This covers the resumability watermark in _backfill_with_conn: step 3 queries
    existing youtube_video_ids and the loop skips any video already present. A
    second run (or any run after a partial ingest) must not duplicate rows or
    re-enqueue transcription jobs for videos already in the DB.

    Setup: manually insert N_PRE of the K videos directly (simulating a previous
    partial run), then call backfill_channel and assert only K-N_PRE are inserted.
    """
    K = 5
    N_PRE = 2  # videos pre-inserted before backfill_channel is called

    analyst_id = add_analyst(
        db_conn,
        channel_id=_CHAN_RESUME,
        display_name="T2 BF Resume",
        slug="t2-bf-resume-0003",
        status="active",
    )

    videos = _make_videos("BF-t2bf-res", K)

    # Pre-insert N_PRE videos directly — these should be detected and skipped.
    for v in videos[:N_PRE]:
        with db_conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO videos
                    (analyst_id, youtube_video_id, title, published_at, source_status)
                VALUES (%s, %s, %s, %s, 'live')
                ON CONFLICT (youtube_video_id) DO NOTHING
                """,
                (analyst_id, v.youtube_video_id, v.title, v.published_at),
            )

    client = _SyntheticClient(_CHAN_RESUME, videos)

    report = backfill_channel(client, _CHAN_RESUME, db_conn, months=24)

    # Only K - N_PRE should be inserted; the N_PRE pre-existing ones are skipped.
    assert report.new_videos == K - N_PRE, (
        f"Expected {K - N_PRE} new videos (skipping {N_PRE} pre-existing), got {report.new_videos}"
    )
    assert report.transcribe_jobs_enqueued == K - N_PRE
    assert report.videos_in_window == K
    assert report.capped is False
    assert report.remaining == 0, f"Expected 0 remaining after full run, got {report.remaining}"

    # Total video rows for our namespace must equal K (N_PRE pre-existing + K-N_PRE new).
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM videos WHERE youtube_video_id LIKE 'BF-t2bf-res%'",
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == K, f"Expected {K} total video rows, found {row[0]}"

    # Pre-existing videos must NOT have transcribe jobs (they were already present).
    pre_ids = [v.youtube_video_id for v in videos[:N_PRE]]
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' = ANY(%s)",
            (pre_ids,),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 0, f"Pre-existing videos must not produce transcribe jobs; found {row[0]}"
