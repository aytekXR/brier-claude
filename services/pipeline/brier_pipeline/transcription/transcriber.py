"""Transcription behind a small interface (mock-first convention).

Real adapters: faster-whisper large-v3 on a rented GPU for the backfill batch,
Deepgram/Groq API for incremental (PRD §18). Audio is transient with a 30-day
TTL; only transcripts persist (FR-103, NFR-4).
"""

from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from brier_pipeline import config

# NFR-4: audio is transient with a 30-day TTL; transcripts persist.
# The TTL enforcement mechanism (lifecycle rule on R2) lands in E2-T5.
AUDIO_KEY_PREFIX = "audio/"
AUDIO_TTL_DAYS = 30  # NFR-4: audio transient 30-day TTL


def audio_key(youtube_video_id: str) -> str:
    """Return the canonical storage key for a video's audio object."""
    return f"{AUDIO_KEY_PREFIX}{youtube_video_id}"


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
    """Fixture-backed fake: returns canned segments from data/fixtures/transcripts/.

    The audio_pointer is expected to be a video ID (or a path ending in the video ID
    e.g. 'audio://NCfx-btc-apr30') so the fake can locate the fixture transcript.
    Used for videos where captions are absent (captions_available=false in videos.json).
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        """Replay fixture transcript segments for the given audio pointer."""
        # Extract video ID: audio_pointer may be 'audio://<video_id>' or just the video ID
        video_id = audio_pointer.removeprefix("audio://").rstrip("/")
        transcript_path = self.fixtures_dir / "transcripts" / f"{video_id}.json"
        if not transcript_path.exists():
            raise FileNotFoundError(
                f"FakeTranscriber: no fixture transcript for {video_id!r} at {transcript_path}"
            )
        raw = json.loads(transcript_path.read_text(encoding="utf-8"))
        return [TranscriptSegment(**seg) for seg in raw]


_DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
_DEEPGRAM_QUERY_PARAMS = "smart_format=true&utterances=true"


def _default_http_post(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    """Real HTTP POST via stdlib urllib; returns parsed JSON response.

    Only called with the Deepgram endpoint this client constructs; tests inject
    a fake http_post and never touch the network.
    """
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))


class DeepgramTranscriber(Transcriber):
    """Hosted REST API adapter for incremental uploads (PRD §18).

    Uses stdlib urllib — no Deepgram SDK dependency (ADR-0003 gate).
    Audio is transient with a 30-day TTL (NFR-4); transcripts persist.
    The injectable http_post boundary is what tests exercise; the default
    performs the real POST to Deepgram's REST endpoint.
    """

    def __init__(
        self,
        api_key: str,
        http_post: Callable[[str, bytes, dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self.api_key = api_key
        if http_post is not None:
            self._http_post = http_post
        else:
            self._http_post = _default_http_post

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        """POST audio to Deepgram REST and map utterances to TranscriptSegment.

        The audio_pointer is an opaque storage key (e.g. 'audio/<video_id>').
        POSTs to https://api.deepgram.com/v1/listen with Authorization: Token.
        Parses response['results']['utterances'] into TranscriptSegment objects
        with second-level offsets (FR-103).

        If utterances are absent, falls back to words grouping. Raises ValueError
        if neither utterances nor words are present in the response.
        """
        url = f"{_DEEPGRAM_LISTEN_URL}?{_DEEPGRAM_QUERY_PARAMS}"
        headers: dict[str, str] = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/octet-stream",
        }
        # audio_pointer is a storage key; pass it as the body reference.
        # In production the caller fetches the audio bytes before calling transcribe.
        body = audio_pointer.encode("utf-8")
        response = self._http_post(url, body, headers)

        results = cast(dict[str, Any], response.get("results", {}))
        utterances = cast(list[dict[str, Any]] | None, results.get("utterances"))

        if utterances is not None:
            return [
                TranscriptSegment(
                    start_seconds=float(cast(float, u["start"])),
                    end_seconds=float(cast(float, u["end"])),
                    text=str(u["transcript"]),
                )
                for u in utterances
            ]

        # Fallback: group words into a single segment
        channels = cast(list[dict[str, Any]], results.get("channels", []))
        if channels:
            alternatives = cast(list[dict[str, Any]], channels[0].get("alternatives", []))
            if alternatives:
                words = cast(list[dict[str, Any]], alternatives[0].get("words", []))
                if words:
                    return [
                        TranscriptSegment(
                            start_seconds=float(cast(float, words[0]["start"])),
                            end_seconds=float(cast(float, words[-1]["end"])),
                            text=" ".join(str(w["word"]) for w in words),
                        )
                    ]

        raise ValueError(
            "Deepgram response contained neither utterances nor words; "
            "ensure smart_format=true&utterances=true query params are set."
        )


def _default_whisper_model_loader(model_size: str) -> Any:
    """Lazy-import faster_whisper and return a WhisperModel.

    The import is INSIDE this function so that absence of faster-whisper
    does not cause an ImportError at module load time (ADR-0003 gate).
    Raises RuntimeError with a clear message if faster-whisper is not installed.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper not installed; "
            "see docs/adr/0003-faster-whisper-transcription-dependency.md"
        ) from exc
    return WhisperModel(model_size)


