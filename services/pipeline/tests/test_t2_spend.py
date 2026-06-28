"""T2-spend: failure-path & edge regression tests for the spend-cap exact boundaries.

Cluster: spend  (DB id prefix: spend-t2)

Covers the exact percentage boundaries at 99%, 100%, and 101% of the monthly
spend cap, and the 70% alert-threshold crossing semantics per ops/spend.py:

    would_exceed_cap     = mtd_after > cap          (strict greater-than)
    crosses_alert_threshold = mtd_before < alert_threshold <= mtd_after

Established behavioral contract verified here:
  - 99%:  charge is ALLOWED and recorded.
  - 100%: charge is ALLOWED (cap guard is strict >; equality is NOT a breach).
  - 101%: charge is BLOCKED and NOT recorded; cost_cap (critical) alert fires.
  - 70% alert: fires exactly once on a strict upward crossing from <70% to >=70%;
    re-fires do NOT occur when mtd_before is already at or above the threshold.

All DB tests use far-future billing periods in the 2150s to avoid any collision
with production data or concurrently running test files.  The db_conn fixture
rolls back all writes, so cross-test isolation is already guaranteed.

Categories must be 'llm' or 'transcription' (config.monthly_spend_cap_usd
raises ValueError for unknown categories); period-based namespacing (one unique
month per test class) substitutes for a category-level spend-t2 prefix.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from brier_pipeline.ops.alerts import FakeAlerter
from brier_pipeline.ops.spend import (
    SpendCapExceeded,
    evaluate_spend,
    guard_and_record_spend,
    month_to_date_spend,
    record_spend,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# One unique far-future billing month per test class so no class-level
# cross-contamination can occur even outside a single rolled-back connection.
_NOW_99 = datetime(2150, 1, 15, tzinfo=UTC)  # 99% boundary
_NOW_100 = datetime(2150, 2, 15, tzinfo=UTC)  # exact 100% boundary
_NOW_101 = datetime(2150, 3, 15, tzinfo=UTC)  # >100% (blocked)
_NOW_70A = datetime(2150, 4, 15, tzinfo=UTC)  # 70% upward crossing
_NOW_70B = datetime(2150, 5, 15, tzinfo=UTC)  # no re-fire above threshold
_NOW_70C = datetime(2150, 6, 15, tzinfo=UTC)  # exact boundary 69->70
_NOW_70D = datetime(2150, 7, 15, tzinfo=UTC)  # already at threshold
_NOW_70E = datetime(2150, 8, 15, tzinfo=UTC)  # sequential two-call proof

_LLM_CAP_ENV = "BRIER_LLM_MONTHLY_CAP_USD"
_CAP = 100.0  # simple arithmetic


def _set_cap(monkeypatch: Any, cap: float = _CAP) -> None:
    """Inject a deterministic cap via env override (config reads at call time)."""
    monkeypatch.setenv(_LLM_CAP_ENV, str(cap))


# ---------------------------------------------------------------------------
# 1. 99% of cap: charge landing at 99% is ALLOWED and recorded.
# ---------------------------------------------------------------------------


class TestSpend99PctBoundary:
    """A charge whose running total lands at 99% of cap is allowed, recorded, silent.

    Pre-seed at 89% so the 70% alert was already crossed in a prior call;
    the 10% test charge brings total to 99% without triggering any alert.
    """

    def test_charge_at_99pct_not_blocked(self, db_conn: Any, monkeypatch: Any) -> None:
        """guard_and_record_spend must not raise when total lands at 99% of cap."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=89.0, now=_NOW_99)
        decision = guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_99)
        assert decision.would_exceed_cap is False

    def test_charge_at_99pct_is_recorded(self, db_conn: Any, monkeypatch: Any) -> None:
        """Spend row is written; running total equals 99 after the call."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=89.0, now=_NOW_99)
        guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_99)
        total = month_to_date_spend(db_conn, "llm", now=_NOW_99)
        assert total == pytest.approx(99.0)

    def test_charge_at_99pct_no_cap_alert(self, db_conn: Any, monkeypatch: Any) -> None:
        """No cost_cap alert fires: cap has not been breached at 99%."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=89.0, now=_NOW_99)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=_NOW_99, alerter=alerter
        )
        cap_alerts = [a for a in alerter.dispatched if a.kind == "cost_cap"]
        assert len(cap_alerts) == 0

    def test_99pct_decision_fields_correct(self, db_conn: Any, monkeypatch: Any) -> None:
        """SpendDecision.mtd_before, cap, and would_exceed_cap are correct at 99%."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=89.0, now=_NOW_99)
        decision = guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_99)
        assert decision.mtd_before == pytest.approx(89.0)
        assert decision.cap == pytest.approx(_CAP)
        assert decision.would_exceed_cap is False


# ---------------------------------------------------------------------------
# 2. Exact 100% of cap: ALLOWED (block condition is strict >, not >=).
# ---------------------------------------------------------------------------


class TestSpendExact100PctBoundary:
    """A charge whose running total equals the cap exactly is ALLOWED.

    The enforcing predicate is: would_exceed_cap = mtd_after > cap
    Because the comparison is strict greater-than, a charge that brings the
    running total to exactly the cap (mtd_after == cap) is not blocked.
    This is the documented 'block at >100%' boundary.
    """

    def test_charge_at_exact_100pct_is_allowed(self, db_conn: Any, monkeypatch: Any) -> None:
        """guard_and_record_spend must NOT raise when total == cap (strict > boundary)."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_100)
        # 90 + 10 = 100 == cap; 100 > 100 is False -> not blocked.
        decision = guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_100)
        assert decision.would_exceed_cap is False

    def test_charge_at_exact_100pct_is_recorded(self, db_conn: Any, monkeypatch: Any) -> None:
        """Spend row at exactly the cap is written; total == cap."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_100)
        guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_100)
        total = month_to_date_spend(db_conn, "llm", now=_NOW_100)
        assert total == pytest.approx(_CAP)

    def test_charge_at_exact_100pct_no_exception(self, db_conn: Any, monkeypatch: Any) -> None:
        """SpendCapExceeded is NOT raised when the proposed total equals the cap."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_100)
        try:
            guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_100)
        except SpendCapExceeded:
            pytest.fail(
                "SpendCapExceeded raised at exactly 100% of cap; "
                "the boundary is strict > so equality must be allowed."
            )

    def test_charge_at_exact_100pct_no_cap_alert(self, db_conn: Any, monkeypatch: Any) -> None:
        """No cost_cap alert fires when total == cap (alert fires only when total > cap)."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_100)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=_NOW_100, alerter=alerter
        )
        cap_alerts = [a for a in alerter.dispatched if a.kind == "cost_cap"]
        assert len(cap_alerts) == 0

    def test_evaluate_exact_100pct_not_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        """evaluate_spend (pure read) also returns would_exceed_cap=False when total==cap."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_100)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_100)
        # mtd_after == 100.0 == cap; strict > means not exceeded.
        assert decision.would_exceed_cap is False


