# ADR-0011: OG image generation via built-in next/og ImageResponse

- **Status:** accepted (ratified 2026-06-16, launch-readiness ADR gate — no dependency, nothing to activate)
- **Date:** 2026-06-15 (proposed); 2026-06-16 (accepted)
- **Deciders:** human owner (approved 2026-06-16) + frontend-engineer (E5-T4)

## Context

Task E5-T4 (PRD §19 "Social/OG layer (P0)") requires auto-generated Open Graph
share cards per receipt (`/r/[claimId]`) and per analyst (`/a/[slug]`), with alt
text on every card, satisfying PRD accessibility requirements.

The PRD §19 names "Vercel OG" as the implementation vehicle. The project's
**locked stack rule** (CLAUDE.md "Boring stack, locked") prohibits adding new
top-level dependencies without human approval and an ADR. Adding `@vercel/og`
directly would be such a new dependency.

**Key fact:** Next.js 15 ships `next/og` as a built-in module that re-exports
`ImageResponse` from `@vercel/og` (the compiled bundle lives at
`node_modules/next/dist/compiled/@vercel/og/`). No separate `@vercel/og`
package install is required. The functionality described in PRD §19 is therefore
available **for free** via the existing `next` dependency.

## Decision (proposed)

Implement OG image generation using the **built-in** `next/og` `ImageResponse`
class (no new package):

- Two `opengraph-image.tsx` files placed inside the existing route segments:
  - `apps/web/app/r/[claimId]/opengraph-image.tsx` — per-receipt share card
  - `apps/web/app/a/[slug]/opengraph-image.tsx` — per-analyst share card
- Next.js App Router detects these files by convention and auto-wires the
  `og:image` and `twitter:image` meta tags on the parent page. No manual
  `<meta>` tag authoring is required.
- `export const alt = "..."` in each file provides the accessible alt text that
  Next.js injects into `og:image:alt` and `twitter:image:alt` tags.
- `export const dynamic = "force-dynamic"` in both files ensures that card
  generation is deferred to request time. The build does **not** pre-render
  these routes and does **not** touch the database or any network resource at
  build time (mock-first: CI/build succeeds offline).
- Cards are rendered with `ImageResponse` at 1200×630 pixels, PNG format.
- Layout uses inline styles only (Tailwind does not run inside `ImageResponse`).
- No remote font fetches: the rendered text uses the system/generic font stack
  (`sans-serif`, `monospace`) so no `fetch()` call is made at generation time.
  This keeps CI and build clean (no network dependency for OG generation).
- All copy on the cards is neutral: score, claim asset/direction, outcome status
  only. No recommendation language, no hype vocabulary (AC-7 firewall).
- Numbers are ledger-exact (AC-3): FAS to 1 decimal, n as integer.
- Reads flow through `lib/db.ts` only (read-layer contract).
- Graceful fallback: if a claim or analyst is not found (or the DB call fails),
  a neutral fallback card renders instead of a crash.

A shared helper module (`apps/web/lib/og.tsx`) is factored for layout primitives
used by both cards. Per CLAUDE.md "A helper used once gets inlined", the helper
is only introduced because it is used twice.

## Consequences

- **Zero new dependencies.** `package.json` is unchanged. `next/og` is bundled
  with `next` 15 at no extra install cost. PRD §19 "Vercel OG" requirement is
  satisfied.
- **Build is offline-safe.** `force-dynamic` prevents pre-rendering; no DB
  connection and no font fetch happen at `npm run build`.
- **Mock-first.** The cards hit `lib/db.ts` at request time on the production
  server; CI never exercises the card routes (no test hits `/r/*/opengraph-image`
  or `/a/*/opengraph-image`).
- **Automatic meta wiring.** Next.js injects `og:image`, `og:image:alt`,
  `twitter:image`, and `twitter:image:alt` on the parent pages automatically —
  no manual `<head>` authoring needed.
- **Font limitation.** System fonts are used to avoid `fetch()` calls. The card
  aesthetic is clinical/typographic and readable at share-card size; this matches
  the BRANDKIT rating-agency aesthetic. If the human owner later approves fetching
  a specific font (e.g. IBM Plex Mono from Google Fonts), the font-loading call
  can be added behind the existing `fetch` pattern Next.js documents for
  `opengraph-image.tsx` without any dependency change.
- **This ADR is not yet accepted.** The implementation is proposed under the
  option-b (seam-landed) pattern: the files are committed and the gate is green,
  but the human owner's approval is needed to record this as accepted. Changing
  this requires the owner's approval recorded here (status → accepted) per
  ADR-0001 and CLAUDE.md.
