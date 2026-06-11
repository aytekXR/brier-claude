import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import Link from "next/link";

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
  title: "Brier — the prediction track record, with receipts",
  description:
    "Independent, base-rate-corrected accuracy scores for crypto YouTube analysts. Every score links to a clip, a timestamp, and a price chart.",
};

const METHODOLOGY_VERSION = "v1.0";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body className="min-h-screen flex flex-col">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-4xl items-center gap-4 px-5 py-3">
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
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-4xl flex-1 px-5 py-10">{children}</main>
        <footer className="border-t border-line">
          <div className="mx-auto max-w-4xl px-5 py-4 font-mono text-[10.5px] text-ink-4">
            Methodology {METHODOLOGY_VERSION} · FAS = base-rate-corrected, calibration-aware,
            Bayesian-shrunk · Brier publishes statistics about public statements; it never
            recommends instruments or actions.
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