# ---------------------------------------------------------------------------
# 3. >100% of cap: charge blocked, NOT recorded; cost_cap (critical) alert fires.
# ---------------------------------------------------------------------------


class TestSpend101PctBoundary:
    """A charge whose running total exceeds the cap is BLOCKED and not recorded."""

    def test_charge_over_cap_raises(self, db_conn: Any, monkeypatch: Any) -> None:
        """guard_and_record_spend raises SpendCapExceeded when mtd_after > cap."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_101)
        with pytest.raises(SpendCapExceeded):
            guard_and_record_spend(db_conn, category="llm", amount_usd=11.0, now=_NOW_101)

    def test_blocked_charge_is_not_recorded(self, db_conn: Any, monkeypatch: Any) -> None:
        """No spend row is inserted when the cap would be exceeded; total stays at pre-seed."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_101)
        with pytest.raises(SpendCapExceeded):
            guard_and_record_spend(db_conn, category="llm", amount_usd=11.0, now=_NOW_101)
        total = month_to_date_spend(db_conn, "llm", now=_NOW_101)
        # Spend must NOT have increased beyond the 90 pre-seed.
        assert total == pytest.approx(90.0)

    def test_blocked_charge_dispatches_cost_cap_alert(self, db_conn: Any, monkeypatch: Any) -> None:
        """A blocked call dispatches exactly one cost_cap (critical) alert."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_101)
        alerter = FakeAlerter()
        with pytest.raises(SpendCapExceeded):
            guard_and_record_spend(
                db_conn, category="llm", amount_usd=11.0, now=_NOW_101, alerter=alerter
            )
        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_cap"
        assert alerter.dispatched[0].severity == "critical"

    def test_evaluate_over_cap_returns_would_exceed_true(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """evaluate_spend (pure read) reports would_exceed_cap=True when mtd_after > cap."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=90.0, now=_NOW_101)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=11.0, now=_NOW_101)
        assert decision.would_exceed_cap is True

    def test_one_cent_over_cap_is_blocked(self, db_conn: Any, monkeypatch: Any) -> None:
        """Even $0.01 over the cap is blocked: the boundary is strict >."""
        _set_cap(monkeypatch)
        # Pre-seed exactly at the cap so the next penny pushes it over.
        record_spend(db_conn, category="llm", amount_usd=_CAP, now=_NOW_101)
        with pytest.raises(SpendCapExceeded):
            guard_and_record_spend(db_conn, category="llm", amount_usd=0.01, now=_NOW_101)


