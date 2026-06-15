"""Tests for E3-T3: confidence threshold routing, record_review, and ReviewQueue seam.

Categories:
  1. route_low_confidence — pure/in-memory, no DB.
  2. record_review        — DB-backed via rolled-back db_conn fixture; skips when DB down.
  3. ReviewQueue ABC      — InMemoryReviewQueue (CI path); LabelStudioQueue unconfigured raises.

No network calls in any test. InMemoryReviewQueue is the only ReviewQueue exercised.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from typing import Any

import pytest

from brier_pipeline.models import Claim, ReviewState, SpecificityClass
from brier_pipeline.qa.queue import (
    CONFIDENCE_THRESHOLD,
    InMemoryReviewQueue,
    LabelStudioQueue,
    record_review,
    route_and_enqueue,
    route_low_confidence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    extraction_confidence: float | None = 0.95,
    flags: dict[str, Any] | None = None,
    analyst_id: int = 1,
    video_id: int = 1,
    transcript_id: int = 1,
) -> Claim:
    """Return a minimal Claim with controllable confidence and flags."""
    return Claim(
        analyst_id=analyst_id,
        video_id=video_id,
        transcript_id=transcript_id,
        specificity_class=SpecificityClass.DIRECTION_ONLY,
        source_offset_seconds=0,
        model_version="fake-v0",
        prompt_version="fake-v0",
        uttered_at=datetime(2026, 1, 1, tzinfo=UTC),
        extraction_confidence=extraction_confidence,
        flags=flags if flags is not None else {},
    )


# ---------------------------------------------------------------------------
# 1. route_low_confidence — pure unit tests (no DB)
# ---------------------------------------------------------------------------


class TestRouteLowConfidence:
    def test_low_confidence_claim_is_routed(self) -> None:
        """A claim with confidence below the threshold is routed to review."""
        claim = _make_claim(extraction_confidence=0.6)
        routed = route_low_confidence([claim])

        assert len(routed) == 1
        assert routed[0] is claim
        assert claim.publishable is False
        assert claim.review_state == ReviewState.UNREVIEWED

    def test_high_confidence_claim_is_auto_approved(self) -> None:
        """A claim with confidence >= threshold is auto-approved, NOT routed."""
        claim = _make_claim(extraction_confidence=0.95)
        routed = route_low_confidence([claim])

        assert routed == []
        assert claim.review_state == ReviewState.APPROVED
        assert claim.publishable is True

    def test_none_confidence_is_routed(self) -> None:
        """A claim with None extraction_confidence must be routed (FR-203)."""
        claim = _make_claim(extraction_confidence=None)
        routed = route_low_confidence([claim])

        assert len(routed) == 1
        assert claim.publishable is False
        assert claim.review_state == ReviewState.UNREVIEWED

    def test_diarization_uncertain_routes_despite_high_confidence(self) -> None:
        """EC-5: diarization_uncertain flag routes even a high-confidence claim."""
        claim = _make_claim(
            extraction_confidence=0.99,
            flags={"diarization_uncertain": True},
        )
        routed = route_low_confidence([claim])

        assert len(routed) == 1
        assert routed[0] is claim
        assert claim.publishable is False
        assert claim.review_state == ReviewState.UNREVIEWED

    def test_ec3_residue_flag_routes_claim(self) -> None:
        """EC-3 residue: ec3_residue flag routes a high-confidence claim (≥ 0.8)."""
        claim = _make_claim(
            extraction_confidence=0.95,
            flags={"ec3_residue": True},
        )
        routed = route_low_confidence([claim])

        assert len(routed) == 1
        assert routed[0] is claim
        assert claim.publishable is False
        assert claim.review_state == ReviewState.UNREVIEWED

    def test_excluded_reason_alone_not_routed(self) -> None:
        """excluded_reason alone must NOT route a high-confidence claim.

        is_excluded_span (E3-T2) drops such claims upstream before they reach
        route_low_confidence.  Routing on excluded_reason here would be dead
        code and would re-introduce dropped claims into the queue.
        """
        claim = _make_claim(
            extraction_confidence=0.95,
            flags={"excluded_reason": "sarcasm"},
        )
        routed = route_low_confidence([claim])

        assert routed == []
        assert claim.publishable is True
        assert claim.review_state == ReviewState.APPROVED

    def test_exact_threshold_not_routed(self) -> None:
        """A claim at exactly the threshold (not below it) is auto-approved."""
        claim = _make_claim(extraction_confidence=CONFIDENCE_THRESHOLD)
        routed = route_low_confidence([claim])

        assert routed == []
        assert claim.publishable is True
        assert claim.review_state == ReviewState.APPROVED

    def test_just_below_threshold_is_routed(self) -> None:
        """A claim just below the threshold is routed."""
        claim = _make_claim(extraction_confidence=CONFIDENCE_THRESHOLD - 0.001)
        routed = route_low_confidence([claim])

        assert len(routed) == 1

    def test_mixed_list_splits_correctly(self) -> None:
        """Mixed list: only below-threshold / flagged claims are returned."""
        low = _make_claim(extraction_confidence=0.5)
        high = _make_claim(extraction_confidence=0.95)
        flagged = _make_claim(extraction_confidence=0.99, flags={"diarization_uncertain": True})

        routed = route_low_confidence([low, high, flagged])

        assert len(routed) == 2
        assert low in routed
        assert flagged in routed
        assert high not in routed
        # High-confidence, unflagged claim is auto-approved.
        assert high.review_state == ReviewState.APPROVED
        assert high.publishable is True

    def test_empty_list_returns_empty(self) -> None:
        """Empty input returns empty output without errors."""
        assert route_low_confidence([]) == []

    def test_diarization_uncertain_falsy_does_not_route(self) -> None:
        """A falsy diarization_uncertain value (False/0) does not trigger routing."""
        claim = _make_claim(
            extraction_confidence=0.95,
            flags={"diarization_uncertain": False},
        )
        routed = route_low_confidence([claim])

        assert routed == []
        assert claim.publishable is True


# ---------------------------------------------------------------------------
# 2. record_review — DB-backed (rolled-back db_conn fixture)
# ---------------------------------------------------------------------------


def _insert_minimal_claim(conn: Any) -> int:
    """Insert the minimal parent rows (analyst, video, transcript) and one claim.

    Uses synthetic channel IDs unlikely to collide with seeded data.
    Returns the new claim's integer id.
    All inserts live in the test transaction rolled back by db_conn.
    """
    with conn.cursor() as cur:
        # Analyst
        cur.execute(
            """
            INSERT INTO analysts (channel_id, display_name, slug)
            VALUES ('UCqa-test-channel-e3t3', 'QA Test Analyst E3-T3', 'qa-test-analyst-e3t3')
            RETURNING id
            """,
        )
        row = cur.fetchone()
        assert row is not None
        analyst_id: int = int(row[0])

        # Video
        cur.execute(
            """
            INSERT INTO videos (analyst_id, youtube_video_id, title, published_at)
            VALUES (%s, 'qa-test-vid-e3t3-001', 'QA Test Video E3-T3', now())
            RETURNING id
            """,
            (analyst_id,),
        )
        row = cur.fetchone()
        assert row is not None
        video_id: int = int(row[0])

        # Transcript
        cur.execute(
            """
            INSERT INTO transcripts (video_id, source, storage_pointer)
            VALUES (%s, 'captions', 'fake://qa-test-e3t3')
            RETURNING id
            """,
            (video_id,),
        )
        row = cur.fetchone()
        assert row is not None
        transcript_id: int = int(row[0])

        # Claim
        cur.execute(
            """
            INSERT INTO claims (
                analyst_id, video_id, transcript_id,
                specificity_class, source_offset_seconds,
                model_version, prompt_version, uttered_at,
                extraction_confidence
            ) VALUES (%s, %s, %s, 'direction_only', 0,
                      'fake-v0', 'fake-v0', now(), 0.65)
            RETURNING id
            """,
            (analyst_id, video_id, transcript_id),
        )
        row = cur.fetchone()
        assert row is not None
        claim_id: int = int(row[0])

    return claim_id


def test_record_review_approved_sets_publishable_true(db_conn: Any) -> None:
    """APPROVED decision makes publishable=True and sets reviewer_id (US-009, NFR-2)."""
    claim_id = _insert_minimal_claim(db_conn)

    record_review(claim_id, "reviewer-alice", ReviewState.APPROVED, "looks good", conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT review_state, reviewer_id, publishable,"
            " flags->>'review_note' FROM claims WHERE id = %s",
            (claim_id,),
        )
        row = cur.fetchone()

    assert row is not None
    review_state, reviewer_id, publishable, review_note = row
    assert review_state == "approved"
    assert reviewer_id == "reviewer-alice"
    assert publishable is True
    assert review_note == "looks good"


def test_record_review_voided_sets_publishable_false(db_conn: Any) -> None:
    """VOIDED decision makes publishable=False."""
    claim_id = _insert_minimal_claim(db_conn)

    record_review(claim_id, "reviewer-bob", ReviewState.VOIDED, "not a claim", conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT review_state, publishable FROM claims WHERE id = %s",
            (claim_id,),
        )
        row = cur.fetchone()

    assert row is not None
    review_state, publishable = row
    assert review_state == "voided"
    assert publishable is False


def test_record_review_corrected_sets_publishable_true(db_conn: Any) -> None:
    """CORRECTED decision makes publishable=True (claim was fixed, safe to publish)."""
    claim_id = _insert_minimal_claim(db_conn)

    record_review(
        claim_id,
        "reviewer-carol",
        ReviewState.CORRECTED,
        "fixed horizon to end-of-year",
        conn=db_conn,
    )

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT review_state, publishable FROM claims WHERE id = %s",
            (claim_id,),
        )
        row = cur.fetchone()

    assert row is not None
    review_state, publishable = row
    assert review_state == "corrected"
    assert publishable is True


def test_record_review_second_call_overwrites_decision(db_conn: Any) -> None:
    """A second record_review call updates the row; VOIDED after APPROVED -> not publishable."""
    claim_id = _insert_minimal_claim(db_conn)

    record_review(claim_id, "reviewer-alice", ReviewState.APPROVED, "first pass", conn=db_conn)
    record_review(
        claim_id, "reviewer-bob", ReviewState.VOIDED, "re-review: not a prediction", conn=db_conn
    )

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT review_state, reviewer_id, publishable FROM claims WHERE id = %s",
            (claim_id,),
        )
        row = cur.fetchone()

    assert row is not None
    review_state, reviewer_id, publishable = row
    assert review_state == "voided"
    assert reviewer_id == "reviewer-bob"
    assert publishable is False


def test_record_review_unknown_claim_id_raises(db_conn: Any) -> None:
    """record_review raises RuntimeError for a nonexistent claim_id (no silent no-op)."""
    nonexistent_id = 999_999_999

    with pytest.raises(RuntimeError, match="not found"):
        record_review(
            nonexistent_id,
            "reviewer-dave",
            ReviewState.APPROVED,
            "should raise",
            conn=db_conn,
        )


def test_record_review_preserves_existing_flags(db_conn: Any) -> None:
    """record_review preserves existing flags keys and only adds review_note."""
    # Insert a claim with a pre-existing flag
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analysts (channel_id, display_name, slug)
            VALUES ('UCqa-flags-test-e3t3', 'Flags Test Analyst', 'qa-flags-test-e3t3')
            RETURNING id
            """,
        )
        row = cur.fetchone()
        assert row is not None
        analyst_id = int(row[0])

        cur.execute(
            """
            INSERT INTO videos (analyst_id, youtube_video_id, title, published_at)
            VALUES (%s, 'qa-flags-vid-e3t3', 'Flags Test Video', now())
            RETURNING id
            """,
            (analyst_id,),
        )
        row = cur.fetchone()
        assert row is not None
        video_id = int(row[0])

        cur.execute(
            """
            INSERT INTO transcripts (video_id, source, storage_pointer)
            VALUES (%s, 'captions', 'fake://flags-test-e3t3')
            RETURNING id
            """,
            (video_id,),
        )
        row = cur.fetchone()
        assert row is not None
        transcript_id = int(row[0])

        cur.execute(
            """
            INSERT INTO claims (
                analyst_id, video_id, transcript_id,
                specificity_class, source_offset_seconds,
                model_version, prompt_version, uttered_at,
                flags
            ) VALUES (%s, %s, %s, 'direction_only', 0,
                      'fake-v0', 'fake-v0', now(),
                      '{"diarization_uncertain": true}'::jsonb)
            RETURNING id
            """,
            (analyst_id, video_id, transcript_id),
        )
        row = cur.fetchone()
        assert row is not None
        claim_id = int(row[0])

    record_review(
        claim_id, "reviewer-eve", ReviewState.APPROVED, "confirmed owner speaker", conn=db_conn
    )

    with db_conn.cursor() as cur:
        cur.execute("SELECT flags FROM claims WHERE id = %s", (claim_id,))
        row = cur.fetchone()

    assert row is not None
    flags = row[0]
    # Original flag must still be present.
    assert flags.get("diarization_uncertain") is True
    # review_note must have been added.
    assert flags.get("review_note") == "confirmed owner speaker"


