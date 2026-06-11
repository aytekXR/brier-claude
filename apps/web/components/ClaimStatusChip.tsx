import type { ClaimStatus } from "@/lib/types";

const STATUS_LABELS: Record<ClaimStatus, string> = {
  hit: "Hit",
  miss: "Miss",
  partial: "Partial",
  open: "Open",
  void: "Void",
};

/**
 * Claim-status chip: muted and bordered, a ledger annotation, not an alarm
 * (BRANDKIT §1). Status colors come from the brand tokens in globals.css.
 */
// TASK: E1-T5 — used by ClaimTable and receipts once claims render.
export function ClaimStatusChip({ status }: { status: ClaimStatus }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em]"
      style={{
        color: `var(--color-${status})`,
        borderColor: "var(--color-line-2)",
        background: "var(--color-surface)",
      }}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {STATUS_LABELS[status]}
    </span>
  );
}
