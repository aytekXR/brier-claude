type TrendSparklineProps = {
  /** 90-day FAS series, oldest first (FR-401). Null until the ledger has history. */
  points: number[] | null;
};

/**
 * 90-day trend sparkline for leaderboard rows: one ink-weight line, no axes,
 * no fill (BRANDKIT §5 chart principles).
 */
// TASK: E1-T5 — render the series as a single polyline in the FAS band color.
export function TrendSparkline({ points }: TrendSparklineProps) {
  if (points === null || points.length === 0) {
    return <span className="font-mono text-[12px] text-ink-4">—</span>;
  }
  // No fabricated trend lines: real rendering arrives with the ledger (E1-T5).
  return <span className="font-mono text-[12px] text-ink-4">n={points.length}</span>;
}
