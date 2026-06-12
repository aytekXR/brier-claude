"""E1-T1 contract tests for the five fakes and fixture integrity.

Tests are organized into:
  - LocalFSStorage: round-trip, delete, path sanitization
  - FakePriceSource: 18+ months of data, HP-2 BTC close, filtering
  - FakeYouTubeClient: list uploads, captions present/absent
  - FakeTranscriber: replays fixture segments
  - FakeExtractor: detect_candidates + structure_claim end-to-end
  - Fixture integrity: p0_price, quote lengths, quote-in-transcript, base_rate range

DB-dependent demo tests use the db_conn fixture and skip when DB is down.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from brier_pipeline.extraction.extractor import FakeExtractor
from brier_pipeline.ingestion.youtube import FakeYouTubeClient
from brier_pipeline.models import SpecificityClass
from brier_pipeline.resolution.prices import FakePriceSource
from brier_pipeline.transcription.storage import LocalFSStorage
from brier_pipeline.transcription.transcriber import FakeTranscriber

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"


# ---------------------------------------------------------------------------
# LocalFSStorage
# ---------------------------------------------------------------------------


def test_localfs_put_get_round_trip(tmp_path: Path) -> None:
    storage = LocalFSStorage(tmp_path)
    body = b"hello fixture"
    key = storage.put("a/b/c.json", body)
    assert key == "a/b/c.json"
    assert storage.get("a/b/c.json") == body


def test_localfs_put_creates_parents(tmp_path: Path) -> None:
    storage = LocalFSStorage(tmp_path)
    storage.put("deep/nested/path/data.bin", b"\x00\x01")
    assert (tmp_path / "deep" / "nested" / "path" / "data.bin").exists()


def test_localfs_delete_removes_file(tmp_path: Path) -> None:
    storage = LocalFSStorage(tmp_path)
    storage.put("to_delete.txt", b"x")
    storage.delete("to_delete.txt")
    assert not (tmp_path / "to_delete.txt").exists()


def test_localfs_delete_missing_is_noop(tmp_path: Path) -> None:
    storage = LocalFSStorage(tmp_path)
    storage.delete("does_not_exist.txt")  # must not raise


def test_localfs_rejects_path_traversal(tmp_path: Path) -> None:
    storage = LocalFSStorage(tmp_path)
    with pytest.raises(ValueError, match="Unsafe"):
        storage.put("../../etc/passwd", b"evil")


def test_localfs_get_missing_raises(tmp_path: Path) -> None:
    storage = LocalFSStorage(tmp_path)
    with pytest.raises(FileNotFoundError):
        storage.get("nonexistent.json")


# ---------------------------------------------------------------------------
# FakePriceSource
# ---------------------------------------------------------------------------


def test_fake_price_source_btc_18_months() -> None:
    source = FakePriceSource(FIXTURES)
    start = date(2024, 12, 1)
    end = date(2026, 6, 11)
    closes = source.daily_closes("BTC", start, end)
    assert len(closes) >= 18 * 30  # at least 18 months of data


def test_fake_price_source_all_days_present_btc() -> None:
    """No gaps in BTC fixture data."""
    source = FakePriceSource(FIXTURES)
    start = date(2024, 12, 1)
    end = date(2026, 6, 11)
    closes = source.daily_closes("BTC", start, end)
    days_in_range = (end - start).days + 1
    assert len(closes) == days_in_range, f"Expected {days_in_range} rows, got {len(closes)}"


def test_fake_price_source_hp2_btc_close() -> None:
    """HP-2 canonical: BTC close on 2025-07-14 is exactly 80140."""
    source = FakePriceSource(FIXTURES)
    d = date(2025, 7, 14)
    closes = source.daily_closes("BTC", d, d)
    assert len(closes) == 1
    assert closes[0].close_usd == 80140.0, f"Expected 80140.0, got {closes[0].close_usd}"


def test_fake_price_source_btc_below_80k_constraint() -> None:
    """BTC must stay below 80000 from 2025-05-01 through 2025-07-13."""
    source = FakePriceSource(FIXTURES)
    start = date(2025, 5, 1)
    end = date(2025, 7, 13)
    closes = source.daily_closes("BTC", start, end)
    violations = [c for c in closes if c.close_usd >= 80000.0]
    violation_days = [str(v.day) for v in violations]
    assert violations == [], f"BTC sub-80k constraint violated on: {violation_days}"


def test_fake_price_source_eth_and_sol() -> None:
    source = FakePriceSource(FIXTURES)
    start = date(2024, 12, 1)
    end = date(2026, 6, 11)
    days_in_range = (end - start).days + 1
    for asset in ("ETH", "SOL"):
        closes = source.daily_closes(asset, start, end)
        msg = f"{asset}: expected {days_in_range} rows, got {len(closes)}"
        assert len(closes) == days_in_range, msg


def test_fake_price_source_filter_by_date() -> None:
    source = FakePriceSource(FIXTURES)
    start = date(2025, 1, 1)
    end = date(2025, 1, 31)
    closes = source.daily_closes("BTC", start, end)
    assert all(start <= c.day <= end for c in closes)
    assert len(closes) == 31


def test_fake_price_source_unknown_asset() -> None:
    source = FakePriceSource(FIXTURES)
    closes = source.daily_closes("UNKNOWN", date(2025, 1, 1), date(2025, 1, 31))
    assert closes == []


def test_fake_price_source_source_field() -> None:
    source = FakePriceSource(FIXTURES)
    closes = source.daily_closes("BTC", date(2025, 7, 14), date(2025, 7, 14))
    assert closes[0].source == "fixture-composite"


# ---------------------------------------------------------------------------
# FakeYouTubeClient
# ---------------------------------------------------------------------------


def test_fake_youtube_list_all_uploads() -> None:
    client = FakeYouTubeClient(FIXTURES)
    channel_id = "UCfix-northchain-0001"
    videos = client.list_all_uploads(channel_id, months=24)
    assert len(videos) >= 5
    for v in videos:
        assert v.youtube_video_id != ""
        assert v.title != ""


def test_fake_youtube_list_uploads_since_filters() -> None:
    client = FakeYouTubeClient(FIXTURES)
    channel_id = "UCfix-northchain-0001"
    # Before all fixture dates — should return all videos
    all_videos = client.list_uploads_since(channel_id, datetime(2000, 1, 1, tzinfo=UTC))
    assert len(all_videos) >= 5
    # After all fixture dates — should return none
    no_videos = client.list_uploads_since(channel_id, datetime(2030, 1, 1, tzinfo=UTC))
    assert no_videos == []


def test_fake_youtube_captions_present() -> None:
    """Most videos should have captions available."""
    videos_file = FIXTURES / "videos.json"
    videos: list[dict[str, Any]] = json.loads(videos_file.read_text(encoding="utf-8"))
    has_captions = [v for v in videos if v.get("captions_available") is not False]
    assert len(has_captions) >= 10


def test_fake_youtube_captions_absent_for_at_least_one() -> None:
    """At least one video must return None captions (to exercise FakeTranscriber)."""
    client = FakeYouTubeClient(FIXTURES)
    videos_file = FIXTURES / "videos.json"
    videos: list[dict[str, Any]] = json.loads(videos_file.read_text(encoding="utf-8"))
    absent = [v for v in videos if v.get("captions_available") is False]
    assert len(absent) >= 1, "Need at least one video with captions_available=false"
    for v in absent:
        result = client.fetch_captions(str(v["youtube_video_id"]))
        assert result is None


def test_fake_youtube_captions_returns_json_text() -> None:
    """For a video with captions, fetch_captions returns parseable JSON."""
    client = FakeYouTubeClient(FIXTURES)
    # Use a known video that has captions
    text = client.fetch_captions("NCfx-btc-dec01")
    assert text is not None
    segs = json.loads(text)
    assert isinstance(segs, list)
    assert len(segs) > 0
    assert "start_seconds" in segs[0]
    assert "text" in segs[0]


def test_fake_youtube_all_three_channels_have_videos() -> None:
    client = FakeYouTubeClient(FIXTURES)
    for channel_id in (
        "UCfix-northchain-0001",
        "UCfix-aylinmarkets-0002",
        "UCfix-vectoredge-0003",
    ):
        videos = client.list_all_uploads(channel_id, months=24)
        assert len(videos) >= 2, f"Channel {channel_id} has fewer than 2 videos"


# ---------------------------------------------------------------------------
# FakeTranscriber
# ---------------------------------------------------------------------------


def test_fake_transcriber_replays_segments() -> None:
    transcriber = FakeTranscriber(FIXTURES)
    segments = transcriber.transcribe("NCfx-btc-apr30")
    assert len(segments) > 0
    for seg in segments:
        assert seg.start_seconds >= 0
        assert seg.end_seconds > seg.start_seconds
        assert len(seg.text) > 0


def test_fake_transcriber_audio_prefix_stripped() -> None:
    """The audio:// prefix is stripped when locating the fixture file."""
    transcriber = FakeTranscriber(FIXTURES)
    segs_raw = transcriber.transcribe("NCfx-btc-apr30")
    segs_prefixed = transcriber.transcribe("audio://NCfx-btc-apr30")
    assert len(segs_raw) == len(segs_prefixed)


