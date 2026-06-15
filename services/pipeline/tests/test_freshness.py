"""Tests for brier_pipeline/ingestion/freshness.py (E6-T2).

Coverage:
  - find_stale_analysts: correctly identifies stale analysts (old upload, no
    upload) and excludes fresh analysts and non-active (paused/removed) analysts.
  - hours_stale accuracy: positive value, correct magnitude.
  - run_freshness_check: raises one 'freshness' alert per stale analyst per
    billing month; idempotent on re-run (dedup); writes rows to the alerts table.
  - Paused/removed analysts are excluded from freshness checks.
  - All tests drive 'now' explicitly; no real-clock calls.
  - DB-backed tests use the rolled-back db_conn fixture (never commits).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from brier_pipeline.ingestion.freshness import (
    StaleAnalyst,
    find_stale_analysts,
    run_freshness_check,
)
from brier_pipeline.ops.alerts import FakeAlerter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
_FRESHNESS_HOURS = 48.0


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
) -> int:
    """Insert a minimal video row; return the new id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into videos
                (analyst_id, youtube_video_id, title, published_at, source_status)
            values (%s, %s, %s, %s, 'live')
            returning id
            """,
            (analyst_id, youtube_video_id, title, published_at),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# Tests: find_stale_analysts
# ---------------------------------------------------------------------------


class TestFindStaleAnalysts:
    """Unit-level correctness tests for find_stale_analysts (DB-backed)."""

    def test_fresh_analyst_not_returned(self, db_conn: Any) -> None:
        """An analyst with a recent upload is NOT stale."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_fresh_001",
            display_name="FreshAnalyst One",
            slug="fresh-analyst-001",
        )
        recent = _NOW - timedelta(hours=10)  # 10h ago, well within 48h
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="ytf001",
            title="Fresh video",
            published_at=recent,
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        stale_ids = {s.analyst_id for s in result}
        assert analyst_id not in stale_ids

    def test_old_video_analyst_is_stale(self, db_conn: Any) -> None:
        """An analyst whose only video is older than the threshold is stale."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_old_001",
            display_name="OldVideo Analyst",
            slug="old-video-001",
        )
        old = _NOW - timedelta(hours=72)  # 72h > 48h threshold
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="ytold001",
            title="Old video",
            published_at=old,
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        stale_ids = {s.analyst_id for s in result}
        assert analyst_id in stale_ids

    def test_no_videos_analyst_is_stale(self, db_conn: Any) -> None:
        """An analyst with no videos at all is always stale."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_novid_001",
            display_name="NoVideo Analyst",
            slug="no-video-001",
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        stale = {s.analyst_id: s for s in result}
        assert analyst_id in stale
        assert stale[analyst_id].last_upload_at is None
        assert stale[analyst_id].hours_stale is None

    def test_stale_analyst_has_correct_hours_stale(self, db_conn: Any) -> None:
        """hours_stale is positive and approximately equal to the actual lag."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_hours_001",
            display_name="HourCheck Analyst",
            slug="hour-check-001",
        )
        lag_hours = 96.0
        old = _NOW - timedelta(hours=lag_hours)
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="ythours001",
            title="Hours-check video",
            published_at=old,
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        stale = {s.analyst_id: s for s in result}
        assert analyst_id in stale

        hs = stale[analyst_id].hours_stale
        assert hs is not None
        # Allow a small floating-point tolerance.
        assert abs(hs - lag_hours) < 0.01

    def test_only_stale_ones_returned_mixed(self, db_conn: Any) -> None:
        """Given one fresh and one stale analyst, only the stale one is returned."""
        fresh_id = _seed_analyst(
            db_conn,
            channel_id="UC_mix_fresh",
            display_name="Mix Fresh",
            slug="mix-fresh",
        )
        stale_id = _seed_analyst(
            db_conn,
            channel_id="UC_mix_stale",
            display_name="Mix Stale",
            slug="mix-stale",
        )

        _seed_video(
            db_conn,
            analyst_id=fresh_id,
            youtube_video_id="ytmix_fresh",
            title="Recent upload",
            published_at=_NOW - timedelta(hours=5),
        )
        _seed_video(
            db_conn,
            analyst_id=stale_id,
            youtube_video_id="ytmix_stale",
            title="Old upload",
            published_at=_NOW - timedelta(hours=100),
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert stale_id in ids
        assert fresh_id not in ids

    def test_paused_analyst_excluded(self, db_conn: Any) -> None:
        """A PAUSED analyst is excluded even if their videos are old."""
        paused_id = _seed_analyst(
            db_conn,
            channel_id="UC_paused_001",
            display_name="Paused Analyst",
            slug="paused-001",
            status="paused",
        )
        _seed_video(
            db_conn,
            analyst_id=paused_id,
            youtube_video_id="ytpaused001",
            title="Very old video from a paused channel",
            published_at=_NOW - timedelta(days=30),
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert paused_id not in ids

    def test_removed_analyst_excluded(self, db_conn: Any) -> None:
        """A REMOVED analyst is excluded even if their videos are old."""
        removed_id = _seed_analyst(
            db_conn,
            channel_id="UC_removed_001",
            display_name="Removed Analyst",
            slug="removed-001",
            status="removed",
        )
        _seed_video(
            db_conn,
            analyst_id=removed_id,
            youtube_video_id="ytremoved001",
            title="Very old video from a removed channel",
            published_at=_NOW - timedelta(days=30),
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert removed_id not in ids

    def test_stale_analyst_fields_populated(self, db_conn: Any) -> None:
        """The returned StaleAnalyst has all expected fields populated correctly."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_fields_001",
            display_name="Fields Analyst",
            slug="fields-001",
        )
        old = _NOW - timedelta(hours=60)
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="ytfields001",
            title="Old upload",
            published_at=old,
        )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        stale = {s.analyst_id: s for s in result}
        assert analyst_id in stale

        entry = stale[analyst_id]
        assert isinstance(entry, StaleAnalyst)
        assert entry.slug == "fields-001"
        assert entry.display_name == "Fields Analyst"
        assert entry.last_upload_at is not None
        assert entry.hours_stale is not None
        assert entry.hours_stale > 0.0

    def test_tz_naive_published_at_treated_as_utc(self, db_conn: Any) -> None:
        """DB timestamps without tzinfo are treated as UTC (not local time)."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_tznaive_001",
            display_name="TzNaive Analyst",
            slug="tznaive-001",
        )
        # Insert a tz-naive timestamp that is 72h before _NOW.
        naive_old = (_NOW - timedelta(hours=72)).replace(tzinfo=None)
        with db_conn.cursor() as cur:
            cur.execute(
                """
                insert into videos
                    (analyst_id, youtube_video_id, title, published_at, source_status)
                values (%s, %s, %s, %s, 'live')
                """,
                (analyst_id, "yttznaive001", "Tz-naive video", naive_old),
            )

        result = find_stale_analysts(db_conn, _NOW, freshness_hours=_FRESHNESS_HOURS)
        ids = {s.analyst_id for s in result}
        assert analyst_id in ids

    def test_custom_freshness_hours(self, db_conn: Any) -> None:
        """A custom freshness_hours threshold is respected."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_custom_001",
            display_name="Custom Threshold",
            slug="custom-threshold-001",
        )
        # Video 30h old — stale under 24h but fresh under 48h.
        old = _NOW - timedelta(hours=30)
        _seed_video(
            db_conn,
            analyst_id=analyst_id,
            youtube_video_id="ytcustom001",
            title="Custom threshold video",
            published_at=old,
        )

        # With 24h threshold, this analyst is stale.
        stale_24 = find_stale_analysts(db_conn, _NOW, freshness_hours=24.0)
        assert any(s.analyst_id == analyst_id for s in stale_24)

        # With 48h threshold, this analyst is NOT stale.
        stale_48 = find_stale_analysts(db_conn, _NOW, freshness_hours=48.0)
        assert not any(s.analyst_id == analyst_id for s in stale_48)