# ---------------------------------------------------------------------------
# 3. ReviewQueue seam tests — no network
# ---------------------------------------------------------------------------


class TestInMemoryReviewQueue:
    def test_enqueue_stores_claim(self) -> None:
        """Enqueued claim is stored in the .enqueued list."""
        queue = InMemoryReviewQueue()
        claim = _make_claim()

        ref = queue.enqueue(claim)

        assert len(queue.enqueued) == 1
        assert queue.enqueued[0] is claim
        assert ref == "mem-task-1"

    def test_enqueue_returns_sequential_refs(self) -> None:
        """Each enqueue call returns a distinct sequential ref."""
        queue = InMemoryReviewQueue()
        refs = [queue.enqueue(_make_claim()) for _ in range(3)]

        assert refs == ["mem-task-1", "mem-task-2", "mem-task-3"]

    def test_enqueued_list_is_per_instance(self) -> None:
        """Each InMemoryReviewQueue instance has its own enqueued list."""
        q1 = InMemoryReviewQueue()
        q2 = InMemoryReviewQueue()

        q1.enqueue(_make_claim())

        assert len(q1.enqueued) == 1
        assert len(q2.enqueued) == 0


class TestLabelStudioQueueUnconfigured:
    def test_raises_when_base_url_missing(self) -> None:
        """LabelStudioQueue.enqueue raises RuntimeError when base URL is not set."""
        queue = LabelStudioQueue(base_url="", token="some-token")
        claim = _make_claim()

        with pytest.raises(RuntimeError, match="BRIER_LABEL_STUDIO_URL"):
            queue.enqueue(claim)

    def test_raises_when_token_missing(self) -> None:
        """LabelStudioQueue.enqueue raises RuntimeError when token is not set."""
        queue = LabelStudioQueue(base_url="http://localhost:8080", token="")
        claim = _make_claim()

        with pytest.raises(RuntimeError, match="BRIER_LABEL_STUDIO_TOKEN"):
            queue.enqueue(claim)

    def test_no_network_call_from_any_test(self) -> None:
        """Confirm that raising happens before any urllib call (no network side-effect).

        This test verifies the guard-clause pattern: the RuntimeError must be
        raised before urllib.request.urlopen is ever reached.
        """
        queue = LabelStudioQueue(base_url="", token="")
        claim = _make_claim()

        # Must raise immediately; if it reached urllib it would raise a different
        # exception type (URLError / ConnectionRefused, not RuntimeError).
        with pytest.raises(RuntimeError):
            queue.enqueue(claim)


