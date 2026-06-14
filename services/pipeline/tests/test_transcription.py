"""Tests for E2-T4: captions + transcription adapters.

No network calls, no real credentials, no model downloads.
All external boundaries are injected fakes (mock-first convention).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.ingestion.youtube import DataApiYouTubeClient
from brier_pipeline.transcription.transcriber import (
    AUDIO_KEY_PREFIX,
    AUDIO_TTL_DAYS,
    DeepgramTranscriber,
    FakeTranscriber,
    TranscriptSegment,
    WhisperTranscriber,
    audio_key,
)

FIXTURES = Path(__file__).parent.parent.parent.parent / "data" / "fixtures"


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


def test_audio_ttl_days() -> None:
    """AUDIO_TTL_DAYS == 30 per NFR-4."""
    assert AUDIO_TTL_DAYS == 30


def test_audio_key_prefix() -> None:
    """audio_key() returns 'audio/<video_id>'."""
    assert audio_key("my-video-123") == "audio/my-video-123"
    assert audio_key("my-video-123").startswith(AUDIO_KEY_PREFIX)


# ---------------------------------------------------------------------------
# DataApiYouTubeClient.fetch_captions
# ---------------------------------------------------------------------------


def test_fetch_captions_returns_text_when_track_exists() -> None:
    """fetch_captions returns caption text when captions.list has items."""
    recorded_urls: list[str] = []

    def fake_http_get(url: str) -> dict[str, Any]:
        recorded_urls.append(url)
        return {
            "items": [
                {
                    "id": "track-abc",
                    "snippet": {"language": "en", "trackKind": "standard"},
                }
            ]
        }

    caption_text = "Hello world\nThis is a caption."

    def fake_caption_get(url: str) -> str:
        recorded_urls.append(url)
        return caption_text

    client = DataApiYouTubeClient("fake-key", http_get=fake_http_get, caption_get=fake_caption_get)
    result = client.fetch_captions("vid-001")

    assert result == caption_text
    # Verify captions.list was called (not search)
    assert any("captions" in u for u in recorded_urls), "Should call captions endpoint"
    assert not any("search" in u for u in recorded_urls), "Must never call search endpoint"


def test_fetch_captions_returns_none_when_no_tracks() -> None:
    """fetch_captions returns None when captions.list items is empty."""

    def fake_http_get(url: str) -> dict[str, Any]:
        return {"items": []}

    caption_get_called = False

    def fake_caption_get(url: str) -> str:
        nonlocal caption_get_called
        caption_get_called = True
        return ""

    client = DataApiYouTubeClient("fake-key", http_get=fake_http_get, caption_get=fake_caption_get)
    result = client.fetch_captions("vid-no-captions")

    assert result is None
    assert not caption_get_called, "caption_get should not be called when no tracks exist"


def test_fetch_captions_url_hits_captions_not_search() -> None:
    """The captions.list URL must reference the captions endpoint, never search."""
    recorded_list_urls: list[str] = []

    def fake_http_get(url: str) -> dict[str, Any]:
        recorded_list_urls.append(url)
        return {"items": []}

    client = DataApiYouTubeClient("api-key-xyz", http_get=fake_http_get)
    client.fetch_captions("some-video-id")

    assert len(recorded_list_urls) == 1
    url = recorded_list_urls[0]
    assert "captions" in url
    assert "search" not in url
    assert "some-video-id" in url
    assert "api-key-xyz" in url


def test_fetch_captions_increments_units_used() -> None:
    """fetch_captions should cost 1 quota unit (captions.list call)."""

    def fake_http_get(url: str) -> dict[str, Any]:
        return {"items": []}

    client = DataApiYouTubeClient("fake-key", http_get=fake_http_get)
    assert client.units_used == 0
    client.fetch_captions("vid-001")
    assert client.units_used == 1


# ---------------------------------------------------------------------------
# DeepgramTranscriber
# ---------------------------------------------------------------------------

_DEEPGRAM_UTTERANCES_RESPONSE: dict[str, Any] = {
    "results": {
        "utterances": [
            {"start": 0.0, "end": 5.3, "transcript": "Hello world"},
            {"start": 5.3, "end": 11.7, "transcript": "BTC will hit 100k by year end"},
            {"start": 11.7, "end": 18.0, "transcript": "That is my prediction for this cycle"},
        ]
    }
}


def test_deepgram_transcriber_maps_utterances() -> None:
    """DeepgramTranscriber maps utterances response to TranscriptSegment list."""

    def fake_http_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        return _DEEPGRAM_UTTERANCES_RESPONSE

    transcriber = DeepgramTranscriber("dg-key-fake", http_post=fake_http_post)
    segments = transcriber.transcribe("audio/test-video-id")

    assert len(segments) == 3
    assert segments[0] == TranscriptSegment(start_seconds=0.0, end_seconds=5.3, text="Hello world")
    assert segments[1] == TranscriptSegment(
        start_seconds=5.3, end_seconds=11.7, text="BTC will hit 100k by year end"
    )
    assert segments[2] == TranscriptSegment(
        start_seconds=11.7, end_seconds=18.0, text="That is my prediction for this cycle"
    )


def test_deepgram_transcriber_second_level_offsets() -> None:
    """All offsets in segments are second-level floats (FR-103)."""

    def fake_http_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        return _DEEPGRAM_UTTERANCES_RESPONSE

    transcriber = DeepgramTranscriber("dg-key-fake", http_post=fake_http_post)
    segments = transcriber.transcribe("audio/test-video-id")

    for seg in segments:
        assert isinstance(seg.start_seconds, float)
        assert isinstance(seg.end_seconds, float)
        assert seg.end_seconds > seg.start_seconds


def test_deepgram_transcriber_no_network() -> None:
    """Injected http_post is called; confirms no real network hit."""
    call_count = 0
    posted_url: list[str] = []

    def fake_http_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        posted_url.append(url)
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Token ")
        return _DEEPGRAM_UTTERANCES_RESPONSE

    transcriber = DeepgramTranscriber("my-dg-token", http_post=fake_http_post)
    transcriber.transcribe("audio/video-x")

    assert call_count == 1
    assert "deepgram.com" in posted_url[0]
    assert "search" not in posted_url[0]


def test_deepgram_words_fallback() -> None:
    """When utterances absent, fallback to words grouping."""
    words_response: dict[str, Any] = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "words": [
                                {"word": "hello", "start": 0.5, "end": 1.0},
                                {"word": "world", "start": 1.0, "end": 1.8},
                            ]
                        }
                    ]
                }
            ]
        }
    }

    def fake_http_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        return words_response

    transcriber = DeepgramTranscriber("dg-key", http_post=fake_http_post)
    segments = transcriber.transcribe("audio/v")

    assert len(segments) == 1
    assert segments[0].start_seconds == 0.5
    assert segments[0].end_seconds == 1.8
    assert "hello" in segments[0].text
    assert "world" in segments[0].text


def test_deepgram_raises_when_no_utterances_or_words() -> None:
    """Raises ValueError when response has neither utterances nor words."""

    def fake_http_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
        return {"results": {}}

    transcriber = DeepgramTranscriber("dg-key", http_post=fake_http_post)
    with pytest.raises(ValueError, match="utterances"):
        transcriber.transcribe("audio/v")


# ---------------------------------------------------------------------------
# WhisperTranscriber (seam tests with injected fake model)
# ---------------------------------------------------------------------------


class _FakeSegment:
    """Mimics a faster_whisper Segment namedtuple: .start, .end, .text."""

    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeWhisperModel:
    """Mimics a WhisperModel: .transcribe() yields (segments_iter, info)."""

    def __init__(self, segments: list[_FakeSegment]) -> None:
        self._segments = segments

    def transcribe(self, audio_pointer: str) -> tuple[list[_FakeSegment], dict[str, Any]]:
        return self._segments, {"language": "en", "language_probability": 0.99}


def test_whisper_transcriber_maps_segments() -> None:
    """WhisperTranscriber correctly maps fake model segments to TranscriptSegment."""
    fake_segments = [
        _FakeSegment(0.0, 4.5, " Opening statement."),
        _FakeSegment(4.5, 9.1, " BTC is going to 80k."),
        _FakeSegment(9.1, 14.2, " That is my view."),
    ]
    fake_model = _FakeWhisperModel(fake_segments)

    def fake_loader(model_size: str) -> _FakeWhisperModel:
        assert model_size == "large-v3"
        return fake_model

    transcriber = WhisperTranscriber(model_size="large-v3", model_loader=fake_loader)
    segments = transcriber.transcribe("audio/my-video")

    assert len(segments) == 3
    assert segments[0] == TranscriptSegment(
        start_seconds=0.0, end_seconds=4.5, text=" Opening statement."
    )
    assert segments[1] == TranscriptSegment(
        start_seconds=4.5, end_seconds=9.1, text=" BTC is going to 80k."
    )
    assert segments[2] == TranscriptSegment(
        start_seconds=9.1, end_seconds=14.2, text=" That is my view."
    )


def test_whisper_transcriber_second_level_offsets() -> None:
    """All offsets from WhisperTranscriber are second-level floats (FR-103)."""
    fake_segments = [
        _FakeSegment(0.0, 3.0, "Segment one."),
        _FakeSegment(3.0, 7.5, "Segment two."),
    ]
    fake_model = _FakeWhisperModel(fake_segments)

    def fake_loader(model_size: str) -> _FakeWhisperModel:
        return fake_model

    transcriber = WhisperTranscriber(model_loader=fake_loader)
    segments = transcriber.transcribe("audio/v")

    for seg in segments:
        assert isinstance(seg.start_seconds, float)
        assert isinstance(seg.end_seconds, float)


def test_whisper_transcriber_custom_model_size() -> None:
    """model_size is passed through to the loader."""
    received_sizes: list[str] = []
    fake_model = _FakeWhisperModel([])

    def fake_loader(model_size: str) -> _FakeWhisperModel:
        received_sizes.append(model_size)
        return fake_model

    transcriber = WhisperTranscriber(model_size="medium", model_loader=fake_loader)
    transcriber.transcribe("audio/v")

    assert received_sizes == ["medium"]


def test_whisper_transcriber_default_loader_raises_runtime_error_when_absent() -> None:
    """Default loader raises RuntimeError mentioning ADR-0003 when faster_whisper absent.

    faster-whisper is NOT installed in CI/dev (ADR-0003 pending approval).
    This test proves the error is a RuntimeError (not NotImplementedError) with
    an actionable message pointing to the ADR.
    """
    transcriber = WhisperTranscriber()  # uses default loader
    with pytest.raises(RuntimeError) as exc_info:
        transcriber.transcribe("audio://x")

    error_message = str(exc_info.value)
    assert "faster-whisper" in error_message, f"Expected 'faster-whisper' in: {error_message!r}"
    assert "0003" in error_message, f"Expected ADR reference '0003' in: {error_message!r}"


# ---------------------------------------------------------------------------
# FakeTranscriber (CI path — fixture-backed)
# ---------------------------------------------------------------------------


def test_fake_transcriber_replays_fixture() -> None:
    """FakeTranscriber returns TranscriptSegment list from fixture JSON."""
    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("AYfx-btc-dec08")

    assert len(segments) > 0
    for seg in segments:
        assert isinstance(seg, TranscriptSegment)
        assert isinstance(seg.start_seconds, float)
        assert isinstance(seg.end_seconds, float)
        assert isinstance(seg.text, str)
        assert seg.end_seconds >= seg.start_seconds


def test_fake_transcriber_audio_prefix_stripped() -> None:
    """FakeTranscriber strips 'audio://' prefix from audio_pointer."""
    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("audio://AYfx-btc-dec08")
    assert len(segments) > 0


def test_fake_transcriber_missing_fixture_raises() -> None:
    """FakeTranscriber raises FileNotFoundError for unknown video IDs."""
    transcriber = FakeTranscriber(FIXTURES)
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe("does-not-exist-video-id")
