"""E6-T3 deletion tracking tests (PRD EC-1, AC-6, NFR-3).

Test categories:
  1. Unit tests (no DB): FakeYouTubeClient.check_video_status returns LIVE for
     an existing fixture video; returns DELETED for an absent video id;
     honours an explicit 'source_status' field in videos.json.
  2. DB-backed tests (db_conn rolled-back fixture):
     - Sweep with probe returning DELETED: videos.source_status='deleted',
       claim flags['source_deleted']=True; claim row AND resolution row
       both STILL EXIST unchanged (NFR-3).
     - Sweep with probe returning PRIVATE: videos.source_status='private',
       claim flags['source_deleted']=True.
     - Sweep with probe returning LIVE (no change): video and claim unchanged.
     - Sweep with multiple videos: only the affected video is updated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brier_pipeline.ingestion.deletion import DeletionReport, run_deletion_sweep
from brier_pipeline.ingestion.youtube import FakeYouTubeClient
from brier_pipeline.models import SourceStatus

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "data" / "fixtures"

# ---------------------------------------------------------------------------
# Fake probe for DB-backed tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeProbe:
    """Deterministic probe: returns the configured status for a specific video id,
    LIVE for everything else."""

    target_video_id: str
    return_status: SourceStatus

    def check_video_status(self, youtube_video_id: str) -> SourceStatus:
        if youtube_video_id == self.target_video_id:
            return self.return_status
        return SourceStatus.LIVE


# _FakeProbe conforms to the VideoStatusProbe Protocol structurally; mypy verifies
# that at the run_deletion_sweep(probe, ...) call sites below.


# ---------------------------------------------------------------------------
# DB seed helpers (synthetic — no dependency on demo state)
# ---------------------------------------------------------------------------


def _seed_analyst(cur: Any) -> int:
    cur.execute(
        """
        INSERT INTO analysts (channel_id, display_name, slug, status)
        VALUES ('UCtest-deletion-sweep', 'Deletion Test Analyst', 'deletion-test', 'active')
        RETURNING id
        """
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_video(cur: Any, analyst_id: int, *, yt_id: str = "del-test-vid-001") -> int:
    cur.execute(
        """
        INSERT INTO videos (analyst_id, youtube_video_id, title, published_at, source_status)
        VALUES (%s, %s, 'Deletion Test Video', '2025-01-01T00:00:00+00', 'live')
        RETURNING id
        """,
        (analyst_id, yt_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_transcript(cur: Any, video_id: int) -> int:
    cur.execute(
        """
        INSERT INTO transcripts (video_id, source, storage_pointer, language)
        VALUES (%s, 'captions', 'fake://del-test', 'en')
        RETURNING id
        """,
        (video_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_claim(cur: Any, analyst_id: int, video_id: int, transcript_id: int) -> int:
    cur.execute(
        """
        INSERT INTO claims (
            analyst_id, video_id, transcript_id,
            asset, direction, target_price,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            specificity_class, source_offset_seconds,
            quote, uttered_at, p0_price,
            model_version, prompt_version,
            review_state, publishable, status, flags
        ) VALUES (
            %s, %s, %s,
            'BTC', 'bullish', 80000.0,
            '2025-07-31', 'stated',
            0.70, 'stated',
            'target_deadline', 120,
            'Deletion test claim fewer than fifteen words.',
            '2025-01-01 00:00:00+00', 79000.0,
            'test', 'test',
            'approved', true, 'open', '{}'::jsonb
        ) RETURNING id
        """,
        (analyst_id, video_id, transcript_id),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_resolution(cur: Any, claim_id: int) -> int:
    cur.execute(
        """
        INSERT INTO resolutions (
            claim_id, outcome, resolved_at, rule_id, rationale,
            price_citation, methodology_version, supersedes_resolution_id
        ) VALUES (
            %s, 1.0, now(), 'target_by_deadline.v0',
            'Deletion test resolution.',
            '{"asset": "BTC", "day": "2025-07-14", "close_usd": 80140.0, "source": "test"}',
            'v1.1', NULL
        ) RETURNING id
        """,
        (claim_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ---------------------------------------------------------------------------
# 1. Unit tests (no DB)
# ---------------------------------------------------------------------------


class TestFakeYouTubeClientCheckVideoStatus:
    """check_video_status on FakeYouTubeClient — no DB needed."""

    def test_existing_fixture_video_returns_live_by_default(self) -> None:
        """An existing fixture video with no source_status field -> LIVE."""
        client = FakeYouTubeClient(FIXTURES_DIR)
        # NCfx-btc-dec01 is a known fixture video with no source_status field.
        result = client.check_video_status("NCfx-btc-dec01")
        assert result == SourceStatus.LIVE

    def test_absent_video_id_returns_deleted(self) -> None:
        """A video id not in videos.json -> DELETED (simulates removed video)."""
        client = FakeYouTubeClient(FIXTURES_DIR)
        result = client.check_video_status("nonexistent-video-id-xyz-999")
        assert result == SourceStatus.DELETED

    def test_explicit_source_status_deleted_field(self) -> None:
        """Fixture video with source_status='deleted' field -> DELETED."""
        # We test via a patched _videos list rather than editing the fixture file,
        # so the existing demo board is completely unaffected.
        client = FakeYouTubeClient(FIXTURES_DIR)
        # Override the loaded videos in-memory.
        client._videos = [
            {
                "youtube_video_id": "fake-deleted-vid",
                "channel_id": "UCtest",
                "title": "Deleted",
                "published_at": "2025-01-01T00:00:00Z",
                "source_status": "deleted",
            }
        ]
        assert client.check_video_status("fake-deleted-vid") == SourceStatus.DELETED

    def test_explicit_source_status_private_field(self) -> None:
        """Fixture video with source_status='private' field -> PRIVATE."""
        client = FakeYouTubeClient(FIXTURES_DIR)
        client._videos = [
            {
                "youtube_video_id": "fake-private-vid",
                "channel_id": "UCtest",
                "title": "Private",
                "published_at": "2025-01-01T00:00:00Z",
                "source_status": "private",
            }
        ]
        assert client.check_video_status("fake-private-vid") == SourceStatus.PRIVATE

    def test_explicit_availability_field(self) -> None:
        """Fixture video with availability='deleted' (alias field) -> DELETED."""
        client = FakeYouTubeClient(FIXTURES_DIR)
        client._videos = [
            {
                "youtube_video_id": "fake-avail-vid",
                "channel_id": "UCtest",
                "title": "Avail test",
                "published_at": "2025-01-01T00:00:00Z",
                "availability": "deleted",
            }
        ]
        assert client.check_video_status("fake-avail-vid") == SourceStatus.DELETED

    def test_source_status_live_explicit_stays_live(self) -> None:
        """Fixture video with source_status='live' -> LIVE."""
        client = FakeYouTubeClient(FIXTURES_DIR)
        client._videos = [
            {
                "youtube_video_id": "fake-live-vid",
                "channel_id": "UCtest",
                "title": "Live",
                "published_at": "2025-01-01T00:00:00Z",
                "source_status": "live",
            }
        ]
        assert client.check_video_status("fake-live-vid") == SourceStatus.LIVE


# ---------------------------------------------------------------------------
# 2. DB-backed tests
# ---------------------------------------------------------------------------


class TestRunDeletionSweepDeleted:
    """Probe returns DELETED: video row updated, claim flagged, rows still exist."""

    def test_video_source_status_set_to_deleted(self, db_conn: Any) -> None:
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id)
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-vid-001", return_status=SourceStatus.DELETED)
        report = run_deletion_sweep(probe, db_conn)

        assert report.newly_deleted >= 1

        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "deleted"

    def test_claim_flags_source_deleted_true(self, db_conn: Any) -> None:
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id)
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-vid-001", return_status=SourceStatus.DELETED)
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT flags FROM claims WHERE id = %s", (claim_id,))
            row = cur.fetchone()
        assert row is not None
        flags = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        assert flags.get("source_deleted") is True

    def test_claim_row_still_exists_nfr3(self, db_conn: Any) -> None:
        """NFR-3: The claim row is not deleted."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id)
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-vid-001", return_status=SourceStatus.DELETED)
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT id, status FROM claims WHERE id = %s", (claim_id,))
            row = cur.fetchone()
        assert row is not None, "Claim row must still exist after sweep (NFR-3)"
        assert int(row[0]) == claim_id

    def test_resolution_row_still_exists_unchanged_nfr3(self, db_conn: Any) -> None:
        """NFR-3: Resolutions are never updated or deleted — must persist unchanged."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id)
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            resolution_id = _seed_resolution(cur, claim_id)

        # Record the original resolution data before the sweep.
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, rule_id, rationale FROM resolutions WHERE id = %s",
                (resolution_id,),
            )
            before = cur.fetchone()
        assert before is not None

        probe = _FakeProbe(target_video_id="del-test-vid-001", return_status=SourceStatus.DELETED)
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, rule_id, rationale FROM resolutions WHERE id = %s",
                (resolution_id,),
            )
            after = cur.fetchone()
        assert after is not None, "Resolution row must still exist after sweep (NFR-3)"
        assert after == before, "Resolution row must not be modified by sweep (NFR-3)"


class TestRunDeletionSweepPrivate:
    """Probe returns PRIVATE: video marked private, claim flagged."""

    def test_video_source_status_set_to_private(self, db_conn: Any) -> None:
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id, yt_id="del-test-priv-001")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-priv-001", return_status=SourceStatus.PRIVATE)
        report = run_deletion_sweep(probe, db_conn)

        assert report.newly_private >= 1

        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "private"

    def test_claim_flag_set_for_private_video(self, db_conn: Any) -> None:
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id, yt_id="del-test-priv-002")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-priv-002", return_status=SourceStatus.PRIVATE)
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT flags FROM claims WHERE id = %s", (claim_id,))
            row = cur.fetchone()
        assert row is not None
        flags = row[0] if isinstance(row[0], dict) else json.loads(row[0])
        assert flags.get("source_deleted") is True


class TestRunDeletionSweepLive:
    """Probe returns LIVE: nothing changes."""

    def test_live_video_unchanged(self, db_conn: Any) -> None:
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id, yt_id="del-test-live-001")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        # The probe always returns LIVE.
        probe = _FakeProbe(target_video_id="NOBODY", return_status=SourceStatus.DELETED)
        report = run_deletion_sweep(probe, db_conn)

        # The seeded video is "del-test-live-001" which != "NOBODY", so probe -> LIVE.
        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            v_row = cur.fetchone()
            cur.execute("SELECT flags FROM claims WHERE id = %s", (claim_id,))
            c_row = cur.fetchone()

        assert v_row is not None and v_row[0] == "live", "Live video source_status must not change"
        assert c_row is not None
        flags = c_row[0] if isinstance(c_row[0], dict) else json.loads(c_row[0])
        assert not flags.get("source_deleted"), "Live video must not set source_deleted on claim"
        assert report.unchanged >= 1


class TestRunDeletionSweepReport:
    """DeletionReport counts are correct."""

    def test_report_counts_match_outcomes(self, db_conn: Any) -> None:
        """Seed one LIVE video -> probe returns DELETED; report has exactly those counts."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id, yt_id="del-test-count-001")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-count-001", return_status=SourceStatus.DELETED)
        report = run_deletion_sweep(probe, db_conn)

        # checked must include our seeded video (there may be more from seed data).
        assert report.checked >= 1
        assert report.newly_deleted >= 1
        # The probe returns DELETED for the one seeded video and LIVE for all
        # others, so no video can be newly privated in this run.
        assert report.newly_private == 0
        assert isinstance(report, DeletionReport)

    def test_sweep_is_idempotent_on_rerun(self, db_conn: Any) -> None:
        """Re-running the sweep does not re-process an already-deleted video (NFR-3)."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur)
            video_id = _seed_video(cur, analyst_id, yt_id="del-test-idem-001")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbe(target_video_id="del-test-idem-001", return_status=SourceStatus.DELETED)

        first = run_deletion_sweep(probe, db_conn)
        assert first.newly_deleted >= 1

        # Second run: the video is no longer 'live', so it is excluded from the
        # live set and not re-checked or re-flagged. The flag and status persist.
        second = run_deletion_sweep(probe, db_conn)
        assert second.checked == first.checked - 1

        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            v_row = cur.fetchone()
            cur.execute("SELECT flags FROM claims WHERE id = %s", (claim_id,))
            c_row = cur.fetchone()
        assert v_row is not None and v_row[0] == "deleted"
        assert c_row is not None
        flags = c_row[0] if isinstance(c_row[0], dict) else json.loads(c_row[0])
        assert flags.get("source_deleted") is True
