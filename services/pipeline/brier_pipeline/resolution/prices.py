"""Price data behind a small interface (mock-first convention).

Real sources: CoinGecko composite daily UTC closes for the top 100 assets
(FR-301), cross-checked via CCXT for outage detection (EC-8). The fake replays
fixture closes from data/fixtures/prices/ (arrives with E1-T1).

ADR-0009: CoinGecko accessed via stdlib urllib.request + json (no coingecko SDK,
no new package). The CCXT cross-check is an ADR-gated seam (ADR-0009): the real
adapter is behind a lazy import that raises RuntimeError when ccxt is absent;
the injected/mocked boundary is the test path.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, date
from pathlib import Path
from typing import Any

from brier_pipeline.models import PriceDaily


class PriceSource(ABC):
    @abstractmethod
    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        """Daily UTC closes for an asset over [start, end]."""


class FakePriceSource(PriceSource):
    """Fixture-backed fake: 18 months of BTC/ETH/SOL daily closes (E1-T1).

    Reads data/fixtures/prices/{asset}.json and filters to [start, end].
    Returns an empty list for unknown assets rather than raising, so callers
    can handle EC-8 (data gaps) gracefully.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir
        self._cache: dict[str, list[PriceDaily]] = {}

    def _load(self, asset: str) -> list[PriceDaily]:
        if asset not in self._cache:
            path = self.fixtures_dir / "prices" / f"{asset}.json"
            if not path.exists():
                return []
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._cache[asset] = [
                PriceDaily(
                    asset=str(r["asset"]),
                    day=date.fromisoformat(str(r["day"])),
                    close_usd=float(r["close_usd"]),
                    source=str(r["source"]),
                )
                for r in raw
                if "asset" in r and "day" in r and "close_usd" in r
            ]
        return self._cache[asset]

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        """Return daily closes for asset in [start, end] inclusive."""
        return [p for p in self._load(asset) if start <= p.day <= end]


# ---------------------------------------------------------------------------
# CoinGecko asset-id mapping for the top assets (FR-301)
# The CoinGecko /coins/{id}/market_chart endpoint uses lowercase full names.
# ---------------------------------------------------------------------------

_COINGECKO_ASSET_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "AVAX": "avalanche-2",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
}


