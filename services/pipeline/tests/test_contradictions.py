"""Tests for EC-6 contradiction detection (E4-T4).

Covers:
  1. Basic contradiction: opposite directions, same analyst+asset, overlapping
     horizons -> both voided + hedging flag + contradicts_claim_ids.
  2. Non-overlapping horizons -> NOT contradicted (neither voided).
  3. Same direction, same asset, overlapping -> NOT contradicted (reinforcement).
  4. Different assets, opposite directions, overlapping -> NOT contradicted.
  5. Different analysts -> NOT contradicted (each analyst judged individually).
  6. Three-claim case: two bullish + one bearish, all overlapping -> all three
     voided (pairwise contradiction; bearish records both bullish ids; each
     bullish records the bearish id).
  7. Default-horizon claims (basis=default_30d/default_90d): overlap computed
     using materialised deadlines.
  8. DB-backed test: contradiction pre-pass in resolve_open_claims voids both
     contradicting claims in the DB, sets hedging flags, inserts NO resolution
     rows for them.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from brier_pipeline.models import (
    Claim,
    ClaimStatus,
    SpecificityClass,
)
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.resolution.rules import detect_contradictions

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CLAIM_COUNTER = 0


def _next_id() -> int:
    global _CLAIM_COUNTER
    _CLAIM_COUNTER += 1
    return _CLAIM_COUNTER


def _make_claim(
    *,
    claim_id: int | None = None,
    analyst_id: int = 1,
    asset: str = "BTC",
    direction: Literal["bullish", "bearish"] = "bullish",
    horizon_deadline: date | None = None,
    horizon_basis: Literal["stated", "default_30d", "default_90d", "default_eoy"] | None = "stated",
    uttered_at: datetime,
    specificity_class: SpecificityClass = SpecificityClass.DIRECTION_ONLY,
    status: ClaimStatus = ClaimStatus.OPEN,
    publishable: bool = True,
    flags: dict[str, Any] | None = None,
    target_price: float | None = None,
    p0_price: float = 80000.0,
) -> Claim:
    return Claim(
        id=claim_id if claim_id is not None else _next_id(),
        analyst_id=analyst_id,
        video_id=1,
        transcript_id=1,
        asset=asset,
        direction=direction,
        target_price=target_price,
        horizon_deadline=horizon_deadline,
        horizon_basis=horizon_basis,
        stated_confidence=0.7,
        confidence_basis="stated",
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


# ---------------------------------------------------------------------------
# 1. Basic contradiction: opposite directions, same analyst+asset, overlapping
# ---------------------------------------------------------------------------


class TestBasicContradiction:
    def test_opposite_directions_overlapping_both_voided(self) -> None:
        """Two opposite-direction claims, same analyst+asset, overlapping -> both void."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=10,
            analyst_id=1,
            asset="BTC",
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 3, 31),
            horizon_basis="stated",
        )
        bear = _make_claim(
            claim_id=11,
            analyst_id=1,
            asset="BTC",
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 3, 31),
            horizon_basis="stated",
        )

        result = detect_contradictions([bull, bear])

        assert len(result) == 2
        result_by_id = {c.id: c for c in result}

        # Both must be voided.
        assert result_by_id[10].status == ClaimStatus.VOID
        assert result_by_id[11].status == ClaimStatus.VOID

        # Both must carry the hedging flag.
        assert result_by_id[10].flags["hedging_contradiction"] is True
        assert result_by_id[11].flags["hedging_contradiction"] is True

        # Each must record the other's id.
        assert 11 in result_by_id[10].flags["contradicts_claim_ids"]
        assert 10 in result_by_id[11].flags["contradicts_claim_ids"]

    def test_original_claims_not_mutated(self) -> None:
        """detect_contradictions must return copies; originals stay OPEN."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=20,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bear = _make_claim(
            claim_id=21,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        detect_contradictions([bull, bear])

        # Input objects must be untouched.
        assert bull.status == ClaimStatus.OPEN
        assert bear.status == ClaimStatus.OPEN
        assert "hedging_contradiction" not in bull.flags
        assert "hedging_contradiction" not in bear.flags

    def test_rule_id_noted_in_flags(self) -> None:
        """void_rule_id + contradicts_claim_ids must be recorded (NFR-2 auditability)."""
        uttered = datetime(2025, 2, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=30,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 5, 31),
        )
        bear = _make_claim(
            claim_id=31,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 5, 31),
        )

        result = detect_contradictions([bull, bear])
        result_by_id = {c.id: c for c in result}

        assert set(result_by_id) == {30, 31}
        # rule_id must be recorded so the void is queryable by rule (§2.4 / NFR-2).
        for c in result:
            assert c.flags["void_rule_id"] == "contradiction_void.v0"
        # contradicts_claim_ids must name the actual counterpart, not just be non-empty.
        assert result_by_id[30].flags["contradicts_claim_ids"] == [31]
        assert result_by_id[31].flags["contradicts_claim_ids"] == [30]

    def test_stated_claim_without_deadline_not_contradicted(self) -> None:
        """A 'stated' claim with no computable deadline has no resolvable horizon,
        so overlap cannot be established and it is NOT voided as a hedge (§2.4)."""
        uttered = datetime(2025, 2, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=40,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 5, 31),
            horizon_basis="stated",
        )
        bear_open_ended = _make_claim(
            claim_id=41,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=None,  # stated but no deadline -> no resolvable horizon
            horizon_basis="stated",
        )

        result = detect_contradictions([bull, bear_open_ended])
        # Neither claim is voided: the deadline-less claim cannot establish overlap.
        assert result == []


# ---------------------------------------------------------------------------
# 2. Non-overlapping horizons -> NOT contradicted
# ---------------------------------------------------------------------------


class TestNonOverlappingHorizons:
    def test_non_overlapping_not_contradicted(self) -> None:
        """Opposite directions but horizons do not overlap -> no contradiction."""
        # bull: Jan 1 - Feb 28; bear: Mar 1 - Apr 30  -> no overlap
        bull = _make_claim(
            claim_id=40,
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 2, 28),
        )
        bear = _make_claim(
            claim_id=41,
            direction="bearish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 4, 30),
        )

        result = detect_contradictions([bull, bear])
        assert result == []

    def test_adjacent_horizons_not_overlapping(self) -> None:
        """bull ends Feb 28; bear starts Mar 1 — adjacent but not overlapping."""
        bull = _make_claim(
            claim_id=42,
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 2, 28),
        )
        bear = _make_claim(
            claim_id=43,
            direction="bearish",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 4, 30),
        )

        result = detect_contradictions([bull, bear])
        assert result == []


# ---------------------------------------------------------------------------
# 3. Same direction -> NOT contradicted (reinforcement)
# ---------------------------------------------------------------------------


class TestSameDirection:
    def test_both_bullish_not_contradicted(self) -> None:
        """Same direction: two bullish claims on same asset, overlapping -> no contradiction."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull1 = _make_claim(
            claim_id=50,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bull2 = _make_claim(
            claim_id=51,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bull1, bull2])
        assert result == []

    def test_both_bearish_not_contradicted(self) -> None:
        """Same direction: two bearish claims -> no contradiction."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bear1 = _make_claim(
            claim_id=52,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bear2 = _make_claim(
            claim_id=53,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bear1, bear2])
        assert result == []


# ---------------------------------------------------------------------------
# 4. Different assets -> NOT contradicted
# ---------------------------------------------------------------------------


class TestDifferentAssets:
    def test_different_assets_not_contradicted(self) -> None:
        """Opposite directions but different assets -> no contradiction."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull_btc = _make_claim(
            claim_id=60,
            asset="BTC",
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bear_eth = _make_claim(
            claim_id=61,
            asset="ETH",
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bull_btc, bear_eth])
        assert result == []