# ---------------------------------------------------------------------------
# Tests: run_freshness_check
# ---------------------------------------------------------------------------


class TestRunFreshnessCheck:
    """DB-backed tests for run_freshness_check."""

    def test_raises_one_alert_per_stale_analyst(self, db_conn: Any) -> None:
        """run_freshness_check raises exactly one alert per stale analyst."""
        stale_id = _seed_analyst(
            db_conn,
            channel_id="UC_runfc_stale",
            display_name="RunFC Stale",
            slug="runfc-stale",
        )
        _seed_video(
            db_conn,
            analyst_id=stale_id,
            youtube_video_id="ytrunfc_stale",
            title="Old upload",
            published_at=_NOW - timedelta(hours=72),
        )

        alerter = FakeAlerter()
        result = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        # Should have raised an alert for the stale analyst.
        assert result["stale_count"] >= 1
        assert result["alerts_raised"] >= 1
        assert "runfc-stale" in result["stale_slugs"]

        # Check the FakeAlerter received a freshness dispatch for this slug.
        freshness_dispatches = [
            a for a in alerter.dispatched if a.kind == "freshness" and a.subject == "runfc-stale"
        ]
        assert len(freshness_dispatches) == 1

    def test_idempotent_on_second_run(self, db_conn: Any) -> None:
        """Calling run_freshness_check twice in the same billing period deduplicates alerts."""
        stale_id = _seed_analyst(
            db_conn,
            channel_id="UC_dedup_001",
            display_name="Dedup Analyst",
            slug="dedup-analyst-001",
        )
        _seed_video(
            db_conn,
            analyst_id=stale_id,
            youtube_video_id="ytdedup001",
            title="Old upload",
            published_at=_NOW - timedelta(hours=96),
        )

        alerter = FakeAlerter()
        # First run — should raise the alert.
        r1 = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)
        first_raised = r1["alerts_raised"]

        # Second run in the same period — should NOT raise new alerts (deduped).
        r2 = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)
        second_raised = r2["alerts_raised"]

        # The second call records 0 new alerts for this slug.
        assert first_raised >= 1
        assert second_raised == 0

        # The FakeAlerter dispatched exactly once for this slug (dedup_key).
        dispatched = [a for a in alerter.dispatched if a.subject == "dedup-analyst-001"]
        assert len(dispatched) == 1

    def test_alert_row_written_to_db(self, db_conn: Any) -> None:
        """run_freshness_check writes a row to the alerts table."""
        stale_id = _seed_analyst(
            db_conn,
            channel_id="UC_dbrow_001",
            display_name="DBRow Analyst",
            slug="dbrow-analyst-001",
        )
        _seed_video(
            db_conn,
            analyst_id=stale_id,
            youtube_video_id="ytdbrow001",
            title="Old upload",
            published_at=_NOW - timedelta(hours=72),
        )

        alerter = FakeAlerter()
        run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        expected_dedup = "freshness:dbrow-analyst-001:2026-06"
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind = 'freshness' and dedup_key = %s",
                (expected_dedup,),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1

    def test_no_alert_for_fresh_analyst(self, db_conn: Any) -> None:
        """run_freshness_check raises no alert for an analyst with a recent upload."""
        fresh_id = _seed_analyst(
            db_conn,
            channel_id="UC_fresh_run_001",
            display_name="Fresh Run Analyst",
            slug="fresh-run-001",
        )
        _seed_video(
            db_conn,
            analyst_id=fresh_id,
            youtube_video_id="ytfresh_run001",
            title="Recent upload",
            published_at=_NOW - timedelta(hours=10),
        )

        alerter = FakeAlerter()
        run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        # No freshness alert for this slug.
        dispatched = [a for a in alerter.dispatched if a.subject == "fresh-run-001"]
        assert len(dispatched) == 0

    def test_no_upload_analyst_alert_has_none_hours_stale(self, db_conn: Any) -> None:
        """An analyst with no videos gets a freshness alert; hours_stale in detail is null."""
        analyst_id = _seed_analyst(
            db_conn,
            channel_id="UC_novidrun_001",
            display_name="NoVid Run Analyst",
            slug="novid-run-001",
        )
        _ = analyst_id  # referenced to confirm seeding succeeded

        alerter = FakeAlerter()
        result = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        assert "novid-run-001" in result["stale_slugs"]

        # The dispatched alert detail has hours_stale = None.
        dispatched = [a for a in alerter.dispatched if a.subject == "novid-run-001"]
        assert len(dispatched) == 1
        detail = dispatched[0].detail
        assert detail is not None
        assert detail.get("hours_stale") is None

    def test_paused_analyst_not_alerted(self, db_conn: Any) -> None:
        """A PAUSED analyst is not included in the freshness check."""
        paused_id = _seed_analyst(
            db_conn,
            channel_id="UC_paused_run_001",
            display_name="Paused Run Analyst",
            slug="paused-run-001",
            status="paused",
        )
        _seed_video(
            db_conn,
            analyst_id=paused_id,
            youtube_video_id="ytpaused_run001",
            title="Old upload from paused channel",
            published_at=_NOW - timedelta(days=30),
        )

        alerter = FakeAlerter()
        result = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        assert "paused-run-001" not in result["stale_slugs"]
        dispatched = [a for a in alerter.dispatched if a.subject == "paused-run-001"]
        assert len(dispatched) == 0

    def test_removed_analyst_not_alerted(self, db_conn: Any) -> None:
        """A REMOVED analyst is not included in the freshness check."""
        removed_id = _seed_analyst(
            db_conn,
            channel_id="UC_removed_run_001",
            display_name="Removed Run Analyst",
            slug="removed-run-001",
            status="removed",
        )
        _seed_video(
            db_conn,
            analyst_id=removed_id,
            youtube_video_id="ytremoved_run001",
            title="Old upload from removed channel",
            published_at=_NOW - timedelta(days=30),
        )

        alerter = FakeAlerter()
        result = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        assert "removed-run-001" not in result["stale_slugs"]
        dispatched = [a for a in alerter.dispatched if a.subject == "removed-run-001"]
        assert len(dispatched) == 0

    def test_return_dict_structure(self, db_conn: Any) -> None:
        """run_freshness_check returns a dict with the expected keys."""
        # Seed one analyst with no videos (always stale).
        _seed_analyst(
            db_conn,
            channel_id="UC_struct_001",
            display_name="Struct Analyst",
            slug="struct-analyst-001",
        )

        alerter = FakeAlerter()
        result = run_freshness_check(db_conn, alerter, _NOW, freshness_hours=_FRESHNESS_HOURS)

        assert "stale_count" in result
        assert "alerts_raised" in result
        assert "stale_slugs" in result
        assert isinstance(result["stale_count"], int)
        assert isinstance(result["alerts_raised"], int)
        assert isinstance(result["stale_slugs"], list)

    def test_dedup_key_is_per_billing_month(self, db_conn: Any) -> None:
        """Alert dedup_key varies by billing month, so new month = new alert."""
        stale_id = _seed_analyst(
            db_conn,
            channel_id="UC_monthly_001",
            display_name="Monthly Dedup Analyst",
            slug="monthly-dedup-001",
        )
        _seed_video(
            db_conn,
            analyst_id=stale_id,
            youtube_video_id="ytmonthly001",
            title="Old upload",
            published_at=_NOW - timedelta(hours=200),
        )

        alerter = FakeAlerter()
        # Run in June 2026.
        now_june = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
        r_june = run_freshness_check(db_conn, alerter, now_june, freshness_hours=_FRESHNESS_HOURS)

        # Run in July 2026 (different billing period — a new alert should be raised).
        now_july = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
        r_july = run_freshness_check(db_conn, alerter, now_july, freshness_hours=_FRESHNESS_HOURS)

        june_raised = sum(
            1
            for a in alerter.dispatched
            if a.subject == "monthly-dedup-001" and "2026-06" in a.dedup_key
        )
        july_raised = sum(
            1
            for a in alerter.dispatched
            if a.subject == "monthly-dedup-001" and "2026-07" in a.dedup_key
        )

        assert june_raised == 1
        assert july_raised == 1
        assert r_june["alerts_raised"] >= 1
        assert r_july["alerts_raised"] >= 1


# ---------------------------------------------------------------------------
# Tests: handler self-registration
# ---------------------------------------------------------------------------


class TestFreshnessHandlerRegistration:
    """Verify that importing freshness.py registers the 'freshness_check' handler."""

    def test_handler_is_registered(self) -> None:
        """Importing freshness registers 'freshness_check' in the worker registry."""
        # Importing the module at the top of this file already triggered registration.
        from brier_pipeline.jobs.worker import get_handler

        handler = get_handler("freshness_check")
        assert handler is not None
        assert callable(handler)
