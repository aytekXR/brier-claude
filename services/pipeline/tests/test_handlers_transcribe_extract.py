"""Track G #3: the transcribe + extract job handlers (mock-first, A2#2 + A2#6).

Two layers:
  * Seam-factory unit tests (no DB) — mirror test_handlers_price_source.py:
    the fixture fakes are the CI/dev path; the real adapters activate only when
    keyed; a missing key in production is a hard error for the product-correctness
    seams (extractor), and the AC-7 firewall wrapper screens DB-bound quotes.
  * DB-backed handler tests (db_conn) — the transcribe -> extract chain dispatches
    end to end via process_one on the fixtures, and the extract handler's three
    persistence gates (EC-3, AC-7, FR-203 routing) behave exactly as specified.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from brier_pipeline.extraction.extractor import CandidateSpan, FakeExtractor, LlmExtractor
from brier_pipeline.jobs import handlers, worker
from brier_pipeline.jobs.worker import enqueue_job, process_one
from brier_pipeline.models import Claim, SpecificityClass
from brier_pipeline.qa.queue import InMemoryReviewQueue, LabelStudioQueue
from brier_pipeline.transcription.storage import LocalFSStorage

# ---------------------------------------------------------------------------
# Seam-factory unit tests (no DB) — production guards + mock-first defaults
# ---------------------------------------------------------------------------


def _clear_real_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the test shell hermetic: no real adapter keys, dev environment."""
    for var in (
        "BRIER_ENV",
        "BRIER_ANTHROPIC_API_KEY",
        "BRIER_DEEPGRAM_API_KEY",
        "BRIER_LABEL_STUDIO_URL",
        "BRIER_LABEL_STUDIO_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)


class TestExtractorSeam:
    def test_returns_fake_in_dev_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)
        assert isinstance(handlers._get_extractor(), FakeExtractor)

    def test_returns_llm_when_keyed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)
        monkeypatch.setenv("BRIER_ANTHROPIC_API_KEY", "sk-test")
        assert isinstance(handlers._get_extractor(), LlmExtractor)

    def test_raises_in_production_without_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)
        monkeypatch.setenv("BRIER_ENV", "production")
        with pytest.raises(RuntimeError, match="BRIER_ANTHROPIC_API_KEY"):
            handlers._get_extractor()

    def test_returns_llm_in_production_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)
        monkeypatch.setenv("BRIER_ENV", "production")
        monkeypatch.setenv("BRIER_ANTHROPIC_API_KEY", "sk-test")
        assert isinstance(handlers._get_extractor(), LlmExtractor)


