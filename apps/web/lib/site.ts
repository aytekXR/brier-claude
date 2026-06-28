/**
 * Single source of truth for the public site origin.
 *
 * Production sets NEXT_PUBLIC_SITE_URL (e.g. https://brier.beyondkaira.com);
 * dev/CI fall back to localhost. Centralized here so `metadataBase`, the
 * sitemap, robots.txt, and the analyst-page JSON-LD all resolve canonical / OG
 * URLs against the SAME origin — a divergence between them would emit
 * inconsistent canonical and share URLs and quietly hurt name-query SEO
 * (FR-407, PRD §18).
 *
 * NEXT_PUBLIC_ is required: this value is read in both server and client
 * contexts, and Next.js only inlines NEXT_PUBLIC_* vars into the client bundle.
 * The trailing slash is stripped so `${SITE_URL}/path` never doubles a slash.
 */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000").replace(
  /\/+$/,
  "",
);
