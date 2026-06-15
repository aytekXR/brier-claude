"""E6-T4: Non-vacuous call-site enforcement tests for cost guardrails.

Proves that MeteredCompletion and MeteredTranscriber enforce the monthly spend
cap AT THE CALL SITE: when the cap is exceeded the inner callable is NEVER
invoked.  Spy call counts are the non-vacuous proof.

Three-way proof per metered type:
  1. Under cap   — inner called once; spend row recorded; no alert.
  2. Crossing 70% — inner still called; exactly one cost_threshold alert.
  3. Exceeding cap — inner NEVER called (call_count==0 asserted);
                     no NEW spend row beyond pre-seed; cost_cap alert present.

Caps are controlled deterministically via monkeypatch.setenv because
config reads the env at call time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from brier_pipeline.ops.alerts import FakeAlerter
from brier_pipeline.ops.metering import (
    MeteredCompletion,
    MeteredTranscriber,
    estimate_llm_cost_usd,
    estimate_transcription_cost_usd,
)
from brier_pipeline.ops.spend import SpendCapExceeded, month_to_date_spend, record_spend
from brier_pipeline.transcription.transcriber import FakeTranscriber, TranscriptSegment

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Far-future dates prevent cross-test interference with any real DB rows.
_LLM_NOW = datetime(2097, 1, 15, tzinfo=UTC)
_TXN_NOW = datetime(2097, 2, 15, tzinfo=UTC)

_LLM_CAP_ENV = "BRIER_LLM_MONTHLY_CAP_USD"
_TXN_CAP_ENV = "BRIER_TRANSCRIPTION_MONTHLY_CAP_USD"

# A fixed max_tokens value used for all LLM tests.
_MAX_TOKENS = 1024

# Cost for one call at _MAX_TOKENS.
_LLM_CALL_COST = estimate_llm_cost_usd(max_tokens=_MAX_TOKENS)

# Cost for one transcription call (no audio_seconds -> default).
_TXN_CALL_COST = estimate_transcription_cost_usd()


# ---------------------------------------------------------------------------
# Spy helpers
# ---------------------------------------------------------------------------


class _SpyCompletion:
    """Spy inner completion: records calls; returns a minimal valid response dict."""

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        self.call_count += 1
        self.calls.append({"model": model, "messages": messages, "system": system})
        return {"content": [{"type": "text", "text": "{}"}]}


class _SpyTranscriber:
    """Spy inner Transcriber: records calls; returns one dummy segment."""

    def __init__(self) -> None:
        self.call_count = 0
        self.calls: list[str] = []

    def transcribe(self, audio_pointer: str) -> list[TranscriptSegment]:
        self.call_count += 1
        self.calls.append(audio_pointer)
        return [TranscriptSegment(start_seconds=0.0, end_seconds=1.0, text="hello")]


# ---------------------------------------------------------------------------
# Deterministic cost: unit tests (no DB needed)
# ---------------------------------------------------------------------------


class TestCostEstimators:
    """Verify the rate constants produce non-zero, deterministic estimates."""

    def test_llm_cost_positive(self) -> None:
        cost = estimate_llm_cost_usd(max_tokens=1024)
        assert cost > 0.0

    def test_llm_cost_scales_with_max_tokens(self) -> None:
        cost_1k = estimate_llm_cost_usd(max_tokens=1000)
        cost_2k = estimate_llm_cost_usd(max_tokens=2000)
        assert cost_2k == pytest.approx(cost_1k * 2.0)

    def test_transcription_cost_positive(self) -> None:
        cost = estimate_transcription_cost_usd()
        assert cost > 0.0

    def test_transcription_cost_none_uses_default(self) -> None:
        cost_none = estimate_transcription_cost_usd(audio_seconds=None)
        cost_default = estimate_transcription_cost_usd(audio_seconds=900.0)
        assert cost_none == pytest.approx(cost_default)

    def test_transcription_cost_scales_with_duration(self) -> None:
        cost_1min = estimate_transcription_cost_usd(audio_seconds=60.0)
        cost_2min = estimate_transcription_cost_usd(audio_seconds=120.0)
        assert cost_2min == pytest.approx(cost_1min * 2.0)


# ---------------------------------------------------------------------------
# MeteredCompletion — three-way proof
# ---------------------------------------------------------------------------


class TestMeteredCompletionUnderCap:
    """Under cap: inner called once; spend row recorded; no alert."""

    def test_inner_called_exactly_once(self, db_conn: Any, monkeypatch: Any) -> None:
        # Cap is comfortably above one call's cost.
        monkeypatch.setenv(_LLM_CAP_ENV, "100.0")
        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        result = mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        assert spy.call_count == 1
        assert isinstance(result, dict)

    def test_spend_row_recorded(self, db_conn: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv(_LLM_CAP_ENV, "100.0")
        spy = _SpyCompletion()
        mc = MeteredCompletion(spy, conn=db_conn, now_provider=lambda: _LLM_NOW)
        mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        total = month_to_date_spend(db_conn, "llm", now=_LLM_NOW)
        assert total == pytest.approx(_LLM_CALL_COST)

    def test_no_alert_dispatched(self, db_conn: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv(_LLM_CAP_ENV, "100.0")
        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _LLM_NOW)
        mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        assert len(alerter.dispatched) == 0


class TestMeteredCompletionCrossing70Pct:
    """Crossing 70%: inner still called; exactly one cost_threshold alert."""

    def test_inner_called_after_threshold(self, db_conn: Any, monkeypatch: Any) -> None:
        # Use a tiny cap so that one call crosses 70%.
        # Cost of one call = _LLM_CALL_COST.  Set cap such that pre-seeded spend
        # is just below 70% and adding one call pushes it over.
        cap = _LLM_CALL_COST * 10.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        # Seed 65% of cap.
        pre_seed = cap * 0.65
        record_spend(db_conn, category="llm", amount_usd=pre_seed, now=_LLM_NOW)

        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        # This call crosses from 65% to 65%+10% = 75% (>70%) -> alert but succeeds.
        mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        assert spy.call_count == 1

    def test_exactly_one_cost_threshold_alert_dispatched(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        cap = _LLM_CALL_COST * 10.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        pre_seed = cap * 0.65
        record_spend(db_conn, category="llm", amount_usd=pre_seed, now=_LLM_NOW)

        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_threshold"

    def test_cost_threshold_alert_in_db(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _LLM_CALL_COST * 10.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        pre_seed = cap * 0.65
        record_spend(db_conn, category="llm", amount_usd=pre_seed, now=_LLM_NOW)

        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        period = _LLM_NOW.strftime("%Y-%m")
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind='cost_threshold' and dedup_key=%s",
                (f"cost_threshold:llm:{period}",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1


class TestMeteredCompletionExceedingCap:
    """Exceeding cap: inner NEVER called; no new spend row; cost_cap alert present."""

    def test_raises_spend_cap_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _LLM_CALL_COST * 5.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        # Seed at cap (100%).
        record_spend(db_conn, category="llm", amount_usd=cap, now=_LLM_NOW)

        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        with pytest.raises(SpendCapExceeded):
            mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

    def test_inner_never_called_when_cap_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        """Non-vacuous call-site enforcement proof: spy call_count is exactly 0."""
        cap = _LLM_CALL_COST * 5.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        record_spend(db_conn, category="llm", amount_usd=cap, now=_LLM_NOW)

        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        with pytest.raises(SpendCapExceeded):
            mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        # THE KEY ASSERTION: inner was never called.
        assert spy.call_count == 0

    def test_no_new_spend_row_when_cap_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _LLM_CALL_COST * 5.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        record_spend(db_conn, category="llm", amount_usd=cap, now=_LLM_NOW)

        spy = _SpyCompletion()
        mc = MeteredCompletion(spy, conn=db_conn, now_provider=lambda: _LLM_NOW)
        with pytest.raises(SpendCapExceeded):
            mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        # Spend stayed at the pre-seed amount; no new row was recorded.
        total = month_to_date_spend(db_conn, "llm", now=_LLM_NOW)
        assert total == pytest.approx(cap)

    def test_cost_cap_alert_present_in_db(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _LLM_CALL_COST * 5.0
        monkeypatch.setenv(_LLM_CAP_ENV, str(cap))
        record_spend(db_conn, category="llm", amount_usd=cap, now=_LLM_NOW)

        spy = _SpyCompletion()
        alerter = FakeAlerter()
        mc = MeteredCompletion(
            spy,
            conn=db_conn,
            alerter=alerter,
            now_provider=lambda: _LLM_NOW,
        )
        with pytest.raises(SpendCapExceeded):
            mc("model-v1", [{"role": "user", "content": "hello"}], max_tokens=_MAX_TOKENS)

        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_cap"
        assert alerter.dispatched[0].severity == "critical"

        period = _LLM_NOW.strftime("%Y-%m")
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind='cost_cap' and dedup_key=%s",
                (f"cost_cap:llm:{period}",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1


# ---------------------------------------------------------------------------
# MeteredTranscriber — three-way proof
# ---------------------------------------------------------------------------


class TestMeteredTranscriberUnderCap:
    """Under cap: inner called once; spend row recorded; no alert."""

    def test_inner_called_exactly_once(self, db_conn: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv(_TXN_CAP_ENV, "100.0")
        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        result = mt.transcribe("audio://test-video-under-cap")

        assert spy.call_count == 1
        assert len(result) == 1

    def test_spend_row_recorded(self, db_conn: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv(_TXN_CAP_ENV, "100.0")
        spy = _SpyTranscriber()
        mt = MeteredTranscriber(spy, conn=db_conn, now_provider=lambda: _TXN_NOW)
        mt.transcribe("audio://test-video-spend-record")

        total = month_to_date_spend(db_conn, "transcription", now=_TXN_NOW)
        assert total == pytest.approx(_TXN_CALL_COST)

    def test_no_alert_dispatched(self, db_conn: Any, monkeypatch: Any) -> None:
        monkeypatch.setenv(_TXN_CAP_ENV, "100.0")
        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        mt.transcribe("audio://test-video-no-alert")

        assert len(alerter.dispatched) == 0


class TestMeteredTranscriberCrossing70Pct:
    """Crossing 70%: inner still called; exactly one cost_threshold alert."""

    def test_inner_called_after_threshold(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _TXN_CALL_COST * 10.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        pre_seed = cap * 0.65
        record_spend(db_conn, category="transcription", amount_usd=pre_seed, now=_TXN_NOW)

        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        mt.transcribe("audio://test-video-crossing")

        assert spy.call_count == 1

    def test_exactly_one_cost_threshold_alert_dispatched(
        self, db_conn: Any, monkeypatch: Any
    ) -> None:
        cap = _TXN_CALL_COST * 10.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        pre_seed = cap * 0.65
        record_spend(db_conn, category="transcription", amount_usd=pre_seed, now=_TXN_NOW)

        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        mt.transcribe("audio://test-video-threshold-alert")

        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_threshold"

    def test_cost_threshold_alert_in_db(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _TXN_CALL_COST * 10.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        pre_seed = cap * 0.65
        record_spend(db_conn, category="transcription", amount_usd=pre_seed, now=_TXN_NOW)

        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        mt.transcribe("audio://test-video-threshold-db")

        period = _TXN_NOW.strftime("%Y-%m")
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind='cost_threshold' and dedup_key=%s",
                (f"cost_threshold:transcription:{period}",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1


class TestMeteredTranscriberExceedingCap:
    """Exceeding cap: inner NEVER called; no new spend row; cost_cap alert present."""

    def test_raises_spend_cap_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _TXN_CALL_COST * 5.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        record_spend(db_conn, category="transcription", amount_usd=cap, now=_TXN_NOW)

        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        with pytest.raises(SpendCapExceeded):
            mt.transcribe("audio://test-video-exceed-cap")

    def test_inner_never_called_when_cap_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        """Non-vacuous call-site enforcement proof: spy call_count is exactly 0."""
        cap = _TXN_CALL_COST * 5.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        record_spend(db_conn, category="transcription", amount_usd=cap, now=_TXN_NOW)

        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        with pytest.raises(SpendCapExceeded):
            mt.transcribe("audio://test-video-never-called")

        # THE KEY ASSERTION: inner was never called.
        assert spy.call_count == 0

    def test_no_new_spend_row_when_cap_exceeded(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _TXN_CALL_COST * 5.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        record_spend(db_conn, category="transcription", amount_usd=cap, now=_TXN_NOW)

        spy = _SpyTranscriber()
        mt = MeteredTranscriber(spy, conn=db_conn, now_provider=lambda: _TXN_NOW)
        with pytest.raises(SpendCapExceeded):
            mt.transcribe("audio://test-video-no-new-spend")

        total = month_to_date_spend(db_conn, "transcription", now=_TXN_NOW)
        assert total == pytest.approx(cap)

    def test_cost_cap_alert_present_in_db(self, db_conn: Any, monkeypatch: Any) -> None:
        cap = _TXN_CALL_COST * 5.0
        monkeypatch.setenv(_TXN_CAP_ENV, str(cap))
        record_spend(db_conn, category="transcription", amount_usd=cap, now=_TXN_NOW)

        spy = _SpyTranscriber()
        alerter = FakeAlerter()
        mt = MeteredTranscriber(spy, conn=db_conn, alerter=alerter, now_provider=lambda: _TXN_NOW)
        with pytest.raises(SpendCapExceeded):
            mt.transcribe("audio://test-video-cap-alert")

        assert len(alerter.dispatched) == 1
        assert alerter.dispatched[0].kind == "cost_cap"
        assert alerter.dispatched[0].severity == "critical"

        period = _TXN_NOW.strftime("%Y-%m")
        with db_conn.cursor() as cur:
            cur.execute(
                "select count(*) from alerts where kind='cost_cap' and dedup_key=%s",
                (f"cost_cap:transcription:{period}",),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1


# ---------------------------------------------------------------------------
# build_metered_extractor + build_metered_transcriber: wiring smoke tests
# (no DB call needed for the import/constructor checks)
# ---------------------------------------------------------------------------


class TestBuildMeteredWiring:
    """Verify the factory functions return the correct metered types."""

    def test_build_metered_extractor_returns_llm_extractor(self, db_conn: Any) -> None:
        from brier_pipeline.extraction.extractor import LlmExtractor
        from brier_pipeline.ops.metering import build_metered_extractor

        extractor = build_metered_extractor("claude-haiku-4-5", "v1", conn=db_conn)
        assert isinstance(extractor, LlmExtractor)

    def test_build_metered_extractor_completion_is_metered(self, db_conn: Any) -> None:
        from brier_pipeline.ops.metering import MeteredCompletion, build_metered_extractor

        extractor = build_metered_extractor("claude-haiku-4-5", "v1", conn=db_conn)
        assert isinstance(extractor._completion, MeteredCompletion)

    def test_build_metered_transcriber_returns_metered_transcriber(
        self, db_conn: Any, tmp_path: Any
    ) -> None:
        from brier_pipeline.ops.metering import MeteredTranscriber, build_metered_transcriber

        inner = FakeTranscriber(tmp_path)
        mt = build_metered_transcriber(inner, conn=db_conn)
        assert isinstance(mt, MeteredTranscriber)

    def test_build_metered_transcriber_inner_preserved(self, db_conn: Any, tmp_path: Any) -> None:
        from brier_pipeline.ops.metering import build_metered_transcriber

        inner = FakeTranscriber(tmp_path)
        mt = build_metered_transcriber(inner, conn=db_conn)
        assert mt._inner is inner
