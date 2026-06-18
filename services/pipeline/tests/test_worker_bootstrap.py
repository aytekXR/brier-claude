"""Worker bootstrap + scheduled-ops handler registration.

Closes two launch-readiness gaps:
  - Defect 3 "worker bootstrap imports nothing": bootstrap_handlers() registers
    every scheduled-ops handler so `python -m brier_pipeline.jobs.worker`
    dispatches them.  Registration is explicit + idempotent, so it survives a
    test clear_handlers() (a cached re-import would not re-run module-scope
    registration).
  - Defect 2 (partial): the resolve_claims + score_analysts handlers run
    end-to-end through process_one on the fixture path (transcribe/extract stay
    deferred to the human-gated ADR-0003/0004/0008 activation).
"""

from __future__ import annotations

from typing import Any

from brier_pipeline.jobs import worker
from brier_pipeline.jobs.worker import (
    bootstrap_handlers,
    enqueue_job,
    process_one,
)

# Kinds the production worker must dispatch (runbook §7).  transcribe/extract
# are intentionally absent — they belong to the gated backfill activation.
_EXPECTED_KINDS = [
    "poll_channels",
    "deletion_sweep",
    "freshness_check",
    "dispute_sla_check",
    "weekly_dispute_report",
    "erasure_sla_check",
    "resolve_claims",
    "score_analysts",
]


class TestBootstrapRegistration:
    def test_registers_every_scheduled_ops_handler(self) -> None:
        """After bootstrap_handlers(), every scheduled-ops kind has a handler."""
        worker.clear_handlers()
        try:
            bootstrap_handlers()
            for kind in _EXPECTED_KINDS:
                assert worker.get_handler(kind) is not None, f"{kind} handler not registered"
        finally:
            worker.clear_handlers()

    def test_deterministic_after_clear(self) -> None:
        """Explicit registration repopulates even when the modules are cached.

        clear_handlers() empties the registry; because the handler modules are
        already imported elsewhere in the suite, a pure import-for-side-effect
        bootstrap would NOT re-register them.  Explicit registration must.
        """
        worker.clear_handlers()
        bootstrap_handlers()  # modules already imported -> import side effect is a no-op
        try:
            for kind in _EXPECTED_KINDS:
                assert worker.get_handler(kind) is not None, (
                    f"{kind} not re-registered after clear (import side-effect is not enough)"
                )
        finally:
            worker.clear_handlers()

    def test_idempotent(self) -> None:
        """Calling bootstrap twice leaves exactly one (identical) handler per kind."""
        worker.clear_handlers()
        try:
            bootstrap_handlers()
            first = {k: worker.get_handler(k) for k in _EXPECTED_KINDS}
            bootstrap_handlers()
            for k in _EXPECTED_KINDS:
                assert worker.get_handler(k) is first[k]
        finally:
            worker.clear_handlers()

    def test_transcribe_and_extract_are_deferred(self) -> None:
        """transcribe/extract stay unregistered (gated on ADR-0003/0004/0008)."""
        worker.clear_handlers()
        try:
            bootstrap_handlers()
            assert worker.get_handler("transcribe") is None
            assert worker.get_handler("extract") is None
        finally:
            worker.clear_handlers()


class TestScheduledOpsHandlersRun:
    """The resolve_claims + score_analysts handlers dispatch and complete (DB-backed)."""

    def test_handlers_dispatch_via_process_one(self, db_conn: Any) -> None:
        worker.clear_handlers()
        try:
            bootstrap_handlers()

            with db_conn.cursor() as cur:
                cur.execute("select count(*) from score_runs")
                row = cur.fetchone()
                assert row is not None
                runs_before = int(row[0])

            resolve_job = enqueue_job(db_conn, "resolve_claims", {})
            score_job = enqueue_job(db_conn, "score_analysts", {})

            # Two due jobs -> two successful dispatches.
            assert process_one(db_conn) is True
            assert process_one(db_conn) is True

            with db_conn.cursor() as cur:
                cur.execute("select state from jobs where id = %s", (resolve_job,))
                r = cur.fetchone()
                assert r is not None and str(r[0]) == "done", "resolve_claims must complete"
                cur.execute("select state from jobs where id = %s", (score_job,))
                s = cur.fetchone()
                assert s is not None and str(s[0]) == "done", "score_analysts must complete"
                cur.execute("select count(*) from score_runs")
                after = cur.fetchone()
                assert after is not None
                runs_after = int(after[0])

            assert runs_after == runs_before + 1, (
                "score_analysts must append exactly one score_run (append-only ledger)"
            )
        finally:
            worker.clear_handlers()
