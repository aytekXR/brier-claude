"""E6-T1 Dispute SLA tooling tests (PRD AC-5, §7 trust metrics).

Tests cover:
  1. time_to_breach (unit, no DB)
  2. find_breached_disputes: past deadline + active state
  3. find_at_risk_disputes: within warning window + active state
  4. Adjudicated disputes are NOT breached / at-risk
  5. run_sla_check: one breach alert per breached ticket, idempotent on re-run
  6. weekly_dispute_report: correct pct_within_sla + median on a mixed set
     (one adjudicated-in-3-days, one in-9-days -> pct 0.5) + breached open counts

All DB-backed tests use the rolled-back db_conn fixture (conftest.py).
Disputes are seeded with controlled submitted_at/sla_deadline/state values
via raw INSERTs (helper pattern from test_disputes.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from brier_pipeline.disputes.sla import (
    DisputeReport,
    find_at_risk_disputes,
    find_breached_disputes,
    run_sla_check,
    time_to_breach,
    weekly_dispute_report,
)
from brier_pipeline.models import Dispute
from brier_pipeline.ops.alerts import FakeAlerter

# ---------------------------------------------------------------------------
# DB seed helpers (mirroring test_disputes.py pattern)
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


def _seed_claim(
    cur: Any,
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    *,
    status: str = "open",
) -> int:
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
            'sla test claim fewer than fifteen words.',
            '2025-01-01 00:00:00+00', 79000.0,
            'test', 'test',
            'approved', true, %s, '{}'
        ) returning id
        """,
        (analyst_id, video_id, transcript_id, status),
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
            %s, %s, 'test@example.com', 'SLA test dispute rationale.',
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
# 1. time_to_breach (unit, no DB)
# ---------------------------------------------------------------------------


class TestTimeToBreach:
    def test_future_deadline_positive_timedelta(self) -> None:
        """time_to_breach returns positive timedelta when deadline is in the future."""
        now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
        sla = now + timedelta(hours=36)
        dispute = Dispute(
            id=1,
            ticket_code="DSP-aabbccdd",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=sla,
        )
        ttb = time_to_breach(dispute, now)
        assert ttb > timedelta(0)
        assert abs(ttb.total_seconds() - 36 * 3600) < 1

    def test_past_deadline_negative_timedelta(self) -> None:
        """time_to_breach returns negative timedelta when deadline has passed."""
        now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
        sla = now - timedelta(hours=10)
        dispute = Dispute(
            id=2,
            ticket_code="DSP-11223344",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=sla,
        )
        ttb = time_to_breach(dispute, now)
        assert ttb < timedelta(0)
        assert abs(ttb.total_seconds() + 10 * 3600) < 1

    def test_exact_deadline_zero(self) -> None:
        """time_to_breach returns zero timedelta at exactly the deadline."""
        now = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
        dispute = Dispute(
            id=3,
            ticket_code="DSP-deadbeef",
            claim_id=1,
            rationale="test",
            state="open",
            sla_deadline=now,
        )
        ttb = time_to_breach(dispute, now)
        assert ttb == timedelta(0)


# ---------------------------------------------------------------------------
# 2. find_breached_disputes
# ---------------------------------------------------------------------------


class TestFindBreachedDisputes:
    def test_open_past_deadline_is_breached(self, db_conn: Any) -> None:
        """An open dispute whose sla_deadline is in the past is returned."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=10)
        sla = now - timedelta(days=3)  # 3 days ago = breached

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-breach01",
                state="open",
                submitted_at=submitted,
                sla_deadline=sla,
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "DSP-breach01" in codes

    def test_adjudicating_past_deadline_is_breached(self, db_conn: Any) -> None:
        """An 'adjudicating' dispute past its deadline is returned."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=8)
        sla = now - timedelta(hours=1)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-adjbr01",
                state="adjudicating",
                submitted_at=submitted,
                sla_deadline=sla,
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "DSP-adjbr01" in codes

    def test_future_deadline_not_breached(self, db_conn: Any) -> None:
        """A dispute with a future deadline is NOT in the breached list."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=2)
        sla = now + timedelta(days=5)  # still has time

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-futbr01",
                state="open",
                submitted_at=submitted,
                sla_deadline=sla,
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "DSP-futbr01" not in codes

    def test_adjudicated_dispute_not_breached(self, db_conn: Any) -> None:
        """A dispute that has been adjudicated (upheld) is NOT breached."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=10)
        sla = now - timedelta(days=3)
        adj_at = now - timedelta(days=2)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-upheld1",
                state="upheld",
                submitted_at=submitted,
                sla_deadline=sla,
                adjudicated_at=adj_at,
            )

        result = find_breached_disputes(db_conn, now)
        codes = [d.ticket_code for d in result]
        assert "DSP-upheld1" not in codes, "Upheld dispute must not appear in breached list"