class TestReviewQueueSeam:
    def test_returns_inmemory_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)
        assert isinstance(handlers._get_review_queue(), InMemoryReviewQueue)

    def test_returns_label_studio_when_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)
        monkeypatch.setenv("BRIER_LABEL_STUDIO_URL", "http://localhost:8080")
        monkeypatch.setenv("BRIER_LABEL_STUDIO_TOKEN", "ls-test")
        assert isinstance(handlers._get_review_queue(), LabelStudioQueue)

    def test_inmemory_in_production_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The queue fake does not corrupt the product (routed claims stay
        # unpublishable), so production warns rather than hard-failing.
        _clear_real_keys(monkeypatch)
        monkeypatch.setenv("BRIER_ENV", "production")
        assert isinstance(handlers._get_review_queue(), InMemoryReviewQueue)


class TestStorageSeam:
    def test_returns_localfs_pointed_at_storage_root(self) -> None:
        storage = handlers._get_storage()
        assert isinstance(storage, LocalFSStorage)
        assert storage.root == handlers._LOCAL_STORAGE_ROOT


class TestAc7FirewallWrapper:
    def test_flags_recommendation_terms(self) -> None:
        assert "buy" in handlers._forbidden_terms_in("you should buy the dip")
        assert "guaranteed" in handlers._forbidden_terms_in("guaranteed gains ahead")

    def test_clean_quote_returns_empty(self) -> None:
        assert handlers._forbidden_terms_in("BTC closed above the stated target") == []


# ---------------------------------------------------------------------------
# DB-backed handler tests (db_conn) — rolled back; skip when no dev DB
# ---------------------------------------------------------------------------


def _get_or_create_parent(cur: Any) -> int:
    """Insert-or-get the NorthChain fixture analyst; return its id.

    ON CONFLICT DO NOTHING so the row is reused whether or not `make seed` (or a
    prior committed test) already created it — the surrounding test rolls back.
    """
    cur.execute(
        """
        insert into analysts (channel_id, display_name, slug, status)
        values ('UCfix-northchain-0001', 'NorthChain', 'northchain', 'active')
        on conflict (channel_id) do nothing
        returning id
        """
    )
    row = cur.fetchone()
    if row is None:
        cur.execute("select id from analysts where channel_id = 'UCfix-northchain-0001'")
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _get_or_create_video(cur: Any, analyst_id: int, youtube_video_id: str) -> int:
    """Insert-or-get a fixture-backed video row; return its id."""
    cur.execute(
        """
        insert into videos (analyst_id, youtube_video_id, title, published_at)
        values (%s, %s, 'G3 handler test video', '2024-12-01T18:00:00Z')
        on conflict (youtube_video_id) do nothing
        returning id
        """,
        (analyst_id, youtube_video_id),
    )
    row = cur.fetchone()
    if row is None:
        cur.execute("select id from videos where youtube_video_id = %s", (youtube_video_id,))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


class TestTranscribeExtractChain:
    """transcribe -> extract dispatch end to end on the fixtures (mock-first)."""

    def test_chain_persists_transcript_and_claims(
        self, db_conn: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_real_keys(monkeypatch)
        # Hermetic blob storage: transcribe writes and extract reads the same tmp
        # dir; FakeTranscriber/FakeExtractor still read the read-only fixtures.
        monkeypatch.setattr(handlers, "_LOCAL_STORAGE_ROOT", tmp_path)

        youtube_video_id = "NCfx-btc-dec01"  # has a fixture transcript + claim quotes
        with db_conn.cursor() as cur:
            analyst_id = _get_or_create_parent(cur)
            video_id = _get_or_create_video(cur, analyst_id, youtube_video_id)

        # bootstrap_handlers() is idempotent (overwrites by kind); we do NOT
        # clear the global registry — a finally: clear_handlers() would wipe the
        # self-registered handlers other test files assert at module load.
        worker.bootstrap_handlers()

        transcribe_job = enqueue_job(
            db_conn, "transcribe", {"video_id": video_id, "youtube_video_id": youtube_video_id}
        )
        # 1) transcribe runs -> transcript row + an extract job is enqueued
        assert process_one(db_conn) is True
        with db_conn.cursor() as cur:
            cur.execute("select state from jobs where id = %s", (transcribe_job,))
            assert str(cur.fetchone()[0]) == "done"

            cur.execute(
                "select id from transcripts where video_id = %s and source = 'deepgram'",
                (video_id,),
            )
            t_row = cur.fetchone()
            assert t_row is not None, "transcribe must insert a deepgram transcript row"
            transcript_id = int(t_row[0])

            cur.execute(
                "select id from jobs where kind = 'extract' "
                "and (payload->>'transcript_id')::int = %s",
                (transcript_id,),
            )
            extract_job = int(cur.fetchone()[0])

        # 2) extract runs -> claims persisted for this transcript
        assert process_one(db_conn) is True
        with db_conn.cursor() as cur:
            cur.execute("select state from jobs where id = %s", (extract_job,))
            assert str(cur.fetchone()[0]) == "done"

            cur.execute("select count(*) from claims where transcript_id = %s", (transcript_id,))
            assert int(cur.fetchone()[0]) >= 1, "extract must persist at least one claim"


# --- Precise gate test: EC-3 skip + AC-7 drop + FR-203 routing -------------


class _StubExtractor:
    """Yields a fixed list of claims so the gate behaviour is fully controlled."""

    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims
        self._i = 0

    def detect_candidates(self, segments: Any) -> list[CandidateSpan]:
        return [
            CandidateSpan(start_seconds=float(i), end_seconds=float(i) + 1, text=f"span-{i}")
            for i in range(len(self._claims))
        ]

    def structure_claim(self, span: CandidateSpan, *, uttered_at: datetime) -> Claim:
        claim = self._claims[self._i]
        self._i += 1
        return claim


class _StubStorage:
    """Returns one trivial segment; the stub extractor ignores its content."""

    def get(self, key: str) -> bytes:
        return json.dumps([{"start_seconds": 0.0, "end_seconds": 1.0, "text": "x"}]).encode("utf-8")


def _claim(
    offset: int, *, quote: str, confidence: float, flags: dict[str, Any] | None = None
) -> Claim:
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
        model_version="stub",
        prompt_version="v1",
        uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
        flags=flags or {},
    )


class TestExtractHandlerGates:
    """EC-3 excluded + AC-7 forbidden claims never persist; FR-203 routes the rest."""

    def test_gates(self, db_conn: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_real_keys(monkeypatch)

        # Four candidate claims exercising every gate:
        normal = _claim(10, quote="BTC reaches the stated target", confidence=0.95)
        excluded = _claim(
            20,
            quote="BTC to the stated level",
            confidence=0.95,
            flags={"excluded_reason": "sarcasm"},
        )
        forbidden = _claim(30, quote="you should buy BTC now", confidence=0.95)
        low_conf = _claim(40, quote="BTC drifts toward the level", confidence=0.30)

        stub = _StubExtractor([normal, excluded, forbidden, low_conf])
        captured_queue = InMemoryReviewQueue()
        monkeypatch.setattr(handlers, "_get_extractor", lambda: stub)
        monkeypatch.setattr(handlers, "_get_storage", lambda: _StubStorage())
        monkeypatch.setattr(handlers, "_get_review_queue", lambda: captured_queue)

        with db_conn.cursor() as cur:
            analyst_id = _get_or_create_parent(cur)
            video_id = _get_or_create_video(cur, analyst_id, "NCfx-btc-dec01")
            cur.execute(
                """
                insert into transcripts (video_id, source, storage_pointer)
                values (%s, 'deepgram', 'transcripts/stub.json')
                on conflict (video_id, source) do nothing
                returning id
                """,
                (video_id,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "select id from transcripts where video_id = %s and source = 'deepgram'",
                    (video_id,),
                )
                row = cur.fetchone()
            transcript_id = int(row[0])

        handlers.extract_handler({"transcript_id": transcript_id, "video_id": video_id}, db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "select source_offset_seconds, publishable from claims "
                "where transcript_id = %s order by source_offset_seconds",
                (transcript_id,),
            )
            rows = cur.fetchall()

        offsets = {int(r[0]): bool(r[1]) for r in rows}
        # EC-3 (20) and AC-7 (30) dropped; normal (10) + low-confidence (40) kept.
        assert set(offsets) == {10, 40}
        assert offsets[10] is True, "high-confidence claim auto-approves (publishable)"
        assert offsets[40] is False, "low-confidence claim routes to QA (not publishable)"

        # FR-203: only the routed low-confidence claim was enqueued for review.
        assert [c.source_offset_seconds for c in captured_queue.enqueued] == [40]
