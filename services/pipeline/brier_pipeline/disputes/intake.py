"""Dispute intake and adjudication (FR-405, US-006, AC-5, UF-3, EC-12, NFR-2, NFR-3).

create_dispute():      Insert a new dispute ticket; notify submitter of ticket code.
record_adjudication(): Record upheld/corrected adjudication; corrective path
                       appends a superseding resolution (NFR-3 append-only) then
                       writes a row to the public corrections log.

DB pattern: psycopg + plain SQL, matching the resolver and QA queue modules.
The conn parameter accepts the rolled-back db_conn fixture in tests.

Column names follow 0006_ops.sql exactly:
  disputes   : ticket_code, submitted_by, state, sla_deadline,
               submitted_at, methodology_version_at_publication,
               reviewer_id (added by 0007), resolution_id (added by 0007)
  corrections: claim_id, dispute_id, summary,
               superseded_resolution_id, superseding_resolution_id, published_at
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psycopg

from brier_pipeline.config import METHODOLOGY_VERSION, database_url
from brier_pipeline.disputes.notify import FakeNotifier, Notifier
from brier_pipeline.models import Correction, Dispute
from brier_pipeline.resolution.resolver import _insert_resolution

# ---------------------------------------------------------------------------
# Ticket code generation
# ---------------------------------------------------------------------------

_TICKET_PREFIX = "DSP-"
_TICKET_HEX_BYTES = 4  # 4 bytes = 8 hex chars  ->  DSP-<8hex>


def _generate_ticket_code() -> str:
    """Generate a public dispute ticket code: DSP-<8 lowercase hex chars>."""
    return _TICKET_PREFIX + secrets.token_hex(_TICKET_HEX_BYTES)


# ---------------------------------------------------------------------------
# create_dispute
# ---------------------------------------------------------------------------


def create_dispute(
    claim_id: int,
    rationale: str,
    *,
    submitted_by: str | None = None,
    notifier: Notifier | None = None,
    conn: psycopg.Connection[Any] | None = None,
) -> Dispute:
    """Create a new dispute ticket for a claim.

    - Generates a unique ticket_code (DSP-<8hex>).
    - Sets sla_deadline = now() + 7 days (AC-5).
    - Pins methodology_version_at_publication via get_pinned_methodology_version
      on the claim's most recent non-superseded resolution (EC-12, NFR-2).
      Falls back to the current METHODOLOGY_VERSION when no resolution exists yet.
    - INSERTs a row in the disputes table (0006 column names).
    - Sends a neutral ticket-confirmation via the Notifier seam (FakeNotifier by
      default when notifier=None -- mock-first; production callers must supply
      ResendNotifier explicitly).

    Args:
        claim_id:     ID of the claim being disputed.
        rationale:    Dispute rationale text (user input, not site copy).
        submitted_by: Optional contact email of the submitter.
        notifier:     Notifier implementation; defaults to FakeNotifier().
        conn:         Optional psycopg connection (injected by tests via
                      db_conn fixture for rollback behaviour).

    Returns:
        Dispute model populated from the inserted row.
    """
    if notifier is None:
        notifier = FakeNotifier()

    now = datetime.now(UTC)
    sla_deadline = now + timedelta(days=7)
    ticket_code = _generate_ticket_code()

    if conn is None:
        own_conn = True
        active_conn: psycopg.Connection[Any] = psycopg.connect(database_url())
    else:
        own_conn = False
        active_conn = conn

    try:
        with active_conn.cursor() as cur:
            # EC-12: pin the methodology version from the claim's most recent
            # non-superseded resolution, if one exists.  Fall back to the
            # current global METHODOLOGY_VERSION when no resolution exists.
            methodology_version_at_publication = _get_pinned_methodology_version(cur, claim_id)

            # Guard against the (extremely unlikely) ticket_code collision.
            while True:
                cur.execute("select 1 from disputes where ticket_code = %s", (ticket_code,))
                if cur.fetchone() is None:
                    break
                ticket_code = _generate_ticket_code()

            cur.execute(
                """
                insert into disputes (
                    ticket_code, claim_id, submitted_by, rationale, state,
                    sla_deadline, submitted_at, methodology_version_at_publication
                ) values (%s, %s, %s, %s, 'open', %s, %s, %s)
                returning id, submitted_at
                """,
                (
                    ticket_code,
                    claim_id,
                    submitted_by,
                    rationale,
                    sla_deadline,
                    now,
                    methodology_version_at_publication,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            dispute_id = int(row[0])
            submitted_at: datetime = row[1]

        if own_conn:
            active_conn.commit()

        # Send a neutral ticket-confirmation via the Notifier seam (AC-7).
        _send_ticket_confirmation(
            notifier=notifier,
            ticket_code=ticket_code,
            submitted_by=submitted_by,
            sla_deadline=sla_deadline,
        )

        return Dispute(
            id=dispute_id,
            ticket_code=ticket_code,
            claim_id=claim_id,
            submitted_by=submitted_by,
            rationale=rationale,
            state="open",
            sla_deadline=sla_deadline,
            submitted_at=submitted_at,
            methodology_version_at_publication=methodology_version_at_publication,
        )

    finally:
        if own_conn:
            active_conn.close()


# ---------------------------------------------------------------------------
# record_adjudication
# ---------------------------------------------------------------------------


def record_adjudication(
    dispute_id: int,
    *,
    outcome: Literal["upheld", "corrected"],
    reviewer_id: str,
    note: str,
    corrective_resolution: Any | None = None,
    notifier: Notifier | None = None,
    conn: psycopg.Connection[Any] | None = None,
) -> None:
    """Record the adjudication of a dispute ticket.

    outcome='upheld':
        UPDATE the dispute row to state='upheld' with reviewer fields.
        No new resolution row is created.  No corrections row written.

    outcome='corrected':
        1. Look up the claim's current non-superseded resolution id (=
           superseded_resolution_id for the new row).
        2. Append a superseding resolution row via _insert_resolution (the same
           append path the resolver uses — NFR-3 cannot be bypassed).
        3. INSERT a row into the corrections table (public log, FR-405, NFR-3).
           The summary is neutral, factual copy (AC-7 firewall — no
           buy/sell/hold or recommendation language).
        4. UPDATE the dispute row to state='corrected', reviewer_id,
           adjudicated_at, adjudication_note, resolution_id.

    After the dispute row is updated and the DB write is durable, the analyst
    is notified of the outcome via the Notifier seam when analysts.notify_email
    is set (PRD UF-3 / HP-5 "analyst notified", AC-5).  Neutral register (AC-7);
    a null email is a no-op.  The notice is sent AFTER commit, so a
    notification-side failure raises to the caller even though the adjudication
    is already recorded — it never rolls the adjudication back.

    NEVER UPDATE or DELETE an existing resolution row (NFR-3).

    Args:
        dispute_id:            Row ID of the dispute being adjudicated.
        outcome:               'upheld' or 'corrected'.
        reviewer_id:           ID of the reviewer (NFR-2 reproducibility).
        note:                  Adjudication note; stored on the dispute row.
        corrective_resolution: Required when outcome='corrected'.  A Resolution
                               model with claim_id, outcome, rule_id, rationale,
                               price_citation, methodology_version set.
                               supersedes_resolution_id is set internally.
        notifier:              Notifier for the analyst outcome notice; defaults
                               to FakeNotifier() (mock-first).
        conn:                  Optional psycopg connection (injected by tests).

    Raises:
        ValueError: For missing corrective_resolution when outcome='corrected'.
    """
    if outcome == "corrected" and corrective_resolution is None:
        raise ValueError("corrective_resolution is required when outcome='corrected'")

    if notifier is None:
        notifier = FakeNotifier()

    now = datetime.now(UTC)

    if conn is None:
        own_conn = True
        active_conn: psycopg.Connection[Any] = psycopg.connect(database_url())
    else:
        own_conn = False
        active_conn = conn

    try:
        if outcome == "corrected":
            assert corrective_resolution is not None  # narrowing for mypy

            with active_conn.cursor() as cur:
                # Fetch the dispute row to get claim_id.
                cur.execute("select claim_id from disputes where id = %s", (dispute_id,))
                d_row = cur.fetchone()
                assert d_row is not None, f"dispute {dispute_id} not found"
                claim_id = int(d_row[0])

                # Find the current (non-superseded) resolution id for this claim.
                superseded_id = _find_current_resolution_id(cur, claim_id)

                # Set supersedes_resolution_id on the corrective resolution.
                corr_with_supersedes = corrective_resolution.model_copy(
                    update={"supersedes_resolution_id": superseded_id}
                )

                # Append the superseding resolution (NFR-3 append-only).
                new_res_id = _insert_resolution(cur, corr_with_supersedes)

                # INSERT the public corrections log row (FR-405, NFR-3).
                # Summary is neutral, factual register (AC-7 — no
                # buy/sell/hold/recommendation language).
                correction_summary = (
                    "Resolution corrected after dispute review; superseding resolution appended."
                )
                cur.execute(
                    """
                    insert into corrections (
                        claim_id, dispute_id, summary,
                        superseded_resolution_id, superseding_resolution_id,
                        published_at
                    ) values (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        claim_id,
                        dispute_id,
                        correction_summary,
                        superseded_id,
                        new_res_id,
                        now,
                    ),
                )

                # UPDATE the dispute row (disputes is mutable working state).
                cur.execute(
                    """
                    update disputes
                       set state             = 'corrected',
                           reviewer_id       = %s,
                           adjudicated_at    = %s,
                           adjudication_note = %s,
                           resolution_id     = %s
                     where id = %s
                    """,
                    (reviewer_id, now, note, new_res_id, dispute_id),
                )

        else:
            # outcome == 'upheld': no new resolution, no corrections row.
            with active_conn.cursor() as cur:
                cur.execute(
                    """
                    update disputes
                       set state             = 'upheld',
                           reviewer_id       = %s,
                           adjudicated_at    = %s,
                           adjudication_note = %s
                     where id = %s
                    """,
                    (reviewer_id, now, note, dispute_id),
                )

        if own_conn:
            active_conn.commit()

        # AC-5 / UF-3: notify the analyst of the outcome after the DB write is
        # durable (mirrors create_dispute).  Sent only when the analyst has a
        # known contact email; a null email is a no-op.  Neutral register (AC-7).
        _notify_analyst_of_adjudication(
            active_conn, dispute_id=dispute_id, outcome=outcome, notifier=notifier
        )

    finally:
        if own_conn:
            active_conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_pinned_methodology_version(cur: psycopg.Cursor[Any], claim_id: int) -> str:
    """EC-12: Return the methodology_version from the claim's most recent
    non-superseded resolution, or the current METHODOLOGY_VERSION as fallback.

    'Non-superseded' means: no newer resolution row has this row's id in its
    supersedes_resolution_id column.  We pick the most recent such row.
    """
    cur.execute(
        """
        select r.methodology_version
          from resolutions r
         where r.claim_id = %s
           and r.id not in (
               select supersedes_resolution_id
                 from resolutions
                where supersedes_resolution_id is not null
                  and claim_id = %s
           )
         order by r.id desc
         limit 1
        """,
        (claim_id, claim_id),
    )
    row = cur.fetchone()
    if row is not None:
        return str(row[0])
    # No resolution yet; pin the current methodology version.
    return METHODOLOGY_VERSION