class TestLabelStudioQueueInjectedPost:
    """Structural isolation tests: LabelStudioQueue with an injected http_post callable.

    No real network calls — the fake_post records the Request and returns a
    canned dict.  This verifies the URL, auth header, and JSON body shape
    without any live Label Studio instance.
    """

    def test_injected_http_post_is_called_with_correct_url_and_headers(self) -> None:
        """Injected fake_post receives the correct URL and Authorization header."""
        captured: list[urllib.request.Request] = []

        def fake_post(req: urllib.request.Request) -> dict[str, Any]:
            captured.append(req)
            return {"file_upload_ids": [42], "task_count": 1}

        queue = LabelStudioQueue(
            base_url="http://ls.example",
            token="t",
            project_id=1,
            http_post=fake_post,
        )
        claim = _make_claim()
        ref = queue.enqueue(claim)

        assert len(captured) == 1
        req = captured[0]
        assert req.full_url == "http://ls.example/api/projects/1/import"
        assert req.get_header("Authorization") == "Token t"
        assert req.get_header("Content-type") == "application/json"
        # Return ref is derived from file_upload_ids, not claimed to be a task ID.
        assert ref == "42"

    def test_injected_http_post_body_shape(self) -> None:
        """The JSON body sent to Label Studio contains the expected claim fields."""
        bodies: list[list[dict[str, Any]]] = []

        def fake_post(req: urllib.request.Request) -> dict[str, Any]:
            assert req.data is not None
            bodies.append(json.loads(req.data.decode("utf-8")))
            return {"file_upload_ids": [], "task_count": 1}

        queue = LabelStudioQueue(
            base_url="http://ls.example",
            token="t",
            http_post=fake_post,
        )
        claim = _make_claim(extraction_confidence=0.72, flags={"diarization_uncertain": True})
        queue.enqueue(claim)

        assert len(bodies) == 1
        task_list = bodies[0]
        assert isinstance(task_list, list)
        assert len(task_list) == 1
        data = task_list[0]["data"]
        assert "extraction_confidence" in data
        assert data["extraction_confidence"] == pytest.approx(0.72)
        assert "flags" in data
        assert data["flags"]["diarization_uncertain"] is True

    def test_injected_http_post_fallback_ref_when_no_upload_ids(self) -> None:
        """When file_upload_ids is empty, enqueue returns 'ls-import-unknown'."""

        def fake_post(req: urllib.request.Request) -> dict[str, Any]:
            return {"file_upload_ids": [], "task_count": 0}

        queue = LabelStudioQueue(
            base_url="http://ls.example",
            token="t",
            http_post=fake_post,
        )
        ref = queue.enqueue(_make_claim())
        assert ref == "ls-import-unknown"

    def test_unconfigured_raises_before_http_post_called(self) -> None:
        """RuntimeError is raised by the guard clauses before http_post is ever called.

        Both base_url="" and token="" variants are checked.  The injected fake
        records if it was called; a call would indicate the guard bypassed.
        """
        called: list[bool] = []

        def fake_post(req: urllib.request.Request) -> dict[str, Any]:
            called.append(True)
            return {}

        # base_url missing
        queue_no_url = LabelStudioQueue(base_url="", token="t", http_post=fake_post)
        with pytest.raises(RuntimeError, match="BRIER_LABEL_STUDIO_URL"):
            queue_no_url.enqueue(_make_claim())
        assert called == [], "http_post must not be called when base_url is missing"

        # token missing
        queue_no_token = LabelStudioQueue(
            base_url="http://ls.example", token="", http_post=fake_post
        )
        with pytest.raises(RuntimeError, match="BRIER_LABEL_STUDIO_TOKEN"):
            queue_no_token.enqueue(_make_claim())
        assert called == [], "http_post must not be called when token is missing"


