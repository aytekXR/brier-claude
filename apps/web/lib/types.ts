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

/** Claim-table row; populated when E1-T5 lands. */
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
