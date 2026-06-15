"""E4-T2: tests for base_rate() in resolution/base_rates.py.

Tests use hand-built synthetic PriceSources where the empirical
direction-success probability is known by construction.

Published conventions under test (ADR-0009, METHODOLOGY.md §3):
  - Rolling T-day windows over trailing history ending strictly before utterance.
  - bullish: close[d+T] > close[d] is a success.
  - bearish: close[d+T] < close[d] is a success.
  - Exact ties are not successes for either direction.
  - Minimum 20 windows required; fewer → 0.5 (neutral prior).
  - Result clamped to [0.0, 1.0].
  - T computed via materialise_horizon_deadline; fallback to 90 days when T <= 0.
  - No network, no DB.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from brier_pipeline.models import Claim, ClaimStatus, PriceDaily, ReviewState, SpecificityClass
from brier_pipeline.resolution.base_rates import MIN_BASE_RATE_WINDOWS, base_rate
from brier_pipeline.resolution.prices import FakePriceSource, PriceSource

# ---------------------------------------------------------------------------
# Minimal synthetic PriceSource for use in tests
# ---------------------------------------------------------------------------


class SyntheticPriceSource(PriceSource):
    """In-memory price source for tests: holds an explicit list of closes."""

    def __init__(self, closes: list[PriceDaily]) -> None:
        self._closes = closes

    def daily_closes(self, asset: str, start: date, end: date) -> list[PriceDaily]:
        return [p for p in self._closes if p.asset == asset and start <= p.day <= end]


def _make_daily_closes(
    asset: str,
    start_day: date,
    prices: list[float],
    source: str = "synthetic",
) -> list[PriceDaily]:
    """Build a list of consecutive PriceDaily entries from start_day."""
    return [
        PriceDaily(
            asset=asset,
            day=start_day + timedelta(days=i),
            close_usd=p,
            source=source,
        )
        for i, p in enumerate(prices)
    ]


def _make_claim(
    *,
    asset: str = "BTC",
    direction: str = "bullish",
    uttered_at: datetime | None = None,
    horizon_deadline: date | None = None,
    horizon_basis: str = "stated",
) -> Claim:
    """Build a minimal Claim for base_rate tests."""
    if uttered_at is None:
        uttered_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    return Claim(
        id=1,
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        asset=asset,
        direction=direction,
        target_price=None,
        magnitude_pct=None,
        horizon_deadline=horizon_deadline,
        horizon_basis=horizon_basis,
        stated_confidence=None,
        confidence_basis=None,
        conditionality=None,
        specificity_class=SpecificityClass.DIRECTION_ONLY,
        source_offset_seconds=0,
        quote=None,
        uttered_at=uttered_at,
        p0_price=None,
        extraction_confidence=None,
        model_version="test-v0",
        prompt_version="test-v0",
        reviewer_id=None,
        review_state=ReviewState.APPROVED,
        publishable=True,
        status=ClaimStatus.OPEN,
        flags={},
    )


# ---------------------------------------------------------------------------
# Helper: build a synthetic series with a known exact base rate
#
# We engineer a series of 30 closes over a 30-day window such that for T=1
# there are exactly 29 windows (pairs of consecutive days). We want 20/29
# windows to be "bullish wins" (next > current), so:
#   - Interleave 20 up-moves and 9 down-moves
# But we need >= 20 windows, so we need at least 21 closes.
#
# For a cleaner test: build 30 closes with T=1 so there are 29 pairs.
# Design the series so exactly 21 out of 29 pairs have close[i+1] > close[i].
# Then bullish base_rate = 21/29.
# ---------------------------------------------------------------------------


def _build_series_with_known_bullish_rate(start_day: date, n_up: int, n_down: int) -> list[float]:
    """Return a price series of length (n_up + n_down + 1) such that
    exactly n_up consecutive pairs are up-moves and n_down are down-moves,
    alternating in a simple pattern. T=1 windows.
    """
    # Interleave: up up ... down down ...
    # We want n_up out of (n_up + n_down) pairs to be up.
    prices: list[float] = [100.0]
    for i in range(n_up + n_down):
        if i < n_up:
            prices.append(prices[-1] + 1.0)  # up
        else:
            prices.append(prices[-1] - 1.0)  # down
    return prices


# ---------------------------------------------------------------------------
# Core tests
# ---------------------------------------------------------------------------


class TestBullishBaseRate:
    """Tests for the bullish direction base rate computation."""

    def test_known_bullish_rate_7_of_10(self) -> None:
        """A series engineered so 7/10 T=1 windows rose → bullish base_rate = 0.7.

        Series: 11 closes in a 10-day trailing window (T=1, so 10 pairs).
        7 up-moves, 3 down-moves → base_rate = 7/10 = 0.70.
        But 10 < MIN_BASE_RATE_WINDOWS (20), so this falls back to 0.5.
        Instead use a series with 21 up-moves and 4 down-moves = 25 windows.
        25 >= 20, so base_rate = 21/25 = 0.84.
        """
        # 26 closes → 25 pairs; 21 up-moves then 4 down-moves
        n_up, n_down = 21, 4
        prices = _build_series_with_known_bullish_rate(date(2025, 1, 1), n_up, n_down)
        assert len(prices) == 26  # n_up + n_down + 1

        # trailing window ends strictly before utterance_day
        # utterance_day = day after the last close
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", date(2025, 1, 1), prices)
        src = SyntheticPriceSource(closes)

        # Use T=1 (horizon_deadline = uttered_day + 1)
        claim_t1 = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
            horizon_basis="stated",
        )
        result = base_rate(claim_t1, src)
        # 21 ups, 4 downs = 25 pairs; base_rate = 21/25 = 0.84
        expected = n_up / (n_up + n_down)
        assert result == pytest.approx(expected, abs=1e-9), (
            f"Expected bullish base_rate {expected:.4f}, got {result:.4f}"
        )
        assert 0.0 <= result <= 1.0

    def test_all_up_moves_gives_one(self) -> None:
        """Series of 26 strictly increasing closes → bullish base_rate = 1.0 (T=1, 25 windows)."""
        prices = [100.0 + i for i in range(26)]
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", date(2025, 1, 1), prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
        )
        result = base_rate(claim, src)
        assert result == pytest.approx(1.0)

    def test_all_down_moves_gives_zero_bullish(self) -> None:
        """Series of strictly decreasing closes → bullish base_rate = 0.0 (T=1, 25 windows)."""
        prices = [100.0 - i for i in range(26)]
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", date(2025, 1, 1), prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
        )
        result = base_rate(claim, src)
        assert result == pytest.approx(0.0)


class TestBearishBaseRate:
    """Tests for the bearish direction base rate computation."""

    def test_known_bearish_rate(self) -> None:
        """Series where prices fall 22 times out of 25 consecutive pairs → bearish = 22/25."""
        # 26 closes: 22 down-moves then 3 up-moves
        n_down, n_up = 22, 3
        prices = [100.0]
        for i in range(n_down + n_up):
            if i < n_down:
                prices.append(prices[-1] - 1.0)
            else:
                prices.append(prices[-1] + 1.0)

        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bearish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
        )
        result = base_rate(claim, src)
        expected = n_down / (n_down + n_up)
        assert result == pytest.approx(expected, abs=1e-9)

    def test_all_up_moves_gives_zero_bearish(self) -> None:
        """All up-moves → bearish base_rate = 0.0."""
        prices = [100.0 + i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bearish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
        )
        result = base_rate(claim, src)
        assert result == pytest.approx(0.0)

    def test_all_down_moves_gives_one_bearish(self) -> None:
        """All down-moves → bearish base_rate = 1.0."""
        prices = [100.0 - i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bearish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
        )
        result = base_rate(claim, src)
        assert result == pytest.approx(1.0)


class TestTieHandling:
    """Exact ties must not count as successes for either direction."""

    def test_ties_not_counted_as_success(self) -> None:
        """Series that alternates: 100, 100 (tie), 101 (up), 100 (down), 100 (tie)...
        With T=1 and enough windows.

        Construct 30 closes: alternating 100 (tie) and 101 (up) = 15 ties, 14 ups, 0 downs.
        T=1, 29 windows. Ties are not successes.
        Bullish successes = number of ups = 14 (pairs where close[d+1] > close[d]).
        Ties: pairs where close[d+1] == close[d] → not a success.

        Pattern: [100, 100, 101, 100, 101, 100, ...] — 15 ties + 14 ups alternating.
        Actually let's use: [100]*15 + [101]*15 = all flat then all up.
        Pairs: (100,100)x14 tie, (100,101) up, (101,101)x14 tie = 1 up, 28 ties.
        base_rate = 1/29 ≈ 0.034
        """
        prices = [100.0] * 15 + [101.0] * 15  # 30 closes
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 31, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 2, 1),  # T=1
        )
        result = base_rate(claim, src)
        # 29 windows, 1 up (at the 100→101 boundary), 28 ties
        expected = 1.0 / 29.0
        assert result == pytest.approx(expected, abs=1e-9)


class TestMinimumWindowsFallback:
    """Fewer than MIN_BASE_RATE_WINDOWS T-day windows → return 0.5."""

    def test_empty_price_source_returns_half(self) -> None:
        """No price data → 0.5."""
        src = SyntheticPriceSource([])
        claim = _make_claim(
            direction="bullish",
            uttered_at=datetime(2026, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2026, 2, 1),
        )
        assert base_rate(claim, src) == 0.5

    def test_fewer_than_min_windows_returns_half(self) -> None:
        """19 windows (< 20) → 0.5, regardless of the direction-success rate."""
        # 20 closes gives 19 T=1 windows, which is one less than MIN_BASE_RATE_WINDOWS=20.
        prices = [100.0 + i for i in range(20)]  # 20 closes, all up
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 21, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 22),  # T=1
        )
        result = base_rate(claim, src)
        assert result == 0.5, (
            f"19 windows < MIN_BASE_RATE_WINDOWS={MIN_BASE_RATE_WINDOWS}; "
            f"expected 0.5 fallback, got {result}"
        )

    def test_exactly_min_windows_does_not_fallback(self) -> None:
        """Exactly MIN_BASE_RATE_WINDOWS windows → compute real rate."""
        # MIN_BASE_RATE_WINDOWS = 20 windows requires 21 closes with T=1.
        prices = [100.0 + i for i in range(21)]  # 21 closes, all up
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 22, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 23),  # T=1
        )
        result = base_rate(claim, src)
        # 20 windows, all up → 1.0 (not the fallback 0.5)
        assert result == pytest.approx(1.0), (
            f"Exactly {MIN_BASE_RATE_WINDOWS} windows should compute real rate 1.0, got {result}"
        )


class TestHorizonComputation:
    """T is computed correctly from horizon_deadline and horizon_basis."""

    def test_stated_horizon_used(self) -> None:
        """A stated horizon_deadline gives T = (deadline - uttered_day).days."""
        # 26 closes, all up → bullish = 1.0
        prices = [100.0 + i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        # T=1 via stated deadline
        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
            horizon_basis="stated",
        )
        result = base_rate(claim, src)
        assert result == pytest.approx(1.0)

    def test_default_90d_horizon_basis(self) -> None:
        """No stated horizon_deadline but horizon_basis='default_90d' → T=90 fallback.

        With ~18 months of fixture data, < 20 windows exist for T=90 → returns 0.5.
        This is the correct behavior for the fixture corpus.
        """
        # Build a series with 100 consecutive closes
        prices = [100.0 + i * 0.1 for i in range(100)]
        start_day = date(2024, 1, 1)
        uttered_at = datetime(2024, 4, 10, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        # horizon_deadline=None, horizon_basis='default_90d'
        # materialise_horizon_deadline computes uttered_day + 90d
        # T = 90, trailing window ends 2024-04-09
        # Need closes from [2024-04-09 - 5yr, 2024-04-09]
        # Our closes start 2024-01-01 and go 100 days → ends 2024-04-09.
        # So closes in window: 2024-01-01 to 2024-04-09 = 100 days.
        # T=90 windows: pairs (d, d+90) where d+90 <= day 99, i.e. d in days 0..9
        # = 10 valid windows. 10 < MIN_BASE_RATE_WINDOWS=20 → 0.5 fallback.
        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=None,
            horizon_basis="default_90d",
        )
        result = base_rate(claim, src)
        # Only 1 T=90 window available, which is < MIN_BASE_RATE_WINDOWS → 0.5
        assert result == 0.5

    def test_zero_or_negative_T_falls_back_to_90d(self) -> None:
        """When computed T <= 0 (deadline == uttered_day), fallback T=90 is used."""
        # 26 closes all up (T=1 base_rate would be 1.0)
        prices = [100.0 + i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        # deadline == uttered_day → T = 0 → fallback to T=90
        # With T=90 and only 26 closes, there are 0 windows → < 20 → 0.5
        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 27),  # same as uttered_day → T=0
            horizon_basis="stated",
        )
        result = base_rate(claim, src)
        # T=0 falls back to 90; with 26 closes, no T=90 window exists → 0.5
        assert result == 0.5


class TestClamping:
    """Result is always in [0.0, 1.0]."""

    def test_result_clamped_to_unit_interval(self) -> None:
        """Empirical rate is always in [0, 1] by construction; clamp is defensive."""
        prices = [100.0 + i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        for direction in ("bullish", "bearish"):
            claim = _make_claim(
                direction=direction,
                uttered_at=uttered_at,
                horizon_deadline=date(2025, 1, 28),  # T=1
            )
            result = base_rate(claim, src)
            assert 0.0 <= result <= 1.0, f"{direction}: result {result} outside [0, 1]"


class TestEdgeCases:
    """Edge cases: unknown direction, unknown asset, no claim direction."""

    def test_none_asset_returns_half(self) -> None:
        """Claim with no asset → 0.5."""
        src = SyntheticPriceSource([])
        claim = _make_claim(
            asset="BTC",  # overridden below
            direction="bullish",
            uttered_at=datetime(2026, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2026, 2, 1),
        )
        # Force asset to None via model_copy
        claim = claim.model_copy(update={"asset": None})
        result = base_rate(claim, src)
        assert result == 0.5

    def test_none_direction_returns_half(self) -> None:
        """Claim with no direction → 0.5."""
        prices = [100.0 + i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),
        )
        claim = claim.model_copy(update={"direction": None})
        result = base_rate(claim, src)
        assert result == 0.5

    def test_unknown_direction_returns_half(self) -> None:
        """Claim with direction not in ('bullish', 'bearish') → 0.5."""
        prices = [100.0 + i for i in range(26)]
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = _make_daily_closes("BTC", start_day, prices)
        src = SyntheticPriceSource(closes)

        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),
        )
        claim = claim.model_copy(update={"direction": "neutral"})
        result = base_rate(claim, src)
        assert result == 0.5

    def test_data_gap_days_excluded(self) -> None:
        """Days marked data_gap=True are excluded from the close_map."""
        # Build 26 closes, all increasing, but mark every other one as a data_gap.
        # Result: only 13 non-gap closes → fewer T=1 windows.
        start_day = date(2025, 1, 1)
        uttered_at = datetime(2025, 1, 27, 12, 0, 0, tzinfo=UTC)

        closes = []
        for i in range(26):
            closes.append(
                PriceDaily(
                    asset="BTC",
                    day=start_day + timedelta(days=i),
                    close_usd=100.0 + i,
                    source="synthetic",
                    data_gap=(i % 2 == 1),  # every odd day is a gap
                )
            )
        src = SyntheticPriceSource(closes)

        # T=1 but with every other day a gap, pairs can only be at even-day indices
        # 13 non-gap days at positions 0,2,4,...,24 → d+1 never in close_map (odd).
        # Result: 0 windows → < 20 → fallback 0.5.
        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 28),  # T=1
        )
        result = base_rate(claim, src)
        assert result == 0.5, (
            f"With data-gapped days, T=1 windows should be 0 → fallback 0.5, got {result}"
        )

    def test_fixture_base_source_short_history_returns_half_for_long_T(self) -> None:
        """FakePriceSource with ~18 months of BTC history returns 0.5 for large T values
        that exceed the fixture history length.

        The fixture spans ~18 months (Dec 2024 - Jun 2026, ~560 days). For a T of 540 days,
        there can be at most ~(560-540) = ~20 windows — which may be on the boundary.
        For T = 600 days (> 18 months), there are 0 windows → fallback to 0.5.

        This is the documented expected behaviour: the fixture corpus is explicitly
        too short for large-T base rate computation.
        """
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        fixtures_dir = repo_root / "data" / "fixtures"

        if not (fixtures_dir / "prices" / "BTC.json").exists():
            pytest.skip("BTC fixture prices not found")

        src = FakePriceSource(fixtures_dir)

        # T=600 days; fixture spans ~18 months (~560 days) → 0 windows → 0.5 fallback.
        uttered_at = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            # T=600 days from uttered_at
            horizon_deadline=date(2028, 1, 20),
            horizon_basis="stated",
        )
        result = base_rate(claim, src)
        # With T=600 and only ~560 days of fixture history, 0 T-day windows exist
        # → < MIN_BASE_RATE_WINDOWS → fallback to 0.5.
        assert result == 0.5, (
            f"Fixture corpus (~18 months) with T=600d should return 0.5 fallback, got {result}"
        )
