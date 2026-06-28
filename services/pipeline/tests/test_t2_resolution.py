"""T2 resolution failure-path and edge regression tests.

Characterises the actual behaviour of the existing resolution engine across the key
outcome branches.  All tests must pass against the current code; they form the
missing safety net for resolution edge paths.

Branches covered:
  1. Directional partial credit: 0.5 (ambiguous), 1.0 (clean HIT), 0.0 (clean MISS).
  2. Target-by-deadline: HIT, MISS, deferred (deadline future), deferred (data gap).
  3. resolve_open_claims no-op: no open claims and/or no price data — clean empty return.
  4. Conditional not yet activated: trigger unmet and window open → None (deferred).
  5. Default horizon mapping: default_30d (30 days), default_eoy (Dec 31),
     default_90d (90 days) — only the mappings that exist in rules.py.

DB tests use seeded analyst/video/transcript rows (make seed); claims are inserted
with identifiers prefixed 'res-t2-' and rolled back via the db_conn fixture.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

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
    resolve_directional_at_horizon,
    resolve_target_by_deadline,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"


# ---------------------------------------------------------------------------
# Shared helpers (mirroring test_resolution_e4.py style)
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    asset: str = "BTC",
    direction: Literal["bullish", "bearish"] = "bullish",
    target_price: float | None = None,
    magnitude_pct: float | None = None,
    horizon_deadline: date | None = None,
    horizon_basis: str | None = None,
    conditionality: dict[str, Any] | None = None,
    uttered_at: datetime,
    p0_price: float = 100_000.0,
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
        model_version="t2-test",
        prompt_version="t2-test",
        uttered_at=uttered_at,
        p0_price=p0_price,
        publishable=publishable,
        status=status,
        flags=flags or {},
    )


def _closes(asset: str, entries: list[tuple[date, float]]) -> list[PriceDaily]:
    """Build a synthetic list of daily closes for a single asset."""
    return [PriceDaily(asset=asset, day=d, close_usd=p, source="t2-test") for d, p in entries]


def _get_analyst_video_transcript(cur: Any) -> tuple[int, int, int]:
    """Return seeded (analyst_id, video_id, transcript_id) from the dev DB."""
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
    p0_price: float = 80_000.0,
    flags: str = "{}",
    status: str = "open",
    conditionality: str | None = None,
) -> int:
    """Insert a synthetic T2 test claim and return its auto-generated id."""
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
            'res-t2 placeholder quote fewer than fifteen words.',
            %s, %s,
            't2-test', 't2-test',
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


# ---------------------------------------------------------------------------
# 1. Directional partial credit branches
# ---------------------------------------------------------------------------


class TestDirectionalPartialCreditBranches:
    """resolve_directional_at_horizon returns exactly 0.5, 1.0, or 0.0.

    Outcome map (documented in rules.py):
      direction wrong                              → 0.0  MISS
      direction right + no magnitude stated        → 1.0  HIT (full credit)
      direction right + achieved >= half magnitude → 1.0  HIT (full credit)
      direction right + achieved < half magnitude  → 0.5  PARTIAL (ambiguous)
    """

    def test_clean_miss_wrong_direction(self) -> None:
        """Price falls at horizon for a bullish claim → outcome 0.0 (MISS)."""
        p0 = 100_000.0
        deadline = date(2025, 6, 1)
        claim = _make_claim(
            direction="bullish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=deadline,
            p0_price=p0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        closes = _closes("BTC", [(deadline, 90_000.0)])  # price fell → MISS for bullish
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 0.0
        assert result.rule_id == "directional_at_horizon.v0"
        assert "MISS" in result.rationale

    def test_clean_hit_right_direction_no_magnitude(self) -> None:
        """Price rises for bullish; no magnitude_pct stated → outcome 1.0 (full HIT)."""
        p0 = 100_000.0
        deadline = date(2025, 6, 1)
        claim = _make_claim(
            direction="bullish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=deadline,
            p0_price=p0,
            magnitude_pct=None,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        closes = _closes("BTC", [(deadline, 110_000.0)])  # price rose → HIT
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "directional_at_horizon.v0"
        assert "HIT" in result.rationale

    def test_partial_credit_bullish_achieved_under_half_magnitude(self) -> None:
        """Bullish: direction right, but achieved < half stated magnitude → 0.5 PARTIAL.

        stated_magnitude=20 → half=10; achieved=+8% (< 10) → PARTIAL.
        """
        p0 = 100_000.0
        deadline = date(2025, 6, 1)
        close_usd = 108_000.0  # +8%; 8 < 10 → partial
        claim = _make_claim(
            direction="bullish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=deadline,
            p0_price=p0,
            magnitude_pct=20.0,
            specificity_class=SpecificityClass.DIRECTION_MAGNITUDE,
        )
        closes = _closes("BTC", [(deadline, close_usd)])
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 0.5
        assert result.rule_id == "directional_at_horizon.v0"
        assert "PARTIAL" in result.rationale

    def test_clean_hit_achieved_exceeds_half_magnitude(self) -> None:
        """Bullish: direction right and achieved > half stated magnitude → 1.0 (full HIT).

        stated_magnitude=20 → half=10; achieved=+15% (>= 10) → full HIT.
        """
        p0 = 100_000.0
        deadline = date(2025, 6, 1)
        close_usd = 115_000.0  # +15%; 15 >= 10 → full hit
        claim = _make_claim(
            direction="bullish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=deadline,
            p0_price=p0,
            magnitude_pct=20.0,
            specificity_class=SpecificityClass.DIRECTION_MAGNITUDE,
        )
        closes = _closes("BTC", [(deadline, close_usd)])
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 1.0

    def test_partial_boundary_exactly_at_half_is_not_partial(self) -> None:
        """Achieved move exactly equal to half stated magnitude is NOT partial.

        Rule uses strict less-than (`achieved_pct < half_stated`).  When
        achieved == half, the condition is False → outcome 1.0 (full credit).
        This characterises the strict boundary.
        """
        p0 = 100_000.0
        deadline = date(2025, 6, 1)
        # stated=20, half=10; achieved=exactly 10% → 100000 * 1.10 = 110000
        close_usd = 110_000.0
        claim = _make_claim(
            direction="bullish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=deadline,
            p0_price=p0,
            magnitude_pct=20.0,
            specificity_class=SpecificityClass.DIRECTION_MAGNITUDE,
        )
        closes = _closes("BTC", [(deadline, close_usd)])
        result = resolve_directional_at_horizon(claim, closes)

        # achieved == half → NOT < half → NOT partial → full HIT
        assert result is not None
        assert result.outcome == 1.0

    def test_bearish_partial_credit(self) -> None:
        """Bearish: direction right (price falls) but achieved < half magnitude → 0.5.

        stated_magnitude=30 → half=15; price falls 5% (< 15%) → PARTIAL.
        """
        p0 = 100_000.0
        deadline = date(2025, 6, 1)
        close_usd = 95_000.0  # -5%; 5 < 15 → partial
        claim = _make_claim(
            direction="bearish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=deadline,
            p0_price=p0,
            magnitude_pct=30.0,
            specificity_class=SpecificityClass.DIRECTION_MAGNITUDE,
        )
        closes = _closes("BTC", [(deadline, close_usd)])
        result = resolve_directional_at_horizon(claim, closes)

        assert result is not None
        assert result.outcome == 0.5
        assert "PARTIAL" in result.rationale


# ---------------------------------------------------------------------------
# 2. Target-by-deadline branches
# ---------------------------------------------------------------------------


class TestTargetByDeadlineBranches:
    """resolve_target_by_deadline: HIT, MISS, and two deferred branches."""

    def test_hit_qualifying_close_before_deadline(self) -> None:
        """First qualifying close before deadline → outcome 1.0; FIRST close is cited."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 3, 31)
        target = 90_000.0
        hit_day = date(2025, 1, 6)

        claim = _make_claim(
            direction="bullish",
            target_price=target,
            uttered_at=uttered_at,
            horizon_deadline=deadline,
            p0_price=85_000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )
        closes = _closes(
            "BTC",
            [
                (date(2025, 1, 3), 87_000.0),  # below target
                (hit_day, 91_000.0),  # FIRST qualifying close
                (date(2025, 1, 20), 93_000.0),  # later qualifying close (not cited)
                (deadline, 89_000.0),  # deadline close (below target)
            ],
        )
        result = resolve_target_by_deadline(claim, closes)

        assert result is not None
        assert result.outcome == 1.0
        assert result.rule_id == "target_by_deadline.v0"
        # Must cite the FIRST qualifying close
        assert result.price_citation["day"] == str(hit_day)
        assert "HIT" in result.rationale

    def test_miss_deadline_passed_no_qualifying_close(self) -> None:
        """Deadline passed; target never reached → outcome 0.0; deadline close cited."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 3, 1)
        target = 120_000.0  # unreachable in synthetic data

        claim = _make_claim(
            direction="bullish",
            target_price=target,
            uttered_at=uttered_at,
            horizon_deadline=deadline,
            p0_price=85_000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )
        closes = _closes(
            "BTC",
            [
                (date(2025, 1, 15), 95_000.0),
                (date(2025, 2, 15), 98_000.0),
                (deadline, 97_000.0),  # deadline close present; target not met
            ],
        )
        result = resolve_target_by_deadline(claim, closes)

        assert result is not None
        assert result.outcome == 0.0
        assert result.rule_id == "target_by_deadline.v0"
        assert "MISS" in result.rationale
        # Deadline-day close is cited for the MISS
        assert result.price_citation["day"] == str(deadline)

    def test_deferred_deadline_not_yet_reached(self) -> None:
        """Latest available close is before the deadline; target not met → None (defer)."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 12, 31)  # far future relative to synthetic data
        target = 150_000.0

        claim = _make_claim(
            direction="bullish",
            target_price=target,
            uttered_at=uttered_at,
            horizon_deadline=deadline,
            p0_price=85_000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )
        closes = _closes(
            "BTC",
            [
                (date(2025, 1, 15), 95_000.0),
                (date(2025, 3, 15), 98_000.0),
                # latest close = Mar 15, well before Dec 31 deadline
            ],
        )
        result = resolve_target_by_deadline(claim, closes)

        # deadline in the future, no qualifying close → defer
        assert result is None

    def test_deferred_data_gap_on_deadline_close(self) -> None:
        """EC-8: deadline-day close is flagged data_gap=True → None (defer).

        The deadline has notionally passed (a later close exists), but the only
        close on the deadline day is a data gap.  Without a valid close to cite
        as the MISS reference, the rule defers rather than improvising (EC-8).
        """
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 3, 1)
        target = 150_000.0  # unreachable

        claim = _make_claim(
            direction="bullish",
            target_price=target,
            uttered_at=uttered_at,
            horizon_deadline=deadline,
            p0_price=85_000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )
        closes = [
            PriceDaily(asset="BTC", day=date(2025, 2, 15), close_usd=95_000.0, source="t2-test"),
            # Deadline close is gapped:
            PriceDaily(
                asset="BTC", day=deadline, close_usd=97_000.0, source="t2-test", data_gap=True
            ),
            # Post-deadline close makes latest_day > deadline so rule enters the MISS path,
            # but the only deadline-day close is gapped → defer (EC-8).
            PriceDaily(asset="BTC", day=date(2025, 3, 5), close_usd=96_000.0, source="t2-test"),
        ]
        result = resolve_target_by_deadline(claim, closes)

        # gapped deadline close → EC-8 defer
        assert result is None