# ---------------------------------------------------------------------------
# 5. Different analysts -> NOT contradicted
# ---------------------------------------------------------------------------


class TestDifferentAnalysts:
    def test_different_analysts_not_contradicted(self) -> None:
        """Two analysts, opposite directions same asset -> no contradiction (different analysts)."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull_a1 = _make_claim(
            claim_id=70,
            analyst_id=1,
            asset="BTC",
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bear_a2 = _make_claim(
            claim_id=71,
            analyst_id=2,
            asset="BTC",
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bull_a1, bear_a2])
        assert result == []


# ---------------------------------------------------------------------------
# 6. Three-claim case: two bullish + one bearish, all overlapping
# ---------------------------------------------------------------------------


class TestThreeClaimContradiction:
    def test_two_bullish_one_bearish_all_voided(self) -> None:
        """Two bullish + one bearish, same analyst+asset, overlapping -> all three voided.

        Documented precedence: pairwise contradiction.  The bearish claim
        contradicts both bullish claims; all three are voided.  The bearish
        claim records both bullish IDs; each bullish records the bearish ID.
        """
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull1 = _make_claim(
            claim_id=80,
            analyst_id=1,
            asset="BTC",
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bull2 = _make_claim(
            claim_id=81,
            analyst_id=1,
            asset="BTC",
            direction="bullish",
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 6, 30),
        )
        bear = _make_claim(
            claim_id=82,
            analyst_id=1,
            asset="BTC",
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bull1, bull2, bear])

        result_by_id = {c.id: c for c in result}

        # All three must appear in the result.
        assert set(result_by_id.keys()) == {80, 81, 82}

        # All voided.
        for c in result:
            assert c.status == ClaimStatus.VOID
            assert c.flags["hedging_contradiction"] is True

        # Bearish records both bullish IDs.
        bear_contra = result_by_id[82].flags["contradicts_claim_ids"]
        assert 80 in bear_contra
        assert 81 in bear_contra

        # Each bullish records the bearish ID.
        assert 82 in result_by_id[80].flags["contradicts_claim_ids"]
        assert 82 in result_by_id[81].flags["contradicts_claim_ids"]

    def test_non_contradicting_claims_excluded_from_result(self) -> None:
        """Claims that do not participate in any contradiction are not returned."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=90,
            analyst_id=1,
            asset="BTC",
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        bear = _make_claim(
            claim_id=91,
            analyst_id=1,
            asset="BTC",
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )
        # This claim is a different analyst — should not appear.
        harmless = _make_claim(
            claim_id=92,
            analyst_id=2,
            asset="ETH",
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bull, bear, harmless])

        result_ids = {c.id for c in result}
        assert 90 in result_ids
        assert 91 in result_ids
        assert 92 not in result_ids


