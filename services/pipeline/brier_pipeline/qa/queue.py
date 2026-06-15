"""QA queue loop (FR-203, US-009, HP-4).

Low-confidence extractions route to the reviewer queue (Label Studio per PRD
§21). Reviewers approve / correct / void; every decision records reviewer_id
(NFR-2). Diarization uncertainty (EC-5) and classifier residue (EC-3) also
route here.
"""

from __future__ import annotations

import abc
import json
import urllib.request
from collections.abc import Callable
from typing import Any

import psycopg

from brier_pipeline import config
from brier_pipeline.models import Claim, ReviewState

# Confidence threshold below which claims are routed to human review (FR-203).
# PROVISIONAL: 0.8 is a placeholder. It must be re-calibrated after the
# E3-T6 golden-set eval harness is built and run (AC-1). Do not treat this
# value as final until that calibration exercise is complete.
CONFIDENCE_THRESHOLD = 0.8


def route_low_confidence(claims: list[Claim]) -> list[Claim]:
    """Split claims into those needing human review vs. auto-approved.

    ORDERING CONTRACT: this function runs on in-memory claims in the
    pre-persistence stage, AFTER the EC-3 is_excluded_span exclusion filter
    has already dropped any claims whose flags["excluded_reason"] was set by
    the pass-2 classifier with high confidence. By the time claims reach this
    function, no claim with a confident excluded_reason survives — so routing
    on that field would be dead code. Do NOT add excluded_reason to the
    predicate below.

    A claim is routed to the QA queue when ANY of the following hold:
      - extraction_confidence is None OR < CONFIDENCE_THRESHOLD (FR-203)
      - flags["diarization_uncertain"] is truthy (EC-5: guest/speaker
        uncertainty; PLANNED flag — set by future EC-5 diarization handling
        in E4-T3, not yet emitted by any current producer)
      - flags["ec3_residue"] is truthy (EC-3 residue the pass-2 classifier
        was UNSURE about — distinct from the confident excluded_reason drop
        already handled by is_excluded_span; PLANNED flag — set by future
        E3-T4 classifier, not yet emitted by any current producer)
      - flags["is_sponsor_segment"] is truthy (EC-4: a prediction inside a
        sponsor/ad read is never auto-published; it is routed to QA so a human
        confirms it should be excluded). Set by flag_sponsor_segment.
      - flags["legal_fast_track"] is truthy (EC-10: a legal/defamation concern
        always routes to QA — it is never auto-approved regardless of extraction
        confidence). Set by flag_legal_fast_track.

    For every routed claim: review_state = UNREVIEWED, publishable = False.
    For every non-routed claim (confidence >= threshold, no blocking flags):
      review_state = APPROVED, publishable = True,
      flags["auto_approved"] = True (so downstream can distinguish
      auto-approved from not-yet-reviewed — both have reviewer_id None,
      but only auto-approved has this flag set; NFR-2).

    Mutates claims in place (working state is mutable before DB write).
    Returns only the routed (needs-review) subset.

    Note: the 0.8 threshold is PROVISIONAL — to be re-calibrated after the
    E3-T6 golden-set eval harness is built and run (AC-1).
    """
    routed: list[Claim] = []

    for claim in claims:
        below_threshold = (
            claim.extraction_confidence is None
            or claim.extraction_confidence < CONFIDENCE_THRESHOLD
        )
        # PLANNED: diarization_uncertain is set by EC-5 diarization handling
        # (E4-T3). Not yet emitted by any current producer.
        diarization_uncertain = bool(claim.flags.get("diarization_uncertain"))
        # PLANNED: ec3_residue is set by the E3-T4 EC-3 residue classifier
        # when it is UNSURE (as opposed to certain excluded_reason drops,
        # which never reach this function). Not yet emitted by any current producer.
        ec3_residue = bool(claim.flags.get("ec3_residue"))
        # EC-4 sponsor segments and EC-10 legal fast-track always route to QA:
        # neither may be auto-approved, even at high extraction confidence.
        is_sponsor_segment = bool(claim.flags.get("is_sponsor_segment"))
        legal_fast_track = bool(claim.flags.get("legal_fast_track"))

        needs_review = (
            below_threshold
            or diarization_uncertain
            or ec3_residue
            or is_sponsor_segment
            or legal_fast_track
        )

        if needs_review:
            claim.review_state = ReviewState.UNREVIEWED
            claim.publishable = False
            routed.append(claim)
        else:
            # Auto-approve: confidence >= threshold and no blocking flags.
            # Set auto_approved so downstream can distinguish this from
            # not-yet-reviewed (both have reviewer_id None per NFR-2).
            claim.review_state = ReviewState.APPROVED
            claim.publishable = True
            claim.flags["auto_approved"] = True

    return routed


