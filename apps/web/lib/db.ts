/**
 * Thin typed read layer over Postgres. Server components only.
 *
 * All functions catch nothing internally — callers (pages) try/catch.
 * All "latest run" reads use (select max(id) from score_runs).
 * Filter web-visible claims with publishable = true everywhere.
 *
 * NOTE: postgres npm client returns SQL numeric as JS strings.
 * All numeric columns are cast to float8/int in SQL to avoid string math.
 */

import postgres from "postgres";

import type {
  AnalystClaimRow,
  AnalystDetail,
  AnalystRow,
  DisplayStatus,
  LeaderboardRow,
  OutcomeCounts,
  PricePoint,
  ReceiptData,
} from "./types";

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

/**
 * Leaderboard rows for the latest score_run.
 * Order: ranked desc (ranked analysts first), then fas desc.
 */
export async function getLeaderboard(): Promise<LeaderboardRow[]> {
  const rows = await sql<
    {
      display_name: string;
      slug: string;
      fas: number;
      directional_skill: number;
      calibration: number;
      consistency: number;
      falsifiability: number;
      n_resolved: number;
      ranked: boolean;
      provisional: boolean;
      methodology_version: string;
    }[]
  >`
    select
      a.display_name,
      a.slug,
      s.fas::float8         as fas,
      s.directional_skill::float8  as directional_skill,
      s.calibration::float8        as calibration,
      s.consistency::float8        as consistency,
      s.falsifiability::float8     as falsifiability,
      s.n_resolved::int            as n_resolved,
      s.ranked,
      s.provisional,
      s.methodology_version
    from scores s
    join analysts a on a.id = s.analyst_id
    where s.score_run_id = (select max(id) from score_runs)
    order by s.ranked desc, s.fas desc
  `;

  return rows.map((r) => ({
    displayName: r.display_name,
    slug: r.slug,
    fas: r.fas,
    directionalSkill: r.directional_skill,
    calibration: r.calibration,
    consistency: r.consistency,
    falsifiability: r.falsifiability,
    nResolved: r.n_resolved,
    ranked: r.ranked,
    provisional: r.provisional,
    methodologyVersion: r.methodology_version,
  }));
}

/**
 * Analyst header data + score row (left join to handle no-score case).
 * Returns null if the slug is not in the registry.
 *
 * Outcome counts reconcile:
 *   Aylin  6+4+0 resolved + 3 open + 0 nonfals = 13 total
 *   NorthChain 6+3+0 + 1 + 3 = 13 total
 *   VectorEdge 4+3+0 + 2 + 0 = 9 total
 */
export async function getAnalyst(slug: string): Promise<AnalystDetail | null> {
  const scoreRows = await sql<
    {
      display_name: string;
      slug: string;
      fas: number | null;
      directional_skill: number | null;
      calibration: number | null;
      consistency: number | null;
      falsifiability: number | null;
      n_resolved: number | null;
      ranked: boolean | null;
      provisional: boolean | null;
      methodology_version: string | null;
    }[]
  >`
    select
      a.display_name,
      a.slug,
      s.fas::float8                as fas,
      s.directional_skill::float8  as directional_skill,
      s.calibration::float8        as calibration,
      s.consistency::float8        as consistency,
      s.falsifiability::float8     as falsifiability,
      s.n_resolved::int            as n_resolved,
      s.ranked,
      s.provisional,
      s.methodology_version
    from analysts a
    left join scores s
      on s.analyst_id = a.id
      and s.score_run_id = (select max(id) from score_runs)
    where a.slug = ${slug}
    limit 1
  `;

  if (scoreRows.length === 0) return null;
  const row = scoreRows[0]!;

  // Outcome counts: latest non-superseded resolution per resolved claim
  const outcomesRaw = await sql<{ outcome: number; cnt: number }[]>`
    select
      r.outcome::float8 as outcome,
      count(*)::int     as cnt
    from claims c
    join analysts a on a.id = c.analyst_id
    join resolutions r on r.claim_id = c.id
    where a.slug = ${slug}
      and c.publishable = true
      and r.id not in (
        select supersedes_resolution_id
        from resolutions
        where supersedes_resolution_id is not null
      )
    group by r.outcome
  `;

  const hit = outcomesRaw.find((o) => o.outcome === 1)?.cnt ?? 0;
  const partial = outcomesRaw.find((o) => o.outcome === 0.5)?.cnt ?? 0;
  const miss = outcomesRaw.find((o) => o.outcome === 0)?.cnt ?? 0;

  // Open: status='open' AND specificity_class != 'non_falsifiable'
  const openRow = await sql<{ cnt: number }[]>`
    select count(*)::int as cnt
    from claims c
    join analysts a on a.id = c.analyst_id
    where a.slug = ${slug}
      and c.publishable = true
      and c.status = 'open'
      and c.specificity_class <> 'non_falsifiable'
  `;
  const open = openRow[0]?.cnt ?? 0;

  // Void: status='void'
  const voidRow = await sql<{ cnt: number }[]>`
    select count(*)::int as cnt
    from claims c
    join analysts a on a.id = c.analyst_id
    where a.slug = ${slug}
      and c.publishable = true
      and c.status = 'void'
  `;
  const voidCount = voidRow[0]?.cnt ?? 0;

  // Non-falsifiable: specificity_class='non_falsifiable'
  const nfRow = await sql<{ cnt: number }[]>`
    select count(*)::int as cnt
    from claims c
    join analysts a on a.id = c.analyst_id
    where a.slug = ${slug}
      and c.publishable = true
      and c.specificity_class = 'non_falsifiable'
  `;
  const nonFalsifiable = nfRow[0]?.cnt ?? 0;

  const outcomeCounts: OutcomeCounts = { hit, miss, partial, open, void: voidCount, nonFalsifiable };

  return {
    displayName: row.display_name,
    slug: row.slug,
    fas: row.fas ?? 0,
    directionalSkill: row.directional_skill ?? 0,
    calibration: row.calibration ?? 0,
    consistency: row.consistency ?? 0,
    falsifiability: row.falsifiability ?? 0,
    nResolved: row.n_resolved ?? 0,
    ranked: row.ranked ?? false,
    provisional: row.provisional ?? true,
    methodologyVersion: row.methodology_version ?? "v1.0",
    outcomeCounts,
  };
}

