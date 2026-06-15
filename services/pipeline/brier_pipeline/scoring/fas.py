"""Falsifiable Accuracy Score (FAS) — implementation per docs/METHODOLOGY.md v1.0.

Formula spec: docs/METHODOLOGY.md
Convention pins (unspecified details filled in): docs/adr/0002-scoring-convention-pins.md

ADR reference: ADR-0002 pins the following computation details (not formula changes):
  - norm(DS) = clamp((DS + 0.25) / 0.5, 0, 1); zero skill maps to 0.5
  - Consistency K: rolling 10-claim chronological windows (stride 1), population stdev
  - R_prior = median of pre-shrinkage R across analysts in the run (n >= 1); fallback 0.5 for < 3
  - direction_magnitude claims: implied P_target = P0 * (1 +/- magnitude_pct/100)
  - sigma_annual: stdev of trailing 365 daily log-returns, annualized by sqrt(365)
  - Spam damping: (analyst, asset, ISO week) groups; m > 3 → w / sqrt(m)
  - Falsifiability F: resolved-and-scored claims / all extracted prediction-like statements
  - Zero-confidence claims: C = 0 (no calibration evidence earns no calibration credit)

Determinism (NFR-2): stable ordering (uttered_at, then claim id) everywhere.
Scores are written to append-only ledger rows; never mutated (NFR-3).
Formula changes require an ADR + methodology version bump + full-history recompute (FR-304, AC-4).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

import psycopg

from brier_pipeline import config
from brier_pipeline.models import Claim, Resolution, Score, SpecificityClass

SHRINKAGE_K = 25  # METHODOLOGY.md §6; change only via ADR + version bump
MIN_RANKED_N = 20  # FR-305
PROVISIONAL_CLEARS_AT_N = 30  # two-tier provisional rule, METHODOLOGY.md §6

# Specificity weights (METHODOLOGY.md §4)
_SPECIFICITY_WEIGHT: dict[SpecificityClass, float] = {
    SpecificityClass.DIRECTION_ONLY: 1.0,
    SpecificityClass.DIRECTION_MAGNITUDE: 1.5,
    SpecificityClass.TARGET_DEADLINE: 2.0,
    SpecificityClass.CONDITIONAL: 0.75,
    SpecificityClass.NON_FALSIFIABLE: 0.0,  # never scores
}


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------


def _norm_ds(ds: float) -> float:
    """Map DS to [0, 1]: clamp((DS + 0.25) / 0.5, 0, 1). Zero skill → 0.5.

    ADR-0002 pin 1.
    """
    return max(0.0, min(1.0, (ds + 0.25) / 0.5))


def _specificity_v(claim: Claim) -> float:
    """Return specificity weight v for the claim's class (METHODOLOGY.md §4)."""
    return _SPECIFICITY_WEIGHT.get(claim.specificity_class, 0.0)


def _difficulty_d(claim: Claim, sigma_annual: float | None = None) -> float:
    """Compute difficulty d (METHODOLOGY.md §4).

    - direction_only: d = 0.5 (spec constant)
    - direction_magnitude: implied P_target = P0 * (1 +/- magnitude_pct/100),
      then use the deadline formula (ADR-0002 pin 4a)
    - target_deadline / conditional: d = clamp(|ln(P_target/P0)| / (sigma * sqrt(T)), 0.25, 2.0)
    """
    sc = claim.specificity_class

    if sc == SpecificityClass.DIRECTION_ONLY:
        return 0.5

    if sc == SpecificityClass.DIRECTION_MAGNITUDE:
        # ADR-0002 pin 4a: implied P_target from magnitude_pct
        p0 = claim.p0_price
        mag = claim.magnitude_pct
        if p0 is None or p0 <= 0 or mag is None:
            return 0.5  # fallback when fields missing
        sign = 1.0 if claim.direction == "bullish" else -1.0
        p_target = p0 * (1.0 + sign * mag / 100.0)
        return _deadline_difficulty(p_target, p0, claim, sigma_annual)

    if sc in (SpecificityClass.TARGET_DEADLINE, SpecificityClass.CONDITIONAL):
        p0 = claim.p0_price
        pt = claim.target_price
        if p0 is None or p0 <= 0 or pt is None or pt <= 0:
            return 0.5  # fallback when price fields missing
        return _deadline_difficulty(pt, p0, claim, sigma_annual)

    return 0.5  # non_falsifiable — weight will be 0 anyway


