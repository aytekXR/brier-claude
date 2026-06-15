"""Spend-meter engine for NFR-5 hard caps and 70% alert threshold.

guard_and_record_spend is the enforcing gate: it blocks metered API calls that
would exceed the monthly cap, and raises a cost_threshold alert when spending
crosses the 70% alert fraction for the first time in the billing period.

The spend_ledger table (0008_ops_trust.sql) is the durable record. Alerts are
emitted through the Alerter seam (ops/alerts.py, ADR-0014), keeping the CI
path alert-free by injecting FakeAlerter or None.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from brier_pipeline import config
from brier_pipeline.ops.alerts import Alerter, raise_alert


class SpendCapExceeded(RuntimeError):
    """Raised when a spend call would exceed the monthly cap (NFR-5)."""


def billing_period(now: datetime) -> str:
    """Return the UTC billing month as 'YYYY-MM'.

    Args:
        now: Reference datetime (should be UTC-aware or naive-UTC).

    Returns:
        String like '2026-06'.
    """
    utc_now = now.astimezone(UTC) if now.tzinfo is not None else now
    return utc_now.strftime("%Y-%m")


def month_to_date_spend(conn: Any, category: str, *, now: datetime) -> float:
    """SUM of spend_ledger.amount_usd for category within the current billing period.

    Args:
        conn:     psycopg connection.
        category: Spend category string ('transcription' or 'llm').
        now:      Reference datetime for the billing period.

    Returns:
        Total USD spent so far this period; 0.0 if no rows.
    """
    period = billing_period(now)
    with conn.cursor() as cur:
        cur.execute(
            """
            select coalesce(sum(amount_usd), 0.0)
              from spend_ledger
             where category = %s
               and period = %s
            """,
            (category, period),
        )
        row = cur.fetchone()
    return float(row[0]) if row else 0.0


def record_spend(
    conn: Any,
    *,
    category: str,
    amount_usd: float,
    now: datetime,
    note: str | None = None,
) -> int:
    """INSERT a spend_ledger row and return the new row id.

    Caller owns the transaction (no commit here).

    Args:
        conn:       psycopg connection.
        category:   Spend category ('transcription' or 'llm').
        amount_usd: Amount in USD (must be >= 0).
        now:        Reference datetime for billing_period computation.
        note:       Optional free-text note.

    Returns:
        The new spend_ledger row id.
    """
    period = billing_period(now)
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into spend_ledger (category, period, amount_usd, note)
            values (%s, %s, %s, %s)
            returning id
            """,
            (category, period, amount_usd, note),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


@dataclass
class SpendDecision:
    """Result of evaluate_spend; a pure read with no side effects."""

    category: str
    amount_usd: float
    mtd_before: float
    cap: float
    alert_threshold: float
    would_exceed_cap: bool
    crosses_alert_threshold: bool


def evaluate_spend(
    conn: Any,
    *,
    category: str,
    amount_usd: float,
    now: datetime,
) -> SpendDecision:
    """Pure read: evaluate whether adding amount_usd would breach limits.

    No writes; returns a SpendDecision describing the current situation.
    The cap and alert_threshold are read from config at call time so
    environment-variable overrides take effect without a module reload.

    Args:
        conn:       psycopg connection.
        category:   Spend category ('transcription' or 'llm').
        amount_usd: Proposed spend amount in USD.
        now:        Reference datetime.

    Returns:
        SpendDecision dataclass with flags for cap and threshold crossings.
    """
    mtd_before = month_to_date_spend(conn, category, now=now)
    cap = config.monthly_spend_cap_usd(category)
    alert_threshold = cap * config.spend_alert_fraction()
    mtd_after = mtd_before + amount_usd

    would_exceed_cap = mtd_after > cap
    # crosses_alert_threshold: True only when the threshold is crossed in this
    # specific call (i.e. was below threshold before, will be at/above after).
    crosses_alert_threshold = mtd_before < alert_threshold <= mtd_after

    return SpendDecision(
        category=category,
        amount_usd=amount_usd,
        mtd_before=mtd_before,
        cap=cap,
        alert_threshold=alert_threshold,
        would_exceed_cap=would_exceed_cap,
        crosses_alert_threshold=crosses_alert_threshold,
    )


def guard_and_record_spend(
    conn: Any,
    *,
    category: str,
    amount_usd: float,
    now: datetime,
    alerter: Alerter | None = None,
) -> SpendDecision:
    """Enforcing gate: evaluate, optionally block, record, and alert.

    If the call would exceed the monthly cap:
      - Raises a cost_cap alert (critical severity) via raise_alert.
      - Raises SpendCapExceeded WITHOUT recording the spend row.

    Otherwise:
      - Records the spend in spend_ledger.
      - If the 70% threshold is crossed for the first time, raises a
        cost_threshold alert (warning severity) via raise_alert.

    Alert summaries use neutral register (AC-7).

    Args:
        conn:       psycopg connection (caller owns the transaction).
        category:   Spend category ('transcription' or 'llm').
        amount_usd: Spend amount in USD.
        now:        Reference datetime.
        alerter:    Optional Alerter; if None, only the DB alert row is written.

    Returns:
        SpendDecision from evaluate_spend.

    Raises:
        SpendCapExceeded: When the call would exceed the monthly cap.
    """
    period = billing_period(now)
    decision = evaluate_spend(conn, category=category, amount_usd=amount_usd, now=now)

    if decision.would_exceed_cap:
        raise_alert(
            conn,
            alerter,
            kind="cost_cap",
            severity="critical",
            subject=category,
            dedup_key=f"cost_cap:{category}:{period}",
            summary=(
                f"Monthly spend cap reached for {category}; further metered calls are blocked."
            ),
            detail={
                "mtd_before": decision.mtd_before,
                "amount_usd": decision.amount_usd,
                "cap": decision.cap,
                "period": period,
            },
        )
        raise SpendCapExceeded(
            f"Monthly spend cap of ${decision.cap:.2f} for {category!r} "
            f"exceeded (MTD: ${decision.mtd_before:.2f}, "
            f"requested: ${decision.amount_usd:.2f})."
        )

    record_spend(conn, category=category, amount_usd=amount_usd, now=now)

    if decision.crosses_alert_threshold:
        mtd_after = decision.mtd_before + decision.amount_usd
        raise_alert(
            conn,
            alerter,
            kind="cost_threshold",
            severity="warning",
            subject=category,
            dedup_key=f"cost_threshold:{category}:{period}",
            summary=(f"Monthly spend for {category} crossed the 70% alert threshold."),
            detail={
                "mtd_after": mtd_after,
                "cap": decision.cap,
                "threshold": decision.alert_threshold,
                "period": period,
            },
        )

    return decision
