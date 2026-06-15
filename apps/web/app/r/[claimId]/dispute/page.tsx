/**
 * /r/[claimId]/dispute — Dispute submission page (E5-T3, FR-405, US-006, AC-5, UF-3).
 *
 * Server component. Reads via lib/db.ts only.
 *
 * Layout:
 *   - Claim header (asset, direction, analyst) from getReceipt.
 *   - Existing disputes for this claim (getDisputesForClaim) with state + SLA indicator.
 *   - DisputeForm client island for new submission.
 *
 * Copy is strictly neutral throughout (AC-7 firewall). No recommendation language.
 * Empty state states the rule honestly, never apologises, never fabricates a number.
 */


import Link from "next/link";

import { DisputeForm } from "@/components/DisputeForm";
import { getDisputesForClaim, getReceipt } from "@/lib/db";
import type { DisputeView, ReceiptData } from "@/lib/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ claimId: string }> };

export default async function DisputePage({ params }: Params) {
  const { claimId: claimIdStr } = await params;
  const claimId = Number(claimIdStr);

  if (!Number.isInteger(claimId) || claimId <= 0) {
    return <DisputeNotFound claimId={claimIdStr} />;
  }

  let receipt: ReceiptData | null = null;
  let disputes: DisputeView[] = [];

  try {
    receipt = await getReceipt(claimId);
    if (receipt !== null) {
      disputes = await getDisputesForClaim(claimId);
    }
  } catch {
    receipt = null;
  }

  if (receipt === null) {
    return <DisputeNotFound claimId={claimIdStr} />;
  }

  return (
    <div>
      {/* Page header */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-3">
          DISPUTE · {claimId}
        </span>
        <Link
          href={`/r/${claimId}`}
          className="font-mono text-[11px] text-[var(--color-brier-blue)] hover:underline"
        >
          Receipt {claimId}
        </Link>
        <Link
          href={`/a/${receipt.analystSlug}`}
          className="font-mono text-[11px] text-[var(--color-brier-blue)] hover:underline"
        >
          {receipt.analystDisplayName}
        </Link>
      </div>

      <h1 className="mt-4 font-serif text-3xl font-semibold tracking-tight text-ink">
        File a dispute
      </h1>
      <p className="mt-2 max-w-[64ch] text-[14px] leading-relaxed text-ink-3">
        Disputes are reviewed within 7 days. Provide a factual rationale citing
        the specific element of the claim or resolution that is contested.
      </p>

      {/* Claim summary */}
      <div className="mt-6 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
        <div className="border-b border-line bg-surface-2 px-5 py-3">
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Claim summary
          </span>
        </div>
        <div className="grid gap-3 px-5 py-4 sm:grid-cols-2">
          <ClaimField label="Asset" value={receipt.asset} />
          <ClaimField label="Direction" value={receipt.direction ?? "—"} />
          {receipt.horizonDeadline && (
            <ClaimField label="Horizon deadline" value={receipt.horizonDeadline} />
          )}
          <ClaimField label="Status" value={receipt.displayStatus.replace(/_/g, " ")} />
          {receipt.quote && (
            <div className="sm:col-span-2">
              <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
                Quote
              </dt>
              <dd className="mt-0.5 text-[13px] italic text-ink-3">{receipt.quote}</dd>
            </div>
          )}
        </div>
      </div>

      {/* Existing disputes */}
      {disputes.length > 0 && (
        <div className="mt-8">
          <h2 className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Existing disputes for this claim
          </h2>
          <div className="mt-3 space-y-3">
            {disputes.map((d) => (
              <DisputeStatusCard key={d.ticketCode} dispute={d} />
            ))}
          </div>
        </div>
      )}

      {/* Submission form */}
      <div className="mt-8">
        <h2 className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
          Submit a new dispute
        </h2>
        <div className="mt-3 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
          <DisputeForm claimId={claimId} />
        </div>
      </div>

      <p className="mt-6 font-mono text-[10.5px] text-ink-4">
        We publish statistics about public statements; we never recommend instruments or
        actions.{" "}
        <Link href="/methodology" className="text-[var(--color-brier-blue)] hover:underline">
          Methodology {receipt.resolutionMethodologyVersion ?? "v1.1"}
        </Link>
      </p>
    </div>
  );
}

function DisputeNotFound({ claimId }: { claimId: string }) {
  return (
    <div>
      <span className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-3">
        DISPUTE · {claimId}
      </span>
      <p className="mt-6 font-mono text-[13px] text-ink-4">
        Claim {claimId} not found or not yet publishable.
      </p>
    </div>
  );
}

function ClaimField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">{label}</dt>
      <dd className="num mt-0.5 font-mono text-[13px] text-ink-2">{value}</dd>
    </div>
  );
}

/**
 * Ticket-status card for an existing dispute.
 * Shows state, SLA deadline with days-remaining indicator, and methodology version.
 */
function DisputeStatusCard({ dispute }: { dispute: DisputeView }) {
  const slaDate = new Date(dispute.slaDeadline);
  const now = new Date();
  const msRemaining = slaDate.getTime() - now.getTime();
  const daysRemaining = Math.ceil(msRemaining / (1000 * 60 * 60 * 24));

  const isOpen = dispute.state === "open" || dispute.state === "adjudicating";
  const slaLabel =
    isOpen
      ? daysRemaining > 0
        ? `${daysRemaining} day${daysRemaining === 1 ? "" : "s"} remaining`
        : "SLA elapsed"
      : "Adjudicated";

  return (
    <div className="overflow-hidden rounded-[6px] border border-line-2 bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-4 py-2.5">
        <span className="font-mono text-[11px] font-medium text-ink-2">
          {dispute.ticketCode}
        </span>
        <StateChip state={dispute.state} />
        <span className="ml-auto font-mono text-[10.5px] text-ink-4">{slaLabel}</span>
      </div>
      <div className="grid gap-2 px-4 py-3 sm:grid-cols-2">
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Submitted
          </dt>
          <dd className="num mt-0.5 font-mono text-[12px] text-ink-3">
            {dispute.submittedAt.slice(0, 10)}
          </dd>
        </div>
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            SLA deadline
          </dt>
          <dd className="num mt-0.5 font-mono text-[12px] text-ink-3">
            {dispute.slaDeadline.slice(0, 10)}
          </dd>
        </div>
        {dispute.adjudicatedAt && (
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
              Adjudicated
            </dt>
            <dd className="num mt-0.5 font-mono text-[12px] text-ink-3">
              {dispute.adjudicatedAt.slice(0, 10)}
            </dd>
          </div>
        )}
        {dispute.methodologyVersionAtPublication && (
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
              Methodology at submission
            </dt>
            <dd className="num mt-0.5 font-mono text-[12px] text-ink-3">
              {dispute.methodologyVersionAtPublication}
            </dd>
          </div>
        )}
      </div>
    </div>
  );
}

/** Neutral state chip for a dispute ticket. */
function StateChip({ state }: { state: string }) {
  const label = state.charAt(0).toUpperCase() + state.slice(1);
  return (
    <span className="rounded-[3px] border border-line-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
      {label}
    </span>
  );
}
