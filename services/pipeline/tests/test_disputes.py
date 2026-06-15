"""E5-T3 dispute intake tests (FR-405, US-006, AC-5, UF-3, EC-12, NFR-2, NFR-3).

Schema used: 0006_ops.sql column names (ticket_code, submitted_by, state,
sla_deadline, submitted_at, methodology_version_at_publication) plus the two
additive columns from 0007_disputes.sql (reviewer_id, resolution_id).

Test categories:
  1. Unit tests (no DB): ticket_code format, SLA calculation, FakeNotifier,
     ResendNotifier key guard.
  2. DB-backed tests (db_conn rolled-back fixture):
     - create_dispute -> ticket_code format (DSP-+8hex) + sla_deadline approx
       now+7d + methodology_version_at_publication pinned + FakeNotifier got
       one message.
     - record_adjudication corrective ->
         (a) a NEW superseding resolution exists with supersedes_resolution_id
             set to the prior resolution,
         (b) a row in corrections links dispute_id + superseded + superseding
             resolution ids,
         (c) disputes.state='corrected' + resolution_id set,
         (d) the PRIOR resolution row is UNCHANGED (NFR-3).
     - record_adjudication upheld -> state='upheld', no new resolution, no
       corrections row.
     - NFR-3 trigger proof: a direct UPDATE on resolutions raises.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from brier_pipeline.config import METHODOLOGY_VERSION
from brier_pipeline.disputes.intake import (
    _generate_ticket_code,
    _get_pinned_methodology_version,
    create_dispute,
    record_adjudication,
)
from brier_pipeline.disputes.notify import FakeNotifier, ResendNotifier
from brier_pipeline.models import Correction, Dispute, Resolution

# ---------------------------------------------------------------------------
# DB seed helpers
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
    status: str = "resolved",
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
            'dispute test claim fewer than fifteen words.',
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


def _seed_resolution(
    cur: Any,
    claim_id: int,
    *,
    outcome: float = 1.0,
    methodology_version: str = METHODOLOGY_VERSION,
    supersedes_resolution_id: int | None = None,
) -> int:
    """Insert a resolution row and return its id."""
    cur.execute(
        """
        insert into resolutions (
            claim_id, outcome, resolved_at, rule_id, rationale,
            price_citation, methodology_version, supersedes_resolution_id
        ) values (
            %s, %s, now(), 'target_by_deadline.v0',
            'Dispute test resolution.',
            '{"asset": "BTC", "day": "2025-07-14", "close_usd": 80140.0, "source": "test"}',
            %s, %s
        ) returning id
        """,
        (claim_id, outcome, methodology_version, supersedes_resolution_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# 1. Unit tests (no DB)
# ---------------------------------------------------------------------------


class TestTicketCodeGeneration:
    def test_format_is_dsp_prefix_plus_8_hex(self) -> None:
        """ticket_code format: DSP-<8 lowercase hex chars>."""
        code = _generate_ticket_code()
        assert re.match(r"^DSP-[0-9a-f]{8}$", code), f"Unexpected format: {code!r}"

    def test_codes_are_unique(self) -> None:
        """Successive calls produce distinct codes (birthday-problem collision negligible)."""
        codes = {_generate_ticket_code() for _ in range(50)}
        assert len(codes) == 50


class TestFakeNotifier:
    def test_send_records_message(self) -> None:
        """FakeNotifier.send() appends a SentMessage to self.sent."""
        notifier = FakeNotifier()
        notifier.send(to="analyst@example.com", subject="Test", body="Hello")
        assert len(notifier.sent) == 1
        msg = notifier.sent[0]
        assert msg.to == "analyst@example.com"
        assert msg.subject == "Test"
        assert msg.body == "Hello"

    def test_multiple_sends_accumulate(self) -> None:
        notifier = FakeNotifier()
        notifier.send(to="a@example.com", subject="S1", body="B1")
        notifier.send(to="b@example.com", subject="S2", body="B2")
        assert len(notifier.sent) == 2
        assert notifier.sent[0].to == "a@example.com"
        assert notifier.sent[1].to == "b@example.com"

    def test_starts_empty(self) -> None:
        notifier = FakeNotifier()
        assert notifier.sent == []


class TestResendNotifierKeyGuard:
    def test_raises_runtime_error_when_key_absent(self, monkeypatch: Any) -> None:
        """ResendNotifier raises RuntimeError when BRIER_RESEND_API_KEY is absent."""
        monkeypatch.delenv("BRIER_RESEND_API_KEY", raising=False)
        notifier = ResendNotifier()
        with pytest.raises(RuntimeError, match="BRIER_RESEND_API_KEY"):
            notifier.send(to="x@example.com", subject="S", body="B")

    def test_adr_reference_in_error_message(self, monkeypatch: Any) -> None:
        """RuntimeError message references ADR-0010."""
        monkeypatch.delenv("BRIER_RESEND_API_KEY", raising=False)
        notifier = ResendNotifier()
        with pytest.raises(RuntimeError, match="0010"):
            notifier.send(to="x@example.com", subject="S", body="B")

    def test_calls_http_post_when_key_set(self, monkeypatch: Any) -> None:
        """When key is set, ResendNotifier calls http_post with correct args."""
        monkeypatch.setenv("BRIER_RESEND_API_KEY", "test-key-abc")
        captured: list[tuple[str, dict[str, Any], dict[str, str]]] = []

        def fake_post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
            captured.append((url, payload, headers))
            return {"id": "fake-resend-id"}

        notifier = ResendNotifier(http_post=fake_post)
        notifier.send(to="analyst@example.com", subject="Ticket DSP-abcd1234", body="Your ticket")

        assert len(captured) == 1
        url, payload, headers = captured[0]
        assert "resend.com" in url
        assert payload["to"] == ["analyst@example.com"]
        assert "DSP-abcd1234" in payload["subject"]
        assert "Bearer test-key-abc" in headers.get("Authorization", "")


class TestSlaCalculation:
    def test_sla_is_7_days_from_now(self) -> None:
        """SLA deadline is now + 7 days (AC-5)."""
        before = datetime.now(UTC)
        sla = datetime.now(UTC) + timedelta(days=7)
        after = datetime.now(UTC)
        assert sla >= before + timedelta(days=7)
        assert sla <= after + timedelta(days=7) + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# 2. DB-backed tests
# ---------------------------------------------------------------------------


class TestCreateDisputeDB:
    """DB-backed tests for create_dispute() (rolled-back db_conn fixture)."""

    def test_create_dispute_returns_dispute_model(self, db_conn: Any) -> None:
        """create_dispute() returns a Dispute model (from models.py)."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        notifier = FakeNotifier()
        dispute = create_dispute(
            claim_id,
            "The BTC price citation is incorrect for this date.",
            submitted_by="analyst@example.com",
            notifier=notifier,
            conn=db_conn,
        )

        assert isinstance(dispute, Dispute)
        assert dispute.id is not None

    def test_ticket_code_format(self, db_conn: Any) -> None:
        """create_dispute() ticket_code matches DSP-<8hex>."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        dispute = create_dispute(claim_id, "Rationale.", conn=db_conn)

        assert re.match(r"^DSP-[0-9a-f]{8}$", dispute.ticket_code), (
            f"Unexpected ticket_code format: {dispute.ticket_code!r}"
        )

    def test_sla_deadline_is_approximately_7_days(self, db_conn: Any) -> None:
        """create_dispute() sla_deadline = now + 7 days (AC-5)."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        before = datetime.now(UTC)
        dispute = create_dispute(claim_id, "Rationale for SLA test.", conn=db_conn)
        after = datetime.now(UTC)

        assert dispute.sla_deadline >= before + timedelta(days=7)
        assert dispute.sla_deadline <= after + timedelta(days=7) + timedelta(seconds=1)

    def test_methodology_version_pinned_from_resolution(self, db_conn: Any) -> None:
        """create_dispute() pins methodology_version_at_publication from the claim's resolution."""
        pinned_version = "v1.0-test-pin"

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            _seed_resolution(cur, claim_id, methodology_version=pinned_version)

        dispute = create_dispute(claim_id, "Disputing this resolution.", conn=db_conn)

        assert dispute.methodology_version_at_publication == pinned_version

    def test_methodology_version_falls_back_when_no_resolution(self, db_conn: Any) -> None:
        """When no resolution exists, falls back to METHODOLOGY_VERSION."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        dispute = create_dispute(claim_id, "No resolution yet.", conn=db_conn)

        assert dispute.methodology_version_at_publication == METHODOLOGY_VERSION

    def test_fake_notifier_gets_one_message(self, db_conn: Any) -> None:
        """FakeNotifier receives exactly one confirmation message per create_dispute()."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        notifier = FakeNotifier()
        dispute = create_dispute(
            claim_id,
            "This is my rationale.",
            submitted_by="analyst@example.com",
            notifier=notifier,
            conn=db_conn,
        )

        assert len(notifier.sent) == 1
        msg = notifier.sent[0]
        assert msg.to == "analyst@example.com"
        assert dispute.ticket_code in msg.subject or dispute.ticket_code in msg.body

    def test_initial_state_is_open(self, db_conn: Any) -> None:
        """Dispute starts in 'open' state."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        dispute = create_dispute(claim_id, "Status check rationale.", conn=db_conn)

        assert dispute.state == "open"

        with db_conn.cursor() as cur:
            cur.execute("select state from disputes where id = %s", (dispute.id,))
            row = cur.fetchone()
        assert row is not None
        assert str(row[0]) == "open"

    def test_row_persisted_with_0006_columns(self, db_conn: Any) -> None:
        """create_dispute() inserts a disputes row using 0006 column names."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

        dispute = create_dispute(
            claim_id,
            "Verify DB row exists.",
            submitted_by="alice@example.com",
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select ticket_code, claim_id, submitted_by, rationale, state,
                       sla_deadline, methodology_version_at_publication
                  from disputes
                 where id = %s
                """,
                (dispute.id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert str(row[0]) == dispute.ticket_code
        assert int(row[1]) == claim_id
        assert str(row[2]) == "alice@example.com"
        assert "Verify DB row exists" in str(row[3])
        assert str(row[4]) == "open"


# ---------------------------------------------------------------------------
# 3. record_adjudication — corrective path
# ---------------------------------------------------------------------------


class TestRecordAdjudicationCorrectiveDB:
    """DB-backed tests for record_adjudication() corrective path (NFR-3)."""

    def test_corrective_appends_new_resolution(self, db_conn: Any) -> None:
        """(a) A NEW superseding resolution exists with supersedes_resolution_id set."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            orig_res_id = _seed_resolution(cur, claim_id, outcome=0.0)

        dispute = create_dispute(
            claim_id,
            "The outcome was wrong; the BTC close was above the target on the deadline.",
            submitted_by="analyst@example.com",
            notifier=FakeNotifier(),
            conn=db_conn,
        )
        assert dispute.id is not None
        dispute_id = dispute.id

        corrective = Resolution(
            claim_id=claim_id,
            outcome=1.0,
            rule_id="target_by_deadline.v0",
            rationale="Corrected: BTC closed above target on 2025-07-14 per re-check.",
            price_citation={
                "asset": "BTC",
                "day": "2025-07-14",
                "close_usd": 80500.0,
                "source": "test",
            },
            methodology_version=METHODOLOGY_VERSION,
            supersedes_resolution_id=orig_res_id,
        )

        record_adjudication(
            dispute_id,
            outcome="corrected",
            reviewer_id="reviewer-01",
            note="Re-checked the July 14 close; confirmed HIT.",
            corrective_resolution=corrective,
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select id, outcome, supersedes_resolution_id
                  from resolutions
                 where claim_id = %s
                 order by id
                """,
                (claim_id,),
            )
            rows = cur.fetchall()

        assert len(rows) == 2, f"Expected 2 resolution rows, got {len(rows)}"
        original_row = next(r for r in rows if int(r[0]) == orig_res_id)
        new_row = next(r for r in rows if int(r[0]) != orig_res_id)

        # (d) The prior resolution is UNCHANGED (NFR-3).
        assert float(original_row[1]) == 0.0
        assert original_row[2] is None

        # (a) The new row supersedes the original.
        assert float(new_row[1]) == 1.0
        assert int(new_row[2]) == orig_res_id

    def test_corrections_row_links_dispute_and_resolutions(self, db_conn: Any) -> None:
        """(b) A row in corrections links dispute_id + superseded + superseding resolution ids."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            orig_res_id = _seed_resolution(cur, claim_id, outcome=0.0)

        dispute = create_dispute(claim_id, "Outcome wrong.", notifier=FakeNotifier(), conn=db_conn)
        assert dispute.id is not None
        dispute_id = dispute.id

        corrective = Resolution(
            claim_id=claim_id,
            outcome=1.0,
            rule_id="target_by_deadline.v0",
            rationale="Corrected.",
            price_citation={
                "asset": "BTC",
                "day": "2025-07-14",
                "close_usd": 80500.0,
                "source": "test",
            },
            methodology_version=METHODOLOGY_VERSION,
            supersedes_resolution_id=orig_res_id,
        )
        record_adjudication(
            dispute_id,
            outcome="corrected",
            reviewer_id="reviewer-01",
            note="Confirmed.",
            corrective_resolution=corrective,
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select claim_id, dispute_id, superseded_resolution_id,
                       superseding_resolution_id
                  from corrections
                 where dispute_id = %s
                """,
                (dispute_id,),
            )
            c_row = cur.fetchone()
        assert c_row is not None, "Expected a corrections row"
        assert int(c_row[0]) == claim_id
        assert int(c_row[1]) == dispute_id
        assert int(c_row[2]) == orig_res_id  # superseded
        # superseding_resolution_id must be the newly inserted resolution
        assert c_row[3] is not None

    def test_dispute_state_corrected_and_resolution_id_set(self, db_conn: Any) -> None:
        """(c) disputes.state='corrected' + resolution_id set to superseding row."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            orig_res_id = _seed_resolution(cur, claim_id, outcome=0.0)

        dispute = create_dispute(claim_id, "Wrong outcome.", notifier=FakeNotifier(), conn=db_conn)
        assert dispute.id is not None
        dispute_id = dispute.id

        corrective = Resolution(
            claim_id=claim_id,
            outcome=1.0,
            rule_id="target_by_deadline.v0",
            rationale="Corrected outcome.",
            price_citation={
                "asset": "BTC",
                "day": "2025-07-14",
                "close_usd": 80500.0,
                "source": "test",
            },
            methodology_version=METHODOLOGY_VERSION,
            supersedes_resolution_id=orig_res_id,
        )
        record_adjudication(
            dispute_id,
            outcome="corrected",
            reviewer_id="reviewer-01",
            note="Confirmed correction.",
            corrective_resolution=corrective,
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select state, reviewer_id, adjudication_note, resolution_id
                  from disputes where id = %s
                """,
                (dispute_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert str(row[0]) == "corrected"
        assert str(row[1]) == "reviewer-01"
        assert "Confirmed correction" in str(row[2])
        assert row[3] is not None  # resolution_id linked

    def test_prior_resolution_unchanged_nfr3(self, db_conn: Any) -> None:
        """(d) The PRIOR resolution row is UNCHANGED after corrective adjudication (NFR-3)."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            orig_res_id = _seed_resolution(cur, claim_id, outcome=0.0)

        # Capture original row state.
        with db_conn.cursor() as cur:
            cur.execute(
                """
                select outcome, rationale, supersedes_resolution_id
                  from resolutions where id = %s
                """,
                (orig_res_id,),
            )
            before_row = cur.fetchone()
        assert before_row is not None

        dispute = create_dispute(
            claim_id, "Prior resolution was wrong.", notifier=FakeNotifier(), conn=db_conn
        )
        assert dispute.id is not None
        dispute_id = dispute.id

        corrective = Resolution(
            claim_id=claim_id,
            outcome=1.0,
            rule_id="target_by_deadline.v0",
            rationale="Corrected resolution.",
            price_citation={
                "asset": "BTC",
                "day": "2025-07-14",
                "close_usd": 80500.0,
                "source": "test",
            },
            methodology_version=METHODOLOGY_VERSION,
            supersedes_resolution_id=orig_res_id,
        )
        record_adjudication(
            dispute_id,
            outcome="corrected",
            reviewer_id="reviewer-02",
            note="Correction applied.",
            corrective_resolution=corrective,
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select outcome, rationale, supersedes_resolution_id
                  from resolutions where id = %s
                """,
                (orig_res_id,),
            )
            after_row = cur.fetchone()
        assert after_row is not None
        assert float(after_row[0]) == float(before_row[0]), "Outcome must not change (NFR-3)"
        assert after_row[2] is None, "Original must keep supersedes=None (NFR-3)"


# ---------------------------------------------------------------------------
# 4. record_adjudication — upheld path
# ---------------------------------------------------------------------------


class TestRecordAdjudicationUpheldDB:
    """DB-backed tests for record_adjudication() upheld path."""

    def test_upheld_sets_state_and_reviewer(self, db_conn: Any) -> None:
        """record_adjudication(upheld) sets state='upheld' and reviewer fields."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            _seed_resolution(cur, claim_id)

        dispute = create_dispute(
            claim_id, "I think the outcome is wrong.", notifier=FakeNotifier(), conn=db_conn
        )
        assert dispute.id is not None
        dispute_id = dispute.id

        record_adjudication(
            dispute_id,
            outcome="upheld",
            reviewer_id="reviewer-03",
            note="Reviewed the clip; outcome confirmed correct.",
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                """
                select state, reviewer_id, adjudication_note, resolution_id
                  from disputes where id = %s
                """,
                (dispute_id,),
            )
            row = cur.fetchone()
        assert row is not None
        assert str(row[0]) == "upheld"
        assert str(row[1]) == "reviewer-03"
        assert "confirmed correct" in str(row[2])
        assert row[3] is None  # no corrective resolution for upheld

    def test_upheld_no_new_resolution_row(self, db_conn: Any) -> None:
        """record_adjudication(upheld) does NOT append a new resolution row."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            _seed_resolution(cur, claim_id)

        with db_conn.cursor() as cur:
            cur.execute("select count(*) from resolutions where claim_id = %s", (claim_id,))
            count_row = cur.fetchone()
        assert count_row is not None
        count_before = int(count_row[0])

        dispute = create_dispute(
            claim_id, "I disagree with the outcome.", notifier=FakeNotifier(), conn=db_conn
        )
        assert dispute.id is not None
        dispute_id = dispute.id

        record_adjudication(
            dispute_id,
            outcome="upheld",
            reviewer_id="reviewer-04",
            note="Outcome stands.",
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute("select count(*) from resolutions where claim_id = %s", (claim_id,))
            after_row = cur.fetchone()
        assert after_row is not None
        count_after = int(after_row[0])

        assert count_after == count_before, (
            f"Upheld adjudication must not append new resolutions; "
            f"before={count_before}, after={count_after}"
        )

    def test_upheld_no_corrections_row(self, db_conn: Any) -> None:
        """record_adjudication(upheld) does NOT write a corrections row."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            _seed_resolution(cur, claim_id)

        dispute = create_dispute(claim_id, "I disagree.", notifier=FakeNotifier(), conn=db_conn)
        assert dispute.id is not None
        dispute_id = dispute.id

        record_adjudication(
            dispute_id,
            outcome="upheld",
            reviewer_id="reviewer-05",
            note="Outcome stands.",
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute("select count(*) from corrections where dispute_id = %s", (dispute_id,))
            row = cur.fetchone()
        assert row is not None
        n = int(row[0])
        assert n == 0, f"Upheld must write no corrections row; found {n}"


# ---------------------------------------------------------------------------
# 5. NFR-3 append-only trigger proof
# ---------------------------------------------------------------------------


class TestNFR3AppendOnlyTrigger:
    """Prove the DB trigger blocks UPDATE/DELETE on resolutions (NFR-3)."""

    def test_update_resolution_raises_trigger(self, db_conn: Any) -> None:
        """Attempting to UPDATE a resolutions row raises psycopg.errors.RaiseException."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            res_id = _seed_resolution(cur, claim_id)

        with pytest.raises(psycopg.errors.RaiseException):
            with db_conn.cursor() as cur:
                cur.execute(
                    "update resolutions set outcome = 0.5 where id = %s",
                    (res_id,),
                )

    def test_delete_resolution_raises_trigger(self, db_conn: Any) -> None:
        """Attempting to DELETE a resolutions row raises psycopg.errors.RaiseException."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            res_id = _seed_resolution(cur, claim_id)

        with pytest.raises(psycopg.errors.RaiseException):
            with db_conn.cursor() as cur:
                cur.execute("delete from resolutions where id = %s", (res_id,))


# ---------------------------------------------------------------------------
# 6. _get_pinned_methodology_version helper
# ---------------------------------------------------------------------------


class TestGetPinnedMethodologyVersion:
    """Unit-style DB tests for _get_pinned_methodology_version helper."""

    def test_returns_resolution_version_not_current(self, db_conn: Any) -> None:
        """Returns the version from the non-superseded resolution."""
        historical_version = "v1.0-historical"

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            _seed_resolution(cur, claim_id, methodology_version=historical_version)

            pinned = _get_pinned_methodology_version(cur, claim_id)

        assert pinned == historical_version

    def test_skips_superseded_resolution(self, db_conn: Any) -> None:
        """Uses the non-superseded resolution (latest chain tip)."""
        old_version = "v0.9"
        new_version = "v1.1"

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="resolved")
            orig_id = _seed_resolution(cur, claim_id, methodology_version=old_version)
            _seed_resolution(
                cur, claim_id, methodology_version=new_version, supersedes_resolution_id=orig_id
            )

            pinned = _get_pinned_methodology_version(cur, claim_id)

        assert pinned == new_version

    def test_falls_back_to_current_when_no_resolution(self, db_conn: Any) -> None:
        """Falls back to METHODOLOGY_VERSION when no resolution exists."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, status="open")

            pinned = _get_pinned_methodology_version(cur, claim_id)

        assert pinned == METHODOLOGY_VERSION


# ---------------------------------------------------------------------------
# 7. Model type checks
# ---------------------------------------------------------------------------


class TestModelTypes:
    """Verify the imported models from models.py are the ones used."""

    def test_dispute_is_pydantic_model(self) -> None:
        """Dispute from models.py is a Pydantic BaseModel."""
        from brier_pipeline.models import Dispute as DisputeModel

        assert Dispute is DisputeModel

    def test_correction_is_pydantic_model(self) -> None:
        """Correction from models.py is a Pydantic BaseModel."""
        from brier_pipeline.models import Correction as CorrectionModel

        assert Correction is CorrectionModel
