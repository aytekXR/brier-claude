# Brier — next-prompt (START HERE)

You are the lead engineer on **Brier**, a prediction track-record engine that scores crypto-YouTube
analysts on the accuracy of their public predictions, with clip-level receipts. **This file is the single
live entry point for any new session** — it holds the current state and the active worklist. It is committed
to the repo on purpose so it travels with `git clone`.

> **The prompt system is two files (and only two):**
> - **`next-prompt.md`** (this file) — current state + what to do next.
> - **`past-prompts.md`** — the archive of every completed prompt (E1 → … → CUTOVER round 1 + the old MASTER index).
>
> **Binding rule:** do **not** create new `PROMPT-*.md` files. When a session finishes a worklist, append the
> worklist it completed to the bottom of `past-prompts.md` (under a `## ═══ <name> ═══` header) and rewrite this
> file with the successor worklist. That is what keeps the chain self-perpetuating with a tidy repo root.

## 1. What to read, in order

1. **`CLAUDE.md`** — conventions + the binding 5-rule logging contract (overrides default behavior).
2. **This file** — state + the active worklist.
3. **`docs/LAUNCH-READINESS.md`** — the go/no-go assessment (verdict + per-AC/goal status + remaining gates).
4. **`docs/RUNBOOK-PRODUCTION.md`** — the step-by-step activation + backfill + deploy + on-call runbook.
5. **§A2 below (Audit findings 2026-06-22)** — the verified completion/coverage/assumption/risk audit that
   produced this rewrite. Treat its findings as the authoritative gap list for this session.

## 2. Where the project stands (verified 2026-06-22)

- **Acceptance test re-verified GREEN on this box today** (`sg docker -c 'make ci'`, exit 0): `make check`
  **886 passed + 1 benign skip** (775 at the 06-22 audit; +21 TDD/guard tests 06-24; **+90 on 06-28** — A2#8
  score_runs trigger (8) + Track **T2** failure-path/edge net (82)) (copy-lint AC-7 / ruff / ruff-format /
  mypy-strict 46 files / tsc / eslint
  all clean); `make pipeline-demo` prints the canonical board **NorthChain 59.0 / VectorEdge 57.5 /
  Aylin 51.7** (20 cumulative resolutions); `make web-build` clean (10 static pages). CI runs the identical
  sequence on every push against a pgvector Postgres service.
- **All six MVP build epics are complete on the fixture/mock path** (E1 → E6). Three TASKS.md boxes remain
  unticked **by design** — E2-T4, E2-T5, E3-T5 — each blocked on a heavy-dependency ADR (0003/0004/0008);
  full detail in `EX-dept.md`.
- **Verdict: still NO-GO** for the first production deploy. The NO-GO is now broader than "operational steps
  only": the 2026-06-22 audit confirmed **several real code/wiring gaps** that were not in the prior closeout
  (see §A2). None is a structural failure, but each must be closed (with a test) before GO.

### §A2 — Audit findings (2026-06-22), all adversarially verified

A read-only multi-agent audit (10 coverage auditors + web/assumption/risk auditors + a 5-claim adversarial
refute panel) plus direct code inspection produced these. **Every item below was confirmed against the
actual code** (file:line given where it matters):

> **Progress 2026-06-24 (Track T1):** A2#1, A2#5, A2#6, A2#7 are **CLOSED test-first** (make check 794+1;
> board unchanged; no new dep). A2#3 is handled as documentation in §3b.
> **Progress 2026-06-28:** **A2#8 CLOSED test-first** (migration 0010 narrow `score_runs` trigger + 8 tests;
> make check 886+1; no new dep). **Remaining: A2#2** (QA-queue/FR-203 wiring — lands with the gated `extract`
> handler) and **A2#4** (caption path — human decision). All other §A2 items are now closed.

**Confirmed gaps the prior closeout did NOT capture (fix these — each with a regression test):**