# ---------------------------------------------------------------------------
# 3. resolve_open_claims no-op
# ---------------------------------------------------------------------------


class TestResolveOpenClaimsNoOp:
    """resolve_open_claims with no open claims or no available prices is a no-op."""

    def test_no_open_claims_returns_empty_list(self, db_conn: Any) -> None:
        """When zero open publishable claims exist the function returns [] with no exception."""
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            # Resolve all open claims so the resolver sees none.
            cur.execute("update claims set status = 'resolved' where status = 'open'")

        result = resolve_open_claims(prices=source, conn=db_conn)

        assert result == []

    def test_claim_unknown_asset_defers_gracefully(self, db_conn: Any) -> None:
        """An open claim for an asset with no price data is deferred, not an exception.

        FakePriceSource returns [] for unknown assets; the resolver must apply
        EC-8 deference (no resolution, no status change) without raising.
        """
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            cur.execute("update claims set status = 'resolved' where status = 'open'")
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)
            claim_id = _seed_claim(
                cur,
                analyst_id,
                video_id,
                transcript_id,
                asset="UNKNOWNCOIN",  # no fixture prices for this asset
                direction="bullish",
                horizon_deadline="2025-07-31",
                horizon_basis="stated",
                specificity_class="direction_only",
                uttered_at="2025-01-01 00:00:00+00",
                p0_price=1.0,
            )

        # Must not raise; claim defers due to missing price data.
        result = resolve_open_claims(prices=source, conn=db_conn)

        # No resolution for the unknown-asset claim
        unresolved = [r for r in result if r.claim_id == claim_id]
        assert unresolved == []

        # Claim status must remain 'open' (resolver does not touch it when deferring)
        with db_conn.cursor() as cur:
            cur.execute("select status from claims where id = %s", (claim_id,))
            row = cur.fetchone()
        assert row is not None
        assert str(row[0]) == "open"