def test_fake_transcriber_missing_file_raises() -> None:
    transcriber = FakeTranscriber(FIXTURES)
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe("nonexistent-video-id")


# ---------------------------------------------------------------------------
# FakeExtractor
# ---------------------------------------------------------------------------


def _load_all_claims() -> list[dict[str, Any]]:
    path = FIXTURES / "claims.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_fake_extractor_detect_candidates_all_videos() -> None:
    """FakeExtractor.detect_candidates should find all fixture claims across all videos."""
    client = FakeYouTubeClient(FIXTURES)
    extractor = FakeExtractor(FIXTURES)
    all_claims = _load_all_claims()
    all_found_texts: set[str] = set()

    for channel_id in (
        "UCfix-northchain-0001",
        "UCfix-aylinmarkets-0002",
        "UCfix-vectoredge-0003",
    ):
        videos = client.list_all_uploads(channel_id, months=24)
        for vid in videos:
            caps = client.fetch_captions(vid.youtube_video_id)
            if caps is not None:
                from brier_pipeline.transcription.transcriber import TranscriptSegment

                raw = json.loads(caps)
                segs = [TranscriptSegment(**s) for s in raw]
            else:
                transcriber = FakeTranscriber(FIXTURES)
                segs = transcriber.transcribe(vid.youtube_video_id)
            candidates = extractor.detect_candidates(segs)
            all_found_texts.update(c.text for c in candidates)

    # Every claim quote should have been detected
    fixture_quotes = {c["quote"] for c in all_claims}
    missing = fixture_quotes - all_found_texts
    assert missing == set(), f"Missing fixture claims: {missing}"


