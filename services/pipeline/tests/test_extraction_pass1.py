"""Tests for E3-T1: pass-1 candidate detection and the LLM completion seam.

No network calls, no real API keys. All LLM boundaries are injected fake
callables returning recorded fixture responses (mock-first convention).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from brier_pipeline.extraction import llm as llm_module
from brier_pipeline.extraction.extractor import (
    _BATCH_SIZE,
    CandidateSpan,
    FakeExtractor,
    LlmExtractor,
)
from brier_pipeline.transcription.transcriber import FakeTranscriber, TranscriptSegment

FIXTURES = Path(__file__).parent.parent.parent.parent / "data" / "fixtures"
LLM_FIXTURES = FIXTURES / "llm"

# ---------------------------------------------------------------------------
# Helpers: load recorded fixture responses
# ---------------------------------------------------------------------------


def _load_fixture(filename: str) -> dict[str, Any]:
    path = LLM_FIXTURES / filename
    return dict[str, Any](json.loads(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# LlmExtractor.detect_candidates — batching + offset mapping
# ---------------------------------------------------------------------------


def test_detect_candidates_maps_offsets_correctly() -> None:
    """detect_candidates maps model-returned indices to correct start/end seconds."""
    batch0_fixture = _load_fixture("pass1_NCfx-btc-dec01.json")
    batch1_fixture = _load_fixture("pass1_NCfx-btc-dec01_batch1.json")

    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-dec01")

    # NCfx-btc-dec01 has 43 segments → 2 batches with BATCH_SIZE=40.
    assert len(segments) > _BATCH_SIZE, "fixture must exceed batch size to test batching"

    responses = [batch0_fixture, batch1_fixture]
    call_count = 0

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)

    # The fixture returns indices 9 and 23 from batch 0.
    # Batch 0 = segments[0:40]; index 9 = segments[9], index 23 = segments[23].
    assert len(candidates) == 2, f"Expected 2 candidates, got {len(candidates)}"

    # Segment at batch-0 index 9: start=145.0, end=152.0
    span_btc = candidates[0]
    assert span_btc.start_seconds == 145.0
    assert span_btc.end_seconds == 152.0
    assert "Bitcoin" in span_btc.text or "hundred thousand" in span_btc.text

    # Segment at batch-0 index 23: start=380.0, end=387.0
    span_eth = candidates[1]
    assert span_eth.start_seconds == 380.0
    assert span_eth.end_seconds == 387.0
    assert "Ethereum" in span_eth.text or "year-end" in span_eth.text


def test_detect_candidates_batching_call_count() -> None:
    """One completion call per batch, never one per segment (NFR-5)."""
    batch0_fixture = _load_fixture("pass1_NCfx-btc-dec01.json")
    batch1_fixture = _load_fixture("pass1_NCfx-btc-dec01_batch1.json")

    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-dec01")

    responses = [batch0_fixture, batch1_fixture]
    call_count = 0

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    extractor.detect_candidates(segments)

    n_segments = len(segments)
    expected_calls = (n_segments + _BATCH_SIZE - 1) // _BATCH_SIZE
    assert call_count == expected_calls, (
        f"Expected {expected_calls} completion call(s) for {n_segments} segments "
        f"(batch_size={_BATCH_SIZE}), got {call_count}"
    )
    # Crucially: call_count must be much less than n_segments
    assert call_count < n_segments, "Must not call completion once per segment"


def test_detect_candidates_returns_empty_on_no_predictions() -> None:
    """detect_candidates returns [] when the model finds no candidate spans."""
    empty_fixture: dict[str, Any] = {"content": [{"type": "text", "text": '{"candidates": []}'}]}

    segments = [
        TranscriptSegment(
            start_seconds=0.0,
            end_seconds=10.0,
            text="General market overview today.",
        ),
        TranscriptSegment(
            start_seconds=10.0,
            end_seconds=20.0,
            text="On-chain data is interesting this week.",
        ),
    ]

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return empty_fixture

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)
    assert candidates == []


def test_detect_candidates_single_batch_small_transcript() -> None:
    """A transcript with fewer than BATCH_SIZE segments triggers exactly one call."""
    fixture: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"candidates": [{"index": 1, "text": '
                    '"ETH closes above thirty-two hundred by December thirty-first."}]}'
                ),
            }
        ]
    }

    segments = [
        TranscriptSegment(
            start_seconds=0.0,
            end_seconds=10.0,
            text="Welcome to the weekly crypto market review.",
        ),
        TranscriptSegment(
            start_seconds=10.0,
            end_seconds=20.0,
            text="ETH closes above thirty-two hundred by December thirty-first.",
        ),
        TranscriptSegment(
            start_seconds=20.0,
            end_seconds=30.0,
            text="That concludes the analysis for this period.",
        ),
    ]

    call_count = 0

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return fixture

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)

    assert call_count == 1
    assert len(candidates) == 1
    assert candidates[0].start_seconds == 10.0
    assert candidates[0].end_seconds == 20.0
    assert "ETH" in candidates[0].text or "thirty-two hundred" in candidates[0].text


def test_detect_candidates_robust_to_out_of_range_index() -> None:
    """Out-of-range indices in the model response are silently skipped."""
    fixture: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": (
                    '{"candidates": [{"index": 0, "text": '
                    '"BTC closes above eighty thousand by end of July."}, '
                    '{"index": 99, "text": "phantom"}]}'
                ),
            }
        ]
    }

    segments = [
        TranscriptSegment(
            start_seconds=5.0,
            end_seconds=15.0,
            text="BTC closes above eighty thousand by end of July.",
        )
    ]

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return fixture

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)

    # Only the valid index-0 candidate is returned; index 99 is silently dropped.
    assert len(candidates) == 1
    assert candidates[0].start_seconds == 5.0


def test_detect_candidates_robust_to_malformed_json() -> None:
    """Malformed JSON response returns empty list rather than raising."""
    fixture: dict[str, Any] = {"content": [{"type": "text", "text": "not valid json at all {{"}]}

    segments = [
        TranscriptSegment(
            start_seconds=0.0,
            end_seconds=5.0,
            text="BTC reaches one hundred thousand by end of the year.",
        )
    ]

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return fixture

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)
    assert candidates == []


def test_llm_extractor_completion_injection_no_network() -> None:
    """Injected completion is called; confirms no network path is exercised."""
    network_called = False

    fixture: dict[str, Any] = {"content": [{"type": "text", "text": '{"candidates": []}'}]}

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return fixture

    def guard_urlopen(*args: Any, **kwargs: Any) -> Any:
        nonlocal network_called
        network_called = True
        raise AssertionError("Network must not be called in tests")

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )

    with patch.object(urllib.request, "urlopen", guard_urlopen):
        extractor.detect_candidates(
            [
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=5.0,
                    text="Market commentary only.",
                )
            ]
        )

    assert not network_called


# ---------------------------------------------------------------------------
# llm.completion — key-check and request construction (no network)
# ---------------------------------------------------------------------------


def test_llm_completion_raises_runtime_error_when_key_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """completion() raises RuntimeError mentioning BRIER_ANTHROPIC_API_KEY when key absent."""
    monkeypatch.delenv("BRIER_ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        llm_module.completion("claude-haiku-4-5", [{"role": "user", "content": "test"}])

    msg = str(exc_info.value)
    assert "BRIER_ANTHROPIC_API_KEY" in msg
    assert "ADR-0005" in msg or "0005" in msg


def test_llm_completion_request_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """completion() builds the correct Anthropic request without hitting the network."""
    monkeypatch.setenv("BRIER_ANTHROPIC_API_KEY", "test-key-fixture")

    captured_requests: list[urllib.request.Request] = []
    canned_response_body = json.dumps(
        {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "test response"}],
            "model": "claude-haiku-4-5",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    ).encode("utf-8")

    class _FakeResponse:
        def read(self) -> bytes:
            return canned_response_body

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def fake_urlopen(req: urllib.request.Request, **kwargs: Any) -> _FakeResponse:
        captured_requests.append(req)
        return _FakeResponse()

    with patch.object(urllib.request, "urlopen", fake_urlopen):
        result = llm_module.completion(
            "claude-haiku-4-5",
            [{"role": "user", "content": "Test message"}],
            system="System prompt here",
            max_tokens=256,
        )

    assert len(captured_requests) == 1
    req = captured_requests[0]

    # Verify URL and method
    assert req.full_url == "https://api.anthropic.com/v1/messages"
    assert req.method == "POST"

    # Verify required headers
    assert req.get_header("X-api-key") == "test-key-fixture"
    assert req.get_header("Anthropic-version") == "2023-06-01"
    assert req.get_header("Content-type") == "application/json"

    # Verify body structure
    assert req.data is not None
    body = json.loads(req.data)
    assert body["model"] == "claude-haiku-4-5"
    assert body["max_tokens"] == 256
    assert body["system"] == "System prompt here"
    assert body["messages"] == [{"role": "user", "content": "Test message"}]

    # Verify parsed response
    assert isinstance(result, dict)
    assert result["id"] == "msg_test"


def test_llm_completion_omits_system_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """When system=None, the 'system' key is absent from the request body."""
    monkeypatch.setenv("BRIER_ANTHROPIC_API_KEY", "test-key-fixture")

    captured_body: list[dict[str, Any]] = []
    canned = json.dumps(
        {
            "content": [{"type": "text", "text": "ok"}],
            "model": "claude-haiku-4-5",
        }
    ).encode("utf-8")

    class _FakeResp:
        def read(self) -> bytes:
            return canned

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def fake_urlopen(req: urllib.request.Request, **kwargs: Any) -> _FakeResp:
        assert req.data is not None
        captured_body.append(json.loads(req.data))
        return _FakeResp()

    with patch.object(urllib.request, "urlopen", fake_urlopen):
        llm_module.completion("claude-haiku-4-5", [{"role": "user", "content": "hi"}])

    assert "system" not in captured_body[0]


# ---------------------------------------------------------------------------
# FakeExtractor regression — ensure pass-1 still works on fixture transcript
# ---------------------------------------------------------------------------


def test_fake_extractor_detect_candidates_regression() -> None:
    """FakeExtractor.detect_candidates still works on the NCfx-btc-dec01 fixture."""
    extractor = FakeExtractor(FIXTURES)
    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-dec01")

    candidates = extractor.detect_candidates(segments)

    # NCfx-btc-dec01 has exactly 3 fixture claims (nc-01, nc-02, nc-03).
    assert len(candidates) == 3, f"Expected exactly 3 candidates, got {len(candidates)}"

    texts = {c.text for c in candidates}
    assert any("Bitcoin" in t or "hundred thousand" in t for t in texts), (
        "Expected a BTC prediction span in candidates"
    )
    assert any("Ethereum" in t or "year-end" in t for t in texts), (
        "Expected an ETH prediction span in candidates"
    )


def test_fake_extractor_detect_candidates_returns_candidate_spans() -> None:
    """FakeExtractor returns CandidateSpan objects with valid offsets."""
    extractor = FakeExtractor(FIXTURES)
    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-dec01")

    candidates = extractor.detect_candidates(segments)
    for span in candidates:
        assert isinstance(span, CandidateSpan)
        assert isinstance(span.start_seconds, float)
        assert isinstance(span.end_seconds, float)
        assert span.end_seconds >= span.start_seconds
        assert isinstance(span.text, str)
        assert len(span.text) > 0


# ---------------------------------------------------------------------------
# Robustness: non-object JSON response
# ---------------------------------------------------------------------------


def test_detect_candidates_robust_to_nonobject_json() -> None:
    """detect_candidates returns [] when the model returns a valid JSON array, not an object."""
    # A bare JSON array is valid JSON but not a dict; must not crash with AttributeError.
    fixture: dict[str, Any] = {"content": [{"type": "text", "text": "[]"}]}

    segments = [
        TranscriptSegment(
            start_seconds=0.0,
            end_seconds=10.0,
            text="BTC reaches one hundred thousand by year-end.",
        )
    ]

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        return fixture

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)
    assert candidates == []


# ---------------------------------------------------------------------------
# Cross-batch offset mapping: batch-relative index maps to correct absolute segment
# ---------------------------------------------------------------------------


def test_detect_candidates_cross_batch_offset_mapping() -> None:
    """Batch-relative index in batch 1 maps to the correct absolute segment."""
    # Build 45 synthetic segments so we get 2 batches: [0:40] and [40:45].
    segments = [
        TranscriptSegment(
            start_seconds=float(i * 10),
            end_seconds=float(i * 10 + 9),
            text=f"Segment {i} commentary text.",
        )
        for i in range(45)
    ]

    # Batch 1 is segments[40:45].  Batch-relative index 2 → absolute segments[42].
    target_seg = segments[42]
    assert target_seg.start_seconds == 420.0
    assert target_seg.end_seconds == 429.0

    batch0_response: dict[str, Any] = {"content": [{"type": "text", "text": '{"candidates": []}'}]}
    batch1_response: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": '{"candidates": [{"index": 2, "text": "Segment 42 commentary text."}]}',
            }
        ]
    }

    responses = [batch0_response, batch1_response]
    call_count = 0

    def fake_completion(
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        nonlocal call_count
        result = responses[call_count]
        call_count += 1
        return result

    extractor = LlmExtractor(
        model_version="claude-haiku-4-5",
        prompt_version="v1",
        completion=fake_completion,
    )
    candidates = extractor.detect_candidates(segments)

    assert len(candidates) == 1, f"Expected 1 candidate from batch 1, got {len(candidates)}"
    span = candidates[0]
    # The span must reflect the absolute segment values, not batch-relative values.
    assert span.start_seconds == target_seg.start_seconds, (
        f"start_seconds {span.start_seconds} != {target_seg.start_seconds}"
    )
    assert span.end_seconds == target_seg.end_seconds, (
        f"end_seconds {span.end_seconds} != {target_seg.end_seconds}"
    )
    assert span.text == target_seg.text, f"text {span.text!r} != {target_seg.text!r}"
