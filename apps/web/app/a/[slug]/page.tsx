import { ClaimTable } from "@/components/ClaimTable";
import { listAnalysts } from "@/lib/db";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ slug: string }> };

export default async function AnalystPage({ params }: Params) {
  const { slug } = await params;

  let displayName: string | null = null;
  try {
    const analysts = await listAnalysts();
    displayName = analysts.find((a) => a.slug === slug)?.display_name ?? null;
  } catch {
    displayName = null;
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-6">
        <div>
          <h1 className="font-serif text-4xl font-semibold tracking-tight text-ink">
            {displayName ?? slug}
          </h1>
          <p className="mt-2 font-mono text-[11px] text-ink-4">
            {displayName === null
              ? "Not found in the registry."
              : "No resolved claims on record yet."}
          </p>
        </div>
        {/* FASBadge renders here once the score ledger has rows (E1-T5). */}
      </div>

      <div className="mt-10 rounded-[6px] border border-dashed border-line-2 bg-surface-2 px-8 py-9 text-center">
        <div className="text-[15px] font-semibold text-ink">Not enough resolved claims yet</div>
        <p className="mx-auto mt-2 max-w-[42ch] text-[13.5px] leading-relaxed text-ink-3">
          This analyst is <strong className="text-ink">provisional</strong> (n &lt; 20). We do not
          rank a record we cannot defend. Check back as claims resolve.
        </p>
      </div>

      <h2 className="mt-12 font-serif text-2xl font-semibold text-ink">Claims</h2>
      <div className="mt-4">
        <ClaimTable claims={[]} />
      </div>
    </div>
  );
}
