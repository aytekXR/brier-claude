"""Price data behind a small interface (mock-first convention).

Real sources: CoinGecko composite daily UTC closes for the top 100 assets
(FR-301), cross-checked via CCXT for outage detection (EC-8). The fake replays
fixture closes from data/fixtures/prices/ (arrives with E1-T1).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

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
            ]
        return self._cache[asset]

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        """Return daily closes for asset in [start, end] inclusive."""
        return [p for p in self._load(asset) if start <= p.day <= end]


class CoinGeckoPriceSource(PriceSource):
    """Published composite source for the top 100 assets. Not used until E4."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        # TASK: E4-T2 (collector job + cross-check, EC-8 gap flagging)
        raise NotImplementedError