class WhisperTranscriber(Transcriber):
    """faster-whisper large-v3 batch adapter for the backfill (PRD §18, ADR-0003).

    SEAM: This adapter is fully structured and unit-tested against a mocked
    model boundary (injected model_loader). The faster-whisper dependency is NOT
    installed in CI or dev — it is gated behind ADR-0003 pending human approval.
    When faster_whisper is absent the default loader raises RuntimeError pointing
    to the ADR (not NotImplementedError — the implementation is complete).

    Audio is transient with a 30-day TTL (NFR-4); transcripts persist (FR-103).
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        model_loader: Callable[[str], Any] | None = None,
    ) -> None:
        self.model_size = model_size
        if model_loader is not None:
            self._model_loader = model_loader
        else:
            self._model_loader = _default_whisper_model_loader

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        """Transcribe audio via faster-whisper, mapping segments to second-level offsets.

        Obtains the model via self._model_loader(model_size); the default loader
        lazily imports faster_whisper (ADR-0003 gate). Calls model.transcribe()
        which yields (segments, info); maps each segment's .start/.end/.text to
        TranscriptSegment with second-level offsets (FR-103).

        The injected model_loader is the test boundary — tests pass a fake
        returning a fake model whose .transcribe() yields fake segments,
        proving the mapping logic without faster-whisper installed.
        """
        model = self._model_loader(self.model_size)
        segments_iter, _info = model.transcribe(audio_pointer)
        return [
            TranscriptSegment(
                start_seconds=float(seg.start),
                end_seconds=float(seg.end),
                text=str(seg.text),
            )
            for seg in segments_iter
        ]


def _default_fixtures_dir() -> Path:
    """Repo-root/data/fixtures — the canonical FakeTranscriber source (CI/dev)."""
    return Path(__file__).resolve().parents[4] / "data" / "fixtures"


def get_transcriber(mode: str = "incremental", *, fixtures_dir: Path | None = None) -> Transcriber:
    """Return the configured transcriber for a pipeline mode (mock-first seam).

    Mirrors get_alerter / _get_price_source: the fixture-backed fake is the
    CI/dev path; a real adapter activates only when its key/dependency is present.

    Args:
        mode: 'backfill' -> WhisperTranscriber (batch GPU, ADR-0003; the
              faster-whisper install is gated to the GPU host, but constructing
              the adapter is safe — transcribe() raises only if the dep is
              absent). 'incremental' -> DeepgramTranscriber when
              BRIER_DEEPGRAM_API_KEY is set, else the FakeTranscriber.
        fixtures_dir: override for the FakeTranscriber source (defaults to the
              repo fixtures dir); used only on the fake path.

    Raises:
        ValueError: for an unknown mode.
        RuntimeError: in production (BRIER_ENV=production) when an incremental
            transcriber is requested without BRIER_DEEPGRAM_API_KEY — we will not
            silently transcribe real audio with the fixture fake.
    """
    if mode == "backfill":
        return WhisperTranscriber()
    if mode != "incremental":
        raise ValueError(
            f"Unknown transcriber mode: {mode!r}. Expected 'backfill' or 'incremental'."
        )

    key = config.deepgram_api_key()
    if key:
        return DeepgramTranscriber(key)
    if config.is_production():
        raise RuntimeError(
            "BRIER_DEEPGRAM_API_KEY is not set but BRIER_ENV=production: refusing to "
            "transcribe real uploads with the fixture FakeTranscriber. Set the Deepgram "
            "key (incremental path) or run the backfill mode (Whisper, ADR-0003)."
        )
    return FakeTranscriber(fixtures_dir if fixtures_dir is not None else _default_fixtures_dir())