# ---------------------------------------------------------------------------
# 3. find_at_risk_disputes
# ---------------------------------------------------------------------------


class TestFindAtRiskDisputes:
    def test_dispute_within_24h_is_at_risk(self, db_conn: Any) -> None:
        """A dispute with sla_deadline within the next 24h is at-risk."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=6, hours=18)
        sla = now + timedelta(hours=6)  # 6h remaining -> within 24h window

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-risk001",
                state="open",
                submitted_at=submitted,
                sla_deadline=sla,
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "DSP-risk001" in codes

    def test_dispute_outside_warn_window_not_at_risk(self, db_conn: Any) -> None:
        """A dispute with deadline outside the warning window is NOT at-risk."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=3)
        sla = now + timedelta(days=4)  # 4d remaining -> outside 24h window

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-safe001",
                state="open",
                submitted_at=submitted,
                sla_deadline=sla,
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "DSP-safe001" not in codes

    def test_already_breached_not_at_risk(self, db_conn: Any) -> None:
        """An already-breached dispute (sla_deadline < now) is NOT in at-risk list."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=9)
        sla = now - timedelta(hours=2)  # already past deadline

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-bralr01",
                state="open",
                submitted_at=submitted,
                sla_deadline=sla,
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "DSP-bralr01" not in codes, (
            "Already-breached dispute must not appear in at-risk list (sla_deadline < now)"
        )

    def test_adjudicated_dispute_not_at_risk(self, db_conn: Any) -> None:
        """A 'corrected' dispute within the warning window is NOT at-risk."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        submitted = now - timedelta(days=7)
        sla = now + timedelta(hours=1)
        adj_at = now - timedelta(hours=1)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-corra01",
                state="corrected",
                submitted_at=submitted,
                sla_deadline=sla,
                adjudicated_at=adj_at,
            )

        result = find_at_risk_disputes(db_conn, now, warn_within_hours=24)
        codes = [d.ticket_code for d in result]
        assert "DSP-corra01" not in codes


# ---------------------------------------------------------------------------
# 4. run_sla_check: breach alert raised exactly once per ticket (idempotent)
# ---------------------------------------------------------------------------


