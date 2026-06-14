"""E1 walking-skeleton demo: fixture pipeline thread — end to end.

Runs the full fixture pipeline thread using fixture-backed fakes:
  FakeYouTubeClient -> videos -> captions/FakeTranscriber -> transcripts
  -> LocalFSStorage -> FakeExtractor -> claims
  -> FakePriceSource -> resolve_open_claims -> resolutions ledger
  -> run_score_pass -> scores ledger
  -> leaderboard print (HP-2 demo artifact)

Idempotent: re-running against a seeded database creates zero duplicate
rows (videos/transcripts/claims); appends zero new resolutions if all
resolvable claims are already resolved; always appends a new score_run
(append-only ledger — the leaderboard reads the latest run). Safe to
run multiple times.

Usage:
  python -m brier_pipeline.demo
  (or via: make pipeline-demo)

The leaderboard demonstrates the FAS inversion: Aylin Markets ranks above
NorthChain on FAS despite a lower raw hit rate. All three analysts have
n < 20 resolved claims, so the ranked board is empty per FR-305. The
provisional section orders them by FAS descending.

Next consumer: E1-T5 web pages.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from brier_pipeline.config import METHODOLOGY_VERSION, database_url
from brier_pipeline.extraction.extractor import FakeExtractor
from brier_pipeline.ingestion.youtube import FakeYouTubeClient
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.scoring.fas import run_score_pass
from brier_pipeline.transcription.storage import LocalFSStorage
from brier_pipeline.transcription.transcriber import FakeTranscriber, TranscriptSegment

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
LOCAL_STORAGE_ROOT = REPO_ROOT / "data" / "local"


def _upsert_prices(cur: psycopg.Cursor[Any], records: list[dict[str, Any]]) -> int:
    """Insert fixture price closes into price_daily; skip rows already present.

    Uses INSERT ... ON CONFLICT DO NOTHING so that re-runs are safe — closes
    are immutable fixture data and price_daily is not an append-only ledger.
    Returns the count of newly inserted rows.
    """
    if not records:
        return 0
    inserted = 0
    for rec in records:
        cur.execute(
            """
            insert into price_daily (asset, day, close_usd, source, data_gap)
            values (%s, %s, %s, %s, false)
            on conflict (asset, day) do nothing
            """,
            (rec["asset"], rec["day"], rec["close_usd"], rec["source"]),
        )
        inserted += cur.rowcount
    return inserted


def _get_or_create_analyst(cur: psycopg.Cursor[Any], channel_id: str) -> int:
    """Return the DB id for a channel_id; raises if not found (seeded separately)."""
    cur.execute("select id from analysts where channel_id = %s", (channel_id,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"Analyst with channel_id={channel_id!r} not found. Run `make seed` first."
        )
    return int(row[0])


def _upsert_video(cur: psycopg.Cursor[Any], analyst_id: int, vid: Any) -> tuple[int, bool]:
    """Insert video if not already present; return (db_id, created)."""
    cur.execute(
        "select id from videos where youtube_video_id = %s",
        (vid.youtube_video_id,),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row[0]), False

    cur.execute(
        """
        insert into videos (analyst_id, youtube_video_id, title, published_at, duration_seconds)
        values (%s, %s, %s, %s, %s)
        returning id
        """,
        (
            analyst_id,
            vid.youtube_video_id,
            vid.title,
            vid.published_at,
            vid.duration_seconds,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), True


def _upsert_transcript(
    cur: psycopg.Cursor[Any],
    video_id: int,
    source: str,
    storage_pointer: str,
    language: str = "en",
    quality_note: str | None = None,
) -> tuple[int, bool]:
    """Insert transcript row if not already present; return (db_id, created)."""
    cur.execute(
        "select id from transcripts where video_id = %s and source = %s",
        (video_id, source),
    )
    row = cur.fetchone()
    if row is not None:
        return int(row[0]), False

    cur.execute(
        """
        insert into transcripts (video_id, source, storage_pointer, language, quality_note)
        values (%s, %s, %s, %s, %s)
        returning id
        """,
        (video_id, source, storage_pointer, language, quality_note),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), True


def _claim_exists(cur: psycopg.Cursor[Any], transcript_id: int, source_offset_seconds: int) -> bool:
    """Check whether a claim at this (transcript, offset) is already stored."""
    cur.execute(
        "select id from claims where transcript_id = %s and source_offset_seconds = %s",
        (transcript_id, source_offset_seconds),
    )
    return cur.fetchone() is not None


def _insert_claim(
    cur: psycopg.Cursor[Any], analyst_id: int, video_id: int, transcript_id: int, claim: Any
) -> int:
    """Insert a claim row and return its DB id."""
    conditionality = json.dumps(claim.conditionality) if claim.conditionality else None
    flags = json.dumps(claim.flags) if claim.flags else "{}"

    cur.execute(
        """
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction, target_price, magnitude_pct,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            conditionality, specificity_class,
            source_offset_seconds, quote,
            uttered_at, p0_price,
            extraction_confidence, model_version, prompt_version,
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s
        ) returning id
        """,
        (
            analyst_id,
            video_id,
            transcript_id,
            claim.asset,
            claim.direction,
            claim.target_price,
            claim.magnitude_pct,
            claim.horizon_deadline,
            claim.horizon_basis,
            claim.stated_confidence,
            claim.confidence_basis,
            conditionality,
            str(claim.specificity_class.value),
            claim.source_offset_seconds,
            claim.quote,
            claim.uttered_at,
            claim.p0_price,
            claim.extraction_confidence,
            claim.model_version,
            claim.prompt_version,
            str(claim.review_state.value),
            claim.publishable,
            str(claim.status.value),
            flags,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _load_analyst_names(conn: psycopg.Connection[Any]) -> dict[int, str]:
    """Return mapping of analyst_id -> display_name."""
    with conn.cursor() as cur:
        cur.execute("select id, display_name from analysts order by id")
        return {int(row[0]): str(row[1]) for row in cur.fetchall()}


def _raw_hit_rates(conn: psycopg.Connection[Any]) -> dict[int, tuple[int, int]]:
    """Return per-analyst (hits, total_resolved) from the latest resolutions."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select c.analyst_id,
                   count(*) as total,
                   sum(case when r.outcome = 1.0 then 1 else 0 end) as hits
            from claims c
            join resolutions r on r.claim_id = c.id
            where c.specificity_class != 'non_falsifiable'
              and not exists (
                  select 1 from resolutions r2
                  where r2.supersedes_resolution_id = r.id
              )
            group by c.analyst_id
            """
        )
        return {int(row[0]): (int(row[2]), int(row[1])) for row in cur.fetchall()}


def _resolution_counts_this_run(resolutions: list[Any]) -> dict[str, int]:
    """Summarize resolutions appended in this run as hits/misses/partials."""
    hits = sum(1 for r in resolutions if r.outcome == 1.0)
    misses = sum(1 for r in resolutions if r.outcome == 0.0)
    partials = sum(1 for r in resolutions if r.outcome == 0.5)
    return {"hits": hits, "misses": misses, "partials": partials}


def _cumulative_resolution_counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Count total non-superseded resolutions in the ledger."""
    with conn.cursor() as cur:
        cur.execute(
            """
            select
                sum(case when outcome = 1.0 then 1 else 0 end) as hits,
                sum(case when outcome = 0.0 then 1 else 0 end) as misses,
                sum(case when outcome = 0.5 then 1 else 0 end) as partials,
                count(*) as total
            from resolutions r
            where not exists (
                select 1 from resolutions r2
                where r2.supersedes_resolution_id = r.id
            )
            """
        )
        row = cur.fetchone()
        if row is None or row[3] is None:
            return {"hits": 0, "misses": 0, "partials": 0, "total": 0}
        return {
            "hits": int(row[0] or 0),
            "misses": int(row[1] or 0),
            "partials": int(row[2] or 0),
            "total": int(row[3] or 0),
        }


