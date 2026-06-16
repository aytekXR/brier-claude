# Session prompt — Production cutover (launch readiness assessed: NO-GO on operational gates)

Copy everything below the line into a fresh Claude Code session started at the repo root on the
**Ubuntu 24.04 VPS**. Like `PROMPT-E5.md`/`PROMPT-E6.md`/`PROMPT-LAUNCH.md`, **this file is committed to
the repo on purpose** so it travels with `git clone` and is the first thing you read. The six MVP build
epics are done and the launch-readiness review is complete; the verdict was **NO-GO**, gated only on
operational steps (real credentials, heavy-dependency installs, the real roster + backfill). This prompt
drives the **production cutover** — closing those gates and flipping to GO.

---

## Environment — Ubuntu 24.04 VPS (READ FIRST)

Same as PROMPT-LAUNCH.md. Verify the toolchain, then bring the DB up:

- **Repo root (`$REPO`).** `cd` into your clone; run every command from there.
- **Docker = Engine + systemd (no Desktop).** Daemon auto-starts; if down, `sudo systemctl start docker`.
  **Hard-won gotcha:** the dev user is in the `docker` group in `/etc/group` but the *login session predates
  it*, so `docker` is permission-denied. Wrap docker/compose/`make seed`/`make pipeline-demo`/`make ci` in
  `sg docker -c '...'`. `make check` and `make web-build` need no docker once the DB container is up.
- **Node ≥20 + the pipeline venv** are installed (Node via nvm symlinked into `~/.local/bin`; venv at
  `services/pipeline/.venv`).
- **First-run acceptance test — must pass before any cutover work:**
  ```bash
  sg docker -c 'make ci'    # migrate+seed → make check → pipeline-demo → web-build
  ```
  Expect: `make check` green (**766 pytest + 1 benign skip**; copy-lint + ruff + ruff-format + mypy strict +
  tsc + eslint clean), the demo board **NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7** (20 cumulative
  resolutions), and the Next build clean. If red, fix the *environment* (not the code) until green. The same
  sequence runs in CI on every push (`.github/workflows/ci.yml` now has a Postgres service container, so the
  full DB-backed suite + the e2e demo + the web build all gate every push).

---

You are the lead engineer on **Brier**. **E1–E6 are complete and committed**, and the **launch-readiness
review (2026-06-16) is done**. What changed since PROMPT-LAUNCH.md:

