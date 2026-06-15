"""E6-T5 GDPR/KVKK erasure handling tests (PRD NFR-6).

Test categories:
  1. Unit tests (no DB):
     - evaluate_balancing_test returns PARTIAL + requires_manual_review=True
       when touches_published_claim=True.
     - evaluate_balancing_test returns ERASE for personal-data-only scope.
     - evaluate_balancing_test returns RETAIN_LEGITIMATE_INTEREST for
       published-statistics scope (default).
  2. DB-backed tests (db_conn rolled-back fixture):
     - create_erasure_request: due_at = received_at + 30 days; state='received'.
     - record_erasure_decision: updates state/outcome; does NOT delete any
       seeded resolution or claim row (NFR-3 ledger discipline).
     - find_overdue_requests: returns requests in (received,in_review) with
       due_at < now; completed/rejected are excluded.
     - run_erasure_sla_check: raises an 'erasure_overdue' alert for each
       overdue request; idempotent on re-run (dedup_key unique constraint).
     - Handler registration: 'erasure_sla_check' is registered at module load.

All DB-backed tests use the rolled-back db_conn fixture (conftest.py) and seed
their own rows — no coupling to demo state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from brier_pipeline.ops.alerts import FakeAlerter
from brier_pipeline.ops.erasure import (
    BalancingDecision,
    BalancingOutcome,
    create_erasure_request,
    evaluate_balancing_test,
    find_overdue_requests,
    record_erasure_decision,
    run_erasure_sla_check,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


def _get_analyst_video_transcript(cur: Any) -> tuple[int, int, int]:
    """Return (analyst_id, video_id, transcript_id) from seeded demo data."""
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
            'BTC', 'bullish', 90000.0,
            '2026-12-31', 'stated',
            0.75, 'stated',
            'target_deadline', 60,
            'erasure test claim fewer than fifteen words.',
            '2026-01-01 00:00:00+00', 88000.0,
            'test', 'test',
            'approved', true, 'open', '{}'
        ) returning id
        """,
        (analyst_id, video_id, transcript_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_resolution(cur: Any, claim_id: int) -> int:
    """Insert a synthetic resolution and return its id."""
    cur.execute(
        """
        insert into resolutions (
            claim_id, outcome, rule_id, rationale,
            price_citation, methodology_version
        ) values (
            %s, 1.0, 'target_by_deadline.v0',
            'Erasure NFR-3 test resolution; target met.',
            '{"day": "2026-11-01", "close_usd": 91000.0, "source": "fixture-composite"}'::jsonb,
            'v1.1'
        ) returning id
        """,
        (claim_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_erasure_request(
    cur: Any,
    *,
    subject_ref: str,
    scope: str,
    state: str = "received",
    received_at: datetime,
    due_at: datetime,
) -> int:
    """Insert a synthetic erasure request and return its id."""
    cur.execute(
        """
        insert into erasure_requests (subject_ref, scope, state, received_at, due_at)
        values (%s, %s, %s, %s, %s)
        returning id
        """,
        (subject_ref, scope, state, received_at, due_at),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# 1. Unit tests: evaluate_balancing_test
# ---------------------------------------------------------------------------


class TestEvaluateBalancingTest:
    """Unit tests for the legitimate-interest balancing test logic (no DB)."""

    def test_touches_published_claim_returns_partial_with_manual_review(self) -> None:
        """When touches_published_claim=True, outcome is PARTIAL + requires_manual_review."""
        decision = evaluate_balancing_test(
            "all data related to my predictions",
            touches_published_claim=True,
        )
        assert isinstance(decision, BalancingDecision)
        assert decision.outcome == BalancingOutcome.PARTIAL
        assert decision.requires_manual_review is True
        assert "public statement" in decision.rationale.lower()

    def test_partial_rationale_mentions_retained_legitimate_interest(self) -> None:
        """PARTIAL rationale must explain that the published statistic is retained."""
        decision = evaluate_balancing_test(
            "my score and resolutions",
            touches_published_claim=True,
        )
        rationale_lower = decision.rationale.lower()
        assert "legitimate interest" in rationale_lower
        assert "retained" in rationale_lower

    def test_personal_data_only_scope_returns_erase(self) -> None:
        """A scope covering only personal contact data returns ERASE."""
        decision = evaluate_balancing_test(
            "my email address and contact details",
            touches_published_claim=False,
        )
        assert decision.outcome == BalancingOutcome.ERASE
        assert decision.requires_manual_review is False

    def test_erase_rationale_mentions_no_legitimate_interest(self) -> None:
        """ERASE rationale must state no legitimate-interest basis was identified."""
        decision = evaluate_balancing_test(
            "newsletter subscriber address",
            touches_published_claim=False,
        )
        assert "legitimate" in decision.rationale.lower()
        assert decision.outcome == BalancingOutcome.ERASE

    def test_published_statistics_scope_returns_retain(self) -> None:
        """A scope covering published-statistics data returns RETAIN_LEGITIMATE_INTEREST."""
        decision = evaluate_balancing_test(
            "all statistics published about my channel",
            touches_published_claim=False,
        )
        assert decision.outcome == BalancingOutcome.RETAIN_LEGITIMATE_INTEREST
        assert decision.requires_manual_review is False

    def test_retain_rationale_mentions_legitimate_interest(self) -> None:
        """RETAIN rationale must explain the legitimate-interest basis."""
        decision = evaluate_balancing_test(
            "all records about my predictions on this platform",
            touches_published_claim=False,
        )
        assert "legitimate interest" in decision.rationale.lower()

    def test_vague_scope_defaults_to_retain(self) -> None:
        """A vague scope that mentions no personal-data-only keywords defaults to RETAIN."""
        decision = evaluate_balancing_test(
            "everything",
            touches_published_claim=False,
        )
        assert decision.outcome == BalancingOutcome.RETAIN_LEGITIMATE_INTEREST

    def test_scope_with_published_keyword_not_erased_despite_personal_kw(self) -> None:
        """A scope mentioning 'email' AND 'published' does not default to ERASE."""
        decision = evaluate_balancing_test(
            "my email address and all published claim records",
            touches_published_claim=False,
        )
        # 'published' keyword prevents ERASE; falls to RETAIN.
        assert decision.outcome == BalancingOutcome.RETAIN_LEGITIMATE_INTEREST

    def test_touches_published_claim_overrides_personal_data_keywords(self) -> None:
        """touches_published_claim=True always yields PARTIAL regardless of scope text."""
        decision = evaluate_balancing_test(
            "only my personal email",
            touches_published_claim=True,
        )
        assert decision.outcome == BalancingOutcome.PARTIAL


# ---------------------------------------------------------------------------
# 2. DB-backed tests: create_erasure_request
# ---------------------------------------------------------------------------


class TestCreateErasureRequest:
    """DB-backed tests for create_erasure_request."""

    def test_due_at_is_received_plus_30_days(self, db_conn: Any) -> None:
        """create_erasure_request sets due_at = received_at + 30 days."""
        req = create_erasure_request(
            "user@example.com",
            "all personal data",
            conn=db_conn,
            now=_NOW,
        )
        delta = req.due_at - req.received_at
        assert delta == timedelta(days=30), f"Expected due_at - received_at = 30d, got {delta}"

    def test_state_is_received(self, db_conn: Any) -> None:
        """create_erasure_request sets initial state to 'received'."""
        req = create_erasure_request(
            "subject-ref-abc",
            "my contact details",
            conn=db_conn,
            now=_NOW,
        )
        assert req.state == "received"

    def test_returns_erasure_request_model(self, db_conn: Any) -> None:
        """create_erasure_request returns an ErasureRequest with a non-null id."""
        from brier_pipeline.models import ErasureRequest

        req = create_erasure_request(
            "channel-xyz",
            "all predictions attributed to my channel",
            conn=db_conn,
            now=_NOW,
        )
        assert isinstance(req, ErasureRequest)
        assert req.id is not None
        assert req.id > 0
        assert req.subject_ref == "channel-xyz"

    def test_row_persisted_in_db(self, db_conn: Any) -> None:
        """The created request is queryable from erasure_requests."""
        req = create_erasure_request(
            "db-persist-test",
            "all records",
            conn=db_conn,
            now=_NOW,
        )
        assert req.id is not None
        with db_conn.cursor() as cur:
            cur.execute(
                "select state, subject_ref from erasure_requests where id = %s",
                (req.id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "received"
        assert row[1] == "db-persist-test"

    def test_balancing_outcome_null_on_creation(self, db_conn: Any) -> None:
        """balancing_outcome is None immediately after creation."""
        req = create_erasure_request(
            "null-outcome-test",
            "my email address",
            conn=db_conn,
            now=_NOW,
        )
        assert req.balancing_outcome is None


# ---------------------------------------------------------------------------
# 3. DB-backed tests: record_erasure_decision + NFR-3 preservation
# ---------------------------------------------------------------------------


class TestRecordErasureDecision:
    """DB-backed tests for record_erasure_decision and NFR-3 discipline."""

    def test_updates_state_and_outcome(self, db_conn: Any) -> None:
        """record_erasure_decision sets state, balancing_outcome, decided_at, note."""
        req = create_erasure_request(
            "decision-test-subject",
            "newsletter subscription records",
            conn=db_conn,
            now=_NOW,
        )
        assert req.id is not None

        record_erasure_decision(
            req.id,
            outcome=BalancingOutcome.ERASE,
            note="Personal contact data; no legitimate-interest basis for retention.",
            conn=db_conn,
            now=_NOW,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select state, balancing_outcome, decision_note
                  from erasure_requests where id = %s
                """,
                (req.id,),
            )
            row = cur.fetchone()
        assert row is not None
        state, balancing_outcome, decision_note = row
        assert state == "completed"
        assert balancing_outcome == "erase"
        assert decision_note is not None
        assert "no legitimate-interest" in decision_note.lower()

    def test_retain_outcome_also_sets_completed(self, db_conn: Any) -> None:
        """RETAIN_LEGITIMATE_INTEREST outcome also sets state to 'completed'."""
        req = create_erasure_request(
            "retain-test-subject",
            "published prediction records",
            conn=db_conn,
            now=_NOW,
        )
        assert req.id is not None

        record_erasure_decision(
            req.id,
            outcome=BalancingOutcome.RETAIN_LEGITIMATE_INTEREST,
            note=(
                "Published statistics about public statements; retained under legitimate interest."
            ),
            conn=db_conn,
            now=_NOW,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                "select state, balancing_outcome from erasure_requests where id = %s",
                (req.id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "completed"
        assert row[1] == "retain_legitimate_interest"

    def test_explicit_rejected_state(self, db_conn: Any) -> None:
        """Caller may pass new_state='rejected' for out-of-scope requests."""
        req = create_erasure_request(
            "rejected-test-subject",
            "all youtube content ever uploaded",
            conn=db_conn,
            now=_NOW,
        )
        assert req.id is not None

        record_erasure_decision(
            req.id,
            outcome=BalancingOutcome.RETAIN_LEGITIMATE_INTEREST,
            note="Request is outside the scope of this service's data holdings.",
            conn=db_conn,
            now=_NOW,
            new_state="rejected",
        )

        with db_conn.cursor() as cur:
            cur.execute(
                "select state from erasure_requests where id = %s",
                (req.id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "rejected"

    def test_nfr3_resolutions_not_deleted_after_decision(self, db_conn: Any) -> None:
        """NFR-3: record_erasure_decision does NOT delete any resolution rows."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            resolution_id = _seed_resolution(cur, claim_id)

        # Create and decide an erasure request.
        req = create_erasure_request(
            "nfr3-test-subject",
            "all claims and resolutions",
            conn=db_conn,
            now=_NOW,
        )
        assert req.id is not None
        record_erasure_decision(
            req.id,
            outcome=BalancingOutcome.ERASE,
            note="Test decision — NFR-3 preservation check.",
            conn=db_conn,
            now=_NOW,
        )

        # The seeded resolution must still exist.
        with db_conn.cursor() as cur:
            cur.execute(
                "select id from resolutions where id = %s",
                (resolution_id,),
            )
            row = cur.fetchone()
        assert row is not None, (
            f"NFR-3 violated: resolution row {resolution_id} was deleted by "
            "record_erasure_decision. Resolutions are append-only ledger rows."
        )

    def test_nfr3_claims_not_deleted_after_decision(self, db_conn: Any) -> None:
        """NFR-3: record_erasure_decision does NOT delete any claim rows."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        req = create_erasure_request(
            "nfr3-claims-test",
            "all claims",
            conn=db_conn,
            now=_NOW,
        )
        assert req.id is not None
        record_erasure_decision(
            req.id,
            outcome=BalancingOutcome.PARTIAL,
            note="PARTIAL outcome — claim row must remain per NFR-3.",
            conn=db_conn,
            now=_NOW,
        )

        with db_conn.cursor() as cur:
            cur.execute("select id from claims where id = %s", (claim_id,))
            row = cur.fetchone()
        assert row is not None, (
            f"NFR-3 violated: claim row {claim_id} was deleted. Claims are mutable "
            "working state but must not be deleted by erasure processing."
        )


# ---------------------------------------------------------------------------
# 4. DB-backed tests: find_overdue_requests
# ---------------------------------------------------------------------------


class TestFindOverdueRequests:
    """DB-backed tests for find_overdue_requests."""

    def test_overdue_received_request_returned(self, db_conn: Any) -> None:
        """A 'received' request past due_at is returned."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=5)  # 5 days past deadline

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="overdue-recv-test",
                scope="all personal data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        overdue = find_overdue_requests(db_conn, _NOW)
        subject_refs = [r.subject_ref for r in overdue]
        assert "overdue-recv-test" in subject_refs

    def test_overdue_in_review_request_returned(self, db_conn: Any) -> None:
        """An 'in_review' request past due_at is returned."""
        received_at = _NOW - timedelta(days=40)
        due_at = _NOW - timedelta(days=10)

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="overdue-inrev-test",
                scope="contact details",
                state="in_review",
                received_at=received_at,
                due_at=due_at,
            )

        overdue = find_overdue_requests(db_conn, _NOW)
        subject_refs = [r.subject_ref for r in overdue]
        assert "overdue-inrev-test" in subject_refs

    def test_completed_request_not_returned(self, db_conn: Any) -> None:
        """A 'completed' request (past due) is NOT returned as overdue."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=5)

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="completed-not-overdue",
                scope="all data",
                state="completed",
                received_at=received_at,
                due_at=due_at,
            )

        overdue = find_overdue_requests(db_conn, _NOW)
        subject_refs = [r.subject_ref for r in overdue]
        assert "completed-not-overdue" not in subject_refs

    def test_rejected_request_not_returned(self, db_conn: Any) -> None:
        """A 'rejected' request is NOT returned as overdue."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=5)

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="rejected-not-overdue",
                scope="all data",
                state="rejected",
                received_at=received_at,
                due_at=due_at,
            )

        overdue = find_overdue_requests(db_conn, _NOW)
        subject_refs = [r.subject_ref for r in overdue]
        assert "rejected-not-overdue" not in subject_refs

    def test_not_yet_due_request_not_returned(self, db_conn: Any) -> None:
        """A 'received' request with due_at in the future is NOT overdue."""
        received_at = _NOW - timedelta(days=5)
        due_at = _NOW + timedelta(days=25)

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="not-yet-due-test",
                scope="all data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        overdue = find_overdue_requests(db_conn, _NOW)
        subject_refs = [r.subject_ref for r in overdue]
        assert "not-yet-due-test" not in subject_refs

    def test_results_ordered_by_due_at_ascending(self, db_conn: Any) -> None:
        """find_overdue_requests returns results ordered oldest due_at first."""
        earlier_due = _NOW - timedelta(days=15)
        later_due = _NOW - timedelta(days=3)

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="later-due",
                scope="data",
                state="received",
                received_at=_NOW - timedelta(days=45),
                due_at=later_due,
            )
            _seed_erasure_request(
                cur,
                subject_ref="earlier-due",
                scope="data",
                state="received",
                received_at=_NOW - timedelta(days=50),
                due_at=earlier_due,
            )

        overdue = find_overdue_requests(db_conn, _NOW)
        # Filter to our seeded requests only.
        ours = [r for r in overdue if r.subject_ref in ("earlier-due", "later-due")]
        assert len(ours) >= 2
        # The earliest due_at must come first.
        ours_sorted = sorted(ours, key=lambda r: r.due_at)
        assert ours[0].due_at <= ours[1].due_at
        assert ours[0].subject_ref == ours_sorted[0].subject_ref


# ---------------------------------------------------------------------------
# 5. DB-backed tests: run_erasure_sla_check
# ---------------------------------------------------------------------------


class TestRunErasureSlaCheck:
    """DB-backed tests for run_erasure_sla_check."""

    def test_raises_alert_for_overdue_request(self, db_conn: Any) -> None:
        """run_erasure_sla_check raises an 'erasure_overdue' alert for each overdue."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=5)

        with db_conn.cursor() as cur:
            req_id = _seed_erasure_request(
                cur,
                subject_ref="alert-test-subject",
                scope="all personal data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        alerter = FakeAlerter()
        result = run_erasure_sla_check(db_conn, alerter, _NOW)

        assert result["overdue"] >= 1
        assert result["alerts_raised"] >= 1

        dispatched_keys = {a.dedup_key for a in alerter.dispatched}
        assert f"erasure_overdue:{req_id}" in dispatched_keys

    def test_alert_severity_is_warning(self, db_conn: Any) -> None:
        """erasure_overdue alerts have severity 'warning'."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=2)

        with db_conn.cursor() as cur:
            req_id = _seed_erasure_request(
                cur,
                subject_ref="severity-test-subject",
                scope="data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        alerter = FakeAlerter()
        run_erasure_sla_check(db_conn, alerter, _NOW)

        overdue_alerts = [
            a for a in alerter.dispatched if a.dedup_key == f"erasure_overdue:{req_id}"
        ]
        assert len(overdue_alerts) >= 1
        assert overdue_alerts[0].severity == "warning"

    def test_alert_subject_is_request_id(self, db_conn: Any) -> None:
        """erasure_overdue alert subject is str(request_id)."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=1)

        with db_conn.cursor() as cur:
            req_id = _seed_erasure_request(
                cur,
                subject_ref="subject-id-test",
                scope="data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        alerter = FakeAlerter()
        run_erasure_sla_check(db_conn, alerter, _NOW)

        overdue_alerts = [
            a for a in alerter.dispatched if a.dedup_key == f"erasure_overdue:{req_id}"
        ]
        assert len(overdue_alerts) >= 1
        assert overdue_alerts[0].subject == str(req_id)

    def test_idempotent_on_rerun(self, db_conn: Any) -> None:
        """Re-running run_erasure_sla_check with the same now raises no new alerts."""
        received_at = _NOW - timedelta(days=35)
        due_at = _NOW - timedelta(days=5)

        with db_conn.cursor() as cur:
            _seed_erasure_request(
                cur,
                subject_ref="idem-test-subject",
                scope="all data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        alerter = FakeAlerter()

        # First run.
        result1 = run_erasure_sla_check(db_conn, alerter, _NOW)
        first_alerts_raised = result1["alerts_raised"]
        first_dispatch_count = len(alerter.dispatched)
        assert first_alerts_raised >= 1

        # Second run with identical now -> dedup_key already in DB.
        result2 = run_erasure_sla_check(db_conn, alerter, _NOW)
        assert result2["alerts_raised"] == 0, (
            f"Re-run must raise 0 new alerts (dedup); got {result2['alerts_raised']}"
        )
        assert len(alerter.dispatched) == first_dispatch_count, (
            "No new dispatches on re-run (dedup_key unique constraint)"
        )

    def test_no_alert_for_non_overdue_request(self, db_conn: Any) -> None:
        """run_erasure_sla_check does NOT alert for requests with future due_at."""
        received_at = _NOW - timedelta(days=5)
        due_at = _NOW + timedelta(days=25)

        with db_conn.cursor() as cur:
            req_id = _seed_erasure_request(
                cur,
                subject_ref="non-overdue-subject",
                scope="data",
                state="received",
                received_at=received_at,
                due_at=due_at,
            )

        alerter = FakeAlerter()
        run_erasure_sla_check(db_conn, alerter, _NOW)

        dispatched_keys = {a.dedup_key for a in alerter.dispatched}
        assert f"erasure_overdue:{req_id}" not in dispatched_keys

    def test_returns_dict_with_overdue_and_alerts_raised(self, db_conn: Any) -> None:
        """run_erasure_sla_check returns a dict with 'overdue' and 'alerts_raised' keys."""
        alerter = FakeAlerter()
        result = run_erasure_sla_check(db_conn, alerter, _NOW)
        assert "overdue" in result
        assert "alerts_raised" in result
        assert isinstance(result["overdue"], int)
        assert isinstance(result["alerts_raised"], int)


# ---------------------------------------------------------------------------
# 6. Handler registration
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    def test_erasure_sla_check_handler_registered(self) -> None:
        """'erasure_sla_check' job kind is registered at module load."""
        # erasure.py is imported at module scope (top of this file), registering
        # its job handler at load time.
        from brier_pipeline.jobs.worker import get_handler

        handler = get_handler("erasure_sla_check")
        assert handler is not None, "'erasure_sla_check' handler must be registered"
        assert callable(handler)
