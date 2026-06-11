import Link from "next/link";

import { listAnalysts } from "@/lib/db";
import type { AnalystRow } from "@/lib/types";

// The leaderboard reads live data; never prerender a stale board at build time.
export const dynamic = "force-dynamic";

export default async function LeaderboardPage() {
  let analysts: AnalystRow[] | null = null;
  try {
    analysts = await listAnalysts();
  } catch {
    analysts = null; // dev database not running; say so honestly below
  }

  return (
    <div>
      <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">Leaderboard</h1>
      <p className="mt-3 max-w-[62ch] text-[15px] leading-relaxed text-ink-3">
        Ranked accuracy scores for crypto YouTube analysts: base-rate-corrected,
        calibration-aware, and backed by a receipt for every resolved claim.
      </p>

      <div className="mt-8 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
        <div className="grid grid-cols-[34px_1fr_64px_48px_110px] gap-3 border-b border-line bg-surface-2 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
          <span>#</span>
          <span>Analyst</span>
          <span>FAS</span>
          <span className="num text-right">n</span>
          <span>Falsifiability</span>
        </div>

        {analysts === null ? (
          <EmptyRow>
            Registry unavailable. Start the dev database and seed it: <Mono>make seed</Mono>
          </EmptyRow>
        ) : analysts.length === 0 ? (
          <EmptyRow>
            No analysts in the registry yet. Seed the fixtures: <Mono>make seed</Mono>
          </EmptyRow>
        ) : (
          analysts.map((analyst, index) => (
            <div
              key={analyst.slug}
              className="grid grid-cols-[34px_1fr_64px_48px_110px] items-center gap-3 border-b border-line px-4 py-3 last:border-b-0 hover:bg-surface-2"
            >
              <span className="font-mono text-[13px] font-semibold text-ink-3">
                {String(index + 1).padStart(2, "0")}
              </span>
              <Link href={`/a/${analyst.slug}`} className="text-[14px] font-medium text-ink hover:underline">
                {analyst.display_name}
              </Link>
              {/* No fabricated numbers: scores render only once the ledger has rows (E1). */}
              <span className="font-mono text-[13px] text-ink-4">—</span>
              <span className="num text-right font-mono text-[13px] text-ink-4">—</span>
              <span className="font-mono text-[12px] text-ink-4">—</span>
            </div>
          ))
        )}
      </div>

      <p className="mt-4 font-mono text-[10.5px] text-ink-4">
        Scores publish when the scoring engine lands (TASKS.md, epic E1). Analysts with fewer than
        20 resolved claims are provisional and excluded from the ranked board.
      </p>
    </div>
  );
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-8 text-center text-[13.5px] text-ink-3">{children}</div>;
}

function Mono({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-[12px] text-ink-2">{children}</code>;
}
