"""A2#5: get_transcriber() factory — mock-first transcriber selection.

The fixture-backed FakeTranscriber is the CI/dev path; DeepgramTranscriber
activates on BRIER_DEEPGRAM_API_KEY (incremental uploads); 'backfill' mode
returns WhisperTranscriber (ADR-0003, GPU host). Production refuses to
transcribe real audio with the fake.
"""

from __future__ import annotations

import pytest

from brier_pipeline.transcription.transcriber import (
    DeepgramTranscriber,
    FakeTranscriber,
    WhisperTranscriber,
    get_transcriber,
)


def test_incremental_without_key_returns_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIER_DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("BRIER_ENV", raising=False)
    assert isinstance(get_transcriber("incremental"), FakeTranscriber)


def test_incremental_with_key_returns_deepgram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIER_DEEPGRAM_API_KEY", "dg-test")
    monkeypatch.delenv("BRIER_ENV", raising=False)
    assert isinstance(get_transcriber("incremental"), DeepgramTranscriber)


def test_backfill_returns_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIER_DEEPGRAM_API_KEY", raising=False)
    assert isinstance(get_transcriber("backfill"), WhisperTranscriber)


def test_production_incremental_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIER_ENV", "production")
    monkeypatch.delenv("BRIER_DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="BRIER_DEEPGRAM_API_KEY"):
        get_transcriber("incremental")


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="Unknown transcriber mode"):
        get_transcriber("bogus")
