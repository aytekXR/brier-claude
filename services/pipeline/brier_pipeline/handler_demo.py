"""`make handler-demo`: the transcribe + extract job handlers, end to end on fakes.

Runs the REAL production dispatch path — ``bootstrap_handlers()`` then
``process_one()`` over an enqueued ``transcribe`` job — using the fixture-backed
FakeTranscriber + FakeExtractor (the CI/dev seam, no key, no network, no spend).
It demonstrates two things:

  1. **The chain.** A ``transcribe`` job stores a transcript blob, writes the
     ``transcripts`` row, and enqueues an ``extract`` job; that job structures
     claims and persists them — the same code the worker runs in production.
  2. **The three extract gates.** EC-3 (sarcasm/hypothetical/paraphrase is
     skipped), AC-7 (recommendation language is dropped), FR-203 (a
     low-confidence claim routes to human review and is NOT published) — shown
     by running the real gate predicates over four illustrative claims.

Everything runs inside ONE transaction that is rolled back at the end, so the
dev database is left untouched. To see the REAL adapters select instead of the
fakes, set ``BRIER_DEEPGRAM_API_KEY`` / ``BRIER_ANTHROPIC_API_KEY`` (the seam
tests prove the switch) — but a full real run also needs audio acquisition + a
scheduler + a roster, which stay human-gated.

Run:  make handler-demo   (or:  python -m brier_pipeline.handler_demo)
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from brier_pipeline.config import database_url
from brier_pipeline.extraction.extractor import is_excluded_span
from brier_pipeline.jobs import handlers, worker
from brier_pipeline.models import Claim, SpecificityClass
from brier_pipeline.qa.queue import route_low_confidence

# A NorthChain fixture video that has a transcript fixture + claim-bearing quotes.
_DEMO_CHANNEL = "UCfix-northchain-0001"
_DEMO_VIDEO = "NCfx-btc-dec01"


def _ensure_parent(conn: psycopg.Connection[Any]) -> tuple[int, int]:
    """Insert-or-get the demo analyst + video; return (analyst_id, video_id).

    ON CONFLICT DO NOTHING so the demo works whether or not the row already
    exists — the surrounding transaction is rolled back regardless.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into analysts (channel_id, display_name, slug, status)
            values (%s, 'NorthChain', 'northchain', 'active')
            on conflict (channel_id) do nothing returning id
            """,
            (_DEMO_CHANNEL,),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("select id from analysts where channel_id = %s", (_DEMO_CHANNEL,))
            row = cur.fetchone()
        assert row is not None
        analyst_id = int(row[0])

        cur.execute(
            """
            insert into videos (analyst_id, youtube_video_id, title, published_at)
            values (%s, %s, 'handler-demo', '2024-12-01T18:00:00Z')
            on conflict (youtube_video_id) do nothing returning id
            """,
            (analyst_id, _DEMO_VIDEO),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute("select id from videos where youtube_video_id = %s", (_DEMO_VIDEO,))
            row = cur.fetchone()
        assert row is not None
        video_id = int(row[0])
    return analyst_id, video_id


def _drain_until_done(conn: psycopg.Connection[Any], job_id: int, *, limit: int = 25) -> str:
    """Run process_one() until *job_id* reaches a terminal state (or no work)."""
    for _ in range(limit):
        with conn.cursor() as cur:
            cur.execute("select state from jobs where id = %s", (job_id,))
            row = cur.fetchone()
            assert row is not None
            state = str(row[0])
        if state in ("done", "failed"):
            return state
        if not worker.process_one(conn):
            break
    with conn.cursor() as cur:
        cur.execute("select state from jobs where id = %s", (job_id,))
        row = cur.fetchone()
        assert row is not None
        return str(row[0])


def _example_claim(
    offset: int, *, quote: str, confidence: float, flags: dict[str, Any] | None = None
) -> Claim:
    """Build a minimal illustrative claim for the gate demonstration."""
    return Claim(
        analyst_id=0,
        video_id=0,
        transcript_id=0,
        asset="BTC",
        direction="bullish",
        specificity_class=SpecificityClass.DIRECTION_ONLY,
        source_offset_seconds=offset,
        quote=quote,
        extraction_confidence=confidence,
        model_version="handler-demo",
        prompt_version="v1",
        uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
        flags=flags or {},
    )


def _disposition(claim: Claim) -> str:
    """Apply the extract handler's three gates, in the handler's order, and label.

    Mirrors extract_handler: EC-3 is_excluded_span -> AC-7 forbidden_terms_in ->
    FR-203 route_low_confidence. Uses the exact same functions the handler calls.
    """
    if is_excluded_span(claim):
        return "SKIPPED (EC-3 — not the analyst's own statement)"
    if handlers._forbidden_terms_in(claim.quote or ""):
        return "DROPPED (AC-7 — recommendation language)"
    routed = route_low_confidence([claim])  # mutates publishable/review_state in place
    if routed:
        return "ROUTED to QA (FR-203 — low confidence, not published)"
    return "PUBLISHED (auto-approved)"


def run_handler_demo(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Drive the handlers end to end on *conn* (caller owns + rolls back the txn)."""
    original_root = handlers._LOCAL_STORAGE_ROOT
    handlers._LOCAL_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="brier-handler-demo-"))
    try:
        worker.bootstrap_handlers()
        analyst_id, video_id = _ensure_parent(conn)

        # --- Part 1: the transcribe -> extract chain via the real worker path ---
        transcribe_job = worker.enqueue_job(
            conn, "transcribe", {"video_id": video_id, "youtube_video_id": _DEMO_VIDEO}
        )
        transcribe_state = _drain_until_done(conn, transcribe_job)

        with conn.cursor() as cur:
            cur.execute(
                "select id, source, storage_pointer from transcripts "
                "where video_id = %s and source = 'deepgram'",
                (video_id,),
            )
            t_row = cur.fetchone()
            transcript_id = int(t_row[0]) if t_row else None
            cur.execute(
                "select id from jobs where kind = 'extract' "
                "and (payload->>'transcript_id')::int = %s",
                (transcript_id,),
            )
            e_row = cur.fetchone()
            extract_job = int(e_row[0]) if e_row else None

        extract_state = _drain_until_done(conn, extract_job) if extract_job else "not enqueued"

        claims: list[dict[str, Any]] = []
        if transcript_id is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select asset, direction, round(extraction_confidence::numeric, 2),
                           review_state, publishable, quote
                    from claims where transcript_id = %s order by source_offset_seconds
                    """,
                    (transcript_id,),
                )
                for asset, direction, conf, rstate, pub, quote in cur.fetchall():
                    claims.append(
                        {
                            "asset": asset,
                            "direction": direction,
                            "confidence": float(conf) if conf is not None else None,
                            "review_state": str(rstate),
                            "publishable": bool(pub),
                            "quote": quote,
                        }
                    )

        # --- Part 2: the three extract gates, on four illustrative claims ---
        examples = [
            _example_claim(
                10, quote="Bitcoin reaches the stated target by year-end", confidence=0.95
            ),
            _example_claim(
                20,
                quote="some say BTC will fly — that's their view, not mine",
                confidence=0.95,
                flags={"excluded_reason": "paraphrase"},
            ),
            _example_claim(30, quote="you should buy BTC right now", confidence=0.95),
            _example_claim(40, quote="BTC may drift toward the level", confidence=0.30),
        ]
        gates = [{"quote": c.quote, "disposition": _disposition(c)} for c in examples]

        return {
            "transcribe_job": transcribe_job,
            "transcribe_state": transcribe_state,
            "transcript_id": transcript_id,
            "extract_job": extract_job,
            "extract_state": extract_state,
            "claims": claims,
            "gates": gates,
        }
    finally:
        handlers._LOCAL_STORAGE_ROOT = original_root


def _render(result: dict[str, Any]) -> None:
    """Print the handler-demo result as a human-readable narrative."""
    sep = "-" * 72
    print(sep)
    print("Brier handler demo — transcribe + extract on the fixture fakes")
    print(sep)
    print(f"\n  transcribe job {result['transcribe_job']} -> {result['transcribe_state']}")
    print(f"  transcript row id={result['transcript_id']} (source=deepgram)")
    print(f"  extract job {result['extract_job']} -> {result['extract_state']}")

    print(f"\n  EXTRACTED CLAIMS ({len(result['claims'])} persisted):")
    for c in result["claims"]:
        flag = "PUBLISHABLE" if c["publishable"] else "-> QA review"
        print(
            f"    [{c['asset'] or '?':<4} {c['direction'] or '?':<7} "
            f"conf={c['confidence']} {c['review_state']:<9} {flag}]"
        )
        print(f"       {c['quote']!r}")

    print("\n  GATE GUARANTEES (four illustrative claims through the real gates):")
    for g in result["gates"]:
        print(f"    {g['disposition']}")
        print(f"       {g['quote']!r}")

    print(f"\n{sep}")
    print("  (transaction rolled back — dev DB unchanged)")
    print(sep)


def main() -> None:
    """Entry point for `python -m brier_pipeline.handler_demo` / `make handler-demo`."""
    conn = psycopg.connect(database_url())
    try:
        result = run_handler_demo(conn)
        _render(result)
    finally:
        conn.rollback()  # leave the dev DB untouched
        conn.close()


if __name__ == "__main__":
    main()
