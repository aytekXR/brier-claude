# Brier — Master entry prompt (START HERE)

You are the lead engineer on **Brier**, a prediction track-record engine that scores crypto-YouTube
analysts on the accuracy of their public predictions, with clip-level receipts. This file is the **single
entry point** for any new session: it tells you the project state and which prompt to open next. It is
committed to the repo on purpose so it travels with `git clone`.

## 1. What to read, in order

1. **`CLAUDE.md`** — conventions + the binding 5-rule logging contract (this overrides default behavior).
2. **This file** — orientation + which prompt is active.
3. **`docs/LAUNCH-READINESS.md`** — the current go/no-go assessment (verdict + per-AC/goal status + the
   remaining gates). Read this to know exactly where the product stands.
4. **The ACTIVE session prompt** (see §3) — your actual worklist this session.

## 2. Where the project stands (as of 2026-06-16)

- **All six MVP build epics are complete and committed** (E1 Walking Skeleton → E6 Trust+Ops). Every
  `TASKS.md` item is ticked or recorded blocked-by-design in `EX-dept.md`.
- **Launch-readiness review is done. Verdict: NO-GO** for the first production deploy — gated on operational
  steps, not code defects. Full evidence in `docs/LAUNCH-READINESS.md`.
- **CI/CD is hardened and green on a clean checkout:** `.github/workflows/ci.yml` runs a pgvector Postgres
  service so the full DB-backed suite + the end-to-end `pipeline-demo` smoke + the Next `web-build` gate
  every push. Local equivalent: `sg docker -c 'make ci'`.
- **Acceptance test (must hold):** `make check` green (**767 passed + 1 benign skip**); `make pipeline-demo`
  prints the canonical board **NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7** (20 cumulative resolutions);
  `make web-build` clean.

## 3. The prompt chain — which one is ACTIVE

Each session closes by writing the next session's prompt (self-perpetuating). The chain so far:

`PROMPT-E5.md` → `PROMPT-E6.md` → `PROMPT-LAUNCH.md` → **`PROMPT-CUTOVER.md` ← ACTIVE: open this next.**

**Start here now:** read `PROMPT-CUTOVER.md`. It is the production-cutover worklist (close the NO-GO gates,
then flip to GO) and opens with an explicit **"Roles & handoff"** section. Its companion is
`docs/RUNBOOK-PRODUCTION.md` (the step-by-step activation + backfill + deploy runbook).

> If `PROMPT-CUTOVER.md` has been superseded by a newer `PROMPT-*.md` (e.g. `PROMPT-RUNBOOK.md` once
> production is GO), open the newest one instead — and update the arrow above.

## 4. Roles & handoff — who does what

This is a **gated** project. The agent does the engineering; several gates are the **human owner's call**,
and the agent must STOP and ask at each one.

- **Human owner provides:** ADR approvals for heavy dependencies (0003 faster-whisper, 0004 boto3/R2, 0008
  sentence-transformers, optional 0009-CCXT); production credentials as env vars (never committed —
  `BRIER_ANTHROPIC_API_KEY`, `BRIER_RESEND_API_KEY`, `BRIER_BUTTONDOWN_API_KEY`,
  `BRIER_BETTER_STACK_TOKEN`/`BRIER_SENTRY_DSN`); infrastructure (GPU host, R2 bucket, spend budget); the
  50-analyst roster source; the named erasure owner; and the **final GO call**.
- **Agent does:** run the acceptance test; perform each seam activation once the human approves the
  dep/key and re-verify the gate stays green (the fake stays the CI path); ingest the roster; run the
  24-month backfill to ≥10k resolutions; re-run the golden gate on real model output; schedule the
  trust-ops jobs; wire monitoring; fix the tracked launch-quality defects; update the ledgers; commit per
  logical change; push; and **write the next session's prompt**.

## 5. Binding constraints (violations are session failures)

- **AC-7** regulatory firewall — never output buy/sell/hold or recommendation language (`scripts/copy_lint.py`
  enforces it; runs in `make check` + CI).
- **NFR-3** append-only ledger — `resolutions`/`scores` are never updated/deleted; corrections append a
  superseding row (DB triggers enforce).
- **Mock-first** — every external service sits behind a seam with a fixture-backed fake; the fake is the CI
  path. **Never add a dependency or call a live external API without explicit human approval + an ADR; never
  commit a key.**
- **Scope lock** — crypto + YouTube only; no equities/X/podcasts/auth/payments; quotes ≤ 15 words.
- **No scoring/methodology change** — v1.1 and the binding worked examples (`tests/test_fas.py`: FAS_A≈47.02,
  FAS_B≈66.74, B-outranks-A, k=25, min n=20) must not move.
- **Definition of done** = `make check` green + the `TASKS.md` checkbox + a matching `LOG.md` DONE line.

## 6. First action this session

```bash
cd "$REPO"
sg docker -c 'make ci'     # migrate+seed → make check → pipeline-demo → web-build; must be green
```
Then open **`PROMPT-CUTOVER.md`** and work it top to bottom, stopping to ask the human at each gated step.

## 7. Orchestration note (hard-won)

The orchestrator (main loop) owns `LOG.md`, `TASKS.md`, `EX-dept.md`, ADR statuses, and git. Subagents
RETURN findings only and must write nothing to the ledger — **even read-only agents with Bash can write
files**, so after every subagent batch verify the working tree (`git status`) for `LOG.md`/`TASKS.md`
pollution and a stray `services/pipeline/LOG.md`, and clean it before committing. A real example: a
launch-readiness audit agent left a (correct) test fix in the working tree; it was caught by the tree check,
independently verified, and committed. Always verify, never blindly trust or discard.
