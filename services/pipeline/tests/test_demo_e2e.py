"""E1-T4 end-to-end demo tests: run_demo() against the dev DB.

These tests commit real data (consistent with the existing demo test pattern —
the demo is the product demo, not a unit test). They are order-independent
and re-runnable: each test calls run_demo() which is idempotent for
videos/transcripts/claims/resolutions, and always appends a new score_run.

Assertions:
  - All resolvable fixture claims are resolved (derived from claims.json, no
    magic numbers).
  - HP-2 claim (hp2-btc-80k) resolves outcome=1 with citation day 2025-07-14
    and close 80140.
  - Each analyst has a scores row tagged v1.1 under the new score_run.
  - FAS INVERSION (v1.1): VectorEdge FAS > Aylin Markets FAS while Aylin
    Markets raw hit rate > VectorEdge raw hit rate.  Under v1.0 the
    illustrative pair was NorthChain vs Aylin; v1.1 real base rates from the
    ~18-month BTC fixture changed the NC base rates dramatically (all 90-day
    windows Dec 2024-Apr 2025 were bearish-close, giving real_b=0.000 for
    bullish NC calls), removing that inversion. The VE-vs-Aylin inversion
    has TWO distinct mechanisms (be precise — this is the credibility moat):
      * Aylin's suppression is GENUINELY MEASURED: ay-07 (BTC bearish) gets
        real_b=1.000 from trailing fixture history — an obvious call that HIT but
        earns zero DS credit. Her remaining hedge calls (ay-03/04/05/08/10) form
        EC-6 opposite-direction pairs VOIDED by the contradiction pre-pass
        (E4-T4) before scoring, so a hedger's contradictory bets never pad the
        record. Net: Aylin resolves 3/5 = 60% with mean DS ~= 0.0. (ay-09 is
        conditional/PENDING, never scored.)
      * VectorEdge's positive DS is the MIN-WINDOWS FALLBACK, not a measured
        prior: ve-01/02/03 (Dec 2024) have only ~14 trailing fixture windows
        (< MIN_BASE_RATE_WINDOWS=20), so they get b=0.5 — numerically identical
        to the old fixture placeholder, just routed through the published
        convention. So half the inversion is a thin-fixture artifact; with real
        5-year history these priors would be measured (E4-T2, ADR-0009).
  - Second run_demo() adds no videos/transcripts/claims/resolutions and adds
    exactly one new score_run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from brier_pipeline.config import METHODOLOGY_VERSION

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"


def _load_fixture_claims() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "claims.json").read_text(encoding="utf-8"))


# Fixture claims that form EC-6 contradiction pairs (opposite direction, same
# asset, overlapping horizon, same analyst) are VOIDED by the demo's
# contradiction pre-pass (E4-T4, rule contradiction_void.v0) BEFORE resolution,
# so they never reach status='resolved' in the full thread.  Their *isolated*
# resolution outcomes (HIT/MISS) remain covered by
# test_resolution.py::test_fixture_sweep — only the end-to-end demo applies
# contradiction detection, so only this thread-level count subtracts them.
# This set is asserted against the actual demo DB in
# test_contradiction_voided_set_matches_db so it cannot silently drift.
_CONTRADICTION_VOIDED_FIXTURE_IDS = {
    "ay-03",  # Aylin BTC bullish  <-> ay-05 BTC bearish
    "ay-05",  # Aylin BTC bearish  <-> ay-03 BTC bullish
    "ay-04",  # Aylin ETH bullish  <-> ay-08 ETH bearish
    "ay-08",  # Aylin ETH bearish  <-> ay-04 ETH bullish
    "ay-10",  # Aylin BTC bullish  <-> ay-09 BTC bearish (conditional)
    "ve-07",  # VectorEdge ETH bearish <-> ve-open-eth ETH bullish
}


def _resolvable_fixture_count() -> int:
    """Count fixture claims the demo thread resolves to status='resolved'.

    Excludes non-resolvable expected outcomes (open/pending/non_falsifiable),
    conditional/non_falsifiable specificity, and the EC-6 contradiction-voided
    claims that the demo's contradiction pre-pass removes before resolution.
    """
    claims = _load_fixture_claims()
    skip = {"non_falsifiable", "OPEN", "PENDING"}
    return sum(
        1
        for c in claims
        if c.get("expected_outcome") not in skip
        and c.get("specificity_class") not in ("non_falsifiable", "conditional")
        and c.get("fixture_id") not in _CONTRADICTION_VOIDED_FIXTURE_IDS
    )


@pytest.fixture
def db_conn_live() -> Any:
    """A COMMITTING connection to the dev database; skips if unreachable.

    Unlike the rolled-back db_conn fixture, this one commits so the demo
    writes persist. Tests using this fixture depend on run_demo() idempotency.
    """
    from brier_pipeline.config import database_url

    try:
        conn = psycopg.connect(database_url(), connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("dev database not running (docker compose up -d db && make seed)")
    yield conn
    conn.close()


def _get_analyst_id(conn: Any, slug: str) -> int:
    with conn.cursor() as cur:
        cur.execute("select id from analysts where slug = %s", (slug,))
        row = cur.fetchone()
        assert row is not None, f"Analyst {slug!r} not found — run make seed first"
        return int(row[0])


class TestResolvableClaimsAreResolved:
    """All resolvable fixture claims must be in status='resolved' after run_demo."""

    def test_all_resolvable_claims_resolved(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        run_demo()

        expected_count = _resolvable_fixture_count()
        with db_conn_live.cursor() as cur:
            cur.execute(
                """
                select count(*) from claims c
                join resolutions r on r.claim_id = c.id
                where c.status = 'resolved'
                  and c.specificity_class not in ('non_falsifiable', 'conditional')
                  and not exists (
                      select 1 from resolutions r2
                      where r2.supersedes_resolution_id = r.id
                  )
                """
            )
            row = cur.fetchone()
        assert row is not None
        actual = int(row[0])
        assert actual == expected_count, (
            f"Expected {expected_count} resolved claims (from claims.json), got {actual}"
        )

    def test_contradiction_voided_set_matches_db(self, db_conn_live: Any) -> None:
        """Guard: the documented contradiction-voided set must equal what the
        demo actually voids among otherwise-resolvable fixtures.

        Prevents _CONTRADICTION_VOIDED_FIXTURE_IDS from silently drifting away
        from the contradiction pre-pass behaviour (E4-T4) — if the rules or
        fixtures change the void set, this fails loudly rather than masking a
        wrong resolvable count.
        """
        from brier_pipeline.demo import run_demo

        run_demo()

        fixtures = {c["fixture_id"]: c for c in _load_fixture_claims()}
        with db_conn_live.cursor() as cur:
            cur.execute(
                """
                select c.flags->>'fixture_id'
                from claims c
                where c.flags->>'void_rule_id' = 'contradiction_void.v0'
                """
            )
            voided_fixture_ids = {row[0] for row in cur.fetchall()}

        # Among voided claims, the ones that WOULD otherwise be counted as
        # resolvable (HIT/MISS, non-conditional, non-non_falsifiable).
        skip = {"non_falsifiable", "OPEN", "PENDING"}
        counted_voided = {
            fid
            for fid in voided_fixture_ids
            if fid in fixtures
            and fixtures[fid].get("expected_outcome") not in skip
            and fixtures[fid].get("specificity_class") not in ("non_falsifiable", "conditional")
        }
        assert counted_voided == _CONTRADICTION_VOIDED_FIXTURE_IDS, (
            "Contradiction-voided resolvable set drifted from the documented "
            f"constant: DB={sorted(counted_voided)}, "
            f"expected={sorted(_CONTRADICTION_VOIDED_FIXTURE_IDS)}"
        )

    def test_no_resolvable_claims_remain_open(self, db_conn_live: Any) -> None:
        """After run_demo, no non-conditional, non-future claims should be open."""
        from brier_pipeline.demo import run_demo

        run_demo()

        with db_conn_live.cursor() as cur:
            # Claims with past deadlines that v0 can handle should be resolved
            cur.execute(
                """
                select count(*) from claims
                where status = 'open'
                  and publishable = true
                  and specificity_class not in ('non_falsifiable', 'conditional')
                  and horizon_deadline <= '2026-06-11'
                """
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 0, f"Found {row[0]} resolvable open claims with past deadlines"


class TestHP2Canonical:
    """HP-2 canonical claim: BTC daily close above $80k by Jul 31 -> HIT on Jul 14."""

    def test_hp2_resolved_hit(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        run_demo()

        with db_conn_live.cursor() as cur:
            # Find the hp2-btc-80k claim
            cur.execute(
                """
                select c.id, c.status
                from claims c
                where c.flags->>'fixture_id' = 'hp2-btc-80k'
                """
            )
            row = cur.fetchone()
        assert row is not None, "hp2-btc-80k claim not found in DB"
        claim_id = int(row[0])
        assert str(row[1]) == "resolved", (
            f"hp2-btc-80k claim status is {row[1]!r}, expected 'resolved'"
        )

        with db_conn_live.cursor() as cur:
            cur.execute(
                """
                select r.outcome, r.price_citation
                from resolutions r
                where r.claim_id = %s
                  and not exists (
                      select 1 from resolutions r2
                      where r2.supersedes_resolution_id = r.id
                  )
                """,
                (claim_id,),
            )
            row = cur.fetchone()
        assert row is not None, "No resolution row for hp2-btc-80k"
        assert float(row[0]) == 1.0, f"HP-2 outcome expected 1.0 (HIT), got {row[0]}"

        citation = row[1] if isinstance(row[1], dict) else {}
        assert citation.get("day") == "2025-07-14", (
            f"HP-2 citation day expected '2025-07-14', got {citation.get('day')!r}"
        )
        assert float(citation.get("close_usd", 0)) == 80140.0, (
            f"HP-2 citation close_usd expected 80140.0, got {citation.get('close_usd')}"
        )


class TestScoresLedger:
    """Scores rows exist per analyst tagged v1.0 under the new score_run."""

    def test_scores_exist_per_analyst_after_run(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        result = run_demo()
        run_id = result["score_run_id"]

        with db_conn_live.cursor() as cur:
            cur.execute(
                """
                select s.analyst_id, s.fas, s.n_resolved, s.methodology_version
                from scores s
                where s.score_run_id = %s
                order by s.analyst_id
                """,
                (run_id,),
            )
            rows = cur.fetchall()

        # Must have one score per analyst (3 fixture analysts)
        assert len(rows) == 3, f"Expected 3 score rows for run {run_id}, got {len(rows)}"
        for row in rows:
            assert str(row[3]) == METHODOLOGY_VERSION, (
                f"Methodology version mismatch: expected {METHODOLOGY_VERSION!r}, got {row[3]!r}"
            )

    def test_scores_tagged_correct_methodology_version(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        result = run_demo()
        run_id = result["score_run_id"]

        with db_conn_live.cursor() as cur:
            cur.execute(
                "select count(*) from scores where score_run_id = %s and methodology_version = %s",
                (run_id, METHODOLOGY_VERSION),
            )
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 3


class TestFASInversion:
    """FAS inversion (v1.1): VectorEdge FAS > Aylin Markets FAS, Aylin hit rate > VectorEdge.

    Under v1.0 the illustrative pair was NorthChain vs Aylin Markets.  v1.1 real
    base rates (E4-T2, ADR-0009) changed the NorthChain base rates: all 90-day
    windows in the ~18-month BTC fixture from Dec 2024 to Apr 2025 are bearish-close,
    giving real_b=0.000 for every NorthChain bullish call uttered in Apr 2025.
    Because those calls still HIT (BTC was above p0 at the deadline), the (y-b)
    DS term becomes (1.0-0.0)=1.0 — the maximum reward — reversing the NC-Aylin
    inversion.

    The VectorEdge-vs-Aylin inversion under v1.1 has two DISTINCT mechanisms — be
    precise about which is measured vs a fixture artifact (this is the moat):
      * Aylin's DS suppression is GENUINELY MEASURED. ay-07 (BTC bearish) gets
        real_b=1.000 from trailing fixture history (every same-horizon window in
        that slice was a bearish win), so that HIT earns zero DS credit. Aylin's
        other hedge calls (ay-03/04/05/08/10) are opposite-direction EC-6 pairs
        VOIDED by the contradiction pre-pass (E4-T4) before scoring, so her
        contradictory bets never pad the record. She resolves 3/5 = 60% with mean
        DS ~= 0.0. (ay-09 is a conditional/PENDING claim, never scored — the
        scoring SQL filters to status='resolved'.)
      * VectorEdge's positive DS is the MIN-WINDOWS FALLBACK, not a measured prior.
        ve-01/ve-02/ve-03 (Dec 2024 calls) have only ~14 trailing fixture windows,
        below MIN_BASE_RATE_WINDOWS=20, so each gets b=0.5 — numerically identical
        to the old fixture_base_rate placeholder, now routed through the published
        convention. Half the inversion is therefore a thin-fixture artifact; with
        real 5-year history these priors would be measured. The inversion still
        honestly demonstrates "higher raw hit rate does not imply higher FAS," but
        the VE half is fallback-driven, not base-rate signal (E4-T2, ADR-0009).
    """

    def test_fas_inversion_holds(self, db_conn_live: Any) -> None:
        """VectorEdge ranks above Aylin Markets on FAS despite lower raw hit rate (v1.1).

        v1.1 base-rate change (E4-T2, ADR-0009): real trailing-history base rates
        replace fixture_base_rate placeholders.  The illustrative inversion pair
        changed from (NorthChain, AylinMarkets) to (VectorEdge, AylinMarkets) — see
        class docstring for the full explanation.
        """
        from brier_pipeline.demo import run_demo

        result = run_demo()
        run_id = result["score_run_id"]

        aylin_id = _get_analyst_id(db_conn_live, "aylin-markets")
        ve_id = _get_analyst_id(db_conn_live, "vectoredge")

        with db_conn_live.cursor() as cur:
            cur.execute(
                "select fas from scores where score_run_id = %s and analyst_id = %s",
                (run_id, aylin_id),
            )
            row = cur.fetchone()
            assert row is not None, "No score for aylin-markets"
            aylin_fas = float(row[0])

            cur.execute(
                "select fas from scores where score_run_id = %s and analyst_id = %s",
                (run_id, ve_id),
            )
            row = cur.fetchone()
            assert row is not None, "No score for vectoredge"
            ve_fas = float(row[0])

        # FAS inversion (v1.1): VectorEdge must outrank Aylin Markets.
        # v1.1 real base rates: Aylin's Mar-2025 bearish hits have real_b=1.000
        # (obvious calls), earning no DS credit. VE priors were more neutral.
        assert ve_fas > aylin_fas, (
            f"FAS inversion not present: VectorEdge FAS {ve_fas:.2f} "
            f"is not > Aylin Markets FAS {aylin_fas:.2f}. "
            "Check wiring — do not tune fixtures or formulas. "
            "(v1.1 real base rates; see ADR-0009 and class docstring)"
        )

        # Raw hit rate: Aylin Markets must have higher raw hit rate than VectorEdge.
        # (Aylin: 3/5 resolved = 60%; VectorEdge: 3/6 resolved = 50%) This is
        # the inversion: higher raw hit rate does not imply higher FAS.
        with db_conn_live.cursor() as cur:
            for analyst_id, _name in [(aylin_id, "aylin-markets"), (ve_id, "vectoredge")]:
                cur.execute(
                    """
                    select
                        count(*) as total,
                        sum(case when r.outcome = 1.0 then 1 else 0 end) as hits
                    from claims c
                    join resolutions r on r.claim_id = c.id
                    where c.analyst_id = %s
                      and c.specificity_class != 'non_falsifiable'
                      and not exists (
                          select 1 from resolutions r2
                          where r2.supersedes_resolution_id = r.id
                      )
                    """,
                    (analyst_id,),
                )
                row = cur.fetchone()
                assert row is not None
                if analyst_id == aylin_id:
                    aylin_total = int(row[0])
                    aylin_hits = int(row[1])
                else:
                    ve_total = int(row[0])
                    ve_hits = int(row[1])

        aylin_hit_rate = aylin_hits / aylin_total if aylin_total > 0 else 0.0
        ve_hit_rate = ve_hits / ve_total if ve_total > 0 else 0.0

        assert aylin_hit_rate > ve_hit_rate, (
            f"Aylin Markets raw hit rate {aylin_hit_rate:.3f} is not > "
            f"VectorEdge raw hit rate {ve_hit_rate:.3f}. "
            "The inversion story (v1.1) requires Aylin to have the higher raw hit rate. "
            "Check wiring — do not tune fixtures or formulas."
        )


class TestPricePersistence:
    """price_daily is populated by run_demo(); fixture closes are web-readable."""

    def test_price_daily_row_count(self, db_conn_live: Any) -> None:
        """After run_demo(), price_daily must contain exactly 1674 rows (558 per asset)."""
        from brier_pipeline.demo import run_demo

        run_demo()

        with db_conn_live.cursor() as cur:
            cur.execute("select count(*) from price_daily")
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1674, (
            f"Expected 1674 price_daily rows (558 BTC + 558 ETH + 558 SOL), got {row[0]}"
        )

    def test_hp2_btc_close_readable_from_price_daily(self, db_conn_live: Any) -> None:
        """BTC close on 2025-07-14 (HP-2 citation day) must read 80140.0 from price_daily."""
        from brier_pipeline.demo import run_demo

        run_demo()

        with db_conn_live.cursor() as cur:
            cur.execute(
                "select close_usd from price_daily where asset = 'BTC' and day = '2025-07-14'"
            )
            row = cur.fetchone()
        assert row is not None, "BTC 2025-07-14 not found in price_daily"
        assert float(row[0]) == 80140.0, f"BTC 2025-07-14 close_usd expected 80140.0, got {row[0]}"

    def test_price_persist_idempotent(self, db_conn_live: Any) -> None:
        """Second run_demo() adds 0 new price rows (ON CONFLICT DO NOTHING)."""
        from brier_pipeline.demo import run_demo

        # Ensure first run has seeded price_daily
        run_demo()

        # Second run: prices_persisted must be 0
        result2 = run_demo()

        assert result2["prices_persisted"] == 0, (
            f"Second run inserted {result2['prices_persisted']} price rows; expected 0"
        )

        # Row count must still be 1674 (no duplicates)
        with db_conn_live.cursor() as cur:
            cur.execute("select count(*) from price_daily")
            row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1674, (
            f"price_daily row count after two runs: expected 1674, got {row[0]}"
        )


class TestIdempotency:
    """Second run_demo() adds no videos/transcripts/claims/resolutions,
    adds exactly one new score_run."""

    def test_second_run_adds_no_videos_transcripts_claims(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        # Ensure first run has completed
        run_demo()

        # Second run
        result2 = run_demo()

        assert result2["videos_persisted"] == 0, (
            f"Second run created {result2['videos_persisted']} new videos"
        )
        assert result2["transcripts_persisted"] == 0, (
            f"Second run created {result2['transcripts_persisted']} new transcripts"
        )
        assert result2["claims_persisted"] == 0, (
            f"Second run created {result2['claims_persisted']} new claims"
        )

    def test_second_run_adds_no_resolutions(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        # First run resolves all resolvable claims
        run_demo()

        # Second run: no new resolutions
        result2 = run_demo()

        assert result2["resolutions_this_run"] == 0, (
            f"Second run appended {result2['resolutions_this_run']} resolutions "
            "(expected 0 — all resolvable claims already resolved)"
        )

    def test_second_run_adds_exactly_one_new_score_run(self, db_conn_live: Any) -> None:
        from brier_pipeline.demo import run_demo

        result1 = run_demo()
        result2 = run_demo()

        assert result2["score_run_id"] != result1["score_run_id"], (
            "Second run reused the same score_run_id; expected a new append-only row"
        )

        # Confirm score_run_id incremented (append-only)
        assert result2["score_run_id"] > result1["score_run_id"], (
            f"score_run_id did not advance: run1={result1['score_run_id']}, "
            f"run2={result2['score_run_id']}"
        )

        # Both runs must have 3 score rows
        with db_conn_live.cursor() as cur:
            for run_id in (result1["score_run_id"], result2["score_run_id"]):
                cur.execute(
                    "select count(*) from scores where score_run_id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
                assert row is not None
                assert int(row[0]) == 3, f"Expected 3 score rows for run {run_id}, got {row[0]}"