# ---------------------------------------------------------------------------
# 4. 70% alert: upward crossing fires once; already-above does not re-fire.
# ---------------------------------------------------------------------------


class TestSpend70PctAlertUpwardCrossing:
    """Alert fires exactly once when spend crosses from strictly below 70% to >=70%."""

    def test_alert_fires_on_crossing_from_below(self, db_conn: Any, monkeypatch: Any) -> None:
        """cost_threshold is dispatched once when spend crosses from <70% to >70%."""
        _set_cap(monkeypatch)
        # 65 < 70 (threshold); 65+10=75 >= 70 -> crosses.
        record_spend(db_conn, category="llm", amount_usd=65.0, now=_NOW_70A)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=_NOW_70A, alerter=alerter
        )
        threshold_alerts = [a for a in alerter.dispatched if a.kind == "cost_threshold"]
        assert len(threshold_alerts) == 1

    def test_alert_severity_is_warning(self, db_conn: Any, monkeypatch: Any) -> None:
        """cost_threshold alert must carry severity='warning'."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=65.0, now=_NOW_70A)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=_NOW_70A, alerter=alerter
        )
        alert = next(a for a in alerter.dispatched if a.kind == "cost_threshold")
        assert alert.severity == "warning"

    def test_spend_still_recorded_when_alert_fires(self, db_conn: Any, monkeypatch: Any) -> None:
        """Crossing 70% allows the spend: the row IS recorded (not blocked)."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=65.0, now=_NOW_70A)
        guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_70A)
        total = month_to_date_spend(db_conn, "llm", now=_NOW_70A)
        assert total == pytest.approx(75.0)


