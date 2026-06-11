"""Price data behind a small interface (mock-first convention).

Real sources: CoinGecko composite daily UTC closes for the top 100 assets
(FR-301), cross-checked via CCXT for outage detection (EC-8). The fake replays
fixture closes from data/fixtures/prices/ (arrives with E1-T1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from brier_pipeline.models import PriceDaily


class PriceSource(ABC):
    @abstractmethod
    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        """Daily UTC closes for an asset over [start, end]."""


class FakePriceSource(PriceSource):
    """Fixture-backed fake: 18 months of BTC/ETH/SOL daily closes (E1-T1)."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        # TASK: E1-T1
        raise NotImplementedError


class CoinGeckoPriceSource(PriceSource):
    """Published composite source for the top 100 assets. Not used until E4."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        # TASK: E4-T2 (collector job + cross-check, EC-8 gap flagging)
        raise NotImplementedError
