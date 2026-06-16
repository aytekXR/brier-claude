# Brier — Exceptions & Deferred Tasks ledger (technical debt)

Purpose: a single place that records every task whose TASKS.md checkbox is **not
ticked** because it is intentionally deferred — almost always an ADR-gated heavy
dependency that the locked stack (CLAUDE.md "Boring stack, locked") will not let
us add without human approval. Each entry states what *is* delivered (the seam +
mock-first fake that CI exercises), what *remains* (the dependency install +
human ADR approval), and the exact pointers (ADR, LOG line, commit) to resume.

This file is **not** a substitute for the DoD: a task here is genuinely
incomplete until its dependency is approved, installed, and its checkbox ticked
with a matching LOG.md DONE line. It exists so that "blocked-by-design" never
silently reads as "forgotten."

Convention: when a blocked item is finally approved and closed, move its entry to
the **Resolved** section at the bottom (do not delete it) and tick the TASKS.md box.

---

## Open — blocked by design (pending human ADR approval)

### E2-T4 — Captions + transcription adapters (real) · FR-103
- **Status:** seam landed, dependency-requiring portion BLOCKED. TASKS.md checkbox UNTICKED.
- **Delivered (CI path, no network):** caption-first acquisition (`fetch_captions`,
  stdlib `urllib`), `DeepgramTranscriber` (stdlib REST, no SDK, second-level
  offsets) — both fully implemented and tested; `WhisperTranscriber` seam (lazy
  `faster_whisper` import, mocked-model test, clear `RuntimeError` → ADR-0003 when
  absent); `AUDIO_TTL_DAYS = 30` (NFR-4). `FakeTranscriber` remains the CI/demo path.
- **Remaining to close:** human approval of **ADR-0003** → add the pinned
  `faster-whisper` *optional extra* to `pyproject.toml` and install it only on the
  rented-GPU backfill host (never CI/dev). No code reshape required — the seam is merged.
- **Pointers:** ADR `docs/adr/0003-faster-whisper-transcription-dependency.md`
  (Status: proposed); commit `7f6cbde`; LOG.md E2-T4 `BLOCKED` line (2026-06-14 15:47).
- **Blast radius:** none on E3 — extraction reads transcripts, which captions/Deepgram/FakeTranscriber already produce.

### E2-T5 — R2 storage adapter + audio TTL · NFR-4
- **Status:** seam landed, dependency-requiring portion BLOCKED. TASKS.md checkbox UNTICKED.
- **Delivered (CI path, no network):** `R2Storage` seam (lazy `boto3`, injected
  client factory, `ensure_audio_ttl_lifecycle` 30-day `audio/` rule, clear
  `RuntimeError` → ADR-0004 when absent); `LocalFSStorage.sweep_expired_audio` is the
  **real** dependency-free 30-day audio TTL exercised by CI (never deletes
  `transcripts/`). `LocalFSStorage` remains the CI/demo path.
- **Remaining to close:** human approval of **ADR-0004** → add the pinned `boto3`
  *optional extra* to `pyproject.toml`, installed only where R2 is reached. No code reshape required.
- **Pointers:** ADR `docs/adr/0004-boto3-r2-storage-dependency.md` (Status: proposed);
  commit `571d167`; LOG.md E2-T5 `BLOCKED` line (2026-06-14 15:58).
- **Blast radius:** none on E3.

### E3-T5 — Semantic dedup: production embedding model · FR-205, EC-2
- **Status:** seam + full dedup logic landed, dependency-requiring portion BLOCKED. TASKS.md checkbox UNTICKED.
- **Delivered (CI path, no network/model):** `dedup_claims` fully implements FR-205 grouping
  (same analyst+asset+direction+overlapping-horizon), representative-linkage clustering with one
  shared `dedup_cluster_id` (repeats reinforce, not multiply), and EC-2 (re-uploads keep the
  earliest `uttered_at`). On the DB path the similarity query uses the real pgvector `<=>`
  cosine-distance operator on `claims.embedding vector(384)` (no migration needed — column exists).
  The `Embedder` seam: `SentenceTransformerEmbedder` lazily imports `sentence-transformers`
  (all-MiniLM-L6-v2, 384-dim) and raises a clear `RuntimeError` → ADR-0008 when absent; an injected
  fake embedder / synthetic vectors are the CI/test path (DB-backed tests run on the dev DB).
