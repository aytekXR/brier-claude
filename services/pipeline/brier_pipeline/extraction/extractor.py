"""Claim extraction behind a small interface (mock-first convention).

Pass 1 detects candidate prediction spans (FR-201); pass 2 structures each span
into the FR-202 claim tuple with model and prompt versions recorded (NFR-2).
The real implementation is LLM-backed via the LiteLLM router (litellm.config.yaml);
the FakeExtractor replays fixture claims so the walking skeleton (E1) and all
tests run without an API key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel

from brier_pipeline.models import Claim
from brier_pipeline.transcription.transcriber import TranscriptSegment


class CandidateSpan(BaseModel):
    """Pass-1 output: a transcript span that smells like a prediction (FR-201)."""

    start_seconds: float
    end_seconds: float
    text: str


class Extractor(ABC):
    @abstractmethod
    def detect_candidates(self, segments: list[TranscriptSegment]) -> list[CandidateSpan]:
        """Pass 1: candidate prediction spans (FR-201)."""

    @abstractmethod
    def structure_claim(self, span: CandidateSpan) -> Claim:
        """Pass 2: structured FR-202 claim, with model/prompt versions stamped.

        Must classify non-falsifiable statements (FR-204) and exclude sarcasm,
        hypotheticals, and paraphrases of others (EC-3).
        """


class FakeExtractor(Extractor):
    """Fixture-backed fake: replays data/fixtures/claims.json (arrives with E1-T1)."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def detect_candidates(self, segments: list[TranscriptSegment]) -> list[CandidateSpan]:
        # TASK: E1-T1
        raise NotImplementedError

    def structure_claim(self, span: CandidateSpan) -> Claim:
        # TASK: E1-T1
        raise NotImplementedError


class LlmExtractor(Extractor):
    """Two-pass LLM extraction via LiteLLM. Not used until E3."""

    def __init__(self, model_version: str, prompt_version: str) -> None:
        self.model_version = model_version
        self.prompt_version = prompt_version

    def detect_candidates(self, segments: list[TranscriptSegment]) -> list[CandidateSpan]:
        # TASK: E3-T1
        raise NotImplementedError

    def structure_claim(self, span: CandidateSpan) -> Claim:
        # TASK: E3-T2
        raise NotImplementedError


def dedup_claims(claims: list[Claim]) -> list[Claim]:
    """FR-205: semantic dedup (same analyst/asset/direction, overlapping horizon).

    Repeats reinforce, not multiply; assigns dedup_cluster_id via pgvector
    similarity. Handles re-uploads where the original timestamp governs (EC-2).
    """
    # TASK: E3-T5
    raise NotImplementedError
