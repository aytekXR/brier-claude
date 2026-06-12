#!/usr/bin/env python3
"""Generate deterministic fixture transcript JSON files.

Each transcript contains segment lists with second-level offsets.
Claim-bearing segments include the exact verbatim quote from claims.json
at the claim's source_offset_seconds. Surrounding segments are neutral
filler dialogue to provide context.

Output: data/fixtures/transcripts/<youtube_video_id>.json
Run once; the output is committed.

All text is regulatory firewall-clean (no buy/sell/hold/signal/moon/
guaranteed/financial advice language).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAIMS_FILE = REPO_ROOT / "data" / "fixtures" / "claims.json"
TRANSCRIPTS_DIR = REPO_ROOT / "data" / "fixtures" / "transcripts"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def load_claims() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = json.loads(CLAIMS_FILE.read_text(encoding="utf-8"))
    return result


def make_segment(start: float, end: float, text: str) -> dict[str, Any]:
    return {"start_seconds": start, "end_seconds": end, "text": text}


def build_transcript(
    video_id: str, duration: int, claim_segments: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Build a transcript with filler around claim-bearing segments."""
    # Sort claim segments by offset
    claim_segments_sorted = sorted(claim_segments, key=lambda s: s["start_seconds"])

    segments: list[dict[str, Any]] = []

    # Intro filler
    segments.append(
        make_segment(
            0,
            12,
            "Welcome back to the channel. Today we are going through the current market environment.",
        )
    )
    segments.append(
        make_segment(
            12, 28, "Nothing in this video constitutes investment advice of any kind."
        )
    )
    segments.append(
        make_segment(
            28,
            45,
            "We are looking at the charts and discussing what the data suggests.",
        )
    )
    segments.append(
        make_segment(
            45,
            65,
            "The on-chain metrics have been quite interesting this week across multiple assets.",
        )
    )

    cursor = 65.0

    for cs in claim_segments_sorted:
        offset = cs["start_seconds"]
        text = cs["text"]
        seg_dur = cs.get("duration", 8.0)

        # Fill gap with filler segments
        while cursor < offset - 15:
            filler_end = min(cursor + 18, offset - 12)
            if filler_end <= cursor:
                break
            segments.append(
                make_segment(cursor, filler_end, _filler_for_cursor(cursor, video_id))
            )
            cursor = filler_end

        # Pre-claim filler (unique per claim offset to maintain uniqueness)
        pre_start = max(cursor, offset - 12)
        if pre_start < offset - 2:
            segments.append(
                make_segment(
                    pre_start,
                    offset - 1,
                    f"Looking at that specific level, the price action around {offset:.0f} seconds into this analysis is notable.",
                )
            )

        # The claim segment (exact quote)
        segments.append(make_segment(offset, offset + seg_dur, text))
        cursor = offset + seg_dur

    # Post-last-claim filler to end of video
    outro_start = cursor
    if outro_start < duration - 30:
        segments.append(
            make_segment(
                outro_start,
                outro_start + 20,
                "There are several other factors we are monitoring across the macro environment.",
            )
        )
        segments.append(
            make_segment(
                outro_start + 20,
                duration - 15,
                "The overall market structure will be discussed further in the next video.",
            )
        )

    segments.append(
        make_segment(
            duration - 15,
            duration,
            "That covers the analysis for today. We will follow up as the price action develops.",
        )
    )

    return segments


# Filler texts: neutral, no forbidden words
_FILLER_POOL = [
    "The weekly close was significant and we need to track what happens next.",
    "Market structure has been forming a notable pattern over the past few sessions.",
    "Volume data from on-chain analytics confirms the direction of the move.",
    "Looking at the historical precedent, this level has been tested multiple times.",
    "The correlation between macro conditions and crypto prices remains elevated.",
    "Risk management is always paramount when discussing any price scenario.",
    "Derivatives data shows positioning has shifted meaningfully in recent days.",
    "The funding rate environment provides additional context for directional bias.",
    "Exchange flows have been notable with large movements between wallets.",
    "The long-term holder base has remained relatively stable during this period.",
    "Technical levels from the monthly timeframe align with what we see on the daily.",
    "Liquidity zones above and below current price are important to monitor.",
    "The broader digital asset landscape has been reflecting global risk appetite.",
    "Institutional activity as measured by CME open interest continues to evolve.",
    "The relationship between price and the two hundred day moving average is worth noting.",
    "Sentiment data from social platforms has been lagging the actual price movement.",
    "Realized gains and losses on-chain provide a clear picture of market conditions.",
    "This timeframe tends to have lower volatility relative to the prior quarter.",
    "The market cap ratio between assets has been fluctuating in a known range.",
    "Supply dynamics are an important variable when projecting forward price ranges.",
    "The stablecoin ratio on exchanges is an underappreciated metric here.",
    "Network activity measured in transactions per day supports the current thesis.",
    "The options market term structure is providing interesting data points this week.",
    "We have seen this pattern before in the prior two market cycles as reference.",
    "The regulatory landscape remains a background variable affecting all assets.",
    "Macro correlations to equities have increased in the short term based on data.",
]


def _filler_for_cursor(cursor: float, video_id: str) -> str:
    idx = int(cursor + hash(video_id)) % len(_FILLER_POOL)
    return _FILLER_POOL[idx]


def main() -> None:
    claims = load_claims()

    # Group claims by video
    by_video: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        vid = claim["youtube_video_id"]
        by_video.setdefault(vid, []).append(claim)

    # Load video metadata
    videos_file = REPO_ROOT / "data" / "fixtures" / "videos.json"
    videos = json.loads(videos_file.read_text(encoding="utf-8"))
    video_meta = {v["youtube_video_id"]: v for v in videos}

    for video_id, vclaims in by_video.items():
        meta = video_meta.get(video_id, {})
        duration = meta.get("duration_seconds", 1200)

        # Skip captions-absent video (NCfx-btc-apr30) — FakeTranscriber will be used
        # We still generate a transcript JSON for it so FakeTranscriber can replay it.

        claim_segments = []
        for claim in vclaims:
            offset = float(claim["source_offset_seconds"])
            quote = claim["quote"]
            # The quote IS the verbatim segment text (the claim-bearing segment)
            claim_segments.append(
                {
                    "start_seconds": offset,
                    "duration": max(7.0, len(quote.split()) * 0.55),
                    "text": quote,
                }
            )

        segments = build_transcript(video_id, duration, claim_segments)

        # Sanity: verify every claim quote appears verbatim in the segments
        seg_texts = {s["text"] for s in segments}
        for claim in vclaims:
            if claim["quote"] not in seg_texts:
                raise ValueError(
                    f"Claim {claim['fixture_id']} quote not found in transcript {video_id}: {claim['quote']!r}"
                )

        out_path = TRANSCRIPTS_DIR / f"{video_id}.json"
        out_path.write_text(json.dumps(segments, indent=2) + "\n", encoding="utf-8")
        print(
            f"  Wrote {len(segments)} segments to {out_path.name} ({len(vclaims)} claims)"
        )

    # Also generate empty transcript file for sanity (none needed since all videos have claims)
    print(f"\nGenerated {len(by_video)} transcript files.")

    # Verify uniqueness of all claim-bearing segment texts across the entire corpus
    all_quotes = [c["quote"] for c in claims]
    if len(all_quotes) != len(set(all_quotes)):
        raise ValueError(
            "Duplicate claim quotes detected — FakeExtractor cannot replay deterministically."
        )
    print("All claim-bearing segment texts are unique across corpus.")


if __name__ == "__main__":
    main()
