import type { DisplayStatus } from "@/lib/types";

const STATUS_LABELS: Record<DisplayStatus, string> = {
  hit: "Hit",
  miss: "Miss",
  partial: "Partial",
  open: "Open",
  void: "Void",
  non_falsifiable: "Non-falsifiable",
};

/** Color variable name for each display status. non_falsifiable uses void tone (neutral). */
const STATUS_COLOR: Record<DisplayStatus, string> = {
  hit: "var(--color-hit)",
  miss: "var(--color-miss)",
  partial: "var(--color-partial)",
  open: "var(--color-open)",
  void: "var(--color-void)",
  non_falsifiable: "var(--color-void)",
};

/**
 * Claim-status chip: muted and bordered, a ledger annotation, not an alarm
 * (BRANDKIT §1). Status colors come from the brand tokens in globals.css.
 *
 * non_falsifiable is rendered with void tone — neutral, not a miss.
 */
export function ClaimStatusChip({ status }: { status: DisplayStatus }) {
  const color = STATUS_COLOR[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em]"
      style={{
        color,
        borderColor: "var(--color-line-2)",
        background: "var(--color-surface)",
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {STATUS_LABELS[status]}
    </span>
  );
}
