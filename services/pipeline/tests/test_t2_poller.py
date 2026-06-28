"""T2 regression tests for poller edge paths.

Covers:
  - Paused analyst skip: paused analysts are excluded from polling entirely
    (no YouTube client call, no video inserts, no transcribe jobs enqueued).
  - Watermark advance: after a successful poll that returns new uploads, the
    per-channel watermark (max published_at in the videos table) advances so
    the next poll does not re-fetch the same items.
  - Empty roster: poll_registered_channels with no active analysts is a clean
    no-op — no exception, zero counts, no YouTube client calls.

DB id prefix: UC-t2-pol
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from brier_pipeline.ingestion.poller import poll_registered_channels
from brier_pipeline.ingestion.registry import add_analyst
from brier_pipeline.ingestion.youtube import YouTubeClient
from brier_pipeline.models import Video

# ---------------------------------------------------------------------------
# Namespace prefix: every channel_id and youtube_video_id used here is
# prefixed with UC-t2-pol so no collisions with concurrent test files.
# ---------------------------------------------------------------------------
_PREFIX = "UC-t2-pol"

# Fixed 'now' used across tests — well within the 48 h freshness window for
# "recent" videos so staleness never fires unless explicitly intended.
_NOW = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Shared test stubs
# ---------------------------------------------------------------------------


class _TrackingClient(YouTubeClient):
    """Records every (channel_id, since) call; returns canned videos per channel.

    *videos_by_channel* maps channel_id -> list[Video].  Only videos whose
    published_at > since are returned, mirroring the real client contract.
    """

    def __init__(self, videos_by_channel: dict[str, list[Video]] | None = None) -> None:
        self.calls: list[tuple[str, datetime]] = []
        self._videos_by_channel: dict[str, list[Video]] = videos_by_channel or {}

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        self.calls.append((channel_id, since))
        return [v for v in self._videos_by_channel.get(channel_id, []) if v.published_at > since]

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        raise NotImplementedError

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        raise NotImplementedError


def _make_video(youtube_video_id: str, published_at: datetime) -> Video:
    """Build a minimal Video for use with _TrackingClient."""
    return Video(
        analyst_id=0,
        youtube_video_id=youtube_video_id,
        title=f"T2 Pol Video {youtube_video_id}",
        published_at=published_at,
    )


# ---------------------------------------------------------------------------
# Edge-path 1: paused analyst skip
# ---------------------------------------------------------------------------


def test_paused_analyst_not_polled(db_conn: Any) -> None:
    """A paused analyst is NOT passed to the YouTube client; active ones are.

    The test pauses all seeded analysts so the only active analyst is the one
    inserted here.  Both analysts are visible to the poller; only the active
    one must be polled.
    """
    # Pause all pre-existing (seeded) analysts within this rolled-back txn.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE analysts SET status = 'paused'")

    active_channel = f"{_PREFIX}-active-001"
    paused_channel = f"{_PREFIX}-paused-001"

    add_analyst(
        db_conn,
        channel_id=active_channel,
        display_name="T2 Pol Active",
        slug="t2-pol-active-001",
        status="active",
    )
    paused_id = add_analyst(
        db_conn,
        channel_id=paused_channel,
        display_name="T2 Pol Paused",
        slug="t2-pol-paused-001",
        status="paused",
    )

    # Give each channel a video so a bug that polls paused analysts would show up.
    active_video = _make_video(f"{_PREFIX}-active-001-vid-001", _NOW - timedelta(hours=1))
    paused_video = _make_video(f"{_PREFIX}-paused-001-vid-001", _NOW - timedelta(hours=2))

    client = _TrackingClient(
        {
            active_channel: [active_video],
            paused_channel: [paused_video],
        }
    )

    report = poll_registered_channels(client, db_conn, now=_NOW)

    queried_channels = {ch for ch, _ in client.calls}

    # Active channel must have been queried.
    assert active_channel in queried_channels, "Active analyst channel must be queried"

    # Paused channel must NOT have been queried at all.
    assert paused_channel not in queried_channels, (
        "Paused analyst channel must NOT be queried by poll_registered_channels"
    )

    # polled_channels counts only ACTIVE analysts (the paused one is excluded).
    assert report.polled_channels == 1, (
        f"Expected 1 polled channel (active only); got {report.polled_channels}"
    )

    # No videos must exist in the DB for the paused analyst.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM videos WHERE analyst_id = %s",
            (paused_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 0, "No videos should be inserted for a paused analyst"

    # No transcribe jobs for the paused channel's video IDs.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' LIKE %s",
            (f"{_PREFIX}-paused-001%",),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 0, "No transcribe jobs should exist for a paused analyst"


# ---------------------------------------------------------------------------
# Edge-path 2: watermark advances after a successful poll
# ---------------------------------------------------------------------------


def test_watermark_advances_after_poll(db_conn: Any) -> None:
    """After a poll inserts new uploads, the per-channel watermark advances.

    The watermark is max(published_at) of existing DB videos.  The second
    poll must pass that value as 'since', preventing re-insertion of the
    same items.
    """
    # Pause seeded analysts so only our test channel is polled.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE analysts SET status = 'paused'")

    channel_id = f"{_PREFIX}-wmark-001"
    analyst_id = add_analyst(
        db_conn,
        channel_id=channel_id,
        display_name="T2 Pol Watermark",
        slug="t2-pol-wmark-001",
        status="active",
    )

    t_older = _NOW - timedelta(hours=24)
    t_newer = _NOW - timedelta(hours=1)  # newest; will become the new watermark

    videos = [
        _make_video(f"{_PREFIX}-wmark-001-vid-001", t_older),
        _make_video(f"{_PREFIX}-wmark-001-vid-002", t_newer),
    ]

    # First poll: both videos are new.
    client1 = _TrackingClient({channel_id: videos})
    report1 = poll_registered_channels(client1, db_conn, now=_NOW)

    assert report1.new_videos == 2, f"Expected 2 new videos on first poll; got {report1.new_videos}"

    # Read the watermark the poller will derive on the next run.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT max(published_at) FROM videos WHERE analyst_id = %s",
            (analyst_id,),
        )
        row = cur.fetchone()
    assert row is not None and row[0] is not None, "Watermark must exist after first poll"

    stored_watermark: datetime = row[0]
    if stored_watermark.tzinfo is None:
        stored_watermark = stored_watermark.replace(tzinfo=UTC)

    # The stored watermark must equal the newest video's published_at.
    assert stored_watermark == t_newer, (
        f"Stored watermark {stored_watermark} must equal newest published_at {t_newer}"
    )

    # Second poll: tracking client records the 'since' argument passed.
    client2 = _TrackingClient({channel_id: videos})
    report2 = poll_registered_channels(client2, db_conn, now=_NOW)

    # The client must have been called exactly once for our channel.
    second_calls = [(ch, s) for ch, s in client2.calls if ch == channel_id]
    assert len(second_calls) == 1, f"Expected 1 call for {channel_id}; got {second_calls}"

    _ch, since_used = second_calls[0]
    if since_used.tzinfo is None:
        since_used = since_used.replace(tzinfo=UTC)

    # The watermark passed as 'since' must be >= t_newer (watermark advanced).
    assert since_used >= t_newer, (
        f"Second poll used since={since_used}; expected >= {t_newer} "
        "(watermark did not advance after first poll)"
    )

    # No new videos on second poll: watermark prevents re-fetching same items.
    assert report2.new_videos == 0, (
        f"Expected 0 new videos on second poll (idempotent); got {report2.new_videos}"
    )


# ---------------------------------------------------------------------------
# Edge-path 3: empty roster is a clean no-op
# ---------------------------------------------------------------------------


def test_empty_roster_is_noop(db_conn: Any) -> None:
    """poll_registered_channels with no active analysts returns cleanly with zeros.

    All seeded analysts are paused within the rolled-back transaction so the
    effective active roster is empty.  The poll must return a zero PollReport,
    never call the YouTube client, and raise no exception.
    """
    # Pause every analyst so the active list is empty.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE analysts SET status = 'paused'")

    client = _TrackingClient()

    # Must not raise.
    report = poll_registered_channels(client, db_conn, now=_NOW)

    assert report.polled_channels == 0, (
        f"Expected polled_channels=0 for empty roster; got {report.polled_channels}"
    )
    assert report.new_videos == 0
    assert report.transcribe_jobs_enqueued == 0
    assert report.stale_channel_ids == []

    # The YouTube client must never be called when there are no active analysts.
    assert client.calls == [], (
        f"No YouTube API calls should be made for empty roster; got {client.calls}"
    )
