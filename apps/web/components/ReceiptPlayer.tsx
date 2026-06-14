type ReceiptPlayerProps = {
  /** YouTube video id; playback is official embeds only (NFR-4). */
  videoId: string | null;
  /** Claim offset in seconds; the player seeks here within 3s (AC-2). */
  offsetSeconds: number | null;
};

/**
 * Receipt player: official YouTube IFrame embed auto-seeked to the claim
 * offset (FR-403). No hosted copies, ever. Seek marker pulses once (BRANDKIT §6).
 *
 * The seek target is shown as metadata so the viewer knows where to look
 * in the source video.
 */
// TASK: E5-T1 — real IFrame embed with start offset, deletion flag overlay (EC-1, AC-6).
export function ReceiptPlayer({ videoId, offsetSeconds }: ReceiptPlayerProps) {
  return (
    <div className="flex min-h-[96px] flex-col items-center justify-center gap-1.5 border-y border-line-2 bg-surface-2 py-4">
      <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-4">
        {videoId === null
          ? "official player placeholder"
          : `official player · seeked to ${formatOffset(offsetSeconds ?? 0)}`}
      </span>
      {videoId !== null && (
        <span className="font-mono text-[10px] text-ink-4">
          video {videoId} · official embed not yet enabled
        </span>
      )}
    </div>
  );
}

function formatOffset(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
