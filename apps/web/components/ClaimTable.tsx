import { ClaimStatusChip } from "@/components/ClaimStatusChip";
import type { ClaimRow } from "@/lib/types";

/**
 * The core surface: sortable, filterable claim table with hairline rows and
 * tabular numerals (FR-402, BRANDKIT §3). Collapses to stacked cards under
 * 640px per PRD §19.
 */
// TASK: E1-T5 — real rows from the read layer; asset/status/date filters;
// each row links its receipt (/r/[claimId]). E5 adds keyboard navigation polish.
export function ClaimTable({ claims }: { claims: ClaimRow[] }) {
  return (
    <div className="overflow-hidden rounded-[6px] border border-line-2 bg-surface">
      <table className="w-full text-[14px]">
        <thead>
          <tr className="border-b border-line-strong text-left font-mono text-[10.5px] uppercase tracking-[0.12em] text-ink-4">
            <th className="px-3.5 py-2.5 font-medium">Claim</th>
            <th className="px-3.5 py-2.5 font-medium">Asset</th>
            <th className="px-3.5 py-2.5 font-medium">Horizon</th>
            <th className="num px-3.5 py-2.5 text-right font-medium">Conf.</th>
            <th className="px-3.5 py-2.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {claims.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-3.5 py-8 text-center text-[13.5px] text-ink-3">
                No claims on record. Claims publish once extraction and resolution land
                (TASKS.md, epics E1 and E3).
              </td>
            </tr>
          ) : (
            claims.map((claim) => (
              <tr key={claim.id} className="border-b border-line last:border-b-0 hover:bg-surface-2">
                <td className="px-3.5 py-3">{claim.summary}</td>
                <td className="px-3.5 py-3 font-mono text-[12px]">{claim.asset}</td>
                <td className="px-3.5 py-3">{claim.horizonLabel}</td>
                <td className="num px-3.5 py-3 text-right font-mono text-[12px]">
                  {claim.confidence ?? "—"}
                </td>
                <td className="px-3.5 py-3">
                  <ClaimStatusChip status={claim.status} />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