- **Remaining to close:** human approval of **ADR-0008** → add the pinned `sentence-transformers`
  *optional extra* to `pyproject.toml`, installed only where dedup runs (never CI/dev). Without it,
  dedup matches only identical text (the fake embedder); true *semantic* dedup needs the real model.
  No code reshape — the seam + pgvector query are merged.
- **Pointers:** ADR `docs/adr/0008-sentence-transformers-embedding-dependency.md` (Status: proposed);
  commit `052c9e7` (E3-T5 seam); LOG.md E3-T5 `BLOCKED` line. mypy override for `sentence_transformers` added.
- **Blast radius:** none on the rest of E3; E4-T4 (contradiction detection) depends on E3-T5's dedup
  scaffolding, which is present and tested.

### E4-T2 (sub-item) — CCXT cross-check for price-outage detection · §18, EC-8
- **Status:** seam landed, dependency-requiring portion BLOCKED. **E4-T2 itself is DONE/ticked** — this
  is a robustness *sub-component*, not the task core. The core (real trailing-history `base_rate`, the
  CoinGecko composite source, the v1.1 methodology bump + recompute) is complete and shipped without it.
- **Delivered (CI path, no network):** `CoinGeckoPriceSource` (stdlib `urllib` REST, injected `http_get`
  boundary, recorded fixture `data/fixtures/coingecko/`, no new dependency) is the published composite
  source. `CcxtCrossCheckSource` is a seam: a lazy `import ccxt` inside the method that raises a clear
  `RuntimeError` → ADR-0009 when absent; an injected/mocked exchange boundary is the test path. `ccxt`
  is NOT in `pyproject.toml` deps; a scoped `[[tool.mypy.overrides]] ignore_missing_imports` stanza
  handles the optional import. `FakePriceSource` (fixture closes) remains the CI/demo path.
- **Remaining to close:** human approval to add the heavy `ccxt` dependency (an *optional extra*,
  installed only where the live cross-check runs, never CI/dev) → wire the real exchange call in
  `CcxtCrossCheckSource` and enable the CoinGecko-vs-CCXT divergence/outage check (EC-8). Until then the
  cross-check is structurally present but inert; base rates compute from the CoinGecko composite (prod)
  or fixtures (CI) without a second-source check.
- **Pointers:** ADR `docs/adr/0009-base-rates-from-trailing-history.md` (base-rate engine **accepted
  2026-06-16**; the CCXT cross-check sub-item remains **proposed**); LOG.md E4-T2 `NOTE` (CCXT seam)
  line; the E4-T2 commit. mypy override for `ccxt` added to `pyproject.toml`.
- **Blast radius:** none — scoring uses the CoinGecko composite / FakePriceSource; the cross-check only
  adds outage detection, which degrades gracefully to "no second source" when absent.

---

## Open — E5 shipped behind a seam; real external adapter pending ADR approval (TASK DONE)

These E5 web tasks are **complete and their TASKS.md checkboxes are ticked** — the
mock-first fake is the CI/build/dev path and the feature works end-to-end on it.
What is deferred is only *activating the real external service*, which needs human
ADR approval + a production API key. CI/build never touch the network.

### E5-T3 (email) — Resend transactional email · FR-405/AC-5/UF-3 · ADR-0010
- **Delivered (CI path):** `Notifier` seam in BOTH `services/pipeline/brier_pipeline/disputes/notify.py`
  (`FakeNotifier` + `ResendNotifier` stdlib-urllib) and `apps/web/lib/dispute-intake.ts`
  (`FakeNotifier` + `ResendNotifier` fetch + `getNotifier()` factory). The dispute
  ticket-id confirmation "email" goes through the fake in CI/dev; the real adapter
  raises a clear error → ADR-0010 without `BRIER_RESEND_API_KEY`. No `resend` SDK; no dep added.