def test_fake_extractor_structure_claim_versions_stamped() -> None:
    """Structured claims must carry model_version='fixture-replay' and prompt_version='v0'."""
    extractor = FakeExtractor(FIXTURES)
    all_claims = _load_all_claims()
    for raw in all_claims[:5]:  # spot-check first 5
        from brier_pipeline.extraction.extractor import CandidateSpan

        span = CandidateSpan(
            start_seconds=float(raw["source_offset_seconds"]),
            end_seconds=float(raw["source_offset_seconds"]) + 8.0,
            text=raw["quote"],
        )
        claim = extractor.structure_claim(span)
        assert claim.model_version == "fixture-replay"
        assert claim.prompt_version == "v0"


def test_fake_extractor_structure_claim_all_30_fixtures() -> None:
    """All fixture claims must be structured end-to-end without error."""
    extractor = FakeExtractor(FIXTURES)
    all_claims = _load_all_claims()
    assert len(all_claims) >= 30, f"Expected >=30 fixture claims, got {len(all_claims)}"
    for raw in all_claims:
        from brier_pipeline.extraction.extractor import CandidateSpan

        span = CandidateSpan(
            start_seconds=float(raw["source_offset_seconds"]),
            end_seconds=float(raw["source_offset_seconds"]) + 8.0,
            text=raw["quote"],
        )
        claim = extractor.structure_claim(span)
        # Placeholder IDs for DB-assigned fields
        assert claim.analyst_id == 0
        assert claim.video_id == 0
        assert claim.transcript_id == 0
        assert claim.model_version == "fixture-replay"
        assert claim.prompt_version == "v0"
        assert claim.publishable is True
        assert "fixture_id" in claim.flags


def test_fake_extractor_specificity_class_preserved() -> None:
    extractor = FakeExtractor(FIXTURES)
    all_claims = _load_all_claims()
    for raw in all_claims:
        from brier_pipeline.extraction.extractor import CandidateSpan

        span = CandidateSpan(
            start_seconds=float(raw["source_offset_seconds"]),
            end_seconds=float(raw["source_offset_seconds"]) + 8.0,
            text=raw["quote"],
        )
        claim = extractor.structure_claim(span)
        assert str(claim.specificity_class.value) == raw["specificity_class"]


