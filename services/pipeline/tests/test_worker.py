"""Tests for brier_pipeline.jobs.worker — postgres-backed job queue.

DB-backed tests use the rolled-back db_conn fixture (from conftest.py):
the transaction is rolled back at the end so nothing commits to the dev DB.

The SKIP LOCKED concurrency test opens two *additional* real connections
(committed enqueue + two competing claim transactions) and cleans up after
itself with explicit DELETE + commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from brier_pipeline.config import database_url
from brier_pipeline.jobs import worker
from brier_pipeline.jobs.worker import (
    MAX_ATTEMPTS,
    claim_next_job,
    clear_handlers,
    enqueue_job,
    get_handler,
    mark_done,
    process_one,
    register_handler,
    reschedule_or_fail,
)
from brier_pipeline.models import JobState

# ---------------------------------------------------------------------------
# Handler registry unit tests (no DB needed)
# ---------------------------------------------------------------------------


class TestHandlerRegistry:
    def setup_method(self) -> None:
        clear_handlers()

    def teardown_method(self) -> None:
        clear_handlers()

    def test_register_and_get(self) -> None:
        def my_handler(payload: dict[str, Any], conn: Any) -> None:
            pass

        register_handler("test_kind", my_handler)
        assert get_handler("test_kind") is my_handler

    def test_get_unknown_returns_none(self) -> None:
        assert get_handler("nonexistent_kind") is None

    def test_clear_removes_all(self) -> None:
        register_handler("a", lambda p, c: None)
        register_handler("b", lambda p, c: None)
        clear_handlers()
        assert get_handler("a") is None
        assert get_handler("b") is None

    def test_register_overwrites(self) -> None:
        def handler1(p: dict[str, Any], c: Any) -> None:
            pass

        def handler2(p: dict[str, Any], c: Any) -> None:
            pass

        register_handler("x", handler1)
        register_handler("x", handler2)
        assert get_handler("x") is handler2


# ---------------------------------------------------------------------------
# DB-backed queue operation tests (rolled back by conftest db_conn fixture)
# ---------------------------------------------------------------------------


def test_enqueue_and_claim(db_conn: Any) -> None:
    """enqueue_job then claim_next_job returns it; state=running; attempts==1."""
    job_id = enqueue_job(db_conn, kind="test_enqueue_claim", payload={"x": 1})

    job = claim_next_job(db_conn)
    assert job is not None
    assert job.id == job_id
    assert job.kind == "test_enqueue_claim"
    assert job.payload == {"x": 1}
    assert job.state == JobState.RUNNING
    assert job.attempts == 1

    # Second claim on an empty queue (no more due jobs of this kind) -> None
    second = claim_next_job(db_conn)
    # The job we just claimed is now 'running', so another claim gets None
    # (or a different job unrelated to our test — we just confirm our job isn't returned again)
    if second is not None:
        assert second.id != job_id, "The same job must not be claimed twice"


def test_future_run_at_not_claimed(db_conn: Any) -> None:
    """A job with run_at in the future must NOT be claimed."""
    future = datetime.now(UTC) + timedelta(days=1)
    enqueue_job(db_conn, kind="test_future_job", payload={}, run_at=future)

    # claim_next_job should not return our future job
    job = claim_next_job(db_conn)
    if job is not None:
        assert job.kind != "test_future_job", "Future job must not be claimed"


def test_process_one_success(db_conn: Any) -> None:
    """process_one with a succeeding handler -> job 'done'; returns True."""
    clear_handlers()

    called: list[dict[str, Any]] = []

    def success_handler(payload: dict[str, Any], conn: Any) -> None:
        called.append(payload)

    register_handler("test_success", success_handler)

    job_id = enqueue_job(db_conn, kind="test_success", payload={"key": "value"})

    result = process_one(db_conn)
    assert result is True
    assert called == [{"key": "value"}]

    # Verify job is 'done' in the DB
    with db_conn.cursor() as cur:
        cur.execute("SELECT state FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "done"

    clear_handlers()


def test_process_one_empty_queue(db_conn: Any) -> None:
    """process_one on empty queue (no due jobs) -> returns False."""
    # Drain any due jobs first by marking them done (or just use a unique kind
    # and rely on the fact that our specific kind has no queued jobs).
    # Since we're in a rolled-back txn, the state is whatever the seed left.
    # We check process_one behavior by using handlers={} and relying on the
    # queue being clear (or all jobs being in non-queued states).
    #
    # The safest way: enqueue a future job so there's nothing due,
    # then assert False is returned.
    clear_handlers()

    # Mark ALL queued jobs as 'running' to drain the queue for this test.
    with db_conn.cursor() as cur:
        cur.execute("UPDATE jobs SET state = 'running' WHERE state = 'queued'")

    result = process_one(db_conn, handlers={})
    assert result is False


def test_retry_backoff(db_conn: Any) -> None:
    """A failing handler -> job requeued with incremented attempts + future run_at."""
    clear_handlers()

    def failing_handler(payload: dict[str, Any], conn: Any) -> None:
        raise ValueError("deliberate test failure")

    register_handler("test_retry", failing_handler)

    job_id = enqueue_job(db_conn, kind="test_retry", payload={})

    result = process_one(db_conn)
    assert result is True

    # After one failure: state should be 'queued' (requeued), attempts=1, last_error set
    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT state, attempts, last_error, run_at FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "queued", f"Expected 'queued' after first failure, got {row[0]!r}"
    assert int(row[1]) == 1
    assert row[2] is not None
    assert "deliberate test failure" in str(row[2])
    # run_at must be in the future (back-off applied)
    run_at = row[3]
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=UTC)
    assert run_at > datetime.now(UTC), "run_at must be in the future after back-off"

    clear_handlers()


def test_retry_until_failed(db_conn: Any) -> None:
    """Loop process_one MAX_ATTEMPTS times -> job reaches state 'failed'."""
    clear_handlers()

    def always_fail(payload: dict[str, Any], conn: Any) -> None:
        raise RuntimeError("always fails")

    register_handler("test_exhaust", always_fail)

    job_id = enqueue_job(db_conn, kind="test_exhaust", payload={})

    for iteration in range(MAX_ATTEMPTS):
        # Reset run_at to now so the job is due immediately (avoid real sleeping).
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET run_at = now() - interval '1 second', state = 'queued'"
                " WHERE id = %s AND state = 'queued'",
                (job_id,),
            )

        result = process_one(db_conn)
        assert result is True, f"process_one returned False on iteration {iteration}"

    # After MAX_ATTEMPTS failures the job should be 'failed'
    with db_conn.cursor() as cur:
        cur.execute("SELECT state, attempts FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "failed", (
        f"Expected 'failed' after {MAX_ATTEMPTS} attempts, got {row[0]!r}"
    )
    assert int(row[1]) == MAX_ATTEMPTS

    clear_handlers()


def test_unknown_kind_failure_path(db_conn: Any) -> None:
    """Unknown kind (no handler) goes through failure path; last_error mentions 'no handler'."""
    clear_handlers()

    job_id = enqueue_job(db_conn, kind="completely_unknown_kind_xyz", payload={})

    # First call: unknown kind -> requeued (attempts=1 < MAX_ATTEMPTS)
    result = process_one(db_conn, handlers={})
    assert result is True

    with db_conn.cursor() as cur:
        cur.execute(
            "SELECT state, last_error, attempts FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert "no handler" in str(row[1]).lower()

    # Exhaust remaining attempts to reach 'failed'
    for _ in range(MAX_ATTEMPTS - 1):
        with db_conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET run_at = now() - interval '1 second', state = 'queued'"
                " WHERE id = %s AND state = 'queued'",
                (job_id,),
            )
        process_one(db_conn, handlers={})

    with db_conn.cursor() as cur:
        cur.execute("SELECT state, last_error FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "failed"
    assert "no handler" in str(row[1]).lower()


def test_reschedule_or_fail_requeued(db_conn: Any) -> None:
    """reschedule_or_fail returns 'requeued' when attempts < max_attempts."""
    job_id = enqueue_job(db_conn, kind="test_rof_requeue", payload={})
    # Claim it manually to get it into running state with attempts=1
    job = claim_next_job(db_conn)
    assert job is not None
    assert job.id == job_id

    outcome = reschedule_or_fail(db_conn, job_id, job.attempts, "some error", max_attempts=5)
    assert outcome == "requeued"

    with db_conn.cursor() as cur:
        cur.execute("SELECT state, last_error FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "queued"
    assert str(row[1]) == "some error"


def test_reschedule_or_fail_failed(db_conn: Any) -> None:
    """reschedule_or_fail returns 'failed' when attempts >= max_attempts."""
    job_id = enqueue_job(db_conn, kind="test_rof_fail", payload={})
    job = claim_next_job(db_conn)
    assert job is not None

    outcome = reschedule_or_fail(
        db_conn, job_id, MAX_ATTEMPTS, "final error", max_attempts=MAX_ATTEMPTS
    )
    assert outcome == "failed"

    with db_conn.cursor() as cur:
        cur.execute("SELECT state, last_error FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "failed"
    assert str(row[1]) == "final error"


def test_mark_done(db_conn: Any) -> None:
    """mark_done sets state='done'."""
    job_id = enqueue_job(db_conn, kind="test_mark_done", payload={})
    job = claim_next_job(db_conn)
    assert job is not None
    assert job.id == job_id

    mark_done(db_conn, job_id)

    with db_conn.cursor() as cur:
        cur.execute("SELECT state FROM jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    assert row is not None
    assert str(row[0]) == "done"


# ---------------------------------------------------------------------------
# run_forever loop (fully faked: no DB, no network)
# ---------------------------------------------------------------------------


def test_run_forever_one_iteration(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_forever runs process_one inside a transaction, then closes the conn.

    The DB connection and process_one are faked; a sentinel exception breaks
    the otherwise-infinite loop after one pass so the test terminates. This
    exercises the loop wiring (register defaults -> connect -> transaction ->
    process_one -> finally close) without any real DB or network.
    """
    calls: list[str] = []

    class _StopLoop(Exception):
        pass

    class _FakeTxn:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *exc: object) -> bool:
            return False  # never suppress

    class _FakeConn:
        def transaction(self) -> _FakeTxn:
            return _FakeTxn()

        def close(self) -> None:
            calls.append("closed")

    def fake_process_one(conn: Any, handlers: Any = None) -> bool:
        calls.append("process_one")
        raise _StopLoop

    monkeypatch.setattr(worker, "connect", lambda: _FakeConn())
    monkeypatch.setattr(worker, "process_one", fake_process_one)
    monkeypatch.setattr(worker.time, "sleep", lambda s: calls.append(f"sleep:{s}"))

    with pytest.raises(_StopLoop):
        worker.run_forever(poll_interval_seconds=0.0)

    assert calls.count("process_one") == 1, "process_one must run exactly once before the sentinel"
    assert "closed" in calls, "run_forever must close the connection in its finally block"