def _deadline_difficulty(
    p_target: float, p0: float, claim: Claim, sigma_annual: float | None
) -> float:
    """d = clamp(|ln(P_target/P0)| / (sigma_annual * sqrt(T_years)), 0.25, 2.0)."""
    if sigma_annual is None or sigma_annual <= 0:
        sigma_annual = 0.7  # reasonable BTC-like default when not provided
    deadline = claim.horizon_deadline
    uttered = claim.uttered_at
    if deadline is None:
        return 0.5
    # T_years = (deadline - utterance date) / 365.25
    utterance_date = uttered.date() if isinstance(uttered, datetime) else uttered
    t_days = (deadline - utterance_date).days
    if t_days <= 0:
        return 0.25
    t_years = t_days / 365.25
    log_return = abs(math.log(p_target / p0))
    d = log_return / (sigma_annual * math.sqrt(t_years))
    return max(0.25, min(2.0, d))


def _base_weight(claim: Claim, sigma_annual: float | None = None) -> float:
    """Raw claim weight w = v * d before spam damping (METHODOLOGY.md §4)."""
    v = _specificity_v(claim)
    if v == 0.0:
        return 0.0
    d = _difficulty_d(claim, sigma_annual)
    return v * d


def claim_weight(
    claim: Claim,
    group_size: int = 1,
    sigma_annual: float | None = None,
) -> float:
    """w = v × d with spam damping (METHODOLOGY.md §4).

    Spam damping (ADR-0002 pin 4c): group claims per (analyst, asset, ISO week).
    If the group has m > 3 claims, every claim in the group takes w / sqrt(m).

    Args:
        claim: The claim to weight.
        group_size: m — number of claims in the (analyst, asset, ISO week) group.
        sigma_annual: Annualised volatility for d computation; uses default if None.
    """
    w = _base_weight(claim, sigma_annual)
    if group_size > 3:
        w = w / math.sqrt(group_size)
    return w


def _build_spam_groups(
    claims: list[Claim],
) -> dict[tuple[int, str, str], int]:
    """Return mapping from (analyst_id, asset, iso_week) -> count of claims in group."""
    groups: dict[tuple[int, str, str], int] = {}
    for c in claims:
        asset = c.asset or ""
        iso_week = c.uttered_at.isocalendar()
        key = (c.analyst_id, asset, f"{iso_week.year}-W{iso_week.week:02d}")
        groups[key] = groups.get(key, 0) + 1
    return groups


def _claim_effective_weight(
    claim: Claim,
    spam_groups: dict[tuple[int, str, str], int],
    sigma_annual: float | None = None,
) -> float:
    """Compute effective weight with spam damping applied."""
    asset = claim.asset or ""
    iso_week = claim.uttered_at.isocalendar()
    group_key = (claim.analyst_id, asset, f"{iso_week.year}-W{iso_week.week:02d}")
    m = spam_groups.get(group_key, 1)
    return claim_weight(claim, group_size=m, sigma_annual=sigma_annual)


# ---------------------------------------------------------------------------
# Component scores (pure)
# ---------------------------------------------------------------------------


def directional_skill(
    resolved: list[tuple[Claim, Resolution, float]],
    sigma_annual: float | None = None,
) -> float:
    """DS = Σ w_i (y_i − b_i) / Σ w_i over (claim, resolution, base_rate).

    Non-falsifiable and void claims are excluded (METHODOLOGY.md §5).
    Stable ordering: (uttered_at, claim.id) for determinism (NFR-2).
    """
    if not resolved:
        return 0.0

    # Stable ordering
    ordered = sorted(
        resolved,
        key=lambda t: (t[0].uttered_at, t[0].id or 0),
    )

    # Build spam groups over all claims in this set
    claims_list = [c for c, _, _ in ordered]
    spam_groups = _build_spam_groups(claims_list)

    total_w = 0.0
    total_wds = 0.0
    for claim, resolution, base_rate in ordered:
        sc = claim.specificity_class
        if sc == SpecificityClass.NON_FALSIFIABLE:
            continue
        w = _claim_effective_weight(claim, spam_groups, sigma_annual)
        if w == 0.0:
            continue
        y = resolution.outcome
        b = base_rate
        total_wds += w * (y - b)
        total_w += w

    if total_w == 0.0:
        return 0.0
    return total_wds / total_w


