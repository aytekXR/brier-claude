"""Dispute SLA tooling (PRD AC-5, §7 trust metrics, E6-T1).

SLA clock, breach detection, at-risk detection, weekly report, and
run_sla_check driver.  Two job kinds are registered at module load:
  'dispute_sla_check'    — calls run_sla_check (breach + at-risk alerts)
  'weekly_dispute_report' — builds WeeklyDisputeReport and logs it

This module is the CLOCK + ALERT + REPORT layer only.
Dispute adjudication is record_adjudication() in disputes/intake.py.

The 7-day SLA (AC-5) is a launch metric: 100% of disputes must be
adjudicated within 7 days.  pct_within_sla == 1.0 is the target.

All alert summaries use neutral, factual register (AC-7).
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from brier_pipeline.jobs import worker
from brier_pipeline.models import Dispute
from brier_pipeline.ops.alerts import Alerter, get_alerter, raise_alert
from brier_pipeline.ops.spend import billing_period

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SLA constants
# ---------------------------------------------------------------------------

_SLA_DAYS = 7
_ACTIVE_STATES = ("open", "adjudicating")
_ADJUDICATED_STATES = ("upheld", "corrected", "rejected")

# ---------------------------------------------------------------------------
# time_to_breach
# ---------------------------------------------------------------------------


def time_to_breach(dispute: Dispute, now: datetime) -> timedelta:
    """Return time remaining until the SLA deadline (may be negative when breached).

    Args:
        dispute: Dispute model with a populated sla_deadline.
        now:     Reference datetime (UTC-aware recommended).

    Returns:
        timedelta = sla_deadline - now.  Negative means already breached.
    """
    return dispute.sla_deadline - now


# ---------------------------------------------------------------------------
# find_breached_disputes
# ---------------------------------------------------------------------------


def find_breached_disputes(
    conn: Any,
    now: datetime,
) -> list[Dispute]:
    """Return disputes whose SLA deadline has passed and are still active.

    Conditions: sla_deadline < now AND state IN ('open', 'adjudicating').

    Args:
        conn: psycopg connection.
        now:  Reference datetime.

    Returns:
        List of Dispute models ordered by sla_deadline ascending (oldest first).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, ticket_code, claim_id, submitted_by, rationale,
                   state, sla_deadline, submitted_at, adjudicated_at,
                   adjudication_note, methodology_version_at_publication
              from disputes
             where sla_deadline < %s
               and state = any(%s)
             order by sla_deadline asc
            """,
            (now, list(_ACTIVE_STATES)),
        )
        rows = cur.fetchall()
    return [_row_to_dispute(r) for r in rows]


# ---------------------------------------------------------------------------
# find_at_risk_disputes
# ---------------------------------------------------------------------------


def find_at_risk_disputes(
    conn: Any,
    now: datetime,
    *,
    warn_within_hours: int = 24,
) -> list[Dispute]:
    """Return disputes whose SLA deadline is within the warning window and still active.

    Fires BEFORE the 7-day line.
    Conditions: now <= sla_deadline <= now + warn_within_hours AND state IN active.

    Args:
        conn:             psycopg connection.
        now:              Reference datetime.
        warn_within_hours: Hours before deadline to start warning (default 24).

    Returns:
        List of Dispute models ordered by sla_deadline ascending.
    """
    warn_until = now + timedelta(hours=warn_within_hours)
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, ticket_code, claim_id, submitted_by, rationale,
                   state, sla_deadline, submitted_at, adjudicated_at,
                   adjudication_note, methodology_version_at_publication
              from disputes
             where sla_deadline >= %s
               and sla_deadline <= %s
               and state = any(%s)
             order by sla_deadline asc
            """,
            (now, warn_until, list(_ACTIVE_STATES)),
        )
        rows = cur.fetchall()
    return [_row_to_dispute(r) for r in rows]


# ---------------------------------------------------------------------------
# DisputeReport dataclass
# ---------------------------------------------------------------------------


@dataclass
class DisputeReport:
    """Summary statistics over a dispute window (PRD AC-5, §7 trust metrics).

    AC-5 target: pct_within_sla == 1.0 (100% adjudicated within 7 days).
    breached_count is reported separately so an honest reader sees open breaches
    even when no disputes have been adjudicated yet (vacuously met pct).
    """

    window_days: int
    total: int
    adjudicated: int
    open_count: int
    breached_count: int
    pct_within_sla: float  # 0.0 .. 1.0; 1.0 when zero adjudicated (vacuously met)
    median_time_to_adjudication_hours: float | None  # None when zero adjudicated


