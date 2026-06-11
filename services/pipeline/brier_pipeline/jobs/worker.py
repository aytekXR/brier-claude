"""Cron-style worker loop over the `jobs` table.

Polls for due jobs (state=queued, run_at <= now), claims one with
SELECT ... FOR UPDATE SKIP LOCKED, dispatches by kind, records attempts and
errors. Job kinds (wired up as their epics land): poll_channels, transcribe,
extract, resolve_claims, score_analysts, weekly_digest, freshness_check.
"""

from __future__ import annotations

from brier_pipeline.models import Job


def claim_next_job() -> Job | None:
    """Atomically claim the next due job, or None when the queue is idle."""
    # TASK: E2-T6
    raise NotImplementedError


def run_forever(poll_interval_seconds: float = 5.0) -> None:
    """The worker loop: claim, dispatch, record outcome, sleep, repeat."""
    # TASK: E2-T6
    raise NotImplementedError
