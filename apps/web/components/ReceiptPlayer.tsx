"use client";

/**
 * Receipt player: official YouTube IFrame embed auto-seeked to the claim
 * offset (FR-403, AC-2, NFR-4). No hosted copies, ever.
 *
 * AC-2 COMPLIANCE — "player starts within 3 seconds of the claim offset":
 *   The IFrame is NOT mounted until the user clicks the facade. On first
 *   render (SSR + hydration) only a lightweight facade is shown: a decorative
 *   CSS background thumbnail (no fetch cost) + a play affordance + the offset label.
 *   When the user clicks (or presses Enter/Space), the IFrame mounts with
 *   start=<offsetSeconds>&autoplay=1 so YouTube begins playing at the claim
 *   offset immediately. Because the IFrame is deferred until click, the
 *   initial interaction cost is the thumbnail image only (~20 KB), well
 *   within the 3s budget on any reasonable connection.
 *
 * NFR-4: official YouTube embeds only. The IFrame src is always
 *   https://www.youtube.com/embed/<videoId> — Brier never hosts or proxies
 *   video content.
 *
 * AC-6 / EC-1 — Deletion overlay: when videoSourceStatus !== "live", no
 *   play affordance is rendered and the IFrame is never attempted. A neutral
 *   status overlay informs the viewer that the source is unavailable while
 *   making clear that the claim and resolution remain on the record (NFR-3).
 *
 * No new dependencies: native <iframe> + CSS background-image. No react-youtube,
 *   no lite-youtube-embed, no next/image, no package.json changes.
 */

import { useCallback, useState } from "react";

type ReceiptPlayerProps = {
  /** YouTube video id; playback is official embeds only (NFR-4). */
  videoId: string | null;
  /** Claim offset in seconds; the player seeks here (AC-2). */
  offsetSeconds: number | null;
  /**
   * Source video status from the DB. When !== "live" the embed is suppressed
   * and a deletion overlay is rendered instead (AC-6, EC-1).
   */
  sourceStatus: string;
};

function formatOffset(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function ReceiptPlayer({
  videoId,
  offsetSeconds,
  sourceStatus,
}: ReceiptPlayerProps) {
  const [playing, setPlaying] = useState(false);

  const isLive = sourceStatus === "live";
  const offset = offsetSeconds ?? 0;
  const offsetLabel = formatOffset(offset);

  const activate = useCallback(() => {
    if (isLive && videoId !== null) {
      setPlaying(true);
    }
  }, [isLive, videoId]);

  // A native <button> already fires onClick for Enter and Space (and Space does
  // not scroll on a button), so no onKeyDown handler is needed — adding one
  // would double-activate. Keyboard operability is native.

  // ── No videoId: bare placeholder ────────────────────────────────────────
  if (videoId === null) {
    return (
      <div className="flex min-h-[96px] flex-col items-center justify-center gap-1.5 border-y border-line-2 bg-surface-2 py-4">
        <span className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-4">
          No source video recorded for this claim.
        </span>
      </div>
    );
  }

  // ── AC-6 / EC-1: source unavailable — no embed attempted ─────────────────
  if (!isLive) {
    return (
      <div className="border-y border-line-2 bg-surface-2 px-5 py-5">
        <div className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-4">
          Source video
        </div>
        <p className="mt-2 font-mono text-[12px] text-ink-3">
          Source video unavailable — marked{" "}
          <span className="font-medium text-ink">{sourceStatus}</span>. The
          claim and resolution remain on the record.
        </p>
        <p className="mt-1 font-mono text-[11px] text-ink-4">
          Video ID: {videoId} · offset {offsetLabel}
        </p>
      </div>
    );
  }

  // ── AC-2 facade → IFrame ──────────────────────────────────────────────────
  //
  // Facade is shown until the user clicks. On click the IFrame mounts with
  // autoplay=1&start=<offset> so playback begins at the claim offset.
  // The IFrame is never loaded during SSR, build, or CI (no network cost).
  //
  // The thumbnail is a decorative CSS background-image on a <div> — no
  // <img> element, no next/image, no eslint suppression needed. The facade
  // button carries an aria-label describing the seek target; the thumbnail
  // background is purely decorative (aria-hidden via background, no alt text
  // needed).
  const thumbnailUrl = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;
  const embedSrc = `https://www.youtube.com/embed/${videoId}?start=${offset}&autoplay=1&rel=0`;
  const ariaLabel = `Play source clip at ${offsetLabel} on YouTube`;

  if (playing) {
    return (
      <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
        <iframe
          className="absolute inset-0 h-full w-full"
          src={embedSrc}
          title={`Source clip at ${offsetLabel}`}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          loading="eager"
        />
      </div>
    );
  }

  // Facade: thumbnail + play circle + offset label
  return (
    <button
      type="button"
      className="group relative block w-full cursor-pointer overflow-hidden border-y border-line-2 bg-black focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-brier-blue)] focus-visible:ring-offset-2"
      aria-label={ariaLabel}
      onClick={activate}
    >
      {/* Decorative thumbnail via CSS background-image (no <img>, no next/image,
           no eslint suppression). The button's aria-label covers accessibility;
           the thumbnail background is purely decorative. AC-2: no network cost
           at SSR/build time — the background URL is resolved by the browser
           only when the facade is painted. */}
      <div
        aria-hidden="true"
        className="w-full opacity-80 transition-opacity duration-150 group-hover:opacity-60 group-focus-visible:opacity-60"
        style={{
          backgroundImage: `url(${thumbnailUrl})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          aspectRatio: "16 / 9",
        }}
      />

      {/* Play circle overlay */}
      <span
        aria-hidden="true"
        className="absolute inset-0 flex flex-col items-center justify-center gap-2"
      >
        {/* Circle */}
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--color-navy)] opacity-90 transition-opacity duration-150 group-hover:opacity-100 group-focus-visible:opacity-100">
          {/* Play triangle */}
          <svg
            width="20"
            height="20"
            viewBox="0 0 20 20"
            fill="none"
            aria-hidden="true"
          >
            <polygon points="6,3 17,10 6,17" fill="#FCFBF8" />
          </svg>
        </span>
        {/* Offset label */}
        <span className="rounded-[3px] bg-[var(--color-navy)] px-2 py-0.5 font-mono text-[11px] text-[#FCFBF8] opacity-90">
          {offsetLabel}
        </span>
      </span>
    </button>
  );
}
