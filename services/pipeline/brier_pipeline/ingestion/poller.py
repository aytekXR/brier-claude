"""New-upload poller: registry channels -> ingestion events (FR-102, HP-1)."""

from __future__ import annotations

from brier_pipeline.ingestion.youtube import YouTubeClient


def poll_registered_channels(client: YouTubeClient) -> int:
    """Poll every active registry channel for new uploads at <= 2h latency.

    Writes video rows and enqueues transcription jobs. Returns the number of
    new videos ingested. Freshness > 48h must raise the staleness alert (NFR-1).
    """
    # TASK: E2-T2
    raise NotImplementedError
