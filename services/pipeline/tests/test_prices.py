"""E4-T2: tests for CoinGeckoPriceSource and CcxtCrossCheckSource seams.

All tests use injected recorded fixtures or recorded boundaries — no network,
no live API, no real credentials (CI contract).

Tests cover:
  - CoinGeckoPriceSource.daily_closes parses a RECORDED fixture via the injected
    http_get boundary (no network).
  - CoinGeckoPriceSource raises RuntimeError when no API key and no injected http_get.
  - CcxtCrossCheckSource.daily_closes works via injected exchange_factory (no ccxt).
  - CcxtCrossCheckSource raises RuntimeError when ccxt is absent and no factory injected.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.resolution.prices import CcxtCrossCheckSource, CoinGeckoPriceSource

# ---------------------------------------------------------------------------
# Path to the recorded CoinGecko fixture
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).resolve().parents[3] / "data" / "fixtures"
_COINGECKO_FIXTURE = _FIXTURES_DIR / "coingecko" / "btc_market_chart_range.json"


def _load_coingecko_fixture() -> dict[str, Any]:
    """Load the recorded CoinGecko market_chart_range fixture."""
    return dict(json.loads(_COINGECKO_FIXTURE.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# CoinGeckoPriceSource tests
# ---------------------------------------------------------------------------


class TestCoinGeckoPriceSourceParsing:
    """CoinGeckoPriceSource parses recorded fixture via injected http_get."""

    def _make_source(self) -> CoinGeckoPriceSource:
        """Return a CoinGeckoPriceSource with an injected recorded-fixture boundary."""
        fixture = _load_coingecko_fixture()

        def recorded_http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
            return fixture

        return CoinGeckoPriceSource(
            api_key="test-api-key-fictional",
            http_get=recorded_http_get,
        )

    def test_parses_recorded_fixture_returns_price_daily(self) -> None:
        """daily_closes returns a list of PriceDaily parsed from the recorded response."""
        src = self._make_source()
        closes = src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 15))
        assert len(closes) > 0, "Expected at least one PriceDaily from the recorded fixture"
        for p in closes:
            assert p.asset == "BTC"
            assert p.source == "coingecko"
            assert p.close_usd > 0.0
            assert isinstance(p.day, date)

    def test_filters_to_date_range(self) -> None:
        """Only closes within [start, end] inclusive are returned."""
        src = self._make_source()
        start = date(2024, 1, 2)
        end = date(2024, 1, 4)
        closes = src.daily_closes("BTC", start, end)
        for p in closes:
            assert start <= p.day <= end, (
                f"PriceDaily day {p.day} outside requested range [{start}, {end}]"
            )

    def test_injected_boundary_is_called(self) -> None:
        """The injected http_get callable is called exactly once per daily_closes call."""
        fixture = _load_coingecko_fixture()
        call_count = 0

        def counting_http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return fixture

        src = CoinGeckoPriceSource(
            api_key="test-api-key-fictional",
            http_get=counting_http_get,
        )
        src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 10))
        assert call_count == 1, f"Expected exactly 1 http_get call, got {call_count}"

    def test_unknown_asset_returns_empty(self) -> None:
        """An asset not in _COINGECKO_ASSET_ID returns an empty list (no network call)."""
        call_count = 0

        def should_not_be_called(url: str, headers: dict[str, str]) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {}

        src = CoinGeckoPriceSource(
            api_key="test-api-key-fictional",
            http_get=should_not_be_called,
        )
        result = src.daily_closes("FICTIONAL_COIN_XYZ", date(2024, 1, 1), date(2024, 1, 10))
        assert result == [], "Unknown asset should return empty list"
        assert call_count == 0, "No http_get call should occur for unknown asset"

    def test_empty_response_prices_returns_empty(self) -> None:
        """Response with empty prices list → empty result."""

        def empty_http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
            return {"prices": [], "market_caps": [], "total_volumes": []}

        src = CoinGeckoPriceSource(
            api_key="test-api-key-fictional",
            http_get=empty_http_get,
        )
        result = src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 10))
        assert result == []

    def test_headers_include_api_key(self) -> None:
        """The injected http_get receives the API key in the headers."""
        received_headers: dict[str, str] = {}

        def capturing_http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
            received_headers.update(headers)
            return {"prices": [], "market_caps": [], "total_volumes": []}

        src = CoinGeckoPriceSource(
            api_key="fictional-key-abc123",
            http_get=capturing_http_get,
        )
        src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 2))
        assert received_headers.get("x-cg-demo-api-key") == "fictional-key-abc123"


class TestCoinGeckoPriceSourceErrorHandling:
    """CoinGeckoPriceSource raises RuntimeError when no key and no injection."""

    def test_raises_runtime_error_without_key_or_injection(self) -> None:
        """No API key and no injected http_get (default) → RuntimeError referencing ADR."""
        import os

        # Ensure BRIER_COINGECKO_API_KEY is not set for this test.
        old_key = os.environ.get("BRIER_COINGECKO_API_KEY")
        try:
            if old_key is not None:
                del os.environ["BRIER_COINGECKO_API_KEY"]
            src = CoinGeckoPriceSource(api_key="")
            with pytest.raises(RuntimeError, match="BRIER_COINGECKO_API_KEY"):
                src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 10))
        finally:
            if old_key is not None:
                os.environ["BRIER_COINGECKO_API_KEY"] = old_key

    def test_injected_http_get_bypasses_key_requirement(self) -> None:
        """An injected http_get callable works even with an empty API key."""
        fixture = _load_coingecko_fixture()

        def recorded_http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
            return fixture

        src = CoinGeckoPriceSource(api_key="", http_get=recorded_http_get)
        # Should not raise — the injected boundary bypasses the key check.
        closes = src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 15))
        assert isinstance(closes, list)


# ---------------------------------------------------------------------------
# CcxtCrossCheckSource seam tests
# ---------------------------------------------------------------------------


class TestCcxtCrossCheckSourceSeam:
    """CcxtCrossCheckSource seam: injected factory works; absent ccxt raises RuntimeError."""

    def test_injected_exchange_factory_returns_closes(self) -> None:
        """daily_closes works correctly via injected exchange factory (no ccxt installed)."""
        # Build a fake exchange with recorded OHLCV data.
        # CoinGecko fixture dates → timestamps for the fake CCXT exchange.
        # The recorded data represents fictional BTC closes from early 2024.
        recorded_ohlcv = [
            # [ts_ms, open, high, low, close, volume]
            [1704067200000, 41000.0, 43000.0, 40500.0, 42500.0, 12000.0],
            [1704153600000, 42500.0, 44000.0, 42000.0, 43100.0, 13000.0],
            [1704240000000, 43100.0, 44500.0, 42800.0, 43800.0, 14000.0],
        ]

        class FakeExchange:
            def fetch_ohlcv(
                self,
                symbol: str,
                timeframe: str,
                since: int,
                limit: int,
            ) -> list[list[float]]:
                return recorded_ohlcv

        def fake_factory(exchange_name: str) -> FakeExchange:
            return FakeExchange()

        src = CcxtCrossCheckSource(
            exchange_name="binance",
            exchange_factory=fake_factory,
        )
        closes = src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 5))
        assert len(closes) == 3
        for p in closes:
            assert p.asset == "BTC"
            assert p.source == "ccxt-binance"
            assert p.close_usd > 0.0
            assert date(2024, 1, 1) <= p.day <= date(2024, 1, 5)

    def test_absent_ccxt_raises_runtime_error(self) -> None:
        """When ccxt is not installed and no factory is injected, raises RuntimeError."""
        src = CcxtCrossCheckSource(exchange_name="binance")
        # ccxt is not in the CI venv. The lazy import raises RuntimeError.
        with pytest.raises(RuntimeError, match="ccxt"):
            src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 5))

    def test_absent_ccxt_error_references_adr(self) -> None:
        """RuntimeError message mentions ADR and/or FakePriceSource for guidance."""
        src = CcxtCrossCheckSource(exchange_name="binance")
        with pytest.raises(RuntimeError) as exc_info:
            src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 5))
        msg = str(exc_info.value)
        # Must reference the dependency-gate concept (adr or docs/ reference)
        assert "ADR" in msg or "adr" in msg or "FakePriceSource" in msg, (
            f"RuntimeError should reference ADR or FakePriceSource for guidance: {msg}"
        )

    def test_injected_factory_date_filtering(self) -> None:
        """Only closes within the requested date range are returned."""
        # Include closes outside the requested range.
        recorded_ohlcv = [
            [1704067200000, 41000.0, 43000.0, 40500.0, 42500.0, 12000.0],  # 2024-01-01
            [1704153600000, 42500.0, 44000.0, 42000.0, 43100.0, 13000.0],  # 2024-01-02
            [1704844800000, 45000.0, 47000.0, 44500.0, 46000.0, 15000.0],  # 2024-01-10
        ]

        class FakeExchange:
            def fetch_ohlcv(
                self,
                symbol: str,
                timeframe: str,
                since: int,
                limit: int,
            ) -> list[list[float]]:
                return recorded_ohlcv

        def fake_factory(exchange_name: str) -> FakeExchange:
            return FakeExchange()

        src = CcxtCrossCheckSource(exchange_factory=fake_factory)
        closes = src.daily_closes("BTC", date(2024, 1, 1), date(2024, 1, 3))
        # Only the first two are within [2024-01-01, 2024-01-03]
        assert len(closes) == 2
        for p in closes:
            assert date(2024, 1, 1) <= p.day <= date(2024, 1, 3)