def route_and_enqueue(claims: list[Claim], queue: ReviewQueue) -> list[Claim]:
    """Route low-confidence claims and enqueue each one for human review (HP-4).

    Calls route_low_confidence(claims) then queue.enqueue(claim) for every
    routed claim. Returns the routed subset (same list as route_low_confidence).

    This is the HP-4 wiring point: it connects the in-memory routing predicate
    to the live ReviewQueue seam (InMemoryReviewQueue in CI/tests,
    LabelStudioQueue at runtime). Without this function the queue seam is dead
    code; calling it makes the loop live.
    """
    routed = route_low_confidence(claims)
    for claim in routed:
        queue.enqueue(claim)
    return routed


def record_review(
    claim_id: int,
    reviewer_id: str,
    decision: ReviewState,
    note: str,
    conn: psycopg.Connection[Any] | None = None,
) -> None:
    """Persist a reviewer decision to the claims row (US-009, NFR-2).

    Sets review_state, reviewer_id, publishable, and records the reviewer note
    into flags['review_note'] (preserving all existing flags).

    Publishability rule:
      - APPROVED or CORRECTED  -> publishable = True
      - VOIDED or UNREVIEWED   -> publishable = False

    Caller-owns-transaction pattern (mirrors poll_registered_channels):
      - When conn is passed, use it and do NOT commit.
      - When conn is None, open + own + commit + close.

    Raises RuntimeError if claim_id does not exist (no silent no-op).

    Claims rows are mutable (normal UPDATE); resolutions and scores are
    append-only ledgers and are never touched here (NFR-3).
    """
    publishable = decision in {ReviewState.APPROVED, ReviewState.CORRECTED}

    if conn is not None:
        _record_review_with_conn(claim_id, reviewer_id, decision, note, publishable, conn)
    else:
        from brier_pipeline.db import connect

        _conn: psycopg.Connection[Any] = connect()
        try:
            _record_review_with_conn(claim_id, reviewer_id, decision, note, publishable, _conn)
            _conn.commit()
        finally:
            _conn.close()


def _record_review_with_conn(
    claim_id: int,
    reviewer_id: str,
    decision: ReviewState,
    note: str,
    publishable: bool,
    conn: psycopg.Connection[Any],
) -> None:
    """Internal: execute the review UPDATE on a provided connection (no commit).

    NFR-2 audit trail: before overwriting reviewer_id, any existing reviewer_id
    is preserved in flags["review_history"] as an appended JSON object
    {reviewer_id, review_state, note} so the full reviewer chain is never lost.
    claims rows are mutable (normal UPDATE); resolutions and scores are never
    touched here (NFR-3 append-only ledger).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE claims
            SET    review_state = %s,
                   reviewer_id  = %s,
                   publishable  = %s,
                   flags        = jsonb_set(
                                      -- First, append the OLD reviewer identity
                                      -- to flags["review_history"] before overwriting
                                      -- (NFR-2: full reviewer audit trail preserved).
                                      -- If reviewer_id is NULL (first review), the
                                      -- history entry is skipped via CASE.
                                      CASE
                                        WHEN reviewer_id IS NOT NULL THEN
                                          jsonb_set(
                                            flags,
                                            '{review_history}',
                                            coalesce(flags->'review_history', '[]'::jsonb)
                                              || jsonb_build_array(jsonb_build_object(
                                                   'reviewer_id',   reviewer_id,
                                                   'review_state',  review_state,
                                                   'note',          flags->>'review_note'
                                                 )),
                                            true
                                          )
                                        ELSE flags
                                      END,
                                      '{review_note}',
                                      to_jsonb(%s::text),
                                      true
                                  )
            WHERE  id = %s
            """,
            (str(decision), reviewer_id, publishable, note, claim_id),
        )
        if cur.rowcount == 0:
            raise RuntimeError(
                f"record_review: claim_id {claim_id!r} not found; "
                "no rows updated (check the claim exists before calling record_review)"
            )


# ---------------------------------------------------------------------------
# ReviewQueue ABC + implementations (PRD §21 mock-first seam)
# ---------------------------------------------------------------------------


class ReviewQueue(abc.ABC):
    """Abstract interface for the human review queue (PRD §21, HP-4).

    Concrete implementations:
      - InMemoryReviewQueue  — CI/test fake (no network, no external deps)
      - LabelStudioQueue     — live seam via stdlib urllib (ADR gate: no SDK)
    """

    @abc.abstractmethod
    def enqueue(self, claim: Claim) -> str:
        """Submit a claim to the review queue.

        Returns a task reference string (e.g. a Label Studio task ID or a
        synthetic ref in the in-memory fake).
        """
        ...


