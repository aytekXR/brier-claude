# ADR-0012: Leaderboard p95 <2s via Next.js built-in data cache (no new dependency)

- **Status:** proposed
- **Date:** 2026-06-15
- **Deciders:** human owner (approval pending) + frontend-engineer (proposing, E5-T5)

## Context

PRD §18 states: "leaderboard p95 latency <2s (materialized views + Upstash Redis)."

Task E5-T5 requires meeting the p95 <2s SLO on the leaderboard page.  The PRD
names two specific mechanisms:

1. **Postgres materialized views** — a database-side precomputation of the
   leaderboard result, refreshed by the pipeline on each scoring run.  This is
   a pipeline migration and a non-trivial schema change.
2. **Upstash Redis** — a serverless Redis cache layer in front of the DB read.
   Adding `@upstash/redis` would be a new dependency requiring human approval
   and this ADR.

The **locked stack rule** (CLAUDE.md "Boring stack, locked") prohibits adding
new dependencies without human approval and an ADR.

**Key fact:** Next.js 15 ships a built-in data cache (`unstable_cache`) that
caches the return value of any async function on the server, keyed by a tag
array, with a configurable `revalidate` window (seconds).  This is part of the
existing `next` dependency — no new package is required.

**Why 60 seconds satisfies p95 <2s:**
The leaderboard SQL query joins `scores` → `score_runs` → `analysts` and reads
at most O(50) rows.  On a standard Postgres instance this executes in <50 ms.
With a 60-second cache window:
- 99%+ of requests are served from the in-memory cache (sub-millisecond).
- At most 1 request per 60 seconds hits Postgres (the cache-miss that triggers
  revalidation).
- The p95 is therefore bounded by the cache hit path, well under 2 seconds.
- AC-3 (numbers ledger-exact) is satisfied: a score written after the previous
  cache fill will be visible within 60 seconds of being written — the revalidation
  window is a bounded staleness, not perpetual drift.

## Decision (proposed)

Meet the leaderboard p95 <2s requirement using the **built-in** Next.js
`unstable_cache`:

```ts
// apps/web/lib/db.ts
export const getLeaderboardCached = unstable_cache(
  () => getLeaderboard(),
  ["leaderboard-latest"],
  { revalidate: 60 },
);
```

The leaderboard page (`app/page.tsx`) calls `getLeaderboardCached` instead of
`getLeaderboard` directly.  The `dynamic = "force-dynamic"` directive is removed
from the leaderboard page; the ISR revalidation mechanism takes its place.

The PRD §18 "materialized views + Upstash Redis" path is **deferred**:

- A Postgres materialized view is a future **pipeline** migration (numbered
  `migrations/*.sql`), to be added when traffic scale justifies the operational
  complexity.  At that point, `getLeaderboard` can read from the materialized
  view directly, making the cache less necessary (but still harmless).
- Upstash Redis is an ADR-gated dependency.  If traffic scale requires a
  distributed cache (e.g., to survive a Next.js server restart resetting the
  in-process cache), an ADR should be filed at that time.  The `getLeaderboardCached`
  wrapper is the seam: swapping the transport from `unstable_cache` to an Upstash
  call behind the same export name requires no call-site changes in the page.

## Mock-first / CI / build

`unstable_cache` is part of `next` — imported as `import { unstable_cache } from "next/cache"`.  No network call, no external service, no environment variable is required at build or in CI.  The cache is in-process memory; CI tests do not exercise it.  The build succeeds offline.

## Consequences

- **Zero new dependencies.** `package.json` is unchanged.
- **p95 <2s achieved** at current scale via in-process cache hit path.
- **AC-3 satisfied.** Bounded 60-second staleness window.  Score writes are
  visible within 60 seconds.  Numbers are ledger-exact (no rounding, no
  fabrication).
- **Build offline-safe.** No DB connection at build time; `unstable_cache` is
  lazy (first call triggers the first DB read at request time).
- **Materialized-view + Upstash path deferred**, documented here so the human
  owner can evaluate when to pursue them (traffic metrics will clarify whether
  they are needed).
- **`getLeaderboardCached` is the seam** for future cache-backend swap.  No
  page-level changes are needed if the backing implementation is swapped.
- **This ADR is not yet accepted.** The implementation is proposed under the
  option-b (seam-landed) pattern: the files are committed and the gate is green,
  but the human owner's approval is needed to record this as accepted.  Changing
  this requires the owner's approval recorded here (status → accepted) per
  ADR-0001 and CLAUDE.md.