- **ADR gate walked.** Accepted: 0001/0002/**0005**/0006/0007/**0010**/**0011**/**0012**/**0013**/**0014**.
  0011 + 0012 are no-dep, nothing to activate. 0005/0010/0013/0014 are accepted *decisions* whose live
  activation is just a production env key. Still **proposed** (heavy-dependency seams, approve before
  installing): **0003** faster-whisper, **0004** boto3/R2, **0008** sentence-transformers, and optionally a
  CCXT ADR for **0009**'s EC-8 cross-check.
- **CI/CD hardened.** CI now runs a Postgres (pgvector) service container, so the ~23 DB-backed test files
  that previously *silently skipped* in CI now run on every push; CI also runs the end-to-end `pipeline-demo`
  smoke and the Next `web-build`. New guard tests landed: `test_migrations.py` (idempotent/complete
  migrations + NFR-3 triggers) and `test_seams.py` (mock-first `get_alerter` contract). New Make targets:
  `make web-build`, `make ci` (the full launch-style verification), and `db-up` is a no-op when
  `BRIER_DB_EXTERNAL=1` (the CI path).
- **Verdict: NO-GO**, recorded in `docs/LAUNCH-READINESS.md`. The full activation/backfill/deploy sequence is
  `docs/RUNBOOK-PRODUCTION.md` — **that runbook is your worklist this session.**

## Your mission: execute the cutover (close the NO-GO gates, then flip to GO)

Work `docs/RUNBOOK-PRODUCTION.md` top to bottom. **Do not add any dependency or call any live external API
without explicit human approval, and never commit a key.** The remaining gates, in order:

1. **Acceptance test green** on the deploy box (`make ci`).
2. **Approve the heavy-dependency ADRs** you intend to run (0003/0004/0008, optional 0009): flip ADR status →
   add the pinned **optional extra** to `pyproject.toml` → install on the dedicated host only (GPU box for
   whisper; dedup host for embeddings) → tick the TASKS.md box (E2-T4/E2-T5/E3-T5) → move the EX-dept entry to
   **Resolved**. Activating a real adapter must not regress `make check` (the fake stays the CI path).
3. **Set the production credentials** (env only, never committed): `BRIER_ANTHROPIC_API_KEY` (extraction),
   `BRIER_RESEND_API_KEY` (dispute email), `BRIER_BUTTONDOWN_API_KEY` (newsletter), and
   `BRIER_BETTER_STACK_TOKEN`/`BRIER_SENTRY_DSN` (monitoring).
4. **Roster ingest — G1:** build the real 50-analyst roster JSON and
   `python -m brier_pipeline.ingestion.registry import-roster <file>` (crypto + YouTube only; scope lock).
5. **24-month backfill — G3:** enqueue `backfill_channel(..., months=24, max_videos=<cap>)` per channel, then
   drain with the jobs worker (`run_forever`): transcribe → extract → resolve_claims → score_analysts. Mind
   the NFR-5 spend caps (set them to the real monthly budget first). Verify **≥ 10,000 resolved claims**.
6. **Golden-set on REAL model output — AC-1/G2:** with the LLM key live, re-run `tests/test_golden_set.py`
   against real extraction; require **precision ≥ 95% & recall ≥ 80%**.
7. **Schedule the trust-ops jobs** (poll_channels ≤2h, freshness_check, resolve_claims, score_analysts,
   deletion_sweep, dispute_sla_check, weekly_dispute_report, erasure_sla_check) and wire monitoring.
8. **Final compliance:** AC-7 copy-lint clean on the final build; NFR-6 `/about` notice + named erasure owner;
   NFR-3 spot check (UPDATE/DELETE on `resolutions` raises); v1.1 scoring + the binding worked examples
   unchanged.

## Launch-quality items the readiness audit surfaced (fix during cutover — see `docs/LAUNCH-READINESS.md`)

The 18-agent adversarial readiness audit found four tracked defects in otherwise-DONE work. They do not
block the NO-GO decision (the hard gates above dominate) but must be closed before GO:

1. **AC-3 trend column is non-functional.** `apps/web/app/page.tsx:174,229` always passes `[]`/`null` to
   `TrendSparkline`; real per-analyst trend points are never fetched. Wire a trend series (FAS over recent
   `score_runs`) into `getLeaderboard` and pass it through. FAS/n/falsifiability are already ledger-exact.
2. **Backfill job handlers are unregistered.** `transcribe` / `extract` / `resolve_claims` / `score_analysts`
   exist only as direct functions (the demo path); they are NOT registered as `jobs` handlers, so
   `backfill_channel`'s enqueued `transcribe` jobs have no processor. Register them (gated on
   ADR-0003/0004/0008) as part of backfill activation.
3. **Worker bootstrap imports nothing.** `run_forever` auto-discovers no handlers; the production worker must
   import every handler module first (poller/deletion/freshness/sla/erasure + the backfill handlers). See
   `docs/RUNBOOK-PRODUCTION.md` §3. Consider adding a single `python -m brier_pipeline.jobs.worker`-style
   entrypoint that imports all handlers.
4. **AC-5 UF-3 analyst notification.** The disputer is emailed the ticket id, but the analyst is not notified
   on adjudication. Confirm against PRD scope and wire if required.

## Read first (in this order)

1. `CLAUDE.md` — conventions + the binding 5-rule logging contract.
2. `docs/LAUNCH-READINESS.md` — the go/no-go assessment + per-AC / per-goal evidence and the remaining gates.
3. `docs/RUNBOOK-PRODUCTION.md` — the step-by-step activation + backfill + deploy + on-call runbook.
4. `EX-dept.md` — the seam-activation worklist (E2-T4/E2-T5/E3-T5 + the optional CCXT sub-item).
5. `docs/adr/0003`,`0004`,`0008`,`0009` — the heavy-dependency ADRs still pending approval.
6. `TASKS.md` (E2-T4/E2-T5/E3-T5 unticked, blocked-by-design) and the `LOG.md` tail.

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

After the cutover work, the last phase must **write the next session prompt into the repo root** and commit
it in a small `chore:`:
- If production is now **GO** (all gates closed, backfill run, keys live), write `PROMPT-RUNBOOK.md`: the
  deploy steps actually taken, the scheduled-jobs cron, the monitoring dashboards, the dispute/erasure
  on-call playbook, and the first-week launch-metric watch (G4) — and end it with an operations-handoff
  instruction.
- If still **NO-GO** (some gate remains), write `PROMPT-CUTOVER.md`'s successor capturing exactly which gates
  remain and the precise steps — and have it **end with this same Final-phase instruction**.
Append a LOG.md NOTE recording which prompt was written, mention it in the closing report, and commit it.
This is what makes the chain self-perpetuating: every prompt closes by generating the next.
