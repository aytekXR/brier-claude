# Session prompt — Production cutover, round 2 (code defects closed; NO-GO on the human-gated activation)

Copy everything below into a fresh Claude Code session started at the repo root on the **Ubuntu 24.04 VPS**.
Like its predecessors (`PROMPT-LAUNCH.md` → `PROMPT-CUTOVER.md`), **this file is committed to the repo on
purpose** so it travels with `git clone`. The six MVP build epics are done, the launch-readiness review is
complete (verdict **NO-GO**), and the **2026-06-18 cutover session closed every ungated launch-quality code
defect**. What remains is the **human-gated activation** — real dependencies, real credentials, real data —
plus the final GO call. This prompt drives that activation.

---

## Environment — Ubuntu 24.04 VPS (READ FIRST)

Same as `PROMPT-CUTOVER.md`. Verify the toolchain, then bring the DB up:

- **Repo root (`$REPO`).** `cd` into your clone; run every command from there.
- **Docker = Engine + systemd (no Desktop).** Wrap docker/compose/`make seed`/`make pipeline-demo`/`make ci`
  in `sg docker -c '...'` (the dev login session predates the `docker` group). `make check` and
  `make web-build` need no docker once the DB container is up.
- **First-run acceptance test — must pass before any activation work:**
  ```bash
  sg docker -c 'make ci'    # migrate (incl. 0009) + seed → make check → pipeline-demo → web-build
  ```
  Expect: `make check` green (**775 pytest + 1 benign skip**; copy-lint + ruff + ruff-format + mypy strict +
  tsc + eslint clean), the demo board **NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7** (20 cumulative
  resolutions), and the Next build clean. Same sequence runs in CI on every push.

---

## What changed since `PROMPT-CUTOVER.md` (2026-06-18 cutover session)

All four tracked launch-quality **code** defects are closed, mock-first, with **zero new dependencies and
zero keys**, adversarially verified (a 4-agent read-only refute panel returned CONFIRMED, zero blockers):

- **AC-3 trend (`630afb8`)** — `getLeaderboard` wires a real per-analyst 90-day FAS series into
  `LeaderboardRow.trend`; the leaderboard renders a real sparkline (honest per-analyst "—" when <2 dates).
- **Worker bootstrap (`8dc908e`)** — `jobs/worker.py` `bootstrap_handlers()` + the
  `python -m brier_pipeline.jobs.worker` entrypoint register all 8 scheduled-ops handlers deterministically.
- **Scheduled-ops handlers (`8dc908e`)** — `jobs/handlers.py` registers `resolve_claims` + `score_analysts`
  (mock-first price seam: `FakePriceSource` in CI, CoinGecko only when `BRIER_COINGECKO_API_KEY` is set).
- **AC-5/UF-3 analyst notification (`4fe62b6`)** — migration `0009` adds nullable `analysts.notify_email`;
  `record_adjudication` notifies the **claim author** on upheld+corrected when the email is known.

Full evidence in `docs/LAUNCH-READINESS.md` (the worklist now shows DONE/PARTIAL/PENDING per item),
`EX-dept.md`, and the `LOG.md` CUTOVER lines.

## Roles & handoff — who does what (unchanged, read first)

This is a **gated** session: the agent does the engineering, but every remaining gate is the **human owner's
call**, and the agent must STOP and ask at each one. Nothing proceeds past a gate without the human.