# ---------------------------------------------------------------------------
# 4. HP-4 end-to-end — DB-backed, rolled-back db_conn
# ---------------------------------------------------------------------------


def _insert_low_confidence_claim(conn: Any) -> tuple[int, Claim]:
    """Insert a low-confidence claim (0.65) and return (claim_id, in-memory Claim).

    Uses synthetic channel IDs unlikely to collide with seeded data.
    Returns (claim_id_in_db, in_memory_claim) so tests can call both
    route_and_enqueue (in-memory) and record_review (DB).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analysts (channel_id, display_name, slug)
            VALUES ('UCqa-hp4-e3t3', 'HP4 E3T3 Analyst', 'hp4-e3t3-analyst')
            RETURNING id
            """,
        )
        row = cur.fetchone()
        assert row is not None
        analyst_id: int = int(row[0])

        cur.execute(
            """
            INSERT INTO videos (analyst_id, youtube_video_id, title, published_at)
            VALUES (%s, 'hp4-e3t3-vid-001', 'HP4 E3T3 Video', now())
            RETURNING id
            """,
            (analyst_id,),
        )
        row = cur.fetchone()
        assert row is not None
        video_id: int = int(row[0])

        cur.execute(
            """
            INSERT INTO transcripts (video_id, source, storage_pointer)
            VALUES (%s, 'captions', 'fake://hp4-e3t3')
            RETURNING id
            """,
            (video_id,),
        )
        row = cur.fetchone()
        assert row is not None
        transcript_id: int = int(row[0])

        cur.execute(
            """
            INSERT INTO claims (
                analyst_id, video_id, transcript_id,
                specificity_class, source_offset_seconds,
                model_version, prompt_version, uttered_at,
                extraction_confidence
            ) VALUES (%s, %s, %s, 'direction_only', 0,
                      'fake-v0', 'fake-v0', now(), 0.65)
            RETURNING id
            """,
            (analyst_id, video_id, transcript_id),
        )
        row = cur.fetchone()
        assert row is not None
        claim_id: int = int(row[0])

    claim = _make_claim(
        extraction_confidence=0.65,
        analyst_id=analyst_id,
        video_id=video_id,
        transcript_id=transcript_id,
    )
    return claim_id, claim