class InMemoryReviewQueue(ReviewQueue):
    """CI/test fake: stores enqueued claims in a list, returns synthetic refs.

    This is the only path exercised in tests.  No network, no external deps.
    The enqueued list is the test assertion surface.
    """

    def __init__(self) -> None:
        self.enqueued: list[Claim] = []

    def enqueue(self, claim: Claim) -> str:
        """Store the claim in-memory and return a synthetic task ref."""
        self.enqueued.append(claim)
        return f"mem-task-{len(self.enqueued)}"


def _urllib_post(req: urllib.request.Request) -> dict[str, Any]:
    """Real network POST using stdlib urllib; returns the parsed JSON response body.

    This is the default http_post implementation for LabelStudioQueue.  It is
    NOT called in tests — tests inject a fake callable via the http_post=
    parameter on LabelStudioQueue.__init__.
    """
    with urllib.request.urlopen(req) as resp:
        return dict[str, Any](json.loads(resp.read().decode("utf-8")))


class LabelStudioQueue(ReviewQueue):
    """Live seam: POST claims to a Label Studio project import endpoint.

    Uses stdlib urllib.request only — no Label Studio SDK, no new dependency
    (same pattern as the Anthropic completion seam in extraction/llm.py).

    Requires:
      - BRIER_LABEL_STUDIO_URL   (e.g. http://localhost:8080)
      - BRIER_LABEL_STUDIO_TOKEN (Label Studio API token)

    When either is unconfigured (empty string), raises RuntimeError immediately
    rather than making a network call with invalid credentials.

    The http_post parameter is the network seam: tests inject a fake callable
    so that no real HTTP request is ever made in the test suite.  At runtime
    the default (_urllib_post) is used.

    NEVER makes real network calls in tests; CI/tests use InMemoryReviewQueue
    or inject a fake http_post callable.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        project_id: int = 1,
        http_post: Callable[[urllib.request.Request], dict[str, Any]] | None = None,
    ) -> None:
        self._base_url = (base_url if base_url is not None else config.label_studio_url()).rstrip(
            "/"
        )
        self._token = token if token is not None else config.label_studio_token()
        self._project_id = project_id
        self._http_post: Callable[[urllib.request.Request], dict[str, Any]] = (
            http_post if http_post is not None else _urllib_post
        )

    def enqueue(self, claim: Claim) -> str:
        """POST the claim as a Label Studio task to the project import endpoint.

        Returns a best-effort import ref string derived from the Label Studio
        JSON-body import response.

        IMPORTANT: the Label Studio /api/projects/{id}/import endpoint returns
        an import summary ({"task_count": N, "file_upload_ids": [...], ...}),
        NOT individual task IDs.  ``file_upload_ids`` contains file-upload
        object IDs, not task IDs.  If you need the actual task ID you must
        issue a follow-up GET /api/tasks/?project=N query after import.  This
        method returns a best-effort ref (the first file_upload_id, or the
        string "ls-import-unknown") and does NOT claim it is a task ID.

        Raises RuntimeError when BRIER_LABEL_STUDIO_URL or BRIER_LABEL_STUDIO_TOKEN
        is not configured.
        """
        if not self._base_url:
            raise RuntimeError(
                "LabelStudioQueue: BRIER_LABEL_STUDIO_URL is not configured. "
                "Set the env var or pass base_url= explicitly."
            )
        if not self._token:
            raise RuntimeError(
                "LabelStudioQueue: BRIER_LABEL_STUDIO_TOKEN is not configured. "
                "Set the env var or pass token= explicitly."
            )

        url = f"{self._base_url}/api/projects/{self._project_id}/import"
        task_data = [
            {
                "data": {
                    "claim_id": claim.id,
                    "asset": claim.asset,
                    "direction": claim.direction,
                    "extraction_confidence": claim.extraction_confidence,
                    "flags": claim.flags,
                    "quote": claim.quote,
                    "review_state": str(claim.review_state),
                }
            }
        ]
        body = json.dumps(task_data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Token {self._token}",
            },
            method="POST",
        )
        response_data = self._http_post(req)

        # Label Studio JSON-body import returns:
        # {"task_count": N, "annotation_count": N, "predictions_count": N,
        #  "duration": ..., "file_upload_ids": [...], "could_be_tasks_list": ...,
        #  "found_formats": [...], "data_columns": [...]}
        # file_upload_ids holds file-upload object IDs, NOT task IDs.
        # For real task IDs, use a follow-up GET /api/tasks/?project=N.
        upload_ids: list[Any] = response_data.get("file_upload_ids", [])
        ref = str(upload_ids[0]) if upload_ids else "ls-import-unknown"
        return ref