def _open_claim_counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    """Count claims by status/class that remain unresolved."""
    with conn.cursor() as cur:
        # Future-deadline open claims
        cur.execute(
            """
            select count(*) from claims
            where status = 'open'
              and specificity_class not in ('non_falsifiable', 'conditional')
              and publishable = true
            """
        )
        row = cur.fetchone()
        future_open = int(row[0]) if row else 0

        # Conditional (skipped by v0 resolver, pending E4-T1)
        cur.execute("select count(*) from claims where specificity_class = 'conditional'")
        row = cur.fetchone()
        conditional_skipped = int(row[0]) if row else 0

        # Non-falsifiable (counted in F only, never scored)
        cur.execute("select count(*) from claims where specificity_class = 'non_falsifiable'")
        row = cur.fetchone()
        non_falsifiable = int(row[0]) if row else 0

    return {
        "future_open": future_open,
        "conditional_skipped": conditional_skipped,
        "non_falsifiable": non_falsifiable,
    }


def run_demo() -> dict[str, Any]:
    """Execute the E1 fixture pipeline thread end to end and return stage counters.

    Stages:
      1. Ingestion: FakeYouTubeClient -> videos persisted (idempotent upsert)
      2. Transcription: captions / FakeTranscriber -> transcript rows
      3. Extraction: FakeExtractor -> claim rows
      4. Resolution: resolve_open_claims via FakePriceSource -> resolutions ledger
      5. Scoring: run_score_pass -> score_runs + scores ledger
    """
    yt_client = FakeYouTubeClient(FIXTURES_DIR)
    fake_transcriber = FakeTranscriber(FIXTURES_DIR)
    extractor = FakeExtractor(FIXTURES_DIR)
    storage = LocalFSStorage(LOCAL_STORAGE_ROOT)
    prices = FakePriceSource(FIXTURES_DIR)

    # Load fixture analyst registry
    analysts_path = FIXTURES_DIR / "analysts.json"
    analysts_raw: list[dict[str, Any]] = json.loads(analysts_path.read_text(encoding="utf-8"))

    videos_persisted = 0
    transcripts_persisted = 0
    claims_persisted = 0
    claims_skipped = 0
    prices_persisted = 0

    with psycopg.connect(database_url()) as conn:
        # ----------------------------------------------------------------
        # Stage 0: Price persistence — write fixture closes into price_daily
        # so the web receipt chart can read daily closes via apps/web/lib/db.ts.
        # Resolution still uses FakePriceSource directly; this stage exists
        # only to make closes web-readable. Idempotent: ON CONFLICT DO NOTHING.
        # ----------------------------------------------------------------
        price_assets = ["BTC", "ETH", "SOL"]
        with conn.cursor() as cur:
            for asset in price_assets:
                price_path = FIXTURES_DIR / "prices" / f"{asset}.json"
                records: list[dict[str, Any]] = json.loads(price_path.read_text(encoding="utf-8"))
                prices_persisted += _upsert_prices(cur, records)
            conn.commit()
        # ----------------------------------------------------------------
        # Stages 1-3: ingest -> transcribe -> extract -> persist claims
        # ----------------------------------------------------------------
        for analyst_raw in analysts_raw:
            channel_id = str(analyst_raw["channel_id"])
            with conn.cursor() as cur:
                analyst_id = _get_or_create_analyst(cur, channel_id)
                conn.commit()

            # Fetch all fixture videos for this channel
            videos = yt_client.list_all_uploads(channel_id, months=24)

            for vid in videos:
                with conn.cursor() as cur:
                    video_id, video_created = _upsert_video(cur, analyst_id, vid)
                    conn.commit()
                if video_created:
                    videos_persisted += 1

                # Attempt caption-first transcript acquisition
                captions_text = yt_client.fetch_captions(vid.youtube_video_id)

                if captions_text is not None:
                    # Captions available: parse the fixture JSON directly
                    raw_segs: list[dict[str, Any]] = json.loads(captions_text)
                    segments = [TranscriptSegment(**s) for s in raw_segs]
                    source = "captions"
                    quality_note = "fixture-captions"
                else:
                    # No captions: fall back to FakeTranscriber
                    segments = fake_transcriber.transcribe(vid.youtube_video_id)
                    source = "whisper"
                    quality_note = "fixture-transcribed"

                # Serialize segments to storage
                storage_key = f"transcripts/{vid.youtube_video_id}.json"
                storage_body = json.dumps([s.model_dump() for s in segments], indent=2).encode(
                    "utf-8"
                )
                storage.put(storage_key, storage_body)

                with conn.cursor() as cur:
                    transcript_id, transcript_created = _upsert_transcript(
                        cur,
                        video_id,
                        source=source,
                        storage_pointer=storage_key,
                        quality_note=quality_note,
                    )
                    conn.commit()
                if transcript_created:
                    transcripts_persisted += 1

                # Run FakeExtractor: pass 1 then pass 2
                candidates = extractor.detect_candidates(segments)
                for span in candidates:
                    claim = extractor.structure_claim(span)
                    # Fill in the DB-assigned IDs
                    claim.analyst_id = analyst_id
                    claim.video_id = video_id
                    claim.transcript_id = transcript_id

                    with conn.cursor() as cur:
                        if _claim_exists(cur, transcript_id, claim.source_offset_seconds):
                            claims_skipped += 1
                            conn.commit()
                            continue
                        _insert_claim(cur, analyst_id, video_id, transcript_id, claim)
                        conn.commit()
                    claims_persisted += 1

        # ----------------------------------------------------------------
        # Stage 4: Resolution — resolve_open_claims via FakePriceSource
        # Reuses the same connection; caller (conn) manages commit.
        # resolve_open_claims with conn=conn does NOT auto-commit;
        # we commit explicitly after.
        # ----------------------------------------------------------------
        resolutions_this_run = resolve_open_claims(prices=prices, conn=conn)
        conn.commit()

        # ----------------------------------------------------------------
        # Stage 5: Scoring — run_score_pass writes score_runs + scores
        # Reuses the same connection; run_score_pass with conn passes
        # caller_owns_transaction=True so it does not commit.
        # ----------------------------------------------------------------
        score_run_id, scores = run_score_pass(trigger="demo", conn=conn)
        conn.commit()

        # ----------------------------------------------------------------
        # Collect leaderboard data
        # ----------------------------------------------------------------
        analyst_names = _load_analyst_names(conn)
        raw_hit_rate_map = _raw_hit_rates(conn)
        cum_counts = _cumulative_resolution_counts(conn)
        open_counts = _open_claim_counts(conn)

    this_run_summary = _resolution_counts_this_run(resolutions_this_run)

    return {
        "prices_persisted": prices_persisted,
        "videos_persisted": videos_persisted,
        "transcripts_persisted": transcripts_persisted,
        "claims_persisted": claims_persisted,
        "claims_skipped": claims_skipped,
        "resolutions_this_run": len(resolutions_this_run),
        "resolutions_this_run_hits": this_run_summary["hits"],
        "resolutions_this_run_misses": this_run_summary["misses"],
        "resolutions_this_run_partials": this_run_summary["partials"],
        "cumulative_hits": cum_counts["hits"],
        "cumulative_misses": cum_counts["misses"],
        "cumulative_partials": cum_counts["partials"],
        "cumulative_total": cum_counts["total"],
        "future_open_claims": open_counts["future_open"],
        "conditional_skipped": open_counts["conditional_skipped"],
        "non_falsifiable_count": open_counts["non_falsifiable"],
        "score_run_id": score_run_id,
        "scores": scores,
        "analyst_names": analyst_names,
        "raw_hit_rate_map": raw_hit_rate_map,
    }


