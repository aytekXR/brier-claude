"""YouTube metadata access behind a small interface (mock-first convention).

The real client uses the official Data API v3 (playlistItems, 1 unit — never
search, 100 units) per PRD Section 20. The fake replays fixture JSON so every
later phase develops and tests without quota or keys.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
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
    """Fixture-backed fake: replays canned channel/video/caption fixtures."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def list_uploads_since(self, channel_id: str, since: datetime) -> list[Video]:
        # TASK: E1-T1 (fixture transcripts/videos), E2-T2 (poller contract tests)
        raise NotImplementedError

    def list_all_uploads(self, channel_id: str, months: int) -> list[Video]:
        # TASK: E1-T1, E2-T3
        raise NotImplementedError

    def fetch_captions(self, youtube_video_id: str) -> str | None:
        # TASK: E1-T1, E2-T4
        raise NotImplementedError


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