# ---------------------------------------------------------------------------
# 7. Default-horizon claims (basis=default_30d / default_90d)
# ---------------------------------------------------------------------------


class TestDefaultHorizonContradictions:
    def test_default_30d_overlapping_contradicted(self) -> None:
        """Two opposite-direction claims with default_30d basis, uttered same day -> overlapping."""
        uttered = datetime(2025, 3, 1, tzinfo=UTC)
        # Both materialise to [2025-03-01, 2025-03-31] -> fully overlapping.
        bull = _make_claim(
            claim_id=100,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=None,
            horizon_basis="default_30d",
        )
        bear = _make_claim(
            claim_id=101,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=None,
            horizon_basis="default_30d",
        )

        result = detect_contradictions([bull, bear])

        assert len(result) == 2
        ids = {c.id for c in result}
        assert ids == {100, 101}
        for c in result:
            assert c.status == ClaimStatus.VOID
            assert c.flags["hedging_contradiction"] is True

    def test_default_horizons_non_overlapping_not_contradicted(self) -> None:
        """default_30d bull uttered Jan 1 (deadline Jan 31); default_30d bear uttered Feb 5
        (deadline Mar 7) -> horizons do not overlap."""
        bull = _make_claim(
            claim_id=102,
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=None,
            horizon_basis="default_30d",
        )
        # Bear uttered after bull's deadline.
        bear = _make_claim(
            claim_id=103,
            direction="bearish",
            uttered_at=datetime(2025, 2, 5, tzinfo=UTC),
            horizon_deadline=None,
            horizon_basis="default_30d",
        )

        result = detect_contradictions([bull, bear])
        assert result == []

    def test_default_90d_overlapping_contradicted(self) -> None:
        """default_90d bull Jan 1 (deadline Apr 1); default_30d bear Feb 1 (deadline Mar 3)
        -> overlapping (Feb 1 <= Apr 1 and Jan 1 <= Mar 3)."""
        bull = _make_claim(
            claim_id=104,
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=None,
            horizon_basis="default_90d",
        )
        bear = _make_claim(
            claim_id=105,
            direction="bearish",
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
            horizon_deadline=None,
            horizon_basis="default_30d",
        )

        result = detect_contradictions([bull, bear])

        assert len(result) == 2
        ids = {c.id for c in result}
        assert ids == {104, 105}

    def test_void_and_non_falsifiable_excluded(self) -> None:
        """Void and non-falsifiable claims must not participate in contradiction detection."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        already_void = _make_claim(
            claim_id=110,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            status=ClaimStatus.VOID,
        )
        non_false = _make_claim(
            claim_id=111,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            specificity_class=SpecificityClass.NON_FALSIFIABLE,
        )
        normal_bull = _make_claim(
            claim_id=112,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([already_void, non_false, normal_bull])

        # no contradiction (non-falsifiable and already-void excluded).
        assert result == []

    def test_unpublishable_excluded(self) -> None:
        """Unpublishable claims must not participate in contradiction detection."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        unpub_bull = _make_claim(
            claim_id=120,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            publishable=False,
        )
        bear = _make_claim(
            claim_id=121,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            publishable=True,
        )

        result = detect_contradictions([unpub_bull, bear])
        assert result == []

    def test_existing_flags_preserved(self) -> None:
        """detect_contradictions must not clobber existing flags on the claim."""
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=130,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            flags={"fixture_id": "fx-42", "some_prior_flag": True},
        )
        bear = _make_claim(
            claim_id=131,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
        )

        result = detect_contradictions([bull, bear])

        result_bull = next(c for c in result if c.id == 130)
        # Existing flags must still be present.
        assert result_bull.flags.get("fixture_id") == "fx-42"
        assert result_bull.flags.get("some_prior_flag") is True
        # And the new hedging flags must also be there.
        assert result_bull.flags["hedging_contradiction"] is True

    def test_empty_list_returns_empty(self) -> None:
        """detect_contradictions([]) -> []."""
        assert detect_contradictions([]) == []

    def test_single_claim_returns_empty(self) -> None:
        """A single claim cannot contradict anything."""
        claim = _make_claim(
            claim_id=140,
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 6, 30),
        )
        assert detect_contradictions([claim]) == []