def test_fake_extractor_fixture_id_in_flags() -> None:
    """fixture_id and fixture_base_rate must be stored in claim.flags."""
    extractor = FakeExtractor(FIXTURES)
    all_claims = _load_all_claims()
    # Pick a non-non_falsifiable claim with a base_rate
    scored_claims = [c for c in all_claims if c.get("fixture_base_rate") is not None]
    assert len(scored_claims) >= 25
    for raw in scored_claims[:5]:
        from brier_pipeline.extraction.extractor import CandidateSpan

        span = CandidateSpan(
            start_seconds=float(raw["source_offset_seconds"]),
            end_seconds=float(raw["source_offset_seconds"]) + 8.0,
            text=raw["quote"],
        )
        claim = extractor.structure_claim(span)
        assert claim.flags.get("fixture_id") == raw["fixture_id"]
        assert claim.flags.get("fixture_base_rate") == raw["fixture_base_rate"]


# ---------------------------------------------------------------------------
# Fixture integrity tests
# ---------------------------------------------------------------------------


def test_fixture_p0_equals_close_on_utterance_date() -> None:
    """Every claim's p0_price must equal the fixture close on its utterance date."""
    source = FakePriceSource(FIXTURES)
    all_claims = _load_all_claims()
    errors: list[str] = []
    for c in all_claims:
        if c.get("asset") is None or c.get("p0_price") is None:
            continue
        uttered_day = date.fromisoformat(c["uttered_at"][:10])
        closes = source.daily_closes(str(c["asset"]), uttered_day, uttered_day)
        if not closes:
            errors.append(f"{c['fixture_id']}: no price for {c['asset']} on {uttered_day}")
            continue
        expected = closes[0].close_usd
        stated = float(c["p0_price"])
        if abs(expected - stated) > 1.0:
            errors.append(
                f"{c['fixture_id']}: p0={stated} but fixture close={expected} on {uttered_day}"
            )
    assert errors == [], "p0_price mismatches:\n" + "\n".join(errors)


def test_fixture_quotes_max_15_words() -> None:
    """NFR-4: verbatim quotes must be at most 15 words."""
    all_claims = _load_all_claims()
    violations = [
        f"{c['fixture_id']}: {len(c['quote'].split())} words"
        for c in all_claims
        if len(c["quote"].split()) > 15
    ]
    assert violations == [], "Quote length violations:\n" + "\n".join(violations)


def test_fixture_quotes_appear_in_transcripts() -> None:
    """Each claim's verbatim quote must appear in its video's transcript."""
    all_claims = _load_all_claims()
    errors: list[str] = []
    for c in all_claims:
        vid_id = c["youtube_video_id"]
        quote = c["quote"]
        transcript_path = FIXTURES / "transcripts" / f"{vid_id}.json"
        if not transcript_path.exists():
            errors.append(f"{c['fixture_id']}: no transcript file for {vid_id}")
            continue
        segs = json.loads(transcript_path.read_text(encoding="utf-8"))
        found = any(s["text"] == quote for s in segs)
        if not found:
            errors.append(f"{c['fixture_id']}: quote not in transcript {vid_id!r}")
    assert errors == [], "Quote-in-transcript violations:\n" + "\n".join(errors)


def test_fixture_base_rate_in_range() -> None:
    """Fixture base rates must be in [0.2, 0.7] when present."""
    all_claims = _load_all_claims()
    errors: list[str] = []
    for c in all_claims:
        br = c.get("fixture_base_rate")
        if br is None:
            continue
        if not (0.2 <= float(br) <= 0.7):
            errors.append(f"{c['fixture_id']}: base_rate={br} out of [0.2, 0.7]")
    assert errors == [], "Base rate range violations:\n" + "\n".join(errors)


def test_fixture_assets_in_allowed_set() -> None:
    """All claim assets must be BTC, ETH, or SOL."""
    all_claims = _load_all_claims()
    allowed = {"BTC", "ETH", "SOL"}
    violations = [
        f"{c['fixture_id']}: asset={c['asset']!r}"
        for c in all_claims
        if c.get("asset") is not None and c["asset"] not in allowed
    ]
    assert violations == [], "Asset violations:\n" + "\n".join(violations)


def test_fixture_hp2_canonical_claim() -> None:
    """HP-2 canonical claim must exist with exact required fields."""
    all_claims = _load_all_claims()
    hp2 = next((c for c in all_claims if c["fixture_id"] == "hp2-btc-80k"), None)
    assert hp2 is not None, "hp2-btc-80k claim not found in claims.json"
    assert hp2["asset"] == "BTC"
    assert hp2["target_price"] == 80000.0
    assert hp2["direction"] == "bullish"
    assert hp2["horizon_deadline"] == "2025-07-31"
    assert hp2["specificity_class"] == "target_deadline"
    # p0 must be the Apr 30 BTC close
    source = FakePriceSource(FIXTURES)
    closes = source.daily_closes("BTC", date(2025, 4, 30), date(2025, 4, 30))
    assert abs(closes[0].close_usd - float(hp2["p0_price"])) < 1.0


