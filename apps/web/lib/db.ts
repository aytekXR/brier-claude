/**
 * Thin typed read layer over Postgres. Server components only.
 *
 * Skeleton scope: listAnalysts() is the single implemented query (the DoD
 * allows listing seeded analysts by name and nothing more). Leaderboard,
 * claim, and receipt reads arrive with E1-T5 against materialized views.
 */

import postgres from "postgres";

import type { AnalystRow } from "./types";

const sql = postgres(
  process.env.BRIER_DATABASE_URL ?? "postgresql://brier:brier@localhost:5432/brier",
  { connect_timeout: 3 },
);

export async function listAnalysts(): Promise<AnalystRow[]> {
  return await sql<AnalystRow[]>`
    select display_name, slug, status
    from analysts
    order by display_name
  `;
}

// TASK: E1-T5 — leaderboard rows (FAS, n, falsifiability, trend) from the
// score ledger; claim table per analyst; receipt lookup by claim id.