class TestRunSlaCheck:
    def test_breach_alert_raised_for_each_breached_ticket(self, db_conn: Any) -> None:
        """run_sla_check raises exactly one breach alert per breached dispute ticket."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id_a = _seed_claim(cur, analyst_id, video_id, transcript_id)
            claim_id_b = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id_a,
                ticket_code="DSP-chk0001",
                state="open",
                submitted_at=now - timedelta(days=10),
                sla_deadline=now - timedelta(days=3),
            )
            _seed_dispute(
                cur,
                claim_id_b,
                ticket_code="DSP-chk0002",
                state="adjudicating",
                submitted_at=now - timedelta(days=8),
                sla_deadline=now - timedelta(hours=1),
            )

        alerter = FakeAlerter()
        result = run_sla_check(db_conn, alerter, now)

        # Verify counts.
        assert result["breached"] >= 2, f"Expected >=2 breached, got {result['breached']}"

        # Verify breach alert dispatched for our two tickets.
        dispatched_keys = {a.dedup_key for a in alerter.dispatched}
        assert "dispute_sla_breach:DSP-chk0001" in dispatched_keys
        assert "dispute_sla_breach:DSP-chk0002" in dispatched_keys

        # Verify severities are critical.
        for alert in alerter.dispatched:
            if alert.kind == "dispute_sla_breach":
                assert alert.severity == "critical", (
                    f"Breach alert must be critical; got {alert.severity!r}"
                )

    def test_breach_alert_is_idempotent_on_rerun(self, db_conn: Any) -> None:
        """Re-running run_sla_check with same now raises no additional alerts (dedup)."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-idem001",
                state="open",
                submitted_at=now - timedelta(days=9),
                sla_deadline=now - timedelta(days=2),
            )

        alerter = FakeAlerter()

        # First run: breach alert raised.
        result1 = run_sla_check(db_conn, alerter, now)
        first_alerts_raised = result1["alerts_raised"]
        first_dispatch_count = len(alerter.dispatched)
        assert first_alerts_raised >= 1

        # Second run: dedup key already in DB — no new alerts raised.
        result2 = run_sla_check(db_conn, alerter, now)
        assert result2["alerts_raised"] == 0, (
            f"Re-run must raise 0 new alerts (dedup); got {result2['alerts_raised']}"
        )
        # No new dispatches.
        assert len(alerter.dispatched) == first_dispatch_count, "No new dispatches on re-run"

    def test_at_risk_alert_kind_and_severity(self, db_conn: Any) -> None:
        """run_sla_check raises a 'dispute_sla_at_risk' warning for at-risk tickets."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-risk999",
                state="open",
                submitted_at=now - timedelta(days=6, hours=20),
                sla_deadline=now + timedelta(hours=4),  # 4h remaining
            )

        alerter = FakeAlerter()
        result = run_sla_check(db_conn, alerter, now)

        assert result["at_risk"] >= 1

        risk_alerts = [a for a in alerter.dispatched if a.kind == "dispute_sla_at_risk"]
        assert len(risk_alerts) >= 1
        assert risk_alerts[0].severity == "warning"

    def test_already_adjudicated_no_breach_alert(self, db_conn: Any) -> None:
        """A dispute adjudicated before deadline generates no breach alert."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-done001",
                state="upheld",
                submitted_at=now - timedelta(days=8),
                sla_deadline=now - timedelta(days=1),
                adjudicated_at=now - timedelta(days=2),  # adjudicated before deadline
            )

        alerter = FakeAlerter()
        run_sla_check(db_conn, alerter, now)

        breach_alerts = [
            a
            for a in alerter.dispatched
            if a.kind == "dispute_sla_breach" and a.subject == "DSP-done001"
        ]
        assert len(breach_alerts) == 0, "Adjudicated dispute must not generate a breach alert"


# ---------------------------------------------------------------------------
# 5. weekly_dispute_report: correctness on mixed adjudicated set
# ---------------------------------------------------------------------------


