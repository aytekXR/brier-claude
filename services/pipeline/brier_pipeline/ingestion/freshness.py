"""Freshness alerting for analyst channels (PRD NFR-1, E6-T2).

Polls every ACTIVE analyst's max(videos.published_at) against a staleness
threshold (default 48h). Any channel with no uploads at all, or whose most
recent upload is older than the threshold, raises a 'freshness' alert via the
Alerter seam (ops/alerts.py, ADR-0014). Alerts are idempotent per analyst per
billing month (dedup_key=freshness:<slug>:<YYYY-MM>).

The 'freshness_check' job is enqueued by poll_registered_channels (poller.py)
when a channel is stale. This module registers the handler, which performs a
full scan of all active analysts rather than using the per-analyst payload
(idempotent full-scan; the per-analyst payload is informational only).

Pattern mirrors ingestion/poller.py: handler self-registers at module load so
importing freshness wires the handler automatically — do NOT edit jobs/worker.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from brier_pipeline.ingestion import registry
from brier_pipeline.jobs import worker
from brier_pipeline.ops.alerts import Alerter, get_alerter, raise_alert
from brier_pipeline.ops.spend import billing_period

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StaleAnalyst:
    """An active analyst whose channel has not had a new upload within the threshold.

    Attributes:
        analyst_id:    DB id of the analyst.
        slug:          URL slug (used as subject in alerts and dedup_key).
        display_name:  Human-readable name (used in alert summary).
        last_upload_at: UTC datetime of the most recent video, or None if no
                        videos exist for this analyst.
        hours_stale:   Hours since the last upload (or None when last_upload_at
                       is None, indicating the analyst has never uploaded).
    """

    analyst_id: int
    slug: str
    display_name: str
    last_upload_at: datetime | None
    hours_stale: float | None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def find_stale_analysts(
    conn: Any,
    now: datetime,
    *,
    freshness_hours: float = 48.0,
) -> list[StaleAnalyst]:
    """Return every ACTIVE analyst that is stale relative to *now*.

    An analyst is stale if:
      - They have no uploads (last_upload_at is None), or
      - (now - last_upload_at) > freshness_hours.

    Timezone handling: DB timestamps may be tz-naive (stored without TZ in
    Postgres). Following poller.py's convention, tz-naive values are treated as
    UTC (replace(tzinfo=UTC)). The *now* argument is normalised to UTC-aware
    before comparison.

    Args:
        conn:            psycopg connection (caller owns the transaction).
        now:             Reference datetime for staleness computation.
        freshness_hours: Hours of silence that constitute stale. Default 48.

    Returns:
        list[StaleAnalyst] — one entry per stale ACTIVE analyst, ordered by id.
    """
    # Normalise now to UTC-aware.
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    threshold = timedelta(hours=freshness_hours)
    analysts = registry.list_analysts(conn, status="active")

    stale: list[StaleAnalyst] = []
    for analyst in analysts:
        assert analyst.id is not None
        with conn.cursor() as cur:
            cur.execute(
                "SELECT max(published_at) FROM videos WHERE analyst_id = %s",
                (analyst.id,),
            )
            row = cur.fetchone()

        last_raw = row[0] if row else None

        if last_raw is None:
            # No uploads at all — stale by definition.
            stale.append(
                StaleAnalyst(
                    analyst_id=analyst.id,
                    slug=analyst.slug,
                    display_name=analyst.display_name,
                    last_upload_at=None,
                    hours_stale=None,
                )
            )
            continue

        last_upload: datetime = last_raw
        if last_upload.tzinfo is None:
            last_upload = last_upload.replace(tzinfo=UTC)

        age = now - last_upload
        if age > threshold:
            stale.append(
                StaleAnalyst(
                    analyst_id=analyst.id,
                    slug=analyst.slug,
                    display_name=analyst.display_name,
                    last_upload_at=last_upload,
                    hours_stale=age.total_seconds() / 3600.0,
                )
            )

    return stale


def run_freshness_check(
    conn: Any,
    alerter: Alerter | None,
    now: datetime,
    *,
    freshness_hours: float = 48.0,
) -> dict[str, Any]:
    """Scan all ACTIVE analysts; raise a 'freshness' alert for each stale one.

    Each alert is deduplicated per analyst per billing month so repeated runs
    within the same month produce at most one dispatch per analyst
    (dedup_key = freshness:<slug>:<YYYY-MM>).

    Alert summaries are in the neutral register required by AC-7 — no
    buy/sell/hold language; factual observation only.

    Args:
        conn:            psycopg connection (caller owns the transaction).
        alerter:         Alerter implementation (FakeAlerter in CI; production
                         callers use get_alerter()).
        now:             Reference datetime; drives staleness computation and
                         billing_period key.
        freshness_hours: Hours threshold for staleness. Default 48.

    Returns:
        dict with keys:
            stale_count   — number of stale analysts found.
            alerts_raised — number of *new* alerts inserted (deduped calls
                            return False from raise_alert and are not counted).
            stale_slugs   — list of slugs for stale analysts.
    """
    period = billing_period(now)
    stale_list = find_stale_analysts(conn, now, freshness_hours=freshness_hours)

    alerts_raised = 0
    stale_slugs: list[str] = []

    for analyst in stale_list:
        stale_slugs.append(analyst.slug)
        dedup_key = f"freshness:{analyst.slug}:{period}"

        if analyst.hours_stale is None:
            # No videos ever uploaded.
            summary = (
                f"No upload has been detected from {analyst.display_name}. "
                f"The channel has no recorded videos."
            )
        else:
            hours = int(analyst.hours_stale)
            summary = (
                f"No new upload detected from {analyst.display_name} "
                f"in over {freshness_hours:.0f}h. "
                f"Last upload was approximately {hours}h ago."
            )

        newly_raised = raise_alert(
            conn,
            alerter,
            kind="freshness",
            severity="warning",
            subject=analyst.slug,
            dedup_key=dedup_key,
            summary=summary,
            detail={
                "analyst_id": analyst.analyst_id,
                "slug": analyst.slug,
                "last_upload_at": analyst.last_upload_at.isoformat()
                if analyst.last_upload_at is not None
                else None,
                "hours_stale": analyst.hours_stale,
                "freshness_hours": freshness_hours,
                "period": period,
            },
        )
        if newly_raised:
            alerts_raised += 1

    return {
        "stale_count": len(stale_list),
        "alerts_raised": alerts_raised,
        "stale_slugs": stale_slugs,
    }


# ---------------------------------------------------------------------------
# Job handler — registered at module load (poller.py precedent)
# ---------------------------------------------------------------------------


def _freshness_check_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """Job handler for 'freshness_check'.

    The payload carries analyst_id / channel_id from the poller (informational),
    but the handler performs a full scan of all active analysts for idempotency.
    The alerter is resolved from config at call time (BetterStackAlerter in
    production when BRIER_BETTER_STACK_TOKEN is set; FakeAlerter otherwise).

    CI/tests call run_freshness_check directly with an injected FakeAlerter
    and FakeYouTubeClient — this handler (and get_alerter) are NOT invoked in
    tests. This is the mock-first seam described in CLAUDE.md.
    """
    alerter = get_alerter()
    now = datetime.now(UTC)
    run_freshness_check(conn, alerter, now)


# Register at module load so importing freshness wires the handler automatically.
# The worker's run_forever() docstring documents: import freshness before calling
# run_forever() to activate this handler.
worker.register_handler("freshness_check", _freshness_check_handler)


# Expose public API.
__all__ = [
    "StaleAnalyst",
    "find_stale_analysts",
    "run_freshness_check",
]