# ---------------------------------------------------------------------------
# weekly_dispute_report
# ---------------------------------------------------------------------------


def weekly_dispute_report(
    conn: Any,
    *,
    now: datetime,
    window_days: int = 7,
) -> DisputeReport:
    """Build a DisputeReport over disputes submitted in the last window_days.

    Counts:
      - total: all disputes submitted_at >= now - window_days
      - adjudicated: state in ('upheld','corrected','rejected') with
        adjudicated_at not null
      - open_count: state in ('open','adjudicating')
      - breached_count: open/adjudicating AND sla_deadline < now
      - pct_within_sla: fraction of adjudicated where
        (adjudicated_at - submitted_at) <= 7 days; 1.0 when zero adjudicated
      - median_time_to_adjudication_hours: median of
        (adjudicated_at - submitted_at) in hours over adjudicated set;
        None when zero adjudicated

    Args:
        conn:        psycopg connection.
        now:         Reference datetime.
        window_days: Look-back window in days (default 7).

    Returns:
        DisputeReport dataclass.
    """
    window_start = now - timedelta(days=window_days)

    with conn.cursor() as cur:
        # Total submitted in window.
        cur.execute(
            """
            select count(*)
              from disputes
             where submitted_at >= %s
            """,
            (window_start,),
        )
        total_row = cur.fetchone()
        total = int(total_row[0]) if total_row else 0

        # Adjudicated rows (with adjudicated_at) in window.
        cur.execute(
            """
            select adjudicated_at, submitted_at
              from disputes
             where submitted_at >= %s
               and state = any(%s)
               and adjudicated_at is not null
            """,
            (window_start, list(_ADJUDICATED_STATES)),
        )
        adjudicated_rows = cur.fetchall()

        # Open count.
        cur.execute(
            """
            select count(*)
              from disputes
             where submitted_at >= %s
               and state = any(%s)
            """,
            (window_start, list(_ACTIVE_STATES)),
        )
        open_row = cur.fetchone()
        open_count = int(open_row[0]) if open_row else 0

        # Breached count (open/adjudicating, past deadline).
        cur.execute(
            """
            select count(*)
              from disputes
             where submitted_at >= %s
               and state = any(%s)
               and sla_deadline < %s
            """,
            (window_start, list(_ACTIVE_STATES), now),
        )
        breached_row = cur.fetchone()
        breached_count = int(breached_row[0]) if breached_row else 0

    adjudicated_count = len(adjudicated_rows)

    # pct_within_sla: vacuously 1.0 when no adjudicated disputes.
    if adjudicated_count == 0:
        pct_within_sla = 1.0
        median_hours: float | None = None
    else:
        sla_limit = timedelta(days=_SLA_DAYS)
        within_sla_count = 0
        durations_hours: list[float] = []
        for adj_at, sub_at in adjudicated_rows:
            # Ensure both datetimes are comparable (both UTC-aware or both naive).
            duration = adj_at - sub_at
            durations_hours.append(duration.total_seconds() / 3600.0)
            if duration <= sla_limit:
                within_sla_count += 1
        pct_within_sla = within_sla_count / adjudicated_count
        median_hours = statistics.median(durations_hours)

    return DisputeReport(
        window_days=window_days,
        total=total,
        adjudicated=adjudicated_count,
        open_count=open_count,
        breached_count=breached_count,
        pct_within_sla=pct_within_sla,
        median_time_to_adjudication_hours=median_hours,
    )


# ---------------------------------------------------------------------------
# run_sla_check
# ---------------------------------------------------------------------------


