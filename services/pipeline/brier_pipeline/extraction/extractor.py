"""Claim extraction behind a small interface (mock-first convention).

Pass 1 detects candidate prediction spans (FR-201); pass 2 structures each span
into the FR-202 claim tuple with model and prompt versions recorded (NFR-2).
The real implementation uses the stdlib-REST LLM seam (ADR-0005, proposed).
The FakeExtractor replays fixture claims so the walking skeleton (E1) and all
tests run without an API key.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from brier_pipeline.extraction import llm as llm_module
from brier_pipeline.models import Claim, ReviewState, SpecificityClass
from brier_pipeline.transcription.transcriber import TranscriptSegment

# Maximum segments per completion call (NFR-5: one call per batch, never one per segment).
_BATCH_SIZE = 40

_PASS1_SYSTEM_PROMPT = (
    "You are a prediction-detection assistant for a crypto-analyst fact-checking platform. "
    "Your task is to identify transcript segments that contain a falsifiable prediction "
    "about a specific crypto asset's price or direction within a stated or inferable time horizon. "
    "Do not flag general commentary, market observations, or non-falsifiable statements. "
    "Respond with valid JSON only, no markdown fences, no explanation."
)

_PASS1_USER_TEMPLATE = """\
Below are indexed transcript segments. Return the indices of segments that contain \
a candidate prediction (a falsifiable assertion about a crypto asset price, direction, \
or target within a stated or inferable horizon). For each matching index also include \
the verbatim text of that segment. Non-falsifiable commentary does not qualify.

Respond with a JSON object of this exact shape (no other keys):
{{"candidates": [{{"index": <int>, "text": "<verbatim segment text>"}}]}}

If no segments qualify, return: {{"candidates": []}}

Segments:
{segments_json}
"""


class CandidateSpan(BaseModel):
    """Pass-1 output: a transcript span that smells like a prediction (FR-201)."""

    start_seconds: float
    end_seconds: float
    text: str


class Extractor(ABC):
    @abstractmethod
    def detect_candidates(self, segments: list[TranscriptSegment]) -> list[CandidateSpan]:
        """Pass 1: candidate prediction spans (FR-201)."""

    @abstractmethod
    def structure_claim(self, span: CandidateSpan) -> Claim:
        """Pass 2: structured FR-202 claim, with model/prompt versions stamped.

        Must classify non-falsifiable statements (FR-204) and exclude sarcasm,
        hypotheticals, and paraphrases of others (EC-3).
        """


class FakeExtractor(Extractor):
    """Fixture-backed fake: replays data/fixtures/claims.json.

    Pass 1 (detect_candidates): matches segment texts against the verbatim
    quotes in claims.json. Each claim-bearing segment has a unique text across
    the whole corpus, so the match is deterministic.

    Pass 2 (structure_claim): maps the matched span back to its fixture claim
    record and returns a fully-populated models.Claim with:
        model_version='fixture-replay'
        prompt_version='v0'

    IDs that only exist after DB insert (analyst_id, video_id, transcript_id)
    are set to placeholder 0 here. The demo/ingestion layer fills them in after
    persisting the parent rows. Do not use these placeholder IDs directly.
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir
        self._claims_by_quote: dict[str, dict[str, Any]] | None = None

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if self._claims_by_quote is None:
            path = self.fixtures_dir / "claims.json"
            raw: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
            self._claims_by_quote = {r["quote"]: r for r in raw}
        return self._claims_by_quote

    def detect_candidates(self, segments: list[TranscriptSegment]) -> list[CandidateSpan]:
        """Return spans whose text matches a fixture claim quote verbatim."""
        index = self._load_index()
        candidates: list[CandidateSpan] = []
        for seg in segments:
            if seg.text in index:
                candidates.append(
                    CandidateSpan(
                        start_seconds=seg.start_seconds,
                        end_seconds=seg.end_seconds,
                        text=seg.text,
                    )
                )
        return candidates

    def structure_claim(self, span: CandidateSpan) -> Claim:
        """Map a candidate span back to its fixture claim record."""
        index = self._load_index()
        raw = index.get(span.text)
        if raw is None:
            raise KeyError(f"FakeExtractor: no fixture claim for span text: {span.text!r}")
        return _raw_to_claim(raw)


def _raw_to_claim(raw: dict[str, Any]) -> Claim:
    """Convert a fixture claims.json record to a models.Claim.

    analyst_id, video_id, and transcript_id are set to 0 (placeholder).
    The demo layer replaces these after inserting parent rows.
    horizon_deadline is a date string in the fixture; convert to date.
    uttered_at is a datetime string; convert to datetime with UTC.
    """
    from datetime import date as date_t

    def _date(val: Any) -> date_t | None:
        if val is None:
            return None
        if isinstance(val, date_t):
            return val
        return date_t.fromisoformat(str(val))

    def _dt(val: Any) -> datetime:
        s = str(val)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    flags: dict[str, Any] = {}
    fixture_id = raw.get("fixture_id")
    if fixture_id:
        flags["fixture_id"] = fixture_id
    base_rate = raw.get("fixture_base_rate")
    if base_rate is not None:
        flags["fixture_base_rate"] = base_rate

    return Claim(
        analyst_id=0,  # placeholder; filled by demo/ingestion layer
        video_id=0,  # placeholder; filled by demo/ingestion layer
        transcript_id=0,  # placeholder; filled by demo/ingestion layer
        asset=raw.get("asset"),
        direction=raw.get("direction"),
        target_price=raw.get("target_price"),
        magnitude_pct=raw.get("magnitude_pct"),
        horizon_deadline=_date(raw.get("horizon_deadline")),
        horizon_basis=raw.get("horizon_basis"),
        stated_confidence=raw.get("stated_confidence"),
        confidence_basis=raw.get("confidence_basis"),
        conditionality=raw.get("conditionality"),
        specificity_class=SpecificityClass(str(raw["specificity_class"])),
        source_offset_seconds=int(raw["source_offset_seconds"]),
        quote=raw.get("quote"),
        extraction_confidence=0.99,  # fixture replay: treat as high confidence
        model_version="fixture-replay",
        prompt_version="v0",
        review_state=ReviewState.APPROVED,
        publishable=True,
        uttered_at=_dt(raw["uttered_at"]),
        p0_price=raw.get("p0_price"),
        flags=flags,
    )


