import Link from "next/link";

import { ClaimStatusChip } from "@/components/ClaimStatusChip";
import { PriceChart } from "@/components/PriceChart";
import { ReceiptPlayer } from "@/components/ReceiptPlayer";
import { getReceipt, getPriceSeries } from "@/lib/db";
import type { PricePoint } from "@/lib/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ claimId: string }> };

/**
 * The receipt — the viral unit (PRD §19.3, FR-403).
 *
 * Claim card: structured fields + verbatim quote (<=15 words).
 * ReceiptPlayer: honest placeholder (real embed = E5-T1).
 * PriceChart: real lightweight-charts chart, t0 -> resolution.
 * Resolution block: rationale + rule_id + price citation in mono.
 * EC-1: source deletion flag if video.source_status != 'live'.
 */
export default async function ReceiptPage({ params }: Params) {
  const { claimId: claimIdStr } = await params;
  const claimId = Number(claimIdStr);

  if (!Number.isInteger(claimId) || claimId <= 0) {
    return <NotFound claimId={claimIdStr} />;
  }

  let receipt = null;
  let series: PricePoint[] = [];

  try {
    receipt = await getReceipt(claimId);

    if (receipt) {
      // Compute the price series window: t0 to resolution day (or horizon deadline)
      const startDate = receipt.utteredAt.slice(0, 10);
      let endDate: string;
      if (receipt.resolutionResolvedAt) {
        // Use the resolution price citation day as end
        endDate = receipt.resolutionPriceCitation?.day ?? receipt.resolutionResolvedAt.slice(0, 10);
      } else if (receipt.horizonDeadline) {
        endDate = receipt.horizonDeadline;
      } else {
        // Default: 90 days from utterance
        const t0 = new Date(startDate);
        t0.setDate(t0.getDate() + 90);
        endDate = t0.toISOString().slice(0, 10);
      }
      series = await getPriceSeries(receipt.asset, startDate, endDate);
    }
  } catch {
    receipt = null;
    series = [];
  }

  if (receipt === null) {
    return <NotFound claimId={claimIdStr} />;
  }

  // Build chart markers
  const utteranceDay = receipt.utteredAt.slice(0, 10);
  const markers = [
    { day: utteranceDay, type: "utterance" as const },
    ...(receipt.targetPrice != null
      ? [{ day: utteranceDay, type: "target" as const, targetPrice: receipt.targetPrice }]
      : []),
    ...(receipt.resolutionPriceCitation
      ? [
          {
            day: receipt.resolutionPriceCitation.day,
            type: "resolution" as const,
            outcome: receipt.resolutionOutcome ?? undefined,
          },
        ]
      : []),
  ];

  const isDeletedSource = receipt.videoSourceStatus !== "live";

  return (
    <div>
      {/* Receipt header */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-3">
          RECEIPT · {claimId}
        </span>
        <ClaimStatusChip status={receipt.displayStatus} />
        <Link
          href={`/a/${receipt.analystSlug}`}
          className="font-mono text-[12px] text-[var(--color-brier-blue)] hover:underline"
        >
          {receipt.analystDisplayName}
        </Link>
      </div>

      {/* EC-1: Deleted source flag */}
      {isDeletedSource && (
        <div className="mt-4 rounded-[3px] border border-line-2 bg-surface-2 px-4 py-3 font-mono text-[12px] text-ink-3">
          Source video status: <span className="font-medium text-ink">{receipt.videoSourceStatus}</span>.
          The claim and resolution remain on the record (EC-1).
        </div>
      )}

      {/* Claim card */}
      <div className="mt-6 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
        <div className="border-b border-line px-5 py-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Claim
          </div>
          {receipt.quote && (
            <blockquote className="mt-2 border-l-2 border-[var(--color-brier-blue)] pl-3 text-[14px] italic text-ink-2">
              {receipt.quote}
            </blockquote>
          )}

          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <ClaimField label="Asset" value={receipt.asset} mono />
            <ClaimField
              label="Direction"
              value={receipt.direction ?? "—"}
              mono
            />
            {receipt.targetPrice != null && (
              <ClaimField
                label="Target price"
                value={`$${receipt.targetPrice.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                mono
              />
            )}
            {receipt.magnitudePct != null && (
              <ClaimField
                label="Magnitude"
                value={`${receipt.magnitudePct.toFixed(1)}%`}
                mono
              />
            )}
            {receipt.horizonDeadline && (
              <ClaimField
                label="Horizon deadline"
                value={receipt.horizonDeadline}
                mono
              />
            )}
            <ClaimField
              label="Horizon basis"
              value={receipt.horizonBasis ?? "—"}
              mono
            />
            <ClaimField
              label="Stated confidence"
              value={
                receipt.statedConfidence != null
                  ? `${receipt.statedConfidence.toFixed(2)} (${receipt.confidenceBasis ?? "stated"})`
                  : "—"
              }
              mono
            />
            <ClaimField
              label="Specificity class"
              value={receipt.specificityClass.replace(/_/g, " ")}
              mono
            />
            <ClaimField
              label="Uttered at"
              value={receipt.utteredAt.slice(0, 10)}
              mono
            />
            {receipt.p0Price != null && (
              <ClaimField
                label="Price at utterance (p0)"
                value={`$${receipt.p0Price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                mono
              />
            )}
          </div>
        </div>

        {/* Source video metadata */}
        <div className="border-b border-line px-5 py-3 font-mono text-[11px] text-ink-4">
          <span className="font-medium text-ink-3">Source:</span>{" "}
          {receipt.videoTitle} · published {receipt.videoPublishedAt.slice(0, 10)} · offset{" "}
          {formatOffset(receipt.sourceOffsetSeconds)}
          {isDeletedSource && (
            <span className="ml-2 text-[var(--color-void)]">
              [{receipt.videoSourceStatus}]
            </span>
          )}
        </div>

        {/* Player placeholder (E5-T1) */}
        <ReceiptPlayer
          videoId={receipt.videoYoutubeId}
          offsetSeconds={receipt.sourceOffsetSeconds}
        />

        {/* Price chart */}
        <div className="px-5 py-5">
          <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Price chart — {receipt.asset} · t0 ({utteranceDay}) to{" "}
            {receipt.resolutionPriceCitation?.day ?? receipt.horizonDeadline ?? "latest"}
          </div>
          <div className="mt-3">
            <PriceChart series={series.length > 0 ? series : null} markers={markers} />
          </div>
          {series.length === 0 && (
            <p className="mt-2 font-mono text-[10.5px] text-ink-4">
              Price data for {receipt.asset} in this window is not yet in the ledger.
            </p>
          )}
        </div>

        {/* Resolution block */}
        <div className="border-t border-line px-5 py-5">
          <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
            Resolution
          </div>
          {receipt.resolutionRationale ? (
            <div className="mt-3 space-y-3">
              <p className="text-[13.5px] text-ink-2">{receipt.resolutionRationale}</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <ClaimField label="Rule" value={receipt.resolutionRuleId ?? "—"} mono />
                <ClaimField
                  label="Resolved at"
                  value={receipt.resolutionResolvedAt?.slice(0, 10) ?? "—"}
                  mono
                />
                <ClaimField
                  label="Methodology"
                  value={receipt.resolutionMethodologyVersion ?? "—"}
                  mono
                />
              </div>
              {receipt.resolutionPriceCitation && (
                <div className="rounded-[3px] border border-line-2 bg-surface-2 px-4 py-3">
                  <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">
                    Price citation
                  </div>
                  <div className="mt-2 grid gap-1 sm:grid-cols-2">
                    <ClaimField
                      label="Asset"
                      value={receipt.resolutionPriceCitation.asset}
                      mono
                    />
                    <ClaimField
                      label="Day (UTC close)"
                      value={receipt.resolutionPriceCitation.day}
                      mono
                    />
                    <ClaimField
                      label="Close (USD)"
                      value={`$${receipt.resolutionPriceCitation.close_usd.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                      mono
                    />
                    <ClaimField
                      label="Source"
                      value={receipt.resolutionPriceCitation.source}
                      mono
                    />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="mt-3 font-mono text-[12px] text-ink-4">
              This claim is open. Resolution records when the outcome is determined.
            </p>
          )}
        </div>
      </div>

      <p className="mt-6 font-mono text-[10.5px] text-ink-4">
        We publish statistics about public statements; we never recommend instruments or
        actions.{" "}
        <Link href="/methodology" className="text-[var(--color-brier-blue)] hover:underline">
          Methodology {receipt.resolutionMethodologyVersion ?? "v1.0"}
        </Link>
      </p>
    </div>
  );
}

function NotFound({ claimId }: { claimId: string }) {
  return (
    <div>
      <span className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-3">
        RECEIPT · {claimId}
      </span>
      <p className="mt-6 font-mono text-[13px] text-ink-4">
        Claim {claimId} not found or not yet publishable.
      </p>
    </div>
  );
}

function ClaimField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-4">{label}</dt>
      <dd className={`mt-0.5 text-[13px] text-ink-2 ${mono ? "num font-mono" : ""}`}>
        {value}
      </dd>
    </div>
  );
}

function formatOffset(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