# ---------------------------------------------------------------------------
# 8. DB-backed test: resolver contradiction pre-pass
# ---------------------------------------------------------------------------


def _get_analyst_video_transcript(cur: Any) -> tuple[int, int, int]:
    cur.execute("select id from analysts limit 1")
    a_row = cur.fetchone()
    assert a_row is not None, "No analysts seeded — run make seed first"
    analyst_id = int(a_row[0])
    # seed.py seeds the analyst registry only (no videos/transcripts), so create a
    # video + transcript under the seeded analyst like the other DB-backed tests do
    # (rolled back by the transactional db_conn fixture).
    cur.execute("select id from videos where analyst_id = %s limit 1", (analyst_id,))
    v_row = cur.fetchone()
    if v_row is None:
        cur.execute(
            """
            insert into videos (analyst_id, youtube_video_id, title, published_at)
            values (%s, %s, 'contradiction test video', now()) returning id
            """,
            (analyst_id, f"vid-contra-{analyst_id}"),
        )
        v_row = cur.fetchone()
    video_id = int(v_row[0])
    cur.execute("select id from transcripts where video_id = %s limit 1", (video_id,))
    t_row = cur.fetchone()
    if t_row is None:
        cur.execute(
            """
            insert into transcripts (video_id, source, storage_pointer)
            values (%s, 'captions', 'local://test') returning id
            """,
            (video_id,),
        )
        t_row = cur.fetchone()
    transcript_id = int(t_row[0])
    return analyst_id, video_id, transcript_id