def _find_current_resolution_id(cur: psycopg.Cursor[Any], claim_id: int) -> int | None:
    """Return the most recent non-superseded resolution ID for a claim.

    Used internally to set supersedes_resolution_id on a corrective resolution.
    """
    cur.execute(
        """
        select r.id
          from resolutions r
         where r.claim_id = %s
           and r.id not in (
               select supersedes_resolution_id
                 from resolutions
                where supersedes_resolution_id is not null
                  and claim_id = %s
           )
         order by r.id desc
         limit 1
        """,
        (claim_id, claim_id),
    )
    row = cur.fetchone()
    return int(row[0]) if row is not None else None


def _notify_analyst_of_adjudication(
    conn: psycopg.Connection[Any],
    *,
    dispute_id: int,
    outcome: Literal["upheld", "corrected"],
    notifier: Notifier,
) -> None:
    """Notify the analyst that a dispute on their claim was adjudicated (UF-3, AC-5).

    Resolves the analyst contact (analysts.notify_email) via the dispute's claim
    and sends one neutral notice (AC-7 — no buy/sell/hold/recommendation
    language) only when an email is known; a null email is a no-op.  Called
    after the DB write is durable, so a send failure cannot undo the
    adjudication.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select d.ticket_code, a.notify_email
              from disputes d
              join claims c   on c.id = d.claim_id
              join analysts a on a.id = c.analyst_id
             where d.id = %s
            """,
            (dispute_id,),
        )
        row = cur.fetchone()
    if row is None or not row[1]:
        return
    ticket_code = str(row[0])
    to = str(row[1])
    subject = f"Dispute adjudicated: {ticket_code}"
    body = (
        f"A dispute referencing your published claim has been adjudicated.\n\n"
        f"Ticket reference: {ticket_code}\n"
        f"Outcome: {outcome}\n\n"
        f"The public corrections log reflects any resulting change. "
        f"No action is required."
    )
    notifier.send(to=to, subject=subject, body=body)


def _send_ticket_confirmation(
    *,
    notifier: Notifier,
    ticket_code: str,
    submitted_by: str | None,
    sla_deadline: datetime,
) -> None:
    """Send a neutral ticket-confirmation via the Notifier seam (AC-7).

    When submitted_by is None, the notification goes to a system placeholder
    address.  The DB operation is not blocked by notification failure.
    """
    to = submitted_by if submitted_by else "disputes@brier.app"
    sla_str = sla_deadline.strftime("%Y-%m-%d %H:%M UTC")
    subject = f"Dispute received: {ticket_code}"
    body = (
        f"Your dispute has been received.\n\n"
        f"Ticket reference: {ticket_code}\n"
        f"Review target: {sla_str} (7-day SLA)\n\n"
        f"The reviewer will examine the claim and rationale. "
        f"You will be notified of the adjudication outcome."
    )
    notifier.send(to=to, subject=subject, body=body)


# ---------------------------------------------------------------------------
# Public re-export: Correction model (for callers that need the type)
# ---------------------------------------------------------------------------

__all__ = [
    "Dispute",
    "Correction",
    "create_dispute",
    "record_adjudication",
    "_generate_ticket_code",
    "_get_pinned_methodology_version",
    "_find_current_resolution_id",
]
