"""T2-extend: deletion boundary and edge regression tests (EC-1, AC-6, NFR-3).

Covers genuine gaps NOT present in tests/test_deletion.py:
  1. Resolution persistence after a PRIVATE sweep (EC-1, NFR-3) — only the
     DELETED case is tested in the existing file; PRIVATE is a gap.
  2. Multiple claims on the same video — ALL claims are flagged and ALL persist
     after the sweep (existing tests cover only single-claim scenarios).
  3. Video with no claims — sweep handles an empty-claim set without error.
  4. Pre-existing claim flags are merged (not overwritten) when source_deleted
     is propagated; this exercises flag_source_deleted's copy-and-extend logic
     at the DB write level.
  5. Idempotency for PRIVATE — re-running on an already-private video does not
     re-process it (only DELETED idempotency is tested in the existing file).
  6. No alerts dispatched — the deletion sweep does not write to the alerts
     table; confirmed by counting rows before and after a sweep run.
  7. DeletionReport sum invariant: checked == newly_deleted + newly_private
     + unchanged must hold for every run.
  8. Clean no-op assertions: when the probe returns LIVE for everything,
     newly_deleted == 0 AND newly_private == 0 (the existing test only asserts
     unchanged >= 1 but does not assert the zero-deleted-or-private conditions).

DB id namespace:
  channel_id prefix: 'UC-t2x-del-'
  youtube_video_id prefix: 'DELt2x-'
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from brier_pipeline.ingestion.deletion import DeletionReport, run_deletion_sweep
from brier_pipeline.models import SourceStatus

# ---------------------------------------------------------------------------
# Namespace prefixes (required by the T2-extend harness rules)
# ---------------------------------------------------------------------------

_CHANNEL_PREFIX = "UC-t2x-del"
_VIDEO_PREFIX = "DELt2x-"


# ---------------------------------------------------------------------------
# Fake probes
# ---------------------------------------------------------------------------


@dataclass
class _FakeProbeT2:
    """Deterministic probe: returns return_status for target_video_id,
    SourceStatus.LIVE for every other video id."""

    target_video_id: str
    return_status: SourceStatus

    def check_video_status(self, youtube_video_id: str) -> SourceStatus:
        if youtube_video_id == self.target_video_id:
            return self.return_status
        return SourceStatus.LIVE


@dataclass
class _AllLiveProbe:
    """Probe that always returns LIVE regardless of video id."""

    def check_video_status(self, youtube_video_id: str) -> SourceStatus:
        return SourceStatus.LIVE


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------


def _seed_analyst(cur: Any, suffix: str) -> int:
    cur.execute(
        """
        INSERT INTO analysts (channel_id, display_name, slug, status)
        VALUES (%s, %s, %s, 'active')
        RETURNING id
        """,
        (
            f"{_CHANNEL_PREFIX}-{suffix}",
            f"T2 Del Test Analyst {suffix}",
            f"t2-del-analyst-{suffix}",
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_video(
    cur: Any,
    analyst_id: int,
    *,
    yt_id: str,
    source_status: str = "live",
) -> int:
    cur.execute(
        """
        INSERT INTO videos (analyst_id, youtube_video_id, title, published_at, source_status)
        VALUES (%s, %s, 'T2 Deletion Edge Test Video', '2025-01-01T00:00:00+00', %s)
        RETURNING id
        """,
        (analyst_id, yt_id, source_status),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_transcript(cur: Any, video_id: int) -> int:
    cur.execute(
        """
        INSERT INTO transcripts (video_id, source, storage_pointer, language)
        VALUES (%s, 'captions', 'fake://t2x-del-test', 'en')
        RETURNING id
        """,
        (video_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _seed_claim(
    cur: Any,
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    *,
    flags: dict[str, Any] | None = None,
) -> int:
    flags_json = json.dumps(flags if flags is not None else {})
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
            'T2 del edge test claim fewer than fifteen.',
            '2025-01-01 00:00:00+00', 79000.0,
            'test', 'test',
            'approved', true, 'open', %s::jsonb
        ) RETURNING id
        """,
        (analyst_id, video_id, transcript_id, flags_json),
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
            'T2 del edge test resolution row.',
            '{"asset": "BTC", "day": "2025-07-14", "close_usd": 80140.0, "source": "test"}',
            'v1.1', NULL
        ) RETURNING id
        """,
        (claim_id,),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _get_flags(db_conn: Any, claim_id: int) -> dict[str, Any]:
    """Fetch the flags dict for a single claim row."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT flags FROM claims WHERE id = %s", (claim_id,))
        row = cur.fetchone()
    assert row is not None
    return row[0] if isinstance(row[0], dict) else json.loads(row[0])


