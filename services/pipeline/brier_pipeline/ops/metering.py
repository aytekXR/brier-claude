"""Cost-metering wrappers that enforce NFR-5 hard monthly spend caps at call sites.

Every metered LLM completion and every metered transcription call passes through
guard_and_record_spend BEFORE the underlying work is performed.  If the monthly
cap is exceeded the inner callable is NEVER called (the spend is blocked at the
seam, not just logged after the fact).

PRD §18 cost reference:
    LLM:           Haiku-class (<$300/mo at 50 analysts).
    Transcription: Deepgram/Groq incremental (~$130/wk via API).

Rate constants are named module-level so they can be found and updated together.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from brier_pipeline.extraction import llm as llm_module
from brier_pipeline.extraction.extractor import LlmExtractor
from brier_pipeline.ops.alerts import Alerter
from brier_pipeline.ops.spend import guard_and_record_spend
from brier_pipeline.transcription.transcriber import Transcriber, TranscriptSegment

# ---------------------------------------------------------------------------
# Rate constants (PRD §18 — update here when provider pricing changes)
# ---------------------------------------------------------------------------

# Claude Haiku-class: ~$0.25 per 1M output tokens (as of 2025-Q4).
# We use max_tokens as the per-call ceiling estimate (conservative, simple).
# $0.25 / 1_000_000 tokens = $0.00000025 per token.
_LLM_RATE_USD_PER_TOKEN = 0.00000025  # PRD §18: Haiku-class LLM cost estimate

# Deepgram Nova-2 base rate: $0.0043 per minute of audio (as of 2025-Q4).
# PRD §18: "Deepgram or Groq API for incremental (~$130/wk via API)".
_TRANSCRIPTION_RATE_USD_PER_MINUTE = 0.0043  # PRD §18: Deepgram-class transcription cost estimate

# Default audio duration used when actual audio_seconds is unknown (conservative 15 min).
_DEFAULT_AUDIO_SECONDS = 900.0


def estimate_llm_cost_usd(*, max_tokens: int) -> float:
    """Deterministic per-call LLM cost estimate (Haiku-class, PRD §18).

    Uses max_tokens as the ceiling — a conservative upper-bound estimate that
    avoids any network round-trip.  The actual completion may use fewer tokens;
    this approach errs on the side of over-counting spend, which is preferable
    to under-counting when enforcing hard caps.

    Args:
        max_tokens: The max_tokens parameter passed to the completion call.

    Returns:
        Estimated cost in USD.
    """
    return _LLM_RATE_USD_PER_TOKEN * max_tokens


def estimate_transcription_cost_usd(*, audio_seconds: float | None = None) -> float:
    """Deterministic per-call transcription cost estimate (Deepgram-class, PRD §18).

    Args:
        audio_seconds: Duration of the audio in seconds.  When None, a
            conservative default of 15 minutes (_DEFAULT_AUDIO_SECONDS) is used
            so the cap guard always fires on the safe side.

    Returns:
        Estimated cost in USD.
    """
    seconds = audio_seconds if audio_seconds is not None else _DEFAULT_AUDIO_SECONDS
    minutes = seconds / 60.0
    return _TRANSCRIPTION_RATE_USD_PER_MINUTE * minutes


class MeteredCompletion:
    """Drop-in wrapper for LlmExtractor's completion param that enforces the LLM cap.

    Calls guard_and_record_spend BEFORE delegating to inner_completion.
    If the monthly cap is exceeded, SpendCapExceeded is raised and the
    inner completion is NEVER called (call-site enforcement, not post-hoc logging).

    The signature matches the completion(model, messages, *, system, max_tokens)->dict
    interface expected by LlmExtractor.
    """

    def __init__(
        self,
        inner_completion: Callable[..., dict[str, Any]],
        *,
        conn: Any,
        alerter: Alerter | None = None,
        cost_estimator: Callable[..., float] = estimate_llm_cost_usd,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialise the metered completion wrapper.

        Args:
            inner_completion: The real completion callable (e.g. llm.completion).
            conn:             psycopg connection; caller owns the transaction.
            alerter:          Optional Alerter for dispatch; None -> DB-only alert row.
            cost_estimator:   Callable(max_tokens=int)->float; injectable for tests.
            now_provider:     Callable()->datetime for the billing-period clock;
                              defaults to datetime.now(UTC).
        """
        self._inner = inner_completion
        self._conn = conn
        self._alerter = alerter
        self._cost_estimator = cost_estimator
        self._now_provider = now_provider if now_provider is not None else lambda: datetime.now(UTC)

    def __call__(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """Check spend cap, record cost, then delegate to inner completion.

        Raises:
            SpendCapExceeded: When the monthly LLM cap would be exceeded.
                              The inner completion is NOT called in this case.
        """
        cost = self._cost_estimator(max_tokens=max_tokens)
        now = self._now_provider()
        # guard_and_record_spend raises SpendCapExceeded when the cap is exceeded,
        # propagating upward WITHOUT calling the inner completion.
        guard_and_record_spend(
            self._conn,
            category="llm",
            amount_usd=cost,
            now=now,
            alerter=self._alerter,
        )
        return self._inner(model, messages, system=system, max_tokens=max_tokens)


class MeteredTranscriber(Transcriber):
    """Transcriber wrapper that enforces the transcription monthly cap.

    Calls guard_and_record_spend BEFORE delegating to inner.transcribe.
    If the monthly cap is exceeded, SpendCapExceeded is raised and the
    inner transcriber is NEVER called (call-site enforcement).
    """

    def __init__(
        self,
        inner: Transcriber,
        *,
        conn: Any,
        alerter: Alerter | None = None,
        cost_estimator: Callable[..., float] = estimate_transcription_cost_usd,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialise the metered transcriber wrapper.

        Args:
            inner:          The real Transcriber implementation.
            conn:           psycopg connection; caller owns the transaction.
            alerter:        Optional Alerter; None -> DB-only alert row.
            cost_estimator: Callable(audio_seconds=float|None)->float; injectable.
            now_provider:   Callable()->datetime; defaults to datetime.now(UTC).
        """
        self._inner = inner
        self._conn = conn
        self._alerter = alerter
        self._cost_estimator = cost_estimator
        self._now_provider = now_provider if now_provider is not None else lambda: datetime.now(UTC)

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        """Check spend cap, record cost, then delegate to inner.transcribe.

        Raises:
            SpendCapExceeded: When the monthly transcription cap would be exceeded.
                              The inner transcriber is NOT called in this case.
        """
        cost = self._cost_estimator()
        now = self._now_provider()
        guard_and_record_spend(
            self._conn,
            category="transcription",
            amount_usd=cost,
            now=now,
            alerter=self._alerter,
        )
        return self._inner.transcribe(audio_pointer)


def build_metered_extractor(
    model_version: str,
    prompt_version: str,
    *,
    conn: Any,
    alerter: Alerter | None = None,
) -> LlmExtractor:
    """Return an LlmExtractor wired through MeteredCompletion.

    This is the live wiring that proves the LLM call site is metered:
    every completion call in LlmExtractor.detect_candidates and
    LlmExtractor.structure_claim will pass through guard_and_record_spend
    before hitting the Anthropic API.

    Args:
        model_version: Anthropic model identifier (e.g. 'claude-haiku-4-5').
        prompt_version: Prompt version string stamped on every extracted claim.
        conn:          psycopg connection; caller owns the transaction.
        alerter:       Optional Alerter for dispatch; None -> DB-only alert row.

    Returns:
        LlmExtractor with MeteredCompletion as its completion callable.
    """
    metered = MeteredCompletion(llm_module.completion, conn=conn, alerter=alerter)
    return LlmExtractor(model_version, prompt_version, completion=metered)


def build_metered_transcriber(
    inner: Transcriber,
    *,
    conn: Any,
    alerter: Alerter | None = None,
) -> MeteredTranscriber:
    """Return a MeteredTranscriber wrapping the given inner Transcriber.

    This is the live wiring for the transcription call site: every call to
    transcribe() will pass through guard_and_record_spend before the audio
    is sent to the transcription service.

    Args:
        inner:   Real Transcriber implementation (DeepgramTranscriber or
                 WhisperTranscriber for the live path; FakeTranscriber for tests).
        conn:    psycopg connection; caller owns the transaction.
        alerter: Optional Alerter; None -> DB-only alert row.

    Returns:
        MeteredTranscriber wrapping inner.
    """
    return MeteredTranscriber(inner, conn=conn, alerter=alerter)
