"""YouTube metadata access behind a small interface (mock-first convention).

The real client uses the official Data API v3 (playlistItems, 1 unit — never
search, 100 units) per PRD Section 20. The fake replays fixture JSON so every
later phase develops and tests without quota or keys.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

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
    """Real client over the official Data API v3. Not used until E2."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        """Poll playlistItems for new uploads at <= 2h latency (FR-102)."""
        # TASK: E2-T2
        raise NotImplementedError

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        """Backfill trailing 24 months of public uploads (FR-104)."""
        # TASK: E2-T3
        raise NotImplementedError

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        """Captions when present; uneven quality, verify offsets (PRD §20)."""
        # TASK: E2-T4
        raise NotImplementedError
