"""Cron-style worker loop over the `jobs` table.

Polls for due jobs (state=queued, run_at <= now), claims one atomically
with SELECT ... FOR UPDATE SKIP LOCKED, dispatches by kind, records
attempts and errors. Implements NFR-5 cost-sane exponential back-off.

Canonical job kinds (registered by their respective epics when imported):
  poll_channels   — E2-T2: scan registered channels for new uploads
  transcribe      — E2-T4: acquire captions / run Whisper / Deepgram
  extract         — E3-T2: LLM extraction pass
  resolve_claims  — E1-T3: run resolution engine over open claims
  score_analysts  — E1-T2: compute FAS scores and append to ledger
  weekly_digest   — future: weekly email / report job
  freshness_check — E6-T2: alert when an analyst channel goes stale

Design: E3/E4 register handlers by importing worker and calling
register_handler() — the loop itself stays unchanged.

Constants (NFR-5 cost-sane retries):
  MAX_ATTEMPTS         = 5    — after this many failures the job is 'failed'
  BACKOFF_BASE_SECONDS = 30   — first retry delay
  BACKOFF_MAX_SECONDS  = 3600 — cap at 1 hour
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import psycopg

from brier_pipeline.db import connect
from brier_pipeline.models import Job, JobState

# ---------------------------------------------------------------------------
# Retry constants (NFR-5)
# ---------------------------------------------------------------------------

MAX_ATTEMPTS: int = 5
BACKOFF_BASE_SECONDS: int = 30
BACKOFF_MAX_SECONDS: int = 3600

# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------

JobHandler = Callable[[dict[str, Any], psycopg.Connection[Any]], None]

_registry: dict[str, JobHandler] = {}


def register_handler(kind: str, handler: JobHandler) -> None:
    """Register a handler callable for the given job kind.

    E3/E4 modules call this at import time (or in their own register_*
    functions) so the worker loop dispatches to them without coupling.
    """
    _registry[kind] = handler


def get_handler(kind: str) -> JobHandler | None:
    """Return the registered handler for *kind*, or None if unknown."""
    return _registry.get(kind)


def clear_handlers() -> None:
    """Remove all registered handlers.  Test helper — not for production use."""
    _registry.clear()


# ---------------------------------------------------------------------------
# Queue operations
# ---------------------------------------------------------------------------


def enqueue_job(
    conn: psycopg.Connection[Any],
    kind: str,
    payload: dict[str, Any] | None = None,
    run_at: datetime | None = None,
) -> int:
    """INSERT a new job row in state 'queued' and return its id.

    Caller owns the transaction; this function does not commit.
    run_at defaults to now() inside Postgres when None.
    """
    payload_val = payload or {}
    with conn.cursor() as cur:
        if run_at is None:
            cur.execute(
                """
                INSERT INTO jobs (kind, payload, state)
                VALUES (%s, %s, 'queued')
                RETURNING id
                """,
                (kind, json.dumps(payload_val)),
            )
        else:
            cur.execute(
                """
                INSERT INTO jobs (kind, payload, run_at, state)
                VALUES (%s, %s, %s, 'queued')
                RETURNING id
                """,
                (kind, json.dumps(payload_val), run_at),
            )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def claim_next_job(conn: psycopg.Connection[Any]) -> Job | None:
    """Atomically claim the next DUE queued job; return None when idle.

    Uses SELECT ... FOR UPDATE SKIP LOCKED so multiple worker processes can
    safely compete without blocking each other.  The caller MUST hold the
    surrounding transaction open until it has finished processing the job
    (so the row lock is not released prematurely).

    The returned Job has attempts already incremented by 1 (the 'running'
    attempt count).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, kind, payload, run_at, state, attempts, last_error,
                   created_at, updated_at
            FROM   jobs
            WHERE  state = 'queued'
              AND  run_at <= now()
            ORDER  BY run_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT  1
            """
        )
        row = cur.fetchone()
        if row is None:
            return None

        job_id, kind, payload, run_at, _state, attempts, last_error, _created_at, _updated_at = row

        new_attempts = int(attempts) + 1

        cur.execute(
            """
            UPDATE jobs
            SET    state      = 'running',
                   attempts   = %s,
                   updated_at = now()
            WHERE  id = %s
            """,
            (new_attempts, job_id),
        )

        return Job(
            id=int(job_id),
            kind=str(kind),
            payload=payload if isinstance(payload, dict) else {},
            run_at=run_at,
            state=JobState.RUNNING,
            attempts=new_attempts,
            last_error=last_error,
        )


def mark_done(conn: psycopg.Connection[Any], job_id: int) -> None:
    """Transition a job to state='done'.  Caller owns the transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET    state      = 'done',
                   updated_at = now()
            WHERE  id = %s
            """,
            (job_id,),
        )


def reschedule_or_fail(
    conn: psycopg.Connection[Any],
    job_id: int,
    attempts: int,
    error: str,
    *,
    max_attempts: int = MAX_ATTEMPTS,
) -> str:
    """Record an error and either requeue with back-off or mark as failed.

    Back-off is exponential: BACKOFF_BASE_SECONDS * 2 ** (attempts - 1),
    capped at BACKOFF_MAX_SECONDS.  The interval is computed via Postgres
    make_interval() so the arithmetic stays in the DB.

    Returns 'requeued' or 'failed'.
    """
    if attempts < max_attempts:
        raw_delay = BACKOFF_BASE_SECONDS * (2 ** (attempts - 1))
        delay_seconds = min(raw_delay, BACKOFF_MAX_SECONDS)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET    state      = 'queued',
                       run_at     = now() + make_interval(secs => %s),
                       last_error = %s,
                       updated_at = now()
                WHERE  id = %s
                """,
                (float(delay_seconds), error, job_id),
            )
        return "requeued"
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET    state      = 'failed',
                       last_error = %s,
                       updated_at = now()
                WHERE  id = %s
                """,
                (error, job_id),
            )
        return "failed"


def process_one(
    conn: psycopg.Connection[Any],
    handlers: dict[str, JobHandler] | None = None,
) -> bool:
    """Claim and process one due job.  Returns True if a job was found.

    Must be called inside an open transaction (e.g. ``with conn.transaction()``
    in run_forever).  This function does NOT commit.

    Handler resolution order: *handlers* arg overrides the global registry.
    An unknown kind is treated as a failure ('no handler registered for kind').
    """
    effective: dict[str, JobHandler] = _registry if handlers is None else handlers

    job = claim_next_job(conn)
    if job is None:
        return False

    assert job.id is not None
    handler = effective.get(job.kind)

    if handler is None:
        error_msg = f"no handler registered for kind '{job.kind}'"
        reschedule_or_fail(conn, job.id, job.attempts, error_msg)
        return True

    try:
        handler(job.payload, conn)
        mark_done(conn, job.id)
    except Exception as exc:
        reschedule_or_fail(conn, job.id, job.attempts, str(exc))

    return True


# ---------------------------------------------------------------------------
# Default handler stubs (safe no-ops until epics land)
# ---------------------------------------------------------------------------


def register_default_handlers() -> None:
    """Register built-in handlers that are safe to call at startup.

    For E2, only structural stubs exist here.  Heavier epics register their
    own handlers when imported by the live entrypoint:
      - ingestion.poller registers 'poll_channels' (E2-T2)
      - transcription module registers 'transcribe' (E2-T4)
      - extraction module registers 'extract' (E3-T2)
      - resolution module registers 'resolve_claims' (E1-T3/E4-T1)
      - scoring module registers 'score_analysts' (E1-T2)

    This function is idempotent and intentionally imports nothing heavy.
    """
    # No default handlers registered in E2; each epic wires its own.
    pass


def bootstrap_handlers() -> None:
    """Register every scheduled-ops handler so the production worker dispatches them.

    The production entrypoint (``python -m brier_pipeline.jobs.worker``) calls
    this before run_forever — closing the launch-readiness "worker bootstrap
    imports nothing" gap.  Registration is EXPLICIT (not import-for-side-effect)
    so it is deterministic and idempotent: it repopulates the registry even
    after a test clear_handlers() (a cached re-import would not re-run a module's
    module-scope register_handler call).  register_handler overwrites by kind, so
    calling this twice is a no-op.

    Imports are deferred to call time to avoid an import cycle (the handler
    modules import this module to register).

    Registered: poll_channels, deletion_sweep, freshness_check, dispute_sla_check,
    weekly_dispute_report, erasure_sla_check, resolve_claims, score_analysts.

    NOT registered (human-gated backfill activation, ADR-0003/0004/0008): the
    transcribe + extract handlers — see brier_pipeline/jobs/handlers.py.
    """
    from brier_pipeline.disputes.sla import (
        _dispute_sla_check_handler,
        _weekly_dispute_report_handler,
    )
    from brier_pipeline.ingestion.deletion import _deletion_sweep_handler
    from brier_pipeline.ingestion.freshness import _freshness_check_handler
    from brier_pipeline.ingestion.poller import _poll_channels_handler
    from brier_pipeline.jobs.handlers import resolve_claims_handler, score_analysts_handler
    from brier_pipeline.ops.erasure import _erasure_sla_check_handler

    register_handler("poll_channels", _poll_channels_handler)
    register_handler("deletion_sweep", _deletion_sweep_handler)
    register_handler("freshness_check", _freshness_check_handler)
    register_handler("dispute_sla_check", _dispute_sla_check_handler)
    register_handler("weekly_dispute_report", _weekly_dispute_report_handler)
    register_handler("erasure_sla_check", _erasure_sla_check_handler)
    register_handler("resolve_claims", resolve_claims_handler)
    register_handler("score_analysts", score_analysts_handler)


# ---------------------------------------------------------------------------
# Infinite loop
# ---------------------------------------------------------------------------


def run_forever(poll_interval_seconds: float = 5.0) -> None:
    """Thin infinite loop: open a connection, poll, sleep when idle.

    To wire up job kinds, register handlers before calling this function.  The
    production entrypoint does this via bootstrap_handlers()::

        python -m brier_pipeline.jobs.worker   # bootstrap_handlers(); run_forever()

    or, to wire a single kind in a script::

        from brier_pipeline.ingestion import poller  # registers 'poll_channels'
        from brier_pipeline.jobs.worker import run_forever
        run_forever()
    """
    register_default_handlers()
    conn = connect()
    try:
        while True:
            with conn.transaction():
                did_work = process_one(conn)
            if not did_work:
                time.sleep(poll_interval_seconds)
    finally:
        conn.close()


if __name__ == "__main__":
    # Production worker entrypoint (launch-readiness defect 3): register every
    # scheduled-ops handler, then drain the jobs table forever.
    bootstrap_handlers()
    run_forever()
