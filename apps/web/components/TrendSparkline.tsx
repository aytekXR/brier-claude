type TrendSparklineProps = {
  /** 90-day FAS series, oldest first (FR-401). Null until the ledger has history. */
  points: number[] | null;
};

/**
 * 90-day trend sparkline for leaderboard rows: one ink-weight line, no axes,
 * no fill (BRANDKIT §5 chart principles).
 *
 * Renders the polyline when the analyst has >= 2 distinct scoring dates
 * (AC-3 — real points are wired through getLeaderboard); fewer points render
 * the honest insufficient state. No fabricated sparkline, ever.
 */
export function TrendSparkline({ points }: TrendSparklineProps) {
  // `!points` (not `=== null`) also tolerates a row deserialized from an older
  // cache shape that predates the `trend` field (undefined at that boundary).
  if (!points || points.length < 2) {
    return (
      <span
        className="font-mono text-[11px] text-ink-4"
        title="Trend requires at least two scoring dates"
      >
        —
      </span>
    );
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const W = 64;
  const H = 20;
  const pts = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * W;
      const y = H - ((v - min) / range) * H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      aria-label="90-day FAS trend"
      className="overflow-visible"
    >
      <polyline
        points={pts}
        fill="none"
        stroke="var(--color-ink-3)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