def _parse_pass1_response(
    response: dict[str, Any], batch: list[TranscriptSegment]
) -> list[CandidateSpan]:
    """Parse a pass-1 model response and map batch-relative indices to CandidateSpan.

    The model is asked to return JSON of shape:
        {"candidates": [{"index": <int>, "text": "<verbatim>"}]}

    Indices are 0-based relative to the submitted batch. Out-of-range or
    duplicate indices are silently skipped (robustness). Returns empty list
    when the model returns zero candidates or when JSON parsing fails cleanly.
    """
    content_blocks: list[dict[str, Any]] = response.get("content", [])
    raw_text = ""
    for block in content_blocks:
        if block.get("type") == "text":
            raw_text = str(block.get("text", ""))
            break

    try:
        parsed: Any = json.loads(raw_text)
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(parsed, dict):
        return []

    candidates_raw = parsed.get("candidates", [])
    if not isinstance(candidates_raw, list):
        return []

    spans: list[CandidateSpan] = []
    seen: set[int] = set()
    for item in candidates_raw:
        if not isinstance(item, dict):
            continue
        idx_raw = item.get("index")
        if not isinstance(idx_raw, int):
            continue
        if idx_raw < 0 or idx_raw >= len(batch):
            continue
        if idx_raw in seen:
            continue
        seen.add(idx_raw)
        seg = batch[idx_raw]
        # Use verbatim transcript text (AC-2 receipt integrity, NFR-4).
        # The model's echoed text is at most a hint and must not be stored.
        spans.append(
            CandidateSpan(
                start_seconds=seg.start_seconds,
                end_seconds=seg.end_seconds,
                text=seg.text,
            )
        )
    return spans


class LlmExtractor(Extractor):
    """Two-pass LLM extraction via the stdlib-REST seam (ADR-0005, proposed).

    Pass 1 (detect_candidates) batches segments into groups of at most
    _BATCH_SIZE, asks a Haiku-class model to return the indices of candidate
    prediction spans, and maps each returned index back to the source segment's
    start_seconds/end_seconds to produce CandidateSpan objects (FR-201).

    The completion callable is injected so tests can supply a recorded fixture
    response without touching the network. The default is llm.completion.
    """

    def __init__(
        self,
        model_version: str,
        prompt_version: str,
        completion: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.model_version = model_version
        self.prompt_version = prompt_version
        self._completion = completion if completion is not None else llm_module.completion

    def detect_candidates(self, segments: list[TranscriptSegment]) -> list[CandidateSpan]:
        """Pass 1: detect candidate prediction spans (FR-201).

        Batches segments in groups of at most _BATCH_SIZE segments per completion
        call (NFR-5: cost guardrail — never one call per segment). Parses the
        model's JSON response and maps returned indices back to the source
        segment offsets.
        """
        results: list[CandidateSpan] = []
        for batch_start in range(0, len(segments), _BATCH_SIZE):
            batch = segments[batch_start : batch_start + _BATCH_SIZE]
            batch_spans = self._detect_batch(batch)
            results.extend(batch_spans)
        return results

    def _detect_batch(self, batch: list[TranscriptSegment]) -> list[CandidateSpan]:
        """Run one completion call over a single batch of segments.

        The model returns batch-relative indices (0-based within this batch),
        which are mapped directly to ``batch[idx]``. Because batch slicing
        preserves the absolute segment objects, no offset arithmetic is needed:
        ``batch[idx].start_seconds`` and ``batch[idx].end_seconds`` are already
        the correct absolute values.
        """
        indexed: list[dict[str, Any]] = [
            {"index": i, "start": seg.start_seconds, "end": seg.end_seconds, "text": seg.text}
            for i, seg in enumerate(batch)
        ]
        segments_json = json.dumps(indexed, ensure_ascii=False)
        user_content = _PASS1_USER_TEMPLATE.format(segments_json=segments_json)

        response = self._completion(
            self.model_version,
            [{"role": "user", "content": user_content}],
            system=_PASS1_SYSTEM_PROMPT,
            max_tokens=1024,
        )

        return _parse_pass1_response(response, batch)

    def structure_claim(self, span: CandidateSpan) -> Claim:
        # TASK: E3-T2
        raise NotImplementedError


def dedup_claims(claims: list[Claim]) -> list[Claim]:
    """FR-205: semantic dedup (same analyst/asset/direction, overlapping horizon).

    Repeats reinforce, not multiply; assigns dedup_cluster_id via pgvector
    similarity. Handles re-uploads where the original timestamp governs (EC-2).
    """
    # TASK: E3-T5
    raise NotImplementedError