# ---------------------------------------------------------------------------
# SKIP LOCKED concurrency test
# ---------------------------------------------------------------------------


def test_skip_locked_concurrency() -> None:
    """Two competing workers claim different jobs; SKIP LOCKED prevents double-claim.

    Opens two additional real connections (committed enqueue, two competing
    claimants).  Cleans up with an explicit DELETE + commit so the dev DB
    is left clean.
    """
    # Unique kind so we can clean up precisely.
    test_kind = f"skip_locked_test_{uuid.uuid4().hex[:8]}"

    try:
        setup_conn = psycopg.connect(database_url(), connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("dev database not running")

    job_ids: list[int] = []
    try:
        # Enqueue 2 jobs and COMMIT so both are visible to other connections.
        with setup_conn.cursor() as cur:
            for i in range(2):
                jid = enqueue_job(setup_conn, kind=test_kind, payload={"n": i})
                job_ids.append(jid)
        setup_conn.commit()
    except Exception:
        setup_conn.rollback()
        setup_conn.close()
        raise

    conn_a: psycopg.Connection[Any] | None = None
    conn_b: psycopg.Connection[Any] | None = None

    try:
        conn_a = psycopg.connect(database_url(), connect_timeout=2)
        conn_b = psycopg.connect(database_url(), connect_timeout=2)

        # Conn A: BEGIN + claim (holds the FOR UPDATE lock, does NOT commit).
        conn_a.autocommit = False
        job_a = claim_next_job(conn_a)
        assert job_a is not None, "conn_a should have claimed a job"
        assert job_a.id in job_ids

        # Conn B: BEGIN + claim — SKIP LOCKED must skip conn_a's row.
        conn_b.autocommit = False
        job_b = claim_next_job(conn_b)
        assert job_b is not None, "conn_b should have claimed the OTHER job"
        assert job_b.id in job_ids

        # The two claimed ids must be distinct.
        assert job_a.id != job_b.id, (
            f"SKIP LOCKED failed: both workers claimed the same job id={job_a.id}"
        )

    finally:
        # Roll back the two competing transactions (don't leave them committed).
        if conn_a is not None:
            try:
                conn_a.rollback()
            except Exception:
                pass
            conn_a.close()
        if conn_b is not None:
            try:
                conn_b.rollback()
            except Exception:
                pass
            conn_b.close()

        # Clean up the committed test rows from setup_conn.
        try:
            with setup_conn.cursor() as cur:
                cur.execute("DELETE FROM jobs WHERE kind = %s", (test_kind,))
            setup_conn.commit()
        except Exception:
            setup_conn.rollback()
        finally:
            setup_conn.close()
