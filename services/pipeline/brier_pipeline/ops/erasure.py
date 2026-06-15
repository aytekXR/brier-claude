"""GDPR/KVKK erasure-request intake and 30-day policy workflow (PRD NFR-6).

This module implements the legitimate-interest balancing test described in
docs/LEGITIMATE_INTEREST.md and the operational workflow for erasure requests.

Key design decisions:
  - Published statistics about public statements by public figures are retained
    under legitimate interest (NFR-3 + NFR-6 reconciliation).
  - Personal data outside that scope is erasable.
  - Any erasure touching a published claim requires documented manual review —
    never a silent hard-delete of ledger rows.
  - resolutions and scores rows are NEVER deleted (NFR-3 ledger discipline).

Job handler 'erasure_sla_check' is registered at module load, mirroring the
pattern in brier_pipeline/disputes/sla.py and brier_pipeline/ingestion/poller.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from brier_pipeline.jobs import worker
from brier_pipeline.models import ErasureRequest
from brier_pipeline.ops.alerts import Alerter, get_alerter, raise_alert

# ---------------------------------------------------------------------------
# BalancingOutcome enum
# ---------------------------------------------------------------------------


class BalancingOutcome(StrEnum):
    """Outcome of the legitimate-interest balancing test (NFR-6)."""

    RETAIN_LEGITIMATE_INTEREST = "retain_legitimate_interest"
    ERASE = "erase"
    PARTIAL = "partial"


# ---------------------------------------------------------------------------
# BalancingDecision dataclass
# ---------------------------------------------------------------------------


@dataclass
class BalancingDecision:
    """Result of evaluate_balancing_test; a pure value with no side effects.

    Attributes:
        outcome:               The balancing outcome (BalancingOutcome enum value).
        rationale:             Neutral-register explanation of the decision (AC-7).
        requires_manual_review: True when human review is required before action.
    """

    outcome: BalancingOutcome
    rationale: str
    requires_manual_review: bool


# ---------------------------------------------------------------------------
# create_erasure_request
# ---------------------------------------------------------------------------


def create_erasure_request(
    subject_ref: str,
    scope: str,
    *,
    conn: Any,
    now: datetime,
) -> ErasureRequest:
    """INSERT an erasure_requests row and return the populated model.

    The due_at is set to now + 30 days (NFR-6 30-day response window).
    State is 'received'. Caller owns the transaction (no commit here).

    Args:
        subject_ref: Requester identifier (email, channel id, etc.).
        scope:       Description of what the requester asks to be erased.
        conn:        psycopg connection.
        now:         Reference datetime for received_at and due_at computation.

    Returns:
        ErasureRequest model populated with the new row id and timestamps.
    """
    due_at = now + timedelta(days=30)
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into erasure_requests (subject_ref, scope, state, received_at, due_at)
            values (%s, %s, 'received', %s, %s)
            returning id, received_at, due_at
            """,
            (subject_ref, scope, now, due_at),
        )
        row = cur.fetchone()
    assert row is not None
    row_id, db_received_at, db_due_at = row
    return ErasureRequest(
        id=int(row_id),
        subject_ref=subject_ref,
        scope=scope,
        state="received",
        balancing_outcome=None,
        received_at=db_received_at,
        due_at=db_due_at,
        decided_at=None,
        decision_note=None,
    )


# ---------------------------------------------------------------------------
# evaluate_balancing_test
# ---------------------------------------------------------------------------


