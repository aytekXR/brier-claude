"""A2#1: production price-source guard for the scheduled-ops handlers.

_get_price_source() is the mock-first seam shared by resolve_claims +
score_analysts. The fixture-backed FakePriceSource is the CI/dev path; the real
CoinGeckoPriceSource activates only when BRIER_COINGECKO_API_KEY is set. The
guard under test: in production (BRIER_ENV=production) a missing key must RAISE
rather than silently score real analysts against the 18-month fixture prices.
"""

from __future__ import annotations

import pytest

from brier_pipeline.jobs import handlers
from brier_pipeline.resolution.prices import CoinGeckoPriceSource, FakePriceSource


def test_returns_fake_in_dev_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRIER_COINGECKO_API_KEY", raising=False)
    monkeypatch.delenv("BRIER_ENV", raising=False)
    assert isinstance(handlers._get_price_source(), FakePriceSource)


def test_returns_coingecko_when_keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIER_COINGECKO_API_KEY", "cg-test")
    monkeypatch.delenv("BRIER_ENV", raising=False)
    assert isinstance(handlers._get_price_source(), CoinGeckoPriceSource)


def test_raises_in_production_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIER_ENV", "production")
    monkeypatch.delenv("BRIER_COINGECKO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="BRIER_COINGECKO_API_KEY"):
        handlers._get_price_source()


def test_returns_coingecko_in_production_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRIER_ENV", "production")
    monkeypatch.setenv("BRIER_COINGECKO_API_KEY", "cg-test")
    assert isinstance(handlers._get_price_source(), CoinGeckoPriceSource)