**You, the human owner, must provide (the agent cannot self-serve these):**
- **ADR approvals** for the heavy dependencies — `0003` faster-whisper, `0004` boto3/R2, `0008`
  sentence-transformers (and optional CCXT for `0009`'s EC-8 cross-check). No dependency lands without it.
- **Production credentials** (env only, never committed): `BRIER_ANTHROPIC_API_KEY`, `BRIER_RESEND_API_KEY`,
  `BRIER_BUTTONDOWN_API_KEY`, `BRIER_BETTER_STACK_TOKEN`/`BRIER_SENTRY_DSN`, optional
  `BRIER_COINGECKO_API_KEY`; and the **analyst `notify_email` values** (in the roster JSON) you want notified.
- **Infrastructure** — the rented GPU host (whisper backfill), the Cloudflare R2 bucket + creds, the monthly
  spend budget, the **named erasure-request owner** (NFR-6), and which channels make up the 50-analyst roster.
- **The final GO call.**

## Your mission: execute the activation (close the remaining NO-GO gates, then flip to GO)

Work `docs/RUNBOOK-PRODUCTION.md` top to bottom. **Do not add any dependency or call any live external API
without explicit human approval, and never commit a key.** Remaining gates, in order:

1. **Acceptance test green** on the deploy box (`make ci` → 775 + 1 skip).
2. **Approve the heavy-dependency ADRs** (0003/0004/0008): flip ADR status → add the pinned **optional extra**
   to `pyproject.toml` → install on the dedicated host only (GPU box for whisper; dedup host for embeddings) →
   tick the TASKS.md box (E2-T4/E2-T5/E3-T5) → move the EX-dept entry to **Resolved**. Activating a real
   adapter must not regress `make check` (the fake stays the CI path).
3. **Register the `transcribe` + `extract` handlers** (the deferred half of the backfill-handler defect):
   add them to `jobs/handlers.py` wired to the now-installed real adapters via their seams, and add them to
   `bootstrap_handlers()` in `jobs/worker.py`. They were intentionally left out this round because a
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

## Read first (in this order)

1. `CLAUDE.md` — conventions + the binding 5-rule logging contract.
2. `docs/LAUNCH-READINESS.md` — go/no-go + the updated tracked-worklist (DONE/PARTIAL/PENDING).
3. `docs/RUNBOOK-PRODUCTION.md` — the step-by-step activation + backfill + deploy + on-call runbook.
4. `EX-dept.md` — the seam-activation worklist (E2-T4/E2-T5/E3-T5 + the launch-readiness findings section).
5. `docs/adr/0003`,`0004`,`0008`,`0009` — the heavy-dependency ADRs still pending approval.

## Binding constraints (unchanged — violations are session failures)

- **AC-7** regulatory firewall (`scripts/copy_lint.py`); **NFR-3** append-only ledger (triggers);
  **mock-first** for every external service (the fake stays the CI path); **boring stack locked** (no dep
  without approval + an ADR); **scope lock** (crypto + YouTube only; no auth/payments; quotes ≤ 15 words).
  **No scoring/methodology change** — v1.1 and the binding worked examples (`tests/test_fas.py`: FAS_A≈47.02,
  FAS_B≈66.74, B-outranks-A, k=25, min n=20) must not move.

## Orchestration (if you use workflows)

The orchestrator (main loop) owns LOG.md, TASKS.md, EX-dept.md, the ADR statuses, and git; subagents RETURN
findings only and write nothing to the ledger (the hard-won E2–E6 lesson — after every subagent batch verify
the working tree for LOG/TASKS pollution and a stray `services/pipeline/LOG.md`, and clean it pre-commit).
Run an adversarial verification panel before any activation commit. One conventional commit per logical
change; commit the ledger at the close.

## Final phase — keep the chain going (do not skip)

After the activation work, the last phase must **write the next session prompt into the repo root** and
commit it in a small `chore:`:
- If production is now **GO** (all gates closed, backfill run, keys live), write `PROMPT-RUNBOOK.md`: the
  deploy steps actually taken, the scheduled-jobs cron, the monitoring dashboards, the dispute/erasure
  on-call playbook, and the first-week launch-metric watch (G4) — end it with an operations-handoff note.
- If still **NO-GO** (some gate remains), write this prompt's successor (`PROMPT-CUTOVER-3.md`) capturing
  exactly which gates remain and the precise steps — and have it **end with this same Final-phase
  instruction**.
Append a LOG.md NOTE recording which prompt was written, update `PROMPT-MASTER.md`'s arrow, mention it in the
closing report, and commit it. Every prompt closes by generating the next — that is what makes the chain
self-perpetuating.
