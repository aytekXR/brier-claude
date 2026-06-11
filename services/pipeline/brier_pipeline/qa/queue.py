"""QA queue loop (FR-203, US-009, HP-4).

Low-confidence extractions route to the reviewer queue (Label Studio per PRD
§21). Reviewers approve / correct / void; every decision records reviewer_id
(NFR-2). Diarization uncertainty (EC-5) and classifier residue (EC-3) also
route here.
"""

from __future__ import annotations

from brier_pipeline.models import Claim, ReviewState

CONFIDENCE_THRESHOLD = 0.8  # placeholder constant; calibrated against the golden set in E3


def route_low_confidence(claims: list[Claim]) -> list[Claim]:
    """Split off claims below CONFIDENCE_THRESHOLD for human review."""
    # TASK: E3-T3
    raise NotImplementedError


def record_review(claim_id: int, reviewer_id: str, decision: ReviewState, note: str) -> None:
    """Persist a reviewer decision; only approved/corrected claims publish."""
    # TASK: E3-T3
    raise NotImplementedError