def _print_leaderboard(result: dict[str, Any]) -> None:
    """Print the HP-2 demo leaderboard artifact per brandkit voice rules."""
    scores = result["scores"]
    analyst_names = result["analyst_names"]
    raw_hit_rate_map = result["raw_hit_rate_map"]

    # Sort by FAS descending
    ranked_scores = sorted(
        [s for s in scores if s.ranked],
        key=lambda s: s.fas,
        reverse=True,
    )
    provisional_scores = sorted(
        [s for s in scores if not s.ranked],
        key=lambda s: s.fas,
        reverse=True,
    )

    sep = "-" * 72

    print(sep)
    print(f"Brier Falsifiable Accuracy Score — Methodology {METHODOLOGY_VERSION}")
    print(sep)
    print()

    # RANKED section
    print("RANKED")
    if not ranked_scores:
        print("  Analysts with fewer than 20 resolved claims are provisional and")
        print("  excluded from the ranked board.")
    else:
        print(f"  {'#':<4} {'Analyst':<22} {'FAS':>6} {'n':>5} {'F':>6} {'Hit%':>6}  Status")
        print(f"  {'-' * 4} {'-' * 22} {'-' * 6} {'-' * 5} {'-' * 6} {'-' * 6}  {'-' * 12}")
        for pos, s in enumerate(ranked_scores, start=1):
            name = analyst_names.get(s.analyst_id, f"analyst-{s.analyst_id}")
            hits, total = raw_hit_rate_map.get(s.analyst_id, (0, 1))
            hit_pct = hits / total if total > 0 else 0.0
            status = "provisional" if s.provisional else "ranked"
            print(
                f"  {pos:<4} {name:<22} {s.fas:>6.1f} {s.n_resolved:>5} "
                f"{s.falsifiability:>6.2f} {hit_pct:>5.1%}  {status}"
            )

    print()

    # PROVISIONAL section
    print("PROVISIONAL  (n < 20; excluded from ranked board per FR-305)")
    if not provisional_scores:
        print("  No provisional analysts in this run.")
    else:
        print(f"  {'#':<4} {'Analyst':<22} {'FAS':>6} {'n':>5} {'F':>6} {'Hit%':>6}  Status")
        print(f"  {'-' * 4} {'-' * 22} {'-' * 6} {'-' * 5} {'-' * 6} {'-' * 6}  {'-' * 18}")
        for pos, s in enumerate(provisional_scores, start=1):
            name = analyst_names.get(s.analyst_id, f"analyst-{s.analyst_id}")
            hits, total = raw_hit_rate_map.get(s.analyst_id, (0, 1))
            hit_pct = hits / total if total > 0 else 0.0
            print(
                f"  {pos:<4} {name:<22} {s.fas:>6.1f} {s.n_resolved:>5} "
                f"{s.falsifiability:>6.2f} {hit_pct:>5.1%}  provisional, not ranked"
            )

    print()

    # FAS inversion note (factual, cite-don't-characterize per brandkit §7)
    aylin_score = next(
        (s for s in scores if analyst_names.get(s.analyst_id) == "Aylin Markets"), None
    )
    nc_score = next((s for s in scores if analyst_names.get(s.analyst_id) == "NorthChain"), None)
    if aylin_score is not None and nc_score is not None:
        aylin_hits, aylin_total = raw_hit_rate_map.get(aylin_score.analyst_id, (0, 1))
        nc_hits, nc_total = raw_hit_rate_map.get(nc_score.analyst_id, (0, 1))
        aylin_hit_pct = aylin_hits / aylin_total if aylin_total > 0 else 0.0
        nc_hit_pct = nc_hits / nc_total if nc_total > 0 else 0.0
        if aylin_score.fas > nc_score.fas and nc_hit_pct > aylin_hit_pct:
            print("FAS INVERSION (methodology illustration)")
            print(
                f"  Aylin Markets: FAS {aylin_score.fas:.1f}, "
                f"raw hit rate {aylin_hit_pct:.1%} ({aylin_hits}/{aylin_total})"
            )
            print(
                f"  NorthChain:    FAS {nc_score.fas:.1f}, "
                f"raw hit rate {nc_hit_pct:.1%} ({nc_hits}/{nc_total})"
            )
            print("  Aylin Markets ranks above NorthChain on FAS despite a lower raw")
            print("  hit rate. Base-rate correction, specificity weights, and")
            print("  calibration account for the difference.")
            print()

    # Stage report
    print("STAGE REPORT")
    print(f"  Prices persisted this run:       {result['prices_persisted']}")
    print(f"  Videos persisted this run:       {result['videos_persisted']}")
    print(f"  Transcripts persisted this run:  {result['transcripts_persisted']}")
    print(f"  Claims persisted this run:       {result['claims_persisted']}")
    print(f"  Claims skipped (duplicate):      {result['claims_skipped']}")
    print()
    print(
        f"  Resolutions appended this run:   {result['resolutions_this_run']} "
        f"(hits: {result['resolutions_this_run_hits']}, "
        f"misses: {result['resolutions_this_run_misses']}, "
        f"partials: {result['resolutions_this_run_partials']})"
    )
    print(
        f"  Resolutions cumulative:          {result['cumulative_total']} "
        f"(hits: {result['cumulative_hits']}, "
        f"misses: {result['cumulative_misses']}, "
        f"partials: {result['cumulative_partials']})"
    )
    print()
    print(f"  Claims still open (deadline ahead or deferred): {result['future_open_claims']}")
    print(f"  Conditional claims skipped (E4-T1):  {result['conditional_skipped']}")
    print(f"  Non-falsifiable counted in F only:   {result['non_falsifiable_count']}")
    print()
    print(f"  Score run id:        {result['score_run_id']}")
    print(f"  Methodology version: {METHODOLOGY_VERSION}")
    print(sep)


def main() -> None:
    """Entry point for `python -m brier_pipeline.demo`."""
    started_at = datetime.now(UTC)
    print("Brier pipeline demo — E1 fixture thread")
    print(f"  Started: {started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  Fixtures: {FIXTURES_DIR}")
    print(f"  Storage:  {LOCAL_STORAGE_ROOT}")
    print()

    result = run_demo()

    print("Stages complete: prices, ingestion, transcription, extraction, resolution, scoring")
    print()

    _print_leaderboard(result)


if __name__ == "__main__":
    main()
