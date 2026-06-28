"""Pin the extraction model to a Haiku-class id (E3-T1, ADR-0005).

LlmExtractor takes the model id as a constructor arg (extractor.py); config
.extraction_model() is the single source of truth the gated `extract` handler
will inject. This guards against silent drift to a non-Haiku / more expensive
model and confirms the env override works.
"""

from __future__ import annotations

import pytest

from brier_pipeline import config


def test_default_extraction_model_is_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIER_EXTRACTION_MODEL", raising=False)
    assert config.extraction_model().startswith("claude-haiku"), (
        "extraction must default to a Haiku-class model (cheap pass-1/pass-2, E3-T1)"
    )


def test_extraction_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIER_EXTRACTION_MODEL", "claude-haiku-4-5")
    assert config.extraction_model() == "claude-haiku-4-5"