1. **Silent fixture-pricing in production (HIGH).** `jobs/handlers.py:50-56` — `_get_price_source()` returns
   `FakePriceSource(_FIXTURES_DIR)` and only logs a *warning* when `BRIER_COINGECKO_API_KEY` is unset. The
   nightly `score_analysts` / `resolve_claims` jobs would then **score 50 real analysts against 18-month
   fixture prices** with no hard failure. Fix: a production-mode guard that raises (or refuses to score) when
   the key is absent + a failure-path test.
2. **QA review queue is dead code in production — FR-203 risk (HIGH).** `qa/queue.py`’s `route_and_enqueue` /
   `route_low_confidence` / `record_review` are **never called outside tests**. The `extract` handler (not yet
   written) MUST call `route_and_enqueue` so low-confidence claims route to human review before publishing
   (FR-203, HP-4). Today nothing enforces "nothing below threshold publishes unreviewed." Fix as part of the
   `extract` handler wiring + a test asserting the route is invoked.
3. **Missing production credentials in the checklist (MEDIUM).** `config.youtube_api_key()` reads
   `BRIER_YOUTUBE_API_KEY` (used by `poller.py:212` + `deletion.py:179`) and the QA queue needs
   `BRIER_LABEL_STUDIO_URL` / `BRIER_LABEL_STUDIO_TOKEN` — **none were in the prior credentials list.** Added
   to §4 below. `BRIER_COINGECKO_API_KEY` was listed "optional" but is **effectively required** (see #1).
4. **Caption-first acquisition is not wired (MEDIUM).** `DataApiYouTubeClient.fetch_captions()` uses an
   injectable `caption_get` boundary that has never been connected to a real source; the Data API
   `captions.download` endpoint needs OAuth2 (not available with an API key). Decide the caption path + ToS
   posture before the backfill, or all videos fall through to (costly) Whisper.
5. **Incremental transcription has no seam (MEDIUM).** There is no `BRIER_DEEPGRAM_API_KEY` (or Groq) in
   `config.py` and no `get_transcriber()` factory. When the `transcribe` handler is written it risks
   hard-coding Whisper for *new uploads* too (GPU cost per upload). Add the key + a factory (Whisper for
   backfill, incremental adapter for new uploads).

**Lower-severity, confirmed (backlog, each with a test):**

6. **AC-7 firewall has a blind spot.** `copy_lint.py` scans web `.ts/.tsx`, fixtures, `METHODOLOGY.md`,
   `LEGITIMATE_INTEREST.md` — **not** Python-rendered DB strings (claim `quote`, `rationale`) or API JSON
   derived from the DB. A forbidden phrase inside a real extracted `quote` would reach users unscanned.
7. **No YouTube-only scope check at roster import.** `_assert_in_scope()` only blocks Turkey/BIST
   jurisdictions; it does not verify `channel_id` is a YouTube ID (`UC…`, 24 chars). Scope lock is unenforced
   at import.
8. **`score_runs` is outside the NFR-3 trigger.** ✅ **CLOSED 2026-06-28** — migration 0010
   `forbid_score_runs_mutation` narrows it: an UPDATE is allowed only when nothing but `finished_at` changes,
   every other column is immutable, and DELETE is barred; the lone `finished_at` finalize still works. Proven
   by `tests/test_score_runs_append_only.py` (8) + the extended `test_migrations` trigger guard.

## 3. Pending User Actions (persist across sessions — the agent cannot self-serve these)

This is a **gated** project: the agent does the engineering, but each gate is the **human owner's call** and
the agent must STOP and ask at each one. Nothing proceeds past a gate without you.

### 3a. ADR approvals (no dependency lands without one)
- **ADR-0003** faster-whisper (GPU transcription), **ADR-0004** boto3/R2 (object storage), **ADR-0008**
  sentence-transformers (semantic dedup) — flip status → add the pinned **optional extra** to
  `pyproject.toml` → install on the dedicated host only. These unblock E2-T4 / E2-T5 / E3-T5 and the
  `transcribe`/`extract` handler wiring.
- **ADR-0009 CCXT cross-check** (optional, EC-8 price-outage detection) — base-rate engine is already
  accepted; only the CCXT sub-item remains proposed.
- **ADR-0016 — web unit-test runner (Vitest)** *(renumbered from 0015, which T3 took for the coverage gate).*
  apps/web has **zero** tests; a JS test runner (Vitest + @vitejs/plugin-react + @testing-library/react +
  @testing-library/user-event + jsdom) is a new dev dependency and is gated. Approve before any web test lands
  (Track T4). (Pure-logic targets need only `vitest`, not jsdom.)
- **Coverage tooling — ✅ APPROVED + DONE 2026-06-28 (ADR-0015, Track T3).** `coverage[toml]` added as a
  pipeline dev extra; `make coverage` + a CI step now enforce a line-coverage **floor of 89** (measured
  baseline 89.92%, displays 90%; 3235 stmts, 326 missed). The floor is a ratchet — bump to 90 once the
  remaining Track-T hardening (SLA/freshness/deletion + the broad pass) pushes the number comfortably past it.
  **Web is still 0%** (no runner — gated behind ADR-0016/Track T4).

### 3b. Production credentials (env only — NEVER commit a key)
> Fill from the committed templates: repo-root **`.env.production.example`** → a `chmod 600`
> `/etc/brier/brier.env` on the worker host, loaded by **`deploy/brier-worker.service`** (systemd
> `EnvironmentFile=`); web keys go in `apps/web/.env.production.local`. `.gitignore` ignores `.env*`
> except the two `*.example` templates.
- **Required:** `BRIER_ANTHROPIC_API_KEY` (extraction), `BRIER_YOUTUBE_API_KEY` (poller + deletion sweep —
  *was missing from the list*), `BRIER_COINGECKO_API_KEY` (*effectively required* — without it production
  silently scores against fixtures, finding A2#1), `BRIER_RESEND_API_KEY` (dispute/adjudication email),
  `BRIER_BUTTONDOWN_API_KEY` (newsletter/waitlist).
- **Monitoring:** `BRIER_BETTER_STACK_TOKEN` and/or `BRIER_SENTRY_DSN`.
- **QA review (FR-203):** `BRIER_LABEL_STUDIO_URL` + `BRIER_LABEL_STUDIO_TOKEN` (or accept the in-memory queue
  with a documented synchronous human-review step) — *was missing from the list*.
- **Incremental transcription (after A2#5 lands):** `BRIER_DEEPGRAM_API_KEY` (or Groq).
- **Extraction model (optional):** `BRIER_EXTRACTION_MODEL` — defaults to the Haiku-class
  `claude-haiku-4-5-20251001` (`config.extraction_model()`); the gated `extract` handler must inject it.
  Override only with human approval (cheap pass-1/pass-2 is intentional, E3-T1).
- **Analyst `notify_email` values** in the roster JSON for the AC-5/UF-3 adjudication notice.
- **Spend caps:** set `BRIER_TRANSCRIPTION_MONTHLY_CAP_USD` (default 700) and `BRIER_LLM_MONTHLY_CAP_USD`
  (default 300) to the **real** backfill-month budget before draining (assumption A-15); run a single-channel
  pilot to calibrate.

### 3c. Infrastructure & business decisions
- Rented **GPU host** (Whisper backfill); **Cloudflare R2** bucket + creds; the monthly **spend budget**.
- The **named erasure-request owner** (NFR-6 / GDPR Art. 17) — *still open, this is a GO blocker* (eliminate
  assumption A-14); publish a routing contact on `/about` + `LEGITIMATE_INTEREST.md`.
- The **50-analyst roster** (which channels) as crypto + YouTube only (scope lock).
- The **caption path / ToS posture** decision (A2#4).
- A concrete **job scheduler** choice (systemd timer / pg_cron / external cron) — the runbook names cadences
  but ships no scheduler (assumption A-6).
- **The final GO call.**

## 4. Environment — Ubuntu 24.04 VPS (READ FIRST)

- **Repo root (`$REPO`).** `cd` into your clone; run every command from there.
- **Docker = Engine + systemd (no Desktop).** Wrap docker/compose/`make seed`/`make pipeline-demo`/`make ci`
  in `sg docker -c '...'`. `make check` and `make web-build` need no docker once the DB container is up
  (`brier-db` on `localhost:5432`, creds `brier:brier`).
- **First-run acceptance test — must pass before any work:**
  ```bash
  sg docker -c 'make ci'    # seed → make check → coverage(ADR-0015) → pipeline-demo → web-build
  ```
  Expect: `make check` green (**886 + 1 benign skip**), board **NorthChain 59.0 / VectorEdge 57.5 /
  Aylin 51.7**, Next build clean. If red, fix the *environment*, not the code.

## 5. The active worklist

Two tracks. **Track T (TDD hardening) is ungated and starts now**; **Track G (activation gates) is human-gated**
and proceeds gate-by-gate. Do Track T first (or interleave) — it closes the §A2 code gaps with tests and
raises the safety net before real data flows.

### Track T — TDD hardening (ungated; do now)
Work test-first: write the failing test, then the fix, then `make check` green. (≈228 concrete missing-test
cases were catalogued by the audit — see the workflow result; the priority subset is below.)

- **T1 — Close the §A2 ungated code gaps, each test-first — ✅ DONE 2026-06-24** (make check 794+1, board
  unchanged, no new dep): A2#1 production price-source guard (`config.is_production()` + `_get_price_source`
  raises in prod without the CoinGecko key); A2#5 `config.deepgram_api_key()` + `get_transcriber()` factory
  (backfill→Whisper, incremental→Deepgram-when-keyed-else-Fake, prod-no-key→raise); A2#6
  `copy_lint.forbidden_terms_in()` reusable AC-7 matcher for DB-sourced `quote`/`rationale`; A2#7
  `_assert_youtube_channel` UC-prefix scope check in `add_analyst`/`import_roster`. New tests:
  test_handlers_price_source, test_transcriber_factory, test_scope_lock_channel, test_copy_lint_forbidden_terms.
  **A2#8 — ✅ DONE 2026-06-28** (migration 0010 `forbid_score_runs_mutation` + `test_score_runs_append_only.py`
  (8) + extended `test_migrations` trigger guard; make check 886+1; no new dep). **All ungated §A2 code gaps
  are now closed.**
- **T2 — Python failure-path & edge backlog — ✅ DONE 2026-06-28** (make check **886+1**; +82 tests/7 files;
  tests-only, no source edits, no new dep; built via a 6-cluster workflow with per-cluster adversarial QA —
  all solid, **0 genuine defect flags**): `test_t2_registry` (13: not-found raises on update/remove/set-flag,
  duplicate `channel_id`+slug UniqueViolation, `notify_email` round-trip, exactly-one-selector),
  `test_t2_poller` (3: paused-analyst skip, watermark advance, empty-roster no-op), `test_t2_backfill`
  (3: `max_videos=0/1` boundaries + resumability watermark), `test_t2_scoring` (21: k=25 shrinkage, n=19/20
  ranked, n=29/30 provisional — all match METHODOLOGY, `fas.py` untouched), `test_t2_resolution` (17:
  directional 0/0.5/1, target-by-deadline HIT/MISS/deferred incl. EC-8 gap, `resolve_open_claims` no-op,
  conditional-not-activated, `default_30d/90d/eoy` horizons), `test_t2_spend` (25: 99/100/101% cap boundary at
  strict `>`, 70% single upward-crossing alert). The credibility moat (scoring math, resolution rules,
  append-only ledger, spend caps, AC-7) is now under regression guard. **Remaining T2 backlog** (optional next
  pass): SLA-clock boundary cases (`disputes/sla.py`) and freshness/deletion edge branches were not in this
  batch — pick up if hardening continues.
- **T3 — Coverage as a permanent gate — ✅ DONE 2026-06-28** (ADR-0015): added `coverage[toml]` (dev extra),
  `[tool.coverage]` config, `make coverage`, and a dedicated CI step + `make ci` stage; **fail_under = 89**
  (baseline 89.92% / displays 90%). Ratchet to 90 after the SLA/freshness/deletion + broad hardening tests
  land. `make check` stays instrumentation-free (coverage is a separate target).
- **T4 — Web tests (after ADR-0015):** stand up Vitest; implement the priority targets in order — `lib/og`
  band/label colors, `lib/subscriber` `validateEmail` + `FakeSubscriber`, `lib/types` `FAS_BANDS` ordering,
  `lib/dispute-intake` `FakeNotifier`/ticket shape, `lib/db` `deriveDisplayStatus` (export it), the three API
  route handlers (disputes/newsletter/waitlist validation), then `TrendSparkline` empty-state, `FASBadge`,
  `ClaimStatusChip`, `ClaimTable` filter, `ReceiptPlayer` deletion overlay. **Untestable without a browser
  runner (defer to a Playwright ADR):** AC-2 "<3s" embed, PriceChart live render, OG pixel output, p95<2s.

### Track G — Activation gates (human-gated; STOP and ask at each)
Work `docs/RUNBOOK-PRODUCTION.md` top to bottom. **No dependency or live external API call without explicit
human approval; never commit a key.**

1. **Acceptance test green** on the deploy box (`make ci` → 796 + 1 skip).
2. **Approve heavy-dep ADRs (0003/0004/0008):** flip status → pin optional extra → install on the dedicated
   host only → tick TASKS.md (E2-T4/E2-T5/E3-T5) → move the EX-dept entry to **Resolved**. Activating a real
   adapter must not regress `make check` (the fake stays the CI path).
3. **Register `transcribe` + `extract` handlers** wired to the now-installed real adapters via their seams,
   added to `bootstrap_handlers()`. The `transcribe` handler uses `get_transcriber()`; the `extract` handler
   constructs `LlmExtractor(model_version=config.extraction_model(), completion=llm.completion)` (Haiku-class)
   and **must call `route_and_enqueue` (A2#2 / FR-203).** Re-verify `make check` stays green with the fakes in CI.
4. **Set production credentials** (§3b, env only). Populate `analysts.notify_email` via the roster JSON or
   `registry add --notify-email …`.
5. **Roster ingest — G1:** real 50-analyst roster JSON (crypto + YouTube; scope lock) →
   `registry import-roster <file>`.
6. **24-month backfill — G3:** set spend caps to the real budget + run a single-channel **cost pilot** first;
   enqueue `backfill_channel(..., months=24, max_videos=<cap>)` per channel; drain with
   `python -m brier_pipeline.jobs.worker`. Verify **≥ 10,000 resolved claims** and that base rates are
   non-degenerate on real 5-year history (assumptions A-2/A-3).
7. **Golden-set on REAL model output — AC-1/G2:** regenerate the 200 `predicted` records by running the live
   `LlmExtractor` (ADR-0005 key), then re-run `tests/test_golden_set.py`; require **precision ≥ 95% &
   recall ≥ 80%**. (Today the gate scores a static snapshot — it cannot catch a model regression. Eliminate
   assumption A-1.) Add a manual spot-check of 20–50 real claims before any score goes public (risk: a wrong
   public score is reputational/defamation exposure).
8. **Schedule the trust-ops jobs** (poll_channels ≤2h, freshness_check, resolve_claims, score_analysts,
   deletion_sweep, dispute_sla_check, weekly_dispute_report, erasure_sla_check) with a concrete scheduler
   (A-6) + wire monitoring.
9. **Final compliance:** AC-7 copy-lint clean (incl. the A2#6 DB-content scan); NFR-6 `/about` notice + named
   erasure owner; NFR-3 spot check (UPDATE/DELETE on `resolutions` raises); v1.1 scoring + binding worked
   examples unchanged.

## 6. Verification workflow (run for EVERY change — bias to verification over speed)

1. **Test-first:** write the failing test before the code (Track T). A bug fix starts with a reproducing test.
2. **Gate:** `make check` green (copy-lint AC-7 → ruff → ruff-format → mypy-strict → pytest → tsc → eslint).
3. **End-to-end:** `sg docker -c 'make ci'` — re-confirms the canonical board + web build on a seeded DB.
4. **Coverage:** `make coverage` (after T3) ≥ the CI floor; report the delta in the LOG DONE line.
5. **Staging/smoke (activation):** per real adapter, one real input end-to-end on its host before scheduling
   (one YouTube video → transcriber → R2 → LlmExtractor → embedder → resolve → score) — assumption A-4.
6. **Deploy smoke:** after deploy, hit the leaderboard, an analyst page, a receipt; confirm monitoring
   receives events; confirm the cold-cache leaderboard query is < 2s at real volume (assumptions A-5/A-12).
7. **Rollback:** append-only ledger (NFR-3) — correct a bad scoring change via `recompute_all` into a new
   `score_run` (AC-4); correct a bad resolution by appending a superseding row. No destructive edit exists.

## 7. Assumptions to eliminate (verify before relying on them; do not preserve stale ones)

| # | Assumption (currently unverified) | Disposition |
| --- | --- | --- |
| A-1 | AC-1 golden gate reflects live model quality | **eliminate**: re-run on real `LlmExtractor` output (G7) |
| A-2 | The demo board / FAS inversion holds on real data | validate after the real backfill (G6) |
| A-3 | Base rates are genuine priors | validate on real 5-year history (degenerate 0/1 on 18-mo fixtures today) |
| A-4 | Mock-first fake == real adapter behavior | validate via a per-adapter end-to-end smoke (§6.5) |
| A-5 / A-12 | Leaderboard p95 < 2s at 50-analyst scale | benchmark cold-cache on real volume; add the MV/index if needed |
| A-6 | Trust-ops jobs are scheduled in prod | **eliminate**: ship a concrete scheduler (no mechanism exists) |
| A-14 | An erasure owner exists | **eliminate now**: name a human (GO blocker) |
| A-15 | Spend caps match the real budget | calibrate via a single-channel cost pilot before draining |
| — | "make check green ⇒ the real pipeline works" | **false**: real adapter paths are unexercised (confirmed) |

## 8. Binding constraints (violations are session failures)

- **AC-7** regulatory firewall (`scripts/copy_lint.py`); **NFR-3** append-only ledger (triggers);
  **mock-first** for every external service (the fake stays the CI path); **boring stack locked** (no dep
  without approval + an ADR; never commit a key); **scope lock** (crypto + YouTube only; no auth/payments;
  quotes ≤ 15 words). **No scoring/methodology change** — v1.1 and the binding worked examples
  (`tests/test_fas.py`: FAS_A≈47.02, FAS_B≈66.74, B-outranks-A, k=25, min n=20) must not move.
- **Definition of done** = `make check` green + the `TASKS.md` checkbox + a matching `LOG.md` DONE line.

## 9. Orchestration (if you use workflows)

The orchestrator (main loop) owns LOG.md, TASKS.md, EX-dept.md, the ADR statuses, and git; subagents RETURN
findings only and write nothing to the ledger. After every subagent batch, verify the working tree for
LOG/TASKS pollution and a stray `services/pipeline/LOG.md`, and clean it pre-commit. Run an adversarial
verification panel before any activation commit. One conventional commit per logical change. (This session's
audit used exactly this pattern — read-only agents, results synthesized by the orchestrator.)

## 10. Final phase — keep the two-file chain going (do not skip)

When a session completes a worklist, **rewrite this file** with the successor worklist and **append the
finished worklist to `past-prompts.md`** (under a `## ═══ <name> ═══` header), in a small `chore:` commit.
Do **not** create a new `PROMPT-*.md`. Append a `LOG.md` NOTE recording the rewrite.
- If production becomes **GO** (all gates closed, backfill run, keys live), make this file the operations
  handoff: deploy steps, scheduled-jobs cron, monitoring dashboards, dispute/erasure on-call playbook, and the
  first-week launch-metric watch (G4).
- If still **NO-GO**, rewrite this file with exactly which gates remain and the precise steps.
