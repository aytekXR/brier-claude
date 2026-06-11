import { PriceChart } from "@/components/PriceChart";
import { ReceiptPlayer } from "@/components/ReceiptPlayer";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ claimId: string }> };

/**
 * The receipt — the viral unit (PRD §19.3). Skeleton shell: claim card,
 * player, and chart render real data when E1-T5 and E5-T1 land.
 */
export default async function ReceiptPage({ params }: Params) {
  const { claimId } = await params;

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="rounded-[3px] border border-line-2 bg-surface px-2 py-1 font-mono text-[11px] text-ink-3">
          RECEIPT · {claimId}
        </span>
      </div>

      <div className="mt-6 overflow-hidden rounded-[6px] border border-line-2 bg-surface">
        <div className="border-b border-line px-5 py-4">
          <div className="font-mono text-[13px] text-ink-4">
            Claim record pending. Structured claims publish with the walking-skeleton slice
            (TASKS.md, epic E1); each receipt then shows asset, direction or target, horizon, and a
            verbatim quote of at most 15 words.
          </div>
        </div>
        <ReceiptPlayer videoId={null} offsetSeconds={null} />
        <div className="px-5 py-4">
          <PriceChart series={null} />
          <p className="mt-3 font-mono text-[10.5px] text-ink-4">
            Resolution rationale and the daily-UTC-close citation render here once the resolution
            engine lands (E1-T3).
          </p>
        </div>
      </div>
    </div>
  );
}