class TestSpend70PctAlertNoRefire:
    """Alert does NOT fire when mtd_before is already at or above the 70% threshold."""

    def test_alert_does_not_refire_when_already_above(self, db_conn: Any, monkeypatch: Any) -> None:
        """No cost_threshold alert when starting spend is already above the threshold."""
        _set_cap(monkeypatch)
        # Pre-seed at 75% (above 70%).
        record_spend(db_conn, category="llm", amount_usd=75.0, now=_NOW_70B)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=5.0, now=_NOW_70B, alerter=alerter
        )
        threshold_alerts = [a for a in alerter.dispatched if a.kind == "cost_threshold"]
        assert len(threshold_alerts) == 0

    def test_evaluate_no_crossing_when_already_above(self, db_conn: Any, monkeypatch: Any) -> None:
        """evaluate_spend.crosses_alert_threshold=False when mtd_before > threshold."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=80.0, now=_NOW_70B)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=5.0, now=_NOW_70B)
        # mtd_before=80 >= threshold=70; 80 < 70 is False -> no crossing.
        assert decision.crosses_alert_threshold is False


class TestSpend70PctAlertExactBoundary:
    """Alert fires when crossing from strictly below the threshold to exactly the threshold."""

    def test_alert_fires_crossing_to_exactly_70pct(self, db_conn: Any, monkeypatch: Any) -> None:
        """Crossing from 69 to exactly 70 satisfies: mtd_before < threshold <= mtd_after."""
        _set_cap(monkeypatch)
        # 69 < 70 (threshold) <= 70 (mtd_after=69+1) -> fires.
        record_spend(db_conn, category="llm", amount_usd=69.0, now=_NOW_70C)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=1.0, now=_NOW_70C, alerter=alerter
        )
        threshold_alerts = [a for a in alerter.dispatched if a.kind == "cost_threshold"]
        assert len(threshold_alerts) == 1

    def test_evaluate_crossing_to_exactly_70pct(self, db_conn: Any, monkeypatch: Any) -> None:
        """evaluate_spend.crosses_alert_threshold=True when mtd_before<threshold==mtd_after."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=69.0, now=_NOW_70C)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=1.0, now=_NOW_70C)
        # mtd_before=69 < threshold=70 <= mtd_after=70 -> True.
        assert decision.crosses_alert_threshold is True


class TestSpend70PctAlertAlreadyAtThreshold:
    """Alert does NOT fire when mtd_before is exactly equal to the threshold."""

    def test_no_alert_when_pre_seeded_at_threshold(self, db_conn: Any, monkeypatch: Any) -> None:
        """No cost_threshold alert when starting spend == threshold (not strictly below)."""
        _set_cap(monkeypatch)
        # Pre-seed exactly at 70 (the threshold).  Next call starts AT threshold, not below.
        record_spend(db_conn, category="llm", amount_usd=70.0, now=_NOW_70D)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=5.0, now=_NOW_70D, alerter=alerter
        )
        threshold_alerts = [a for a in alerter.dispatched if a.kind == "cost_threshold"]
        assert len(threshold_alerts) == 0

    def test_evaluate_no_crossing_at_exact_threshold(self, db_conn: Any, monkeypatch: Any) -> None:
        """evaluate_spend.crosses_alert_threshold=False when mtd_before==threshold."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=70.0, now=_NOW_70D)
        decision = evaluate_spend(db_conn, category="llm", amount_usd=5.0, now=_NOW_70D)
        # mtd_before=70, threshold=70: 70 < 70 is False -> crosses_alert_threshold=False.
        assert decision.crosses_alert_threshold is False


class TestSpend70PctAlertSequentialCalls:
    """Sequential calls: 70% alert fires only on the first crossing, not again."""

    def test_alert_fires_only_once_across_two_allowed_calls(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """Two calls: first crosses 70% (alert fires), second is above (no re-fire)."""
        _set_cap(monkeypatch)
        # Call 1: 65 -> 75 (crosses 70%) -> alert fires via FakeAlerter.
        record_spend(db_conn, category="llm", amount_usd=65.0, now=_NOW_70E)
        alerter = FakeAlerter()
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=_NOW_70E, alerter=alerter
        )
        # Call 2: 75 -> 85 (already above 70%) -> crosses_alert_threshold=False, no re-fire.
        guard_and_record_spend(
            db_conn, category="llm", amount_usd=10.0, now=_NOW_70E, alerter=alerter
        )
        threshold_alerts = [a for a in alerter.dispatched if a.kind == "cost_threshold"]
        assert len(threshold_alerts) == 1

    def test_total_accumulates_correctly_across_two_calls(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        """Both allowed calls are recorded; total is the sum of all three amounts."""
        _set_cap(monkeypatch)
        record_spend(db_conn, category="llm", amount_usd=65.0, now=_NOW_70E)
        guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_70E)
        guard_and_record_spend(db_conn, category="llm", amount_usd=10.0, now=_NOW_70E)
        total = month_to_date_spend(db_conn, "llm", now=_NOW_70E)
        assert total == pytest.approx(85.0)
