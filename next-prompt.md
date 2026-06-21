# Brier — next-prompt (START HERE)

You are the lead engineer on **Brier**, a prediction track-record engine that scores crypto-YouTube
analysts on the accuracy of their public predictions, with clip-level receipts. **This file is the single
live entry point for any new session** — it holds the current state and the active worklist. It is committed
to the repo on purpose so it travels with `git clone`.

> **The prompt system is two files (and only two):**
> - **`next-prompt.md`** (this file) — current state + what to do next.
> - **`past-prompts.md`** — the archive of every completed prompt (E1 → … → CUTOVER round 1 + the old MASTER index).
>
> **Binding rule:** do **not** create new `PROMPT-*.md` files. When this session finishes, append the worklist
> it just completed to the bottom of `past-prompts.md` (under a `## ═══ <name> ═══` header) and rewrite this
> file with the successor worklist. That is what keeps the chain self-perpetuating with a tidy repo root.

## 1. What to read, in order

1. **`CLAUDE.md`** — conventions + the binding 5-rule logging contract (overrides default behavior).
2. **This file** — state + the active worklist.
3. **`docs/LAUNCH-READINESS.md`** — the go/no-go assessment (verdict + per-AC/goal status + remaining gates).
4. **`docs/RUNBOOK-PRODUCTION.md`** — the step-by-step activation + backfill + deploy + on-call runbook (your companion this session).

## 2. Where the project stands (as of 2026-06-18)

- **All six MVP build epics are complete and committed** (E1 → E6). Every `TASKS.md` item is ticked or
  recorded blocked-by-design in `EX-dept.md`.
- **Launch-readiness review done. Verdict: NO-GO** for the first production deploy — gated on operational
  steps, not code defects. Full evidence in `docs/LAUNCH-READINESS.md`.
- **Cutover round 1 (2026-06-18) closed every ungated launch-quality code defect** — AC-3 trend (`630afb8`),
  worker bootstrap + scheduled-ops handlers (`8dc908e`), AC-5/UF-3 analyst notification (`4fe62b6`); all
  mock-first, no new deps/keys, adversarially verified (4-agent refute panel, zero blockers). The
  `transcribe`/`extract` handler registration and the AC-1/G2 golden re-run remain part of the **human-gated
  activation**. Verdict still **NO-GO** on the hard gates.
- **CI/CD hardened and green on a clean checkout:** `.github/workflows/ci.yml` runs a pgvector Postgres
  service so the full DB-backed suite + the `pipeline-demo` smoke + the `web-build` gate every push.
- **Acceptance test (must hold):** `make check` green (**775 passed + 1 benign skip**); `make pipeline-demo`
  prints the canonical board **NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7** (20 cumulative resolutions);
  `make web-build` clean.

## 3. Environment — Ubuntu 24.04 VPS (READ FIRST)

- **Repo root (`$REPO`).** `cd` into your clone; run every command from there.
- **Docker = Engine + systemd (no Desktop).** Wrap docker/compose/`make seed`/`make pipeline-demo`/`make ci`
  in `sg docker -c '...'` (the dev login session predates the `docker` group). `make check` and `make web-build`
  need no docker once the DB container is up.
- **First-run acceptance test — must pass before any activation work:**
  ```bash
  sg docker -c 'make ci'    # migrate (incl. 0009) + seed → make check → pipeline-demo → web-build
  ```
  Expect: `make check` green (**775 pytest + 1 benign skip**), the demo board **NorthChain 59.0 /
  VectorEdge 57.5 / Aylin 51.7**, and the Next build clean. If red, fix the *environment* (not the code).

## 4. Roles & handoff — who does what (read first)

This is a **gated** session: the agent does the engineering, but every remaining gate is the **human owner's
call**, and the agent must STOP and ask at each one. Nothing proceeds past a gate without the human.