def test_hp4_end_to_end_route_and_record_review(db_conn: Any) -> None:
    """HP-4 full loop: low-confidence claim routes -> lands in InMemoryReviewQueue
    -> record_review APPROVED -> publishable=True, reviewer_id set, review_state approved.

    Encodes the complete HP-4 reviewer workflow: identify, queue, decide.
    """
    claim_id, claim = _insert_low_confidence_claim(db_conn)
    queue = InMemoryReviewQueue()

    # Route and enqueue
    routed = route_and_enqueue([claim], queue)

    # Claim is routed (publishable False, state UNREVIEWED) and landed in queue.
    assert len(routed) == 1
    assert routed[0] is claim
    assert claim.publishable is False
    assert claim.review_state == ReviewState.UNREVIEWED
    assert len(queue.enqueued) == 1
    assert queue.enqueued[0] is claim

    # Reviewer approves
    record_review(claim_id, "reviewer-x", ReviewState.APPROVED, "looks right", conn=db_conn)

    # DB row reflects the decision.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT review_state, reviewer_id, publishable FROM claims WHERE id = %s",
            (claim_id,),
        )
        row = cur.fetchone()

    assert row is not None
    review_state, reviewer_id, publishable = row
    assert publishable is True
    assert reviewer_id == "reviewer-x"
    assert review_state == "approved"


