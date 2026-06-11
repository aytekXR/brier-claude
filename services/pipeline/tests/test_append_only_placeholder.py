"""Append-only ledger discipline (NFR-3) — placeholder schema test.

Rows in `resolutions` and `scores` are never updated in place; corrections
append a superseding row. The 0005_ledger.sql triggers enforce this at the
database layer; this test proves the triggers fire. It runs only when the dev
database is up (it skips otherwise), so `make check` stays green without Docker.

Pipeline-level tests of correction flows arrive with E4/E6 tasks.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest


def _seed_resolution(cur: psycopg.Cursor[Any]) -> int:
    """Insert the minimal analyst->video->transcript->claim->resolution chain."""
    cur.execute(
        """
        insert into analysts (channel_id, display_name, slug)
        values ('UC-test-append-only', 'Append Only Probe', 'append-only-probe')
        returning id
        """
    )
    analyst_id = cur.fetchone()[0]  # type: ignore[index]
    cur.execute(
        """
        insert into videos (analyst_id, youtube_video_id, title, published_at)
        values (%s, 'vid-append-only', 'probe', now()) returning id
        """,
        (analyst_id,),
    )
    video_id = cur.fetchone()[0]  # type: ignore[index]
    cur.execute(
        """
        insert into transcripts (video_id, source, storage_pointer)
        values (%s, 'captions', 'local://probe') returning id
        """,
        (video_id,),
    )
    transcript_id = cur.fetchone()[0]  # type: ignore[index]
    cur.execute(
        """
        insert into claims (analyst_id, video_id, transcript_id, specificity_class,
                            source_offset_seconds, model_version, prompt_version, uttered_at)
        values (%s, %s, %s, 'target_deadline', 1, 'probe', 'probe', now()) returning id
        """,
        (analyst_id, video_id, transcript_id),
    )
    claim_id = cur.fetchone()[0]  # type: ignore[index]
    cur.execute(
        """
        insert into resolutions (claim_id, outcome, rule_id, rationale,
                                 price_citation, methodology_version)
        values (%s, 1, 'probe', 'probe', '{}'::jsonb, 'v1.0') returning id
        """,
        (claim_id,),
    )
    return int(cur.fetchone()[0])  # type: ignore[index]


def test_resolutions_reject_update_and_delete(db_conn: psycopg.Connection[Any]) -> None:
    with db_conn.cursor() as cur:
        resolution_id = _seed_resolution(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            cur.execute("update resolutions set outcome = 0 where id = %s", (resolution_id,))
    db_conn.rollback()
    with db_conn.cursor() as cur:
        resolution_id = _seed_resolution(cur)
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            cur.execute("delete from resolutions where id = %s", (resolution_id,))
    db_conn.rollback()  # nothing from this test persists


def test_scores_reject_update(db_conn: psycopg.Connection[Any]) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            insert into analysts (channel_id, display_name, slug)
            values ('UC-test-scores', 'Score Probe', 'score-probe') returning id
            """
        )
        analyst_id = cur.fetchone()[0]  # type: ignore[index]
        cur.execute(
            "insert into score_runs (methodology_version, trigger) "
            "values ('v1.0', 'demo') returning id"
        )
        run_id = cur.fetchone()[0]  # type: ignore[index]
        cur.execute(
            """
            insert into scores (score_run_id, analyst_id, methodology_version, fas,
                                directional_skill, calibration, consistency, falsifiability,
                                n_resolved, ranked, provisional)
            values (%s, %s, 'v1.0', 50, 0, 0, 0, 0, 0, false, true) returning id
            """,
            (run_id, analyst_id),
        )
        score_id = cur.fetchone()[0]  # type: ignore[index]
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            cur.execute("update scores set fas = 99 where id = %s", (score_id,))
    db_conn.rollback()
