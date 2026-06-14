import { FAS_BANDS } from "@/lib/types";

type FASBadgeProps = {
  /** Falsifiable Accuracy Score, 0–100, from the score ledger. */
  score: number;
  /** Two-tier provisional flag (METHODOLOGY.md §6). */
  provisional?: boolean;
  size?: "sm" | "lg";
};

/**
 * FAS badge: score in band color with band label (BRANDKIT §1). Band colors
 * appear only here and on chart annotations — never as decoration.
 *
 * PROVISIONAL is rendered as a separate neutral mono tag (void tone), never
 * recoloring the whole badge. The FAS score always shows in its band color
 * because band color is information about the score.
 *
 * Display: score to 1 decimal (toFixed(1)) per AC-3 display rounding.
 */
export function FASBadge({ score, provisional = false, size = "sm" }: FASBadgeProps) {
  const band = FAS_BANDS.find((b) => score >= b.min) ?? FAS_BANDS[FAS_BANDS.length - 1]!;

  if (size === "lg") {
    return (
      <div className="flex flex-col items-start gap-1">
        <span
          className="inline-flex h-[74px] w-[82px] flex-col items-center justify-center rounded-[6px] font-mono text-white"
          style={{ background: band.cssVar }}
          title={band.label}
        >
          <span className="num font-semibold text-[27px]">{score.toFixed(1)}</span>
          <span className="mt-0.5 text-[8.5px] uppercase tracking-[0.12em] opacity-85">
            {band.label}
          </span>
        </span>
        {provisional && (
          <span
            className="inline-block rounded-[3px] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[0.12em]"
            style={{ background: "var(--color-surface-2)", color: "var(--color-void)", border: "1px solid var(--color-line-2)" }}
          >
            Provisional
          </span>
        )}
      </div>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className="inline-flex h-[26px] min-w-[46px] flex-col items-center justify-center rounded-[3px] px-1.5 font-mono text-white"
        style={{ background: band.cssVar }}
        title={provisional ? `${band.label} · provisional` : band.label}
      >
        <span className="num font-semibold text-[13px]">{score.toFixed(1)}</span>
      </span>
      {provisional && (
        <span
          className="inline-block rounded-[3px] px-1 py-0.5 font-mono text-[9px] uppercase tracking-[0.1em]"
          style={{ color: "var(--color-void)", border: "1px solid var(--color-line-2)" }}
        >
          Prov.
        </span>
      )}
    </span>
  );
}
