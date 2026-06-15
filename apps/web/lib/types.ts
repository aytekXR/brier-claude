/**
 * Read-layer row shapes. These mirror the public surface of the Postgres
 * schema (services/pipeline/migrations); the pipeline writes, the web reads.
 */

export type AnalystRow = {
  display_name: string;
  slug: string;
  status: "active" | "paused" | "removed";
};

export type ClaimStatus = "hit" | "miss" | "partial" | "open" | "void";

/** Display status includes non_falsifiable as a neutral indicator. */
export type DisplayStatus = ClaimStatus | "non_falsifiable";

/** Claim-table row from the read layer. */
export type ClaimRow = {
  id: number;
  asset: string;
  summary: string;
  horizonLabel: string;
  confidence: number | null;
  status: ClaimStatus;
};

/** FAS presentation bands per docs/BRANDKIT.md §1 (display only, not scoring). */
export const FAS_BANDS = [
  { min: 75, label: "Elite", cssVar: "var(--color-fas-elite)" },
  { min: 60, label: "Skilled", cssVar: "var(--color-fas-skilled)" },
  { min: 40, label: "Coin-flip", cssVar: "var(--color-fas-flip)" },
  { min: 0, label: "Anti-skilled", cssVar: "var(--color-fas-anti)" },
] as const;

/** Leaderboard row: one per analyst in the latest score_run. */
export type LeaderboardRow = {
  displayName: string;
  slug: string;
  fas: number;
  directionalSkill: number;
  calibration: number;
  consistency: number;
  falsifiability: number;
  nResolved: number;
  ranked: boolean;
  provisional: boolean;
  methodologyVersion: string;
};

/** Outcome counts for an analyst's claims. */
export type OutcomeCounts = {
  hit: number;
  miss: number;
  partial: number;
  open: number;
  void: number;
  nonFalsifiable: number;
};

/** Analyst header data including score row. */
export type AnalystDetail = {
  displayName: string;
  slug: string;
  fas: number;
  directionalSkill: number;
  calibration: number;
  consistency: number;
  falsifiability: number;
  nResolved: number;
  ranked: boolean;
  provisional: boolean;
  methodologyVersion: string;
  outcomeCounts: OutcomeCounts;
};

/** Claim row for the analyst claim table. */
export type AnalystClaimRow = {
  id: number;
  asset: string;
  direction: string | null;
  targetPrice: number | null;
  magnitudePct: number | null;
  horizonDeadline: string | null;
  horizonBasis: string | null;
  statedConfidence: number | null;
  specificityClass: string;
  quote: string | null;
  utteredAt: string;
  dbStatus: string;
  resolutionOutcome: number | null;
  displayStatus: DisplayStatus;
};

/** Receipt data for a single claim. */
export type ReceiptData = {
  claimId: number;
  asset: string;
  direction: string | null;
  targetPrice: number | null;
  magnitudePct: number | null;
  horizonDeadline: string | null;
  horizonBasis: string | null;
  statedConfidence: number | null;
  confidenceBasis: string | null;
  specificityClass: string;
  quote: string | null;
  utteredAt: string;
  p0Price: number | null;
  dbStatus: string;
  sourceOffsetSeconds: number;
  displayStatus: DisplayStatus;
  analystDisplayName: string;
  analystSlug: string;
  videoYoutubeId: string;
  videoTitle: string;
  videoPublishedAt: string;
  videoSourceStatus: string;
  resolutionOutcome: number | null;
  resolutionResolvedAt: string | null;
  resolutionRuleId: string | null;
  resolutionRationale: string | null;
  resolutionPriceCitation: {
    asset: string;
    day: string;
    close_usd: number;
    source: string;
  } | null;
  resolutionMethodologyVersion: string | null;
};

/** Price series point from price_daily. */
export type PricePoint = {
  day: string;
  closeUsd: number;
};

/**
 * One side of a resolution correction pair (NFR-3, FR-405).
 * Mirrors the columns visible on the corrections log.
 */
export type ResolutionSide = {
  resolutionId: number;
  outcome: number;
  resolvedAt: string;
  ruleId: string;
  rationale: string;
  methodologyVersion: string;
};

/**
 * One side of a score-recompute pair (trigger='methodology_bump').
 * Per-analyst before/after entry from adjacent score_runs.
 */
export type ScoreSide = {
  scoreRunId: number;
  methodologyVersion: string;
  startedAt: string;
  fas: number;
  nResolved: number;
  analystDisplayName: string;
  analystSlug: string;
};

/**
 * Discriminated union of correction event types for the public corrections log.
 *
 * kind='resolution'  — sourced from the curated `corrections` table (NFR-3, FR-405).
 *   Carries the public summary, claim receipt link, and both resolution sides.
 * kind='score_recompute' — a methodology-bump recompute pair (HP-6, AC-4).
 *
 * Both are chronological ledger events (append, never silent edits).
 */
export type CorrectionEntry =
  | {
      kind: "resolution";
      /** Wall-clock time of the correcting event (corrections.published_at). */
      eventAt: string;
      /** Correction record id from the corrections table. */
      correctionId: number;
      /** Neutral public summary authored by the pipeline (corrections.summary). */
      summary: string;
      /** Claim id — links to /r/[claimId] receipt page. */
      claimId: number;
      /** Asset name from the underlying claim. */
      asset: string;
      /** Display name of the analyst who made the claim. */
      analystDisplayName: string;
      /** Slug of the analyst — links to /a/[slug]. */
      analystSlug: string;
      superseded: ResolutionSide;
      superseding: ResolutionSide;
    }
  | {
      kind: "score_recompute";
      /** Wall-clock time of the correcting event (recompute run's started_at). */
      eventAt: string;
      prior: ScoreSide | null;
      recomputed: ScoreSide;
    };