# ---------------------------------------------------------------------------
# Gap 1: Resolution persistence after a PRIVATE sweep (EC-1, NFR-3)
# Existing tests only verify resolution persistence for the DELETED path.
# ---------------------------------------------------------------------------


class TestResolutionPersistenceAfterPrivateEC1:
    """EC-1/NFR-3: resolution rows survive a PRIVATE deletion sweep unchanged."""

    def test_resolution_exists_and_unchanged_after_private_sweep(self, db_conn: Any) -> None:
        """Resolution row is intact after the sweep flags a PRIVATE video."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "prv-res-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}prv-res-a")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            resolution_id = _seed_resolution(cur, claim_id)

        # Capture state before sweep.
        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, rule_id, rationale FROM resolutions WHERE id = %s",
                (resolution_id,),
            )
            before = cur.fetchone()
        assert before is not None

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}prv-res-a",
            return_status=SourceStatus.PRIVATE,
        )
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT outcome, rule_id, rationale FROM resolutions WHERE id = %s",
                (resolution_id,),
            )
            after = cur.fetchone()

        assert after is not None, "Resolution row must still exist after PRIVATE sweep (EC-1/NFR-3)"
        assert after == before, "Resolution row must not be modified by the PRIVATE sweep (NFR-3)"

    def test_resolution_row_count_unchanged_after_private_sweep(self, db_conn: Any) -> None:
        """No resolution rows are inserted or removed by a PRIVATE sweep (NFR-3)."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "prv-cnt-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}prv-cnt-a")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)
            _seed_resolution(cur, claim_id)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM resolutions")
            count_before = int(cur.fetchone()[0])

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}prv-cnt-a",
            return_status=SourceStatus.PRIVATE,
        )
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM resolutions")
            count_after = int(cur.fetchone()[0])

        assert count_after == count_before, (
            "PRIVATE sweep must not insert or delete any resolution rows (NFR-3)"
        )


# ---------------------------------------------------------------------------
# Gap 2: Multiple claims on the same video — all flagged and all persist.
# Existing tests only use a single claim per video.
# ---------------------------------------------------------------------------


