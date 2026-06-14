"use client";

import Link from "next/link";
import { useState } from "react";

import { ClaimStatusChip } from "@/components/ClaimStatusChip";
import type { AnalystClaimRow, DisplayStatus } from "@/lib/types";

/**
 * The core surface: filterable claim table with hairline rows and
 * tabular numerals (FR-402, BRANDKIT §3). Collapses to stacked cards under
 * 640px per PRD §19. Each row links its receipt (/r/[claimId]).
 *
 * Filters: asset dropdown + status dropdown, client-side.
 * Non-falsifiable rows show a neutral indicator, not a hit/miss chip.
 */
export function ClaimTable({ claims }: { claims: AnalystClaimRow[] }) {
  const [assetFilter, setAssetFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const assets = Array.from(new Set(claims.map((c) => c.asset))).sort();
  const statuses: { value: string; label: string }[] = [
    { value: "all", label: "All statuses" },
    { value: "hit", label: "Hit" },
    { value: "miss", label: "Miss" },
    { value: "partial", label: "Partial" },
    { value: "open", label: "Open" },
    { value: "void", label: "Void" },
    { value: "non_falsifiable", label: "Non-falsifiable" },
  ];

  const filtered = claims.filter((c) => {
    if (assetFilter !== "all" && c.asset !== assetFilter) return false;
    if (statusFilter !== "all" && c.displayStatus !== statusFilter) return false;
    return true;
  });

  return (
    <div className="overflow-hidden rounded-[6px] border border-line-2 bg-surface">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-3.5 py-2.5">
        <select
          value={assetFilter}
          onChange={(e) => setAssetFilter(e.target.value)}
          className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-2 focus:outline-none focus:ring-2 focus:ring-[var(--color-brier-blue)]"
          aria-label="Filter by asset"
        >
          <option value="all">All assets</option>
          {assets.map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-2 focus:outline-none focus:ring-2 focus:ring-[var(--color-brier-blue)]"
          aria-label="Filter by status"
        >
          {statuses.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {(assetFilter !== "all" || statusFilter !== "all") && (
          <span className="font-mono text-[10.5px] text-ink-4">
            {filtered.length} of {claims.length}
          </span>
        )}
      </div>

      {/* Desktop table — hidden below 640px */}
      <table className="hidden w-full text-[14px] sm:table">
        <thead>
          <tr className="border-b border-line text-left font-mono text-[10.5px] uppercase tracking-[0.12em] text-ink-4">
            <th className="px-3.5 py-2.5 font-medium">Claim</th>
            <th className="px-3.5 py-2.5 font-medium">Asset</th>
            <th className="px-3.5 py-2.5 font-medium">Horizon</th>
            <th className="num px-3.5 py-2.5 text-right font-medium">Conf.</th>
            <th className="px-3.5 py-2.5 font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {filtered.length === 0 ? (
            <tr>
              <td colSpan={5} className="px-3.5 py-8 text-center text-[13.5px] text-ink-3">
                No claims match the current filters.
              </td>
            </tr>
          ) : (
            filtered.map((claim) => (
              <ClaimTableRow key={claim.id} claim={claim} />
            ))
          )}
        </tbody>
      </table>

      {/* Mobile stacked cards — shown below 640px */}
      <div className="sm:hidden">
        {filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-[13.5px] text-ink-3">
            No claims match the current filters.
          </div>
        ) : (
          filtered.map((claim) => <ClaimCard key={claim.id} claim={claim} />)
        )}
      </div>
    </div>
  );
}

function horizonLabel(claim: AnalystClaimRow): string {
  if (claim.horizonDeadline) {
    const d = claim.horizonDeadline.slice(0, 10);
    const basis = claim.horizonBasis === "stated" ? "" : ` (${claim.horizonBasis ?? ""})`;
    return `${d}${basis}`;
  }
  return claim.horizonBasis ?? "—";
}

function quoteLabel(claim: AnalystClaimRow): string {
  if (claim.quote) return claim.quote;
  // fallback: direction + asset
  const dir = claim.direction ?? "";
  return `${dir} ${claim.asset}`.trim();
}

function ClaimTableRow({ claim }: { claim: AnalystClaimRow }) {
  return (
    <tr className="border-b border-line last:border-b-0 hover:bg-surface-2">
      <td className="px-3.5 py-3">
        <Link
          href={`/r/${claim.id}`}
          className="text-[13px] text-ink hover:text-[var(--color-brier-blue)] hover:underline"
        >
          {quoteLabel(claim)}
        </Link>
      </td>
      <td className="px-3.5 py-3 font-mono text-[12px] text-ink-2">{claim.asset}</td>
      <td className="px-3.5 py-3 font-mono text-[12px] text-ink-3">{horizonLabel(claim)}</td>
      <td className="num px-3.5 py-3 text-right font-mono text-[12px] text-ink-3">
        {claim.statedConfidence != null ? claim.statedConfidence.toFixed(2) : "—"}
      </td>
      <td className="px-3.5 py-3">
        <ClaimStatusChip status={claim.displayStatus as DisplayStatus} />
      </td>
    </tr>
  );
}

function ClaimCard({ claim }: { claim: AnalystClaimRow }) {
  return (
    <div className="border-b border-line px-4 py-3 last:border-b-0">
      <div className="flex items-start justify-between gap-2">
        <Link
          href={`/r/${claim.id}`}
          className="text-[13px] font-medium text-ink hover:text-[var(--color-brier-blue)] hover:underline"
        >
          {quoteLabel(claim)}
        </Link>
        <ClaimStatusChip status={claim.displayStatus as DisplayStatus} />
      </div>
      <div className="mt-2 flex flex-wrap gap-3 font-mono text-[11px] text-ink-4">
        <span>{claim.asset}</span>
        <span>{horizonLabel(claim)}</span>
        {claim.statedConfidence != null && (
          <span>conf. {claim.statedConfidence.toFixed(2)}</span>
        )}
      </div>
    </div>
  );
}
