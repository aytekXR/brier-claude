"""Tests for E2-T3: DataApiYouTubeClient.list_all_uploads and backfill_channel.

NO network access.  Fully deterministic.

Categories:
  1. DataApiYouTubeClient.list_all_uploads unit tests — injected fake http_get, no DB.
  2. FakeYouTubeClient.list_all_uploads fixture test — no DB, CI path.
  3. backfill_channel DB integration — rolled-back db_conn fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from brier_pipeline.ingestion.backfill import backfill_channel
from brier_pipeline.ingestion.registry import add_analyst
from brier_pipeline.ingestion.youtube import DataApiYouTubeClient, FakeYouTubeClient, YouTubeClient
from brier_pipeline.models import Video

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"


def _make_item(video_id: str, title: str, published_at: str) -> dict[str, Any]:
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


def _build_client_with_pages(
    pages: list[dict[str, Any]],
) -> tuple[DataApiYouTubeClient, list[str]]:
    """Build a DataApiYouTubeClient whose http_get returns *pages* in sequence.

    Returns (client, recorded_urls).
    """
    recorded_urls: list[str] = []
    page_iter = iter(pages)

    def fake_http_get(url: str) -> dict[str, Any]:
        recorded_urls.append(url)
        return next(page_iter)

    client = DataApiYouTubeClient(api_key="TEST_KEY", http_get=fake_http_get)
    return client, recorded_urls


# ---------------------------------------------------------------------------
# 1. DataApiYouTubeClient.list_all_uploads unit tests (no DB, no network)
# ---------------------------------------------------------------------------


class TestDataApiYouTubeClientListAllUploads:
    """Tests for DataApiYouTubeClient.list_all_uploads with injected http_get."""

    def _make_cutoff(self, months: int = 24) -> datetime:
        """Return the expected cutoff for a given months value."""
        return datetime.now(UTC) - timedelta(days=round(months * 30.44))

    def test_returns_only_videos_within_window(self) -> None:
        """Only items with publishedAt >= cutoff are returned."""
        # Pin 'now' to a fixed instant so the cutoff is predictable.
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))

        # One video inside the window, one clearly outside (5 years ago).
        inside_ts = (cutoff + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        outside_ts = (cutoff - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page: dict[str, Any] = {
            "items": [
                _make_item("vid-in", "Inside Window", inside_ts),
                _make_item("vid-out", "Outside Window", outside_ts),
            ],
        }

        client, _ = _build_client_with_pages([page])

        # Patch datetime.now so list_all_uploads sees our fixed_now.
        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            videos = client.list_all_uploads("UCtest-channel-001", 24)

        assert len(videos) == 1
        assert videos[0].youtube_video_id == "vid-in"

    def test_cutoff_boundary_is_inclusive(self) -> None:
        """An item published exactly at the cutoff is INCLUDED (>= cutoff);
        one a second earlier is EXCLUDED. Pins the < vs <= window invariant."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))

        at_cutoff_ts = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        before_cutoff_ts = (cutoff - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Newest-first: the at-cutoff item precedes the one just before cutoff.
        page: dict[str, Any] = {
            "items": [
                _make_item("vid-at-cutoff", "Exactly At Cutoff", at_cutoff_ts),
                _make_item("vid-before-cutoff", "Just Before Cutoff", before_cutoff_ts),
            ],
        }

        client, _ = _build_client_with_pages([page])
        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            videos = client.list_all_uploads("UCtest-channel-001", 24)

        # Exactly-at-cutoff is kept; the second-earlier item is dropped.
        assert [v.youtube_video_id for v in videos] == ["vid-at-cutoff"]

    def test_paging_stops_at_cutoff(self) -> None:
        """Paging STOPS at the first out-of-window item; older pages are NOT fetched."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))

        inside_ts = (cutoff + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        outside_ts = (cutoff - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page1: dict[str, Any] = {
            "nextPageToken": "PAGE2",
            "items": [
                _make_item("vid-in", "Inside Window", inside_ts),
                _make_item("vid-boundary", "Outside Window", outside_ts),
            ],
        }
        # Page 2 should NEVER be fetched.
        page2: dict[str, Any] = {
            "items": [
                _make_item("vid-never", "Should Not Be Fetched", "2020-01-01T00:00:00Z"),
            ],
        }

        client, recorded_urls = _build_client_with_pages([page1, page2])

        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            videos = client.list_all_uploads("UCtest-channel-001", 24)

        # Only the in-window video is returned.
        assert len(videos) == 1
        assert videos[0].youtube_video_id == "vid-in"
        # Only ONE page was fetched (paging stopped at the boundary item).
        assert len(recorded_urls) == 1

    def test_multiple_pages_all_inside_window(self) -> None:
        """Multiple pages of in-window items are all collected."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))

        ts1 = (cutoff + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts2 = (cutoff + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts3 = (cutoff + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page1: dict[str, Any] = {
            "nextPageToken": "PAGE2",
            "items": [
                _make_item("v1", "Video 1", ts1),
                _make_item("v2", "Video 2", ts2),
            ],
        }
        page2: dict[str, Any] = {
            "items": [
                _make_item("v3", "Video 3", ts3),
            ],
        }

        client, recorded_urls = _build_client_with_pages([page1, page2])

        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            videos = client.list_all_uploads("UCtest-channel-001", 24)

        assert len(videos) == 3
        assert [v.youtube_video_id for v in videos] == ["v1", "v2", "v3"]
        assert len(recorded_urls) == 2

    def test_urls_contain_playlist_items_not_search(self) -> None:
        """All URLs contain 'playlistItems'; NONE contain 'search' (PRD §20 quota guardrail)."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))
        inside_ts = (cutoff + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page: dict[str, Any] = {"items": [_make_item("v1", "V1", inside_ts)]}

        client, recorded_urls = _build_client_with_pages([page])

        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            client.list_all_uploads("UCtest-channel-001", 24)

        assert len(recorded_urls) >= 1
        for url in recorded_urls:
            assert "playlistItems" in url, f"URL must contain 'playlistItems': {url}"
            assert "search" not in url, f"URL must NOT contain 'search': {url}"

    def test_units_used_equals_pages_fetched(self) -> None:
        """client.units_used must equal the number of pages actually fetched."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))

        ts1 = (cutoff + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts2 = (cutoff + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ts3 = (cutoff + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page1: dict[str, Any] = {
            "nextPageToken": "P2",
            "items": [_make_item("v1", "V1", ts1)],
        }
        page2: dict[str, Any] = {
            "nextPageToken": "P3",
            "items": [_make_item("v2", "V2", ts2)],
        }
        page3: dict[str, Any] = {
            "items": [_make_item("v3", "V3", ts3)],
        }

        client, _ = _build_client_with_pages([page1, page2, page3])

        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            client.list_all_uploads("UCtest-channel-001", 24)

        assert client.units_used == 3, f"Expected 3 pages fetched, got {client.units_used}"

    def test_units_used_stops_early_at_cutoff(self) -> None:
        """units_used reflects only the pages actually fetched (stops at cutoff)."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))

        inside_ts = (cutoff + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        outside_ts = (cutoff - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page1: dict[str, Any] = {
            "nextPageToken": "PAGE2",
            "items": [
                _make_item("v-in", "Inside", inside_ts),
                _make_item("v-out", "Outside", outside_ts),
            ],
        }
        page2: dict[str, Any] = {
            "items": [_make_item("v-never", "Never", "2020-01-01T00:00:00Z")],
        }

        client, _ = _build_client_with_pages([page1, page2])

        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            client.list_all_uploads("UCtest-channel-001", 24)

        # Only 1 page fetched (stopped at boundary).
        assert client.units_used == 1

    def test_analyst_id_is_zero_placeholder(self) -> None:
        """Returned Videos must have analyst_id=0 (placeholder)."""
        fixed_now = datetime(2026, 6, 14, 0, 0, 0, tzinfo=UTC)
        cutoff = fixed_now - timedelta(days=round(24 * 30.44))
        inside_ts = (cutoff + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        page: dict[str, Any] = {"items": [_make_item("v1", "Video", inside_ts)]}

        client, _ = _build_client_with_pages([page])

        with patch(
            "brier_pipeline.ingestion.youtube.datetime",
            wraps=datetime,
        ) as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.fromisoformat.side_effect = datetime.fromisoformat
            videos = client.list_all_uploads("UCtest-channel-001", 24)

        assert len(videos) == 1
        assert videos[0].analyst_id == 0

    def test_empty_channel_returns_empty_list(self) -> None:
        """An empty playlistItems response returns an empty list."""
        page: dict[str, Any] = {"items": []}
        client, _ = _build_client_with_pages([page])

        videos = client.list_all_uploads("UCtest-channel-001", 24)

        assert videos == []
        assert client.units_used == 1


# ---------------------------------------------------------------------------
# 2. FakeYouTubeClient.list_all_uploads fixture test (no DB — CI path)
# ---------------------------------------------------------------------------


class TestFakeYouTubeClientListAllUploads:
    """Pure-unit test of FakeYouTubeClient.list_all_uploads — keeps the fake on CI path."""

    def test_returns_fixture_videos_for_channel(self) -> None:
        """list_all_uploads returns all fixture videos for the given channel."""
        fake = FakeYouTubeClient(FIXTURES_DIR)

        videos = fake.list_all_uploads("UCfix-northchain-0001", 24)

        assert len(videos) > 0, "Expected at least one video for northchain"
        for v in videos:
            assert v.analyst_id == 0  # placeholder
            assert v.youtube_video_id.startswith("NC"), (
                f"Expected NC-prefixed video id, got {v.youtube_video_id!r}"
            )

    def test_returns_empty_for_unknown_channel(self) -> None:
        """list_all_uploads returns [] for an unregistered channel."""
        fake = FakeYouTubeClient(FIXTURES_DIR)

        videos = fake.list_all_uploads("UCfix-nonexistent-0000", 24)

        assert videos == []

    def test_different_channels_isolated(self) -> None:
        """Videos from different channels are isolated."""
        fake = FakeYouTubeClient(FIXTURES_DIR)

        nc = fake.list_all_uploads("UCfix-northchain-0001", 24)
        ay = fake.list_all_uploads("UCfix-aylinmarkets-0002", 24)

        nc_ids = {v.youtube_video_id for v in nc}
        ay_ids = {v.youtube_video_id for v in ay}

        assert nc_ids.isdisjoint(ay_ids), "Channel video sets must be disjoint"


# ---------------------------------------------------------------------------
# 3. backfill_channel DB integration tests
# ---------------------------------------------------------------------------

# Synthetic channel ID used across DB tests (different from poller tests).
_BACKFILL_TEST_CHANNEL = "UCfix-backfill-test-8001"


class _SyntheticYouTubeClient(YouTubeClient):
    """Stub returning K fixed Videos for _BACKFILL_TEST_CHANNEL, [] for others."""

    def __init__(self, videos: list[Video]) -> None:
        self._videos = videos

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        raise NotImplementedError

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        if channel_id == _BACKFILL_TEST_CHANNEL:
            return list(self._videos)
        return []

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        raise NotImplementedError


def _make_backfill_videos(n: int) -> list[Video]:
    """Create n synthetic Videos with unique youtube_video_ids."""
    base = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
    return [
        Video(
            analyst_id=0,
            youtube_video_id=f"BF-test-8001-vid-{i:03d}",
            title=f"Backfill Video {i}",
            published_at=base - timedelta(days=i),
        )
        for i in range(n)
    ]


def test_backfill_first_run_inserts_up_to_cap(db_conn: Any) -> None:
    """Run 1 with max_videos=m < K: new_videos==m, capped==True, remaining==K-m."""
    K = 7
    m = 3

    add_analyst(
        db_conn,
        channel_id=_BACKFILL_TEST_CHANNEL,
        display_name="Backfill Test Analyst",
        slug="backfill-test-8001",
        status="active",
    )

    synthetic_videos = _make_backfill_videos(K)
    client = _SyntheticYouTubeClient(synthetic_videos)

    report = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24, max_videos=m)

    assert report.videos_in_window == K
    assert report.new_videos == m
    assert report.transcribe_jobs_enqueued == m
    assert report.capped is True
    assert report.remaining == K - m

    # Verify via DB count.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' LIKE 'BF-test-8001%'"
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == m


def test_backfill_resume_inserts_next_batch(db_conn: Any) -> None:
    """Run 2 (resume) with the same cap picks up where Run 1 left off."""
    K = 6
    m = 2

    add_analyst(
        db_conn,
        channel_id=_BACKFILL_TEST_CHANNEL,
        display_name="Backfill Resume Analyst",
        slug="backfill-resume-8001",
        status="active",
    )

    synthetic_videos = _make_backfill_videos(K)
    client = _SyntheticYouTubeClient(synthetic_videos)

    # Run 1: insert first 2
    r1 = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24, max_videos=m)
    assert r1.new_videos == m
    assert r1.capped is True
    assert r1.remaining == K - m

    # Run 2: insert next 2 (skipping the 2 already in DB)
    r2 = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24, max_videos=m)
    assert r2.new_videos == m
    assert r2.capped is True
    assert r2.remaining == K - (m * 2)

    # Run 3: insert last 2
    r3 = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24, max_videos=m)
    assert r3.new_videos == m
    assert r3.capped is False
    assert r3.remaining == 0

    # Final run: all K in DB — idempotent
    r4 = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24, max_videos=m)
    assert r4.new_videos == 0
    assert r4.capped is False
    assert r4.remaining == 0


def test_backfill_no_cap_inserts_all(db_conn: Any) -> None:
    """Without a cap, all K videos are inserted in a single run."""
    K = 5

    add_analyst(
        db_conn,
        channel_id=_BACKFILL_TEST_CHANNEL,
        display_name="Backfill No Cap Analyst",
        slug="backfill-nocap-8001",
        status="active",
    )

    synthetic_videos = _make_backfill_videos(K)
    client = _SyntheticYouTubeClient(synthetic_videos)

    report = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24, max_videos=None)

    assert report.new_videos == K
    assert report.capped is False
    assert report.remaining == 0
    assert report.transcribe_jobs_enqueued == K


def test_backfill_idempotent_on_rerun(db_conn: Any) -> None:
    """Re-running after all videos are inserted inserts 0 and is idempotent."""
    K = 4

    add_analyst(
        db_conn,
        channel_id=_BACKFILL_TEST_CHANNEL,
        display_name="Backfill Idempotent Analyst",
        slug="backfill-idempotent-8001",
        status="active",
    )

    synthetic_videos = _make_backfill_videos(K)
    client = _SyntheticYouTubeClient(synthetic_videos)

    # First full run
    r1 = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24)
    assert r1.new_videos == K

    # Second run — nothing new
    r2 = backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24)
    assert r2.new_videos == 0
    assert r2.capped is False
    assert r2.remaining == 0


def test_backfill_unregistered_channel_raises(db_conn: Any) -> None:
    """backfill_channel raises ValueError for an unregistered channel_id."""
    client = _SyntheticYouTubeClient([])

    with pytest.raises(ValueError, match="not registered"):
        backfill_channel(client, "UCfix-unregistered-9999", db_conn, months=24)


def test_backfill_transcribe_jobs_payload(db_conn: Any) -> None:
    """Each transcribe job payload contains both video_id and youtube_video_id."""
    K = 2

    add_analyst(
        db_conn,
        channel_id=_BACKFILL_TEST_CHANNEL,
        display_name="Backfill Payload Analyst",
        slug="backfill-payload-8001",
        status="active",
    )

    synthetic_videos = _make_backfill_videos(K)
    client = _SyntheticYouTubeClient(synthetic_videos)

    backfill_channel(client, _BACKFILL_TEST_CHANNEL, db_conn, months=24)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM jobs WHERE kind = 'transcribe'"
            " AND payload->>'youtube_video_id' LIKE 'BF-test-8001%'"
            " ORDER BY id"
        )
        rows = cur.fetchall()

    assert len(rows) == K
    for row in rows:
        payload = row[0]
        assert "video_id" in payload
        assert "youtube_video_id" in payload
        assert payload["video_id"] > 0
