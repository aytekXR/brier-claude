import Link from "next/link";

import { FASBadge } from "@/components/FASBadge";
import { TrendSparkline } from "@/components/TrendSparkline";
import { getCurrentMethodologyVersion, getLeaderboard, hasTrendHistory } from "@/lib/db";
import type { LeaderboardRow } from "@/lib/types";

// The leaderboard reads live data; never prerender a stale board at build time.
export const dynamic = "force-dynamic";

export default async function LeaderboardPage() {
  let rows: LeaderboardRow[] | null = null;
  let trendAvailable = false;
  let methodologyVersion = "v1.1";

  try {
    rows = await getLeaderboard();
    trendAvailable = await hasTrendHistory();
    methodologyVersion = await getCurrentMethodologyVersion();
  } catch {
    rows = null;
  }

  const ranked = rows?.filter((r) => r.ranked) ?? [];
  const provisional = rows?.filter((r) => !r.ranked) ?? [];

  return (
    <div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">Leaderboard</h1>
      <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-ink-3">
        Base-rate-corrected accuracy scores for crypto YouTube analysts, backed by a receipt
        for every resolved claim. Methodology{" "}
        <Link href="/methodology" className="text-[var(--color-brier-blue)] hover:underline">
          {methodologyVersion}
        </Link>
        .
      </p>

      {rows === null ? (
        <div className="mt-8 rounded-[6px] border border-line-2 bg-surface px-6 py-10 text-center font-mono text-[13px] text-ink-3">
          Score ledger unavailable. Start the dev database and seed it:{" "}
          <code className="text-ink-2">make seed</code>
        </div>
      ) : (
        <>
          {/* Ranked board (FR-305: n >= 20 required) */}
          <section aria-labelledby="ranked-heading" className="mt-10">
            <h2
              id="ranked-heading"
              className="font-serif text-2xl font-semibold text-ink"
            >
              Ranked
            </h2>
            <div className="mt-4 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
              {/* Table header */}
              <div
                className="hidden sm:grid"
                style={{ gridTemplateColumns: "40px 1fr 90px 56px 100px 80px" }}
              >
                <div className="col-span-6 grid border-b border-line bg-surface-2 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4"
                  style={{ display: "contents" }}>
                  <span className="px-4 py-2.5">#</span>
                  <span className="px-4 py-2.5">Analyst</span>
                  <span className="px-4 py-2.5">FAS</span>
                  <span className="num px-4 py-2.5 text-right">n</span>
                  <span className="px-4 py-2.5">Falsifiability</span>
                  <span className="px-4 py-2.5">90-day trend</span>
                </div>
              </div>

              {ranked.length === 0 ? (
                <div className="px-6 py-8 text-[13.5px] text-ink-3">
                  <p className="font-medium text-ink">Ranked board is empty.</p>
                  <p className="mt-1">
                    Analysts with fewer than 20 resolved claims are provisional and excluded from
                    the ranked board.
                  </p>
                </div>
              ) : (
                ranked.map((row, i) => (
                  <RankedRow key={row.slug} row={row} rank={i + 1} trendAvailable={trendAvailable} />
                ))
              )}
            </div>
          </section>

          {/* Provisional secondary section (PRD §19.1) */}
          {provisional.length > 0 && (
            <section aria-labelledby="provisional-heading" className="mt-10">
              <h2
                id="provisional-heading"
                className="font-serif text-2xl font-semibold text-ink"
              >
                Provisional
              </h2>
              <p className="mt-1 text-[13px] text-ink-3">
                Analysts with fewer than 20 resolved claims. Scores are published but these
                analysts are excluded from the ranked board (FR-305).
              </p>

              <div className="mt-4 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
                {/* Desktop header */}
                <div
                  role="rowgroup"
                  className="hidden border-b border-line bg-surface-2 sm:block"
                >
                  <div
                    className="grid px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4"
                    style={{ gridTemplateColumns: "1fr 120px 56px 100px 80px" }}
                  >
                    <span>Analyst</span>
                    <span>FAS</span>
                    <span className="num text-right">n</span>
                    <span>Falsifiability</span>
                    <span>90-day trend</span>
                  </div>
                </div>

                {provisional.map((row) => (
                  <ProvisionalRow key={row.slug} row={row} trendAvailable={trendAvailable} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function RankedRow({
  row,
  rank,
  trendAvailable,
}: {
  row: LeaderboardRow;
  rank: number;
  trendAvailable: boolean;
}) {
  return (
    <>
      {/* Desktop row */}
      <div
        className="hidden border-b border-line px-4 py-3 last:border-b-0 hover:bg-surface-2 sm:grid"
        style={{ gridTemplateColumns: "40px 1fr 90px 56px 100px 80px", alignItems: "center" }}
      >
        <span className="num font-mono text-[13px] font-semibold text-ink-3">
          {String(rank).padStart(2, "0")}
        </span>
        <Link href={`/a/${row.slug}`} className="text-[14px] font-medium text-ink hover:underline">
          {row.displayName}
        </Link>
        <div>
          <FASBadge score={row.fas} provisional={row.provisional} />
        </div>
        <span className="num text-right font-mono text-[13px] text-ink-2">{row.nResolved}</span>
        <span className="num font-mono text-[13px] text-ink-2">
          {row.falsifiability.toFixed(2)}
        </span>
        <TrendSparkline points={trendAvailable ? [] : null} />
      </div>

      {/* Mobile card */}
      <div className="border-b border-line px-4 py-3 last:border-b-0 sm:hidden">
        <div className="flex items-center justify-between gap-3">
          <span className="flex items-center gap-2">
            <span className="num font-mono text-[13px] font-semibold text-ink-3">
              {String(rank).padStart(2, "0")}
            </span>
            <Link
              href={`/a/${row.slug}`}
              className="text-[14px] font-medium text-ink hover:underline"
            >
              {row.displayName}
            </Link>
          </span>
          <FASBadge score={row.fas} provisional={row.provisional} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-[11px] text-ink-4">
          <span>n={row.nResolved}</span>
          <span>F={row.falsifiability.toFixed(2)}</span>
        </div>
      </div>
    </>
  );
}

function ProvisionalRow({
  row,
  trendAvailable,
}: {
  row: LeaderboardRow;
  trendAvailable: boolean;
}) {
  return (
    <>
      {/* Desktop row */}
      <div
        className="hidden border-b border-line px-4 py-3 last:border-b-0 hover:bg-surface-2 sm:grid"
        style={{ gridTemplateColumns: "1fr 120px 56px 100px 80px", alignItems: "center" }}
      >
        <Link
          href={`/a/${row.slug}`}
          className="text-[14px] font-medium text-ink hover:underline"
        >
          {row.displayName}
        </Link>
        <div>
          <FASBadge score={row.fas} provisional={row.provisional} />
        </div>
        <span className="num text-right font-mono text-[13px] text-ink-2">{row.nResolved}</span>
        <span className="num font-mono text-[13px] text-ink-2">
          {row.falsifiability.toFixed(2)}
        </span>
        <TrendSparkline points={trendAvailable ? [] : null} />
      </div>

      {/* Mobile card */}
      <div className="border-b border-line px-4 py-3 last:border-b-0 sm:hidden">
        <div className="flex items-center justify-between gap-3">
          <Link
            href={`/a/${row.slug}`}
            className="text-[14px] font-medium text-ink hover:underline"
          >
            {row.displayName}
          </Link>
          <FASBadge score={row.fas} provisional={row.provisional} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-[11px] text-ink-4">
          <span>n={row.nResolved}</span>
          <span>F={row.falsifiability.toFixed(2)}</span>
        </div>
      </div>
    </>
  );
}