class TestMultipleClaimsAllFlagged:
    """Every claim on a deleted video must be flagged; every claim must persist."""

    def test_two_claims_both_get_source_deleted_flag_after_deleted_sweep(
        self, db_conn: Any
    ) -> None:
        """Both claims on a video must have source_deleted=True after DELETED sweep."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "multi-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}multi-a")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id_a = _seed_claim(cur, analyst_id, video_id, transcript_id)
            claim_id_b = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}multi-a",
            return_status=SourceStatus.DELETED,
        )
        run_deletion_sweep(probe, db_conn)

        for cid, label in ((claim_id_a, "first"), (claim_id_b, "second")):
            flags = _get_flags(db_conn, cid)
            assert flags.get("source_deleted") is True, (
                f"{label} claim (id={cid}) must have source_deleted=True after DELETED sweep"
            )

    def test_two_claims_both_persist_after_deleted_sweep(self, db_conn: Any) -> None:
        """Both claim rows must still exist (not deleted) after the sweep (NFR-3)."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "multi-b")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}multi-b")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id_a = _seed_claim(cur, analyst_id, video_id, transcript_id)
            claim_id_b = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}multi-b",
            return_status=SourceStatus.DELETED,
        )
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM claims WHERE id = ANY(%s)",
                ([claim_id_a, claim_id_b],),
            )
            found_ids = {int(row[0]) for row in cur.fetchall()}

        assert claim_id_a in found_ids, "First claim row must persist after DELETED sweep (NFR-3)"
        assert claim_id_b in found_ids, "Second claim row must persist after DELETED sweep (NFR-3)"

    def test_two_claims_both_flagged_after_private_sweep(self, db_conn: Any) -> None:
        """Multiple claims on a PRIVATE video all receive the source_deleted flag."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "multi-c")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}multi-c")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id_a = _seed_claim(cur, analyst_id, video_id, transcript_id)
            claim_id_b = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}multi-c",
            return_status=SourceStatus.PRIVATE,
        )
        run_deletion_sweep(probe, db_conn)

        for cid in (claim_id_a, claim_id_b):
            flags = _get_flags(db_conn, cid)
            assert flags.get("source_deleted") is True, (
                f"Claim {cid} must have source_deleted=True after PRIVATE sweep"
            )


# ---------------------------------------------------------------------------
# Gap 3: Video with zero claims — sweep handles empty-claim set without error.
# ---------------------------------------------------------------------------


class TestDeletionNoClaimsVideo:
    """A deleted video with no claims must not cause errors in the sweep."""

    def test_no_claims_video_sweep_completes_and_status_updated(self, db_conn: Any) -> None:
        """Sweep a claimless video: source_status updated, no exception raised."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "noclaim-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}noclaim-a")
            # Deliberately no claim seeded for this video.

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}noclaim-a",
            return_status=SourceStatus.DELETED,
        )
        report = run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "deleted", (
            "Claimless video must still have source_status updated to 'deleted'"
        )
        assert report.newly_deleted >= 1, "Claimless deleted video must be counted in newly_deleted"

    def test_no_claims_video_claims_table_count_unchanged(self, db_conn: Any) -> None:
        """Claims table total is unchanged when the swept video has no claims."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "noclaim-b")
            _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}noclaim-b")

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM claims")
            count_before = int(cur.fetchone()[0])

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}noclaim-b",
            return_status=SourceStatus.DELETED,
        )
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM claims")
            count_after = int(cur.fetchone()[0])

        assert count_after == count_before, (
            "Claims table count must not change when the deleted video had no claims"
        )


# ---------------------------------------------------------------------------
# Gap 4: Pre-existing claim flags are merged, not overwritten.
# flag_source_deleted copies the flags dict and adds source_deleted=True.
# This test verifies that the DB write preserves pre-existing keys.
# ---------------------------------------------------------------------------


class TestDeletionFlagMerge:
    """Pre-existing claim flags must survive the source_deleted propagation."""

    def test_preexisting_flags_preserved_after_deleted_sweep(self, db_conn: Any) -> None:
        """Claim with existing flags: after DELETED sweep, old flags and
        source_deleted are both present."""
        pre_flags: dict[str, Any] = {
            "qa_note": "t2x-del-merge-check",
            "reviewed": True,
        }
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "merge-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}merge-a")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, flags=pre_flags)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}merge-a",
            return_status=SourceStatus.DELETED,
        )
        run_deletion_sweep(probe, db_conn)

        flags = _get_flags(db_conn, claim_id)
        assert flags.get("source_deleted") is True, "source_deleted must be set after DELETED sweep"
        assert flags.get("qa_note") == "t2x-del-merge-check", (
            "Pre-existing qa_note must not be overwritten by DELETED sweep"
        )
        assert flags.get("reviewed") is True, (
            "Pre-existing reviewed flag must not be overwritten by DELETED sweep"
        )

    def test_preexisting_flags_preserved_after_private_sweep(self, db_conn: Any) -> None:
        """Same flag-merge guarantee holds for the PRIVATE path."""
        pre_flags: dict[str, Any] = {"custom_key": "t2x-del-prv-merge"}
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "merge-b")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}merge-b")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id, flags=pre_flags)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}merge-b",
            return_status=SourceStatus.PRIVATE,
        )
        run_deletion_sweep(probe, db_conn)

        flags = _get_flags(db_conn, claim_id)
        assert flags.get("source_deleted") is True
        assert flags.get("custom_key") == "t2x-del-prv-merge", (
            "Pre-existing custom_key must survive the PRIVATE sweep flag merge"
        )


# ---------------------------------------------------------------------------
# Gap 5: Idempotency for PRIVATE sweep.
# The existing test_sweep_is_idempotent_on_rerun only covers the DELETED path.
# ---------------------------------------------------------------------------


class TestDeletionIdempotencyPrivate:
    """Re-running the sweep on an already-private video must be a true no-op."""

    def test_private_sweep_idempotent_second_run_skips_already_private_video(
        self, db_conn: Any
    ) -> None:
        """Second PRIVATE sweep does not re-process the already-private video."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "idem-prv-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}idem-prv-a")
            transcript_id = _seed_transcript(cur, video_id)
            claim_id = _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}idem-prv-a",
            return_status=SourceStatus.PRIVATE,
        )

        first = run_deletion_sweep(probe, db_conn)
        assert first.newly_private >= 1, "First run must flag the video as newly private"

        # The video is now PRIVATE; the sweep query uses WHERE source_status='live'
        # so it must be excluded from the second run.
        second = run_deletion_sweep(probe, db_conn)
        assert second.checked == first.checked - 1, (
            "Second run must check one fewer video: the already-private one is excluded"
        )
        assert second.newly_private == 0, "Second run must not re-flag the already-private video"

        # Persistent state must still be correct after the second run.
        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            v_row = cur.fetchone()
        assert v_row is not None and v_row[0] == "private"

        flags = _get_flags(db_conn, claim_id)
        assert flags.get("source_deleted") is True, (
            "source_deleted flag must remain set after the second PRIVATE sweep"
        )