def calibration(resolved: list[tuple[Claim, Resolution]]) -> float:
    """C = clamp(1 − Brier/0.25, 0, 1) over claims with stated_confidence (§5).

    ADR-0002: if analyst has zero claims with confidence, C = 0 (no calibration
    evidence earns no calibration credit).
    """
    # Extract (confidence, outcome) pairs where confidence is present;
    # the explicit float annotation narrows away None for mypy.
    conf_outcome: list[tuple[float, float]] = [
        (c.stated_confidence, r.outcome) for c, r in resolved if c.stated_confidence is not None
    ]
    if not conf_outcome:
        return 0.0  # no calibration evidence → no credit (ADR-0002)

    brier_sum = sum((conf - y) ** 2 for conf, y in conf_outcome)
    brier = brier_sum / len(conf_outcome)
    return max(0.0, min(1.0, 1.0 - brier / 0.25))


def consistency(
    resolved: list[tuple[Claim, Resolution, float]],
    sigma_annual: float | None = None,
) -> float:
    """K = 1 - normalized dispersion of rolling 10-claim DS windows (§5).

    ADR-0002 pin 2:
    - Chronological rolling 10-claim windows (stride 1) over analyst's resolved claims.
    - Each window scores its weighted DS.
    - K = clamp(1 - stdev(window DS values) / 0.25, 0, 1) using population stdev.
    - Fewer than 2 windows (n < 11) → K = 0.5 (neutral).

    Non-falsifiable and void claims are excluded.
    """
    # Filter out non-falsifiable; stable ordering (uttered_at, id)
    scorable = sorted(
        [t for t in resolved if t[0].specificity_class != SpecificityClass.NON_FALSIFIABLE],
        key=lambda t: (t[0].uttered_at, t[0].id or 0),
    )

    if len(scorable) < 11:
        return 0.5  # fewer than 2 full windows → neutral

    # Build spam groups over the full scorable set for deterministic weighting
    claims_list = [c for c, _, _ in scorable]
    spam_groups = _build_spam_groups(claims_list)

    window_size = 10
    window_ds_values: list[float] = []

    for start in range(len(scorable) - window_size + 1):
        window = scorable[start : start + window_size]
        total_w = 0.0
        total_wds = 0.0
        for claim, resolution, base_rate in window:
            w = _claim_effective_weight(claim, spam_groups, sigma_annual)
            if w == 0.0:
                continue
            total_w += w
            total_wds += w * (resolution.outcome - base_rate)
        ds_w = total_wds / total_w if total_w > 0.0 else 0.0
        window_ds_values.append(ds_w)

    if len(window_ds_values) < 2:
        return 0.5

    # Population stdev (ADR-0002 pin 2)
    mean_ds = sum(window_ds_values) / len(window_ds_values)
    variance = sum((v - mean_ds) ** 2 for v in window_ds_values) / len(window_ds_values)
    stdev_ds = math.sqrt(variance)

    return max(0.0, min(1.0, 1.0 - stdev_ds / 0.25))


def falsifiability(scored_count: int, prediction_like_count: int) -> float:
    """F = scored claims / total extracted prediction-like statements (§5).

    ADR-0002 pin 4d: scored_count = resolved-and-scored claims;
    prediction_like_count = all extracted prediction-like statements (denominator).

    Returns 0.0 when prediction_like_count == 0.
    """
    if prediction_like_count <= 0:
        return 0.0
    return max(0.0, min(1.0, scored_count / prediction_like_count))


