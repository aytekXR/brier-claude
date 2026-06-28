"""T2-extend: SLA-clock boundary & edge regression tests (cluster: sla).

Fills genuine gaps NOT covered by tests/test_sla.py:
  1. time_to_breach: 1-second precision — confirms the sign-flip is exactly at
     zero, not fuzzy (existing tests use 36 h / 10 h deltas).
  2. find_breached_disputes: sla_deadline == now exactly is NOT breached (SQL
     uses strict <); 'rejected' adjudicated state is excluded; empty-set no-op.
  3. find_at_risk_disputes: sla_deadline == now + warn_within_hours exactly IS
     at-risk (SQL uses <=, inclusive upper bound); one second past that window
     is NOT at-risk; sla_deadline == now is at-risk but NOT breached (tests the
     flip from find_breached); 'rejected' state excluded.
  4. run_sla_check: combined breach + at-risk seeded in same call asserts exact
     dispatched count; at-risk dedup idempotency (separate from breach dedup);
     alerter=None does not crash.
  5. weekly_dispute_report: pct_within_sla = 1.0 with REAL adjudicated disputes
     all within SLA (non-vacuous, not tested in existing suite); median over an
     ODD count of 3 durations (middle element, not average); truly empty window
     (total=0) returns a sane zero report without divide-by-zero.

DB identifiers namespaced 'T2S-'; channel_ids not inserted (reuse seed analysts).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from brier_pipeline.disputes.sla import (
    find_at_risk_disputes,
    find_breached_disputes,
    run_sla_check,
    time_to_breach,
    weekly_dispute_report,
)
from brier_pipeline.models import Dispute
from brier_pipeline.ops.alerts import FakeAlerter

# ---------------------------------------------------------------------------
# DB seed helpers (mirror pattern from test_sla.py)
# ---------------------------------------------------------------------------


def _get_analyst_video_transcript(cur: Any) -> tuple[int, int, int]:
    cur.execute("select id from analysts limit 1")
    a_row = cur.fetchone()
    assert a_row is not None, "No analysts seeded — run make seed first"
    analyst_id = int(a_row[0])
    cur.execute("select id from videos where analyst_id = %s limit 1", (analyst_id,))
    v_row = cur.fetchone()
    assert v_row is not None
    video_id = int(v_row[0])
    cur.execute("select id from transcripts where video_id = %s limit 1", (video_id,))
    t_row = cur.fetchone()
    assert t_row is not None
    transcript_id = int(t_row[0])
    return analyst_id, video_id, transcript_id


def _seed_claim(cur: Any, analyst_id: int, video_id: int, transcript_id: int) -> int:
    """Insert a synthetic claim and return its id."""
    cur.execute(
        """
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction, target_price,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            specificity_class, source_offset_seconds,
            quote, uttered_at, p0_price,
            model_version, prompt_version,
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            'BTC', 'bullish', 80000.0,
            '2025-07-31', 'stated',
            0.70, 'stated',
            'target_deadline', 120,
            't2x sla boundary test claim.',
            '2025-01-01 00:00:00+00', 79000.0,
            'test', 'test',
            'approved', true, 'open', '{}'
        ) returning id
        """,
        (analyst_id, video_id, transcript_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_dispute(
    cur: Any,
    claim_id: int,
    *,
    ticket_code: str,
    state: str = "open",
    submitted_at: datetime,
    sla_deadline: datetime,
    adjudicated_at: datetime | None = None,
    adjudication_note: str | None = None,
) -> int:
    """Insert a dispute row with controlled timestamps and return its id."""
    cur.execute(
        """
        insert into disputes (
            ticket_code, claim_id, submitted_by, rationale, state,
            sla_deadline, submitted_at, adjudicated_at, adjudication_note,
            methodology_version_at_publication
        ) values (
            %s, %s, 'test@example.com', 'T2-SLA boundary test rationale.',
            %s, %s, %s, %s, %s, 'v1.1'
        ) returning id
        """,
        (
            ticket_code,
            claim_id,
            state,
            sla_deadline,
            submitted_at,
            adjudicated_at,
            adjudication_note,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# 1. time_to_breach: 1-second precision boundaries (unit, no DB)
# ---------------------------------------------------------------------------


class TestTimeToBreach1SecondPrecision:
    """Existing tests use 36 h / 10 h deltas; these pin the exact 1-second flip."""

    def test_one_second_past_deadline_is_negative(self) -> None:
        """time_to_breach returns exactly -1 s when 1 second past the deadline."""
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
        sla = now - timedelta(seconds=1)
        dispute = Dispute(
            id=1,
            ticket_code="T2S-ttb-001",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=sla,
        )
        ttb = time_to_breach(dispute, now)
        assert ttb == timedelta(seconds=-1), (
            f"Expected timedelta(-1s), got {ttb}; threshold must be exactly 0"
        )
        assert ttb < timedelta(0), "1 second past deadline must be classified as breached"

    def test_one_second_before_deadline_is_positive(self) -> None:
        """time_to_breach returns exactly +1 s when 1 second before the deadline."""
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
        sla = now + timedelta(seconds=1)
        dispute = Dispute(
            id=2,
            ticket_code="T2S-ttb-002",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=sla,
        )
        ttb = time_to_breach(dispute, now)
        assert ttb == timedelta(seconds=1), (
            f"Expected timedelta(+1s), got {ttb}; 1 s before deadline must not be breached"
        )
        assert ttb > timedelta(0), "1 second before deadline must not be classified as breached"

    def test_sign_flips_across_zero(self) -> None:
        """The sign of time_to_breach flips exactly at 0 (no dead-band)."""
        now = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)

        past_dispute = Dispute(
            id=3,
            ticket_code="T2S-ttb-003",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=now - timedelta(seconds=1),
        )
        future_dispute = Dispute(
            id=4,
            ticket_code="T2S-ttb-004",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=now + timedelta(seconds=1),
        )
        ttb_past = time_to_breach(past_dispute, now)
        ttb_future = time_to_breach(future_dispute, now)

        # Past is negative (breached), future is positive (not breached).
        assert ttb_past < timedelta(0)
        assert ttb_future > timedelta(0)
        # The sum of the two deltas must equal exactly 2 seconds.
        assert ttb_future - ttb_past == timedelta(seconds=2), (
            "The window between ±1 s must span exactly 2 seconds"
        )


# ---------------------------------------------------------------------------
# 2. find_breached_disputes: exact-now boundary + excluded states
# ---------------------------------------------------------------------------


class TestFindBreachedExactBoundary:
    def test_sla_deadline_exactly_now_is_not_breached(self, db_conn: Any) -> None:
        """sla_deadline == now is NOT in the breached list (SQL: sla_deadline < now, strict)."""
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-bnd-001",
                state="open",
                submitted_at=now - timedelta(days=7),
                sla_deadline=now,  # exactly now
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "T2S-bnd-001" not in codes, (
            "sla_deadline == now must NOT be breached (SQL uses strict <, not <=)"
        )

    def test_sla_deadline_one_second_before_now_is_breached(self, db_conn: Any) -> None:
        """sla_deadline == now - 1s IS in the breached list; confirms the flip at the threshold."""
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-bnd-002",
                state="open",
                submitted_at=now - timedelta(days=7),
                sla_deadline=now - timedelta(seconds=1),  # 1 second past deadline
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "T2S-bnd-002" in codes, "sla_deadline == now - 1s must be classified as breached"

    def test_rejected_dispute_excluded_from_breached(self, db_conn: Any) -> None:
        """'rejected' adjudicated state is NOT in the breached list.

        Existing test_sla.py only tests 'upheld'. This covers the third adjudicated state.
        """
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-bnd-003",
                state="rejected",
                submitted_at=now - timedelta(days=10),
                sla_deadline=now - timedelta(days=3),  # past deadline
                adjudicated_at=now - timedelta(days=2),
                adjudication_note="Rejected after review.",
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "T2S-bnd-003" not in codes, (
            "'rejected' dispute must not appear in breached list; only active states qualify"
        )

    def test_empty_result_when_no_disputes(self, db_conn: Any) -> None:
        """find_breached_disputes returns an empty list when there are no disputes."""
        # Use a far-future time; since seed.py inserts no disputes and this
        # transaction is rolled back, no disputes should exist before now.
        now = datetime(2099, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = find_breached_disputes(db_conn, now)
        # seed.py inserts no disputes and every test rolls back, so no dispute is
        # ever committed: at a far-future `now` the breached list must be empty.
        assert result == [], f"no committed disputes exist; expected [], got {result}"

    def test_no_breached_when_only_future_deadlines(self, db_conn: Any) -> None:
        """find_breached_disputes returns no matches when only future deadlines exist."""
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-bnd-004",
                state="open",
                submitted_at=now - timedelta(days=1),
                sla_deadline=now + timedelta(days=6),  # future deadline
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "T2S-bnd-004" not in codes


# ---------------------------------------------------------------------------
# 3. find_at_risk_disputes: exact window boundary + combined checks
# ---------------------------------------------------------------------------


class TestFindAtRiskExactBoundary:
    def test_exactly_at_window_boundary_is_at_risk(self, db_conn: Any) -> None:
        """sla_deadline == now + warn_within_hours exactly IS at-risk (SQL uses <=, inclusive)."""
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)
        # Set deadline exactly at the 24-hour boundary.
        sla = now + timedelta(hours=24)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-risk-001",
                state="open",
                submitted_at=now - timedelta(days=6),
                sla_deadline=sla,
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "T2S-risk-001" in codes, (
            "sla_deadline == now + warn_within_hours must be at-risk (inclusive boundary)"
        )

    def test_one_second_past_window_is_not_at_risk(self, db_conn: Any) -> None:
        """sla_deadline == now + 24h + 1s is outside the window; NOT at-risk."""
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)
        # One second beyond the 24-hour window.
        sla = now + timedelta(hours=24, seconds=1)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-risk-002",
                state="open",
                submitted_at=now - timedelta(days=6),
                sla_deadline=sla,
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "T2S-risk-002" not in codes, (
            "sla_deadline 1 second past the warn window must NOT be at-risk"
        )

    def test_sla_deadline_exactly_now_is_at_risk_but_not_breached(self, db_conn: Any) -> None:
        """sla_deadline == now: find_at_risk includes it (>= now); find_breached does not (< now).

        This asserts the precise classification split at the boundary: a dispute
        whose deadline is exactly 'now' is at-risk (warning), not yet breached.
        """
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-risk-003",
                state="open",
                submitted_at=now - timedelta(days=7),
                sla_deadline=now,  # exactly now
            )

        at_risk_codes = [d.ticket_code for d in find_at_risk_disputes(db_conn, now)]
        breached_codes = [d.ticket_code for d in find_breached_disputes(db_conn, now)]

        assert "T2S-risk-003" in at_risk_codes, (
            "sla_deadline == now must appear in at-risk list (>= condition is inclusive)"
        )
        assert "T2S-risk-003" not in breached_codes, (
            "sla_deadline == now must NOT appear in breached list (< condition is strict)"
        )

    def test_rejected_dispute_excluded_from_at_risk(self, db_conn: Any) -> None:
        """'rejected' state inside the warning window is NOT at-risk.

        Existing test_sla.py only tests 'corrected'. 'rejected' is the third adjudicated state.
        """
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-risk-004",
                state="rejected",
                submitted_at=now - timedelta(days=7),
                sla_deadline=now + timedelta(hours=6),  # inside 24h window
                adjudicated_at=now - timedelta(hours=1),
                adjudication_note="Rejected: invalid submission.",
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "T2S-risk-004" not in codes, (
            "'rejected' dispute must not appear in at-risk list; only active states qualify"
        )

    def test_upheld_dispute_excluded_from_at_risk(self, db_conn: Any) -> None:
        """'upheld' state inside the warning window is NOT at-risk.

        Existing test_sla.py tests 'corrected'. This adds 'upheld' for completeness.
        """
        now = datetime(2026, 6, 20, 8, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-risk-005",
                state="upheld",
                submitted_at=now - timedelta(days=7),
                sla_deadline=now + timedelta(hours=2),  # inside 24h window
                adjudicated_at=now - timedelta(hours=2),
                adjudication_note="Upheld: dispute accepted.",
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "T2S-risk-005" not in codes, (
            "'upheld' dispute must not appear in at-risk list; only active states qualify"
        )


# ---------------------------------------------------------------------------
# 4. run_sla_check: combined alert count + at-risk dedup + None alerter
# ---------------------------------------------------------------------------


class TestRunSlaCheckEdges:
    def test_combined_breach_and_atrisk_exact_dispatched_count(self, db_conn: Any) -> None:
        """Seeding one breached and one at-risk dispute yields exactly 2 dispatched alerts."""
        now = datetime(2026, 6, 20, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)

            # Breached dispute: deadline 3 days ago.
            cid_b = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_b,
                ticket_code="T2S-chk-001",
                state="open",
                submitted_at=now - timedelta(days=10),
                sla_deadline=now - timedelta(days=3),
            )

            # At-risk dispute: deadline 6 hours from now (inside 24h window).
            cid_r = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_r,
                ticket_code="T2S-chk-002",
                state="open",
                submitted_at=now - timedelta(days=6, hours=18),
                sla_deadline=now + timedelta(hours=6),
            )

        alerter = FakeAlerter()
        result = run_sla_check(db_conn, alerter, now)

        # No dispute is ever committed, so the rolled-back fixture guarantees
        # EXACTLY one breached and one at-risk dispute — assert exact counts so a
        # double-dispatch regression cannot hide behind a loose lower bound.
        assert result["breached"] == 1
        assert result["at_risk"] == 1

        # Exactly 2 dispatches: one for breach, one for at-risk, and nothing else.
        our_keys = {
            "dispute_sla_breach:T2S-chk-001",
            "dispute_sla_at_risk:T2S-chk-002:2026-06",
        }
        dispatched_keys = {a.dedup_key for a in alerter.dispatched}
        assert dispatched_keys == our_keys, (
            f"Expected exactly the breach + at-risk dedup_keys; got {dispatched_keys}"
        )
        assert result["alerts_raised"] == 2, (
            f"Expected exactly 2 alerts_raised; got {result['alerts_raised']}"
        )

    def test_atrisk_alert_dedup_on_rerun(self, db_conn: Any) -> None:
        """Re-running run_sla_check with the same now does not duplicate at-risk alerts.

        The breach dedup is tested in test_sla.py. This test covers the at-risk
        dedup key which includes the billing period: 'dispute_sla_at_risk:{code}:{period}'.
        """
        now = datetime(2026, 6, 20, 11, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-chk-003",
                state="open",
                submitted_at=now - timedelta(days=6, hours=20),
                sla_deadline=now + timedelta(hours=4),  # at-risk, 4h remaining
            )

        alerter = FakeAlerter()

        # First run: at-risk alert raised.
        result1 = run_sla_check(db_conn, alerter, now)
        first_count = len(alerter.dispatched)
        assert result1["at_risk"] >= 1
        assert first_count >= 1, "Expected at least one dispatch on first run"

        # Second run with identical now: dedup_key already present — no new dispatch.
        result2 = run_sla_check(db_conn, alerter, now)
        assert result2["alerts_raised"] == 0, (
            f"Re-run must raise 0 new alerts (at-risk dedup); got {result2['alerts_raised']}"
        )
        assert len(alerter.dispatched) == first_count, (
            "FakeAlerter.dispatched must not grow on re-run (at-risk dedup)"
        )

    def test_alerter_none_does_not_crash(self, db_conn: Any) -> None:
        """Passing alerter=None to run_sla_check is safe; alerts still recorded in DB.

        The 'alerter=None' path skips external dispatch but still calls record_alert
        (dedup via DB). No crash should occur.
        """
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-chk-004",
                state="open",
                submitted_at=now - timedelta(days=9),
                sla_deadline=now - timedelta(days=2),  # breached
            )

        # Must not raise; alerter=None means no external dispatch.
        result = run_sla_check(db_conn, None, now)
        assert result["breached"] >= 1
        # alerts_raised reflects DB inserts even without dispatch.
        assert isinstance(result["alerts_raised"], int)

    def test_run_sla_check_returns_zero_counts_with_no_active_disputes(self, db_conn: Any) -> None:
        """run_sla_check returns zeros when only adjudicated disputes exist."""
        now = datetime(2026, 6, 20, 9, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            # Adjudicated (upheld) — should not trigger any alert.
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-chk-005",
                state="upheld",
                submitted_at=now - timedelta(days=8),
                sla_deadline=now - timedelta(days=1),
                adjudicated_at=now - timedelta(days=3),
                adjudication_note="Upheld.",
            )

        alerter = FakeAlerter()
        result = run_sla_check(db_conn, alerter, now)

        assert result["breached"] == 0
        assert result["at_risk"] == 0
        assert result["alerts_raised"] == 0
        assert len(alerter.dispatched) == 0


# ---------------------------------------------------------------------------
# 5. weekly_dispute_report: non-vacuous 100%, odd-count median, empty window
# ---------------------------------------------------------------------------


class TestWeeklyDisputeReportEdges:
    def test_pct_within_sla_100_all_adjudicated_on_time(self, db_conn: Any) -> None:
        """pct_within_sla = 1.0 when all disputes ARE adjudicated and ALL within 7 days.

        This is the non-vacuous 100% case.  Existing test_sla.py only tests vacuous
        100% (zero adjudicated).  This seeds two adjudicated-within-SLA disputes.
        """
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)

            # Dispute A: 2 days to adjudicate (well within 7-day SLA).
            submitted_a = now - timedelta(days=5)
            cid_a = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_a,
                ticket_code="T2S-rpt-001",
                state="upheld",
                submitted_at=submitted_a,
                sla_deadline=submitted_a + timedelta(days=7),
                adjudicated_at=submitted_a + timedelta(days=2),
            )

            # Dispute B: 4 days to adjudicate (within 7-day SLA).
            submitted_b = now - timedelta(days=6)
            cid_b = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_b,
                ticket_code="T2S-rpt-002",
                state="corrected",
                submitted_at=submitted_b,
                sla_deadline=submitted_b + timedelta(days=7),
                adjudicated_at=submitted_b + timedelta(days=4),
            )

        report = weekly_dispute_report(db_conn, now=now, window_days=7)

        assert report.adjudicated >= 2, f"Expected >=2 adjudicated; got {report.adjudicated}"
        assert report.pct_within_sla == pytest.approx(1.0, abs=0.001), (
            f"All disputes adjudicated within SLA: expected pct=1.0, got {report.pct_within_sla}"
        )
        assert report.median_time_to_adjudication_hours is not None

    def test_median_over_odd_count_three_disputes(self, db_conn: Any) -> None:
        """Median over 3 durations is the middle element (not an average of two).

        Existing test_sla.py only tests median over 2 (even count, average of the two).
        With 3 disputes (24h, 48h, 120h), the median should be the middle: 48h.
        """
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)

            # Dispute A: 1 day (24h).
            submitted_a = now - timedelta(days=6)
            cid_a = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_a,
                ticket_code="T2S-rpt-003",
                state="upheld",
                submitted_at=submitted_a,
                sla_deadline=submitted_a + timedelta(days=7),
                adjudicated_at=submitted_a + timedelta(days=1),  # 24h
            )

            # Dispute B: 2 days (48h) — this is the median.
            submitted_b = now - timedelta(days=6, hours=1)
            cid_b = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_b,
                ticket_code="T2S-rpt-004",
                state="corrected",
                submitted_at=submitted_b,
                sla_deadline=submitted_b + timedelta(days=7),
                adjudicated_at=submitted_b + timedelta(days=2),  # 48h
            )

            # Dispute C: 5 days (120h).
            submitted_c = now - timedelta(days=6, hours=2)
            cid_c = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_c,
                ticket_code="T2S-rpt-005",
                state="rejected",
                submitted_at=submitted_c,
                sla_deadline=submitted_c + timedelta(days=7),
                adjudicated_at=submitted_c + timedelta(days=5),  # 120h
            )

        report = weekly_dispute_report(db_conn, now=now, window_days=7)

        assert report.adjudicated >= 3, f"Expected >=3 adjudicated; got {report.adjudicated}"
        assert report.median_time_to_adjudication_hours is not None

        # With exactly 3 disputes [24h, 48h, 120h], statistics.median returns 48h.
        # If other disputes from seed happen to exist (unlikely), the median may
        # shift.  Assert it is within a reasonable range given our seeded set.
        # Since the rolled-back fixture guarantees only our 3 exist here, expect 48h.
        median_h = report.median_time_to_adjudication_hours
        assert abs(median_h - 48.0) < 1.0, f"Median of [24h, 48h, 120h] must be 48h; got {median_h}"

    def test_empty_window_returns_zero_report_no_divide_by_zero(self, db_conn: Any) -> None:
        """No disputes in the window returns a sane zero report; no divide-by-zero.

        Existing test_sla.py seeds one open dispute in its 'zero adjudicated' test.
        This uses a 1-second window far enough in the past that NO disputes exist.
        """
        # Use a window whose end is in the past where no data exists.
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)
        # A 1-day window starting 30 days ago: submitted_at >= (now - 1d - 29d) = 30d ago
        # Since seed.py inserts no disputes, this window is empty.
        far_past_now = now - timedelta(days=365)  # 1 year ago

        report = weekly_dispute_report(db_conn, now=far_past_now, window_days=1)

        assert report.total == 0, f"Expected 0 total in empty window; got {report.total}"
        assert report.adjudicated == 0
        assert report.open_count == 0
        assert report.breached_count == 0
        # Vacuous SLA: no adjudicated disputes means pct is 1.0 by definition.
        assert report.pct_within_sla == 1.0, (
            "Empty window pct_within_sla must be 1.0 (vacuously met)"
        )
        # Median is undefined with zero data points; must be None, not crash.
        assert report.median_time_to_adjudication_hours is None, (
            "Median must be None when no adjudicated disputes (no divide-by-zero)"
        )

    def test_weekly_report_window_days_param_respected(self, db_conn: Any) -> None:
        """Disputes submitted outside the window_days lookback are excluded.

        Existing tests always use the default 7-day window. This verifies that a
        narrower window_days=1 excludes a dispute submitted 2 days ago.
        """
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)
            cid = _seed_claim(cur, a_id, v_id, t_id)
            # Submitted 2 days ago — outside a 1-day window.
            _seed_dispute(
                cur,
                cid,
                ticket_code="T2S-rpt-006",
                state="upheld",
                submitted_at=now - timedelta(days=2),
                sla_deadline=(now - timedelta(days=2)) + timedelta(days=7),
                adjudicated_at=now - timedelta(days=1),
            )

        # window_days=1 means submitted_at >= now - 1 day.
        report = weekly_dispute_report(db_conn, now=now, window_days=1)

        # The dispute submitted 2 days ago is outside the 1-day window, and no
        # dispute is ever committed, so the windowed report counts nothing.
        assert report.total == 0, f"No disputes in 1-day window; got total={report.total}"

    def test_weekly_report_pct_zero_all_late(self, db_conn: Any) -> None:
        """pct_within_sla = 0.0 when all adjudicated disputes exceeded the 7-day SLA.

        Existing test_sla.py tests 0.5 (one on time, one late). This tests the 0%
        boundary.
        """
        now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            a_id, v_id, t_id = _get_analyst_video_transcript(cur)

            # Dispute A: 9-day adjudication (past 7-day SLA).
            submitted_a = now - timedelta(days=6)
            cid_a = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_a,
                ticket_code="T2S-rpt-007",
                state="upheld",
                submitted_at=submitted_a,
                sla_deadline=submitted_a + timedelta(days=7),
                adjudicated_at=submitted_a + timedelta(days=9),  # 9 days → miss SLA
            )

            # Dispute B: 10-day adjudication (past 7-day SLA).
            submitted_b = now - timedelta(days=6, hours=1)
            cid_b = _seed_claim(cur, a_id, v_id, t_id)
            _seed_dispute(
                cur,
                cid_b,
                ticket_code="T2S-rpt-008",
                state="corrected",
                submitted_at=submitted_b,
                sla_deadline=submitted_b + timedelta(days=7),
                adjudicated_at=submitted_b + timedelta(days=10),  # 10 days → miss SLA
            )

        report = weekly_dispute_report(db_conn, now=now, window_days=7)

        assert report.adjudicated >= 2
        assert report.pct_within_sla == pytest.approx(0.0, abs=0.001), (
            f"All disputes past SLA: expected pct=0.0, got {report.pct_within_sla}"
        )
