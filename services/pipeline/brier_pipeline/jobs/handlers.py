"""Pipeline job handlers: resolve_claims, score_analysts, transcribe, extract.

All four stages are wired on the mock-first seam: the fixture-backed fakes are
the CI/dev path, and the real adapters activate only when their key is set —
each behind a production guard that REFUSES to silently fall back to fixtures
(BRIER_ENV=production + missing key -> RuntimeError).  None of the real adapters
adds a heavy dependency: prices via CoinGecko (ADR-0009 stdlib urllib),
transcription via Deepgram (stdlib REST), and extraction via the Anthropic
completion seam (ADR-0005 stdlib REST).

Still gated (NOT reached by the incremental path wired here):
  * ADR-0003 faster-whisper — only the `backfill` transcribe mode (WhisperTranscriber);
    the incremental path uses Deepgram/Fake and needs no install.
  * ADR-0004 boto3/R2 — durable blob storage.  The interim path is LocalFSStorage
    (claims persist in Postgres; the transcript blob is a re-extraction/audit
    artifact, so local disk is degraded-not-broken — logged, not fatal).
  * ADR-0008 sentence-transformers — FR-205 dedup; the extract handler skips it.

transcribe/extract only fire once upstream ingestion (poll_channels) enqueues
`transcribe` jobs, which needs a registered roster + YouTube key — separately
human-gated — so wiring them here does not start any metered work on its own.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg

from brier_pipeline.config import (
    anthropic_api_key,
    coingecko_api_key,
    extraction_model,
    is_production,
    label_studio_token,
    label_studio_url,
)
from brier_pipeline.extraction import llm as llm_module
from brier_pipeline.extraction.extractor import (
    Extractor,
    FakeExtractor,
    LlmExtractor,
    is_excluded_span,
)
from brier_pipeline.jobs import worker
from brier_pipeline.jobs.persistence import claim_exists, insert_claim, upsert_transcript
from brier_pipeline.qa.queue import (
    InMemoryReviewQueue,
    LabelStudioQueue,
    ReviewQueue,
    route_low_confidence,
)
from brier_pipeline.resolution.prices import (
    CoinGeckoPriceSource,
    FakePriceSource,
    PriceSource,
)
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.scoring.fas import run_score_pass
from brier_pipeline.transcription.storage import LocalFSStorage, Storage
from brier_pipeline.transcription.transcriber import TranscriptSegment, get_transcriber

logger = logging.getLogger(__name__)

# services/pipeline/brier_pipeline/jobs -> repo root is 4 up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
# Repo-root/data/fixtures — the same canonical path run_score_pass derives when
# prices is None.
_FIXTURES_DIR = _REPO_ROOT / "data" / "fixtures"
# Interim transcript blob storage (ADR-0004 R2 is the durable target).
_LOCAL_STORAGE_ROOT = _REPO_ROOT / "data" / "local"
# Extraction prompt template version stamped on every claim (NFR-2).
_PROMPT_VERSION = "v1"
# AC-7 firewall vocabulary lives in the repo-root copy_lint script (A2#6).
_COPY_LINT_PATH = _REPO_ROOT / "scripts" / "copy_lint.py"
_forbidden_terms_fn: Callable[[str], list[str]] | None = None


def _forbidden_terms_in(text: str) -> list[str]:
    """AC-7 firewall (A2#6): forbidden recommendation terms found in *text*.

    Loads scripts/copy_lint.py — the single source of truth for the FORBIDDEN
    vocabulary — via importlib so the repo-root script need not be importable as
    a package from the installed pipeline.  The resolved function is cached.
    """
    global _forbidden_terms_fn
    if _forbidden_terms_fn is None:
        spec = importlib.util.spec_from_file_location("brier_copy_lint", _COPY_LINT_PATH)
        if spec is None or spec.loader is None:  # pragma: no cover - import wiring
            raise RuntimeError(f"cannot load AC-7 firewall from {_COPY_LINT_PATH}")
        module: Any = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _forbidden_terms_fn = module.forbidden_terms_in
    return _forbidden_terms_fn(text)


def _get_price_source() -> PriceSource:
    """Return the configured price source: CoinGecko when keyed, else Fake.

    Mirrors get_alerter (E6): the fake is the CI/dev path; the real adapter
    activates only when BRIER_COINGECKO_API_KEY is set (ADR-0009, no new dep).

    In production (BRIER_ENV=production) a missing key is a hard error — we will
    NOT silently score real analysts against the 18-month fixture prices. In
    CI/dev the fake is returned with a warning so a misconfigured host is caught.
    """
    if coingecko_api_key():
        return CoinGeckoPriceSource()
    if is_production():
        raise RuntimeError(
            "BRIER_COINGECKO_API_KEY is not set but BRIER_ENV=production: refusing "
            "to run resolve_claims/score_analysts against FakePriceSource (fixture "
            "prices). Set the CoinGecko key (ADR-0009) before scoring real analysts."
        )
    logger.warning(
        "No BRIER_COINGECKO_API_KEY set; resolve_claims/score_analysts are using "
        "FakePriceSource (fixtures). This is the CI/dev path — production must set the key."
    )
    return FakePriceSource(_FIXTURES_DIR)


def resolve_claims_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """`resolve_claims` job: append resolutions for every due open claim.

    The worker (process_one) owns the transaction; resolve_open_claims with conn
    set does not commit (NFR-3 append-only path).  payload is unused.
    """
    resolve_open_claims(_get_price_source(), conn=conn)


def score_analysts_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """`score_analysts` job: append a new nightly score_run + scores.

    Appends to the append-only ledger (a fresh score_run, NFR-3); run_score_pass
    with conn set does not commit.  payload is unused (the scheduled pass is
    always 'nightly'; methodology bumps use recompute_all separately).
    """
    run_score_pass("nightly", conn=conn, prices=_get_price_source())


# ---------------------------------------------------------------------------
# transcribe + extract seams (mock-first; real adapters activate when keyed)
# ---------------------------------------------------------------------------


def _get_storage() -> Storage:
    """Transcript/audio blob storage.  LocalFS is the active path everywhere.

    Cloudflare R2 (R2Storage) is the durable production target but stays gated on
    ADR-0004 (boto3 not installed).  In production we log a warning so the
    interim local-disk storage is visible, but do NOT hard-fail: the product
    output (claims) lives in Postgres, and the transcript blob is only a
    re-extraction/audit artifact — local disk is degraded, not broken.
    """
    if is_production():
        logger.warning(
            "Using LocalFSStorage for transcript blobs in production; durable "
            "Cloudflare R2 storage is gated on ADR-0004. Claims persist in "
            "Postgres; the blob is a re-extraction/audit artifact only."
        )
    return LocalFSStorage(_LOCAL_STORAGE_ROOT)


def _get_extractor() -> Extractor:
    """Configured claim extractor: LlmExtractor when keyed, else FakeExtractor.

    Mirrors _get_price_source / get_transcriber: the fixture FakeExtractor is the
    CI/dev path; the real LlmExtractor (ADR-0005 stdlib-REST seam, no new dep)
    activates only when BRIER_ANTHROPIC_API_KEY is set.  In production a missing
    key is a hard error — we will NOT structure real claims from fixture replays.
    """
    if anthropic_api_key():
        return LlmExtractor(
            model_version=extraction_model(),
            prompt_version=_PROMPT_VERSION,
            completion=llm_module.completion,
        )
    if is_production():
        raise RuntimeError(
            "BRIER_ANTHROPIC_API_KEY is not set but BRIER_ENV=production: refusing "
            "to extract real claims with the fixture FakeExtractor. Set the Anthropic "
            "key (ADR-0005) before running extraction against real transcripts."
        )
    logger.warning(
        "No BRIER_ANTHROPIC_API_KEY set; extract is using FakeExtractor (fixtures). "
        "This is the CI/dev path — production must set the key."
    )
    return FakeExtractor(_FIXTURES_DIR)


def _get_review_queue() -> ReviewQueue:
    """Configured QA review queue: LabelStudioQueue when keyed, else InMemory.

    InMemoryReviewQueue is the CI/dev path; the live LabelStudioQueue (stdlib
    urllib, no SDK) activates when both BRIER_LABEL_STUDIO_URL and
    BRIER_LABEL_STUDIO_TOKEN are set.  Unlike the extractor/transcriber seams a
    missing queue does NOT corrupt the product — routed claims are still stored
    with publishable=False (unreviewed) and are simply not surfaced to reviewers
    — so in production we warn rather than hard-fail.
    """
    if label_studio_url() and label_studio_token():
        return LabelStudioQueue()
    if is_production():
        logger.warning(
            "No Label Studio config in production; routed low-confidence claims "
            "are stored unpublishable but not surfaced to reviewers. Configure "
            "BRIER_LABEL_STUDIO_URL/TOKEN (PRD §21) to enable human review."
        )
    return InMemoryReviewQueue()


def transcribe_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """`transcribe` job: acquire a transcript for one video, then enqueue extract.

    Payload (enqueued by the poller/backfill): {"video_id", "youtube_video_id"};
    an optional "mode" selects 'incremental' (default, Deepgram/Fake) vs
    'backfill' (Whisper, ADR-0003).  get_transcriber() owns the production guard.

    Idempotent: transcripts has UNIQUE(video_id, source); a retried job reuses the
    existing transcript row and re-enqueues extract.  The worker (process_one)
    owns the transaction — this handler never commits.
    """
    video_id = int(payload["video_id"])
    youtube_video_id = str(payload["youtube_video_id"])
    mode = str(payload.get("mode", "incremental"))

    with conn.cursor() as cur:
        cur.execute("select id from videos where id = %s", (video_id,))
        if cur.fetchone() is None:
            raise RuntimeError(f"transcribe: no video row for video_id={video_id}")

    # incremental -> deepgram, backfill -> whisper (transcripts.source vocabulary).
    source = "whisper" if mode == "backfill" else "deepgram"

    with conn.cursor() as cur:
        cur.execute(
            "select id from transcripts where video_id = %s and source = %s",
            (video_id, source),
        )
        existing = cur.fetchone()

    if existing is not None:
        transcript_id = int(existing[0])
    else:
        transcriber = get_transcriber(mode)
        # FakeTranscriber locates the fixture by the bare video id (it strips only
        # an 'audio://' prefix); demo.py passes the bare id, so we do too.  The
        # real DeepgramTranscriber treats the pointer as an opaque storage key.
        segments = transcriber.transcribe(youtube_video_id)
        storage_key = f"transcripts/{youtube_video_id}.json"
        body = json.dumps([s.model_dump() for s in segments], indent=2).encode("utf-8")
        _get_storage().put(storage_key, body)
        with conn.cursor() as cur:
            transcript_id, _created = upsert_transcript(
                cur, video_id, source=source, storage_pointer=storage_key
            )

    worker.enqueue_job(conn, "extract", {"transcript_id": transcript_id, "video_id": video_id})


def extract_handler(payload: dict[str, Any], conn: psycopg.Connection[Any]) -> None:
    """`extract` job: structure claims from one transcript (FR-201/202/203/204).

    Payload (enqueued by transcribe_handler): {"transcript_id", "video_id"}.
    Mirrors the demo extraction stage with THREE production gates the demo omits:
      * EC-3 (is_excluded_span): sarcasm/hypothetical/paraphrase never persist.
      * AC-7 (A2#6): a claim quote containing recommendation language never
        persists (forbidden_terms_in, the copy_lint single source of truth).
      * FR-203 (A2#2): low-confidence/sponsor/legal claims route to the QA queue
        with publishable=False; high-confidence claims auto-approve.
    FR-204 non-falsifiability is applied inside structure_claim (those claims ARE
    persisted — they enter the F denominator but never score).  FR-205 dedup
    (ADR-0008) is skipped — see the gated stub.  Idempotent on
    (transcript_id, source_offset_seconds); the worker owns the transaction.
    """
    transcript_id = int(payload["transcript_id"])

    with conn.cursor() as cur:
        cur.execute(
            """
            select t.storage_pointer, t.video_id, v.analyst_id, v.published_at
            from transcripts t join videos v on v.id = t.video_id
            where t.id = %s
            """,
            (transcript_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"extract: no transcript row for transcript_id={transcript_id}")
    storage_pointer = str(row[0])
    video_id = int(row[1])
    analyst_id = int(row[2])
    uttered_at = row[3]

    body = _get_storage().get(storage_pointer)
    segments = [TranscriptSegment(**seg) for seg in json.loads(body.decode("utf-8"))]

    extractor = _get_extractor()
    queue = _get_review_queue()

    for span in extractor.detect_candidates(segments):
        claim = extractor.structure_claim(span, uttered_at=uttered_at)
        claim.analyst_id = analyst_id
        claim.video_id = video_id
        claim.transcript_id = transcript_id

        # EC-3: not the analyst's own statement -> never persisted.
        if is_excluded_span(claim):
            continue
        # AC-7 (A2#6): recommendation language must never reach the DB.
        if _forbidden_terms_in(claim.quote or ""):
            logger.warning(
                "AC-7: dropping claim with forbidden terms in quote (transcript_id=%s, offset=%s)",
                transcript_id,
                claim.source_offset_seconds,
            )
            continue

        # FR-205 dedup seam (ADR-0008 gated): sentence-transformers is not
        # installed; dedup_claims(..., embedder=None) would raise. Skip until the
        # ADR is approved.  # TASK: E3-T5 (ADR-0008 gated)

        # FR-203 (A2#2): in-place routing -> review_state + publishable.
        routed = route_low_confidence([claim])

        with conn.cursor() as cur:
            if claim_exists(cur, transcript_id, claim.source_offset_seconds):
                continue
            claim.id = insert_claim(cur, analyst_id, video_id, transcript_id, claim)

        # HP-4: enqueue to the live review queue AFTER insert so claim.id is real.
        if routed:
            queue.enqueue(claim)


# Self-register at import, matching the poller/deletion/freshness/sla/erasure
# convention.  bootstrap_handlers() also registers these explicitly so the
# production worker is deterministic even after a test clear_handlers().
worker.register_handler("resolve_claims", resolve_claims_handler)
worker.register_handler("score_analysts", score_analysts_handler)
worker.register_handler("transcribe", transcribe_handler)
worker.register_handler("extract", extract_handler)