# ---------------------------------------------------------------------------
# Gap 6: No alerts dispatched during the deletion sweep.
# deletion.py does NOT integrate with the alerts table or the Alerter seam.
# These tests document current behavior so a future regression is caught.
# ---------------------------------------------------------------------------


class TestDeletionNoAlertDispatch:
    """Deletion sweep must not insert rows into the alerts table."""

    def test_alerts_table_not_written_during_deleted_sweep(self, db_conn: Any) -> None:
        """DELETED sweep: alerts table row count is unchanged (no alert raised)."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "noalert-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}noalert-a")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM alerts")
            alerts_before = int(cur.fetchone()[0])

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}noalert-a",
            return_status=SourceStatus.DELETED,
        )
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM alerts")
            alerts_after = int(cur.fetchone()[0])

        assert alerts_after == alerts_before, (
            "DELETED sweep must not insert any rows into the alerts table"
            " (deletion.py has no alerter seam in the current implementation)"
        )

    def test_alerts_table_not_written_during_private_sweep(self, db_conn: Any) -> None:
        """PRIVATE sweep: alerts table row count is unchanged (no alert raised)."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "noalert-b")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}noalert-b")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM alerts")
            alerts_before = int(cur.fetchone()[0])

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}noalert-b",
            return_status=SourceStatus.PRIVATE,
        )
        run_deletion_sweep(probe, db_conn)

        with db_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM alerts")
            alerts_after = int(cur.fetchone()[0])

        assert alerts_after == alerts_before, (
            "PRIVATE sweep must not insert any rows into the alerts table"
        )


# ---------------------------------------------------------------------------
# Gap 7: DeletionReport invariant and clean no-op assertions.
# Existing tests do not assert: (a) the sum identity checked == newly_deleted +
# newly_private + unchanged, or (b) that newly_deleted == 0 AND newly_private
# == 0 when the probe returns LIVE for every video.
# ---------------------------------------------------------------------------


class TestDeletionReportInvariants:
    """DeletionReport fields must satisfy structural invariants."""

    def test_checked_equals_sum_of_outcome_buckets_after_deleted_sweep(self, db_conn: Any) -> None:
        """checked == newly_deleted + newly_private + unchanged must hold."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "sum-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}sum-a")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}sum-a",
            return_status=SourceStatus.DELETED,
        )
        report = run_deletion_sweep(probe, db_conn)

        assert isinstance(report, DeletionReport)
        total = report.newly_deleted + report.newly_private + report.unchanged
        assert total == report.checked, (
            f"Sum invariant failed: {report.newly_deleted} + {report.newly_private}"
            f" + {report.unchanged} = {total} != checked={report.checked}"
        )

    def test_checked_equals_sum_of_outcome_buckets_after_private_sweep(self, db_conn: Any) -> None:
        """Sum invariant holds for a PRIVATE sweep as well."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "sum-b")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}sum-b")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        probe = _FakeProbeT2(
            target_video_id=f"{_VIDEO_PREFIX}sum-b",
            return_status=SourceStatus.PRIVATE,
        )
        report = run_deletion_sweep(probe, db_conn)

        total = report.newly_deleted + report.newly_private + report.unchanged
        assert total == report.checked, (
            f"Sum invariant failed for PRIVATE path: {total} != {report.checked}"
        )

    def test_noop_sweep_newly_deleted_and_newly_private_are_zero(self, db_conn: Any) -> None:
        """When the probe returns LIVE for every video, newly_deleted == 0
        AND newly_private == 0 (the existing test only asserts unchanged >= 1)."""
        with db_conn.cursor() as cur:
            analyst_id = _seed_analyst(cur, "noop-a")
            video_id = _seed_video(cur, analyst_id, yt_id=f"{_VIDEO_PREFIX}noop-a")
            transcript_id = _seed_transcript(cur, video_id)
            _seed_claim(cur, analyst_id, video_id, transcript_id)

        # _AllLiveProbe returns LIVE for every video — nothing should be flagged.
        probe = _AllLiveProbe()
        report = run_deletion_sweep(probe, db_conn)

        assert report.newly_deleted == 0, (
            "No-op sweep must have newly_deleted == 0 when all videos stay live"
        )
        assert report.newly_private == 0, (
            "No-op sweep must have newly_private == 0 when all videos stay live"
        )
        assert report.unchanged >= 1, (
            "No-op sweep must have unchanged >= 1 (our seeded video is live)"
        )

        # Verify our seeded video's status was not touched.
        with db_conn.cursor() as cur:
            cur.execute("SELECT source_status FROM videos WHERE id = %s", (video_id,))
            row = cur.fetchone()
        assert row is not None and row[0] == "live", (
            "No-op sweep must not change source_status of a live video"
        )