def composite_fas(
    ds: float,
    c: float,
    k: float,
    f: float,
    n: int,
    population_median_r: float,
) -> float:
    """Compute the Falsifiable Accuracy Score (METHODOLOGY.md §6).

    R = 0.45·norm(DS) + 0.25·C + 0.15·K + 0.15·F
    FAS = 100 × (n·R + SHRINKAGE_K·R_prior) / (n + SHRINKAGE_K)

    with SHRINKAGE_K = 25 and R_prior = population_median_r.
    """
    norm_ds = _norm_ds(ds)
    r = 0.45 * norm_ds + 0.25 * c + 0.15 * k + 0.15 * f
    fas = 100.0 * (n * r + SHRINKAGE_K * population_median_r) / (n + SHRINKAGE_K)
    return fas


# ---------------------------------------------------------------------------
# Per-analyst scoring (pure, no DB)
# ---------------------------------------------------------------------------


class AnalystComponents:
    """Intermediate scoring components for one analyst."""

    def __init__(
        self,
        analyst_id: int,
        ds: float,
        c: float,
        k: float,
        f: float,
        n: int,
        prediction_like_count: int,
    ) -> None:
        self.analyst_id = analyst_id
        self.ds = ds
        self.c = c
        self.k = k
        self.f = f
        self.n = n
        self.prediction_like_count = prediction_like_count

    @property
    def pre_shrinkage_r(self) -> float:
        """R before shrinkage (used for run-population median)."""
        norm_ds = _norm_ds(self.ds)
        return 0.45 * norm_ds + 0.25 * self.c + 0.15 * self.k + 0.15 * self.f

    def ranked(self) -> bool:
        return self.n >= MIN_RANKED_N

    def provisional(self) -> bool:
        return self.n < PROVISIONAL_CLEARS_AT_N

    def to_score(
        self,
        score_run_id: int,
        methodology_version: str,
        population_median_r: float,
        supersedes_score_id: int | None = None,
    ) -> Score:
        """Build the Score ledger row."""
        fas = composite_fas(self.ds, self.c, self.k, self.f, self.n, population_median_r)
        return Score(
            score_run_id=score_run_id,
            analyst_id=self.analyst_id,
            methodology_version=methodology_version,
            fas=fas,
            directional_skill=self.ds,
            calibration=self.c,
            consistency=self.k,
            falsifiability=self.f,
            n_resolved=self.n,
            ranked=self.ranked(),
            provisional=self.provisional(),
            supersedes_score_id=supersedes_score_id,
        )


def score_analyst_pure(
    analyst_id: int,
    resolved: list[tuple[Claim, Resolution, float]],
    prediction_like_count: int,
    sigma_annual: float | None = None,
) -> AnalystComponents:
    """Compute all scoring components for one analyst from pure data.

    Args:
        analyst_id: The analyst's DB id.
        resolved: List of (Claim, Resolution, base_rate) tuples for resolved claims.
            Non-falsifiable and void claims must be excluded from DS/C/K; they enter
            F's denominator via prediction_like_count.
        prediction_like_count: Total extracted prediction-like statements for this
            analyst (denominator for falsifiability F).
        sigma_annual: Annualised volatility for difficulty computation.
    """
    # Scorable = resolved claims that are not non-falsifiable
    scorable = [
        (c, r, b) for c, r, b in resolved if c.specificity_class != SpecificityClass.NON_FALSIFIABLE
    ]
    n = len(scorable)

    ds = directional_skill(scorable, sigma_annual)
    c = calibration([(c, r) for c, r, _ in scorable])
    k = consistency(scorable, sigma_annual)
    f = falsifiability(n, prediction_like_count)

    return AnalystComponents(
        analyst_id=analyst_id,
        ds=ds,
        c=c,
        k=k,
        f=f,
        n=n,
        prediction_like_count=prediction_like_count,
    )


# ---------------------------------------------------------------------------
# DB layer: run_score_pass
# ---------------------------------------------------------------------------


