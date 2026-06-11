"""Transcription behind a small interface (mock-first convention).

Real adapters: faster-whisper large-v3 on a rented GPU for the backfill batch,
Deepgram/Groq API for incremental (PRD §18). Audio is transient with a 30-day
TTL; only transcripts persist (FR-103, NFR-4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    """One utterance with second-level offsets (FR-103)."""

    start_seconds: float
    end_seconds: float
    text: str


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        """Transcribe transient audio into offset-stamped segments."""


class FakeTranscriber(Transcriber):
    """Fixture-backed fake: returns canned segments from data/fixtures/transcripts/."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        # TASK: E1-T1 (fixture transcripts), E2-T4 (adapter contract tests)
        raise NotImplementedError


class WhisperTranscriber(Transcriber):
    """faster-whisper large-v3 batch adapter for the backfill. Not used until E2."""

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        # TASK: E2-T4
        raise NotImplementedError


class DeepgramTranscriber(Transcriber):
    """Hosted API adapter for incremental uploads. Not used until E2."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        # TASK: E2-T4
        raise NotImplementedError
