"""Tests for E2-T2: DataApiYouTubeClient.list_uploads_since and poll_registered_channels.

NO network access. Fully deterministic.

Categories:
  1. DataApiYouTubeClient unit tests — injected fake http_get, no DB.
  2. FakeYouTubeClient fixture tests — no DB, keeps the fake on the CI path.
  3. poll_registered_channels DB integration — rolled-back db_conn fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.ingestion.poller import poll_registered_channels
from brier_pipeline.ingestion.registry import add_analyst
from brier_pipeline.ingestion.youtube import DataApiYouTubeClient, FakeYouTubeClient, YouTubeClient
from brier_pipeline.models import Video

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"


def _make_item(
    video_id: str,
    title: str,
    published_at: str,
) -> dict[str, Any]:
    """Build a minimal playlistItems API item dict."""
    return {
        "contentDetails": {
            "videoId": video_id,
            "videoPublishedAt": published_at,
        },
        "snippet": {
            "title": title,
            "publishedAt": published_at,
        },
    }


# ---------------------------------------------------------------------------
# 1. DataApiYouTubeClient unit tests (no DB, no network)
# ---------------------------------------------------------------------------


class TestDataApiYouTubeClientListUploadsSince:
    """Tests for DataApiYouTubeClient.list_uploads_since with an injected http_get."""

    def _build_client_with_pages(
        self,
        pages: list[dict[str, Any]],
    ) -> tuple[DataApiYouTubeClient, list[str]]:
        """Build a client whose http_get returns *pages* in sequence.

        Returns (client, recorded_urls).
        """
        recorded_urls: list[str] = []
        page_iter = iter(pages)

        def fake_http_get(url: str) -> dict[str, Any]:
            recorded_urls.append(url)
            return next(page_iter)

        client = DataApiYouTubeClient(api_key="TEST_KEY", http_get=fake_http_get)
        return client, recorded_urls

    def test_returns_only_videos_after_since(self) -> None:
        """Only items with publishedAt > since are returned."""
        since = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)

        page1: dict[str, Any] = {
            "nextPageToken": "TOKEN2",
            "items": [
                _make_item("vid-003", "New Video C", "2025-06-14T12:00:00Z"),
                _make_item("vid-002", "New Video B", "2025-06-10T08:00:00Z"),
            ],
        }
        page2: dict[str, Any] = {
            "items": [
                _make_item("vid-001", "Old Video", "2025-05-15T10:00:00Z"),
            ],
        }

        client, recorded_urls = self._build_client_with_pages([page1, page2])
        videos = client.list_uploads_since("UCtest-channel-001", since)

        assert len(videos) == 2
        assert videos[0].youtube_video_id == "vid-003"
        assert videos[1].youtube_video_id == "vid-002"

    def test_paging_stops_at_since(self) -> None:
        """Paging stops as soon as an item's publishedAt <= since."""
        since = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)

        page1: dict[str, Any] = {
            "nextPageToken": "TOKEN2",
            "items": [
                _make_item("vid-003", "New Video C", "2025-06-14T12:00:00Z"),
                # This item is older than since -> paging must stop here.
                _make_item("vid-old", "Old Video", "2025-05-15T10:00:00Z"),
            ],
        }
        # Page 2 should NEVER be fetched.
        page2: dict[str, Any] = {
            "items": [
                _make_item("vid-never", "Should Not Be Fetched", "2025-04-01T00:00:00Z"),
            ],
        }

        client, recorded_urls = self._build_client_with_pages([page1, page2])
        videos = client.list_uploads_since("UCtest-channel-001", since)

        # Only the item before the cutoff is returned.
        assert len(videos) == 1
        assert videos[0].youtube_video_id == "vid-003"
        # Only one page was fetched (paging stopped at the since boundary).
        assert len(recorded_urls) == 1

    def test_urls_contain_playlist_items_not_search(self) -> None:
        """Every URL must contain 'playlistItems'; NONE must contain 'search'.

        PRD §20: playlistItems costs 1 unit; search costs 100 units.
        """
        since = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        page1: dict[str, Any] = {
            "nextPageToken": "PAGE2",
            "items": [
                _make_item("v1", "Video 1", "2025-03-01T00:00:00Z"),
            ],
        }
        page2: dict[str, Any] = {
            "items": [
                _make_item("v2", "Video 2", "2025-02-01T00:00:00Z"),
            ],
        }

        client, recorded_urls = self._build_client_with_pages([page1, page2])
        client.list_uploads_since("UCtest-channel-001", since)

        assert len(recorded_urls) >= 1, "At least one URL must have been recorded"
        for url in recorded_urls:
            assert "playlistItems" in url, f"URL must contain 'playlistItems': {url}"
            assert "search" not in url, f"URL must NOT contain 'search': {url}"

    def test_url_uses_uploads_playlist_id(self) -> None:
        """The URL must use the 'UU' uploads playlist ID, not the raw channel ID."""
        since = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        page: dict[str, Any] = {
            "items": [
                _make_item("v1", "Video", "2025-01-01T00:00:00Z"),
            ],
        }

        client, recorded_urls = self._build_client_with_pages([page])
        client.list_uploads_since("UCabc-channel-xyz", since)

        assert len(recorded_urls) == 1
        assert "UUabc-channel-xyz" in recorded_urls[0], (
            f"Expected 'UU...' uploads playlist ID in URL: {recorded_urls[0]}"
        )
        assert "UCabc-channel-xyz" not in recorded_urls[0], (
            "Channel ID must be converted to uploads playlist ID (UU prefix)"
        )

    def test_units_used_equals_pages_fetched(self) -> None:
        """client.units_used must equal the number of pages fetched."""
        since = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

        page1: dict[str, Any] = {
            "nextPageToken": "P2",
            "items": [_make_item("v1", "V1", "2025-06-01T00:00:00Z")],
        }
        page2: dict[str, Any] = {
            "nextPageToken": "P3",
            "items": [_make_item("v2", "V2", "2025-05-01T00:00:00Z")],
        }
        page3: dict[str, Any] = {
            "items": [_make_item("v3", "V3", "2025-04-01T00:00:00Z")],
        }

        client, _ = self._build_client_with_pages([page1, page2, page3])
        client.list_uploads_since("UCtest-channel-001", since)

        assert client.units_used == 3, f"Expected 3 pages fetched, got {client.units_used}"

    def test_naive_since_treated_as_utc(self) -> None:
        """A naive since datetime is treated as UTC (no crash, correct filtering)."""
        since_naive = datetime(2025, 6, 1, 0, 0, 0)  # no tzinfo

        page: dict[str, Any] = {
            "items": [
                _make_item("newer", "Newer Video", "2025-06-14T00:00:00Z"),
                _make_item("older", "Older Video", "2025-05-01T00:00:00Z"),
            ],
        }

        client, _ = self._build_client_with_pages([page])
        videos = client.list_uploads_since("UCtest-channel-001", since_naive)

        assert len(videos) == 1
        assert videos[0].youtube_video_id == "newer"

    def test_analyst_id_is_zero_placeholder(self) -> None:
        """Returned Videos must have analyst_id=0 (filled by the poller)."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

        page: dict[str, Any] = {
            "items": [_make_item("v1", "Video", "2025-06-01T00:00:00Z")],
        }

        client, _ = self._build_client_with_pages([page])
        videos = client.list_uploads_since("UCtest-channel-001", since)

        assert len(videos) == 1
        assert videos[0].analyst_id == 0

    def test_empty_channel_returns_empty_list(self) -> None:
        """An empty playlistItems response returns an empty list."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

        page: dict[str, Any] = {"items": []}

        client, _ = self._build_client_with_pages([page])
        videos = client.list_uploads_since("UCtest-channel-001", since)

        assert videos == []
        assert client.units_used == 1

    def test_invalid_channel_id_raises(self) -> None:
        """_uploads_playlist_id raises ValueError for non-UC channel IDs."""
        client = DataApiYouTubeClient(api_key="key", http_get=lambda url: {})

        with pytest.raises(ValueError, match="must start with 'UC'"):
            client._uploads_playlist_id("invalid-channel-id")

    def test_content_details_published_at_preferred_over_snippet(self) -> None:
        """contentDetails.videoPublishedAt is used when available."""
        since = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)

        # Discriminating data: snippet.publishedAt is BEFORE since (would be
        # filtered out / stop paging), contentDetails.videoPublishedAt is AFTER
        # since. The video is only included if the code prefers contentDetails.
        item: dict[str, Any] = {
            "contentDetails": {
                "videoId": "v_cd",
                "videoPublishedAt": "2025-06-01T00:00:00Z",
            },
            "snippet": {
                "title": "Video Title",
                "publishedAt": "2024-12-01T00:00:00Z",
            },
        }
        page: dict[str, Any] = {"items": [item]}

        client, _ = self._build_client_with_pages([page])
        videos = client.list_uploads_since("UCtest-channel-001", since)

        # If the implementation read snippet.publishedAt (2024-12-01 <= since) the
        # video would be dropped and len would be 0; getting 1 proves the preference.
        assert len(videos) == 1
        assert videos[0].youtube_video_id == "v_cd"


