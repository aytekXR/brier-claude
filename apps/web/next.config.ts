import type { NextConfig } from "next";

/**
 * Content-Security-Policy, assembled from explicit directives.
 *
 * Tuned to exactly what Brier loads — nothing more:
 *   - frame-src www.youtube.com  : the official receipt embed (ReceiptPlayer, NFR-4).
 *   - img-src i.ytimg.com        : the receipt facade thumbnail (hqdefault.jpg).
 *   - script/style 'unsafe-inline': required by the Next.js App Router (hydration
 *       flight data) and next/font/Tailwind inline styles. No 'unsafe-eval'
 *       (production `next start` needs none; only dev HMR does). Tightening to a
 *       nonce-based policy would force dynamic rendering and is deferred — the
 *       site is overwhelmingly static (locked stack, no middleware).
 *   - connect/font/default 'self': all data fetches are same-origin (/api/*),
 *       fonts are self-hosted by next/font, and lightweight-charts is bundled.
 *   - frame-ancestors 'none'     : Brier is never embedded by others.
 */
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "font-src 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "frame-src https://www.youtube.com",
  "img-src 'self' data: https://i.ytimg.com",
  "object-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "connect-src 'self'",
  "upgrade-insecure-requests",
].join("; ");

/** Security headers applied to every response (defense-in-depth hardening). */
const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  // 2-year HSTS; honored only over HTTPS (ignored on http://localhost in dev).
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // Disable powerful features the product never uses; opt out of FLoC.
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
];

const nextConfig: NextConfig = {
  // Server components by default; the read layer (lib/db.ts) is server-only.
  poweredByHeader: false, // drop the X-Powered-By: Next.js fingerprint
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Stable aliases → canonical routes (exact-match sources; no wildcards):
  //   /leaderboard → /  : the leaderboard IS the homepage (permanent 308).
  //   /newsletter  → /  : no standalone landing page (signup is the homepage
  //       CTA + POST /api/newsletter). Non-permanent (307) so a future
  //       /newsletter page can reclaim the path. The exact source does NOT
  //       match /newsletter/unsubscribe, which stays a live route handler.
  async redirects() {
    return [
      { source: "/leaderboard", destination: "/", permanent: true },
      { source: "/newsletter", destination: "/", permanent: false },
    ];
  },
};

export default nextConfig;
