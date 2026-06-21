"""Mock-first seam-activation contract for the alerter factory (launch-readiness,
2026-06-16).

The whole system must run green OFFLINE: `get_alerter()` returns its
fixture-backed fake unless a real credential is present, and returns the real
adapter (constructed, never dispatched) when the credential is set. This locks
the launch go/no-go item #2 ("CI stays mock-first; no key committed") — see
docs/LAUNCH-READINESS.md (the prompt archive lives in past-prompts.md) — for
the E6 alerting path: an accidental flip that made CI require a real token
would fail here.

The per-adapter "raise a clear ADR-referencing RuntimeError without the
dependency" contract for the heavier seams (faster-whisper, boto3/R2,
sentence-transformers) is already covered by test_transcription.py,
test_storage.py, and test_dedup.py respectively; this file only adds the
alerter-factory contract, which had no test. Pure unit tests — no DB, no
network — so they run everywhere, including the hermetic part of CI.
"""

from __future__ import annotations

import pytest

from brier_pipeline.ops.alerts import BetterStackAlerter, FakeAlerter, get_alerter


def test_get_alerter_returns_fake_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """No BRIER_BETTER_STACK_TOKEN -> the no-network FakeAlerter (CI/dev path)."""
    monkeypatch.delenv("BRIER_BETTER_STACK_TOKEN", raising=False)
    assert isinstance(get_alerter(), FakeAlerter)


def test_get_alerter_returns_real_adapter_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A token present -> the real BetterStackAlerter.

    Construction must not touch the network (dispatch is exercised elsewhere);
    simply selecting the real adapter is the contract under test here.
    """
    monkeypatch.setenv("BRIER_BETTER_STACK_TOKEN", "test-token-never-dispatched")
    assert isinstance(get_alerter(), BetterStackAlerter)