# ---------------------------------------------------------------------------
# 2. FakeYouTubeClient fixture tests (no DB — CI path)
# ---------------------------------------------------------------------------


class TestFakeYouTubeClientFixtures:
    """Pure-unit tests of FakeYouTubeClient — keeps the fixture-backed fake on the CI path."""

    def test_list_uploads_since_far_past_returns_all_for_channel(self) -> None:
        """With since far in the past, all fixture videos for the channel are returned."""
        fake = FakeYouTubeClient(FIXTURES_DIR)
        since = datetime(2000, 1, 1, tzinfo=UTC)

        videos = fake.list_uploads_since("UCfix-northchain-0001", since)

        assert len(videos) > 0, "Expected at least one video for northchain"
        for v in videos:
            assert v.analyst_id == 0  # placeholder
            assert v.youtube_video_id.startswith("NC")  # northchain prefix

    def test_list_uploads_since_future_returns_empty(self) -> None:
        """With since in the far future, no fixture videos are returned."""
        fake = FakeYouTubeClient(FIXTURES_DIR)
        since = datetime(2099, 1, 1, tzinfo=UTC)

        videos = fake.list_uploads_since("UCfix-northchain-0001", since)

        assert videos == []

    def test_list_uploads_since_different_channels_isolated(self) -> None:
        """Videos from different channels are properly isolated."""
        fake = FakeYouTubeClient(FIXTURES_DIR)
        since = datetime(2000, 1, 1, tzinfo=UTC)

        northchain = fake.list_uploads_since("UCfix-northchain-0001", since)
        aylin = fake.list_uploads_since("UCfix-aylinmarkets-0002", since)

        nc_ids = {v.youtube_video_id for v in northchain}
        ay_ids = {v.youtube_video_id for v in aylin}

        assert nc_ids.isdisjoint(ay_ids), "Channel video sets must be disjoint"

    def test_list_uploads_since_naive_since_treated_as_utc(self) -> None:
        """Naive since datetime is handled without error."""
        fake = FakeYouTubeClient(FIXTURES_DIR)
        since_naive = datetime(2000, 1, 1)  # no tzinfo

        # Must not raise; should return all videos.
        videos = fake.list_uploads_since("UCfix-northchain-0001", since_naive)
        assert len(videos) > 0

    def test_published_at_is_tz_aware(self) -> None:
        """All returned Video.published_at values must be timezone-aware."""
        fake = FakeYouTubeClient(FIXTURES_DIR)
        since = datetime(2000, 1, 1, tzinfo=UTC)

        videos = fake.list_uploads_since("UCfix-northchain-0001", since)

        for v in videos:
            assert v.published_at.tzinfo is not None, (
                f"published_at for {v.youtube_video_id} must be tz-aware"
            )


