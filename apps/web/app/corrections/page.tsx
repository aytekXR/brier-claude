import Link from "next/link";

import { getCorrectionsLog } from "@/lib/db";
import type { CorrectionEntry, ResolutionSide, ScoreSide } from "@/lib/types";

// Live data — never prerender a stale corrections log at build time.
export const dynamic = "force-dynamic";

/**
 * FR-405 / NFR-3 — Public corrections log.
 *
 * Corrections are appended ledger events, not silent edits (NFR-3).
 * Each entry shows the before/after pair:
 *   (a) Resolution correction: sourced from the curated corrections table;
 *       shows the neutral summary, claim receipt link, and superseded/superseding pair.
 *   (b) Score recompute (methodology_bump): prior run scores paired with recomputed scores.
 *
 * Numbers are ledger-exact (AC-3). Register: neutral, cite and do not characterize (BRANDKIT §7).
 */
export default async function CorrectionsPage() {
  let entries: CorrectionEntry[] = [];
  let loadError = false;

  try {
    entries = await getCorrectionsLog();
  } catch {
    loadError = true;
  }

  return (
    <div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">
        Corrections log
      </h1>
      <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-ink-3">
        Each entry records an appended correction event. Resolutions and scores are never
        silently edited; corrections appear here as paired before/after events (NFR-3).
      </p>

      {loadError ? (
        <div className="mt-8 rounded-[6px] border border-line-2 bg-surface px-6 py-10 text-center font-mono text-[13px] text-ink-3">
          Corrections ledger unavailable. Start the dev database:{" "}
          <code className="text-ink-2">make seed</code>
        </div>
      ) : entries.length === 0 ? (
        <div className="mt-8 rounded-[6px] border border-line-2 bg-surface px-6 py-10">
          <p className="text-center font-mono text-[13px] text-ink-3">
            No corrections recorded yet.
          </p>
          <p className="mt-2 text-center font-mono text-[11px] text-ink-4">
            When a resolution is superseded or scores are recomputed under a new methodology
            version, the event will appear here.
          </p>
        </div>
      ) : (
        <div className="mt-8 space-y-6">
          {entries.map((entry) => (
            <CorrectionCard
              key={
                entry.kind === "resolution"
                  ? `resolution-${entry.correctionId}`
                  : `score_recompute-${entry.recomputed.scoreRunId}-${entry.recomputed.analystSlug}`
              }
              entry={entry}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function CorrectionCard({ entry }: { entry: CorrectionEntry }) {
  if (entry.kind === "resolution") {
    return <ResolutionCorrectionCard entry={entry} />;
  }
  return <ScoreRecomputeCard entry={entry} />;
}

/**
 * Resolution correction card (type a).
 * Sourced from the corrections table: shows the public summary, claim receipt
 * link, asset, analyst, and the superseded/superseding resolution pair.
 */
function ResolutionCorrectionCard({
  entry,
}: {
  entry: Extract<CorrectionEntry, { kind: "resolution" }>;
}) {
  return (
    <div className="overflow-hidden rounded-[6px] border border-line-2 bg-surface">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-3">
        <span className="rounded-[3px] border border-line-2 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
          Resolution correction
        </span>
        <span className="font-mono text-[11px] text-ink-4">
          {entry.eventAt.slice(0, 10)}
        </span>
        <Link
          href={`/a/${entry.analystSlug}`}
          className="font-mono text-[11px] text-[var(--color-brier-blue)] hover:underline"
        >
          {entry.analystDisplayName}
        </Link>
        <span className="font-mono text-[11px] text-ink-4">{entry.asset}</span>
        <Link
          href={`/r/${entry.claimId}`}
          className="ml-auto font-mono text-[11px] text-[var(--color-brier-blue)] hover:underline"
        >
          Receipt {entry.claimId}
        </Link>
      </div>

      {/* Neutral public summary from the corrections table */}
      <div className="border-b border-line px-5 py-3 text-[13px] text-ink-3">
        {entry.summary}
      </div>

      {/* Before/After pair */}
      <div className="grid gap-0 divide-y divide-line sm:grid-cols-2 sm:divide-x sm:divide-y-0">
        <ResolutionPanel label="Superseded" side={entry.superseded} />
        <ResolutionPanel label="Correcting" side={entry.superseding} />
      </div>
    </div>
  );
}

function ResolutionPanel({
  label,
  side,
}: {
  label: string;
  side: ResolutionSide;
}) {
  const outcomeLabel =
    side.outcome === 1 ? "HIT" : side.outcome === 0.5 ? "PARTIAL" : "MISS";

  return (
    <div className="px-5 py-4">
      <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
        {label}
      </div>
      <div className="mt-3 space-y-2">
        <Field label="Resolution ID" value={String(side.resolutionId)} />
        <Field label="Outcome" value={outcomeLabel} />
        <Field label="Rule" value={side.ruleId} />
        <Field label="Resolved at" value={side.resolvedAt.slice(0, 10)} />
        <Field label="Methodology" value={side.methodologyVersion} />
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Rationale
          </dt>
          <dd className="mt-0.5 text-[12px] text-ink-3">{side.rationale}</dd>
        </div>
      </div>
    </div>
  );
}

/**
 * Score recompute card (type b).
 * Shows the prior run FAS alongside the recomputed FAS for one analyst.
 * Prior may be null for a newly-enrolled analyst absent from all prior runs.
 */
function ScoreRecomputeCard({
  entry,
}: {
  entry: Extract<CorrectionEntry, { kind: "score_recompute" }>;
}) {
  return (
    <div className="overflow-hidden rounded-[6px] border border-line-2 bg-surface">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-3">
        <span className="rounded-[3px] border border-line-2 px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
          Score recompute
        </span>
        <span className="font-mono text-[11px] text-ink-4">
          {entry.eventAt.slice(0, 10)}
        </span>
        <Link
          href={`/a/${entry.recomputed.analystSlug}`}
          className="ml-auto font-mono text-[11px] text-[var(--color-brier-blue)] hover:underline"
        >
          {entry.recomputed.analystDisplayName}
        </Link>
      </div>

      {/* Description */}
      <div className="border-b border-line px-5 py-3 text-[13px] text-ink-3">
        Score run {entry.recomputed.scoreRunId} ({entry.recomputed.methodologyVersion}) recomputed
        scores for {entry.recomputed.analystDisplayName}. Prior run{" "}
        {entry.prior !== null ? (
          <>
            {entry.prior.scoreRunId} ({entry.prior.methodologyVersion}) remains in the ledger and
            queryable.
          </>
        ) : (
          <>not available (analyst not present in any prior run).</>
        )}
      </div>

      {/* Before/After pair */}
      <div className="grid gap-0 divide-y divide-line sm:grid-cols-2 sm:divide-x sm:divide-y-0">
        {entry.prior !== null ? (
          <ScorePanel label="Prior" side={entry.prior} />
        ) : (
          <div className="px-5 py-4">
            <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
              Prior
            </div>
            <p className="mt-3 font-mono text-[12px] text-ink-4">
              No prior score run for this analyst.
            </p>
          </div>
        )}
        <ScorePanel label="Recomputed" side={entry.recomputed} />
      </div>
    </div>
  );
}

function ScorePanel({ label, side }: { label: string; side: ScoreSide }) {
  return (
    <div className="px-5 py-4">
      <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
        {label}
      </div>
      <div className="mt-3 space-y-2">
        <Field label="Score run" value={String(side.scoreRunId)} />
        <Field label="Methodology" value={side.methodologyVersion} />
        <Field label="FAS" value={side.fas.toFixed(1)} />
        <Field label="n resolved" value={String(side.nResolved)} />
        <Field label="Run started" value={side.startedAt.slice(0, 10)} />
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">{label}</dt>
      <dd className="num mt-0.5 font-mono text-[13px] text-ink-2">{value}</dd>
    </div>
  );
}