**You, the human owner, must provide (the agent cannot self-serve these):**
- **ADR approvals** for the heavy dependencies — `0003` faster-whisper, `0004` boto3/R2, `0008`
  sentence-transformers (and optional CCXT for `0009`'s EC-8 cross-check). No dependency lands without it.
- **Production credentials** (env only, never committed): `BRIER_ANTHROPIC_API_KEY`, `BRIER_RESEND_API_KEY`,
  `BRIER_BUTTONDOWN_API_KEY`, `BRIER_BETTER_STACK_TOKEN`/`BRIER_SENTRY_DSN`, optional `BRIER_COINGECKO_API_KEY`;
  and the **analyst `notify_email` values** (in the roster JSON) you want notified.
- **Infrastructure** — the rented GPU host (whisper backfill), the Cloudflare R2 bucket + creds, the monthly
  spend budget, the **named erasure-request owner** (NFR-6), and which channels make up the 50-analyst roster.
- **The final GO call.**

## 5. The active worklist — execute the activation (close the NO-GO gates, then flip to GO)

Work `docs/RUNBOOK-PRODUCTION.md` top to bottom. **Do not add any dependency or call any live external API
without explicit human approval, and never commit a key.** Remaining gates, in order:

1. **Acceptance test green** on the deploy box (`make ci` → 775 + 1 skip).
2. **Approve the heavy-dependency ADRs** (0003/0004/0008): flip ADR status → add the pinned **optional extra**
   to `pyproject.toml` → install on the dedicated host only (GPU box for whisper; dedup host for embeddings) →
   tick the TASKS.md box (E2-T4/E2-T5/E3-T5) → move the EX-dept entry to **Resolved**. Activating a real
   adapter must not regress `make check` (the fake stays the CI path).
3. **Register the `transcribe` + `extract` handlers** (the deferred half of the backfill-handler defect):
   add them to `jobs/handlers.py` wired to the now-installed real adapters via their seams, and add them to
   `bootstrap_handlers()` in `jobs/worker.py`. They were intentionally left out of cutover round 1 because a
   fake-by-default transcribe handler would silently produce fixture transcripts for real videos — wire them
   only once the real adapters exist (this gate). Re-verify `make check` stays green with the fakes in CI.
4. **Set the production credentials** (env only). Populate `analysts.notify_email` via the roster JSON
   (`notify_email` field) or `python -m brier_pipeline.ingestion.registry add --notify-email ...`.
5. **Roster ingest — G1:** build the real 50-analyst roster JSON (crypto + YouTube only; scope lock) and
   `python -m brier_pipeline.ingestion.registry import-roster <file>`.
6. **24-month backfill — G3:** enqueue `backfill_channel(..., months=24, max_videos=<cap>)` per channel, then
   drain with `python -m brier_pipeline.jobs.worker` (transcribe → extract → resolve_claims → score_analysts).
   Set the NFR-5 spend caps to the real budget first. Verify **≥ 10,000 resolved claims**.
7. **Golden-set on REAL model output — AC-1/G2:** with the LLM key live, re-run `tests/test_golden_set.py`
   against real extraction; require **precision ≥ 95% & recall ≥ 80%**.
8. **Schedule the trust-ops jobs** (poll_channels ≤2h, freshness_check, resolve_claims, score_analysts,
   deletion_sweep, dispute_sla_check, weekly_dispute_report, erasure_sla_check) and wire monitoring.
9. **Final compliance:** AC-7 copy-lint clean; NFR-6 `/about` notice + named erasure owner; NFR-3 spot check
   (UPDATE/DELETE on `resolutions` raises); v1.1 scoring + the binding worked examples unchanged.

## 6. Binding constraints (violations are session failures)

- **AC-7** regulatory firewall (`scripts/copy_lint.py`); **NFR-3** append-only ledger (triggers);
  **mock-first** for every external service (the fake stays the CI path); **boring stack locked** (no dep
  without approval + an ADR; never commit a key); **scope lock** (crypto + YouTube only; no auth/payments;
  quotes ≤ 15 words). **No scoring/methodology change** — v1.1 and the binding worked examples
  (`tests/test_fas.py`: FAS_A≈47.02, FAS_B≈66.74, B-outranks-A, k=25, min n=20) must not move.
- **Definition of done** = `make check` green + the `TASKS.md` checkbox + a matching `LOG.md` DONE line.

## 7. Orchestration (if you use workflows)

The orchestrator (main loop) owns LOG.md, TASKS.md, EX-dept.md, the ADR statuses, and git; subagents RETURN
findings only and write nothing to the ledger (the hard-won E2–E6 lesson — after every subagent batch verify
the working tree for LOG/TASKS pollution and a stray `services/pipeline/LOG.md`, and clean it pre-commit).
Run an adversarial verification panel before any activation commit. One conventional commit per logical change.

## 8. Final phase — keep the two-file chain going (do not skip)

After the activation work, the last phase **rewrites this file (`next-prompt.md`)** with the successor worklist
and **appends the worklist you just finished to `past-prompts.md`** (under a `## ═══ <name> ═══` header), in a
small `chore:` commit. Do **not** create a new `PROMPT-*.md`.
- If production is now **GO** (all gates closed, backfill run, keys live), make this file the operations
  handoff: the deploy steps taken, the scheduled-jobs cron, the monitoring dashboards, the dispute/erasure
  on-call playbook, and the first-week launch-metric watch (G4).
- If still **NO-GO**, rewrite this file with exactly which gates remain and the precise steps.
Append a `LOG.md` NOTE recording the rewrite, mention it in the closing report, and commit. Every session
closes by updating these two files — never a third.