def test_fixture_specificity_spread() -> None:
    """Must cover all five specificity classes with at least 2 each (non_falsifiable >=2)."""
    all_claims = _load_all_claims()
    counts: dict[str, int] = {}
    for c in all_claims:
        sc = c["specificity_class"]
        counts[sc] = counts.get(sc, 0) + 1
    for cls in SpecificityClass:
        assert counts.get(cls.value, 0) >= 2, (
            f"Specificity class {cls.value!r} has only {counts.get(cls.value, 0)} claims"
        )


def test_fixture_open_claims_exist() -> None:
    """Must have at least 3 claims with deadlines after 2026-06-11 (open)."""
    all_claims = _load_all_claims()
    cutoff = date(2026, 6, 11)
    open_claims = [
        c
        for c in all_claims
        if c.get("horizon_deadline") and date.fromisoformat(c["horizon_deadline"]) > cutoff
    ]
    assert len(open_claims) >= 3, f"Expected >=3 open claims, found {len(open_claims)}"


def test_fixture_conditional_claims_exist() -> None:
    """Must have at least 2 conditional claims."""
    all_claims = _load_all_claims()
    conditional = [c for c in all_claims if c["specificity_class"] == "conditional"]
    assert len(conditional) >= 2


def test_fixture_all_analysts_covered() -> None:
    """All three fixture analysts must have claims."""
    all_claims = _load_all_claims()
    slugs = {c["analyst_slug"] for c in all_claims}
    assert "northchain" in slugs
    assert "aylin-markets" in slugs
    assert "vectoredge" in slugs


def test_fixture_segment_texts_unique() -> None:
    """Claim-bearing segment texts must be unique across the whole corpus."""
    all_claims = _load_all_claims()
    quotes = [c["quote"] for c in all_claims]
    assert len(quotes) == len(set(quotes)), "Duplicate claim quotes detected"


def test_fixture_northchain_has_nonfalsifiable() -> None:
    """NorthChain profile requires non_falsifiable statements."""
    all_claims = _load_all_claims()
    nc_nf = [
        c
        for c in all_claims
        if c["analyst_slug"] == "northchain" and c["specificity_class"] == "non_falsifiable"
    ]
    assert len(nc_nf) >= 2, f"NorthChain needs >=2 non_falsifiable claims, has {len(nc_nf)}"


# ---------------------------------------------------------------------------
# Demo integration test (DB-dependent, skip if DB down)
# ---------------------------------------------------------------------------


def test_demo_run_is_idempotent(db_conn: Any) -> None:
    """Running the demo twice must produce no extra rows (idempotency)."""
    from brier_pipeline.demo import run_demo

    run_demo()
    counts2 = run_demo()

    # On the second run, everything is already present
    assert counts2["claims_persisted"] == 0, (
        f"Second run created {counts2['claims_persisted']} new claims (expected 0)"
    )
    assert counts2["videos_persisted"] == 0
    assert counts2["transcripts_persisted"] == 0
    # All claims should be skipped
    assert counts2["claims_skipped"] > 0


def test_demo_run_persists_fixture_claims(db_conn: Any) -> None:
    """After one demo run, the DB should contain the fixture claims."""
    from brier_pipeline.demo import run_demo

    run_demo()

    with db_conn.cursor() as cur:
        cur.execute("select count(*) from claims where model_version = 'fixture-replay'")
        row = cur.fetchone()
        assert row is not None
        count = int(row[0])
    # Claim count is read dynamically from claims.json
    all_claims = _load_all_claims()
    assert count == len(all_claims), f"Expected {len(all_claims)} claims, got {count}"


def test_demo_run_persists_all_videos(db_conn: Any) -> None:
    """After demo, DB should contain all fixture videos."""
    from brier_pipeline.demo import run_demo

    run_demo()

    videos_file = FIXTURES / "videos.json"
    videos: list[dict[str, Any]] = json.loads(videos_file.read_text(encoding="utf-8"))

    with db_conn.cursor() as cur:
        cur.execute("select count(*) from videos where youtube_video_id like '%fx-%'")
        row = cur.fetchone()
        assert row is not None
        count = int(row[0])
    assert count == len(videos), f"Expected {len(videos)} videos, got {count}"
