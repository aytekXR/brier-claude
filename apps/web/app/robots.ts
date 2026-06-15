/**
 * Next.js App Router robots.txt (MetadataRoute.Robots).
 *
 * Allow all crawlers; point to the sitemap.
 * Sitemap URL is absolute, resolved from metadataBase / NEXT_PUBLIC_SITE_URL.
 *
 * FR-407, PRD §18.
 */

import type { MetadataRoute } from "next";

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
    },
    sitemap: `${BASE_URL}/sitemap.xml`,
  };
}