def evaluate_balancing_test(
    scope: str,
    *,
    touches_published_claim: bool,
) -> BalancingDecision:
    """Encode the legitimate-interest balancing test.

    The test applies three criteria in order:

    1. If the erasure scope touches a published claim (a resolved public
       prediction by a public figure), the outcome is PARTIAL with mandatory
       manual review.  The published statistic is retained under legitimate
       interest; ancillary personal data that falls outside the scope of the
       published statement may be erasable.

    2. If the scope is clearly personal-data-only (not directly tied to a
       published statement), the outcome is ERASE.

    3. Default: the scope covers published-statistics data, which is retained
       under legitimate interest.

    All rationale strings are in neutral register (AC-7).

    Args:
        scope:                  Description of what the requester asks to erase.
        touches_published_claim: True when the request would affect a published
                                 resolution or score ledger row.

    Returns:
        BalancingDecision with outcome, rationale, and requires_manual_review.
    """
    if touches_published_claim:
        return BalancingDecision(
            outcome=BalancingOutcome.PARTIAL,
            rationale=(
                "The request covers data that includes a published statistic about a "
                "public statement by a public figure. The published record is retained "
                "under legitimate interest (accuracy of the public record, public "
                "accountability for public statements). Ancillary personal data outside "
                "the scope of the published statement is separately erasable. "
                "Manual review is required before any action is taken."
            ),
            requires_manual_review=True,
        )

    # Heuristic: scope strings that reference only contact or identity data
    # (not predictions, claims, or scores) are treated as personal-data-only.
    personal_data_keywords = (
        "email",
        "contact",
        "address",
        "identity",
        "personal",
        "name",
        "subscriber",
        "newsletter",
        "account",
    )
    scope_lower = scope.lower()
    is_personal_data_only = any(kw in scope_lower for kw in personal_data_keywords) and not any(
        kw in scope_lower
        for kw in ("claim", "prediction", "score", "resolution", "statement", "published")
    )

    if is_personal_data_only:
        return BalancingDecision(
            outcome=BalancingOutcome.ERASE,
            rationale=(
                "The request covers personal data that is not part of a published "
                "statistic or public statement record. No legitimate-interest basis "
                "for retention has been identified. The data is erasable."
            ),
            requires_manual_review=False,
        )

    # Default: published-statistics scope; retained under legitimate interest.
    return BalancingDecision(
        outcome=BalancingOutcome.RETAIN_LEGITIMATE_INTEREST,
        rationale=(
            "The request covers data within the scope of published statistics about "
            "public statements by public figures. Brier's legitimate interest in "
            "maintaining an accurate public record of verifiable predictions takes "
            "precedence. The data is retained. The requester may contact us to dispute "
            "the accuracy of a specific published statistic."
        ),
        requires_manual_review=False,
    )


# ---------------------------------------------------------------------------
# record_erasure_decision
# ---------------------------------------------------------------------------


def record_erasure_decision(
    request_id: int,
    *,
    outcome: BalancingOutcome,
    note: str,
    conn: Any,
    now: datetime,
    new_state: str | None = None,
) -> None:
    """UPDATE erasure_requests with the balancing decision.

    NEVER deletes resolutions, scores, or claims rows (NFR-3). This function
    only RECORDS the adjudicated decision; for an ERASE/PARTIAL outcome the
    actual purge of any ancillary personal data outside the published-statistics
    scope is a downstream, manually reviewed step (MVP posture, NFR-6) — it is
    deliberately not automated here so a published claim is never silently erased.

    State mapping when new_state is not provided:
      ERASE / PARTIAL -> 'completed'
      RETAIN_LEGITIMATE_INTEREST -> 'completed' (decision documented, no erasure)

    The caller may pass new_state='rejected' to explicitly record a rejection
    (e.g. fraudulent or out-of-scope request).

    Args:
        request_id: The erasure_requests row id.
        outcome:    BalancingOutcome value to record.
        note:       Decision note (neutral register, AC-7).
        conn:       psycopg connection (caller owns the transaction).
        now:        Reference datetime for decided_at.
        new_state:  Override state; if None, derived from outcome (-> 'completed').
    """
    if new_state is None:
        # All outcomes result in 'completed' — the decision has been documented.
        resolved_state = "completed"
    else:
        resolved_state = new_state

    with conn.cursor() as cur:
        cur.execute(
            """
            update erasure_requests
               set state             = %s,
                   balancing_outcome = %s,
                   decided_at        = %s,
                   decision_note     = %s
             where id = %s
            """,
            (resolved_state, str(outcome), now, note, request_id),
        )


