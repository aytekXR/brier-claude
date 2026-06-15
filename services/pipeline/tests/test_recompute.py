"""E4-T5: recompute_all tests — full-history methodology recompute mechanism.

Tests cover:
  - recompute_all writes a NEW score_run with trigger='methodology_bump' and the
    passed methodology_version.
  - Prior score_run + scores remain queryable and unchanged after recompute (AC-4/HP-6).
  - Append-only invariant: row counts only grow; no prior rows are updated/deleted.
  - Every analyst present in the prior run appears in the new run.
  - Recomputing under the SAME version as a prior run still creates a distinct run.
  - recompute_all returns the new score_run id, which is the max(score_runs.id).

All tests use the db_conn rolled-back fixture so writes never persist to the
dev database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from brier_pipeline.scoring.fas import recompute_all, run_score_pass

# ---------------------------------------------------------------------------
# Seed helper (mirrors pattern in test_fas.py:_seed_scoring_data)
# ---------------------------------------------------------------------------


def _returned_id(cur: psycopg.Cursor[Any]) -> int:
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _count(cur: psycopg.Cursor[Any], table: str) -> int:
    """Row count for an append-only ledger table (identifier is test-controlled)."""
    cur.execute(f"select count(*) from {table}")
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_two_analysts(cur: psycopg.Cursor[Any]) -> tuple[int, int]:
    """Insert two analysts each with 25 resolved claims.

    Returns (analyst_a_id, analyst_b_id).
    """
    analyst_ids: list[int] = []
    for label in ("rc-test-a", "rc-test-b"):
        cur.execute(
            """
            insert into analysts (channel_id, display_name, slug)
            values (%s, %s, %s)
            returning id
            """,
            (f"UC-{label}", f"Recompute Test {label}", label),
        )
        analyst_ids.append(_returned_id(cur))

    for analyst_id in analyst_ids:
        cur.execute(
            """
            insert into videos (analyst_id, youtube_video_id, title, published_at)
            values (%s, %s, 'test video', now()) returning id
            """,
            (analyst_id, f"vid-rc-{analyst_id}"),
        )
        video_id = _returned_id(cur)
        cur.execute(
            """
            insert into transcripts (video_id, source, storage_pointer)
            values (%s, 'captions', 'local://test') returning id
            """,
            (video_id,),
        )
        transcript_id = _returned_id(cur)

        for i in range(25):
            cur.execute(
                """
                insert into claims (
                    analyst_id, video_id, transcript_id, asset, direction,
                    specificity_class, source_offset_seconds,
                    model_version, prompt_version, uttered_at,
                    review_state, publishable, status,
                    stated_confidence, flags
                ) values (
                    %s, %s, %s, 'BTC', 'bullish',
                    'direction_only', %s,
                    'test-v0', 'test-v0', %s,
                    'approved', true, 'resolved',
                    0.7,
                    %s::jsonb
                ) returning id
                """,
                (
                    analyst_id,
                    video_id,
                    transcript_id,
                    i,
                    datetime(2024, 1, 1, tzinfo=UTC).isoformat(),
                    '{"fixture_base_rate": 0.5}',
                ),
            )
            claim_id = _returned_id(cur)
            cur.execute(
                """
                insert into resolutions (claim_id, outcome, rule_id, rationale,
                                         price_citation, methodology_version)
                values (%s, 1, 'test', 'test', '{}'::jsonb, 'v1.0')
                """,
                (claim_id,),
            )

    return analyst_ids[0], analyst_ids[1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_recompute_all_writes_new_score_run(db_conn: psycopg.Connection[Any]) -> None:
    """recompute_all writes a new score_run with trigger=methodology_bump and v='v1.1'."""
    with db_conn.cursor() as cur:
        _seed_two_analysts(cur)

    # Initial run under the current methodology
    run_id_1, _ = run_score_pass("demo", conn=db_conn)

    # Recompute under a new version
    new_run_id = recompute_all("v1.1", conn=db_conn)

    assert new_run_id != run_id_1, "recompute must create a distinct score_run"

    with db_conn.cursor() as cur:
        cur.execute(
            "select methodology_version, trigger, notes from score_runs where id = %s",
            (new_run_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "v1.1", f"expected methodology_version='v1.1', got {row[0]!r}"
    assert row[1] == "methodology_bump", f"expected trigger='methodology_bump', got {row[1]!r}"
    assert row[2] is not None and "v1.1" in row[2], (
        f"notes must reference the new version; got {row[2]!r}"
    )


def test_recompute_all_stamps_scores_with_new_version(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Every scores row written by recompute_all carries the new methodology_version."""
    with db_conn.cursor() as cur:
        _seed_two_analysts(cur)

    run_score_pass("demo", conn=db_conn)
    new_run_id = recompute_all("v1.1", conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute(
            "select count(*), count(*) filter (where methodology_version = 'v1.1') "
            "from scores where score_run_id = %s",
            (new_run_id,),
        )
        row = cur.fetchone()
    assert row is not None
    total, versioned = int(row[0]), int(row[1])
    assert total >= 2, "expected at least one scores row per analyst"
    assert total == versioned, f"all {total} score rows must be stamped v1.1, only {versioned} were"


def test_prior_score_run_survives_recompute(db_conn: psycopg.Connection[Any]) -> None:
    """AC-4/HP-6: the prior score_run and its scores are queryable and unchanged after recompute."""
    with db_conn.cursor() as cur:
        analyst_a_id, analyst_b_id = _seed_two_analysts(cur)

    run_id_1, prior_scores = run_score_pass("demo", conn=db_conn)

    # Capture prior FAS values before the recompute
    prior_fas: dict[int, float] = {s.analyst_id: s.fas for s in prior_scores}

    new_run_id = recompute_all("v1.1", conn=db_conn)
    assert new_run_id != run_id_1

    # Prior score_run row still exists
    with db_conn.cursor() as cur:
        cur.execute("select id from score_runs where id = %s", (run_id_1,))
        row = cur.fetchone()
    assert row is not None, "prior score_run must still exist after recompute"

    # Prior scores rows still exist and values are unchanged
    with db_conn.cursor() as cur:
        cur.execute(
            "select analyst_id, fas from scores where score_run_id = %s",
            (run_id_1,),
        )
        rows = cur.fetchall()

    assert len(rows) >= 2, "prior scores rows must still exist after recompute"
    for r in rows:
        aid, fas = int(r[0]), float(r[1])
        assert aid in prior_fas, f"analyst {aid} missing from prior_fas dict"
        assert abs(fas - prior_fas[aid]) < 1e-9, (
            f"prior FAS for analyst {aid} changed after recompute: was {prior_fas[aid]}, now {fas}"
        )


def test_recompute_append_only_row_counts_only_grow(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Append-only invariant: score_runs and scores row counts strictly increase."""
    with db_conn.cursor() as cur:
        _seed_two_analysts(cur)

    run_score_pass("demo", conn=db_conn)

    with db_conn.cursor() as cur:
        runs_before = _count(cur, "score_runs")
        scores_before = _count(cur, "scores")

    recompute_all("v1.1", conn=db_conn)

    with db_conn.cursor() as cur:
        runs_after = _count(cur, "score_runs")
        scores_after = _count(cur, "scores")

    assert runs_after > runs_before, "score_runs count must increase after recompute"
    assert scores_after > scores_before, "scores count must increase after recompute"


def test_recompute_all_analysts_present_in_new_run(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Every analyst present in the prior run appears in the new run."""
    with db_conn.cursor() as cur:
        analyst_a_id, analyst_b_id = _seed_two_analysts(cur)

    run_id_1, prior_scores = run_score_pass("demo", conn=db_conn)
    prior_analyst_ids = {s.analyst_id for s in prior_scores}

    new_run_id = recompute_all("v1.1", conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute(
            "select analyst_id from scores where score_run_id = %s",
            (new_run_id,),
        )
        new_analyst_ids = {int(r[0]) for r in cur.fetchall()}

    assert prior_analyst_ids <= new_analyst_ids, (
        f"analysts {prior_analyst_ids - new_analyst_ids} present in prior run "
        "but missing from new run"
    )


def test_recompute_same_version_creates_distinct_run(
    db_conn: psycopg.Connection[Any],
) -> None:
    """Recomputing under the same version as a prior run still creates a new distinct score_run."""
    with db_conn.cursor() as cur:
        _seed_two_analysts(cur)

    run_id_1, _ = run_score_pass("demo", conn=db_conn)

    # Recompute under the same version string as the initial run (v1.0)
    new_run_id = recompute_all("v1.0", conn=db_conn)

    assert new_run_id != run_id_1, (
        "recomputing under the same version must produce a new, distinct score_run"
    )

    # Both runs must exist
    with db_conn.cursor() as cur:
        cur.execute(
            "select count(*) from score_runs where id in (%s, %s)",
            (run_id_1, new_run_id),
        )
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 2, "both score_runs must exist simultaneously"


def test_recompute_all_returns_max_score_run_id(
    db_conn: psycopg.Connection[Any],
) -> None:
    """recompute_all returns the new score_run id, which equals max(score_runs.id)."""
    with db_conn.cursor() as cur:
        _seed_two_analysts(cur)

    run_score_pass("demo", conn=db_conn)
    new_run_id = recompute_all("v1.1", conn=db_conn)

    with db_conn.cursor() as cur:
        cur.execute("select max(id) from score_runs")
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == new_run_id, (
        f"returned id {new_run_id} must equal max(score_runs.id) {row[0]}"
    )


def test_recompute_prior_scores_no_trigger_violation(
    db_conn: psycopg.Connection[Any],
) -> None:
    """recompute_all must not UPDATE or DELETE prior scores (append-only trigger)."""
    with db_conn.cursor() as cur:
        _seed_two_analysts(cur)

    run_id_1, prior_scores = run_score_pass("demo", conn=db_conn)
    assert len(prior_scores) > 0
    prior_score_id = prior_scores[0].id
    assert prior_score_id is not None

    # Recompute must not raise any trigger exception
    recompute_all("v1.1", conn=db_conn)

    # Confirm the prior score row is still untouched
    with db_conn.cursor() as cur:
        cur.execute("select fas from scores where id = %s", (prior_score_id,))
        row = cur.fetchone()
    assert row is not None, "prior score row must still exist after recompute"
    expected_fas = prior_scores[0].fas
    assert abs(float(row[0]) - expected_fas) < 1e-9, (
        f"prior score fas must be unmodified: expected {expected_fas}, got {row[0]}"
    )
