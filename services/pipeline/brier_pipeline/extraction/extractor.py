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
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel

from brier_pipeline.extraction import llm as llm_module
from brier_pipeline.extraction.assets import resolve_asset
from brier_pipeline.extraction.embeddings import Embedder, SentenceTransformerEmbedder
from brier_pipeline.models import Claim, ClaimStatus, ReviewState, SpecificityClass
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


_PASS2_SYSTEM_PROMPT = (
    "You are a claim-structuring assistant for a crypto-analyst fact-checking platform. "
    "Your task is to extract structured fields from a transcript span that contains a "
    "prediction. Respond with valid JSON only, no markdown fences, no explanation. "
    "Flag sarcastic statements, hypotheticals, or paraphrases of others' views with "
    "excluded=true and the appropriate excluded_reason (sarcasm|hypothetical|paraphrase). "
    "Use only factual, neutral language consistent with a public-record analysis tool."
)

_PASS2_USER_TEMPLATE = """\
Extract structured fields from the following transcript span. Return a JSON object \
with exactly these keys (use null for unknown or absent fields):

{{
  "asset": "<raw asset name or ticker as mentioned, or null>",
  "direction": "<bullish|bearish|null>",
  "target_price": <number or null>,
  "magnitude_pct": <number or null>,
  "horizon_raw": "<verbatim horizon phrase or null>",
  "horizon_basis": "<stated|default_30d|default_90d|default_eoy>",
  "horizon_deadline": "<YYYY-MM-DD if explicitly stated, else null>",
  "confidence_language": "<will|likely|could|null — the hedging word used>",
  "stated_confidence": <explicit numeric probability 0-1 if stated, else null>,
  "conditionality": "<condition clause text or null>",
  "specificity_class": "<direction_only|direction_magnitude|target_deadline\
|conditional|non_falsifiable>",
  "quote": "<verbatim quote ≤15 words from the span>",
  "extraction_confidence": <your confidence 0.0-1.0 that this is a genuine falsifiable prediction>,
  "excluded": <true if sarcasm, hypothetical, or paraphrase of others — else false>,
  "excluded_reason": "<sarcasm|hypothetical|paraphrase|null>"
}}

Rules:
- horizon_basis: use "stated" only when an explicit date or deadline is given.
  Use "default_30d" for "soon", "default_eoy" for "this year"/"year-end", \
"default_90d" when no horizon is stated.
- horizon_deadline: populate only for "stated" horizons with an explicit date.
- quote must be verbatim text from the span, at most 15 words.
- Set excluded=true for sarcasm, hypotheticals ("imagine if..."), \
or paraphrasing others ("some say BTC will...").
- "could" without a stated condition is non-falsifiable (METHODOLOGY §1); \
set specificity_class="non_falsifiable".

Transcript span:
{span_text}
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
    def structure_claim(self, span: CandidateSpan, *, uttered_at: datetime) -> Claim:
        """Pass 2: structured FR-202 claim, with model/prompt versions stamped.

        Parameters
        ----------
        span:
            The candidate span from pass 1.
        uttered_at:
            The UTC datetime when the prediction was uttered (NFR-2 t0).
            Callers must supply this; there is no acceptable default.

        Excludes sarcasm, hypotheticals, and paraphrases of others (EC-3).
        EC-3-excluded claims must NOT be inserted into the claims table (they are not the
        analyst's own predictions and must not enter the F denominator — see is_excluded_span).
        Non-falsifiable claims (FR-204) ARE persisted and enter the F denominator but never
        score. Use classify_non_falsifiable() to detect them.
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

    def structure_claim(self, span: CandidateSpan, *, uttered_at: datetime) -> Claim:
        """Map a candidate span back to its fixture claim record.

        The ``uttered_at`` parameter matches the abstract base signature (required keyword).
        FakeExtractor always prefers the fixture record's own ``uttered_at`` value (which
        captures the realistic utterance time), but falls back to the caller-supplied value
        when the fixture record lacks one.
        """
        index = self._load_index()
        raw = index.get(span.text)
        if raw is None:
            raise KeyError(f"FakeExtractor: no fixture claim for span text: {span.text!r}")
        return _raw_to_claim(raw, uttered_at_override=uttered_at)


def _raw_to_claim(raw: dict[str, Any], *, uttered_at_override: datetime | None = None) -> Claim:
    """Convert a fixture claims.json record to a models.Claim.

    analyst_id, video_id, and transcript_id are set to 0 (placeholder).
    The demo layer replaces these after inserting parent rows.
    horizon_deadline is a date string in the fixture; convert to date.
    uttered_at is a datetime string; convert to datetime with UTC.
    When uttered_at_override is supplied AND the fixture record has no uttered_at,
    the override is used; otherwise the fixture value takes precedence.
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

    # Prefer fixture-record uttered_at; fall back to caller override only when absent.
    raw_uttered_at = raw.get("uttered_at")
    if raw_uttered_at is not None:
        uttered_at_value = _dt(raw_uttered_at)
    elif uttered_at_override is not None:
        uttered_at_value = uttered_at_override
    else:
        raise ValueError(
            "_raw_to_claim: uttered_at missing from fixture record and no override supplied"
        )

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
        uttered_at=uttered_at_value,
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

    def structure_claim(self, span: CandidateSpan, *, uttered_at: datetime) -> Claim:
        """Pass 2: structure a candidate span into a full FR-202 Claim (NFR-2).

        Calls the Haiku-class model once per span with a structuring prompt that
        returns a JSON object. Parses robustly (no crash on bad JSON). Applies:
          - Asset alias resolution + EC-7 void on unresolvable asset.
          - EC-3 exclusion for sarcasm / hypothetical / paraphrase.
          - METHODOLOGY §1 imputed confidence ("will"→0.85, "likely"→0.70).
          - METHODOLOGY §1 horizon basis mapping (stated / default_30d / default_eoy /
            default_90d); default deadline DATES are deferred to E4-T1.
          - NFR-4 quote clamped to ≤15 words verbatim from span.text.
          - NFR-2 model_version + prompt_version stamped on every claim.
        """
        user_content = _PASS2_USER_TEMPLATE.format(span_text=span.text)
        response = self._completion(
            self.model_version,
            [{"role": "user", "content": user_content}],
            system=_PASS2_SYSTEM_PROMPT,
            max_tokens=512,
        )
        parsed = _parse_pass2_response(response)
        return _build_claim_from_pass2(
            parsed=parsed,
            span=span,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            uttered_at=uttered_at,
        )


# ---------------------------------------------------------------------------
# Pass-2 parsing + claim construction helpers
# ---------------------------------------------------------------------------

_IMPUTED_CONFIDENCE: dict[str, tuple[float, str]] = {
    "will": (0.85, "imputed_will"),
    "likely": (0.70, "imputed_likely"),
}

_VALID_HORIZON_BASES = {"stated", "default_30d", "default_90d", "default_eoy"}

_VALID_SPECIFICITY = {c.value for c in SpecificityClass}

_VALID_DIRECTIONS = {"bullish", "bearish"}

# Hedge words that (without a condition) render a claim unfalsifiable per METHODOLOGY §1.
# "could", "might", "maybe" signal extreme epistemic hedging with no resolvable commitment.
_VAGUE_HEDGE_WORDS: frozenset[str] = frozenset({"could", "might", "maybe"})

# Horizon phrases that indicate open-ended time references with no resolvable deadline.
# These make a claim unresolvable because there is no date at which to check the outcome.
_OPEN_ENDED_HORIZON_PHRASES: frozenset[str] = frozenset(
    {
        "eventually",
        "at some point",
        "long term",
        "long-term",
        "someday",
        "in the future",
        "one day",
        "sometime",
        "sooner or later",
    }
)


def _has_open_ended_phrase(quote: str | None) -> bool:
    """Return True when the quote contains an open-ended horizon phrase."""
    quote_lower = (quote or "").lower()
    return any(phrase in quote_lower for phrase in _OPEN_ENDED_HORIZON_PHRASES)


def classify_non_falsifiable(
    *,
    asset: str | None,
    direction: str | None,
    target_price: float | None,
    magnitude_pct: float | None,
    horizon_deadline: str | None,
    horizon_basis: str | None,
    confidence_language: str | None,
    conditionality: str | None,
    quote: str | None,
) -> bool:
    """Return True when the statement is prediction-like but UNFALSIFIABLE (FR-204).

    Evaluation order (first matching rule wins):

    Rule 0 — Concrete override (ADR-0007): a concrete, resolvable commitment is
        ALWAYS falsifiable even when hedged.
        "BTC might hit $100k by Dec 31" → target_price and horizon_deadline present
        → returns False immediately regardless of confidence_language.

    Rule 3 — No directional signal (no-signal): direction is None → sentiment or
        commentary with nothing to resolve. Fires regardless of whether an asset was
        named. "BTC is the future" (direction=None) → True.

    Rule 1 — Bare hedge: confidence_language in {"could", "might", "maybe"} with
        no conditionality → non-falsifiable per METHODOLOGY §1 "could excluded as
        non-falsifiable, unless paired with conditions." Extended to epistemic synonyms.

    Rule 2 — Open-ended horizon: an explicit open-ended time phrase in the quote
        disclaims any bounded deadline → non-falsifiable even when a default horizon
        would otherwise apply. Fires when horizon_basis is None OR "default_90d".

    A directional claim with a (stated or default) bounded horizon and no disclaiming
    language → FALSIFIABLE → returns False.

    Args:
        asset:               Canonical ticker string from resolve_asset(), or None.
        direction:           "bullish" | "bearish" | None.
        target_price:        Explicit price target, or None.
        magnitude_pct:       Magnitude percentage, or None.
        horizon_deadline:    ISO date string if stated explicitly, else None.
        horizon_basis:       One of the valid basis strings or None.
        confidence_language: Hedge word from the model (raw lowercase), or None.
        conditionality:      Condition clause text from the model, or None.
        quote:               Verbatim quote (≤15 words), or None.

    Returns:
        True  → classify as specificity_class=NON_FALSIFIABLE (counts in F, never scores).
        False → claim has a concrete falsifiable structure; do not downgrade.
    """
    # Rule 0 — Concrete override: a concrete resolvable commitment is always falsifiable.
    # target_price or magnitude_pct provides a testable threshold; horizon_deadline
    # provides a stated deadline. Either is sufficient to anchor resolution.
    has_concrete = target_price is not None or magnitude_pct is not None
    has_stated_deadline = bool(horizon_deadline)
    if has_concrete or has_stated_deadline:
        return False

    # Rule 3 — No directional signal: no direction → pure sentiment/commentary.
    # "BTC is the future" (direction=None) and "blockchain changes everything"
    # (asset=None, direction=None) are both non-falsifiable — there is no outcome
    # to resolve against. Fires regardless of asset presence.
    if direction is None:
        return True

    # Rule 1 — Bare hedge with no conditionality (METHODOLOGY §1).
    # "could excluded as non-falsifiable, unless paired with conditions."
    # Extended to epistemic synonyms "might" and "maybe" (ADR-0007).
    if (
        isinstance(confidence_language, str)
        and confidence_language.lower() in _VAGUE_HEDGE_WORDS
        and not conditionality
    ):
        return True

    # Rule 2 — Open-ended horizon phrase: an explicit open-ended time phrase in the
    # quote disclaims any bounded deadline, making the claim unresolvable.
    # Fires when horizon_basis is None (no horizon at all) or "default_90d" (the
    # "no horizon mentioned" fallback). Must fire regardless of which default applies.
    no_bounded_horizon = horizon_basis is None or horizon_basis == "default_90d"
    if no_bounded_horizon and _has_open_ended_phrase(quote):
        return True

    # Otherwise: a directional claim with a bounded horizon and no disclaiming language.
    return False


def _safe_float(v: Any) -> float | None:
    """Coerce a JSON-parsed value to float, returning None for non-numeric types.

    Accepts int and float only (excludes bool, which is a subclass of int in Python,
    to avoid True->1.0 / False->0.0 coercions that would silently accept malformed JSON).
    Any other type (dict, list, str, None) returns None — this prevents Pydantic
    ValidationError crashes when an LLM returns a badly typed field.
    """
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _parse_pass2_response(response: dict[str, Any]) -> dict[str, Any]:
    """Extract and parse the pass-2 JSON from a raw completion response.

    Returns an empty dict when the model returns non-object JSON or when
    JSON parsing fails — callers treat every field as optional.
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
        return {}

    if not isinstance(parsed, dict):
        return {}

    return dict(parsed)


def _clamp_quote(raw_quote: Any, span_text: str) -> str | None:
    """Return a verbatim quote of at most 15 words taken from span_text (NFR-4).

    If the model's quote is ≤15 words it is used as-is.  If it exceeds 15
    words OR is not found verbatim in the span, the first 15 words of
    ``span_text`` are used instead — never a paraphrase.

    Non-string values (list, int, dict, etc.) are treated as absent and return None.
    """
    if raw_quote is None:
        return None
    if not isinstance(raw_quote, str):
        return None

    words = raw_quote.split()
    if len(words) <= 15 and raw_quote in span_text:
        return raw_quote

    # Fallback: first 15 words of the span verbatim.
    span_words = span_text.split()
    return " ".join(span_words[:15])


def _build_claim_from_pass2(
    parsed: dict[str, Any],
    span: CandidateSpan,
    model_version: str,
    prompt_version: str,
    uttered_at: datetime,
) -> Claim:
    """Construct a Claim from pass-2 parsed fields (FR-202, EC-3, EC-7, NFR-2).

    Decision tree:
    1. EC-3: excluded=true → VOID claim with excluded_reason flag.
    2. EC-7: resolve_asset returns None → VOID claim with void_reason flag.
    3. Happy path: full FR-202 tuple populated.
    """
    # --- EC-3: sarcasm / hypothetical / paraphrase ---
    if parsed.get("excluded") is True:
        excluded_reason = str(parsed.get("excluded_reason") or "paraphrase")
        return Claim(
            analyst_id=0,
            video_id=0,
            transcript_id=0,
            asset=None,
            specificity_class=SpecificityClass.NON_FALSIFIABLE,
            source_offset_seconds=int(span.start_seconds),
            quote=_clamp_quote(parsed.get("quote"), span.text),
            model_version=model_version,
            prompt_version=prompt_version,
            uttered_at=uttered_at,
            status=ClaimStatus.VOID,
            review_state=ReviewState.UNREVIEWED,
            publishable=False,
            extraction_confidence=_safe_float(parsed.get("extraction_confidence")),
            flags={"excluded_reason": excluded_reason},
        )

    # --- Asset resolution (EC-7) ---
    raw_asset: str | None = parsed.get("asset")
    resolved_asset = resolve_asset(raw_asset)

    if resolved_asset is None:
        return Claim(
            analyst_id=0,
            video_id=0,
            transcript_id=0,
            asset=None,
            specificity_class=SpecificityClass.NON_FALSIFIABLE,
            source_offset_seconds=int(span.start_seconds),
            quote=_clamp_quote(parsed.get("quote"), span.text),
            model_version=model_version,
            prompt_version=prompt_version,
            uttered_at=uttered_at,
            status=ClaimStatus.VOID,
            review_state=ReviewState.UNREVIEWED,
            publishable=False,
            extraction_confidence=_safe_float(parsed.get("extraction_confidence")),
            flags={"void_reason": "unresolvable_asset"},
        )

    # --- Happy path: full FR-202 tuple ---

    # Specificity class
    raw_spec = parsed.get("specificity_class")
    if isinstance(raw_spec, str) and raw_spec in _VALID_SPECIFICITY:
        specificity_class = SpecificityClass(raw_spec)
    else:
        specificity_class = SpecificityClass.DIRECTION_ONLY

    # Direction — validated against the Literal values accepted by Claim
    raw_dir = parsed.get("direction")
    direction: Any = raw_dir if isinstance(raw_dir, str) and raw_dir in _VALID_DIRECTIONS else None

    # Confidence: prefer explicit stated_confidence; else impute from language.
    # confidence_basis is typed as Any here so Pydantic validates the Literal at
    # construction time rather than us needing to re-express the Literal type.
    stated_confidence: float | None = None
    confidence_basis: Any = None
    explicit_conf = parsed.get("stated_confidence")
    if not isinstance(explicit_conf, bool) and isinstance(explicit_conf, (int, float)):
        stated_confidence = float(explicit_conf)
        confidence_basis = "stated"
    else:
        confidence_language = parsed.get("confidence_language")
        if isinstance(confidence_language, str):
            imputed = _IMPUTED_CONFIDENCE.get(confidence_language.lower())
            if imputed is not None:
                stated_confidence, confidence_basis = imputed

    # Conditionality: plain text condition clause → stored as a dict for the Claim model.
    raw_cond = parsed.get("conditionality")
    conditionality: dict[str, Any] | None = (
        {"condition": raw_cond} if isinstance(raw_cond, str) and raw_cond.strip() else None
    )

    # Horizon basis is validated against _VALID_HORIZON_BASES before being
    # passed to Claim; typed as Any so Pydantic enforces the Literal at
    # construction rather than us repeating the Literal definition.
    raw_basis = parsed.get("horizon_basis")
    horizon_basis: Any = (
        raw_basis
        if isinstance(raw_basis, str) and raw_basis in _VALID_HORIZON_BASES
        else "default_90d"
    )
    horizon_deadline: date | None = None
    if horizon_basis == "stated":
        raw_deadline = parsed.get("horizon_deadline")
        if isinstance(raw_deadline, str):
            try:
                horizon_deadline = date.fromisoformat(raw_deadline)
            except ValueError:
                horizon_deadline = None

    # Target price + magnitude — use _safe_float to reject non-numeric JSON values.
    target_price: float | None = _safe_float(parsed.get("target_price"))
    magnitude_pct: float | None = _safe_float(parsed.get("magnitude_pct"))

    # FR-204: two-way authoritative specificity_class (ADR-0007).
    #
    # classify_non_falsifiable is the authoritative arbiter. It is called with
    # the full parsed tuple and its result overrides the model's stated class
    # in BOTH directions:
    #
    #   classifier=True  → force NON_FALSIFIABLE (model may have missed the hedge).
    #   classifier=False AND model returned NON_FALSIFIABLE → recompute a falsifiable
    #     class deterministically from the tuple (a falsifiable claim must never be
    #     left mislabeled non_falsifiable by a model error).
    #   else → keep the model's class.
    #
    # Non-falsifiable claims ARE persisted (they enter the F denominator per
    # METHODOLOGY §6) but never score (fas.py excludes NON_FALSIFIABLE from
    # DS/C/K and the scored numerator). They are NOT EC-3-excluded.
    confidence_language_raw = parsed.get("confidence_language")
    raw_cond_str: str | None = raw_cond if isinstance(raw_cond, str) and raw_cond.strip() else None
    is_non_falsifiable = classify_non_falsifiable(
        asset=resolved_asset,
        direction=direction,
        target_price=target_price,
        magnitude_pct=magnitude_pct,
        horizon_deadline=parsed.get("horizon_deadline") if horizon_basis == "stated" else None,
        horizon_basis=horizon_basis,
        confidence_language=confidence_language_raw
        if isinstance(confidence_language_raw, str)
        else None,
        conditionality=raw_cond_str,
        quote=_clamp_quote(parsed.get("quote"), span.text),
    )
    if is_non_falsifiable:
        specificity_class = SpecificityClass.NON_FALSIFIABLE
    elif specificity_class == SpecificityClass.NON_FALSIFIABLE:
        # Classifier says falsifiable but model mislabeled — recompute deterministically.
        if conditionality is not None:
            specificity_class = SpecificityClass.CONDITIONAL
        elif target_price is not None and horizon_deadline is not None:
            specificity_class = SpecificityClass.TARGET_DEADLINE
        elif direction is not None and magnitude_pct is not None:
            specificity_class = SpecificityClass.DIRECTION_MAGNITUDE
        else:
            specificity_class = SpecificityClass.DIRECTION_ONLY

    # Extraction confidence — use _safe_float to reject non-numeric JSON values.
    extraction_confidence: float | None = _safe_float(parsed.get("extraction_confidence"))

    # Quote (NFR-4: ≤15 words verbatim)
    quote = _clamp_quote(parsed.get("quote"), span.text)

    return Claim(
        analyst_id=0,
        video_id=0,
        transcript_id=0,
        asset=resolved_asset,
        direction=direction,
        target_price=target_price,
        magnitude_pct=magnitude_pct,
        horizon_deadline=horizon_deadline,
        horizon_basis=horizon_basis,
        stated_confidence=stated_confidence,
        confidence_basis=confidence_basis,
        conditionality=conditionality,
        specificity_class=specificity_class,
        source_offset_seconds=int(span.start_seconds),
        quote=quote,
        extraction_confidence=extraction_confidence,
        model_version=model_version,
        prompt_version=prompt_version,
        uttered_at=uttered_at,
        review_state=ReviewState.UNREVIEWED,
        publishable=False,
        status=ClaimStatus.OPEN,
        flags={},
    )


def is_excluded_span(claim: Claim) -> bool:
    """Return True when a claim is an EC-3-excluded span (sarcasm/hypothetical/paraphrase).

    EC-3-excluded claims are NOT the analyst's own predictions and must NOT be
    inserted into the claims table.  They must never enter the F denominator.
    Contrast with EC-7 voids (unresolvable asset) and non_falsifiable claims
    ("could" without condition), both of which ARE the analyst's own statements
    and ARE persisted (they correctly enter the F denominator per METHODOLOGY §6).

    The persist filter in demo.py (and the future extract job handler) must call
    this predicate before _insert_claim and skip any claim where it returns True.

    Contract:
      - EC-3 excluded  → is_excluded_span == True  → do NOT insert
      - EC-7 void      → is_excluded_span == False → insert (enters F denominator)
      - non_falsifiable → is_excluded_span == False → insert (enters F denominator)
      - normal claim   → is_excluded_span == False → insert
    """
    return bool(claim.flags.get("excluded_reason"))


def _horizons_overlap(a: Claim, b: Claim) -> bool:
    """Return True if claims a and b have overlapping horizon windows.

    A claim's horizon window is [uttered_at.date(), horizon_deadline].
    When horizon_deadline is None the horizon is open-ended (no deadline stated
    at all after applying defaults); in that case we treat it as overlapping with
    any other claim from the same analyst on the same asset/direction.
    """
    if a.horizon_deadline is None or b.horizon_deadline is None:
        # At least one claim has no deadline — treat as overlapping.
        return True
    start_a = a.uttered_at.date()
    start_b = b.uttered_at.date()
    # Intervals [start_a, deadline_a] and [start_b, deadline_b] overlap when
    # start_a <= deadline_b AND start_b <= deadline_a.
    return start_a <= b.horizon_deadline and start_b <= a.horizon_deadline


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two pre-normalised vectors.

    Both vectors are assumed unit-normalised (as HashEmbedder and the
    SentenceTransformerEmbedder both produce), so the cosine similarity is
    simply the dot product.  A full unnormalised version is used as a fallback
    in case the caller injects raw vectors.
    """
    dot: float = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm1: float = sum(a * a for a in v1) ** 0.5
    norm2: float = sum(b * b for b in v2) ** 0.5
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


def _update_claim_embedding(
    claim: Claim,
    embedding: list[float],
    conn: psycopg.Connection[Any],
) -> None:
    """Persist the embedding vector for a claim row (UPDATE claims.embedding)."""
    if claim.id is None:
        raise ValueError("claim must have a DB id before embedding can be persisted")
    vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE claims SET embedding = %s::vector WHERE id = %s",
            (vec_str, claim.id),
        )


def _update_claim_dedup_cluster(
    claim: Claim,
    cluster_id: int,
    conn: psycopg.Connection[Any],
) -> None:
    """Persist the dedup_cluster_id for a claim row."""
    if claim.id is None:
        raise ValueError("claim must have a DB id before dedup_cluster_id can be persisted")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE claims SET dedup_cluster_id = %s WHERE id = %s",
            (cluster_id, claim.id),
        )


def _pgvector_best_representative(
    candidate_embedding: list[float],
    rep_db_ids: list[int],
    conn: psycopg.Connection[Any],
) -> tuple[int, float] | None:
    """Query the DB for the most similar representative using the pgvector <=> operator.

    The <=> operator is the cosine-distance operator (distance = 1 - similarity).
    We restrict the search to the given ``rep_db_ids`` (the current set of cluster
    representative DB ids in this analyst/asset/direction group), then return
    ``(db_id, similarity)`` for the closest one, or None when the list is empty.

    This is the production similarity path (FR-205, §18): pgvector computes cosine
    distance natively; Python only applies the threshold and horizon-overlap checks.
    """
    if not rep_db_ids:
        return None
    vec_str = "[" + ",".join(str(v) for v in candidate_embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, (embedding <=> %s::vector) AS dist "
            "FROM claims WHERE id = ANY(%s) ORDER BY dist ASC LIMIT 1",
            (vec_str, rep_db_ids),
        )
        row = cur.fetchone()
    if row is None:
        return None
    db_id: int = int(row[0])
    dist: float = float(row[1])
    similarity: float = 1.0 - dist
    return db_id, similarity


def dedup_claims(
    claims: list[Claim],
    *,
    embedder: Embedder | None = None,
    conn: psycopg.Connection[Any] | None = None,
    similarity_threshold: float = 0.9,
) -> list[Claim]:
    """FR-205: semantic dedup (same analyst/asset/direction, overlapping horizon).

    Repeats reinforce, not multiply; assigns dedup_cluster_id using
    REPRESENTATIVE-LINKAGE clustering (eliminates transitive horizon-bridging).

    Clustering algorithm (representative-linkage):
      - Claims are processed in ascending uttered_at order within each
        (analyst_id, asset, direction) group.
      - The first claim in a group seeds a new cluster and becomes its
        REPRESENTATIVE.
      - Each subsequent claim is compared ONLY against existing REPRESENTATIVES
        (never against intermediate members).  It joins the first representative
        where BOTH:
          (a) cosine similarity >= threshold  AND
          (b) horizons overlap between the candidate and the REPRESENTATIVE.
      - If no representative qualifies, the claim seeds a new cluster (it
        becomes the new representative).
      - This ensures that a chain A[Jan-Mar] → B[Mar-Jun] → C[Jun-Sep] with
        identical vectors does NOT let C land in A's cluster: C is compared
        against A's representative directly, horizon-overlap fails (Jun-Sep does
        not overlap Jan-Mar), so C seeds its own cluster.

    Similarity computation:
      - DB path (conn provided): uses the pgvector ``<=>`` cosine-distance
        operator on the ``claims.embedding`` column — ``SELECT id,
        (embedding <=> %s::vector) AS dist FROM claims WHERE id = ANY(%s)
        ORDER BY dist ASC LIMIT 1`` — restricted to the current representative
        DB ids.  Similarity = 1 - distance.  Horizon-overlap and threshold
        checks are applied in Python after the query.
      - In-memory path (conn=None): pure Python ``_cosine_similarity`` over
        the in-process embedding vectors (no DB available).

    Args:
        claims: Mutable list of claims to dedup; dedup_cluster_id is set in-place.
        embedder: Embedder to use; defaults to SentenceTransformerEmbedder (ADR-0008
            gated — raises RuntimeError if sentence-transformers is absent).  Inject
            HashEmbedder or a custom fake in tests.
        conn: Optional psycopg connection.  When provided, claim embeddings and
            dedup_cluster_ids are written back to the DB via pgvector queries.
            Caller owns the transaction; this function never commits.
        similarity_threshold: Cosine similarity >= this value → same cluster.

    Returns:
        The same claims list with dedup_cluster_id populated on every claim.
    """
    if not claims:
        return claims

    resolved_embedder: Embedder = (
        embedder if embedder is not None else SentenceTransformerEmbedder()
    )

    # Step 1: Embed every claim and optionally persist the embedding.
    embeddings: dict[int, list[float]] = {}  # list-index → 384-dim vector
    for idx, claim in enumerate(claims):
        vec = resolved_embedder.embed(claim.quote or "")
        embeddings[idx] = vec
        if conn is not None and claim.id is not None:
            _update_claim_embedding(claim, vec, conn)

    # Step 2: Group claims by (analyst_id, asset, direction).
    # Only claims within the same group are candidates for dedup (FR-205).
    GroupKey = tuple[int, str | None, str | None]
    groups: dict[GroupKey, list[int]] = defaultdict(list)
    for idx, claim in enumerate(claims):
        key: GroupKey = (claim.analyst_id, claim.asset, claim.direction)
        groups[key].append(idx)

    # Step 3: Representative-linkage clustering within each group.
    #
    # cluster_rep_of[idx] = list-index of the representative for idx's cluster.
    # The representative is always the earliest-uttered member (EC-2).
    # We also track the ordered list of representative list-indices so we can
    # iterate them efficiently and build the DB-id list for pgvector queries.
    cluster_rep_of: dict[int, int] = {}

    for group_indices in groups.values():
        # Process claims in ascending uttered_at order.
        sorted_indices = sorted(group_indices, key=lambda i: claims[i].uttered_at)

        # representatives: ordered list of list-indices that are cluster seeds.
        representatives: list[int] = []

        for i in sorted_indices:
            claim_i = claims[i]
            vec_i = embeddings[i]

            if conn is not None:
                # DB path: use pgvector <=> for similarity; restrict to rep DB ids
                # whose claims also horizon-overlap the candidate.
                # We must filter by horizon overlap in Python (after the query)
                # because horizon columns are not indexed for this check.
                # Strategy: query pgvector for the single closest representative
                # (by cosine distance), then verify horizon overlap in Python.
                # If it passes, join that cluster; if not, scan remaining reps
                # in Python-cosine order until one passes or none does.
                #
                # For correctness with representative-linkage we compare only
                # against representatives, not all cluster members.
                rep_db_ids_with_idx: list[tuple[int, int]] = []
                for rep_idx in representatives:
                    rep_claim = claims[rep_idx]
                    if rep_claim.id is not None:
                        rep_db_ids_with_idx.append((rep_claim.id, rep_idx))

                if rep_db_ids_with_idx:
                    rep_db_ids = [pair[0] for pair in rep_db_ids_with_idx]
                    db_id_to_rep_idx = {pair[0]: pair[1] for pair in rep_db_ids_with_idx}

                    pgvec_result = _pgvector_best_representative(vec_i, rep_db_ids, conn)

                    joined_rep: int | None = None
                    if pgvec_result is not None:
                        best_db_id, best_sim = pgvec_result
                        best_rep_idx = db_id_to_rep_idx[best_db_id]
                        if best_sim >= similarity_threshold and _horizons_overlap(
                            claim_i, claims[best_rep_idx]
                        ):
                            joined_rep = best_rep_idx
                        else:
                            # Best by vector didn't pass horizon check; fall back
                            # to scanning remaining reps in Python-cosine order.
                            for rep_idx in representatives:
                                if rep_idx == best_rep_idx:
                                    continue
                                rep_claim = claims[rep_idx]
                                if not _horizons_overlap(claim_i, rep_claim):
                                    continue
                                if rep_claim.id is None:
                                    # No DB id; use in-memory cosine.
                                    sim = _cosine_similarity(vec_i, embeddings[rep_idx])
                                else:
                                    r = _pgvector_best_representative(vec_i, [rep_claim.id], conn)
                                    sim = r[1] if r is not None else 0.0
                                if sim >= similarity_threshold:
                                    joined_rep = rep_idx
                                    break
                    if joined_rep is not None:
                        cluster_rep_of[i] = joined_rep
                    else:
                        cluster_rep_of[i] = i
                        representatives.append(i)
                else:
                    # No existing representatives with DB ids; this claim seeds.
                    cluster_rep_of[i] = i
                    representatives.append(i)

            else:
                # In-memory path (no DB): pure Python cosine similarity.
                joined_mem: int | None = None
                for rep_idx in representatives:
                    rep_claim = claims[rep_idx]
                    if not _horizons_overlap(claim_i, rep_claim):
                        continue
                    sim = _cosine_similarity(vec_i, embeddings[rep_idx])
                    if sim >= similarity_threshold:
                        joined_mem = rep_idx
                        break
                if joined_mem is not None:
                    cluster_rep_of[i] = joined_mem
                else:
                    cluster_rep_of[i] = i
                    representatives.append(i)

    # Step 4: Assign dedup_cluster_id from DB ids of cluster representatives.
    # EC-2: the representative is always the earliest-uttered claim in the cluster.
    for idx, claim in enumerate(claims):
        rep_idx = cluster_rep_of.get(idx, idx)
        rep_claim = claims[rep_idx]
        # Use the DB id of the representative as the cluster id.
        # If claims lack DB ids (e.g. in-memory only), fall back to the list index.
        cluster_id: int = rep_claim.id if rep_claim.id is not None else rep_idx
        claim.dedup_cluster_id = cluster_id
        if conn is not None and claim.id is not None:
            _update_claim_dedup_cluster(claim, cluster_id, conn)

    return claims