# ---------------------------------------------------------------------------
# 3. poll_registered_channels DB integration tests
# ---------------------------------------------------------------------------


class _StubYouTubeClient(YouTubeClient):
    """A minimal stub that returns fixed Videos for a specific channel, [] for others.

    The synthetic test channel is 'UCfix-poller-test-9001'.
    """

    SYNTHETIC_CHANNEL = "UCfix-poller-test-9001"

    def __init__(self, synthetic_videos: list[Video]) -> None:
        self._synthetic_videos = synthetic_videos

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        if channel_id == self.SYNTHETIC_CHANNEL:
            # Return only videos after since (mimics real client behaviour).
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            return [v for v in self._synthetic_videos if v.published_at > since]
        return []

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        raise NotImplementedError

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        raise NotImplementedError


def _make_synthetic_videos(n: int, base_time: datetime) -> list[Video]:
    """Create n synthetic Videos with published_at spread before base_time."""
    return [
        Video(
            analyst_id=0,
            youtube_video_id=f"UCfix-poller-test-9001-vid-{i:03d}",
            title=f"Synthetic Video {i}",
            published_at=base_time - timedelta(hours=i),
        )
        for i in range(n)
    ]


def test_poll_first_run_inserts_videos_and_enqueues_transcribe(db_conn: Any) -> None:
    """First poll: new_videos==N, transcribe_jobs_enqueued==N, verify DB counts."""
    now = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)

    # Add a synthetic ACTIVE analyst with our test channel.
    analyst_id = add_analyst(
        db_conn,
        channel_id=_StubYouTubeClient.SYNTHETIC_CHANNEL,
        display_name="Poller Test Analyst",
        slug="poller-test-9001",
        status="active",
    )

    # 3 synthetic videos published just before 'now' (all within 48h, not stale).
    synthetic_videos = _make_synthetic_videos(3, now - timedelta(minutes=10))
    client = _StubYouTubeClient(synthetic_videos)

    report = poll_registered_channels(client, db_conn, now=now)

    assert report.new_videos == 3
    assert report.transcribe_jobs_enqueued == 3

    # Verify via DB count.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' LIKE 'UCfix-poller-test-9001%'"
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 3

    # Not stale: newest video is within 48h of now.
    assert analyst_id not in report.stale_channel_ids