def _load_resolved_claims(
    cur: psycopg.Cursor[Any],
) -> dict[int, list[tuple[Claim, Resolution, float]]]:
    """Load all resolved claims with their latest (non-superseded) resolution row
    and fixture base rate from claims.flags['fixture_base_rate'].

    Returns mapping: analyst_id -> [(Claim, Resolution, base_rate), ...]

    NOTE: The fixture_base_rate flag is used here. It will be replaced by the
    real base-rate engine in E4-T2 (base_rates.py).

    Resolution supersession: a resolution row is 'superseded' if another resolution
    references it via supersedes_resolution_id. We pick the non-superseded row
    (the leaf of the supersedes chain).
    """
    # Fetch all resolved claims with their non-superseded resolution
    cur.execute(
        """
        select
            c.id, c.analyst_id, c.video_id, c.transcript_id,
            c.asset, c.direction, c.target_price, c.magnitude_pct,
            c.horizon_deadline, c.horizon_basis,
            c.stated_confidence, c.confidence_basis,
            c.conditionality, c.specificity_class,
            c.source_offset_seconds, c.quote,
            c.uttered_at, c.p0_price,
            c.extraction_confidence, c.model_version, c.prompt_version,
            c.reviewer_id, c.review_state, c.publishable, c.status,
            c.dedup_cluster_id, c.flags,
            r.id as res_id, r.outcome, r.resolved_at, r.rule_id,
            r.rationale, r.price_citation, r.methodology_version as res_mv,
            r.supersedes_resolution_id
        from claims c
        join resolutions r on r.claim_id = c.id
        where c.status = 'resolved'
          and c.specificity_class != 'non_falsifiable'
          -- pick the non-superseded resolution (leaf of the chain)
          and not exists (
              select 1 from resolutions r2
              where r2.supersedes_resolution_id = r.id
          )
        order by c.analyst_id, c.uttered_at, c.id
        """
    )
    rows = cur.fetchall()

    result: dict[int, list[tuple[Claim, Resolution, float]]] = {}
    for row in rows:
        (
            cid,
            analyst_id,
            video_id,
            transcript_id,
            asset,
            direction,
            target_price,
            magnitude_pct,
            horizon_deadline,
            horizon_basis,
            stated_confidence,
            confidence_basis,
            conditionality,
            specificity_class_str,
            source_offset_seconds,
            quote,
            uttered_at,
            p0_price,
            extraction_confidence,
            model_version,
            prompt_version,
            reviewer_id,
            review_state,
            publishable,
            status,
            dedup_cluster_id,
            flags,
            res_id,
            outcome,
            resolved_at,
            rule_id,
            rationale,
            price_citation,
            res_mv,
            supersedes_resolution_id,
        ) = row

        claim = Claim(
            id=int(cid),
            analyst_id=int(analyst_id),
            video_id=int(video_id),
            transcript_id=int(transcript_id),
            asset=asset,
            direction=direction,
            target_price=float(target_price) if target_price is not None else None,
            magnitude_pct=float(magnitude_pct) if magnitude_pct is not None else None,
            horizon_deadline=horizon_deadline,
            horizon_basis=horizon_basis,
            stated_confidence=float(stated_confidence) if stated_confidence is not None else None,
            confidence_basis=confidence_basis,
            conditionality=conditionality,
            specificity_class=SpecificityClass(specificity_class_str),
            source_offset_seconds=int(source_offset_seconds),
            quote=quote,
            uttered_at=uttered_at,
            p0_price=float(p0_price) if p0_price is not None else None,
            extraction_confidence=float(extraction_confidence)
            if extraction_confidence is not None
            else None,
            model_version=str(model_version),
            prompt_version=str(prompt_version),
            reviewer_id=reviewer_id,
            review_state=review_state,
            publishable=bool(publishable),
            status=status,
            dedup_cluster_id=int(dedup_cluster_id) if dedup_cluster_id is not None else None,
            flags=flags if isinstance(flags, dict) else {},
        )
        resolution = Resolution(
            id=int(res_id),
            claim_id=int(cid),
            outcome=float(outcome),
            resolved_at=resolved_at,
            rule_id=str(rule_id),
            rationale=str(rationale),
            price_citation=price_citation if isinstance(price_citation, dict) else {},
            methodology_version=str(res_mv),
            supersedes_resolution_id=int(supersedes_resolution_id)
            if supersedes_resolution_id is not None
            else None,
        )

        # Base rate: from claims.flags['fixture_base_rate'] (E4-T2 replaces with real engine)
        flags_dict: dict[str, Any] = flags if isinstance(flags, dict) else {}
        base_rate_val = float(flags_dict.get("fixture_base_rate", 0.5))

        result.setdefault(int(analyst_id), []).append((claim, resolution, base_rate_val))

    return result


