"""Historical backfill crawler: trailing 24 months per analyst (FR-104)."""

from __future__ import annotations

from brier_pipeline.ingestion.youtube import YouTubeClient


def backfill_channel(client: YouTubeClient, channel_id: str, months: int = 24) -> int:
    """Ingest all public uploads in the trailing window for one channel.

    Caption-first strategy; audio transcription only as fallback, within the
    cost guardrails (NFR-5). Returns the number of videos ingested.
    """
    # TASK: E2-T3
    raise NotImplementedError
