"""E4-T1 resolution rule tests.

Three groups:
  1. Default-horizon materialisation (materialise_horizon_deadline).
  2. Conditional activation (resolve_conditional) — fires, never-fires window
     open (defer), never-fires window elapsed (void).
  3. EC-11 reversal close (resolve_reversal_close + resolver pre-pass via db_conn).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from brier_pipeline.config import METHODOLOGY_VERSION
from brier_pipeline.models import (
    Claim,
    ClaimStatus,
    PriceDaily,
    SpecificityClass,
)
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.resolution.rules import (
    materialise_horizon_deadline,
    resolve_conditional,
    resolve_reversal_close,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    asset: str = "BTC",
    direction: Literal["bullish", "bearish"] = "bullish",
    target_price: float | None = None,
    magnitude_pct: float | None = None,
    horizon_deadline: date | None = None,
    horizon_basis: Literal["stated", "default_30d", "default_90d", "default_eoy"] | None = None,
    conditionality: dict[str, Any] | None = None,
    uttered_at: datetime,
    p0_price: float = 100000.0,
    specificity_class: SpecificityClass = SpecificityClass.DIRECTION_ONLY,
    claim_id: int = 1,
    flags: dict[str, Any] | None = None,
    status: ClaimStatus = ClaimStatus.OPEN,
    publishable: bool = True,
) -> Claim:
    return Claim(
        id=claim_id,
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        asset=asset,
        direction=direction,
        target_price=target_price,
        magnitude_pct=magnitude_pct,
        horizon_deadline=horizon_deadline,
        horizon_basis=horizon_basis,
        stated_confidence=0.7,
        confidence_basis="stated",
        conditionality=conditionality,
        specificity_class=specificity_class,
        source_offset_seconds=0,
        model_version="test",
        prompt_version="test",
        uttered_at=uttered_at,
        p0_price=p0_price,
        publishable=publishable,
        status=status,
        flags=flags or {},
    )


def _closes(
    asset: str,
    start: date,
    entries: list[tuple[date, float]],
) -> list[PriceDaily]:
    """Build a synthetic list of daily closes."""
    return [PriceDaily(asset=asset, day=d, close_usd=p, source="test") for d, p in entries]


# ---------------------------------------------------------------------------
# 1. Default-horizon materialisation
# ---------------------------------------------------------------------------


class TestMaterialiseHorizonDeadline:
    """materialise_horizon_deadline must compute from basis if deadline is None."""

    def test_default_30d(self) -> None:
        claim = _make_claim(
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_basis="default_30d",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)
        assert result == date(2025, 3, 31)

    def test_default_90d(self) -> None:
        claim = _make_claim(
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_basis="default_90d",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)
        assert result == date(2025, 5, 30)

    def test_default_eoy(self) -> None:
        claim = _make_claim(
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_basis="default_eoy",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)
        assert result == date(2025, 12, 31)

    def test_stated_with_deadline_returns_stored(self) -> None:
        """stated with an existing horizon_deadline: honour the stored value."""
        stored = date(2025, 9, 30)
        claim = _make_claim(
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_basis="stated",
            horizon_deadline=stored,
        )
        result = materialise_horizon_deadline(claim)
        assert result == stored

    def test_stated_with_null_deadline_returns_none(self) -> None:
        """stated with no horizon_deadline: cannot resolve — return None."""
        claim = _make_claim(
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_basis="stated",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)
        assert result is None

    def test_stored_deadline_takes_precedence_over_basis(self) -> None:
        """If horizon_deadline is already populated, return it regardless of basis."""
        stored = date(2025, 4, 15)
        claim = _make_claim(
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_basis="default_90d",
            horizon_deadline=stored,  # stored beats basis
        )
        result = materialise_horizon_deadline(claim)
        assert result == stored

    def test_eoy_year_derived_from_uttered_at(self) -> None:
        """default_eoy must use the year of uttered_at, not today."""
        claim = _make_claim(
            uttered_at=datetime(2024, 11, 15, tzinfo=UTC),
            horizon_basis="default_eoy",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)
        assert result == date(2024, 12, 31)


# ---------------------------------------------------------------------------
# 2. Conditional activation
# ---------------------------------------------------------------------------


class TestResolveConditional:
    """resolve_conditional: trigger fires / never-fires-open / never-fires-void."""

    # ------------------------------------------------------------------
    # Trigger fires: underlying HIT
    # ------------------------------------------------------------------

    def test_trigger_fires_directional_hit(self) -> None:
        """BTC bullish conditional: trigger below 75000 fires, then price rises."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        # activation: BTC hits below 75000 on day +5
        # horizon: 90d from activation = day +95
        # direction bullish: we set close on activation+10 > p0 -> HIT
        activation_day = date(2025, 1, 6)
        horizon_day = activation_day + timedelta(days=90)

        # Build closes from uttered_day through horizon
        closes: list[PriceDaily] = []
        # Before trigger fires
        for i in range(1, 6):
            closes.append(
                PriceDaily(
                    asset="BTC",
                    day=date(2025, 1, 1) + timedelta(days=i),
                    close_usd=80000.0,
                    source="test",
                )
            )
        # Trigger fires: BTC below 75000 on Jan 6
        closes.append(PriceDaily(asset="BTC", day=activation_day, close_usd=74000.0, source="test"))
        # After activation: price on the horizon date is above p0=70000
        closes.append(PriceDaily(asset="BTC", day=horizon_day, close_usd=75000.0, source="test"))

        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=uttered_at,
            p0_price=70000.0,
            horizon_basis="default_90d",
            horizon_deadline=None,
            conditionality={
                "condition": "if BTC drops below 75000",
                "trigger_asset": "BTC",
                "trigger_price": 75000.0,
                "trigger_direction": "below",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "conditional_at_horizon.v0"
        assert str(activation_day) in result.rationale
        assert "CONDITIONAL" in result.rationale
        assert result.methodology_version == METHODOLOGY_VERSION
        assert "activation_date" in result.price_citation

    def test_trigger_fires_target_hit(self) -> None:
        """Trigger fires, then target_price is hit within the horizon window."""
        uttered_at = datetime(2025, 2, 1, tzinfo=UTC)
        activation_day = date(2025, 2, 6)  # BTC goes above 90000
        horizon_day = activation_day + timedelta(days=30)

        closes: list[PriceDaily] = []
        # Before trigger
        for i in range(1, 6):
            closes.append(
                PriceDaily(
                    asset="BTC",
                    day=date(2025, 2, 1) + timedelta(days=i),
                    close_usd=85000.0,
                    source="test",
                )
            )
        # Trigger fires: above 90000
        closes.append(PriceDaily(asset="BTC", day=activation_day, close_usd=91000.0, source="test"))
        # Within horizon: target 95000 hit
        closes.append(
            PriceDaily(
                asset="BTC",
                day=activation_day + timedelta(days=15),
                close_usd=96000.0,
                source="test",
            )
        )
        closes.append(PriceDaily(asset="BTC", day=horizon_day, close_usd=93000.0, source="test"))

        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=95000.0,
            uttered_at=uttered_at,
            p0_price=85000.0,
            horizon_basis="default_30d",
            horizon_deadline=None,
            conditionality={
                "condition": "if BTC breaks above 90000",
                "trigger_asset": "BTC",
                "trigger_price": 90000.0,
                "trigger_direction": "above",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "conditional_at_horizon.v0"

    def test_trigger_fires_target_miss(self) -> None:
        """Trigger fires but target is never reached within the horizon window."""
        uttered_at = datetime(2025, 2, 1, tzinfo=UTC)
        activation_day = date(2025, 2, 6)

        closes: list[PriceDaily] = []
        for i in range(1, 6):
            closes.append(
                PriceDaily(
                    asset="BTC",
                    day=date(2025, 2, 1) + timedelta(days=i),
                    close_usd=85000.0,
                    source="test",
                )
            )
        closes.append(PriceDaily(asset="BTC", day=activation_day, close_usd=91000.0, source="test"))
        # Target 120000 never reached in window
        for i in range(1, 31):
            closes.append(
                PriceDaily(
                    asset="BTC",
                    day=activation_day + timedelta(days=i),
                    close_usd=95000.0,
                    source="test",
                )
            )

        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=120000.0,
            uttered_at=uttered_at,
            p0_price=85000.0,
            horizon_basis="default_30d",
            horizon_deadline=None,
            conditionality={
                "condition": "if BTC breaks above 90000",
                "trigger_asset": "BTC",
                "trigger_price": 90000.0,
                "trigger_direction": "above",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is not None
        assert result.outcome == 0.0
        assert result.rule_id == "conditional_at_horizon.v0"

    # ------------------------------------------------------------------
    # Never fires — window still open: defer (None)
    # ------------------------------------------------------------------

    def test_never_fires_window_open_returns_none(self) -> None:
        """Trigger never fired; most recent close is before the observation end
        -> window still open -> return None (defer)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        # Observation ends 90 days from uttered_at = Apr 1 2025.
        # Latest close is before that end: window still open.
        closes = [
            PriceDaily(asset="BTC", day=date(2025, 1, 10), close_usd=80000.0, source="test"),
            PriceDaily(asset="BTC", day=date(2025, 1, 20), close_usd=82000.0, source="test"),
        ]

        claim = _make_claim(
            asset="BTC",
            direction="bearish",
            uttered_at=uttered_at,
            horizon_basis="default_90d",
            horizon_deadline=None,
            conditionality={
                "condition": "if BTC drops below 75000",
                "trigger_asset": "BTC",
                "trigger_price": 75000.0,
                "trigger_direction": "below",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is None

    # ------------------------------------------------------------------
    # Never fires — window fully elapsed: void (outcome=-1.0)
    # ------------------------------------------------------------------

    def test_never_fires_window_elapsed_returns_void(self) -> None:
        """Trigger never fired AND window has fully elapsed -> void signal."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        # Observation ends 30 days from uttered_at = Jan 31 2025
        # Latest close is Feb 5 2025 > Jan 31 -> window elapsed.
        closes = [
            PriceDaily(asset="BTC", day=date(2025, 1, 10), close_usd=80000.0, source="test"),
            PriceDaily(asset="BTC", day=date(2025, 1, 20), close_usd=82000.0, source="test"),
            PriceDaily(asset="BTC", day=date(2025, 1, 31), close_usd=83000.0, source="test"),
            PriceDaily(asset="BTC", day=date(2025, 2, 5), close_usd=84000.0, source="test"),
        ]

        claim = _make_claim(
            asset="BTC",
            direction="bearish",
            uttered_at=uttered_at,
            horizon_basis="default_30d",  # deadline = Jan 31
            horizon_deadline=None,
            conditionality={
                "condition": "if BTC drops below 75000",
                "trigger_asset": "BTC",
                "trigger_price": 75000.0,
                "trigger_direction": "below",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is not None
        assert result.outcome < 0  # void signal
        assert result.rule_id == "conditional_void.v0"
        assert "VOID" in result.rationale
        assert "never activated" in result.rationale
        assert METHODOLOGY_VERSION == result.methodology_version

    def test_void_rationale_cites_observation_window(self) -> None:
        """Void rationale must cite the observation window for auditability (NFR-2)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        closes = [
            PriceDaily(asset="ETH", day=date(2025, 3, 31), close_usd=2500.0, source="test"),
            PriceDaily(asset="ETH", day=date(2025, 4, 5), close_usd=2600.0, source="test"),
        ]

        claim = _make_claim(
            asset="ETH",
            direction="bullish",
            uttered_at=uttered_at,
            horizon_basis="default_90d",  # ends Apr 1
            horizon_deadline=None,
            conditionality={
                "condition": "if ETH breaks above 3000",
                "trigger_asset": "ETH",
                "trigger_price": 3000.0,
                "trigger_direction": "above",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is not None
        assert result.rule_id == "conditional_void.v0"
        assert "2025-01-01" in result.rationale  # uttered_day
        assert "3000" in result.rationale  # trigger price in rationale

    # ------------------------------------------------------------------
    # Text-only / cross-asset trigger -> defer (None)
    # ------------------------------------------------------------------

    def test_text_only_conditionality_returns_none(self) -> None:
        """No structured trigger in conditionality -> return None (defer to QA)."""
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_basis="default_90d",
            conditionality={"condition": "if the market recovers"},
            specificity_class=SpecificityClass.CONDITIONAL,
        )
        result = resolve_conditional(claim, [])
        assert result is None

    def test_cross_asset_trigger_returns_none(self) -> None:
        """Trigger asset != claim asset -> cross-asset; out of scope -> None."""
        claim = _make_claim(
            asset="SOL",
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_basis="default_90d",
            conditionality={
                "condition": "if ETH breaks 3000",
                "trigger_asset": "ETH",  # different from claim.asset = SOL
                "trigger_price": 3000.0,
                "trigger_direction": "above",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )
        result = resolve_conditional(claim, [])
        assert result is None

    def test_none_conditionality_returns_none(self) -> None:
        """No conditionality at all -> defer."""
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_basis="default_90d",
            conditionality=None,
            specificity_class=SpecificityClass.CONDITIONAL,
        )
        result = resolve_conditional(claim, [])
        assert result is None

    # ------------------------------------------------------------------
    # NFR-2 auditability
    # ------------------------------------------------------------------

    def test_resolution_records_activation_date_in_citation(self) -> None:
        """price_citation must include activation_date (NFR-2)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        activation_day = date(2025, 1, 10)
        horizon_day = activation_day + timedelta(days=30)

        closes = [
            PriceDaily(asset="BTC", day=date(2025, 1, 5), close_usd=80000.0, source="test"),
            # Trigger fires: above 85000
            PriceDaily(asset="BTC", day=activation_day, close_usd=86000.0, source="test"),
            PriceDaily(asset="BTC", day=horizon_day, close_usd=87000.0, source="test"),
        ]

        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=uttered_at,
            p0_price=80000.0,
            horizon_basis="default_30d",
            conditionality={
                "condition": "if BTC breaks 85000",
                "trigger_asset": "BTC",
                "trigger_price": 85000.0,
                "trigger_direction": "above",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        result = resolve_conditional(claim, closes)
        assert result is not None
        assert "activation_date" in result.price_citation
        assert result.price_citation["activation_date"] == str(activation_day)

    def test_uses_fixture_prices_ay09(self) -> None:
        """ay-09 fixture: BTC conditional, trigger below 75000 fires May 9 2025."""
        source = FakePriceSource(FIXTURES)
        # ay-09: BTC bearish, target 60000, uttered_at 2025-03-01
        # trigger: BTC below 75000 -> activates May 9, 2025
        # horizon_basis: default_90d from activation = Aug 7, 2025
        # BTC min in window (May9..Aug7): ~68020 — never reaches 60000 -> MISS
        uttered_at = datetime(2025, 3, 1, 14, 0, 0, tzinfo=UTC)
        horizon_deadline = date(2025, 9, 30)  # stored deadline from fixture

        claim = _make_claim(
            asset="BTC",
            direction="bearish",
            target_price=60000.0,
            uttered_at=uttered_at,
            p0_price=86071.11,
            horizon_basis="default_90d",
            horizon_deadline=horizon_deadline,
            conditionality={
                "condition": "if BTC drops below 75000",
                "trigger_asset": "BTC",
                "trigger_price": 75000.0,
                "trigger_direction": "below",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )

        closes = source.daily_closes("BTC", uttered_at.date(), horizon_deadline)
        result = resolve_conditional(claim, closes)
        assert result is not None
        assert result.outcome == 0.0  # target 60000 never reached -> MISS
        assert result.rule_id == "conditional_at_horizon.v0"
        assert "2025-05-09" in result.price_citation["activation_date"]


# ---------------------------------------------------------------------------
# 3. EC-11 Reversal close
# ---------------------------------------------------------------------------


class TestResolveReversalClose:
    """resolve_reversal_close: close original claim at reversal_date (scored to date)."""

    def test_reversal_closes_target_claim_at_date(self) -> None:
        """Original target_deadline claim closed at reversal date with score-to-date."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        reversal_date = date(2025, 3, 1)

        # Original claim: BTC bullish, target 100000 by Jul 31
        original = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=100000.0,
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 7, 31),
            horizon_basis="stated",
            p0_price=80000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )

        # Closes up to reversal date (target 100000 not reached)
        closes = [
            PriceDaily(asset="BTC", day=date(2025, 1, 15), close_usd=85000.0, source="test"),
            PriceDaily(asset="BTC", day=date(2025, 2, 15), close_usd=88000.0, source="test"),
            PriceDaily(asset="BTC", day=reversal_date, close_usd=90000.0, source="test"),
        ]

        result = resolve_reversal_close(original, closes, reversal_date)
        assert result is not None
        assert result.outcome == 0.0  # target not reached at reversal date
        assert result.rule_id == "reversal_close.v0"
        assert "REVERSAL CLOSE" in result.rationale
        assert "EC-11" in result.rationale
        assert str(reversal_date) in result.rationale
        assert str(reversal_date) in result.price_citation.get("reversal_date", "")
        assert result.methodology_version == METHODOLOGY_VERSION

    def test_reversal_closes_directional_claim_at_date(self) -> None:
        """Original directional claim closed at reversal date: HIT if correct direction."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        reversal_date = date(2025, 2, 28)

        # Original: BTC bearish direction-only
        original = _make_claim(
            asset="BTC",
            direction="bearish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 6, 30),
            horizon_basis="stated",
            p0_price=90000.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )

        # At reversal date BTC close < p0 -> directional hit
        closes = [
            PriceDaily(asset="BTC", day=reversal_date, close_usd=75000.0, source="test"),
        ]

        result = resolve_reversal_close(original, closes, reversal_date)
        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "reversal_close.v0"

    def test_reversal_cite_reversal_date(self) -> None:
        """price_citation must include reversal_date (NFR-2 auditability)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        reversal_date = date(2025, 3, 15)

        original = _make_claim(
            asset="ETH",
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 9, 30),
            horizon_basis="stated",
            p0_price=3000.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )

        closes = [
            PriceDaily(asset="ETH", day=reversal_date, close_usd=3500.0, source="test"),
        ]

        result = resolve_reversal_close(original, closes, reversal_date)
        assert result is not None
        assert "reversal_date" in result.price_citation
        assert result.price_citation["reversal_date"] == str(reversal_date)

    def test_reversal_no_price_data_returns_none(self) -> None:
        """EC-8: no closes up to reversal_date -> return None (defer)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        reversal_date = date(2025, 3, 1)

        original = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 9, 30),
            horizon_basis="stated",
            p0_price=80000.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )

        result = resolve_reversal_close(original, [], reversal_date)
        assert result is None

    def test_reversal_of_never_fired_conditional_defers_no_void_row(self) -> None:
        """Reversing a CONDITIONAL original whose trigger never fired must NOT
        produce an outcome=-1.0 resolution (which would violate the resolutions
        CHECK constraint when inserted). It defers (returns None) so the normal
        conditional path voids it.
        """
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        reversal_date = date(2025, 2, 15)

        original = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 1, 31),
            horizon_basis="stated",
            p0_price=80000.0,
            specificity_class=SpecificityClass.CONDITIONAL,
            conditionality={
                "condition": "if BTC breaks above 200000",
                "trigger_asset": "BTC",
                "trigger_price": 200000.0,  # never fires
                "trigger_direction": "above",
            },
        )

        # Closes extend past the clamped (reversal) window so it has elapsed.
        closes = [
            PriceDaily(asset="BTC", day=date(2025, 1, 10), close_usd=85000.0, source="test"),
            PriceDaily(asset="BTC", day=date(2025, 2, 15), close_usd=90000.0, source="test"),
        ]

        result = resolve_reversal_close(original, closes, reversal_date)
        # Void sentinel must be swallowed -> None (defer), never a -1.0 row.
        assert result is None


# ---------------------------------------------------------------------------
# 4. DB-backed resolver tests (via db_conn)
# ---------------------------------------------------------------------------


def _get_analyst_video_transcript(cur: Any) -> tuple[int, int, int]:
    cur.execute("select id from analysts limit 1")
    a_row = cur.fetchone()
    assert a_row is not None, "No analysts seeded — run make seed first"
    analyst_id = int(a_row[0])
    cur.execute("select id from videos where analyst_id = %s limit 1", (analyst_id,))
    v_row = cur.fetchone()
    assert v_row is not None
    video_id = int(v_row[0])
    cur.execute("select id from transcripts where video_id = %s limit 1", (video_id,))
    t_row = cur.fetchone()
    assert t_row is not None
    transcript_id = int(t_row[0])
    return analyst_id, video_id, transcript_id


def _seed_claim(
    cur: Any,
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    *,
    asset: str = "BTC",
    direction: str = "bullish",
    target_price: float | None = None,
    horizon_deadline: str | None = None,
    horizon_basis: str = "stated",
    specificity_class: str = "direction_only",
    uttered_at: str = "2025-01-01 00:00:00+00",
    p0_price: float = 80000.0,
    flags: str = "{}",
    status: str = "open",
    conditionality: str | None = None,
) -> int:
    cur.execute(
        """
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction, target_price,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            specificity_class, source_offset_seconds,
            quote, uttered_at, p0_price,
            model_version, prompt_version,
            review_state, publishable, status, flags,
            conditionality
        ) values (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            0.7, 'stated',
            %s, 0,
            'test quote fewer than fifteen words here.',
            %s, %s,
            'test', 'test',
            'approved', true, %s, %s,
            %s
        ) returning id
        """,
        (
            analyst_id,
            video_id,
            transcript_id,
            asset,
            direction,
            target_price,
            horizon_deadline,
            horizon_basis,
            specificity_class,
            uttered_at,
            p0_price,
            status,
            flags,
            conditionality,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_default_horizon_materialises_and_resolves(db_conn: Any) -> None:
    """Resolver materialises default_90d horizon and resolves the claim."""
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
        # BTC direction_only claim, no horizon_deadline, basis=default_90d
        # uttered_at: 2025-01-05 -> horizon = 2025-04-05
        # BTC Apr5=82330 < 105403 (p0) -> MISS
        claim_id = _seed_claim(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bullish",
            horizon_deadline=None,
            horizon_basis="default_90d",
            specificity_class="direction_only",
            uttered_at="2025-01-05 17:00:00+00",
            p0_price=105403.94,
        )

    resolutions = resolve_open_claims(prices=source, conn=db_conn)

    target_res = next((r for r in resolutions if r.claim_id == claim_id), None)
    assert target_res is not None, "Expected a resolution for the default_90d claim"
    assert target_res.outcome == 0.0  # BTC Apr5=82330 < p0=105403 -> MISS
    # The materialised horizon date must appear in the rationale (NFR-2 auditability).
    assert "2025-04-05" in target_res.rationale

    # Check the horizon_deadline was persisted back to the claim
    with db_conn.cursor() as cur:
        cur.execute("select horizon_deadline from claims where id = %s", (claim_id,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == date(2025, 4, 5)


def test_reversal_prepass_closes_original_claim(db_conn: Any) -> None:
    """Resolver reversal pre-pass: new claim with reverses_claim_id closes the original."""
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

        # Original claim: BTC bearish, direction-only, stated deadline Jul 31
        original_id = _seed_claim(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bearish",
            horizon_deadline="2025-07-31",
            horizon_basis="stated",
            specificity_class="direction_only",
            uttered_at="2025-01-01 00:00:00+00",
            p0_price=105000.0,
            status="open",
        )

        # Reversal claim: same analyst, different video but same objects
        # uttered_at = 2025-02-15 (the reversal date)
        # flags: reverses_claim_id = original_id
        # This claim itself has a stated deadline in the future
        reversal_flags = json.dumps({"reverses_claim_id": original_id})
        _reversal_id = _seed_claim(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bullish",
            horizon_deadline="2025-07-31",
            horizon_basis="stated",
            specificity_class="direction_only",
            uttered_at="2025-02-15 00:00:00+00",
            p0_price=95000.0,
            flags=reversal_flags,
            status="open",
        )

    resolutions = resolve_open_claims(prices=source, conn=db_conn)

    # Find the reversal-close resolution on the original claim
    reversal_res = next(
        (r for r in resolutions if r.claim_id == original_id and r.rule_id == "reversal_close.v0"),
        None,
    )
    assert reversal_res is not None, "Expected a reversal_close.v0 resolution for original claim"
    assert "REVERSAL CLOSE" in reversal_res.rationale
    assert "EC-11" in reversal_res.rationale

    # Original claim must be resolved
    with db_conn.cursor() as cur:
        cur.execute("select status from claims where id = %s", (original_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "resolved"


def test_conditional_void_marks_claim_void(db_conn: Any) -> None:
    """Conditional claim that never fires with elapsed window gets status=void.

    The void sentinel is returned in the list (for caller visibility) but the
    resolution row is NOT inserted into the DB (outcome=-1 violates the check
    constraint; voids are not scored and need no ledger entry).
    """
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

        # Conditional claim: BTC above 200000 (impossible trigger)
        # horizon_deadline: 2025-01-31 (stated)
        # Fixture data covers well past Jan 31 -> window elapsed
        # BTC never reaches 200000 -> void
        cond = json.dumps(
            {
                "condition": "if BTC hits 200000",
                "trigger_asset": "BTC",
                "trigger_price": 200000.0,
                "trigger_direction": "above",
            }
        )
        claim_id = _seed_claim(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bullish",
            horizon_deadline="2025-01-31",
            horizon_basis="stated",
            specificity_class="conditional",
            uttered_at="2025-01-01 00:00:00+00",
            p0_price=105000.0,
            conditionality=cond,
        )

    resolutions = resolve_open_claims(prices=source, conn=db_conn)

    # Resolver returns a void sentinel in the list for visibility.
    void_res = next((r for r in resolutions if r.claim_id == claim_id), None)
    assert void_res is not None, "Expected a void sentinel for the conditional claim"
    assert void_res.rule_id == "conditional_void.v0"
    assert void_res.outcome < 0

    # Claim status must be void (not resolved, not open).
    with db_conn.cursor() as cur:
        cur.execute("select status from claims where id = %s", (claim_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "void"

    # No resolution row must be in the DB for this claim (the check
    # constraint permits only 0/0.5/1; voids are not scored).
    with db_conn.cursor() as cur:
        cur.execute("select count(*) from resolutions where claim_id = %s", (claim_id,))
        count_row = cur.fetchone()
    assert count_row is not None
    assert int(count_row[0]) == 0


def test_conditional_fires_late_resolves_through_resolver(db_conn: Any) -> None:
    """A conditional claim whose trigger fires LATE in its observation window
    resolves through the full resolver, inserting a valid resolution row.

    This is the regression guard for the price-window truncation bug: with
    horizon_basis=default_90d and NO stored deadline, the observation window ends
    at uttered+90d (2025-05-30), but the trigger fires 2025-05-09 and the scoring
    horizon then runs to 2025-08-07 (activation+90d) — PAST the observation end.
    The resolver must fetch price data through as_of (not the observation end) so
    the underlying directional rule sees the 2025-08-07 close. BTC bearish,
    p0=86071.11, BTC close on 2025-08-07 = 82321.04 < p0 -> HIT (outcome=1.0).
    """
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

        cond = json.dumps(
            {
                "condition": "if BTC drops below 75000",
                "trigger_asset": "BTC",
                "trigger_price": 75000.0,
                "trigger_direction": "below",
            }
        )
        claim_id = _seed_claim(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bearish",
            horizon_deadline=None,  # default-horizon materialised at resolution time
            horizon_basis="default_90d",
            specificity_class="conditional",
            uttered_at="2025-03-01 14:00:00+00",
            p0_price=86071.11,
            conditionality=cond,
        )

    resolutions = resolve_open_claims(prices=source, conn=db_conn)

    fired = next((r for r in resolutions if r.claim_id == claim_id), None)
    assert fired is not None, "Late-firing conditional must resolve (not defer forever)"
    assert fired.rule_id == "conditional_at_horizon.v0"
    assert fired.outcome == 1.0  # BTC 2025-08-07 close 82321.04 < p0 86071.11 -> bearish HIT
    assert fired.outcome in (0.0, 0.5, 1.0)  # never the void sentinel
    assert fired.price_citation["activation_date"] == "2025-05-09"

    # A real resolution row must be inserted (outcome in {0,0.5,1}) and the
    # claim flipped to resolved.
    with db_conn.cursor() as cur:
        cur.execute(
            "select count(*), max(outcome) from resolutions where claim_id = %s",
            (claim_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 1
    assert float(row[1]) == 1.0

    with db_conn.cursor() as cur:
        cur.execute("select status from claims where id = %s", (claim_id,))
        status_row = cur.fetchone()
    assert status_row is not None
    assert str(status_row[0]) == "resolved"