/**
 * Derive display status from raw DB fields.
 * resolved -> hit|miss|partial by outcome (1.0/0.0/0.5)
 * status 'open' & not non_falsifiable -> 'open'
 * specificity 'non_falsifiable' -> 'non_falsifiable'
 * status 'void' -> 'void'
 */
function deriveDisplayStatus(
  dbStatus: string,
  specificityClass: string,
  resolutionOutcome: number | null,
): DisplayStatus {
  if (specificityClass === "non_falsifiable") return "non_falsifiable";
  if (dbStatus === "void") return "void";
  if (dbStatus === "open") return "open";
  // resolved
  if (resolutionOutcome === 1) return "hit";
  if (resolutionOutcome === 0) return "miss";
  if (resolutionOutcome === 0.5) return "partial";
  return "open";
}

/**
 * Publishable claim rows for the analyst claim table.
 * Includes latest non-superseded resolution outcome.
 * Ordered uttered_at desc, id desc.
 */
export async function getAnalystClaims(slug: string): Promise<AnalystClaimRow[]> {
  const rows = await sql<
    {
      id: number;
      asset: string;
      direction: string | null;
      target_price: number | null;
      magnitude_pct: number | null;
      horizon_deadline: string | null;
      horizon_basis: string | null;
      stated_confidence: number | null;
      specificity_class: string;
      quote: string | null;
      uttered_at: string;
      db_status: string;
      resolution_outcome: number | null;
    }[]
  >`
    select
      c.id,
      c.asset,
      c.direction,
      c.target_price::float8       as target_price,
      c.magnitude_pct::float8      as magnitude_pct,
      c.horizon_deadline::text     as horizon_deadline,
      c.horizon_basis,
      c.stated_confidence::float8  as stated_confidence,
      c.specificity_class,
      c.quote,
      c.uttered_at::text           as uttered_at,
      c.status                     as db_status,
      r.outcome::float8            as resolution_outcome
    from claims c
    join analysts a on a.id = c.analyst_id
    left join resolutions r
      on r.claim_id = c.id
      and r.id not in (
        select supersedes_resolution_id
        from resolutions
        where supersedes_resolution_id is not null
      )
    where a.slug = ${slug}
      and c.publishable = true
    order by c.uttered_at desc, c.id desc
  `;

  return rows.map((r) => ({
    id: r.id,
    asset: r.asset,
    direction: r.direction,
    targetPrice: r.target_price,
    magnitudePct: r.magnitude_pct,
    horizonDeadline: r.horizon_deadline,
    horizonBasis: r.horizon_basis,
    statedConfidence: r.stated_confidence,
    specificityClass: r.specificity_class,
    quote: r.quote,
    utteredAt: r.uttered_at,
    dbStatus: r.db_status,
    resolutionOutcome: r.resolution_outcome,
    displayStatus: deriveDisplayStatus(r.db_status, r.specificity_class, r.resolution_outcome),
  }));
}

/**
 * Full receipt data for a claim. Returns null if not found or not publishable.
 */