def _load_prediction_like_counts(
    cur: psycopg.Cursor[Any],
) -> dict[int, int]:
    """Count all extracted prediction-like statements per analyst.

    This includes non-falsifiable and void claims — the full denominator for F.
    """
    cur.execute(
        """
        select analyst_id, count(*)
        from claims
        group by analyst_id
        """
    )
    return {int(row[0]): int(row[1]) for row in cur.fetchall()}


def _write_score_run(
    cur: psycopg.Cursor[Any],
    methodology_version: str,
    trigger: Literal["nightly", "methodology_bump", "correction", "demo"],
    notes: str | None = None,
) -> int:
    """Insert a score_runs row and return its id."""
    cur.execute(
        """
        insert into score_runs (methodology_version, trigger, notes)
        values (%s, %s, %s)
        returning id
        """,
        (methodology_version, trigger, notes),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _write_score(cur: psycopg.Cursor[Any], score: Score) -> int:
    """Insert a scores row (append-only) and return its id."""
    cur.execute(
        """
        insert into scores (
            score_run_id, analyst_id, methodology_version,
            fas, directional_skill, calibration, consistency, falsifiability,
            n_resolved, ranked, provisional, supersedes_score_id
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id
        """,
        (
            score.score_run_id,
            score.analyst_id,
            score.methodology_version,
            score.fas,
            score.directional_skill,
            score.calibration,
            score.consistency,
            score.falsifiability,
            score.n_resolved,
            score.ranked,
            score.provisional,
            score.supersedes_score_id,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _finish_score_run(cur: psycopg.Cursor[Any], run_id: int) -> None:
    """Mark a score_run as finished. Uses UPDATE via direct SQL (score_runs is not
    append-only — only resolutions and scores are; see 0005_ledger.sql triggers).
    """
    cur.execute(
        "update score_runs set finished_at = now() where id = %s",
        (run_id,),
    )


def _execute_scoring_pass(
    c: psycopg.Connection[Any],
    methodology_version: str,
    trigger: Literal["nightly", "methodology_bump", "correction", "demo"],
    notes: str | None,
    *,
    caller_owns_transaction: bool,
) -> tuple[int, list[Score]]:
    """Core scoring pass body: load data, compute scores, write ledger rows.

    This shared helper is used by both run_score_pass and recompute_all so that
    neither duplicates the pass logic.  The caller controls the methodology_version
    string so recompute_all can stamp an explicit bump version while run_score_pass
    uses config.METHODOLOGY_VERSION.

    Steps:
      1. Load resolved claims + latest resolution rows + fixture base rates.
      2. Load prediction-like statement counts (falsifiability denominator).
      3. Compute per-analyst components and pre-shrinkage R.
      4. Compute run-population median R_prior (ADR-0002 pin 3).
      5. Write ONE score_runs row (with supplied trigger and notes).
      6. Write ONE scores row per analyst (append-only INSERT).
      7. Mark score_run finished.
      8. Commit only when the caller does not own the transaction.

    Returns:
        (score_run_id, list of Score objects written)
    """
    with c.cursor() as cur:
        resolved_by_analyst = _load_resolved_claims(cur)
        prediction_like_counts = _load_prediction_like_counts(cur)

    # Compute components for each analyst that has resolved claims
    components: dict[int, AnalystComponents] = {}
    for analyst_id, resolved in resolved_by_analyst.items():
        pred_count = prediction_like_counts.get(analyst_id, len(resolved))
        comp = score_analyst_pure(analyst_id, resolved, pred_count)
        components[analyst_id] = comp

    # Also create zero-score entries for analysts with no resolved claims
    # (they have prediction-like counts but no resolved claims)
    for analyst_id, pred_count in prediction_like_counts.items():
        if analyst_id not in components:
            comp = score_analyst_pure(analyst_id, [], pred_count)
            components[analyst_id] = comp

    # ADR-0002 pin 3: R_prior = median of pre-shrinkage R across analysts
    # with n >= 1; if fewer than 3 analysts in the run, R_prior = 0.5.
    analysts_with_claims = [a for a in components.values() if a.n >= 1]
    if len(analysts_with_claims) < 3:
        r_prior = 0.5
    else:
        r_values = sorted(a.pre_shrinkage_r for a in analysts_with_claims)
        mid = len(r_values) // 2
        if len(r_values) % 2 == 1:
            r_prior = r_values[mid]
        else:
            r_prior = (r_values[mid - 1] + r_values[mid]) / 2.0

    with c.cursor() as cur:
        run_id = _write_score_run(cur, methodology_version, trigger, notes)

        written: list[Score] = []
        for comp in sorted(components.values(), key=lambda x: x.analyst_id):
            score = comp.to_score(run_id, methodology_version, r_prior)
            score_id = _write_score(cur, score)
            score = score.model_copy(update={"id": score_id})
            written.append(score)

        _finish_score_run(cur, run_id)
        # Only commit when we own the connection; when the caller owns the
        # transaction (e.g. a rolled-back test connection) they manage commit
        # or rollback themselves (NFR-3: never commit test writes).
        if not caller_owns_transaction:
            c.commit()

    return run_id, written


def run_score_pass(
    trigger: Literal["nightly", "methodology_bump", "correction", "demo"],
    conn: psycopg.Connection[Any] | None = None,
) -> tuple[int, list[Score]]:
    """Run a full scoring pass and write results to the append-only ledger.

    Steps:
      1. Load resolved claims + latest resolution rows + fixture base rates.
      2. Load prediction-like statement counts (falsifiability denominator).
      3. Compute per-analyst components and pre-shrinkage R.
      4. Compute run-population median R_prior (ADR-0002 pin 3).
      5. Write ONE score_runs row.
      6. Write ONE scores row per analyst (append-only INSERT).
      7. Mark score_run finished.

    Returns:
        (score_run_id, list of Score objects written)

    Args:
        trigger: Why this run was started.
        conn: Optional psycopg connection (pass a rollback connection from tests).
            If None, opens a new connection via brier_pipeline.db.connect().
    """
    from brier_pipeline.db import connect

    methodology_version = config.METHODOLOGY_VERSION

    if conn is not None:
        return _execute_scoring_pass(
            conn,
            methodology_version,
            trigger,
            None,
            caller_owns_transaction=True,
        )

    with connect() as c:
        return _execute_scoring_pass(
            c,
            methodology_version,
            trigger,
            None,
            caller_owns_transaction=False,
        )


def recompute_all(
    methodology_version: str,
    conn: psycopg.Connection[Any] | None = None,
) -> int:
    """Methodology version bump: full-history recompute into a new score_run.

    Runs a complete scoring pass over ALL analysts/resolved claims and writes:
      - ONE new score_runs row with trigger='methodology_bump' and the supplied
        methodology_version.
      - ONE scores row per analyst, all stamped with methodology_version.

    The prior ledger (prior score_runs + scores rows) is retained unchanged
    (append-only INSERT; DB triggers enforce no UPDATE/DELETE on resolutions and
    scores — see migration 0005_ledger.sql).  Any prior run remains queryable
    after a recompute (FR-304, AC-4, HP-6).

    Args:
        methodology_version: The new methodology version string to stamp on the
            run and all score rows (e.g. "v1.1").  This is decoupled from
            config.METHODOLOGY_VERSION so the mechanism works independently of
            the actual version-bump task (E4-T2).
        conn: Optional psycopg connection.  When supplied the caller owns the
            transaction (rolled-back test connections); when None a fresh
            connection is opened via brier_pipeline.db.connect().

    Returns:
        The new score_run id (int).
    """
    from brier_pipeline.db import connect

    notes = f"full-history methodology recompute -> {methodology_version}"

    if conn is not None:
        run_id, _ = _execute_scoring_pass(
            conn,
            methodology_version,
            "methodology_bump",
            notes,
            caller_owns_transaction=True,
        )
        return run_id

    with connect() as c:
        run_id, _ = _execute_scoring_pass(
            c,
            methodology_version,
            "methodology_bump",
            notes,
            caller_owns_transaction=False,
        )
        return run_id