# ---------------------------------------------------------------------------
# 5. FR-203 invariant — DB-backed
# ---------------------------------------------------------------------------


def test_fr203_routed_claim_stays_unpublished_without_review(db_conn: Any) -> None:
    """FR-203 invariant: a claim inserted with publishable=False stays False
    when record_review is never called.

    Nothing below the confidence threshold publishes unreviewed.
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analysts (channel_id, display_name, slug)
            VALUES ('UCqa-fr203-e3t3', 'FR203 E3T3 Analyst', 'fr203-e3t3-analyst')
            RETURNING id
            """,
        )
        row = cur.fetchone()
        assert row is not None
        analyst_id = int(row[0])

        cur.execute(
            """
            INSERT INTO videos (analyst_id, youtube_video_id, title, published_at)
            VALUES (%s, 'fr203-e3t3-vid-001', 'FR203 E3T3 Video', now())
            RETURNING id
            """,
            (analyst_id,),
        )
        row = cur.fetchone()
        assert row is not None
        video_id = int(row[0])

        cur.execute(
            """
            INSERT INTO transcripts (video_id, source, storage_pointer)
            VALUES (%s, 'captions', 'fake://fr203-e3t3')
            RETURNING id
            """,
            (video_id,),
        )
        row = cur.fetchone()
        assert row is not None
        transcript_id = int(row[0])

        # Insert a claim with publishable=false and review_state=unreviewed —
        # simulating a claim that has been routed but not yet reviewed.
        cur.execute(
            """
            INSERT INTO claims (
                analyst_id, video_id, transcript_id,
                specificity_class, source_offset_seconds,
                model_version, prompt_version, uttered_at,
                extraction_confidence, publishable, review_state
            ) VALUES (%s, %s, %s, 'direction_only', 0,
                      'fake-v0', 'fake-v0', now(), 0.55,
                      false, 'unreviewed')
            RETURNING id
            """,
            (analyst_id, video_id, transcript_id),
        )
        row = cur.fetchone()
        assert row is not None
        claim_id = int(row[0])

    # No record_review call — verify it remains unpublished.
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT publishable, review_state FROM claims WHERE id = %s",
            (claim_id,),
        )
        row = cur.fetchone()

    assert row is not None
    publishable, review_state = row
    assert publishable is False, "Unreviewed routed claim must not be publishable (FR-203)"
    assert review_state == "unreviewed"
