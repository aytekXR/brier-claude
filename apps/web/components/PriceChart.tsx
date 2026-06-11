type PricePoint = { day: string; closeUsd: number };

type PriceChartProps = {
  /** Daily closes from t0 to resolution; null until claim data exists. */
  series: PricePoint[] | null;
  /** Three canonical markers (BRANDKIT §5). */
  utteranceDay?: string;
  targetPrice?: number;
  resolutionDay?: string;
};

/**
 * Price chart from utterance to resolution (FR-403, US-004), built on
 * TradingView Lightweight Charts. One ink line; utterance = blue dot,
 * target = dashed ochre line, resolution = band-colored dot. No gradients,
 * no dual axes (BRANDKIT §5).
 */
// TASK: E1-T5 — client-component wrapper around lightweight-charts (already a
// dependency) fed by the read layer; markers per the brand chart conventions.
export function PriceChart({ series }: PriceChartProps) {
  return (
    <div className="flex min-h-[120px] items-center justify-center rounded-[3px] border border-line-2 bg-surface-2">
      <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-4">
        {series === null ? "price chart placeholder · t0 → resolution" : `${series.length} closes`}
      </span>
    </div>
  );
}