def run_sla_check(
    conn: Any,
    alerter: Alerter | None,
    now: datetime,
) -> dict[str, int]:
    """Alert on breached and at-risk disputes; return counts.

    For each breached dispute: raise_alert kind='dispute_sla_breach',
    severity='critical', dedup_key='dispute_sla_breach:{ticket_code}'.

    For each at-risk dispute: raise_alert kind='dispute_sla_at_risk',
    severity='warning',
    dedup_key='dispute_sla_at_risk:{ticket_code}:{billing_period(now)}'.

    Idempotent: re-running with the same now raises no additional alerts
    (dedup_key uniqueness via ON CONFLICT DO NOTHING in record_alert).

    Args:
        conn:    psycopg connection (caller owns transaction).
        alerter: Alerter seam; None falls through to DB-only dedup.
        now:     Reference datetime.

    Returns:
        Dict {'breached': int, 'at_risk': int, 'alerts_raised': int}.
    """
    breached = find_breached_disputes(conn, now)
    at_risk = find_at_risk_disputes(conn, now)

    alerts_raised = 0
    period = billing_period(now)

    for dispute in breached:
        summary = (
            f"Dispute {dispute.ticket_code} passed its 7-day review target "
            f"and is still {dispute.state}."
        )
        newly = raise_alert(
            conn,
            alerter,
            kind="dispute_sla_breach",
            severity="critical",
            subject=dispute.ticket_code,
            dedup_key=f"dispute_sla_breach:{dispute.ticket_code}",
            summary=summary,
        )
        if newly:
            alerts_raised += 1

    for dispute in at_risk:
        summary = (
            f"Dispute {dispute.ticket_code} is approaching its 7-day review target "
            f"and is still {dispute.state}."
        )
        newly = raise_alert(
            conn,
            alerter,
            kind="dispute_sla_at_risk",
            severity="warning",
            subject=dispute.ticket_code,
            dedup_key=f"dispute_sla_at_risk:{dispute.ticket_code}:{period}",
            summary=summary,
        )
        if newly:
            alerts_raised += 1

    return {
        "breached": len(breached),
        "at_risk": len(at_risk),
        "alerts_raised": alerts_raised,
    }


# ---------------------------------------------------------------------------
# Job handlers
# ---------------------------------------------------------------------------


def _dispute_sla_check_handler(
    payload: dict[str, Any],
    conn: Any,
) -> None:
    """Job handler for 'dispute_sla_check'.

    Builds the configured alerter (FakeAlerter in CI, BetterStackAlerter in
    production) and calls run_sla_check with UTC now.
    """
    alerter = get_alerter()
    now = datetime.now(UTC)
    result = run_sla_check(conn, alerter, now)
    logger.info(
        "dispute_sla_check: breached=%d at_risk=%d alerts_raised=%d",
        result["breached"],
        result["at_risk"],
        result["alerts_raised"],
    )


def _weekly_dispute_report_handler(
    payload: dict[str, Any],
    conn: Any,
) -> None:
    """Job handler for 'weekly_dispute_report'.

    Builds a DisputeReport over the trailing 7 days and logs the summary.
    External delivery (email / webhook) is out of scope for E6-T1.
    """
    now = datetime.now(UTC)
    window_days = int(payload.get("window_days", 7))
    report = weekly_dispute_report(conn, now=now, window_days=window_days)
    logger.info(
        "weekly_dispute_report: window=%dd total=%d adjudicated=%d open=%d "
        "breached=%d pct_within_sla=%.3f median_hours=%s",
        report.window_days,
        report.total,
        report.adjudicated,
        report.open_count,
        report.breached_count,
        report.pct_within_sla,
        (
            f"{report.median_time_to_adjudication_hours:.1f}"
            if report.median_time_to_adjudication_hours is not None
            else "None"
        ),
    )


# Register at module load so importing sla wires both handlers automatically.
# The worker's run_forever() docstring documents: import the module before
# calling run_forever() to activate its handlers.
worker.register_handler("dispute_sla_check", _dispute_sla_check_handler)
worker.register_handler("weekly_dispute_report", _weekly_dispute_report_handler)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dispute(row: tuple[Any, ...]) -> Dispute:
    """Map a DB row from the disputes SELECT to a Dispute model."""
    (
        dispute_id,
        ticket_code,
        claim_id,
        submitted_by,
        rationale,
        state,
        sla_deadline,
        submitted_at,
        adjudicated_at,
        adjudication_note,
        methodology_version_at_publication,
    ) = row
    return Dispute(
        id=int(dispute_id),
        ticket_code=str(ticket_code),
        claim_id=int(claim_id),
        submitted_by=str(submitted_by) if submitted_by is not None else None,
        rationale=str(rationale),
        state=state,
        sla_deadline=sla_deadline,
        submitted_at=submitted_at,
        adjudicated_at=adjudicated_at,
        adjudication_note=str(adjudication_note) if adjudication_note is not None else None,
        methodology_version_at_publication=(
            str(methodology_version_at_publication)
            if methodology_version_at_publication is not None
            else None
        ),
    )


__all__ = [
    "time_to_breach",
    "find_breached_disputes",
    "find_at_risk_disputes",
    "DisputeReport",
    "weekly_dispute_report",
    "run_sla_check",
]
