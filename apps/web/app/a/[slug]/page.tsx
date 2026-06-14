import Link from "next/link";

import { ClaimStatusChip } from "@/components/ClaimStatusChip";
import { ClaimTable } from "@/components/ClaimTable";
import { FASBadge } from "@/components/FASBadge";
import { getAnalyst, getAnalystClaims } from "@/lib/db";
import type { DisplayStatus } from "@/lib/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ slug: string }> };

/**
 * Analyst profile page (FR-402, PRD §19.2).
 *
 * Score header: lg FASBadge (band color + separate provisional tag),
 * four component bars (DS, C, K, F), outcome chip summary.
 * Filterable claim table (client-side, ClaimTable).
 */
export default async function AnalystPage({ params }: Params) {
  const { slug } = await params;

  let analyst = null;
  let claims = null;

  try {
    analyst = await getAnalyst(slug);
    if (analyst) {
      claims = await getAnalystClaims(slug);
    }
  } catch {
    analyst = null;
    claims = null;
  }

  if (analyst === null) {
    return (
      <div>
        <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">{slug}</h1>
        <p className="mt-3 font-mono text-[12px] text-ink-4">Not found in the registry.</p>
      </div>
    );
  }

  const { outcomeCounts } = analyst;

  return (
    <div>
      {/* Score header */}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex items-start gap-4">
          <FASBadge score={analyst.fas} provisional={analyst.provisional} size="lg" />
          <div>
            <h1 className="font-serif text-3xl font-semibold tracking-tight text-ink">
              {analyst.displayName}
            </h1>
            <p className="mt-1 font-mono text-[11px] text-ink-4">
              Methodology {analyst.methodologyVersion} ·{" "}
              <span className="num">n={analyst.nResolved}</span> resolved
            </p>
          </div>
        </div>
      </div>

      {/* Component bars */}
      <div className="mt-8 rounded-[6px] border border-line-2 bg-surface">
        <div className="border-b border-line bg-surface-2 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
          Score components — Methodology {analyst.methodologyVersion}
        </div>
        <div className="space-y-4 px-5 py-5">
          <ComponentBar
            label="Directional Skill (DS)"
            value={analyst.directionalSkill}
            min={-0.25}
            max={0.25}
            hint="Typical range −0.25 to +0.25; zero = coin-flip skill."
          />
          <ComponentBar
            label="Calibration (C)"
            value={analyst.calibration}
            min={0}
            max={1}
            hint="0 to 1; lower = overconfident relative to outcomes."
          />
          <ComponentBar
            label="Consistency (K)"
            value={analyst.consistency}
            min={0}
            max={1}
            hint="0 to 1; lower = higher dispersion across rolling 10-claim skill windows."
          />
          <ComponentBar
            label="Falsifiability (F)"
            value={analyst.falsifiability}
            min={0}
            max={1}
            hint={`Scored claims ÷ all prediction-like statements. ${outcomeCounts.nonFalsifiable} non-falsifiable statement${outcomeCounts.nonFalsifiable !== 1 ? "s" : ""} counted toward denominator, not scored.`}
          />
        </div>
      </div>

      {/* Outcome chip summary */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-4">
          Outcomes
        </span>
        <OutcomeCount count={outcomeCounts.hit} status="hit" />
        <OutcomeCount count={outcomeCounts.miss} status="miss" />
        {outcomeCounts.partial > 0 && (
          <OutcomeCount count={outcomeCounts.partial} status="partial" />
        )}
        <OutcomeCount count={outcomeCounts.open} status="open" />
        {outcomeCounts.void > 0 && (
          <OutcomeCount count={outcomeCounts.void} status="void" />
        )}
        {outcomeCounts.nonFalsifiable > 0 && (
          <OutcomeCount count={outcomeCounts.nonFalsifiable} status="non_falsifiable" />
        )}
      </div>

      {/* Claim table */}
      <h2 className="mt-10 font-serif text-2xl font-semibold text-ink">Claims</h2>
      <p className="mt-1 text-[13px] text-ink-3">
        All publishable claims, ordered by utterance date. Each row links to the full receipt
        with price chart and resolution rationale.
      </p>
      <div className="mt-4">
        {claims === null ? (
          <div className="rounded-[6px] border border-line-2 bg-surface px-4 py-8 text-center font-mono text-[13px] text-ink-3">
            Claim data unavailable.
          </div>
        ) : (
          <ClaimTable claims={claims} />
        )}
      </div>

      <p className="mt-6 font-mono text-[10.5px] text-ink-4">
        We publish statistics about public statements; we never recommend instruments or
        actions.{" "}
        <Link href="/methodology" className="text-[var(--color-brier-blue)] hover:underline">
          Methodology {analyst.methodologyVersion}
        </Link>
      </p>
    </div>
  );
}

/** Single component bar with labeled value (display to 2 decimals). */
function ComponentBar({
  label,
  value,
  min,
  max,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  hint: string;
}) {
  const range = max - min;
  const clamped = Math.max(min, Math.min(max, value));
  const pct = ((clamped - min) / range) * 100;
  // Zero-line position for signed tracks (DS)
  const zeroLine = min < 0 ? ((-min) / range) * 100 : null;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-medium text-ink-2">{label}</span>
        <span className="num font-mono text-[13px] font-medium text-ink">
          {value.toFixed(2)}
        </span>
      </div>
      <div
        className="relative mt-1.5 h-1.5 overflow-hidden rounded-full"
        style={{ background: "var(--color-line-2)" }}
        title={hint}
        role="meter"
        aria-label={`${label}: ${value.toFixed(2)}`}
        aria-valuenow={value}
        aria-valuemin={min}
        aria-valuemax={max}
      >
        {zeroLine !== null && (
          <span
            className="absolute top-0 h-full w-px"
            style={{ left: `${zeroLine}%`, background: "var(--color-ink-4)" }}
          />
        )}
        {zeroLine !== null ? (
          <span
            className="absolute top-0 h-full rounded-full"
            style={{
              left: value >= 0 ? `${zeroLine}%` : `${pct}%`,
              width: `${(Math.abs(value) / range) * 100}%`,
              // Ink, not a FAS band: band colors are reserved for badges and
              // chart annotations (BRANDKIT §1). Data bars use the ink ramp.
              background: value >= 0 ? "var(--color-ink-2)" : "var(--color-ink-4)",
              transition: "width 160ms ease-out",
            }}
          />
        ) : (
          <span
            className="absolute left-0 top-0 h-full rounded-full"
            style={{
              width: `${pct}%`,
              // Ink, not a FAS band (BRANDKIT §1).
              background: "var(--color-ink-2)",
              transition: "width 160ms ease-out",
            }}
          />
        )}
      </div>
      <p className="mt-0.5 font-mono text-[10px] text-ink-4">{hint}</p>
    </div>
  );
}

/** Count + chip inline. */
function OutcomeCount({ count, status }: { count: number; status: DisplayStatus }) {
  return (
    <span className="flex items-center gap-1">
      <span className="num font-mono text-[12px] text-ink-2">{count}</span>
      <ClaimStatusChip status={status} />
    </span>
  );
}
