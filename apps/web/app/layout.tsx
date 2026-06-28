import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import Link from "next/link";

import { NewsletterSignup } from "@/components/NewsletterSignup";
import { getCurrentMethodologyVersion } from "@/lib/db";
import { SITE_URL } from "@/lib/site";
import "./globals.css";

const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-source-serif",
});
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
});

export const metadata: Metadata = {
  /**
   * metadataBase ensures canonical URLs and OG image URLs resolve absolutely.
   * NEXT_PUBLIC_SITE_URL must be set in production (e.g. "https://brier.beyondkaira.com");
   * lib/site.ts is the single source and falls back to localhost for dev/CI.
   */
  metadataBase: new URL(SITE_URL),
  title: "Brier — the prediction track record, with receipts",
  description:
    "Independent, base-rate-corrected accuracy scores for crypto YouTube analysts. Every score links to a clip, a timestamp, and a price chart.",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  let methodologyVersion = "v1.1";
  try {
    methodologyVersion = await getCurrentMethodologyVersion();
  } catch {
    // DB unreachable at build time or during error pages; use safe fallback.
  }
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body className="min-h-screen flex flex-col">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-[940px] items-center gap-4 px-5 py-3">
            <Link href="/" className="flex items-center gap-2.5 text-ink no-underline">
              <BrierMark />
              <span className="font-serif text-xl font-semibold tracking-tight">Brier</span>
            </Link>
            <nav className="ml-2 flex gap-1 text-[13px] text-ink-3">
              <Link href="/" className="rounded-[3px] px-2.5 py-1.5 hover:bg-paper-2 hover:text-ink">
                Leaderboard
              </Link>
              <Link
                href="/methodology"
                className="rounded-[3px] px-2.5 py-1.5 hover:bg-paper-2 hover:text-ink"
              >
                Methodology
              </Link>
              <Link
                href="/corrections"
                className="rounded-[3px] px-2.5 py-1.5 hover:bg-paper-2 hover:text-ink"
              >
                Corrections
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[940px] flex-1 px-5 py-10">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto max-w-[940px] px-5 py-5">
            {/* Newsletter signup — site-wide (US-007, FR-406) */}
            <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="font-mono text-[10.5px] text-ink-4">
                Weekly digest of notable resolutions
              </p>
              <NewsletterSignup />
            </div>
            {/* Legal / methodology line */}
            <div className="border-t border-line pt-3 font-mono text-[10.5px] text-ink-4">
              Methodology{" "}
              <Link href="/methodology" className="text-[var(--color-brier-blue)] hover:underline">
                {methodologyVersion}
              </Link>
              {" "}· FAS = base-rate-corrected, calibration-aware, Bayesian-shrunk · Brier
              publishes statistics about public statements; it never recommends instruments or
              actions. ·{" "}
              <Link href="/corrections" className="text-[var(--color-brier-blue)] hover:underline">
                Corrections log
              </Link>
              {" "}·{" "}
              <Link href="/about" className="text-[var(--color-brier-blue)] hover:underline">
                About &amp; data requests
              </Link>
            </div>
          </div>
        </footer>
      </body>
    </html>
  );
}

/** The Register Mark (docs/BRANDKIT.md §4): scorecard frame, crosshair, blue dot. */
function BrierMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 48 48" fill="none" stroke="var(--color-navy)" aria-hidden>
      <rect x="3.5" y="3.5" width="41" height="41" rx="3" strokeWidth="3" />
      <line x1="30" y1="11" x2="30" y2="26" strokeWidth="3" />
      <line x1="22" y1="18" x2="38" y2="18" strokeWidth="3" />
      <circle cx="30" cy="18" r="3.4" fill="var(--color-brier-blue)" stroke="none" />
    </svg>
  );
}