class TestWeeklyDisputeReport:
    def test_pct_within_sla_and_median_on_mixed_set(self, db_conn: Any) -> None:
        """pct_within_sla=0.5 + correct median on one 3-day and one 9-day dispute."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        window_start = now - timedelta(days=7)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

            # Dispute A: submitted 3 days ago, adjudicated in 3 days (within SLA).
            submitted_a = now - timedelta(days=6)
            adj_a = submitted_a + timedelta(days=3)
            claim_a = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_a,
                ticket_code="DSP-rpt0001",
                state="upheld",
                submitted_at=submitted_a,
                sla_deadline=submitted_a + timedelta(days=7),
                adjudicated_at=adj_a,
            )

            # Dispute B: submitted 6 days ago, adjudicated in 9 days (outside SLA).
            submitted_b = now - timedelta(days=6, hours=1)
            adj_b = submitted_b + timedelta(days=9)  # 9 days -> MISS SLA
            claim_b = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_dispute(
                cur,
                claim_b,
                ticket_code="DSP-rpt0002",
                state="corrected",
                submitted_at=submitted_b,
                sla_deadline=submitted_b + timedelta(days=7),
                adjudicated_at=adj_b,
            )

        # Ensure both submitted_at values are within the window.
        assert submitted_a >= window_start
        assert submitted_b >= window_start

        report = weekly_dispute_report(db_conn, now=now, window_days=7)

        # Two adjudicated disputes in our seeded batch; there may be others from
        # previous tests but they're rolled back.
        assert report.adjudicated >= 2, (
            f"Expected >=2 adjudicated disputes, got {report.adjudicated}"
        )

        # pct_within_sla should be 0.5 (only 1 of our 2 was within 7 days).
        # Since other tests are rolled back, the only rows here are ours.
        # Use exact assertion since db_conn rolls back between tests.
        assert report.pct_within_sla == pytest.approx(0.5, abs=0.01), (
            f"Expected pct_within_sla=0.5, got {report.pct_within_sla}"
        )

        # Median: (3*24 + 9*24) / 2 = 144h; both are symmetric.
        # Median of [72.0, 216.0] = (72+216)/2 = 144.0 hours.
        assert report.median_time_to_adjudication_hours is not None
        assert abs(report.median_time_to_adjudication_hours - 144.0) < 1.0, (
            f"Expected median ~144h, got {report.median_time_to_adjudication_hours}"
        )

    def test_report_counts_breached_open_separately(self, db_conn: Any) -> None:
        """weekly_dispute_report reports breached_count even when pct_within_sla=1.0."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            # Breached open dispute (past deadline, still open).
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-brcnt01",
                state="open",
                submitted_at=now - timedelta(days=6),
                sla_deadline=now - timedelta(days=1),  # past deadline
            )

        report = weekly_dispute_report(db_conn, now=now, window_days=7)

        # pct_within_sla is 1.0 (vacuously — no adjudicated disputes in this
        # particular scope, only the breached open one we seeded).
        # breached_count must be >= 1 so the reader sees the open breach.
        assert report.breached_count >= 1, (
            f"Expected breached_count >=1, got {report.breached_count}"
        )

    def test_zero_adjudicated_gives_pct_1_and_none_median(self, db_conn: Any) -> None:
        """Zero adjudicated disputes -> pct_within_sla=1.0 (vacuously met) + None median."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            # Open dispute submitted within the window.
            _seed_dispute(
                cur,
                claim_id,
                ticket_code="DSP-vac0001",
                state="open",
                submitted_at=now - timedelta(days=3),
                sla_deadline=now + timedelta(days=4),
            )

        report = weekly_dispute_report(db_conn, now=now, window_days=7)

        # In this rolled-back test, only our one open dispute exists.
        assert report.total >= 1
        assert report.adjudicated == 0
        assert report.pct_within_sla == 1.0, (
            "Vacuously met: pct_within_sla must be 1.0 when no adjudicated disputes"
        )
        assert report.median_time_to_adjudication_hours is None

    def test_report_is_dataclass(self, db_conn: Any) -> None:
        """weekly_dispute_report returns a DisputeReport dataclass."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        report = weekly_dispute_report(db_conn, now=now)
        assert isinstance(report, DisputeReport)

    def test_pct_within_sla_is_float_between_0_and_1(self, db_conn: Any) -> None:
        """pct_within_sla is always in [0.0, 1.0]."""
        now = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
        report = weekly_dispute_report(db_conn, now=now)
        assert 0.0 <= report.pct_within_sla <= 1.0


# ---------------------------------------------------------------------------
# 6. Handler registration verification
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    def test_dispute_sla_check_handler_registered(self) -> None:
        """'dispute_sla_check' job kind is registered at module load."""
        # sla.py is imported at module scope (top of this file), which runs its
        # register_handler() calls at load time.
        from brier_pipeline.jobs.worker import get_handler

        handler = get_handler("dispute_sla_check")
        assert handler is not None, "'dispute_sla_check' handler must be registered"
        assert callable(handler)

    def test_weekly_dispute_report_handler_registered(self) -> None:
        """'weekly_dispute_report' job kind is registered at module load."""
        from brier_pipeline.jobs.worker import get_handler

        handler = get_handler("weekly_dispute_report")
        assert handler is not None, "'weekly_dispute_report' handler must be registered"
        assert callable(handler)
