"""E1 walking-skeleton demo: fixture pipeline thread.

Runs the full ingestion-to-claims thread using fixture-backed fakes:
  FakeYouTubeClient -> videos -> captions/FakeTranscriber -> transcripts
  -> LocalFSStorage -> FakeExtractor -> claims

Idempotent: re-running against a seeded database creates zero duplicate
rows. Safe to run multiple times.

Usage:
  python -m brier_pipeline.demo
  (or via: make pipeline-demo)

Stages pending after E1-T1:
  - Resolution (E1-T3)
  - Scoring / FAS computation (E1-T2)
  - Leaderboard rendering (E1-T4)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from brier_pipeline.config import database_url
from brier_pipeline.extraction.extractor import FakeExtractor
from brier_pipeline.ingestion.youtube import FakeYouTubeClient
from brier_pipeline.transcription.storage import LocalFSStorage
from brier_pipeline.transcription.transcriber import FakeTranscriber, TranscriptSegment

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
LOCAL_STORAGE_ROOT = REPO_ROOT / "data" / "local"


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


def run_demo() -> dict[str, int]:
    """Execute the E1 fixture pipeline thread and return stage counters."""
    yt_client = FakeYouTubeClient(FIXTURES_DIR)
    fake_transcriber = FakeTranscriber(FIXTURES_DIR)
    extractor = FakeExtractor(FIXTURES_DIR)
    storage = LocalFSStorage(LOCAL_STORAGE_ROOT)

    # Load fixture analyst registry
    analysts_path = FIXTURES_DIR / "analysts.json"
    analysts_raw: list[dict[str, Any]] = json.loads(analysts_path.read_text(encoding="utf-8"))

    videos_persisted = 0
    transcripts_persisted = 0
    claims_persisted = 0
    claims_skipped = 0

    with psycopg.connect(database_url()) as conn:
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

    return {
        "videos_persisted": videos_persisted,
        "transcripts_persisted": transcripts_persisted,
        "claims_persisted": claims_persisted,
        "claims_skipped": claims_skipped,
    }


def main() -> None:
    """Entry point for `python -m brier_pipeline.demo`."""
    started_at = datetime.now(UTC)
    print("Brier pipeline demo — E1 fixture thread")
    print(f"  Started: {started_at.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  Fixtures: {FIXTURES_DIR}")
    print(f"  Storage:  {LOCAL_STORAGE_ROOT}")
    print()

    counts = run_demo()

    print("Stage results:")
    print(f"  Videos persisted:      {counts['videos_persisted']}")
    print(f"  Transcripts persisted: {counts['transcripts_persisted']}")
    print(f"  Claims persisted:      {counts['claims_persisted']}")
    print(f"  Claims skipped (dup):  {counts['claims_skipped']}")
    print()
    print("Stages complete: ingestion, transcription, extraction")
    print()
    print("Stages pending:")
    print("  Resolution pending  — implement in E1-T3")
    print("  Scoring pending     — implement in E1-T2")
    print("  Leaderboard pending — implement in E1-T4")


if __name__ == "__main__":
    main()
