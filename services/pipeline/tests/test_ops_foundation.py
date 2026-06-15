"""E6 shared foundation tests: Alerter seam + Spend-meter engine.

Test categories:
  1. Unit tests (no DB): billing_period formatting; BetterStackAlerter raises
     RuntimeError without the token.
  2. DB-backed tests (db_conn rolled-back fixture):
     - record_alert inserts a row; second call with same dedup_key returns False.
     - raise_alert with FakeAlerter dispatches exactly once; deduped call skips.
     - spend: record_spend + month_to_date_spend sum correctly within a period.
     - evaluate_spend computes would_exceed_cap and crosses_alert_threshold
       across the 70% and 100% lines.
     - guard_and_record_spend: under threshold -> records, no alert; crossing
       70% -> records + one cost_threshold alert; exceeding 100% -> raises
       SpendCapExceeded, records NO spend row, cost_cap alert is present.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from brier_pipeline.ops.alerts import (
    BetterStackAlerter,
    FakeAlerter,
    SentryAlerter,
    raise_alert,
    record_alert,
)
from brier_pipeline.ops.spend import (
    SpendCapExceeded,
    SpendDecision,
    billing_period,
    evaluate_spend,
    guard_and_record_spend,
    month_to_date_spend,
    record_spend,
)

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
_PERIOD = "2026-06"
_CATEGORY = "llm"  # tests override the cap via BRIER_LLM_MONTHLY_CAP_USD


# ---------------------------------------------------------------------------
# 1. Unit tests (no DB)
# ---------------------------------------------------------------------------


class TestBillingPeriod:
    def test_utc_format(self) -> None:
        """billing_period returns 'YYYY-MM' in UTC."""
        result = billing_period(datetime(2026, 1, 15, tzinfo=UTC))
        assert result == "2026-01"

    def test_end_of_month(self) -> None:
        result = billing_period(datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
        assert result == "2026-12"

    def test_start_of_month(self) -> None:
        result = billing_period(datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC))
        assert result == "2026-03"

    def test_naive_datetime_treated_as_utc(self) -> None:
        result = billing_period(datetime(2025, 11, 5))
        assert result == "2025-11"


class TestBetterStackAlerterKeyGuard:
    def test_raises_runtime_error_when_token_absent(self, monkeypatch: Any) -> None:
        """BetterStackAlerter raises RuntimeError when BRIER_BETTER_STACK_TOKEN is absent."""
        monkeypatch.delenv("BRIER_BETTER_STACK_TOKEN", raising=False)
        from brier_pipeline.models import Alert

        alerter = BetterStackAlerter()
        alert = Alert(
            kind="freshness",
            severity="warning",
            summary="Analyst has not been updated in over 48 hours.",
            dedup_key="freshness:test-slug:2026-06-16",
        )
        with pytest.raises(RuntimeError, match="BRIER_BETTER_STACK_TOKEN"):
            alerter.dispatch(alert)

    def test_adr_reference_in_error_message(self, monkeypatch: Any) -> None:
        """RuntimeError message references ADR-0014."""
        monkeypatch.delenv("BRIER_BETTER_STACK_TOKEN", raising=False)
        from brier_pipeline.models import Alert

        alerter = BetterStackAlerter()
        alert = Alert(
            kind="cost_threshold",
            severity="warning",
            summary="Monthly spend for llm crossed the 70% alert threshold.",
            dedup_key="cost_threshold:llm:2026-06",
        )
        with pytest.raises(RuntimeError, match="0014"):
            alerter.dispatch(alert)

    def test_calls_http_post_when_token_set(self, monkeypatch: Any) -> None:
        """When token is set, BetterStackAlerter calls http_post with correct args."""
        monkeypatch.setenv("BRIER_BETTER_STACK_TOKEN", "test-bs-token")
        from brier_pipeline.models import Alert

        captured: list[tuple[str, dict[str, Any], dict[str, str]]] = []

        def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
            captured.append((url, payload, headers))
            return {}

        alerter = BetterStackAlerter(http_post=fake_post)
        alert = Alert(
            kind="freshness",
            severity="info",
            summary="Data refreshed within the expected window.",
            dedup_key="freshness:northchain:2026-06-16",
        )
        alerter.dispatch(alert)

        assert len(captured) == 1
        url, payload, headers = captured[0]
        assert "betterstack.com" in url or "logs.betterstack.com" in url
        assert payload["kind"] == "freshness"
        assert "Bearer test-bs-token" in headers.get("Authorization", "")


class TestSentryAlerterKeyGuard:
    def test_raises_runtime_error_when_dsn_absent(self, monkeypatch: Any) -> None:
        """SentryAlerter raises RuntimeError when BRIER_SENTRY_DSN is absent."""
        monkeypatch.delenv("BRIER_SENTRY_DSN", raising=False)
        from brier_pipeline.models import Alert

        alerter = SentryAlerter()
        alert = Alert(
            kind="cost_cap",
            severity="critical",
            summary="Monthly spend cap reached for llm; further metered calls are blocked.",
            dedup_key="cost_cap:llm:2026-06",
        )
        with pytest.raises(RuntimeError, match="BRIER_SENTRY_DSN"):
            alerter.dispatch(alert)

    def test_calls_http_post_when_dsn_set(self, monkeypatch: Any) -> None:
        """When the DSN is set, SentryAlerter derives the store URL and posts."""
        monkeypatch.setenv("BRIER_SENTRY_DSN", "https://pub@o123.ingest.sentry.io/42")
        from brier_pipeline.models import Alert

        captured: list[tuple[str, dict[str, Any], dict[str, str]]] = []

        def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
            captured.append((url, payload, headers))
            return {}

        alerter = SentryAlerter(http_post=fake_post)
        alert = Alert(
            kind="cost_cap",
            severity="critical",
            summary="Monthly spend cap reached for llm; further metered calls are blocked.",
            dedup_key="cost_cap:llm:2026-06",
        )
        alerter.dispatch(alert)

        assert len(captured) == 1
        url, payload, headers = captured[0]
        assert url == "https://o123.ingest.sentry.io/api/42/store/"
        assert payload["level"] == "error"
        assert "sentry_key=pub" in headers.get("X-Sentry-Auth", "")


# ---------------------------------------------------------------------------
# 2. DB-backed tests: Alerter seam
# ---------------------------------------------------------------------------


class TestRecordAlertDB:
    """DB-backed tests for record_alert() deduplication."""

    def test_inserts_new_alert_returns_true(self, db_conn: Any) -> None:
        """record_alert inserts a new row and returns True."""
        result = record_alert(
            db_conn,
            kind="freshness",
            summary="Analyst data appears stale; no updates observed in over 48 hours.",
            severity="warning",
            subject="northchain",
            dedup_key="freshness:northchain:2026-06-16:test-insert",
        )
        assert result is True

    def test_dedup_key_conflict_returns_false(self, db_conn: Any) -> None:
        """Second record_alert with same dedup_key returns False (idempotent)."""
        dedup_key = "freshness:northchain:2026-06-16:test-dedup"
        record_alert(
            db_conn,
            kind="freshness",
            summary="Analyst data appears stale; no updates observed in over 48 hours.",
            dedup_key=dedup_key,
        )
        result2 = record_alert(
            db_conn,
            kind="freshness",
            summary="Different summary, same dedup key.",
            dedup_key=dedup_key,
        )
        assert result2 is False

    def test_no_duplicate_rows_on_dedup(self, db_conn: Any) -> None:
        """Duplicate dedup_key leaves only one row in the alerts table."""
        dedup_key = "freshness:aylin:2026-06-16:test-nodup"
        record_alert(
            db_conn,
            kind="freshness",
            summary="Analyst data appears stale.",
            dedup_key=dedup_key,
        )
        record_alert(
            db_conn,
            kind="freshness",
            summary="Another stale notice (should not insert).",
            dedup_key=dedup_key,
        )
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where dedup_key = %s",
                (dedup_key,),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1

    def test_detail_stored_as_jsonb(self, db_conn: Any) -> None:
        """record_alert stores the detail dict as JSONB."""
        dedup_key = "cost_threshold:llm:2026-06:test-detail"
        record_alert(
            db_conn,
            kind="cost_threshold",
            summary="Monthly spend for llm crossed the 70% alert threshold.",
            dedup_key=dedup_key,
            detail={"cap": 300.0, "threshold": 210.0, "mtd_after": 220.0},
        )
        with db_conn.cursor() as cur:
            cur.execute(
                "select detail from alerts where dedup_key = %s",
                (dedup_key,),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0]["cap"] == 300.0


class TestRaiseAlertDB:
    """DB-backed tests for raise_alert() dispatch behaviour."""

    def test_dispatches_once_for_new_alert(self, db_conn: Any) -> None:
        """raise_alert dispatches exactly once via FakeAlerter for a new alert."""
        alerter = FakeAlerter()
        dedup_key = "dispute_sla_at_risk:DSP-aabbccdd:test-dispatch"
        newly_raised = raise_alert(
            db_conn,
            alerter,
            kind="dispute_sla_at_risk",
            summary="A dispute ticket is approaching its SLA deadline.",
            severity="warning",
            subject="DSP-aabbccdd",
            dedup_key=dedup_key,
        )
        assert newly_raised is True
        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "dispute_sla_at_risk"
        assert alerter.dispatched[0].dedup_key == dedup_key

    def test_does_not_dispatch_on_deduped_second_call(self, db_conn: Any) -> None:
        """raise_alert does NOT dispatch on a deduped second call."""
        alerter = FakeAlerter()
        dedup_key = "dispute_sla_breach:DSP-11223344:test-nodedup-dispatch"
        raise_alert(
            db_conn,
            alerter,
            kind="dispute_sla_breach",
            summary="A dispute ticket has exceeded its SLA deadline without resolution.",
            severity="critical",
            dedup_key=dedup_key,
        )
        second = raise_alert(
            db_conn,
            alerter,
            kind="dispute_sla_breach",
            summary="Same alert, second call.",
            severity="critical",
            dedup_key=dedup_key,
        )
        assert second is False
        assert len(alerter.dispatched) == 1  # still only one dispatch

    def test_returns_true_for_new_false_for_dup(self, db_conn: Any) -> None:
        """raise_alert returns True for new, False for duplicate."""
        alerter = FakeAlerter()
        dedup_key = "erasure_overdue:req-999:test-retval"
        first = raise_alert(
            db_conn,
            alerter,
            kind="erasure_overdue",
            summary="An erasure request has exceeded the 30-day response deadline.",
            severity="critical",
            subject="req-999",
            dedup_key=dedup_key,
        )
        second = raise_alert(
            db_conn,
            alerter,
            kind="erasure_overdue",
            summary="Same request again.",
            severity="critical",
            subject="req-999",
            dedup_key=dedup_key,
        )
        assert first is True
        assert second is False

    def test_none_alerter_skips_dispatch_but_records(self, db_conn: Any) -> None:
        """raise_alert with alerter=None records the DB row but does not dispatch."""
        dedup_key = "freshness:vectoredge:2026-06-16:test-none-alerter"
        newly_raised = raise_alert(
            db_conn,
            None,
            kind="freshness",
            summary="Analyst data appears stale; no updates observed in over 48 hours.",
            dedup_key=dedup_key,
        )
        assert newly_raised is True
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where dedup_key = %s",
                (dedup_key,),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1


# ---------------------------------------------------------------------------
# 3. DB-backed tests: Spend meter
# ---------------------------------------------------------------------------


class TestRecordSpendDB:
    """DB-backed tests for record_spend and month_to_date_spend."""

    def test_record_spend_returns_id(self, db_conn: Any) -> None:
        """record_spend returns the new row id."""
        row_id = record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_month_to_date_spend_sums_correctly(self, db_conn: Any) -> None:
        """month_to_date_spend returns the sum of spend rows in the period."""
        record_spend(db_conn, category="llm", amount_usd=5.50, now=_NOW)
        record_spend(db_conn, category="llm", amount_usd=3.25, now=_NOW)
        total = month_to_date_spend(db_conn, "llm", now=_NOW)
        # db_conn is a single rolled-back transaction per test, so the sum is
        # exactly the two rows inserted above — no cross-test contamination.
        assert total == 8.75

    def test_spend_zero_when_no_rows(self, db_conn: Any) -> None:
        """month_to_date_spend returns 0.0 for a period with no rows."""
        # Use a future period that won't have any rows in the rolled-back txn.
        future = datetime(2099, 1, 1, tzinfo=UTC)
        total = month_to_date_spend(db_conn, "transcription", now=future)
        assert total == 0.0

    def test_spend_isolated_by_category(self, db_conn: Any) -> None:
        """month_to_date_spend only sums the given category."""
        future = datetime(2090, 3, 1, tzinfo=UTC)
        record_spend(db_conn, category="transcription", amount_usd=100.0, now=future)
        record_spend(db_conn, category="llm", amount_usd=50.0, now=future)
        transcription_total = month_to_date_spend(db_conn, "transcription", now=future)
        llm_total = month_to_date_spend(db_conn, "llm", now=future)
        assert transcription_total == 100.0
        assert llm_total == 50.0

    def test_spend_isolated_by_period(self, db_conn: Any) -> None:
        """month_to_date_spend only sums the current billing period."""
        jan = datetime(2091, 1, 15, tzinfo=UTC)
        feb = datetime(2091, 2, 15, tzinfo=UTC)
        record_spend(db_conn, category="llm", amount_usd=20.0, now=jan)
        total_feb = month_to_date_spend(db_conn, "llm", now=feb)
        assert total_feb == 0.0


class TestEvaluateSpendDB:
    """DB-backed tests for evaluate_spend (pure read, no side effects)."""

    def _set_llm_cap(self, monkeypatch: Any, cap: float) -> None:
        monkeypatch.setenv("BRIER_LLM_MONTHLY_CAP_USD", str(cap))

    def test_evaluate_no_crossings_under_threshold(self, db_conn: Any, monkeypatch: Any) -> None:
        """Under threshold: both flags are False."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2092, 1, 1, tzinfo=UTC)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=10.0, now=future)
        assert isinstance(decision, SpendDecision)
        assert decision.would_exceed_cap is False
        assert decision.crosses_alert_threshold is False

    def test_evaluate_crosses_alert_threshold(self, db_conn: Any, monkeypatch: Any) -> None:
        """When adding amount crosses the 70% line, crosses_alert_threshold=True."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2092, 2, 1, tzinfo=UTC)
        # Seed 65% spend so that adding 10 (to 75%) crosses the 70% threshold.
        record_spend(db_conn, category="llm", amount_usd=65.0, now=future)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=10.0, now=future)
        assert decision.mtd_before == 65.0
        assert decision.crosses_alert_threshold is True
        assert decision.would_exceed_cap is False

    def test_evaluate_would_exceed_cap(self, db_conn: Any, monkeypatch: Any) -> None:
        """When adding amount pushes past 100%, would_exceed_cap=True."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2092, 3, 1, tzinfo=UTC)
        record_spend(db_conn, category="llm", amount_usd=95.0, now=future)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=10.0, now=future)
        assert decision.would_exceed_cap is True

    def test_evaluate_exactly_at_threshold_not_crossing(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """When mtd_before is already at the threshold, adding more does not re-cross."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2092, 4, 1, tzinfo=UTC)
        # Seed exactly 70% — the threshold has already been crossed in a prior call.
        record_spend(db_conn, category="llm", amount_usd=70.0, now=future)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=5.0, now=future)
        # mtd_before (70) is NOT < threshold (70), so crosses_alert_threshold=False.
        assert decision.crosses_alert_threshold is False
        assert decision.would_exceed_cap is False


class TestGuardAndRecordSpendDB:
    """DB-backed tests for guard_and_record_spend — the enforcing gate."""

    def _set_llm_cap(self, monkeypatch: Any, cap: float) -> None:
        monkeypatch.setenv("BRIER_LLM_MONTHLY_CAP_USD", str(cap))

    def test_under_threshold_records_spend_no_alert(self, db_conn: Any, monkeypatch: Any) -> None:
        """Under threshold: spend row is recorded, no alert dispatched or stored."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2093, 1, 1, tzinfo=UTC)
        alerter = FakeAlerter()
        decision = guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=future, alerter=alerter
        )
        assert decision.would_exceed_cap is False
        assert decision.crosses_alert_threshold is False
        assert len(alerter.dispatched) == 0
        # Verify spend row was recorded.
        total = month_to_date_spend(db_conn, "llm", now=future)
        assert total == 10.0

    def test_crossing_70pct_records_spend_and_cost_threshold_alert(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """Crossing 70%: spend recorded + cost_threshold alert dispatched and in DB."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2093, 2, 1, tzinfo=UTC)
        # Seed 65% so that adding 10 crosses the 70% line.
        record_spend(db_conn, category="llm", amount_usd=65.0, now=future)
        alerter = FakeAlerter()
        decision = guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=future, alerter=alerter
        )
        assert decision.crosses_alert_threshold is True
        # Spend was recorded.
        total = month_to_date_spend(db_conn, "llm", now=future)
        assert total == 75.0
        # FakeAlerter got exactly one cost_threshold alert.
        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_threshold"
        # Alert row is in the DB — check via dedup_key.
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind = 'cost_threshold' and dedup_key = %s",
                ("cost_threshold:llm:2093-02",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1

    def test_exceeding_cap_raises_spend_cap_exceeded_no_spend_row(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """Exceeding cap: SpendCapExceeded raised, NO spend row recorded."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2093, 3, 1, tzinfo=UTC)
        # Seed 95% so that adding 10 exceeds the cap.
        record_spend(db_conn, category="llm", amount_usd=95.0, now=future)
        alerter = FakeAlerter()
        with pytest.raises(SpendCapExceeded):
            guard_and_record_spend(
                db_conn, category="llm", amount_usd=10.0, now=future, alerter=alerter
            )
        # Spend must NOT have been recorded (still at 95).
        total = month_to_date_spend(db_conn, "llm", now=future)
        assert total == 95.0

    def test_exceeding_cap_records_cost_cap_alert(self, db_conn: Any, monkeypatch: Any) -> None:
        """Exceeding cap: cost_cap (critical) alert is present in DB and dispatched."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2093, 4, 1, tzinfo=UTC)
        record_spend(db_conn, category="llm", amount_usd=95.0, now=future)
        alerter = FakeAlerter()
        with pytest.raises(SpendCapExceeded):
            guard_and_record_spend(
                db_conn, category="llm", amount_usd=10.0, now=future, alerter=alerter
            )
        # FakeAlerter dispatched one cost_cap alert.
        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_cap"
        assert alerter.dispatched[0].severity == "critical"
        # Alert row is in the DB.
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind = 'cost_cap' and dedup_key = %s",
                ("cost_cap:llm:2093-04",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1

    def test_cost_cap_alert_is_deduped_on_repeated_blocked_calls(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """Repeated blocked calls produce only one cost_cap alert row (idempotent)."""
        self._set_llm_cap(monkeypatch, 100.0)
        future = datetime(2093, 5, 1, tzinfo=UTC)
        record_spend(db_conn, category="llm", amount_usd=95.0, now=future)
        alerter = FakeAlerter()
        for _ in range(3):
            with pytest.raises(SpendCapExceeded):
                guard_and_record_spend(
                    db_conn, category="llm", amount_usd=10.0, now=future, alerter=alerter
                )
        # Only one DB alert row (dedup_key unique).
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where dedup_key = %s",
                ("cost_cap:llm:2093-05",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
        # FakeAlerter dispatched only once (raise_alert dedup).
        assert len(alerter.dispatched) == 1


# ---------------------------------------------------------------------------
# 4. Model imports sanity check
# ---------------------------------------------------------------------------


class TestModelImports:
    """Verify the E6 models from models.py are importable."""

    def test_alert_kinds_importable(self) -> None:
        from brier_pipeline.models import AlertKind

        assert AlertKind.COST_CAP == "cost_cap"
        assert AlertKind.DISPUTE_SLA_BREACH == "dispute_sla_breach"
        assert AlertKind.FRESHNESS == "freshness"

    def test_alert_severities_importable(self) -> None:
        from brier_pipeline.models import AlertSeverity

        assert AlertSeverity.CRITICAL == "critical"
        assert AlertSeverity.WARNING == "warning"
        assert AlertSeverity.INFO == "info"

    def test_spend_category_importable(self) -> None:
        from brier_pipeline.models import SpendCategory

        assert SpendCategory.TRANSCRIPTION == "transcription"
        assert SpendCategory.LLM == "llm"

    def test_erasure_state_importable(self) -> None:
        from brier_pipeline.models import ErasureState

        assert ErasureState.RECEIVED == "received"
        assert ErasureState.COMPLETED == "completed"

    def test_alert_model_instantiation(self) -> None:
        from brier_pipeline.models import Alert

        a = Alert(
            kind="freshness",
            summary="Analyst data appears stale.",
            dedup_key="freshness:test:2026-06-16",
        )
        assert a.severity == "warning"
        assert a.subject is None

    def test_spend_ledger_entry_instantiation(self) -> None:
        from brier_pipeline.models import SpendLedgerEntry

        e = SpendLedgerEntry(
            category="llm",
            period="2026-06",
            amount_usd=12.50,
        )
        assert e.amount_usd == 12.50

    def test_erasure_request_instantiation(self) -> None:
        from brier_pipeline.models import ErasureRequest

        r = ErasureRequest(
            subject_ref="user@example.com",
            scope="all predictions attributed to this channel",
            due_at=datetime(2026, 7, 16, tzinfo=UTC),
        )
        assert r.state == "received"
        assert r.balancing_outcome is None


class TestConfigAdditions:
    """Verify the new config functions from config.py."""

    def test_transcription_cap_default(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("BRIER_TRANSCRIPTION_MONTHLY_CAP_USD", raising=False)
        from brier_pipeline.config import transcription_monthly_cap_usd

        assert transcription_monthly_cap_usd() == 700.0

    def test_llm_cap_default(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("BRIER_LLM_MONTHLY_CAP_USD", raising=False)
        from brier_pipeline.config import llm_monthly_cap_usd

        assert llm_monthly_cap_usd() == 300.0

    def test_spend_alert_fraction_default(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("BRIER_SPEND_ALERT_FRACTION", raising=False)
        from brier_pipeline.config import spend_alert_fraction

        assert spend_alert_fraction() == 0.70

    def test_monthly_spend_cap_dispatch_transcription(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("BRIER_TRANSCRIPTION_MONTHLY_CAP_USD", "500.0")
        from brier_pipeline.config import monthly_spend_cap_usd

        assert monthly_spend_cap_usd("transcription") == 500.0

    def test_monthly_spend_cap_dispatch_llm(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("BRIER_LLM_MONTHLY_CAP_USD", "250.0")
        from brier_pipeline.config import monthly_spend_cap_usd

        assert monthly_spend_cap_usd("llm") == 250.0

    def test_monthly_spend_cap_unknown_category_raises(self) -> None:
        from brier_pipeline.config import monthly_spend_cap_usd

        with pytest.raises(ValueError, match="Unknown spend category"):
            monthly_spend_cap_usd("unknown")

    def test_better_stack_token_default_empty(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("BRIER_BETTER_STACK_TOKEN", raising=False)
        from brier_pipeline.config import better_stack_token

        assert better_stack_token() == ""

    def test_sentry_dsn_default_empty(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("BRIER_SENTRY_DSN", raising=False)
        from brier_pipeline.config import sentry_dsn

        assert sentry_dsn() == ""