export async function getReceipt(claimId: number): Promise<ReceiptData | null> {
  const rows = await sql<
    {
      claim_id: number;
      asset: string;
      direction: string | null;
      target_price: number | null;
      magnitude_pct: number | null;
      horizon_deadline: string | null;
      horizon_basis: string | null;
      stated_confidence: number | null;
      confidence_basis: string | null;
      specificity_class: string;
      quote: string | null;
      uttered_at: string;
      p0_price: number | null;
      db_status: string;
      source_offset_seconds: number;
      display_name: string;
      slug: string;
      youtube_video_id: string;
      video_title: string;
      video_published_at: string;
      source_status: string;
      resolution_outcome: number | null;
      resolved_at: string | null;
      rule_id: string | null;
      rationale: string | null;
      price_citation: string | null;
      resolution_methodology_version: string | null;
    }[]
  >`
    select
      c.id                                       as claim_id,
      c.asset,
      c.direction,
      c.target_price::float8                     as target_price,
      c.magnitude_pct::float8                    as magnitude_pct,
      c.horizon_deadline::text                   as horizon_deadline,
      c.horizon_basis,
      c.stated_confidence::float8                as stated_confidence,
      c.confidence_basis,
      c.specificity_class,
      c.quote,
      c.uttered_at::text                         as uttered_at,
      c.p0_price::float8                         as p0_price,
      c.status                                   as db_status,
      c.source_offset_seconds,
      a.display_name,
      a.slug,
      v.youtube_video_id,
      v.title                                    as video_title,
      v.published_at::text                       as video_published_at,
      v.source_status,
      r.outcome::float8                          as resolution_outcome,
      r.resolved_at::text                        as resolved_at,
      r.rule_id,
      r.rationale,
      r.price_citation::text                     as price_citation,
      r.methodology_version                      as resolution_methodology_version
    from claims c
    join analysts a on a.id = c.analyst_id
    join videos v on v.id = c.video_id
    left join resolutions r
      on r.claim_id = c.id
      and r.id not in (
        select supersedes_resolution_id
        from resolutions
        where supersedes_resolution_id is not null
      )
    where c.id = ${claimId}
      and c.publishable = true
    limit 1
  `;

  if (rows.length === 0) return null;
  const r = rows[0]!;

  let priceCitation: ReceiptData["resolutionPriceCitation"] = null;
  if (r.price_citation) {
    try {
      priceCitation = JSON.parse(r.price_citation) as ReceiptData["resolutionPriceCitation"];
    } catch {
      priceCitation = null;
    }
  }

  return {
    claimId: r.claim_id,
    asset: r.asset,
    direction: r.direction,
    targetPrice: r.target_price,
    magnitudePct: r.magnitude_pct,
    horizonDeadline: r.horizon_deadline,
    horizonBasis: r.horizon_basis,
    statedConfidence: r.stated_confidence,
    confidenceBasis: r.confidence_basis,
    specificityClass: r.specificity_class,
    quote: r.quote,
    utteredAt: r.uttered_at,
    p0Price: r.p0_price,
    dbStatus: r.db_status,
    sourceOffsetSeconds: r.source_offset_seconds,
    displayStatus: deriveDisplayStatus(r.db_status, r.specificity_class, r.resolution_outcome),
    analystDisplayName: r.display_name,
    analystSlug: r.slug,
    videoYoutubeId: r.youtube_video_id,
    videoTitle: r.video_title,
    videoPublishedAt: r.video_published_at,
    videoSourceStatus: r.source_status,
    resolutionOutcome: r.resolution_outcome,
    resolutionResolvedAt: r.resolved_at,
    resolutionRuleId: r.rule_id,
    resolutionRationale: r.rationale,
    resolutionPriceCitation: priceCitation,
    resolutionMethodologyVersion: r.resolution_methodology_version,
  };
}

/**
 * Price series for a chart window.
 * Returns daily closes for asset between startISO and endISO, excluding gaps.
 */
export async function getPriceSeries(
  asset: string,
  startISO: string,
  endISO: string,
): Promise<PricePoint[]> {
  const rows = await sql<{ day: string; close_usd: number }[]>`
    select
      day::text       as day,
      close_usd::float8 as close_usd
    from price_daily
    where asset = ${asset}
      and day between ${startISO}::date and ${endISO}::date
      and data_gap = false
    order by day asc
  `;

  return rows.map((r) => ({ day: r.day, closeUsd: r.close_usd }));
}

/**
 * Returns true if there are at least 2 distinct calendar dates among score_runs.
 * Used to drive the honest trend empty-state.
 */
export async function hasTrendHistory(): Promise<boolean> {
  const rows = await sql<{ cnt: number }[]>`
    select count(distinct started_at::date)::int as cnt
    from score_runs
  `;
  return (rows[0]?.cnt ?? 0) >= 2;
}