# ---------------------------------------------------------------------------
# 4. Conditional not yet activated
# ---------------------------------------------------------------------------


class TestConditionalNotYetActivated:
    """A conditional claim whose trigger has not fired and whose observation window
    is still open must remain deferred (None from resolve_conditional) and must not
    be marked resolved or void by the resolver.
    """

    def test_trigger_not_fired_window_open_returns_none(self) -> None:
        """Pure rule: trigger price never reached; latest close before observation end → None."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        # default_30d → observation end = Jan 31.  Latest close = Jan 20 < Jan 31 → open.
        closes = _closes(
            "BTC",
            [
                (date(2025, 1, 10), 95_000.0),
                (date(2025, 1, 20), 97_000.0),
            ],
        )
        claim = _make_claim(
            direction="bullish",
            uttered_at=uttered_at,
            horizon_basis="default_30d",
            horizon_deadline=None,
            conditionality={
                "condition": "if BTC reaches a very high price level",
                "trigger_asset": "BTC",
                "trigger_price": 250_000.0,
                "trigger_direction": "above",
            },
            specificity_class=SpecificityClass.CONDITIONAL,
        )
        result = resolve_conditional(claim, closes)

        # trigger not fired; window still open → defer
        assert result is None

    def test_trigger_not_fired_far_future_deadline_stays_open(self, db_conn: Any) -> None:
        """DB: conditional claim with trigger unmet and deadline far in the future.

        horizon_deadline=2030-01-01 ensures the observation window is never elapsed
        by any fixture price data (fixture data ends well before 2030).  The resolver
        must NOT resolve or void the claim.
        """
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            cur.execute("update claims set status = 'resolved' where status = 'open'")
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

            cond = json.dumps(
                {
                    "condition": "if BTC reaches a very high price level",
                    "trigger_asset": "BTC",
                    "trigger_price": 250_000.0,
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
                horizon_deadline="2030-01-01",  # far future: observation window never elapsed
                horizon_basis="stated",
                specificity_class="conditional",
                uttered_at="2025-01-01 00:00:00+00",
                p0_price=95_000.0,
                conditionality=cond,
            )

        result = resolve_open_claims(prices=source, conn=db_conn)

        # No resolution for the claim (trigger never fired, window still open → defer)
        unresolved = [r for r in result if r.claim_id == claim_id]
        assert unresolved == []

        # Claim must remain 'open'
        with db_conn.cursor() as cur:
            cur.execute("select status from claims where id = %s", (claim_id,))
            row = cur.fetchone()
        assert row is not None
        assert str(row[0]) == "open"


# ---------------------------------------------------------------------------
# 5. Default horizon mapping (materialise_horizon_deadline)
# ---------------------------------------------------------------------------


class TestDefaultHorizonMapping:
    """materialise_horizon_deadline maps the three default-horizon basis strings.

    Actual table from rules.py (METHODOLOGY.md §2.1, Table 1):
      "default_30d"  → uttered_at.date() + 30 days
      "default_90d"  → uttered_at.date() + 90 days
      "default_eoy"  → December 31 of the utterance year

    The informal names 'soon', 'this year', and plain 'none' do NOT exist in
    rules.py; only the three basis strings above are implemented.
    """

    def test_default_30d_maps_to_30_days(self) -> None:
        """'default_30d' adds exactly 30 calendar days to uttered_at."""
        uttered_at = datetime(2025, 4, 1, tzinfo=UTC)
        claim = _make_claim(
            uttered_at=uttered_at,
            horizon_basis="default_30d",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)

        # Apr 1 + 30d = May 1
        assert result == date(2025, 5, 1)

    def test_default_90d_maps_to_90_days(self) -> None:
        """'default_90d' adds exactly 90 calendar days to uttered_at."""
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        claim = _make_claim(
            uttered_at=uttered_at,
            horizon_basis="default_90d",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)

        # Jan 1 + 90d = Apr 1 (31 Jan + 28 Feb + 31 Mar = 90)
        assert result == date(2025, 4, 1)

    def test_default_eoy_maps_to_dec_31(self) -> None:
        """'default_eoy' maps to December 31 of the utterance year."""
        uttered_at = datetime(2025, 6, 15, tzinfo=UTC)
        claim = _make_claim(
            uttered_at=uttered_at,
            horizon_basis="default_eoy",
            horizon_deadline=None,
        )
        result = materialise_horizon_deadline(claim)

        assert result == date(2025, 12, 31)
