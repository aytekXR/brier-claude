"""T2-extend: boundary and edge-regression tests for freshness.py.

Cluster: freshness  (DB id prefix: UC-t2x-fr)

Fills genuine gaps NOT already in tests/test_freshness.py (NFR-1, 48h staleness):

  1. Exact 48h boundary — find_stale_analysts uses a STRICT '>' comparison, so
     an analyst whose most recent video is exactly 48h old is NOT stale.
     Three sub-cases: 48h00m00s (not stale), 47h59m00s (not stale), 48h01m00s
     (stale).  A side-by-side test puts at-threshold vs. just-over-threshold
     analysts in the same call to confirm the strict-boundary behaviour.

  2. Paused analyst with NO videos — the existing paused tests all seed an old
     video.  Here we confirm that a paused analyst who has never uploaded is also
     excluded (because list_analysts filters by status='active' before the video
     query, so the no-videos branch is never reached for paused channels).

  3. Clean no-op — when all active analysts have recent uploads, run_freshness_check
     returns stale_count=0, alerts_raised=0, stale_slugs=[].  The three committed
     seed analysts (UCfix-*) are paused within the rolled-back test transaction
     so they do not pollute the result.

  4. alerter=None — the alerter parameter is Optional.  Passing None must still
     record the alert row in the DB (idempotent dedup) but must NOT dispatch
     externally.  This tests the guard in raise_alert: `if newly_recorded and
     alerter is not None: alerter.dispatch(alert)`.

All DB tests use the rolled-back db_conn fixture (never commits).
Channel IDs are namespaced with the 'UC-t2x-fr' cluster prefix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from brier_pipeline.ingestion.freshness import find_stale_analysts, run_freshness_check
from brier_pipeline.ops.alerts import FakeAlerter

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Reference 'now' used for all time-relative tests.
_NOW = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)
_FRESHNESS_HOURS = 48.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_analyst(
    conn: Any,
    *,
    channel_id: str,
    display_name: str,
    slug: str,
    status: str = "active",
) -> int:
    """Insert a minimal analyst row; return the new id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into analysts (channel_id, display_name, slug, status)
            values (%s, %s, %s, %s)
            returning id
            """,
            (channel_id, display_name, slug, status),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_video(
    conn: Any,
    *,
    analyst_id: int,
    youtube_video_id: str,
    title: str,
    published_at: datetime,
) -> None:
    """Insert a minimal video row (no return value needed for boundary tests)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into videos
                (analyst_id, youtube_video_id, title, published_at, source_status)
            values (%s, %s, %s, %s, 'live')
            """,
            (analyst_id, youtube_video_id, title, published_at),
        )


def _pause_seed_analysts(conn: Any) -> None:
    """Pause the three committed seed analysts (UCfix-*) within the current transaction.

    The seed analysts are committed data and always visible.  Pausing them here
    lets tests assert stale_count == 0 without interference.  The db_conn rollback
    restores their status automatically after each test.
    """
    with conn.cursor() as cur:
        cur.execute("update analysts set status = 'paused' where channel_id like 'UCfix-%'")


# ---------------------------------------------------------------------------
# Tests: exact 48h staleness boundary
# ---------------------------------------------------------------------------


class TestFindStaleAnalysts48hBoundary:
    """Characterise the exact '>48h' strict boundary in find_stale_analysts.

    Source: `if age > threshold:` (freshness.py line ~124).
    Equality (age == threshold) is NOT stale.
    """

    def test_exactly_48h_old_is_not_stale(self, db_conn: Any) -> None:
        """A video uploaded exactly 48h ago is NOT stale (strict > comparison).

        age == threshold  →  age > threshold is False  →  not stale.
        """
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-bnd-exact",
            display_name="Boundary Exact 48h",
            slug="t2x-fr-bnd-exact",
        )
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="yt-t2x-fr-bnd-exact",
            title="Boundary exact upload",
            published_at=_NOW - timedelta(hours=48),  # age == threshold exactly
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        # Exactly at threshold: strict '>' means NOT stale.
        assert analyst_id not in ids

    def test_47h59m_old_is_not_stale(self, db_conn: Any) -> None:
        """A video uploaded 47h 59m ago is NOT stale (clearly under threshold)."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-bnd-under",
            display_name="Boundary Under 48h",
            slug="t2x-fr-bnd-under",
        )
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="yt-t2x-fr-bnd-under",
            title="Just-under boundary upload",
            published_at=_NOW - timedelta(hours=47, minutes=59),
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert analyst_id not in ids

    def test_48h1m_old_is_stale(self, db_conn: Any) -> None:
        """A video uploaded 48h 1m ago IS stale (strictly over threshold)."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-bnd-over",
            display_name="Boundary Over 48h",
            slug="t2x-fr-bnd-over",
        )
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="yt-t2x-fr-bnd-over",
            title="Just-over boundary upload",
            published_at=_NOW - timedelta(hours=48, minutes=1),
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert analyst_id in ids

    def test_boundary_is_strict_not_inclusive(self, db_conn: Any) -> None:
        """Side-by-side: exactly-at-threshold is not stale; 1 second over is stale.

        Places two analysts in the same call so the strict boundary is confirmed
        from a single snapshot: at-threshold excluded, just-over-threshold included.
        """
        at_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-bnd-at",
            display_name="At Threshold",
            slug="t2x-fr-bnd-at",
        )
        over_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-bnd-ov2",
            display_name="Over Threshold By 1s",
            slug="t2x-fr-bnd-ov2",
        )
        _seed_video(
            db_conn,
            analyst_id=at_id,
            youtube_video_id="yt-t2x-fr-bnd-at",
            title="At threshold upload",
            published_at=_NOW - timedelta(hours=48),  # exactly 48h — not stale
        )
        _seed_video(
            db_conn,
            analyst_id=over_id,
            youtube_video_id="yt-t2x-fr-bnd-ov2",
            title="Over threshold upload",
            published_at=_NOW - timedelta(hours=48, seconds=1),  # 48h+1s — stale
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert at_id not in ids, "analyst at exactly 48h must NOT be stale (strict >)"
        assert over_id in ids, "analyst at 48h+1s MUST be stale (strict >)"


# ---------------------------------------------------------------------------
# Tests: paused analyst with no videos
# ---------------------------------------------------------------------------


class TestPausedAnalystNoVideos:
    """Paused analyst with no videos is excluded — the no-videos branch is never reached."""

    def test_paused_analyst_with_no_videos_excluded(self, db_conn: Any) -> None:
        """A PAUSED analyst who has never uploaded is still excluded from staleness.

        list_analysts(conn, status='active') filters to active analysts before
        any video query, so a paused analyst with no videos never reaches the
        no-videos-stale branch.  Existing tests cover paused+old-video; this
        covers the paused+no-video edge case.
        """
        paused_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-pno-vid",
            display_name="Paused No Video",
            slug="t2x-fr-pno-vid",
            status="paused",
        )
        # No videos seeded at all — the no-videos path would mark this stale
        # if it were active.  Being paused it must be excluded regardless.

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert paused_id not in ids


# ---------------------------------------------------------------------------
# Tests: run_freshness_check clean no-op
# ---------------------------------------------------------------------------


class TestRunFreshnessCheckCleanNoOp:
    """run_freshness_check returns zero counts when there are no stale analysts."""

    def test_all_fresh_analysts_yields_zero_alerts(self, db_conn: Any) -> None:
        """When every active analyst has a recent upload, stale_count and alerts_raised are both 0.

        The three committed seed analysts (UCfix-*) are paused within this
        rolled-back transaction so they do not interfere.  Only one fresh
        active analyst is seeded.
        """
        _pause_seed_analysts(db_conn)

        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-nop-fresh",
            display_name="No-op Fresh Analyst",
            slug="t2x-fr-nop-fresh",
        )
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="yt-t2x-fr-nop-fresh",
            title="Very recent upload",
            published_at=_NOW - timedelta(hours=2),  # well within 48h
        )

        alerter = FakeAlerter()
        result = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        assert result["stale_count"] == 0
        assert result["alerts_raised"] == 0
        assert result["stale_slugs"] == []
        # No external dispatch occurred.
        assert len(alerter.dispatched) == 0


# ---------------------------------------------------------------------------
# Tests: alerter=None path
# ---------------------------------------------------------------------------


class TestRunFreshnessCheckAlerterNone:
    """Verify that passing alerter=None records the alert in DB but does not dispatch."""

    def test_alerter_none_records_to_db_no_dispatch(self, db_conn: Any) -> None:
        """alerter=None: raise_alert still INSERTs a dedup row but skips dispatch.

        This exercises the `if newly_recorded and alerter is not None` guard in
        raise_alert (ops/alerts.py).  The alerts_raised count should be 1 (the
        DB row was inserted) but the FakeAlerter is not involved at all.
        """
        _pause_seed_analysts(db_conn)

        _seed_analyst(
            db_conn,
            channel_id="UC-t2x-fr-none-alr",
            display_name="Alerter None Test",
            slug="t2x-fr-none-alr",
            # No videos — stale by definition.
        )

        # Pass alerter=None explicitly (the Optional branch).
        result = run_freshness_check(db_conn, None, _NOW, freshness_hours=_FRESHNESS_HOURS)

        # The stale analyst is found and the DB row IS recorded.
        assert result["stale_count"] == 1
        assert result["alerts_raised"] == 1  # newly_recorded=True even with alerter=None
        assert "t2x-fr-none-alr" in result["stale_slugs"]

        # Confirm the alert row exists in the DB.
        expected_dedup = "freshness:t2x-fr-none-alr:2026-06"
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind = 'freshness' and dedup_key = %s",
                (expected_dedup,),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
