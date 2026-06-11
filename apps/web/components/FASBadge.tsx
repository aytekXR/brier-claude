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
 * The band mapping below is a presentation token (display ranges from
 * docs/BRANDKIT.md), not scoring logic; scores arrive computed from the ledger.
 */
// TASK: E1-T5 — render real ledger scores; sm variant in leaderboard rows,
// lg variant on analyst headers; provisional tag per the two-tier rule.
export function FASBadge({ score, provisional = false, size = "sm" }: FASBadgeProps) {
  const band = FAS_BANDS.find((b) => score >= b.min) ?? FAS_BANDS[FAS_BANDS.length - 1]!;
  const dim = size === "lg" ? "h-[74px] w-[74px]" : "h-[30px] w-[46px]";

  return (
    <span
      className={`inline-flex ${dim} flex-col items-center justify-center rounded-[6px] font-mono text-white`}
      style={{ background: provisional ? "var(--color-void)" : band.cssVar }}
      title={provisional ? `${band.label} · provisional` : band.label}
    >
      <span className={`num font-semibold ${size === "lg" ? "text-[27px]" : "text-[15px]"}`}>
        {Math.round(score)}
      </span>
      {size === "lg" && (
        <span className="mt-0.5 text-[8.5px] uppercase tracking-[0.12em] opacity-85">
          {provisional ? "Provisional" : band.label}
        </span>
      )}
    </span>
  );
}