- **Remaining to close (activation only):** **ADR-0010 accepted 2026-06-16** (launch-readiness gate);
  set `BRIER_RESEND_API_KEY` in production so `getNotifier()` returns `ResendNotifier`. No dependency.
- **Pointers:** ADR `docs/adr/0010-resend-transactional-email-via-stdlib-rest.md` (accepted 2026-06-16);
  commits `2f8d204` (intake), `a8e82da` (form), `2bf641c` (getNotifier factory).

### E5-T6 (newsletter) — Buttondown subscriber · FR-406/US-007/US-008 · ADR-0013
- **Delivered (CI path):** `Subscriber` seam in `apps/web/lib/subscriber.ts` — `FakeSubscriber`
  (CI/build/dev default via the `getSubscriber()` factory) + `ButtondownSubscriber` (native
  fetch, no SDK). Double opt-in + one-click unsubscribe provided through the seam; the fake
  records actions, no network in CI/build.
- **Remaining to close (activation only):** **ADR-0013 accepted 2026-06-16** (launch-readiness gate);
  set `BRIER_BUTTONDOWN_API_KEY` in production. Known MVP trade-off documented in ADR-0013: the
  app's own `/newsletter/unsubscribe?email=` route is token-less (Buttondown's native links are tokened).
- **Pointers:** ADR `docs/adr/0013-newsletter-waitlist-via-buttondown-seam.md` (accepted 2026-06-16); commit `0d8ff12`.

### E5-T5 (leaderboard cache) — materialized view + Upstash Redis · FR-407/§18 · ADR-0012
- **Delivered (CI path):** leaderboard p95 met with Next's **built-in** `unstable_cache`
  (revalidate 60s) — measured **p95 = 38 ms** in the E5 dogfood, far under the 2 s target. NO new dependency.
- **Remaining to close (prod-scale, optional):** the PRD §18 path — a Postgres **materialized view**
  (a future pipeline migration) + **Upstash Redis** (an ADR-gated heavy dep) — is deferred; the
  built-in cache already satisfies p95<2s. `getLeaderboardCached` is the seam for a future backend swap.
- **Pointers:** ADR `docs/adr/0012-leaderboard-cache-via-next-builtin.md` (accepted 2026-06-16); commit `8173eb8`.

### E5-T4 (OG cards) — NOT a blocked dependency
- `next/og` ImageResponse ships **with Next 15** — no new top-level dependency. ADR-0011 (accepted 2026-06-16)
  records this for the audit trail. No activation pending; nothing deferred. Listed here only so the
  "Vercel OG" line in PRD §19 is not mistaken for an unshipped heavy add. Commit `cdb6ac3`.

## Open — E6 shipped behind a seam; real external adapter pending ADR approval (TASK DONE)

These E6 trust/ops tasks are **complete and their TASKS.md checkboxes are ticked** —
the mock-first fake (`FakeAlerter`) + the durable `alerts` table are the CI/dev path
and every feature works end-to-end on them (proven by DB-backed tests). What is
deferred is only *activating a real external monitoring sink*, which needs human
ADR-0014 approval + a production token/DSN. CI/build never touch the network.

### E6 monitoring/alerting sinks — Better Stack / Sentry / Axiom · NFR-1/NFR-5/§18 · ADR-0014
- **Delivered (CI path, no network):** the `Alerter` seam in
  `services/pipeline/brier_pipeline/ops/alerts.py` — `FakeAlerter` (CI/dev default;
  injected directly in all E6 alert tests) + `record_alert`/`raise_alert` writing the
  durable, dedup-keyed `alerts` table (idempotent) + `get_alerter()` factory.
  **`BetterStackAlerter` and `SentryAlerter`** are real adapters (stdlib `urllib` REST,
  no SDK, nothing added to `pyproject.toml`); each raises a clear `RuntimeError`
  referencing ADR-0014 when its token/DSN is absent. All five E6 check-jobs
  (dispute SLA, freshness, deletion, cost cap, erasure SLA) and the NFR-5 spend-cap
  engine emit through this one seam.