def _seed_claim_db(
    cur: Any,
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    *,
    asset: str = "BTC",
    direction: str = "bullish",
    horizon_deadline: str | None = "2025-06-30",
    horizon_basis: str = "stated",
    specificity_class: str = "direction_only",
    uttered_at: str = "2025-01-01 00:00:00+00",
    p0_price: float = 80000.0,
    flags: str = "{}",
) -> int:
    cur.execute(
        """
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            specificity_class, source_offset_seconds,
            quote, uttered_at, p0_price,
            model_version, prompt_version,
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            %s, %s,
            %s, %s,
            0.7, 'stated',
            %s, 0,
            'contradiction test fewer than fifteen words.',
            %s, %s,
            'test', 'test',
            'approved', true, 'open', %s
        ) returning id
        """,
        (
            analyst_id,
            video_id,
            transcript_id,
            asset,
            direction,
            horizon_deadline,
            horizon_basis,
            specificity_class,
            uttered_at,
            p0_price,
            flags,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_contradiction_prepass_voids_claims_and_no_resolution_rows(db_conn: Any) -> None:
    """Resolver contradiction pre-pass: both contradicting claims voided in DB,
    hedging flag set, and NO resolution rows inserted for them.

    Scenario:
      - One analyst, two claims on BTC: one bullish, one bearish.
      - Both open, publishable, overlapping horizons (stated, same deadline).
      - A third independent claim (ETH bullish) must still resolve normally.
    """
    source = FakePriceSource(FIXTURES)

    with db_conn.cursor() as cur:
        # Isolate: resolve all pre-existing open claims so only our seeds matter.
        cur.execute("update claims set status = 'resolved' where status = 'open'")
        analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

        # Contradicting pair: BTC bullish + BTC bearish, same deadline.
        bull_id = _seed_claim_db(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bullish",
            horizon_deadline="2025-06-30",
            horizon_basis="stated",
            specificity_class="direction_only",
            uttered_at="2025-01-05 00:00:00+00",
            p0_price=80000.0,
        )
        bear_id = _seed_claim_db(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="BTC",
            direction="bearish",
            horizon_deadline="2025-06-30",
            horizon_basis="stated",
            specificity_class="direction_only",
            uttered_at="2025-01-05 00:00:00+00",
            p0_price=80000.0,
        )
        # Independent ETH claim (should resolve normally).
        eth_id = _seed_claim_db(
            cur,
            analyst_id,
            video_id,
            transcript_id,
            asset="ETH",
            direction="bullish",
            horizon_deadline="2025-04-05",
            horizon_basis="stated",
            specificity_class="direction_only",
            uttered_at="2025-01-05 00:00:00+00",
            p0_price=3000.0,
        )

    resolutions = resolve_open_claims(prices=source, conn=db_conn)

    # 1. No resolution rows for either contradicting claim.
    resolution_claim_ids = {r.claim_id for r in resolutions}
    assert bull_id not in resolution_claim_ids, (
        "BTC bullish contradicted claim must not have a resolution row"
    )
    assert bear_id not in resolution_claim_ids, (
        "BTC bearish contradicted claim must not have a resolution row"
    )

    # 2. Both contradicting claims must be status=void in DB.
    with db_conn.cursor() as cur:
        cur.execute(
            "select id, status, flags from claims where id = any(%s)",
            ([bull_id, bear_id],),
        )
        rows = cur.fetchall()

    assert len(rows) == 2
    flags_by_id: dict[int, dict[str, Any]] = {}
    for row in rows:
        cid, status_val, flags_val = row
        assert str(status_val) == "void", f"Claim {cid} expected status=void, got {status_val!r}"
        flags_dict: dict[str, Any] = (
            flags_val if isinstance(flags_val, dict) else json.loads(flags_val)
        )
        assert flags_dict.get("hedging_contradiction") is True, (
            f"Claim {cid} missing hedging_contradiction flag"
        )
        assert flags_dict.get("void_rule_id") == "contradiction_void.v0", (
            f"Claim {cid} missing/incorrect void_rule_id"
        )
        flags_by_id[int(cid)] = flags_dict
    # The contradicts_claim_ids must name the actual counterpart (not just exist).
    assert flags_by_id[bull_id]["contradicts_claim_ids"] == [bear_id]
    assert flags_by_id[bear_id]["contradicts_claim_ids"] == [bull_id]

    # 3. Verify no resolution rows in DB for the contradicted claims.
    with db_conn.cursor() as cur:
        cur.execute(
            "select count(*) from resolutions where claim_id = any(%s)",
            ([bull_id, bear_id],),
        )
        count_row = cur.fetchone()
    assert count_row is not None
    assert int(count_row[0]) == 0, "No resolution rows must exist for contradiction-voided claims"

    # 4. The ETH claim must still have resolved (it's not contradicted).
    with db_conn.cursor() as cur:
        cur.execute("select status from claims where id = %s", (eth_id,))
        eth_row = cur.fetchone()
    assert eth_row is not None
    # ETH should have resolved (either 'resolved' or still 'open' if price data missing;
    # the key assertion is that it was NOT voided as a side effect of contradiction detection).
    assert str(eth_row[0]) != "void", (
        "Independent ETH claim must not be voided by contradiction detection"
    )