def test_poll_second_run_is_idempotent(db_conn: Any) -> None:
    """Second poll with the same stub returns new_videos==0 and transcribe_jobs_enqueued==0."""
    now = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)

    add_analyst(
        db_conn,
        channel_id=_StubYouTubeClient.SYNTHETIC_CHANNEL,
        display_name="Poller Idempotent Test",
        slug="poller-idempotent-9001",
        status="active",
    )

    synthetic_videos = _make_synthetic_videos(2, now - timedelta(hours=1))
    client = _StubYouTubeClient(synthetic_videos)

    # First poll — inserts 2 videos.
    report1 = poll_registered_channels(client, db_conn, now=now)
    assert report1.new_videos == 2

    # Second poll — all videos already exist; nothing new.
    report2 = poll_registered_channels(client, db_conn, now=now)
    assert report2.new_videos == 0
    assert report2.transcribe_jobs_enqueued == 0


def test_poll_staleness_flag(db_conn: Any) -> None:
    """An analyst whose newest upload is >48h before now is flagged as stale."""
    now = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)

    # Newest video is 72h before now -> stale.
    stale_published = now - timedelta(hours=72)

    analyst_id = add_analyst(
        db_conn,
        channel_id=_StubYouTubeClient.SYNTHETIC_CHANNEL,
        display_name="Stale Analyst",
        slug="stale-poller-9001",
        status="active",
    )

    stale_videos = [
        Video(
            analyst_id=0,
            youtube_video_id="UCfix-poller-test-9001-stale-001",
            title="Old Video",
            published_at=stale_published,
        )
    ]
    client = _StubYouTubeClient(stale_videos)

    report = poll_registered_channels(client, db_conn, now=now)

    # The analyst must be stale because most recent upload is 72h ago > 48h threshold.
    assert analyst_id in report.stale_channel_ids

    # A freshness_check job must have been enqueued.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'freshness_check'"
            " AND payload->>'analyst_id' = %s",
            (str(analyst_id),),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) >= 1


def test_poll_non_stale_analyst_not_flagged(db_conn: Any) -> None:
    """An analyst with a recent upload (< 48h ago) is NOT flagged as stale."""
    now = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)

    analyst_id = add_analyst(
        db_conn,
        channel_id=_StubYouTubeClient.SYNTHETIC_CHANNEL,
        display_name="Fresh Analyst",
        slug="fresh-poller-9001",
        status="active",
    )

    # Newest upload is 24h ago — well within 48h freshness window.
    fresh_videos = [
        Video(
            analyst_id=0,
            youtube_video_id="UCfix-poller-test-9001-fresh-001",
            title="Recent Video",
            published_at=now - timedelta(hours=24),
        )
    ]
    client = _StubYouTubeClient(fresh_videos)

    report = poll_registered_channels(client, db_conn, now=now)

    assert analyst_id not in report.stale_channel_ids


def test_poll_report_counts_include_synthetic_channel(db_conn: Any) -> None:
    """polled_channels counts all active analysts including the 3 seeded ones."""
    now = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)

    add_analyst(
        db_conn,
        channel_id=_StubYouTubeClient.SYNTHETIC_CHANNEL,
        display_name="Count Test Analyst",
        slug="count-test-poller-9001",
        status="active",
    )

    # Stub returns [] for all channels (including synthetic) -> no new videos.
    class _EmptyStub(YouTubeClient):
        def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
            return []

        def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
            raise NotImplementedError

        def fetch_captions(self, youtube_video_id: str) -> str | None:
            raise NotImplementedError

    report = poll_registered_channels(_EmptyStub(), db_conn, now=now)

    # 3 seeded analysts + 1 synthetic = at least 4 channels polled.
    assert report.polled_channels >= 4
    assert report.new_videos == 0
