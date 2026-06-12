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
  - Each analyst has a scores row tagged v1.0 under the new score_run.
  - FAS INVERSION: Aylin Markets FAS > NorthChain FAS while NorthChain raw
    hit rate > Aylin raw hit rate.
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


def _resolvable_fixture_count() -> int:
    """Count fixture claims that v0 rules can resolve (not open/pending/non_falsifiable)."""
    claims = _load_fixture_claims()
    skip = {"non_falsifiable", "OPEN", "PENDING"}
    return sum(
        1
        for c in claims
        if c.get("expected_outcome") not in skip
        and c.get("specificity_class") not in ("non_falsifiable", "conditional")
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
    """FAS inversion: Aylin Markets FAS > NorthChain FAS, NorthChain hit rate > Aylin."""

    def test_fas_inversion_holds(self, db_conn_live: Any) -> None:
        """Aylin Markets ranks above NorthChain on FAS despite lower raw hit rate."""
        from brier_pipeline.demo import run_demo

        result = run_demo()
        run_id = result["score_run_id"]

        aylin_id = _get_analyst_id(db_conn_live, "aylin-markets")
        nc_id = _get_analyst_id(db_conn_live, "northchain")

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
                (run_id, nc_id),
            )
            row = cur.fetchone()
            assert row is not None, "No score for northchain"
            nc_fas = float(row[0])

        # FAS inversion: Aylin Markets must outrank NorthChain
        assert aylin_fas > nc_fas, (
            f"FAS inversion not present: Aylin Markets FAS {aylin_fas:.2f} "
            f"is not > NorthChain FAS {nc_fas:.2f}. "
            "Check wiring — do not tune fixtures or formulas."
        )

        # Raw hit rate: NorthChain must have higher raw hit rate than Aylin
        with db_conn_live.cursor() as cur:
            for analyst_id, _name in [(aylin_id, "aylin-markets"), (nc_id, "northchain")]:
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
                    nc_total = int(row[0])
                    nc_hits = int(row[1])

        aylin_hit_rate = aylin_hits / aylin_total if aylin_total > 0 else 0.0
        nc_hit_rate = nc_hits / nc_total if nc_total > 0 else 0.0

        assert nc_hit_rate > aylin_hit_rate, (
            f"NorthChain raw hit rate {nc_hit_rate:.3f} is not > "
            f"Aylin Markets raw hit rate {aylin_hit_rate:.3f}. "
            "The inversion story requires NorthChain to have the higher raw hit rate. "
            "Check wiring — do not tune fixtures or formulas."
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