- **Remaining to close (activation only):** **ADR-0014 accepted 2026-06-16** (launch-readiness gate);
  set `BRIER_BETTER_STACK_TOKEN` and/or `BRIER_SENTRY_DSN` in production so `get_alerter()`
  returns the real adapter. **Axiom** (the §18 structured-log sink) is the one piece
  NOT yet implemented: it follows the identical Alerter-seam pattern and is
  **blocked-by-design** — the `alerts` table + Better Stack + Sentry already cover the
  §18 monitoring surface, so an Axiom adapter would add a third sink with no new
  behaviour. Add it (same pattern) only if a human wants Axiom specifically.
- **Pointers:** ADR `docs/adr/0014-monitoring-alerting-via-stdlib-rest.md` (accepted 2026-06-16);
  migration `0008_ops_trust.sql` (`alerts`/`spend_ledger`/`erasure_requests`); the
  E6-T1/T2/T3/T4/T5 commits.

## Backlog (quality, not blocked-by-design)

- **PriceChart pre-existing gate-suppressions (E1-T5):** `apps/web/components/PriceChart.tsx`
  carries 4 `// eslint-disable-next-line @typescript-eslint/no-explicit-any` for the
  TradingView lightweight-charts bindings (origin E1-T5, not E5). CLAUDE.md forbids
  gate-silencing; replacing the `any`s with proper lightweight-charts types (or a scoped
  eslint config stanza) would close them. Not actioned in E5 (out of scope + chart-typing risk);
  flagged by the E5 qa-audit for a future cleanup.
- **Multi-year price fixtures (carried from E4):** the demo price fixtures are only ~18 months,
  so E4 base rates over them are thin/extreme (b=0.0/1.0) and the demo inversion's VectorEdge half
  is the MIN_BASE_RATE_WINDOWS fallback, not a measured prior (documented in `test_demo_e2e.py` +
  ADR-0009). Extending the fixtures to a multi-year span would give a fully-measured base-rate demo.

### Launch-readiness audit findings (2026-06-16) — close before production GO

Surfaced by the 18-agent adversarial readiness audit; full detail + verdicts in
`docs/LAUNCH-READINESS.md`. These are completion gaps in otherwise-DONE work (not ADR-gated deps):

- **AC-3 trend column non-functional:** `apps/web/app/page.tsx:174,229` always passes `[]`/`null` to
  `TrendSparkline`; real per-analyst trend points are never fetched into the leaderboard row, so the trend
  renders "—" even in production with multi-day history. FAS/n/falsifiability are ledger-exact. Wire a trend
  series (FAS over recent `score_runs`) into `getLeaderboard`. **AC-3 sub-requirement.**
- **Backfill job handlers unregistered:** `transcribe`/`extract`/`resolve_claims`/`score_analysts` exist only
  as direct functions (the demo path); no `register_handler` call wires them, so `backfill_channel`'s
  enqueued `transcribe` jobs have no processor. Register them for the backfill (gated on ADR-0003/0004/0008).
- **Worker bootstrap imports nothing:** `run_forever` auto-discovers no handlers; the production worker must
  import every handler module first (`docs/RUNBOOK-PRODUCTION.md` §3). A single
  `python -m brier_pipeline.jobs.worker` entrypoint importing all handlers would close this.
- **AC-5 UF-3 analyst notification:** the disputer is emailed the ticket id, but the analyst is not notified
  on adjudication. Confirm against PRD scope; wire if required.
- **AC-1/G2 golden re-run on real output:** `test_golden_set.py` runs against a static `predicted` snapshot,
  so a prompt/model regression would not fail the build. Re-run against real `LlmExtractor` output (ADR-0005
  key) at ≥95%/≥80% before GO. **Not a code defect — a launch validation step.**

## Resolved

_(none yet)_
