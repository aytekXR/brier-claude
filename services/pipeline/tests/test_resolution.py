"""E1-T3 resolution engine tests.

Three categories:
  1. Pure rule tests using FakePriceSource — HP-2 canonical case + edge cases.
  2. Fixture sweep — every resolvable fixture claim must match its expected_outcome.
  3. DB tests via db_conn (rolled back) — idempotency, append-only trigger.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
import pytest

from brier_pipeline.config import METHODOLOGY_VERSION
from brier_pipeline.models import (
    Claim,
    PriceDaily,
    SpecificityClass,
)
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.resolution.rules import (
    resolve_directional_at_horizon,
    resolve_target_by_deadline,
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
    horizon_deadline: date,
    uttered_at: datetime,
    p0_price: float,
    specificity_class: SpecificityClass = SpecificityClass.TARGET_DEADLINE,
    claim_id: int = 1,
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
        horizon_basis="stated",
        stated_confidence=0.7,
        confidence_basis="stated",
        specificity_class=specificity_class,
        source_offset_seconds=0,
        model_version="test",
        prompt_version="test",
        uttered_at=uttered_at,
        p0_price=p0_price,
        publishable=True,
    )


def _btc_closes(
    source: FakePriceSource,
    start: date,
    end: date,
) -> list[PriceDaily]:
    return source.daily_closes("BTC", start, end)


# ---------------------------------------------------------------------------
# 1. Pure rule tests
# ---------------------------------------------------------------------------


class TestTargetByDeadline:
    """Tests for resolve_target_by_deadline."""

    def test_hp2_canonical_hit(self) -> None:
        """HP-2: BTC daily close above 80k by Jul 31 — resolves HIT on Jul 14."""
        source = FakePriceSource(FIXTURES)
        uttered_at = datetime(2025, 4, 30, 17, 0, 0, tzinfo=UTC)
        deadline = date(2025, 7, 31)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=80000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=79800.0,
        )
        closes = source.daily_closes("BTC", date(2025, 4, 30), deadline)
        result = resolve_target_by_deadline(claim, closes)

        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "target_by_deadline.v0"
        assert result.methodology_version == METHODOLOGY_VERSION
        # Must cite the FIRST qualifying close: Jul 14
        assert result.price_citation["day"] == "2025-07-14"
        assert result.price_citation["close_usd"] == 80140.0
        assert result.price_citation["asset"] == "BTC"
        # Rationale cites the result, never advises
        assert "HIT" in result.rationale
        assert "80140.00" in result.rationale
        assert "2025-07-14" in result.rationale
        assert "80000.00" in result.rationale

    def test_target_miss_deadline_passed(self) -> None:
        """Deadline has passed with no qualifying close -> outcome 0."""
        source = FakePriceSource(FIXTURES)
        # ay-04: ETH target 4000 by Apr10 2025 — ETH never reached 4000
        uttered_at = datetime(2025, 1, 10, 13, 30, 0, tzinfo=UTC)
        deadline = date(2025, 4, 10)
        claim = _make_claim(
            asset="ETH",
            direction="bullish",
            target_price=4000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=3578.96,
        )
        closes = source.daily_closes("ETH", date(2025, 1, 10), deadline)
        result = resolve_target_by_deadline(claim, closes)

        assert result is not None
        assert result.outcome == 0.0
        assert result.rule_id == "target_by_deadline.v0"
        assert "MISS" in result.rationale

    def test_future_deadline_returns_none(self) -> None:
        """Deadline in the future, no qualifying close yet -> None (still open)."""
        source = FakePriceSource(FIXTURES)
        # ay-open: BTC target 100000 by Dec 31 2026 (after fixture data end)
        uttered_at = datetime(2025, 6, 1, 13, 0, 0, tzinfo=UTC)
        deadline = date(2026, 12, 31)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=100000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=68053.0,
        )
        # Price data ends Jun 11 2026, well before deadline
        closes = source.daily_closes("BTC", date(2025, 6, 1), deadline)
        result = resolve_target_by_deadline(claim, closes)

        assert result is None

    def test_bearish_target_hit(self) -> None:
        """Bearish target: close <= target -> HIT."""
        source = FakePriceSource(FIXTURES)
        # ay-07: BTC closes below 80000 by Apr30 2025
        uttered_at = datetime(2025, 3, 1, 14, 0, 0, tzinfo=UTC)
        deadline = date(2025, 4, 30)
        claim = _make_claim(
            asset="BTC",
            direction="bearish",
            target_price=80000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=86071.11,
        )
        closes = source.daily_closes("BTC", date(2025, 3, 1), deadline)
        result = resolve_target_by_deadline(claim, closes)

        assert result is not None
        assert result.outcome == 1.0
        # First qualifying close should be Apr 26 at 79985.71
        assert result.price_citation["day"] == "2025-04-26"

    def test_ec8_missing_data_returns_none(self) -> None:
        """EC-8: empty close list (data gap / missing) -> None (defer)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 3, 31)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=90000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=95000.0,
        )
        result = resolve_target_by_deadline(claim, [])
        assert result is None

    def test_ec8_gap_flag_on_deadline_close_returns_none(self) -> None:
        """EC-8: deadline-day close row is flagged data_gap -> None."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 2, 1)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=90000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=95000.0,
        )
        # Provide one gapped close exactly on the deadline
        gapped_close = PriceDaily(
            asset="BTC",
            day=deadline,
            close_usd=88000.0,
            source="fixture",
            data_gap=True,
        )
        # The deadline has "passed" because we have a row for it, but it's gapped.
        # No qualifying close either (single row, gapped).
        result = resolve_target_by_deadline(claim, [gapped_close])
        assert result is None

    def test_price_citation_has_required_fields(self) -> None:
        """Resolution price_citation must include asset, day, close_usd, source."""
        source = FakePriceSource(FIXTURES)
        uttered_at = datetime(2025, 4, 30, 17, 0, 0, tzinfo=UTC)
        deadline = date(2025, 7, 31)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=80000.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=79800.0,
        )
        closes = source.daily_closes("BTC", date(2025, 4, 30), deadline)
        result = resolve_target_by_deadline(claim, closes)
        assert result is not None
        for field in ("asset", "day", "close_usd", "source"):
            assert field in result.price_citation, f"Missing field: {field}"


class TestDirectionalAtHorizon:
    """Tests for resolve_directional_at_horizon."""

    def test_directional_hit_bullish(self) -> None:
        """Bullish direction: close > p0 at horizon -> outcome 1."""
        source = FakePriceSource(FIXTURES)
        # nc-04: BTC bullish, horizon Jan9 2025, p0=101047.85, Jan9=103476
        uttered_at = datetime(2024, 12, 10, 16, 30, 0, tzinfo=UTC)
        deadline = date(2025, 1, 9)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=101047.85,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        closes = source.daily_closes("BTC", date(2024, 12, 10), deadline)
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "directional_at_horizon.v0"

    def test_directional_miss_wrong_direction(self) -> None:
        """Wrong direction -> outcome 0."""
        source = FakePriceSource(FIXTURES)
        # nc-06: BTC bullish, horizon Apr5 2025, p0=105403.94, Apr5=82330
        uttered_at = datetime(2025, 1, 5, 17, 0, 0, tzinfo=UTC)
        deadline = date(2025, 4, 5)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=105403.94,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        closes = source.daily_closes("BTC", date(2025, 1, 5), deadline)
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 0.0
        assert "MISS" in result.rationale

    def test_partial_credit_magnitude_under_half(self) -> None:
        """Direction right but achieved move < half of stated magnitude -> 0.5."""
        # Synthetic: BTC bullish 20%, but only moves up 3%.
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 4, 1)
        p0 = 100000.0
        close_price = 103000.0  # only +3%, half of 20% = 10%
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            magnitude_pct=20.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=p0,
            specificity_class=SpecificityClass.DIRECTION_MAGNITUDE,
        )
        closes = [PriceDaily(asset="BTC", day=deadline, close_usd=close_price, source="test")]
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 0.5
        assert "PARTIAL" in result.rationale

    def test_directional_hit_with_magnitude_full(self) -> None:
        """Direction right AND achieved move >= half of stated magnitude -> 1."""
        # Synthetic: BTC bearish 10%, price drops 12% (>= 5%).
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 4, 1)
        p0 = 100000.0
        close_price = 88000.0  # -12%, half of 10% = 5%
        claim = _make_claim(
            asset="BTC",
            direction="bearish",
            magnitude_pct=10.0,
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=p0,
            specificity_class=SpecificityClass.DIRECTION_MAGNITUDE,
        )
        closes = [PriceDaily(asset="BTC", day=deadline, close_usd=close_price, source="test")]
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 1.0

    def test_ec8_no_close_at_horizon(self) -> None:
        """EC-8: no close row for the horizon day -> None (defer)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 4, 1)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=90000.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        # No close at all
        result = resolve_directional_at_horizon(claim, [])
        assert result is None

    def test_ec8_gap_flag_at_horizon_returns_none(self) -> None:
        """EC-8: close at horizon is flagged data_gap -> None."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 4, 1)
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=90000.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        gapped = PriceDaily(
            asset="BTC", day=deadline, close_usd=95000.0, source="test", data_gap=True
        )
        result = resolve_directional_at_horizon(claim, [gapped])
        assert result is None

    def test_bearish_direction_hit(self) -> None:
        """Bearish direction: close < p0 at horizon -> outcome 1."""
        source = FakePriceSource(FIXTURES)
        # ve-03: BTC bearish, horizon Feb13 2025, p0=104491.49, Feb13=91447.50
        uttered_at = datetime(2024, 12, 15, 19, 0, 0, tzinfo=UTC)
        deadline = date(2025, 2, 13)
        claim = _make_claim(
            asset="BTC",
            direction="bearish",
            horizon_deadline=deadline,
            uttered_at=uttered_at,
            p0_price=104491.49,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        closes = source.daily_closes("BTC", date(2024, 12, 15), deadline)
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 1.0


# ---------------------------------------------------------------------------
# 2. Fixture sweep
# ---------------------------------------------------------------------------

# Map expected_outcome strings to floats.
_OUTCOME_MAP = {"HIT": 1.0, "MISS": 0.0, "PARTIAL": 0.5}

# Claims to skip in the sweep (not resolvable by v0 rules).
_SKIP_EXPECTED = {"non_falsifiable", "OPEN", "PENDING"}


def _load_fixture_claims() -> list[dict[str, Any]]:
    path = FIXTURES / "claims.json"
    data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _claim_from_fixture(raw: dict[str, Any], claim_id: int = 99) -> Claim:
    """Build a Claim from a fixture dict (no DB ids needed)."""
    uttered_at = datetime.fromisoformat(raw["uttered_at"].replace("Z", "+00:00"))
    return Claim(
        id=claim_id,
        analyst_id=1,
        video_id=1,
        transcript_id=1,
        asset=raw.get("asset"),
        direction=raw.get("direction"),
        target_price=float(raw["target_price"]) if raw.get("target_price") is not None else None,
        magnitude_pct=float(raw["magnitude_pct"]) if raw.get("magnitude_pct") is not None else None,
        horizon_deadline=date.fromisoformat(raw["horizon_deadline"])
        if raw.get("horizon_deadline")
        else None,
        horizon_basis=raw.get("horizon_basis"),
        stated_confidence=float(raw["stated_confidence"])
        if raw.get("stated_confidence") is not None
        else None,
        confidence_basis=raw.get("confidence_basis"),
        conditionality=raw.get("conditionality"),
        specificity_class=SpecificityClass(raw["specificity_class"]),
        source_offset_seconds=int(raw["source_offset_seconds"]),
        quote=raw.get("quote"),
        uttered_at=uttered_at,
        p0_price=float(raw["p0_price"]) if raw.get("p0_price") is not None else None,
        model_version="fixture-replay",
        prompt_version="v0",
        publishable=True,
    )


@pytest.mark.parametrize(
    "raw",
    [
        r
        for r in _load_fixture_claims()
        if r.get("expected_outcome") not in _SKIP_EXPECTED
        and r.get("specificity_class") not in ("non_falsifiable", "conditional")
        and r.get("horizon_deadline") is not None
    ],
    ids=lambda r: r["fixture_id"],
)
def test_fixture_sweep(raw: dict[str, Any]) -> None:
    """Every resolvable fixture claim must resolve to its expected_outcome."""
    source = FakePriceSource(FIXTURES)
    expected_str = raw["expected_outcome"]
    expected_outcome = _OUTCOME_MAP[expected_str]
    claim = _claim_from_fixture(raw)

    assert claim.asset is not None
    assert claim.horizon_deadline is not None

    closes = source.daily_closes(claim.asset, claim.uttered_at.date(), claim.horizon_deadline)

    sc = claim.specificity_class
    if sc == SpecificityClass.TARGET_DEADLINE or (
        claim.target_price is not None and claim.horizon_deadline is not None
    ):
        result = resolve_target_by_deadline(claim, closes)
    elif sc in (SpecificityClass.DIRECTION_ONLY, SpecificityClass.DIRECTION_MAGNITUDE):
        result = resolve_directional_at_horizon(claim, closes)
    else:
        raise AssertionError(
            f"{raw['fixture_id']}: unexpected specificity_class={sc} passed the sweep filter"
        )

    assert result is not None, (
        f"{raw['fixture_id']}: expected {expected_str} but got None (deferred)"
    )
    assert result.outcome == expected_outcome, (
        f"{raw['fixture_id']}: expected {expected_str} ({expected_outcome}) "
        f"but got {result.outcome}. rationale={result.rationale!r}"
    )


# ---------------------------------------------------------------------------
# 3. DB tests (rolled back via db_conn fixture)
# ---------------------------------------------------------------------------


def _seed_publishable_claim(
    cur: psycopg.Cursor[Any],
    analyst_id: int,
    video_id: int,
    transcript_id: int,
) -> int:
    """Insert a synthetic open publishable claim for testing and return its id."""
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
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            'BTC', 'bullish', 80000.0,
            '2025-07-31', 'stated',
            0.65, 'stated',
            'target_deadline', 420,
            'BTC daily close above eighty thousand before end of July.',
            '2025-04-30 17:00:00+00', 79800.0,
            'fixture-replay', 'v0',
            'approved', true, 'open', '{}'
        ) returning id
        """,
        (analyst_id, video_id, transcript_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _get_analyst_video_transcript(
    cur: psycopg.Cursor[Any],
) -> tuple[int, int, int]:
    """Return (analyst_id, video_id, transcript_id) from seeded data."""
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


def test_resolve_open_claims_appends_resolution_row(db_conn: Any) -> None:
    """resolve_open_claims appends a resolution row with all required fields."""
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        # First set all existing open claims to resolved to avoid interference.
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
        claim_id = _seed_publishable_claim(cur, analyst_id, video_id, transcript_id)

    resolutions = resolve_open_claims(prices=source, conn=db_conn)

    assert len(resolutions) >= 1
    target_res = next((r for r in resolutions if r.claim_id == claim_id), None)
    assert target_res is not None, "Expected a resolution for the seeded claim"
    assert target_res.outcome == 1.0  # HP-2 claim: HIT on Jul 14
    assert target_res.rule_id == "target_by_deadline.v0"
    assert target_res.rationale != ""
    assert "asset" in target_res.price_citation
    assert "day" in target_res.price_citation
    assert "close_usd" in target_res.price_citation
    assert "source" in target_res.price_citation
    assert target_res.methodology_version == METHODOLOGY_VERSION

    # Verify the DB row was inserted
    with db_conn.cursor() as cur:
        cur.execute(
            "select rule_id, rationale, methodology_version from resolutions where claim_id = %s",
            (claim_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "target_by_deadline.v0"
    assert str(row[1]) != ""
    assert str(row[2]) == METHODOLOGY_VERSION


def test_resolve_open_claims_flips_status_to_resolved(db_conn: Any) -> None:
    """After resolution, the claim's status is 'resolved'."""
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
        claim_id = _seed_publishable_claim(cur, analyst_id, video_id, transcript_id)

    resolve_open_claims(prices=source, conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute("select status from claims where id = %s", (claim_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "resolved"


def test_resolve_open_claims_idempotent_zero_duplicates(db_conn: Any) -> None:
    """A second call with no new open claims appends zero rows."""
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
        claim_id = _seed_publishable_claim(cur, analyst_id, video_id, transcript_id)

    # First run
    first_run = resolve_open_claims(prices=source, conn=db_conn)
    assert any(r.claim_id == claim_id for r in first_run)

    # Second run: claim is now resolved, must produce zero new rows.
    second_run = resolve_open_claims(prices=source, conn=db_conn)
    second_for_claim = [r for r in second_run if r.claim_id == claim_id]
    assert second_for_claim == [], (
        f"Second call produced {len(second_for_claim)} duplicate resolutions"
    )

    # DB must have exactly one resolution row for this claim.
    with db_conn.cursor() as cur:
        cur.execute("select count(*) from resolutions where claim_id = %s", (claim_id,))
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 1


def test_resolution_append_only_trigger_blocks_update(db_conn: Any) -> None:
    """UPDATE on a resolutions row raises (append-only trigger enforces NFR-3)."""
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
        claim_id = _seed_publishable_claim(cur, analyst_id, video_id, transcript_id)

    resolve_open_claims(prices=source, conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute("select id from resolutions where claim_id = %s", (claim_id,))
        row = cur.fetchone()
    assert row is not None
    res_id = int(row[0])

    with pytest.raises(psycopg.errors.RaiseException):
        with db_conn.cursor() as cur:
            cur.execute("update resolutions set outcome = 0 where id = %s", (res_id,))
