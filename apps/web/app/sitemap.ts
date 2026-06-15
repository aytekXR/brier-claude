/**
 * Next.js App Router sitemap (MetadataRoute.Sitemap).
 *
 * Lists the static routes and every analyst page.
 * DB read is wrapped in try/catch so the build succeeds offline (mock-first).
 * When the DB is unreachable only the static routes are emitted.
 *
 * FR-407, PRD §18 — name-query SEO discoverability.
 */

import type { MetadataRoute } from "next";

import { listAnalysts } from "@/lib/db";

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    {
      url: BASE_URL,
      changeFrequency: "daily",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/methodology`,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/corrections`,
      changeFrequency: "weekly",
      priority: 0.6,
    },
  ];

  // Analyst pages: read slugs from the registry.
  // If the DB is unreachable at build time, fall back to static routes only.
  let analystRoutes: MetadataRoute.Sitemap = [];
  try {
    const analysts = await listAnalysts();
    analystRoutes = analysts.map((a) => ({
      url: `${BASE_URL}/a/${a.slug}`,
      changeFrequency: "daily" as const,
      priority: 0.9,
    }));
  } catch {
    // DB unreachable — emit static routes only; no crash (mock-first, offline build).
  }

  return [...staticRoutes, ...analystRoutes];
}