def _default_http_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Real urllib HTTP GET, returns parsed JSON response body."""
    import urllib.request  # stdlib — no new dependency (ADR-0009)

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
    return dict(json.loads(body))


class CoinGeckoPriceSource(PriceSource):
    """CoinGecko composite daily UTC closes.

    Implements the published composite source (FR-301, ADR-0009) using only
    stdlib urllib.request + json — no coingecko SDK, no new dependency.

    The http_get callable is injected for testing: tests supply a recorded
    response fixture and never reach the network. The default implementation
    raises RuntimeError if the API key is absent (BRIER_COINGECKO_API_KEY),
    which is the expected CI behaviour — tests never reach that path.

    See docs/adr/0009-base-rates-from-trailing-history.md.
    """

    _COINGECKO_BASE = "https://api.coingecko.com/api/v3"

    def __init__(
        self,
        api_key: str | None = None,
        http_get: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        from brier_pipeline import config

        self.api_key = api_key or config.coingecko_api_key()
        self._http_get = http_get if http_get is not None else _default_http_get

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        """Fetch daily UTC closes from CoinGecko /coins/{id}/market_chart/range.

        Uses the injected http_get callable (default = real urllib call, which
        requires BRIER_COINGECKO_API_KEY). Tests inject a recorded fixture.

        Raises RuntimeError when no API key is configured and no http_get is
        injected — the CI / no-network path should use FakePriceSource instead.
        """
        if not self.api_key and self._http_get is _default_http_get:
            raise RuntimeError(
                "CoinGecko API key not configured (BRIER_COINGECKO_API_KEY). "
                "Either set the environment variable or inject an http_get fixture. "
                "See docs/adr/0009-base-rates-from-trailing-history.md."
            )

        coin_id = _COINGECKO_ASSET_ID.get(asset.upper())
        if coin_id is None:
            return []  # unknown asset — caller handles EC-8 gap

        import calendar as _cal
        import datetime as _dt

        # CoinGecko expects UNIX epoch in UTC. calendar.timegm interprets the
        # timetuple as UTC (time.mktime would use the host's local timezone and
        # silently shift the query window on a non-UTC server).
        start_ts = int(_cal.timegm(start.timetuple()))
        end_ts = int(_cal.timegm(end.timetuple())) + 86400  # include end day

        url = (
            f"{self._COINGECKO_BASE}/coins/{coin_id}/market_chart/range"
            f"?vs_currency=usd&from={start_ts}&to={end_ts}"
        )
        headers: dict[str, str] = {"x-cg-demo-api-key": self.api_key or ""}

        response = self._http_get(url, headers)

        prices_raw = response.get("prices", [])
        closes: list[PriceDaily] = []

        # CoinGecko returns [[timestamp_ms, price], ...].  Each entry is the
        # daily close price.  Convert to date and filter to [start, end].
        for entry in prices_raw:
            ts_ms = float(entry[0])
            close_price = float(entry[1])
            day = _dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).date()
            if start <= day <= end:
                closes.append(
                    PriceDaily(
                        asset=asset.upper(),
                        day=day,
                        close_usd=close_price,
                        source="coingecko",
                    )
                )

        return closes


# ---------------------------------------------------------------------------
# CCXT cross-check seam (ADR-gated heavy dependency, option b)
#
# CCXT is a heavy new dependency (large package, many exchanges). Per the
# ADR-gate convention (CLAUDE.md "Boring stack, locked"), it is NOT added to
# pyproject.toml. Instead, the cross-check adapter is structured as a seam:
#
#   - The real call site uses a lazy `import ccxt` inside the method body.
#   - When ccxt is absent, it raises RuntimeError referencing ADR-0009.
#   - The injected/mocked boundary is the test path.
#   - A [[tool.mypy.overrides]] stanza in pyproject.toml suppresses the
#     missing-import error (same pattern as faster_whisper / sentence_transformers).
#
# This cross-check is for EC-8 outage/divergence detection. It is NOT part of
# the base-rate computation (that uses CoinGeckoPriceSource / FakePriceSource).
# ---------------------------------------------------------------------------


class CcxtCrossCheckSource(PriceSource):
    """CCXT-backed cross-check source for EC-8 outage/divergence detection.

    The real ccxt package is an ADR-gated optional dependency. When ccxt is
    not installed, every call raises RuntimeError referencing the ADR. The
    injected exchange_factory is the test path (no live exchange, no network).

    See the CCXT seam note in resolution/prices.py and pyproject.toml
    [[tool.mypy.overrides]] for the ccxt module suppression.
    """

    def __init__(
        self,
        exchange_name: str = "binance",
        exchange_factory: Any = None,
    ) -> None:
        self.exchange_name = exchange_name
        self._exchange_factory = exchange_factory

    def _get_exchange(self) -> Any:
        if self._exchange_factory is not None:
            return self._exchange_factory(self.exchange_name)
        # Lazy import — only on hosts where ccxt is installed (ADR-gated).
        try:
            import ccxt  # ADR-gated; missing-import suppressed via pyproject.toml overrides
        except ImportError as exc:
            raise RuntimeError(
                "ccxt is not installed. The CCXT cross-check adapter is an "
                "ADR-gated dependency (see docs/adr/ and pyproject.toml). "
                "Use FakePriceSource or CoinGeckoPriceSource for CI/testing."
            ) from exc
        exchange_class = getattr(ccxt, self.exchange_name)
        return exchange_class()

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        """Fetch daily OHLCV closes from the configured CCXT exchange.

        Raises RuntimeError when ccxt is absent and no exchange_factory injected.
        """
        exchange = self._get_exchange()

        import datetime as _dt

        symbol = f"{asset.upper()}/USDT"
        start_ts = int(_dt.datetime.combine(start, _dt.time.min, tzinfo=UTC).timestamp() * 1000)

        # fetch_ohlcv returns [[timestamp_ms, open, high, low, close, volume], ...]
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", since=start_ts, limit=1000)

        closes: list[PriceDaily] = []
        for candle in ohlcv:
            ts_ms = float(candle[0])
            close_price = float(candle[4])
            day = _dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).date()
            if start <= day <= end:
                closes.append(
                    PriceDaily(
                        asset=asset.upper(),
                        day=day,
                        close_usd=close_price,
                        source=f"ccxt-{self.exchange_name}",
                    )
                )

        return closes