# ---------------------------------------------------------------------------
# find_overdue_requests
# ---------------------------------------------------------------------------


def find_overdue_requests(conn: Any, now: datetime) -> list[ErasureRequest]:
    """Return erasure requests that are overdue and still unresolved.

    Conditions: state IN ('received', 'in_review') AND due_at < now.

    Args:
        conn: psycopg connection.
        now:  Reference datetime.

    Returns:
        List of ErasureRequest models, ordered by due_at ascending (oldest first).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select id, subject_ref, scope, state, balancing_outcome,
                   received_at, due_at, decided_at, decision_note
              from erasure_requests
             where state in ('received', 'in_review')
               and due_at < %s
             order by due_at asc
            """,
            (now,),
        )
        rows = cur.fetchall()

    results: list[ErasureRequest] = []
    for row in rows:
        (
            row_id,
            subject_ref,
            scope,
            state,
            balancing_outcome,
            received_at,
            due_at,
            decided_at,
            decision_note,
        ) = row
        results.append(
            ErasureRequest(
                id=int(row_id),
                subject_ref=str(subject_ref),
                scope=str(scope),
                state=str(state),
                balancing_outcome=balancing_outcome,
                received_at=received_at,
                due_at=due_at,
                decided_at=decided_at,
                decision_note=decision_note,
            )
        )
    return results


# ---------------------------------------------------------------------------
# run_erasure_sla_check
# ---------------------------------------------------------------------------


def run_erasure_sla_check(
    conn: Any,
    alerter: Alerter,
    now: datetime,
) -> dict[str, Any]:
    """Check for overdue erasure requests and raise alerts for each.

    For each overdue request (state in ('received', 'in_review'), due_at < now),
    raises an 'erasure_overdue' warning alert via raise_alert. Idempotent:
    dedup_key = 'erasure_overdue:<request_id>' prevents duplicate alerts.

    Args:
        conn:    psycopg connection.
        alerter: Alerter implementation (FakeAlerter in CI/tests).
        now:     Reference datetime.

    Returns:
        Dict with keys 'overdue' (count) and 'alerts_raised' (count).
    """
    overdue = find_overdue_requests(conn, now)
    alerts_raised = 0
    for req in overdue:
        assert req.id is not None
        # find_overdue_requests already filters due_at < now, so the request is
        # overdue by definition; report whole days, or "less than a day" rather
        # than a misleading "0 day(s)" for a request that is only hours past due.
        days_overdue = (now - req.due_at).days
        overdue_str = f"{days_overdue} day(s)" if days_overdue >= 1 else "less than a day"
        newly_raised = raise_alert(
            conn,
            alerter,
            kind="erasure_overdue",
            severity="warning",
            subject=str(req.id),
            dedup_key=f"erasure_overdue:{req.id}",
            summary=(
                f"Erasure request {req.id} has exceeded the 30-day response deadline "
                f"by {overdue_str}. Review is required."
            ),
            detail={
                "request_id": req.id,
                "subject_ref": req.subject_ref,
                "due_at": req.due_at.isoformat() if req.due_at else None,
                "days_overdue": days_overdue,
            },
        )
        if newly_raised:
            alerts_raised += 1

    return {
        "overdue": len(overdue),
        "alerts_raised": alerts_raised,
    }


# ---------------------------------------------------------------------------
# Job handler registration
# ---------------------------------------------------------------------------


def _erasure_sla_check_handler(payload: dict[str, Any], conn: Any) -> None:
    """Job handler for 'erasure_sla_check'; registered at module load.

    Builds the configured alerter (FakeAlerter in CI, BetterStackAlerter in
    production when BRIER_BETTER_STACK_TOKEN is set) and runs the SLA check.
    """
    alerter = get_alerter()
    now = datetime.now(tz=UTC)
    run_erasure_sla_check(conn, alerter, now)


# Register at module load so importing erasure wires the handler automatically.
worker.register_handler("erasure_sla_check", _erasure_sla_check_handler)
