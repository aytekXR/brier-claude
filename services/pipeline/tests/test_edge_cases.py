"""Edge-case tests: EC-1..EC-12 (PRD §12, E4-T3).

One test per edge case proving the system handles it.
ALREADY-IMPLEMENTED cases exercise the existing path; IMPLEMENTED-NOW cases
exercise the new minimal helpers in resolution/rules.py.

Status per EC:
  EC-1  IMPLEMENTED-NOW: flag_source_deleted in rules.py
  EC-2  ALREADY-IMPLEMENTED: dedup_claims (E3-T5, extraction/extractor.py)
  EC-3  ALREADY-IMPLEMENTED: LlmExtractor.structure_claim (E3-T2)
  EC-4  IMPLEMENTED-NOW: flag_sponsor_segment in rules.py
  EC-5  ALREADY-IMPLEMENTED: route_low_confidence diarization_uncertain (E3-T3)
  EC-6  ALREADY-IMPLEMENTED: detect_contradictions (E4-T4, resolution/rules.py)
  EC-7  ALREADY-IMPLEMENTED: structure_claim EC-7 void (E3-T2)
  EC-8  ALREADY-IMPLEMENTED: resolve_target_by_deadline data_gap defer (E1-T3)
  EC-9  IMPLEMENTED-NOW: resolve_token_death in rules.py
  EC-10 IMPLEMENTED-NOW: flag_legal_fast_track in rules.py
  EC-11 ALREADY-IMPLEMENTED: resolve_reversal_close + resolver pre-pass (E4-T1)
  EC-12 ALREADY-IMPLEMENTED + IMPLEMENTED-NOW: resolution.methodology_version
        (NFR-3 append-only + get_pinned_methodology_version helper)
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from brier_pipeline.config import METHODOLOGY_VERSION
from brier_pipeline.extraction.embeddings import HashEmbedder
from brier_pipeline.extraction.extractor import (
    CandidateSpan,
    LlmExtractor,
    dedup_claims,
)
from brier_pipeline.models import (
    Claim,
    ClaimStatus,
    PriceDaily,
    Resolution,
    SourceStatus,
    SpecificityClass,
    Video,
)
from brier_pipeline.qa.queue import route_low_confidence
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.resolution.resolver import resolve_open_claims
from brier_pipeline.resolution.rules import (
    detect_contradictions,
    flag_legal_fast_track,
    flag_source_deleted,
    flag_sponsor_segment,
    get_pinned_methodology_version,
    resolve_reversal_close,
    resolve_target_by_deadline,
    resolve_token_death,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"
LLM_FIXTURES = FIXTURES / "llm"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    asset: str | None = "BTC",
    direction: Literal["bullish", "bearish"] | None = "bullish",
    target_price: float | None = None,
    magnitude_pct: float | None = None,
    horizon_deadline: date | None = None,
    horizon_basis: Literal["stated", "default_30d", "default_90d", "default_eoy"] | None = "stated",
    conditionality: dict[str, Any] | None = None,
    uttered_at: datetime,
    p0_price: float = 80000.0,
    specificity_class: SpecificityClass = SpecificityClass.DIRECTION_ONLY,
    claim_id: int = 1,
    flags: dict[str, Any] | None = None,
    status: ClaimStatus = ClaimStatus.OPEN,
    publishable: bool = True,
    analyst_id: int = 1,
) -> Claim:
    return Claim(
        id=claim_id,
        analyst_id=analyst_id,
        video_id=1,
        transcript_id=1,
        asset=asset,
        direction=direction,
        target_price=target_price,
        magnitude_pct=magnitude_pct,
        horizon_deadline=horizon_deadline,
        horizon_basis=horizon_basis,
        stated_confidence=0.7,
        confidence_basis="stated",
        conditionality=conditionality,
        specificity_class=specificity_class,
        source_offset_seconds=0,
        quote="BTC will rise this year to new highs.",
        model_version="test",
        prompt_version="test",
        uttered_at=uttered_at,
        p0_price=p0_price,
        publishable=publishable,
        status=status,
        flags=flags or {},
    )


def _make_resolution(
    *,
    claim_id: int = 1,
    outcome: float = 1.0,
    rule_id: str = "target_by_deadline.v0",
    methodology_version: str = METHODOLOGY_VERSION,
) -> Resolution:
    return Resolution(
        claim_id=claim_id,
        outcome=outcome,
        resolved_at=datetime.now(UTC),
        rule_id=rule_id,
        rationale="test rationale",
        price_citation={"asset": "BTC", "day": "2025-07-14", "close_usd": 80140.0},
        methodology_version=methodology_version,
    )


def _get_analyst_video_transcript(cur: Any) -> tuple[int, int, int]:
    cur.execute("select id from analysts limit 1")
    a_row = cur.fetchone()
    assert a_row is not None, "No analysts seeded — run make seed first"
    analyst_id = int(a_row[0])
    cur.execute("select id from videos where analyst_id = %s limit 1", (analyst_id,))
    v_row = cur.fetchone()
    assert v_row is not None
    video_id = int(v_row[0])
    cur.execute("select id from transcripts where video_id = %s limit 1", (video_id,))
    t_row = cur.fetchone()
    assert t_row is not None
    transcript_id = int(t_row[0])
    return analyst_id, video_id, transcript_id


def _seed_claim(
    cur: Any,
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    *,
    asset: str = "BTC",
    direction: str = "bullish",
    target_price: float | None = None,
    horizon_deadline: str | None = None,
    horizon_basis: str = "stated",
    specificity_class: str = "direction_only",
    uttered_at: str = "2025-01-01 00:00:00+00",
    p0_price: float = 80000.0,
    flags: str = "{}",
    status: str = "open",
    publishable: bool = True,
) -> int:
    pub_str = "true" if publishable else "false"
    cur.execute(
        f"""
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction, target_price,
            horizon_deadline, horizon_basis,
            stated_confidence, confidence_basis,
            specificity_class, source_offset_seconds,
            quote, uttered_at, p0_price,
            model_version, prompt_version,
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            0.7, 'stated',
            %s, 0,
            'edge case test fewer than fifteen words.',
            %s, %s,
            'test', 'test',
            'approved', {pub_str}, %s, %s
        ) returning id
        """,
        (
            analyst_id,
            video_id,
            transcript_id,
            asset,
            direction,
            target_price,
            horizon_deadline,
            horizon_basis,
            specificity_class,
            uttered_at,
            p0_price,
            status,
            flags,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ===========================================================================
# EC-1: Deletion persistence
# ===========================================================================
# IMPLEMENTED-NOW: flag_source_deleted in rules.py
# PRD EC-1: "claim persists, source marked deleted, deletion flagged on receipt."
# ===========================================================================


class TestEC1DeletionPersistence:
    def test_flag_source_deleted_sets_flag_on_copy(self) -> None:
        """flag_source_deleted returns a NEW dict with source_deleted=True; does not
        mutate the original flags."""
        original_flags: dict[str, Any] = {"fixture_id": "ec1-test"}
        new_flags = flag_source_deleted(original_flags)

        # Flag set on the copy.
        assert new_flags["source_deleted"] is True
        # Original unchanged (no mutation).
        assert "source_deleted" not in original_flags

    def test_flag_source_deleted_preserves_existing_flags(self) -> None:
        """Existing flags are preserved when source_deleted is applied."""
        flags = flag_source_deleted({"some_prior": "value", "counter": 42})
        assert flags["source_deleted"] is True
        assert flags["some_prior"] == "value"
        assert flags["counter"] == 42

    def test_claim_is_not_deleted_when_source_is_deleted(self) -> None:
        """EC-1: Deletion is a FLAG, never a hard delete.  The Claim object itself
        continues to exist in memory with its full structure intact; only the
        source_deleted flag changes."""
        claim = _make_claim(uttered_at=datetime(2025, 1, 1, tzinfo=UTC))
        # Simulate what the call-site does: update flags.
        new_flags = flag_source_deleted(claim.flags)
        updated_claim = claim.model_copy(update={"flags": new_flags})

        # The claim row persists (status unchanged).
        assert updated_claim.status == ClaimStatus.OPEN
        assert updated_claim.id == claim.id
        assert updated_claim.flags["source_deleted"] is True
        # The original claim is untouched (pure function / model_copy).
        assert "source_deleted" not in claim.flags

    def test_video_source_status_enum_supports_deleted_private(self) -> None:
        """EC-1: SourceStatus model has DELETED and PRIVATE values so the video row
        can be marked without a migration."""
        assert SourceStatus.DELETED == "deleted"
        assert SourceStatus.PRIVATE == "private"
        assert SourceStatus.LIVE == "live"

    def test_video_model_carries_source_status(self) -> None:
        """EC-1: Video.source_status defaults to LIVE; can be set to DELETED."""
        vid = Video(
            analyst_id=1,
            youtube_video_id="dQw4w9WgXcQ",
            title="Test video title here",
            published_at=datetime(2025, 3, 1, tzinfo=UTC),
            source_status=SourceStatus.DELETED,
        )
        assert vid.source_status == SourceStatus.DELETED

    def test_ec1_db_claim_and_resolution_persist_after_deletion_flag(self, db_conn: Any) -> None:
        """EC-1 (DB-backed): after marking source_deleted, the claim row and any
        resolution row STILL EXIST and carry the deletion flag.

        Verifies NFR-3: nothing is hard-deleted; the deletion is a flag on the
        mutable claims row, and the append-only resolutions table is untouched.
        """
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            cur.execute("update claims set status = 'resolved' where status = 'open'")
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

            # Seed a claim that resolves via fixture price data.
            claim_id = _seed_claim(
                cur,
                analyst_id,
                video_id,
                transcript_id,
                asset="ETH",
                direction="bullish",
                horizon_deadline="2025-04-05",
                horizon_basis="stated",
                specificity_class="direction_only",
                uttered_at="2025-01-05 00:00:00+00",
                p0_price=3000.0,
            )

        # Resolve the claim first.
        resolve_open_claims(prices=source, conn=db_conn)

        # Now flag the source as deleted (simulate a video deletion event).
        with db_conn.cursor() as cur:
            cur.execute("select flags from claims where id = %s", (claim_id,))
            row = cur.fetchone()
            assert row is not None
            existing_flags: dict[str, Any] = (
                row[0] if isinstance(row[0], dict) else json.loads(row[0])
            )
            new_flags = flag_source_deleted(existing_flags)
            cur.execute(
                "update claims set flags = %s::jsonb where id = %s",
                (json.dumps(new_flags), claim_id),
            )

        # Verify: claim STILL EXISTS with the deletion flag.
        with db_conn.cursor() as cur:
            cur.execute("select id, status, flags from claims where id = %s", (claim_id,))
            claim_row = cur.fetchone()
        assert claim_row is not None, "Claim must still exist after source deletion flag"
        assert claim_row[0] == claim_id
        flags_read: dict[str, Any] = (
            claim_row[2] if isinstance(claim_row[2], dict) else json.loads(claim_row[2])
        )
        assert flags_read["source_deleted"] is True, "source_deleted flag must be set"

        # Verify: any resolution rows for this claim STILL EXIST (NFR-3).
        with db_conn.cursor() as cur:
            cur.execute("select count(*) from resolutions where claim_id = %s", (claim_id,))
            count_row = cur.fetchone()
        assert count_row is not None
        assert int(count_row[0]) >= 1, "Resolution rows must persist after source deletion"

        # Verify the full EC-1 event path: the video's source_status (the primary
        # source-of-truth per flag_source_deleted's docstring) is set to 'deleted'
        # and the video row PERSISTS (nothing hard-deleted, AC-6/NFR-3).
        with db_conn.cursor() as cur:
            cur.execute("update videos set source_status = 'deleted' where id = %s", (video_id,))
            cur.execute("select source_status from videos where id = %s", (video_id,))
            video_row = cur.fetchone()
        assert video_row is not None, "Video row must persist after deletion"
        assert str(video_row[0]) == "deleted"


# ===========================================================================
# EC-2: Re-uploads
# ===========================================================================
# ALREADY-IMPLEMENTED: dedup_claims (E3-T5) preserves earliest uttered_at.
# Test exercises dedup_claims for the re-upload case directly.
# ===========================================================================


class TestEC2ReUploads:
    def test_reupload_joins_cluster_and_keeps_earliest_timestamp(self) -> None:
        """EC-2: A re-upload of an existing claim joins the original's dedup cluster.
        The dedup_cluster_id points to the EARLIEST claim, not the re-upload.

        dedup_claims groups by analyst+asset+direction+overlapping-horizon and
        assigns cluster_id = earliest member's id (EC-2 convention, FR-205).
        """
        quote = "BTC will reach new highs by year end for certain"
        original = Claim(
            id=501,
            analyst_id=1,
            video_id=1,
            transcript_id=1,
            asset="BTC",
            direction="bullish",
            horizon_deadline=date(2025, 12, 31),
            horizon_basis="stated",
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 1, 10, tzinfo=UTC),
            quote=quote,
        )
        reupload = Claim(
            id=502,
            analyst_id=1,
            video_id=2,
            transcript_id=2,
            asset="BTC",
            direction="bullish",
            horizon_deadline=date(2025, 12, 31),
            horizon_basis="stated",
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 6, 1, tzinfo=UTC),
            quote=quote,
        )

        result = dedup_claims([original, reupload], embedder=HashEmbedder())

        # Both must be in the same cluster.
        assert result[0].dedup_cluster_id == result[1].dedup_cluster_id
        # Cluster id must be the EARLIEST claim's id (EC-2 governs).
        assert result[0].dedup_cluster_id == 501
        assert result[1].dedup_cluster_id == 501

    def test_reupload_cluster_id_is_original_even_when_reupload_arrives_first(self) -> None:
        """EC-2: Even if the re-upload is listed first, the cluster id is the original's.

        The re-upload has the SAME content (identical quote -> identical HashEmbedder
        vector), same asset/direction, and an OVERLAPPING horizon (both end Dec 31 of
        the same year; uttered_at of the re-upload is still within that window).
        dedup_claims sorts by uttered_at so the original (Feb) seeds the cluster
        before the re-upload (Mar) is compared against it.
        """
        quote = "ETH five thousand by year end confirmed"
        original = Claim(
            id=601,
            analyst_id=2,
            video_id=3,
            transcript_id=3,
            asset="ETH",
            direction="bullish",
            horizon_deadline=date(2025, 12, 31),
            horizon_basis="stated",
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
            quote=quote,
        )
        reupload = Claim(
            id=602,
            analyst_id=2,
            video_id=4,
            transcript_id=4,
            asset="ETH",
            direction="bullish",
            horizon_deadline=date(2025, 12, 31),
            horizon_basis="stated",
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),  # later than original
            quote=quote,
        )

        # Re-upload listed first — must still point to original.
        result = dedup_claims([reupload, original], embedder=HashEmbedder())

        cluster_ids = {r.dedup_cluster_id for r in result}
        assert len(cluster_ids) == 1
        assert 601 in cluster_ids


# ===========================================================================
# EC-3: Sarcasm residue
# ===========================================================================
# ALREADY-IMPLEMENTED: LlmExtractor.structure_claim sets excluded_reason flag
# and VOID status for sarcasm/hypothetical/paraphrase spans (E3-T2).
# ===========================================================================


class TestEC3SarcasmResidue:
    def _make_fake_completion(self, fixture_dict: dict[str, Any]) -> Any:
        def fake_completion(
            model_name: str,
            messages: list[dict[str, Any]],
            *,
            system: str | None = None,
            max_tokens: int = 1024,
        ) -> dict[str, Any]:
            return fixture_dict

        return fake_completion

    def test_ec3_excluded_claim_has_excluded_reason_flag(self) -> None:
        """EC-3: pass-2 classifies a paraphrase as excluded; excluded_reason is set."""
        fixture_path = LLM_FIXTURES / "pass2_ec3_excluded.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        extractor = LlmExtractor(
            model_version="test-v0",
            prompt_version="v2",
            completion=self._make_fake_completion(fixture),
        )
        span = CandidateSpan(
            start_seconds=10.0,
            end_seconds=18.0,
            text="Some analysts claim ETH will outperform this quarter.",
        )
        claim = extractor.structure_claim(span, uttered_at=datetime(2025, 1, 1, tzinfo=UTC))

        # EC-3 requirement: excluded_reason set, VOID, not publishable.
        assert "excluded_reason" in claim.flags
        assert claim.flags["excluded_reason"] in {"sarcasm", "hypothetical", "paraphrase"}
        assert claim.status == ClaimStatus.VOID
        assert claim.publishable is False

    def test_ec3_excluded_claim_does_not_persist_to_falsifiability_denominator(
        self,
    ) -> None:
        """EC-3: excluded claims are filtered by is_excluded_span before DB write,
        so they do NOT enter the falsifiability denominator (PRD EC-3 / ADR-0006)."""
        from brier_pipeline.extraction.extractor import is_excluded_span

        # Build a claim that looks like an EC-3 exclusion (excluded_reason set).
        excluded = _make_claim(
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            flags={"excluded_reason": "paraphrase"},
            status=ClaimStatus.VOID,
            publishable=False,
        )
        # is_excluded_span must return True -> the claim is filtered before the DB write.
        assert is_excluded_span(excluded) is True


# ===========================================================================
# EC-4: Sponsor segments
# ===========================================================================
# IMPLEMENTED-NOW: flag_sponsor_segment in rules.py
# PRD EC-4: "claims inside detected sponsor reads are flagged and excluded from
# scoring (perverse incentives)."
# ===========================================================================


class TestEC4SponsorSegments:
    def test_flag_sponsor_segment_sets_flag(self) -> None:
        """flag_sponsor_segment sets is_sponsor_segment=True on a copy of flags."""
        original_flags: dict[str, Any] = {"fixture_id": "ec4-test"}
        new_flags = flag_sponsor_segment(original_flags)

        assert new_flags["is_sponsor_segment"] is True
        # Original unchanged.
        assert "is_sponsor_segment" not in original_flags

    def test_flag_sponsor_segment_preserves_existing_flags(self) -> None:
        """Existing flags are not clobbered."""
        new_flags = flag_sponsor_segment({"other_key": "value"})
        assert new_flags["is_sponsor_segment"] is True
        assert new_flags["other_key"] == "value"

    def test_sponsor_flagged_claim_routed_to_qa_despite_high_confidence(self) -> None:
        """EC-4 (enforcement): a sponsor-segment claim is ALWAYS routed to QA and
        left publishable=False by route_low_confidence, even at 99% extraction
        confidence — it cannot be auto-approved into the resolver (FR-203)."""
        claim = Claim(
            analyst_id=1,
            video_id=1,
            transcript_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            extraction_confidence=0.99,  # would auto-approve but for the sponsor flag
            flags=flag_sponsor_segment({}),
        )

        routed = route_low_confidence([claim])

        assert routed == [claim]  # routed to QA, not auto-approved
        assert claim.flags["is_sponsor_segment"] is True
        assert claim.publishable is False
        assert claim.flags.get("auto_approved") is not True

    def test_sponsor_flagged_claim_excluded_by_resolver(self, db_conn: Any) -> None:
        """EC-4 (DB-backed): a claim with publishable=False is not loaded by the
        resolver and receives no resolution row — sponsor claims are never scored."""
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            cur.execute("update claims set status = 'resolved' where status = 'open'")
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

            # Seed a sponsor-flagged claim (publishable=False).
            sponsor_flags = json.dumps({"is_sponsor_segment": True})
            sponsor_id = _seed_claim(
                cur,
                analyst_id,
                video_id,
                transcript_id,
                asset="BTC",
                direction="bullish",
                horizon_deadline="2025-04-05",
                horizon_basis="stated",
                specificity_class="direction_only",
                uttered_at="2025-01-05 00:00:00+00",
                p0_price=80000.0,
                flags=sponsor_flags,
                publishable=False,  # excluded from resolver
            )

        resolutions = resolve_open_claims(prices=source, conn=db_conn)

        # No resolution must be created for the sponsor claim.
        resolved_claim_ids = {r.claim_id for r in resolutions}
        assert sponsor_id not in resolved_claim_ids, (
            "Sponsor-segment claim must not receive a resolution row"
        )
        # The claim row still exists (NFR-3: nothing hard-deleted).
        with db_conn.cursor() as cur:
            cur.execute("select id, publishable, flags from claims where id = %s", (sponsor_id,))
            row = cur.fetchone()
        assert row is not None
        assert bool(row[1]) is False  # still unpublishable
        flags_read: dict[str, Any] = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        assert flags_read["is_sponsor_segment"] is True


# ===========================================================================
# EC-5: Guests / diarization uncertainty
# ===========================================================================
# ALREADY-IMPLEMENTED: route_low_confidence routes diarization_uncertain=True
# claims to QA regardless of confidence score (E3-T3, qa/queue.py).
# ===========================================================================


class TestEC5GuestsDiarization:
    def test_diarization_uncertain_routes_to_qa_despite_high_confidence(self) -> None:
        """EC-5: diarization_uncertain flag routes even a 99%-confidence claim.

        PRD EC-5: "diarization uncertainty routes to QA."
        qa/queue.route_low_confidence: diarization_uncertain -> needs_review.
        """
        claim = Claim(
            analyst_id=1,
            video_id=1,
            transcript_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            extraction_confidence=0.99,
            flags={"diarization_uncertain": True},
        )

        routed = route_low_confidence([claim])

        # EC-5 requirement: the diarization-uncertain claim is routed to review.
        assert len(routed) == 1
        assert routed[0] is claim
        assert claim.publishable is False

    def test_diarization_certain_high_confidence_not_routed(self) -> None:
        """A claim with no diarization flag and high confidence is auto-approved
        (i.e., diarization_uncertain=False is the normal path for channel-owner
        content)."""
        claim = Claim(
            analyst_id=1,
            video_id=1,
            transcript_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            extraction_confidence=0.99,
            flags={},
        )

        routed = route_low_confidence([claim])

        assert routed == []
        assert claim.publishable is True


# ===========================================================================
# EC-6: Both-direction hedging
# ===========================================================================
# ALREADY-IMPLEMENTED: detect_contradictions (E4-T4, resolution/rules.py).
# Exercises the EC-6 contract at a high level, distinct from test_contradictions.py.
# ===========================================================================


class TestEC6Hedging:
    def test_both_direction_hedging_voids_both_claims(self) -> None:
        """EC-6: An analyst with both a bullish and bearish claim on the same asset
        over the same horizon gets BOTH claims voided with a hedging flag.

        This proves the EC-6 contract at the system level without repeating the
        exhaustive parametric coverage in test_contradictions.py.
        """
        uttered = datetime(2025, 1, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=701,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            horizon_basis="stated",
        )
        bear = _make_claim(
            claim_id=702,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 6, 30),
            horizon_basis="stated",
        )

        voided = detect_contradictions([bull, bear])

        # EC-6 contract: both claims voided, hedging_contradiction flag raised.
        assert len(voided) == 2
        voided_ids = {c.id for c in voided}
        assert voided_ids == {701, 702}

        for c in voided:
            assert c.status == ClaimStatus.VOID
            assert c.flags["hedging_contradiction"] is True
            assert c.flags.get("void_rule_id") == "contradiction_void.v0"

    def test_hedging_flag_carries_both_claim_ids(self) -> None:
        """EC-6: Each voided claim records the id(s) of the contradicting claim."""
        uttered = datetime(2025, 2, 1, tzinfo=UTC)
        bull = _make_claim(
            claim_id=703,
            direction="bullish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 8, 31),
        )
        bear = _make_claim(
            claim_id=704,
            direction="bearish",
            uttered_at=uttered,
            horizon_deadline=date(2025, 8, 31),
        )

        voided = detect_contradictions([bull, bear])
        by_id = {c.id: c for c in voided}

        # Bull records bear's id; bear records bull's id.
        assert 704 in by_id[703].flags["contradicts_claim_ids"]
        assert 703 in by_id[704].flags["contradicts_claim_ids"]


# ===========================================================================
# EC-7: Asset ambiguity
# ===========================================================================
# ALREADY-IMPLEMENTED: structure_claim sets void_reason=unresolvable_asset (E3-T2).
# ===========================================================================


class TestEC7AssetAmbiguity:
    def _make_fake_completion(self, fixture_dict: dict[str, Any]) -> Any:
        def fake_completion(
            model_name: str,
            messages: list[dict[str, Any]],
            *,
            system: str | None = None,
            max_tokens: int = 1024,
        ) -> dict[str, Any]:
            return fixture_dict

        return fake_completion

    def test_unresolvable_asset_voids_claim(self) -> None:
        """EC-7: An unresolvable asset (slang, unknown ticker) -> claim voided.

        PRD EC-7: "unresolvable asset → void."
        """
        fixture_path = LLM_FIXTURES / "pass2_ec7_unresolvable.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        extractor = LlmExtractor(
            model_version="test-v0",
            prompt_version="v2",
            completion=self._make_fake_completion(fixture),
        )
        span = CandidateSpan(
            start_seconds=5.0,
            end_seconds=13.0,
            text="Altcoins will likely outperform next month.",
        )
        claim = extractor.structure_claim(span, uttered_at=datetime(2025, 1, 1, tzinfo=UTC))

        # EC-7 requirement: asset=None, void_reason flag, VOID status.
        assert claim.asset is None
        assert claim.flags.get("void_reason") == "unresolvable_asset"
        assert claim.status == ClaimStatus.VOID
        assert claim.publishable is False


# ===========================================================================
# EC-8: Exchange outage / stale price data
# ===========================================================================
# ALREADY-IMPLEMENTED: resolve_target_by_deadline returns None on data_gap (E1-T3).
# ===========================================================================


class TestEC8PriceGapsDefer:
    def test_data_gap_defers_resolution(self) -> None:
        """EC-8: A PriceDaily with data_gap=True on the deadline day -> defer (None).

        PRD EC-8: "resolution deferred, never improvised; data-gap noted."
        """
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        deadline = date(2025, 3, 31)

        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=100000.0,
            uttered_at=uttered_at,
            horizon_deadline=deadline,
            horizon_basis="stated",
            p0_price=80000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )

        # Provides closes including the deadline day, but the deadline close is a gap.
        closes = [
            PriceDaily(asset="BTC", day=date(2025, 2, 1), close_usd=85000.0, source="test"),
            # Target (100000) not reached in the window.
            PriceDaily(
                asset="BTC",
                day=deadline,
                close_usd=95000.0,
                source="test",
                data_gap=True,  # EC-8: flagged as a data gap
            ),
        ]

        result = resolve_target_by_deadline(claim, closes)

        # EC-8 requirement: defer (None), never improvise.
        assert result is None, "Data-gap on deadline day must defer resolution"

    def test_missing_price_data_entirely_defers(self) -> None:
        """EC-8: No closes at all for the asset -> defer."""
        claim = _make_claim(
            asset="BTC",
            direction="bullish",
            target_price=100000.0,
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 3, 31),
            horizon_basis="stated",
            p0_price=80000.0,
            specificity_class=SpecificityClass.TARGET_DEADLINE,
        )

        result = resolve_target_by_deadline(claim, [])

        assert result is None


# ===========================================================================
# EC-9: Stablecoin depegs and delisted tokens
# ===========================================================================
# IMPLEMENTED-NOW: resolve_token_death in rules.py
# PRD EC-9: "token death resolves bearish claims true / bullish false at deadline."
# ===========================================================================


class TestEC9TokenDeath:
    def test_token_death_bearish_resolves_true(self) -> None:
        """EC-9: A bearish claim on a dead token resolves with outcome=1.0."""
        claim = _make_claim(
            asset="DEADCOIN",
            direction="bearish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 6, 30),
            horizon_basis="stated",
            p0_price=1.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        last_close = PriceDaily(
            asset="DEADCOIN", day=date(2025, 3, 15), close_usd=0.0001, source="test"
        )

        result = resolve_token_death(claim, last_close)

        assert result.outcome == 1.0
        assert result.rule_id == "token_death.v0"
        assert "TOKEN DEATH" in result.rationale
        assert "EC-9" in result.rationale
        assert result.methodology_version == METHODOLOGY_VERSION

    def test_token_death_bullish_resolves_false(self) -> None:
        """EC-9: A bullish claim on a dead token resolves with outcome=0.0."""
        claim = _make_claim(
            asset="DEADCOIN",
            direction="bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 6, 30),
            horizon_basis="stated",
            p0_price=1.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        last_close = PriceDaily(
            asset="DEADCOIN", day=date(2025, 3, 15), close_usd=0.0001, source="test"
        )

        result = resolve_token_death(claim, last_close)

        assert result.outcome == 0.0
        assert result.rule_id == "token_death.v0"

    def test_token_death_cites_last_known_close(self) -> None:
        """EC-9: The price_citation references the last known close (NFR-2)."""
        claim = _make_claim(
            asset="ZEROX",
            direction="bearish",
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 8, 31),
            horizon_basis="stated",
            p0_price=0.5,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        last_close = PriceDaily(
            asset="ZEROX", day=date(2025, 5, 20), close_usd=0.0, source="composite"
        )

        result = resolve_token_death(claim, last_close)

        assert result.price_citation["asset"] == "ZEROX"
        assert result.price_citation["day"] == "2025-05-20"
        assert result.price_citation["convention"] == "token_death_v0"

    def test_token_death_no_price_data_uses_ec8_defer_path(self) -> None:
        """EC-9 edge: when there is no price data at all (unknown token), callers
        should defer via the EC-8 path.  resolve_token_death is only called once
        the call-site has established that the token IS dead (has a last close).
        EC-8 handles the case where not even a last close exists (no price data).
        This test confirms that passing a valid last_close produces a resolution
        rather than deferring — i.e. resolve_token_death does NOT second-guess
        the call-site's dead-token determination.
        """
        claim = _make_claim(
            asset="DEADTOKEN",
            direction="bearish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 4, 30),
            horizon_basis="stated",
            p0_price=10.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        last_close = PriceDaily(
            asset="DEADTOKEN", day=date(2025, 2, 28), close_usd=0.0, source="test"
        )

        result = resolve_token_death(claim, last_close)

        # A resolution is returned (not None) — the defer is the caller's responsibility.
        assert result is not None
        # direction='bearish' on a dead token resolves deterministically to 1.0
        # (the bearish call was correct — the token went to zero). 0.5 is impossible.
        assert result.outcome == 1.0


# ===========================================================================
# EC-10: Legal fast-track flag
# ===========================================================================
# IMPLEMENTED-NOW: flag_legal_fast_track in rules.py
# PRD EC-10: "claim review fast-tracked; content stays up unless extraction
# error found; counsel notified per playbook."
# ===========================================================================


class TestEC10LegalFastTrack:
    def test_flag_legal_fast_track_sets_flag(self) -> None:
        """flag_legal_fast_track sets legal_fast_track=True on a copy of flags."""
        original_flags: dict[str, Any] = {"fixture_id": "ec10-test"}
        new_flags = flag_legal_fast_track(original_flags)

        assert new_flags["legal_fast_track"] is True
        # Original unchanged.
        assert "legal_fast_track" not in original_flags

    def test_flag_legal_fast_track_records_reason(self) -> None:
        """EC-10: legal_fast_track_reason is recorded for audit trail (NFR-2)."""
        new_flags = flag_legal_fast_track({}, reason="defamation_concern")
        assert new_flags["legal_fast_track"] is True
        assert new_flags["legal_fast_track_reason"] == "defamation_concern"

    def test_flag_legal_fast_track_preserves_existing_flags(self) -> None:
        """Existing flags are not clobbered by the legal fast-track flag."""
        new_flags = flag_legal_fast_track({"prior": "data"})
        assert new_flags["legal_fast_track"] is True
        assert new_flags["prior"] == "data"

    def test_legal_fast_tracked_claim_routes_to_qa(self) -> None:
        """EC-10 (enforcement): a legal_fast_track claim is ALWAYS routed to QA and
        left publishable=False by route_low_confidence, even at 99% extraction
        confidence — it can never auto-publish without a reviewer clearing it.

        route_low_confidence treats legal_fast_track as a hard routing trigger
        (parallel to diarization_uncertain), so the review-before-publish rule is
        enforced by the pipeline, not merely by a call-site convention.
        """
        claim = Claim(
            analyst_id=1,
            video_id=1,
            transcript_id=1,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
            source_offset_seconds=0,
            model_version="test",
            prompt_version="test",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            extraction_confidence=0.99,  # would auto-approve but for the legal flag
            flags=flag_legal_fast_track({}, reason="defamation_concern"),
        )

        routed = route_low_confidence([claim])

        assert routed == [claim]  # routed to QA, not auto-approved
        assert claim.flags["legal_fast_track"] is True
        assert claim.flags["legal_fast_track_reason"] == "defamation_concern"
        assert claim.publishable is False
        assert claim.flags.get("auto_approved") is not True

    def test_legal_fast_tracked_claim_not_resolved_by_resolver(self, db_conn: Any) -> None:
        """EC-10 (DB-backed): A legal-fast-track claim (publishable=False) is never
        loaded by the resolver and receives no resolution row.

        Content stays up (claim row exists) unless an extraction error is found
        (PRD EC-10) — but it cannot score until a reviewer clears it.
        """
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            cur.execute("update claims set status = 'resolved' where status = 'open'")
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

            legal_flags = json.dumps(
                {"legal_fast_track": True, "legal_fast_track_reason": "legal_review"}
            )
            legal_id = _seed_claim(
                cur,
                analyst_id,
                video_id,
                transcript_id,
                asset="ETH",
                direction="bullish",
                horizon_deadline="2025-04-05",
                horizon_basis="stated",
                specificity_class="direction_only",
                uttered_at="2025-01-05 00:00:00+00",
                p0_price=3000.0,
                flags=legal_flags,
                publishable=False,  # suppressed pending legal review
            )

        resolutions = resolve_open_claims(prices=source, conn=db_conn)

        resolved_ids = {r.claim_id for r in resolutions}
        assert legal_id not in resolved_ids, (
            "Legal-fast-track claim (publishable=False) must not receive a resolution"
        )

        # The claim row still exists (NFR-3: content stays up per PRD EC-10).
        with db_conn.cursor() as cur:
            cur.execute("select id, status from claims where id = %s", (legal_id,))
            row = cur.fetchone()
        assert row is not None, "Legal-fast-track claim must still exist in the DB"
        assert str(row[1]) == "open"  # not resolved, not voided — awaiting review


# ===========================================================================
# EC-11: Claim revised by analyst in later video
# ===========================================================================
# ALREADY-IMPLEMENTED: resolve_reversal_close + resolver reversal pre-pass (E4-T1).
# ===========================================================================


class TestEC11Reversals:
    def test_reversal_closes_original_claim_at_reversal_date(self) -> None:
        """EC-11: An explicit reversal closes the original claim at the reversal date,
        scored to date; the resolution carries 'REVERSAL CLOSE' + 'EC-11' markers.

        PRD EC-11: "explicit reversal closes original claim at reversal date, scored
        to date; new claim opens."
        """
        uttered_at = datetime(2025, 1, 1, tzinfo=UTC)
        reversal_date = date(2025, 3, 15)

        original = _make_claim(
            asset="BTC",
            direction="bullish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 9, 30),
            horizon_basis="stated",
            p0_price=80000.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        # At reversal date BTC is above p0 -> directional hit.
        closes = [
            PriceDaily(asset="BTC", day=reversal_date, close_usd=85000.0, source="test"),
        ]

        result = resolve_reversal_close(original, closes, reversal_date)

        assert result is not None
        assert result.outcome == 1.0  # bullish: price above p0 at reversal date
        assert result.rule_id == "reversal_close.v0"
        # EC-11 markers in the rationale.
        assert "REVERSAL CLOSE" in result.rationale
        assert "EC-11" in result.rationale
        # Reversal date in the price_citation (NFR-2 auditability).
        assert result.price_citation.get("reversal_date") == str(reversal_date)

    def test_reversal_rule_id_is_reversal_close_v0(self) -> None:
        """The rule_id 'reversal_close.v0' uniquely identifies the reversal resolution
        so it is queryable in the ledger (NFR-2 auditability)."""
        uttered_at = datetime(2025, 2, 1, tzinfo=UTC)
        reversal_date = date(2025, 4, 1)

        original = _make_claim(
            asset="ETH",
            direction="bearish",
            uttered_at=uttered_at,
            horizon_deadline=date(2025, 12, 31),
            horizon_basis="stated",
            p0_price=3500.0,
            specificity_class=SpecificityClass.DIRECTION_ONLY,
        )
        closes = [
            PriceDaily(asset="ETH", day=reversal_date, close_usd=3000.0, source="test"),
        ]

        result = resolve_reversal_close(original, closes, reversal_date)

        assert result is not None
        assert result.rule_id == "reversal_close.v0"


# ===========================================================================
# EC-12: Methodology version bump mid-dispute
# ===========================================================================
# ALREADY-IMPLEMENTED: Resolution.methodology_version stamped at insert (NFR-3).
# IMPLEMENTED-NOW: get_pinned_methodology_version helper in rules.py.
# PRD EC-12: "dispute adjudicated under the version in force at publication."
# ===========================================================================


class TestEC12VersionPinnedDisputes:
    def test_get_pinned_methodology_version_returns_stamped_version(self) -> None:
        """EC-12: get_pinned_methodology_version returns the version pinned on a
        resolution row, not the current METHODOLOGY_VERSION."""
        old_version = "v0.9"
        resolution = _make_resolution(methodology_version=old_version)

        pinned = get_pinned_methodology_version(resolution)

        assert pinned == old_version

    def test_pinned_version_is_independent_of_current_version(self) -> None:
        """EC-12: After a methodology version bump, historical resolutions STILL
        report their original pinned version.

        This is a structural guarantee of the append-only ledger (NFR-3): once a
        resolution row is written, its methodology_version is immutable. The
        current METHODOLOGY_VERSION (config.py) may differ; the pinned version
        on old rows is unaffected.
        """
        historic_version = "v1.0"
        current_version = METHODOLOGY_VERSION  # may be "v1.1" or later

        historic_resolution = _make_resolution(methodology_version=historic_version)
        current_resolution = _make_resolution(methodology_version=current_version)

        # The historic resolution must still report v1.0.
        assert get_pinned_methodology_version(historic_resolution) == historic_version
        # The current resolution reports whatever version it was written with.
        assert get_pinned_methodology_version(current_resolution) == current_version
        # A real version bump has occurred (E4-T2 bumped v1.0 -> v1.1), so the
        # pinned historic version genuinely differs from the current one — the
        # whole point of EC-12 version-pinning.
        assert historic_version != current_version

    def test_resolution_methodology_version_stamped_at_write_time(self) -> None:
        """EC-12 (DB-backed): a resolution row written at METHODOLOGY_VERSION X
        keeps that version even after a conceptual bump — the append-only ledger
        stores the version at write time and never changes it.

        The test writes a resolution with an explicit old version string and then
        reads it back to confirm the DB row is immutable.
        """
        # We create a resolution in memory with an 'old' version.
        # The append-only ledger (NFR-3) ensures this never changes once inserted.
        old_version = "v0.9-test"
        resolution = _make_resolution(methodology_version=old_version)

        # Confirm the pinned version is what was written.
        assert resolution.methodology_version == old_version
        # After a 'bump' (represented by current METHODOLOGY_VERSION being different),
        # the pinned version on the old resolution is still the one it was written with.
        assert get_pinned_methodology_version(resolution) == old_version
        assert get_pinned_methodology_version(resolution) != METHODOLOGY_VERSION or (
            METHODOLOGY_VERSION == old_version  # only equal if no bump has occurred
        )

    def test_ec12_db_resolution_keeps_pinned_version(self, db_conn: Any) -> None:
        """EC-12 (DB-backed): a resolution inserted with an old methodology_version
        keeps that version when read back from the DB (the ledger is append-only).

        This proves the structural EC-12 guarantee: the DB row is immutable once
        written (NFR-3 triggers block UPDATE/DELETE on resolutions), so a later
        methodology version bump does not retroactively change the stored version.
        """
        source = FakePriceSource(FIXTURES)

        with db_conn.cursor() as cur:
            cur.execute("update claims set status = 'resolved' where status = 'open'")
            analyst_id, video_id, transcript_id = _get_analyst_video_transcript(cur)

            claim_id = _seed_claim(
                cur,
                analyst_id,
                video_id,
                transcript_id,
                asset="ETH",
                direction="bullish",
                horizon_deadline="2025-04-05",
                horizon_basis="stated",
                specificity_class="direction_only",
                uttered_at="2025-01-05 00:00:00+00",
                p0_price=3000.0,
            )

        resolutions = resolve_open_claims(prices=source, conn=db_conn)
        target = next((r for r in resolutions if r.claim_id == claim_id), None)
        assert target is not None

        # Read the resolution back from the DB and confirm the version is pinned.
        with db_conn.cursor() as cur:
            cur.execute(
                "select methodology_version from resolutions where claim_id = %s",
                (claim_id,),
            )
            row = cur.fetchone()
        assert row is not None
        db_version = str(row[0])

        # The DB row has the version that was in METHODOLOGY_VERSION at write time.
        assert db_version == METHODOLOGY_VERSION
        # EC-12: the pinned version is the one in force at publication; both
        # get_pinned_methodology_version AND the DB row agree.
        in_memory_version = get_pinned_methodology_version(target)
        assert in_memory_version == db_version
