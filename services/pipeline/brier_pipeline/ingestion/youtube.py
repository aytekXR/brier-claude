"""YouTube metadata access behind a small interface (mock-first convention).

The real client uses the official Data API v3 (playlistItems, 1 unit — never
search, 100 units) per PRD Section 20. The fake replays fixture JSON so every
later phase develops and tests without quota or keys.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from brier_pipeline.models import Video


class YouTubeClient(ABC):
    """Metadata-only access; raw video is never fetched or stored (NFR-4)."""

    @abstractmethod
    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        """New uploads for a channel since a timestamp (FR-102 polling)."""

    @abstractmethod
    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        """All public uploads in the trailing window (FR-104 backfill)."""

    @abstractmethod
    def fetch_captions(self, youtube_video_id: str) -> str | None:
        """Caption track when available, else None (FR-103 caption-first)."""


class FakeYouTubeClient(YouTubeClient):
    """Fixture-backed fake: replays canned channel/video/caption fixtures.

    Reads data/fixtures/videos.json and data/fixtures/transcripts/.
    Captions are present for most videos; at least one video (NCfx-btc-apr30)
    has captions_available=false so FakeTranscriber is exercised in tests and
    the demo pipeline.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir
        self._videos: list[dict[str, object]] | None = None

    def _load_videos(self) -> list[dict[str, object]]:
        if self._videos is None:
            path = self.fixtures_dir / "videos.json"
            loaded: list[dict[str, object]] = json.loads(path.read_text(encoding="utf-8"))
            self._videos = loaded
        return self._videos

    def _parse_video(self, raw: dict[str, object]) -> Video:
        published_at_str = str(raw["published_at"])
        if published_at_str.endswith("Z"):
            published_at_str = published_at_str[:-1] + "+00:00"
        published_at = datetime.fromisoformat(published_at_str)
        dur_raw = raw.get("duration_seconds")
        duration_seconds: int | None = int(str(dur_raw)) if dur_raw is not None else None
        return Video(
            analyst_id=0,  # placeholder; filled by the demo/ingestion layer
            youtube_video_id=str(raw["youtube_video_id"]),
            title=str(raw["title"]),
            published_at=published_at,
            duration_seconds=duration_seconds,
        )

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        """Return fixture videos for channel_id published after since."""
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        return [
            self._parse_video(v)
            for v in self._load_videos()
            if str(v["channel_id"]) == channel_id
            and datetime.fromisoformat(str(v["published_at"]).replace("Z", "+00:00")) > since
        ]

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        """Return all fixture videos for channel_id (ignores months cutoff)."""
        return [
            self._parse_video(v) for v in self._load_videos() if str(v["channel_id"]) == channel_id
        ]

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        """Return the raw caption text for a video, or None when absent.

        Videos with captions_available=false in videos.json return None,
        causing the demo pipeline to fall back to FakeTranscriber.
        Otherwise returns the JSON text of the transcript segments file.
        """
        for v in self._load_videos():
            if str(v["youtube_video_id"]) == youtube_video_id:
                if v.get("captions_available") is False:
                    return None
                transcript_path = self.fixtures_dir / "transcripts" / f"{youtube_video_id}.json"
                if transcript_path.exists():
                    return transcript_path.read_text(encoding="utf-8")
                return None
        return None


class DataApiYouTubeClient(YouTubeClient):
    """Real client over the official Data API v3.

    The injectable http_get parameter is the MOCKED boundary for tests; the
    default performs a real GET via urllib (stdlib). CI and demo always use
    FakeYouTubeClient — this client is tested with an injected fake only.
    """

    _PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

    def __init__(
        self,
        api_key: str,
        http_get: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key
        self.units_used: int = 0  # quota counter; reused by E2-T3 backfill
        if http_get is not None:
            self._http_get = http_get
        else:
            self._http_get = self._default_http_get

    @staticmethod
    def _default_http_get(url: str) -> dict[str, Any]:
        """Real HTTP GET via stdlib urllib; returns parsed JSON.

        Only ever called with a URL this client constructs against the
        googleapis.com host; tests inject a fake http_get and never hit the network.
        """
        with urllib.request.urlopen(url) as resp:
            return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))

    @staticmethod
    def _uploads_playlist_id(channel_id: str) -> str:
        """Convert a channel ID to its uploads playlist ID.

        The uploads playlist ID is the channel ID with 'UC' replaced by 'UU'.

        Raises:
            ValueError: if channel_id does not start with 'UC'.
        """
        if not channel_id.startswith("UC"):
            raise ValueError(
                f"channel_id must start with 'UC'; got {channel_id!r}. "
                "Only standard YouTube channel IDs are supported."
            )
        return "UU" + channel_id[2:]

    def _fetch_playlist_page(
        self,
        playlist_id: str,
        page_token: str | None,
    ) -> dict[str, Any]:
        """Fetch one page of playlistItems and increment the quota counter.

        playlistItems costs 1 unit per page (PRD §20).
        NEVER use search (costs 100 units per call) — PRD §20 quota guardrail.
        """
        params: dict[str, str] = {
            "part": "snippet,contentDetails",
            "maxResults": "50",
            "playlistId": playlist_id,
            "key": self.api_key,
        }
        if page_token is not None:
            params["pageToken"] = page_token
        url = self._PLAYLIST_ITEMS_URL + "?" + urllib.parse.urlencode(params)
        result = self._http_get(url)
        self.units_used += 1
        return result

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        """Poll playlistItems for new uploads since *since* (FR-102).

        Pages through the uploads playlist newest-first; stops as soon as an
        item's publishedAt is <= since (items are newest-first, so all later
        pages are older). Returns list[Video] with analyst_id=0 (placeholder;
        filled by the poller).

        If *since* is naive it is treated as UTC.
        """
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)

        playlist_id = self._uploads_playlist_id(channel_id)
        videos: list[Video] = []
        page_token: str | None = None

        while True:
            page = self._fetch_playlist_page(playlist_id, page_token)
            items = page.get("items", [])

            stop_paging = False
            for item in items:
                content_details = item.get("contentDetails", {})
                snippet = item.get("snippet", {})

                video_id = str(content_details.get("videoId", ""))
                title = str(snippet.get("title", ""))

                # Prefer contentDetails.videoPublishedAt; fall back to snippet.publishedAt
                raw_published = content_details.get("videoPublishedAt") or snippet.get(
                    "publishedAt", ""
                )
                published_str = str(raw_published).replace("Z", "+00:00")
                published_at = datetime.fromisoformat(published_str)
                # Ensure tz-aware UTC
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=UTC)

                if published_at <= since:
                    # Items are newest-first; everything from here on is older.
                    stop_paging = True
                    break

                videos.append(
                    Video(
                        analyst_id=0,
                        youtube_video_id=video_id,
                        title=title,
                        published_at=published_at,
                    )
                )

            next_token = page.get("nextPageToken")
            if stop_paging or not next_token:
                break
            page_token = str(next_token)

        return videos

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        """Backfill trailing 24 months of public uploads (FR-104)."""
        # TASK: E2-T3
        raise NotImplementedError

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        """Captions when present; uneven quality, verify offsets (PRD §20)."""
        # TASK: E2-T4
        raise NotImplementedError
