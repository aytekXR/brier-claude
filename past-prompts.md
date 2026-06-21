# Brier — Past session prompts (archive)

This file is the **single archive of completed session prompts**. Brier's sessions are
self-perpetuating: each closes by writing the next session's worklist. To keep the repo root tidy,
the prompt chain now lives in exactly **two files**:

- **`next-prompt.md`** — the live entry point + the active worklist (what to do next). **Start here.**
- **`past-prompts.md`** (this file) — every completed prompt, in order, for history.

**The rule going forward (binding):** when a session finishes, it appends the prompt it just
completed to the bottom of this file (under a `## ═══ <name> ═══` header) and rewrites
`next-prompt.md` with the successor worklist. **No new `PROMPT-*.md` files — only these two.**

The chain so far (all complete): `E1 → E1B → E2 → E3 → E4 → E5 → E6 → LAUNCH → CUTOVER (round 1)`.
`PROMPT-MASTER.md` (the former entry index) is archived at the end. The active worklist that followed
CUTOVER round 1 — the human-gated production activation — now lives in `next-prompt.md`.

---


## ═══════════════════════ PROMPT-E1.md ═══════════════════════

# Session prompt — Implement Epic E1 (Walking Skeleton) via workflows

Copy everything below the line into a fresh Claude Code session started at the repo root
(`/Users/ae/repo/brier-claude`). This file is session tooling, not product code — delete it
(or leave it untracked) once the session is launched.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube
analysts). The repository skeleton is complete and committed (HEAD `51fb7bd`, `make check`
green, 18 tests). Your mission this session: **implement Epic E1 — Walking Skeleton — end to
end (tasks E1-T1 through E1-T5 in TASKS.md), driving each task to the Definition of Done.**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to
workflows for this session. Orchestrate the epic with the scoped subagents that already exist
in `.claude/agents/` (`pipeline-engineer`, `scoring-quant`, `frontend-engineer`,
`qa-reviewer`) — pass them via the Workflow `agentType` option or the Agent tool's
`subagent_type`.

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, and the **binding 5-rule logging contract**.
2. `TASKS.md` — the E1 task definitions and acceptance criteria are authoritative.
3. `docs/METHODOLOGY.md` — the scoring spec. The two worked examples in it are **binding
   test cases**, not illustrations.
4. `docs/PRD.md` — at minimum HP-1, HP-2, FR-202, FR-301–FR-305, AC-3, AC-7.
5. `docs/BRANDKIT.md` — binding for anything E1-T5 renders.
6. `LOG.md` tail — confirm the last line is the SCAFFOLD DONE entry before appending.

## The five tasks and their dependency shape

- **E1-T1** (pipeline-engineer, no deps) — fixture dataset (~30 claims with realistic
  specificity spread, fixture transcripts the FakeExtractor replays, 18 months of BTC/ETH/SOL
  daily closes, precomputed fixture base rates per claim) + implement the five fakes
  (`FakeYouTubeClient`, `FakeTranscriber`, `FakeExtractor`, `FakePriceSource`,
  `LocalFSStorage`) + a `pipeline-demo` Makefile target that runs the thread and reports
  which stages are still pending.
- **E1-T2** (scoring-quant, deps: T1) — FAS engine in `brier_pipeline/scoring/fas.py`,
  exactly per METHODOLOGY.md. Unit tests must encode: **B outranks A despite a lower raw hit
  rate; A (60 claims, 68% raw) lands in the 45–60 band (≈54); B (24 claims, 58% raw) lands
  in the 60–80 band (≈71) and is flagged provisional; shrinkage k=25; minimum ranked n=20;
  provisional flag clears at n≥30.** Scores write to the append-only `scores` ledger under a
  `score_runs` row tagged with the methodology version.
- **E1-T3** (pipeline-engineer, deps: T1) — resolution v0: `resolve_target_by_deadline`,
  `resolve_directional_at_horizon` (partial credit 0.5), `resolve_open_claims`, close basis
  only, outcomes append to `resolutions` with rule_id + rationale + price citation. Canonical
  test: HP-2's "BTC daily close above $80k by Jul 31" resolves HIT on a qualifying close.
- **E1-T4** (pipeline-engineer, deps: T2+T3) — wire `make pipeline-demo` end to end:
  transcripts → FakeExtractor → claims → resolution → scoring → printed ranked board.
  Idempotent, re-runnable, works against a fresh `make seed` database.
- **E1-T5** (frontend-engineer, deps: T4) — four pages on real ledger data: leaderboard rows
  (rank, FAS badge, n, falsifiability, trend), analyst page (component bars, outcome chips,
  claim table), receipt page (claim card, placeholder player, real lightweight-charts price
  chart t0 → resolution). Numbers must match the ledger exactly (AC-3). copy-lint stays green.
- **Final** (qa-reviewer) — audit the session: diffs vs PRD acceptance criteria, TASKS.md
  checkboxes vs LOG.md DONE lines vs `git log`; file NOTE lines for any mismatch. qa-reviewer
  never fixes code.

Suggested workflow shape: **T1 → (T2 ∥ T3) → T4 → T5 → qa audit**, one phase per stage. T2
and T3 touch disjoint modules (`scoring/` vs `resolution/`) and may run in parallel in the
same tree, but see the serialization rules below.

## Orchestration rules (these prevent real races — follow them)

1. **The orchestrator (you, the main loop) owns LOG.md and git.** Subagents must not write
   LOG.md or commit. You append the STARTED line (attributed to the executing agent) before
   launching each task's agent, and the DONE line only after you have verified the gate.
   LOG.md is append-only — new lines at the bottom, never edit or reorder. Line format:
   `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`.
2. **Parallel agents run only scoped checks** (e.g. `services/pipeline/.venv/bin/pytest
   services/pipeline/tests/test_fas.py`). The full `make check` runs serially, by you, at
   each integration point — concurrent full gates race the venv/node_modules.
3. **One conventional commit per completed task**, made by you after its gate is green, e.g.
   `feat(scoring): FAS engine with worked-example tests (E1-T2)`. Commits end with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
4. **DoD triple per task:** `make check` green + TASKS.md checkbox ticked + LOG.md DONE line
   stating the verification evidence (test count) and modules touched. One without the others
   is a defect.
5. If a task is blocked or an agent fails after a retry, append a BLOCKED line with the
   reason and continue with whatever is unblocked; report it at the end.

## Binding constraints (violations are session failures)

- **Regulatory firewall (AC-7):** no buy/sell/hold/recommendation language in any
  user-visible copy — fixture claim quotes included. `scripts/copy_lint.py` enforces it; the
  fix for a violation is rewording the copy, never weakening the linter. The
  `copy-lint-ignore` marker is reserved for verbatim quoted evidence with a stated reason.
- **Append-only ledger:** `resolutions` and `scores` are never UPDATEd or DELETEd — DB
  triggers enforce it. Corrections append superseding rows via `supersedes_*_id`.
- **Scope lock:** crypto + YouTube only. Nothing from E2–E6 sneaks in.
- **Boring stack, locked:** no new dependencies, no formula changes, no stack deviations
  without my approval + an ADR (`docs/adr/`, via the `new-adr` skill). If METHODOLOGY.md
  turns out to be ambiguous on a formula detail, stop and ask me — do not improvise math.
- **Never silence a gate** (no `# type: ignore`, `# noqa`, eslint-disable, test deletion, or
  skipped assertions to get to green).
- Stubs carry `# TASK: <id>` markers — implementing a task means replacing its stubs and
  removing those markers.

## Environment notes (learned the hard way during scaffolding)

- Python 3.12 is at `python3.12` (Homebrew); the Makefile's `BOOTSTRAP_PY` already prefers
  it. The pipeline venv lives at `services/pipeline/.venv`.
- Docker CLI is `/usr/local/bin/docker` (Docker Desktop); background shells may not resolve
  bare `docker`. The dev DB: `docker compose up -d db`, then `make seed`.
- DB-backed tests **skip hermetically when the DB is down** — for any ledger-touching task
  (T2, T3, T4) bring the DB up first so the append-only trigger tests actually execute, and
  say so in the DONE evidence.
- `make check` = copy-lint → ruff (lint+format) → mypy strict → pytest → tsc → eslint.
  mypy needs `--config-file services/pipeline/pyproject.toml` (the Makefile handles it).
- The methodology page reads `docs/METHODOLOGY.md` via `path.join(process.cwd(), "..", "..")`
  — pages run with `apps/web` as cwd.
- Fixture analysts are fictional: NorthChain, Aylin Markets, VectorEdge
  (`data/fixtures/analysts.json`, slugs match). Keep new fixture data fictional and
  brandkit-voiced.

## Closing report (required)

End the session with: (1) per-task status table (DONE/BLOCKED + evidence line), (2) final
`make check` output summary, (3) `make pipeline-demo` output (the ranked board — confirm B
outranks A), (4) LOG.md tail, (5) `git log --oneline` for the session's commits, (6) the
next unblocked tasks (should be E2-T1, E2-T6, E3-T1, E4-T1, E4-T2 territory) with suggested
owners.


## ═══════════════════════ PROMPT-E1B.md ═══════════════════════

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube
analysts). Epic E1 is four-fifths done and committed (HEAD `008f12c`, `make check` green,
160 pytest + tsc + eslint + copy-lint + mypy strict all clean). Tasks E1-T1 through E1-T4
are DONE per the DoD triple (checkbox + LOG.md DONE line + green gate, one conventional
commit each: `e0b0432`, `ee33e2a`, `39c7f66`, `008f12c`). Your mission this session:
**implement E1-T5 (four pages rendering real ledger data) to the Definition of Done, then
run the qa-reviewer session audit and produce the closing report.**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to
workflows for this session. Use the scoped subagents in `.claude/agents/`
(`frontend-engineer`, `pipeline-engineer`, `qa-reviewer`) via the Workflow `agentType`
option, with adversarial verification panels before every gate.

## Current state (verified 2026-06-12)

- **Dev DB:** docker-compose Postgres, volume freshly recreated, `make seed` + two
  `make pipeline-demo` runs applied. Contents: 3 analysts, 14 videos, 14 transcripts,
  35 claims (26 resolved: 16 hits / 10 misses / 0 partials; 4 open future-deadline;
  2 conditional pending E4-T1; 3 non-falsifiable), 26 resolutions, score_runs ids 1 and 2
  (identical scores; the web must read the LATEST run). Docker Desktop may be stopped after
  a reboot: `open -a Docker`, wait for the daemon, then `make seed` is idempotent.
- **Scores (latest run, methodology v1.0):** Aylin Markets FAS 62.0 / n=10 / F 0.77;
  VectorEdge 61.2 / 7 / 0.78; NorthChain 58.1 / 9 / 0.69. All n < 20 ⇒ ALL provisional and
  unranked (FR-305) — the ranked board is honestly empty; pages must render that state
  without fabricating numbers.
- **The FAS inversion is the demo:** Aylin (62.0 at 60.0% raw hit rate) above NorthChain
  (58.1 at 66.7% raw). `make pipeline-demo` prints it; PRD HP-2's claim resolves HIT citing
  the 2025-07-14 close of 80,140.
- **Scoring conventions:** four ambiguity pins were human-approved and recorded in the
  METHODOLOGY.md §6 addendum + `docs/adr/0002-scoring-convention-pins.md` (version stays
  v1.0). Do not re-litigate them.
- **KNOWN GAP you must close first:** `price_daily` is EMPTY — resolution read fixture
  prices via FakePriceSource directly. The E1-T5 receipt chart (t0 → resolution) must read
  closes through `apps/web/lib/db.ts` (the web reads via lib/db.ts ONLY), so a
  pipeline-engineer must first add a small idempotent price-persist stage to
  `brier_pipeline/demo.py` (fixture closes → `price_daily`, check-before-insert or upsert
  on the (asset, day) PK), update tests, and re-run the demo. Log it as a NOTE-line
  addendum under E1-T4 (or fold it into the E1-T5 STARTED note); it is enablement, not a
  new task.

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, the binding 5-rule logging contract.
2. `TASKS.md` — E1-T5 acceptance text is authoritative; E1-T1..T4 are ticked.
3. `docs/BRANDKIT.md` — BINDING for everything E1-T5 renders: paper/ink ramp, FAS band
   colors only on badges and chart annotations, Source Serif 4 / IBM Plex Sans / IBM Plex
   Mono with tabular-nums on every numeric, 3px/6px radii, hairlines-not-boxes, chart
   marker spec (§5: utterance = Brier Blue dot, target = dashed ochre line, resolution =
   band-colored dot), voice rules (§7).
4. `docs/PRD.md` — FR-401..FR-404, AC-2 (chart t0→resolution), AC-3 (numbers match the
   ledger EXACTLY), AC-7, §19 web UI spec.
5. `docs/METHODOLOGY.md` — §6 two-tier provisional rule (n<20 unranked; 20≤n<30 ranked
   provisional; clears at 30); the /methodology page already renders this file.
6. `LOG.md` tail — confirm the last line is the E1-T4 DONE entry before appending.
7. `apps/web/` skeleton — `lib/db.ts` (extend; `postgres` package, server components
   only), `lib/types.ts` (FAS_BANDS exist), `app/page.tsx`, `app/a/[slug]/page.tsx`,
   `app/r/[claimId]/page.tsx`, `app/methodology/page.tsx`, the six component stubs in
   `components/` (FASBadge, TrendSparkline, ClaimStatusChip, ClaimTable, PriceChart,
   ReceiptPlayer). `lightweight-charts@4` is already a dependency (client component needed).

## The work

- **E1-T5** (frontend-engineer; pipeline-engineer only for the price_daily enablement
  above) — deps E1-T4 (done) · PRD FR-401–FR-404, AC-3:
  - **Leaderboard `/`**: ranked rows (rank, FAS badge with band color + provisional tag,
    n, falsifiability, 90-day trend) from the LATEST score_run; with all analysts n<20 the
    ranked table states the FR-305 rule and the provisional analysts render in a secondary
    list (PRD §19), ordered by FAS. Trend: only same-day history exists — render the
    honest empty/insufficient state, never a fabricated sparkline.
  - **Analyst `/a/[slug]`**: score header with FAS + four component bars (directional
    skill, calibration, consistency, falsifiability), outcome chip summary
    (hit/miss/partial/open/void counts), filterable claim table, each claim linking its
    receipt. Numbers from the scores/resolutions ledger exactly (AC-3).
  - **Receipt `/r/[claimId]`**: claim card (structured fields, verbatim quote ≤ 15 words),
    placeholder player (official embeds arrive in E5-T1 — placeholder states this
    honestly), real lightweight-charts price chart from `price_daily` rows t0 →
    resolution (or → today for open claims) with the three §5 markers, resolution
    rationale + rule_id + price citation from the resolutions row.
  - **Methodology** page already renders the doc — verify the §6 addendum renders and the
    version v1.0 + changelog show.
  - Mobile: tables collapse to stacked cards under 640px; WCAG AA; tabular-nums
    everywhere numeric; `copy-lint` stays green (it scans all apps/web strings).
- **Final** (qa-reviewer) — session audit: diffs vs PRD acceptance criteria (AC-3 and AC-7
  especially), TASKS.md checkboxes vs LOG.md DONE lines vs `git log` for the WHOLE epic
  (commits e0b0432..HEAD); qa-reviewer reports findings and never fixes code; the
  orchestrator appends any NOTE lines.

## Orchestration rules (same as the E1 session — they prevented real races)

1. The orchestrator (you, the main loop) owns LOG.md, TASKS.md checkboxes, and git.
   Subagents never write them and never commit. STARTED before launching, DONE only after
   you verify the gate. Line format:
   `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`.
2. Subagents run scoped checks only (their pytest files; `npx tsc --noEmit` and
   `npm run lint` inside apps/web; mypy with a private `--cache-dir`; ruff `--no-cache`;
   `python3 scripts/copy_lint.py`). Never `make check` / `make install` / pip / npm
   install inside agents. You run the full `make check` serially at each gate.
3. One conventional commit per completed unit, by you, ending with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
4. DoD triple: `make check` green + TASKS.md checkbox + LOG.md DONE line with evidence.
5. Verify the rendered pages against the live DB before the gate (run `make dev` or
   `cd apps/web && npm run dev` and curl/inspect the four routes; AC-3 means the page
   numbers equal `select ... from scores where score_run_id = (select max(id) ...)`).

## Binding constraints (violations are session failures)

- Regulatory firewall AC-7: no buy/sell/hold/signal/moon/guaranteed/recommendation
  language in any rendered copy. Fix wording, never the linter. `copy-lint-ignore` only
  for verbatim quoted evidence with a stated reason.
- Append-only ledger: never UPDATE/DELETE `resolutions`/`scores` (DB triggers enforce).
- Scope lock: crypto + YouTube only; no auth, no payments, nothing from E2–E6 (no real
  embeds — that is E5-T1; no OG cards — E5-T4).
- Boring stack, locked: no new dependencies (lightweight-charts is already in
  package.json), no formula changes, ADR + approval for any deviation. If brandkit/PRD
  conflict on a UI detail, brandkit wins for visuals, PRD for behavior; stop and ask if
  genuinely ambiguous.
- Never silence a gate (no type: ignore / noqa / eslint-disable / skipped tests).
- Numbers on pages must match the ledger exactly (AC-3) — display rounding only
  (FAS 1 decimal, F 2 decimals, like the demo board).

## Environment notes (learned across the E1 session)

- Python 3.12 venv at `services/pipeline/.venv`; mypy needs
  `--config-file services/pipeline/pyproject.toml`; agents must use private
  `--cache-dir`s when parallel.
- Docker CLI at `/usr/local/bin/docker`; daemon may need `open -a Docker` first.
- Run the demo directly (no pip churn): `services/pipeline/.venv/bin/python -m
  brier_pipeline.demo`.
- DB-backed pytest skips hermetically when the DB is down — bring it up so the ledger
  trigger + demo e2e tests actually run, and say so in DONE evidence.
- The methodology page reads `docs/METHODOLOGY.md` via `path.join(process.cwd(), "..",
  "..")` — pages run with `apps/web` as cwd.
- Fixture analysts are fictional: NorthChain, Aylin Markets, VectorEdge. Keep all new
  copy fictional and brandkit-voiced. Receipt quotes already pass copy-lint; keep it
  that way.
- `lightweight-charts` v4 must render in a client component (`"use client"`); the price
  series arrives as serialized props from the server component.

## Closing report (required — covers the whole epic)

End the session with: (1) per-task status table E1-T1..E1-T5 (DONE/BLOCKED + evidence
line), (2) final `make check` output summary, (3) `make pipeline-demo` output (the ranked
board — the FAS inversion: Aylin above NorthChain on FAS despite lower raw hit rate),
(4) the four page routes with a one-line verification note each (AC-3 numbers vs ledger),
(5) LOG.md tail, (6) `git log --oneline 51fb7bd..HEAD`, (7) the qa-reviewer audit
findings, (8) next unblocked tasks with suggested owners — should be E2-T1
(pipeline-engineer), E2-T6 (pipeline-engineer), E3-T1 (pipeline-engineer), E4-T1
(pipeline-engineer), E4-T2 (scoring-quant), E5-* unlocked after E1-T5.


## ═══════════════════════ PROMPT-E2.md ═══════════════════════

# Session prompt — Implement Epic E2 (Ingestion) via workflows

Copy everything below the line into a fresh Claude Code session started at the repo root
(`/Users/ae/repo/brier-claude`). This file is session tooling, not product code — leave it
untracked (like `PROMPT-E1.md` / `PROMPT-E1B.md`) once the session is launched.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube
analysts). Epic E1 (Walking Skeleton) is complete and committed — HEAD `875ae2e`, `make check`
green (163 pytest + copy-lint + ruff + mypy strict + tsc + eslint all clean). E1-T1 through
E1-T5 are DONE per the DoD triple (checkbox + LOG.md DONE line + green gate), and the
qa-reviewer audited the whole epic as PASS. The four pages render real ledger data; the
fixture thread runs end to end. Your mission this session: **implement Epic E2 — Ingestion —
end to end (tasks E2-T1 through E2-T6 in TASKS.md), driving each task to the Definition of
Done, then run the qa-reviewer session audit and write the next epic's session prompt.**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to
workflows for this session. Orchestrate with the scoped subagents in `.claude/agents/`
(`pipeline-engineer` owns every E2 task; `qa-reviewer` audits) via the Workflow `agentType`
option or the Agent tool's `subagent_type`. Run an adversarial verification panel before each
gate.

## Current state (verified at HEAD `875ae2e`)

- **Dev DB:** docker-compose Postgres (container `brier-db`, dsn
  `postgresql://brier:brier@localhost:5432/brier`). Migrations 0001–0006 applied; the
  `jobs`, `disputes`, and `corrections` tables already exist (`migrations/0006_ops.sql`).
  Fixture data present: 3 analysts, 14 videos, 14 transcripts, 35 claims, 26 resolutions,
  score ledger, and `price_daily` (1674 fixture closes). Docker may be stopped after a
  reboot: `open -a Docker`, wait for the daemon, then `make seed` is idempotent.
- **Fixtures are fictional:** NorthChain, Aylin Markets, VectorEdge
  (`data/fixtures/analysts.json`). Keep all new fixture/roster data fictional and
  brandkit-voiced; `scripts/copy_lint.py` scans `data/fixtures/*.json`.
- **The mock-first seam already exists for every E2 integration** (this is the whole point of
  E2): `YouTubeClient` (fake `FakeYouTubeClient`, real stub `DataApiYouTubeClient`) in
  `ingestion/youtube.py`; `Transcriber` (`FakeTranscriber`, stubs `WhisperTranscriber` /
  `DeepgramTranscriber`) in `transcription/transcriber.py`; `Storage` (`LocalFSStorage`, stub
  `R2Storage`) in `transcription/storage.py`; `poll_registered_channels` in
  `ingestion/poller.py`; `backfill_channel` in `ingestion/backfill.py`; `claim_next_job` /
  `run_forever` in `jobs/worker.py`. Every real stub carries a `# TASK: E2-Tx` marker and
  raises `NotImplementedError`. Implementing a task means replacing its stub and removing the
  marker, while keeping the fixture-backed fake as the tested/CI/demo path.

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, and the **binding 5-rule logging contract**.
2. `TASKS.md` — the E2 task definitions and acceptance criteria are authoritative; E1 is
   ticked.
3. `docs/PRD.md` — at minimum FR-101–FR-104, HP-1, NFR-1 (freshness ≤2h poll, >48h alert),
   NFR-2 (reproducibility), NFR-4 (no raw video; embeds only; transient audio 30-day TTL),
   NFR-5 (cost guardrails), §11 data flows, §18 stack, §20 external resources/quota notes.
4. `CLAUDE.md` **Mock-first integrations** rule and **Boring stack, locked** rule — these two
   govern every E2 task (see Binding constraints below).
5. `LOG.md` tail — confirm the last line is the E1 qa-reviewer `AUDIT | DONE` entry before
   appending anything.
6. The E2 stub modules listed under Current state — implement against the existing interfaces.

## The six tasks and their dependency shape (all owner: pipeline-engineer)

- **E2-T1 — Analyst registry operations** · deps: E1-T4 (done) · PRD FR-101. Registry CRUD
  (plain SQL + a small CLI), status and jurisdiction flags, and a roster import for ~50
  **fictional** analysts (extend `data/fixtures/analysts.json` or a new
  `data/fixtures/roster.json`; honor the scope lock — no Turkey-domiciled subjects via the
  jurisdiction flag). No new dependencies needed.
- **E2-T6 — Jobs worker loop** · deps: E1-T4 (done) · PRD §11. `claim_next_job` /
  `run_forever` over the `jobs` table using `SELECT ... FOR UPDATE SKIP LOCKED`, per-kind
  dispatch (poll_channels | transcribe | extract | resolve_claims | score_analysts |
  weekly_digest | freshness_check), attempt counting, retries with backoff, and `last_error`
  capture. No Celery, no new dependencies (pure SQL + stdlib).
- **E2-T2 — New-upload poller** · deps: E2-T1, E2-T6 · PRD FR-102, HP-1, NFR-1.
  `DataApiYouTubeClient.list_uploads_since` (official Data API v3 via **playlistItems, 1
  unit — never `search`, 100 units**) + `poll_registered_channels` enqueuing jobs at ≤2h
  latency; staleness >48h raises the freshness flag. Test against `FakeYouTubeClient` and a
  mocked HTTP boundary — no live API calls in CI.
- **E2-T3 — 24-month backfill crawler** · deps: E2-T2 · PRD FR-104, G3.
  `DataApiYouTubeClient.list_all_uploads` + `backfill_channel` over the trailing 24 months,
  resumable, quota-aware, capped per NFR-5. Mocked/paginated HTTP in tests.
- **E2-T4 — Captions + transcription adapters (real)** · deps: E2-T2 · PRD FR-103.
  Caption-first acquisition (`DataApiYouTubeClient.fetch_captions`); `WhisperTranscriber`
  (batch GPU) and `DeepgramTranscriber` (incremental) producing second-level offsets; audio
  transient with a 30-day TTL. **Real transcription needs new dependencies — see the ADR gate
  below.**
- **E2-T5 — R2 storage adapter + audio TTL** · deps: E2-T4 · PRD NFR-4. `R2Storage`
  (S3-compatible) implementation, lifecycle rule for audio (30-day TTL), transcripts
  persistent. **Real R2 needs a new dependency — see the ADR gate below.**

Suggested workflow shape: **(T1 ∥ T6) → T2 → (T3 ∥ T4) → T5 → qa audit → write next prompt.**
T1 (registry, plain SQL) and T6 (jobs worker, plain SQL) touch disjoint modules and run in
parallel. T3 (backfill) and T4 (transcription) both depend on T2 and touch disjoint modules,
so they run in parallel. Serialize the full gate per the rules below.

## The ADR gate (the defining constraint of E2 — read carefully)

E2 is where real external integrations appear, but the stack is **locked**: no new
dependencies without my approval + an ADR (`docs/adr/`, via the `new-adr` skill). Hold this
line:

- **E2-T1 and E2-T6** need no new dependencies — implement them fully (plain SQL + stdlib).
- **E2-T2 / E2-T3** (YouTube Data API v3) can be implemented against the REST endpoints using
  the standard library (`urllib.request` + `json`) — no new dependency. Keep the fake as the
  CI path and test the real client with a mocked HTTP boundary. Prefer this stdlib route; if
  you believe an HTTP client library is warranted, stop and propose an ADR first.
- **E2-T4 (faster-whisper / Deepgram SDK) and E2-T5 (R2 via an S3 SDK such as boto3)** require
  heavy new dependencies. Do **not** add them silently. For each, either (a) draft an ADR with
  `new-adr`, present it, and **stop for my approval before adding the dependency**, or (b)
  land the real adapter's *seam* — interface honored, real call site clearly structured and
  unit-tested against a mocked SDK/HTTP boundary, fixture-backed fake remaining the CI/demo
  path — and append a `BLOCKED` LOG line for the dependency-requiring portion pending my
  approval. Choose (b) and keep moving if I am not available to approve; report it in the
  closing report. Never fabricate green by stubbing the assertion.

In all cases: the fixture-backed fake (`FakeYouTubeClient`, `FakeTranscriber`,
`LocalFSStorage`) stays the path that `make check`, the demo, and CI exercise — no test makes
a real network call, uses real credentials, or downloads a model.

## Orchestration rules (these prevent real races — follow them)

1. **The orchestrator (you, the main loop) owns LOG.md, TASKS.md checkboxes, and git.**
   Subagents must NOT write LOG.md, tick checkboxes, or commit — instruct each agent
   explicitly, and do not rely on them to self-report into the ledger (a prior session had
   subagents append stray LOG lines; tell them the orchestrator owns the ledger). You append
   the STARTED line (attributed to the executing agent) before launching each task, and the
   DONE line only after you have verified the gate. LOG.md is append-only — new lines at the
   bottom, never edit or reorder. Format:
   `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`.
2. **Parallel agents run only scoped checks** (their own pytest files; `ruff check --no-cache`;
   `mypy --config-file services/pipeline/pyproject.toml` with a private `--cache-dir`;
   `python3 scripts/copy_lint.py`). The full `make check` runs serially, by you, at each
   integration point — concurrent full gates race the venv. Never run `make check` /
   `make install` / pip / npm install inside an agent.
3. **One conventional commit per completed task**, made by you after its gate is green, e.g.
   `feat(jobs): postgres-backed worker loop with SKIP LOCKED (E2-T6)`. Commits end with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
4. **DoD triple per task:** `make check` green + TASKS.md checkbox ticked + LOG.md DONE line
   stating the verification evidence (test count) and modules touched. One without the others
   is a defect.
5. If a task is blocked (e.g. an ADR-gated dependency) or an agent fails after a retry, append
   a `BLOCKED` line with the reason and continue with whatever is unblocked; report it at the
   end.

## Binding constraints (violations are session failures)

- **Mock-first integrations:** every external dependency sits behind a small interface with a
  fixture-backed fake; CI and the demo never touch the network, real credentials, or a model.
- **Boring stack, locked:** no new dependencies / no stack deviations without my approval + an
  ADR (the ADR gate above). A helper used once gets inlined.
- **Regulatory firewall (AC-7):** no buy/sell/hold/signal/moon/guaranteed/recommendation
  language in any user-visible copy, fixture roster strings included. `scripts/copy_lint.py`
  enforces it; fix the wording, never the linter.
- **Append-only ledger:** `resolutions` and `scores` are never UPDATEd/DELETEd (DB triggers
  enforce). The `jobs` table is mutable operational state (not a ledger) — normal
  UPDATE/claim transitions are fine there.
- **Scope lock:** crypto + YouTube only; no auth, no payments; nothing from E3–E6 sneaks in
  (no extraction LLM work — that is E3; no dispute/SLA tooling — E6). NFR-4: no raw video is
  ever hosted; audio is transient with a 30-day TTL; quotes stay ≤15 words.
- **Never silence a gate** (no `# type: ignore`, `# noqa`, eslint-disable, test deletion, or
  skipped assertions to reach green).

## Environment notes (carried from the E1 sessions)

- Python 3.12 venv at `services/pipeline/.venv`; run the worker/CLIs directly, e.g.
  `services/pipeline/.venv/bin/python -m brier_pipeline.jobs.worker`. `make check` =
  copy-lint → ruff (lint+format) → mypy strict → pytest → tsc → eslint; mypy needs
  `--config-file services/pipeline/pyproject.toml` (the Makefile handles it).
- Docker CLI is `/usr/local/bin/docker`; daemon may need `open -a Docker` first. Bring the DB
  up before ledger/jobs-touching tasks so the DB-backed tests actually run (they skip
  hermetically when the DB is down) — and say so in the DONE evidence.
- The job queue is the spine of §11: the poller (E2-T2) enqueues work; the worker (E2-T6)
  claims and dispatches it. Design T6's per-kind dispatch so E3/E4 can register
  `transcribe`/`extract`/`resolve_claims`/`score_analysts` handlers without reshaping the loop.

## Closing report (required — covers the whole epic)

End the session with: (1) per-task status table E2-T1..E2-T6 (DONE/BLOCKED + evidence line),
(2) final `make check` output summary, (3) a short demonstration that the job queue + poller
work on fixtures (enqueue → claim → dispatch, idempotent/resumable), (4) any ADR drafts and
their approval status, (5) LOG.md tail, (6) `git log --oneline 875ae2e..HEAD`, (7) the
qa-reviewer audit findings, (8) next unblocked tasks with suggested owners (E3 territory:
E3-T1 pass-1 detection, then E3-T2 structuring, plus E4-T1/E4-T2 if still open).

## Final phase — write the next session prompt (do not skip)

After the qa-reviewer audit and the closing report, the **last phase of the workflow must
spawn one agent (or do it yourself as the orchestrator) that writes `PROMPT-E3.md`** — the
session prompt for **Epic E3 (Extraction + QA)** — into the repo root, modeled exactly on the
structure of this file and `PROMPT-E1.md`. That generated prompt must:

1. Reflect the **post-E2 repo state**: the new HEAD commit, the `make check` test count, which
   E2 tasks are DONE vs BLOCKED, any ADRs landed, and the live DB/fixtures state.
2. Enumerate the **E3 tasks from TASKS.md** (E3-T1 pass-1 candidate detection, E3-T2 pass-2
   structuring, E3-T3 confidence threshold + QA queue, E3-T4 non-falsifiable classifier,
   E3-T5 semantic dedup, E3-T6 golden-set eval harness) with their real owners
   (`pipeline-engineer`, with `qa-reviewer` on the E3-T6 spec) and their dependency shape, and
   call out the E3-specific binding constraints (LiteLLM/Haiku-class extraction behind the
   mock-first seam with recorded fixtures — no live LLM calls in CI; the AC-1 golden-set gate
   ≥95% precision / ≥80% recall; the same ADR gate for any new dependency).
3. Carry forward the orchestration rules, the ADR gate, the binding constraints, and the
   environment notes, updated for E3.
4. **Itself end with this same "Final phase — write the next session prompt" instruction**, so
   the chain continues (E3 writes `PROMPT-E4.md`, and so on through E6). This is what makes the
   epic chain self-perpetuating: every epic prompt closes by generating the next one.

Append a LOG.md NOTE line recording that `PROMPT-E3.md` was written, and mention it in the
closing report. Do not commit `PROMPT-E3.md` (session tooling stays untracked, like this file).


## ═══════════════════════ PROMPT-E3.md ═══════════════════════

# Session prompt — Implement Epic E3 (Extraction + QA) via workflows

Copy everything below the line into a fresh Claude Code session started at the repo root
(`/Users/ae/repo/brier-claude`). This file is session tooling, not product code — leave it
untracked (like `PROMPT-E1.md` / `PROMPT-E2.md`) once the session is launched.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube
analysts). Epics E1 (Walking Skeleton) and E2 (Ingestion) are complete and committed — HEAD
`1f5fde3`, `make check` green (**296 pytest** + copy-lint + ruff lint/format + mypy strict (31
files) + tsc + eslint all clean). The qa-reviewer audited E2 as **PASS_WITH_NOTES**. Your mission
this session: **implement Epic E3 — Extraction + QA — end to end (tasks E3-T1 through E3-T6 in
TASKS.md), driving each task to the Definition of Done, then run the qa-reviewer session audit and
write the next epic's session prompt (`PROMPT-E4.md`).**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to workflows
for this session. Orchestrate with the scoped subagents in `.claude/agents/` (`pipeline-engineer`
owns every E3 implementation task; `qa-reviewer` owns the E3-T6 golden-set spec and the audits) via
the Workflow `agentType` option or the Agent tool's `subagent_type`. Run an adversarial verification
panel before each gate.

## Current state (verified at HEAD `1f5fde3`)

- **Dev DB:** docker-compose Postgres (container `brier-db`, dsn
  `postgresql://brier:brier@localhost:5432/brier`). Migrations 0001–0006 applied; pgvector
  extension is enabled (0001) and `claims.embedding vector(384)` already exists (0003) — **E3-T5
  semantic dedup needs no new migration for the column**. The `jobs`/`disputes`/`corrections`
  tables exist (0006). Fixture data present: 3 analysts, 14 videos, 14 transcripts, 35 claims, 26
  resolutions, score ledger, and `price_daily` (1674 fixture closes). Docker may be stopped after a
  reboot: `open -a Docker`, wait for the daemon, then `make seed` is idempotent.
- **Fixtures are fictional:** NorthChain, Aylin Markets, VectorEdge (`data/fixtures/analysts.json`),
  plus a 50-analyst fictional roster (`data/fixtures/roster.json`, imported on demand via the E2-T1
  CLI — NOT auto-seeded; `make seed` still seeds only the 3). Keep all new fixture/golden-set data
  fictional and brandkit-voiced; `scripts/copy_lint.py` scans `data/fixtures/*.json`.
- **E2 status (this is what E3 builds on):**
  - **DONE:** E2-T1 analyst registry (`ingestion/registry.py` + CLI + scope-lock), E2-T6 jobs worker
    (`jobs/worker.py`: `enqueue_job`, `claim_next_job` FOR UPDATE SKIP LOCKED, per-kind handler
    registry, retries+backoff), E2-T2 poller (`ingestion/poller.py` + `DataApiYouTubeClient.list_uploads_since`),
    E2-T3 backfill (`ingestion/backfill.py` + `list_all_uploads`).
  - **BLOCKED-by-design (ADR-gated heavy deps; seams landed + mocked-boundary tests + fixture/local
    fakes are the CI path):** E2-T4 transcription (`transcription/transcriber.py`: captions stdlib +
    `DeepgramTranscriber` stdlib REST done; `WhisperTranscriber` seam — faster-whisper pending
    **ADR-0003**); E2-T5 storage (`transcription/storage.py`: `R2Storage` seam + real
    `LocalFSStorage.sweep_expired_audio` 30-day TTL; boto3 pending **ADR-0004**). Their TASKS.md
    checkboxes are intentionally UNTICKED with `BLOCKED` LOG lines; `docs/adr/0003` and
    `docs/adr/0004` are drafted **Status: proposed (pending human approval)**. These do not block E3.
- **The job queue is the spine (§11):** the poller enqueues `transcribe` jobs; the worker
  (`jobs/worker.py`) dispatches by kind. **E3 registers the `extract` handler** (and may register
  `resolve_claims`/`score_analysts` if convenient) on the existing loop without reshaping it — use
  `worker.register_handler("extract", ...)` exactly as `ingestion/poller.py` registers `poll_channels`.
- **The mock-first seam for E3 extraction already exists:** `Extractor` (fake `FakeExtractor` that
  replays `data/fixtures/claims.json`, real stub `LlmExtractor`) in `extraction/extractor.py`; the
  LiteLLM router glue `completion(model_name, messages)` in `extraction/llm.py`; the QA-queue stubs
  `route_low_confidence` / `record_review` in `qa/queue.py`; `dedup_claims` in `extractor.py`. Every
  real stub carries a `# TASK: E3-Tx` marker and raises `NotImplementedError`. Implementing a task
  means replacing its stub and removing the marker, while keeping the fixture-backed `FakeExtractor`
  as the tested/CI/demo path. **Note:** `litellm.config.yaml` does NOT exist yet and `litellm` is
  NOT a dependency — see the ADR gate below.

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, and the **binding 5-rule logging contract**.
2. `TASKS.md` — the E3 task definitions and acceptance criteria are authoritative; E1 and the four
   DONE E2 tasks are ticked, E2-T4/T5 are unticked (BLOCKED).
3. `docs/PRD.md` — at minimum FR-201–FR-205, FR-203/US-009/HP-4 (QA queue), FR-204 (non-falsifiable),
   FR-205/EC-2 (dedup), EC-3 (sarcasm/hypothetical/paraphrase), EC-5 (guests/diarization), EC-7
   (asset ambiguity → void), AC-1 + G2 + §7 (golden-set gate ≥95% precision / ≥80% recall), NFR-2
   (reproducibility: model/prompt versions, reviewer id), NFR-5 (LLM spend caps), §11 data flow 2,
   §18 (LLM stack + eval harness), §21 (Label Studio, LiteLLM, promptfoo).
4. `docs/METHODOLOGY.md` §1/§4 — the FR-202 claim tuple and `SpecificityClass` semantics extraction
   must populate (these feed scoring; do not change scoring math — that is scoring-quant's domain).
5. `docs/adr/0001`–`0004` — ADR-0001 (process), ADR-0002 (scoring pins), ADR-0003/0004 (the proposed
   ADR-gate precedent E3 should mirror for any new dependency).
6. `LOG.md` tail — confirm the last line is the E2 qa-reviewer `AUDIT | DONE` entry (PASS_WITH_NOTES)
   before appending anything.
7. The E3 stub modules listed under Current state — implement against the existing interfaces.

## The six tasks and their dependency shape (owners as noted)

- **E3-T1 — Pass-1 candidate detection** · deps: E1-T4 (done) · PRD FR-201 · owner: pipeline-engineer.
  `LlmExtractor.detect_candidates` (`extraction/extractor.py`) via the LiteLLM router (Haiku-class,
  structured outputs), batched over transcript segments, spend within the NFR-5 caps. Recorded-fixture
  responses are the CI path (no live LLM).
- **E3-T2 — Pass-2 structuring** · deps: E3-T1 · PRD FR-202, EC-3, EC-7 · owner: pipeline-engineer.
  `LlmExtractor.structure_claim` (+ `extraction/llm.completion`) into the full FR-202 tuple with
  model/prompt versions recorded (NFR-2); a controlled asset vocabulary + alias table; sarcasm /
  hypothetical / paraphrase-of-others exclusion (EC-3); unresolvable asset → `void` (EC-7).
- **E3-T3 — Confidence threshold + QA queue loop** · deps: E3-T2 · PRD FR-203, US-009, HP-4, NFR-2 ·
  owner: pipeline-engineer. `route_low_confidence` + `record_review` (`qa/queue.py`), Label Studio
  queue wiring behind a mock-first seam, `reviewer_id` recorded, nothing below threshold publishes
  unreviewed; diarization uncertainty (EC-5) routes here.
- **E3-T4 — Non-falsifiable classifier** · deps: E3-T2 · PRD FR-204 · owner: pipeline-engineer.
  Classify prediction-like-but-unfalsifiable statements; they count toward the falsifiability ratio
  (the F denominator scoring already reads) but never score. (Builds on the `structure_claim` path;
  shares `extraction/extractor.py`.)
- **E3-T5 — Semantic dedup** · deps: E3-T2 · PRD FR-205, EC-2 · owner: pipeline-engineer.
  `dedup_claims` (`extraction/extractor.py`) via pgvector embeddings on `claims.embedding`; repeats
  reinforce (one `dedup_cluster_id`), they do not multiply; re-uploads keep the original timestamp
  (EC-2). The embedding model is an external dependency — keep it behind a mock-first seam (injected
  embedder / recorded vectors), no live model in CI.
- **E3-T6 — Golden-set eval harness** · deps: E3-T2 · PRD AC-1, G2, §18 eval · owner: **qa-reviewer
  (spec) + pipeline-engineer (harness)**. `data/fixtures/golden_set.jsonl` (200 hand-labeled,
  fictional claims from ~40 fixture videos), a pytest/promptfoo harness wired as a **required CI
  check**: precision ≥95% AND recall ≥80% against the golden set, or the build fails (AC-1). The
  harness must run against recorded fixture extractions, never a live LLM.

Suggested workflow shape: **T1 → T2 → (T3 ∥ T6) then (T4 → T5)**. T1 and T2 both touch
`extraction/extractor.py` (+ `llm.py`) so they serialize. After T2: T3 (`qa/queue.py`, disjoint) and
T6 (new `golden_set.jsonl` + harness files, disjoint) can run in parallel; **T4 and T5 both edit
`extraction/extractor.py`, so serialize that pair** (the same shared-file lesson as E2-T3/T4 — do not
run two agents editing `extractor.py` concurrently in the same tree). Serialize the full gate per the
rules below.

## The ADR gate (carry it forward — E3 introduces the LLM dependency)

E3 is where the extraction LLM appears, but the stack is **locked**: no new dependency without my
approval + an ADR (`docs/adr/`, via the `new-adr` skill). Hold this line exactly as E2 did:

- **LiteLLM** (and any embedding SDK for E3-T5) are heavy new dependencies. Do **not** add them
  silently. For each, either (a) draft an ADR with `new-adr`, present it, and **stop for my approval
  before adding the dependency**, or (b) land the real adapter's *seam* — `LlmExtractor`/embedder
  interface honored, the real call site clearly structured and unit-tested against a **mocked**
  LLM/embedding boundary (an injected `completion`/embedder, or recorded fixture responses checked
  into `data/fixtures/`), with `FakeExtractor` remaining the CI/demo path — and append a `BLOCKED`
  LOG line for the dependency-requiring portion pending my approval. **Choose (b) and keep moving if
  I am not available to approve** (this is exactly how E2-T4/T5 landed: ADR-0003/0004 drafted
  *proposed*, seams committed, BLOCKED lines, checkboxes unticked). Report it in the closing report.
- Calling the Anthropic API directly via stdlib `urllib` (REST) instead of the LiteLLM SDK is a
  legitimate no-new-dependency route — **but** the PRD §18 calls for LiteLLM's provider-swappable
  router, so if you go stdlib-REST, structure it behind the same `completion()` seam and note the
  deviation; if you believe the LiteLLM dependency is warranted, stop and propose an ADR first.
- **Never make a live LLM/embedding call, use real credentials, or hit the network in any test or in
  `make check`/CI.** Recorded fixture responses are the eval and CI substrate. The golden-set gate
  (AC-1) runs against recorded extractions, deterministically.

In all cases the fixture-backed `FakeExtractor` stays the path that `make check`, the demo, and CI
exercise.

## Orchestration rules (these prevent real races — follow them)

1. **The orchestrator (you, the main loop) owns LOG.md, TASKS.md checkboxes, and git.** Subagents
   must NOT write LOG.md, tick checkboxes, or commit. **Hard-won lesson from E2: the `qa-reviewer`
   agent definition makes verification subagents habitually append audit NOTE lines to LOG.md even
   when told not to.** Mitigate explicitly: in every verification-agent prompt, instruct the agent
   to **RETURN its findings as its final message only and write NOTHING to LOG.md/TASKS.md**, and
   have the orchestrator transcribe any needed NOTE/AUDIT line itself (with a correct `date -u`
   UTC timestamp). If a subagent appends to the uncommitted working-tree LOG.md anyway, the
   orchestrator cleans it up pre-commit (the committed ledger is the append-only artifact) and
   records the cleanup in an orchestrator NOTE. You append the STARTED line (attributed to the
   executing agent) before launching each task, and the DONE/BLOCKED line only after you have
   verified the gate. LOG.md is append-only — new lines at the bottom, never edit or reorder.
   Format: `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`.
2. **Parallel agents run only scoped checks** (their own pytest files; `ruff check --no-cache`;
   `mypy --config-file services/pipeline/pyproject.toml` with a private `--cache-dir`;
   `python3 scripts/copy_lint.py`). The full `make check` runs serially, by you, at each integration
   point — concurrent full gates race the venv. Never run `make check` / `make install` / pip / npm
   install inside an agent. Never run two agents editing the same file concurrently (e.g. both
   editing `extraction/extractor.py`) — serialize them.
3. **One conventional commit per completed task**, made by you after its gate is green, e.g.
   `feat(extraction): pass-1 candidate detection via LiteLLM seam (E3-T1)`. Commits end with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Commit the ledger (LOG.md + TASKS.md)
   at the epic close (a `chore:` commit), as E2 did (`1f5fde3`).
4. **DoD triple per task:** `make check` green + TASKS.md checkbox ticked + LOG.md DONE line stating
   the verification evidence (test count) and modules touched. For an ADR-gated BLOCKED task: seam
   committed + `BLOCKED` line + ADR drafted (proposed) + checkbox left UNTICKED.
5. If a task is blocked (ADR-gated dependency) or an agent fails after a retry, append a `BLOCKED`
   line with the reason and continue with whatever is unblocked; report it at the end.

## Binding constraints (violations are session failures)

- **Mock-first integrations:** every external dependency (LLM, embeddings, Label Studio) sits behind
  a small interface with a fixture-backed fake; CI and the demo never touch the network, real
  credentials, or a live model. `FakeExtractor` replays `data/fixtures/claims.json` and stays the CI
  path.
- **AC-1 golden-set gate:** E3-T6 wires a required CI check that fails the build if extraction
  precision < 95% or recall < 80% against `data/fixtures/golden_set.jsonl`. This is the credibility
  gate (G2); do not weaken it to pass — fix the extraction.
- **Boring stack, locked:** no new dependencies / no stack deviations without my approval + an ADR
  (the ADR gate above). A helper used once gets inlined.
- **Regulatory firewall (AC-7):** no buy/sell/hold/signal/moon/guaranteed/recommendation language in
  any user-visible copy, golden-set/fixture strings included. `scripts/copy_lint.py` enforces it;
  fix the wording, never the linter.
- **Append-only ledger:** `resolutions` and `scores` are never UPDATEd/DELETEd (DB triggers enforce).
  `claims` is mutable working state (review_state, publishable, dedup_cluster_id, embedding,
  status transitions are normal UPDATEs).
- **Reproducibility (NFR-2):** every published claim records model_version, prompt_version, source
  offset, transcript span, and reviewer_id when QA-touched.
- **Scope lock:** crypto + YouTube only; no auth, no payments; nothing from E4–E6 sneaks in (no
  resolution rule-library expansion — that is E4; no dispute/SLA tooling — E6). Quotes stay ≤15 words
  (NFR-4).
- **Never silence a gate** (no `# type: ignore`, `# noqa`, eslint-disable, test deletion, or skipped
  assertions to reach green). For an optional/ADR-gated package mypy can't resolve, add a scoped
  `[[tool.mypy.overrides]] ... ignore_missing_imports = true` stanza in
  `services/pipeline/pyproject.toml` (the agreed mechanism — see the faster_whisper/boto3 entries),
  not an inline suppression.

## Environment notes (carried from the E1/E2 sessions)

- Python 3.12 venv at `services/pipeline/.venv`; run workers/CLIs directly, e.g.
  `services/pipeline/.venv/bin/python -m brier_pipeline.jobs.worker`. `make check` =
  copy-lint → ruff (lint+format) → mypy strict → pytest → tsc → eslint; mypy needs
  `--config-file services/pipeline/pyproject.toml` (the Makefile handles it).
- Docker CLI is `/usr/local/bin/docker`; daemon may need `open -a Docker` first. Bring the DB up
  before ledger/claims-touching tasks so DB-backed tests actually run (they skip hermetically via the
  `db_conn` fixture when the DB is down) — and say so in the DONE evidence.
- DB-backed tests use the rolled-back `db_conn` fixture (`tests/conftest.py`); for deterministic
  integration tests prefer a synthetic in-test fixture over coupling to committed demo state. The
  E2 `test_smoke.py` `NOT_IMPLEMENTED_PROBES` list drops a probe when its stub is implemented —
  remove the E3 probes (`llm.completion`, `extractor.dedup_claims`, and add any you implement) as you
  land them, plus any now-unused imports (ruff F401).
- Recorded-fixture pattern for the LLM seam: check canned request/response pairs into
  `data/fixtures/` (copy-lint clean, fictional) and have `LlmExtractor` accept an injected
  `completion` callable defaulting to the real `llm.completion`; tests inject the recorded boundary.

## Closing report (required — covers the whole epic)

End the session with: (1) per-task status table E3-T1..E3-T6 (DONE/BLOCKED + evidence line),
(2) final `make check` output summary, (3) a short demonstration that extraction → QA-queue routing
→ (dedup) works on fixtures and that the golden-set eval reports precision/recall against the
recorded golden set, (4) any ADR drafts (e.g. LiteLLM / embeddings) and their approval status,
(5) LOG.md tail, (6) `git log --oneline 1f5fde3..HEAD`, (7) the qa-reviewer audit findings,
(8) next unblocked tasks with suggested owners (E4 territory: E4-T1 full resolution rule library,
E4-T2 base rates [scoring-quant], E4-T3 edge cases, E4-T4 contradiction detection, E4-T5 methodology
recompute; plus E5 web-completion tasks if you want to parallelize the frontend).

## Final phase — write the next session prompt (do not skip)

After the qa-reviewer audit and the closing report, the **last phase of the workflow must spawn one
agent (or do it yourself as the orchestrator) that writes `PROMPT-E4.md`** — the session prompt for
**Epic E4 (Resolution + Scoring hardening)** — into the repo root, modeled exactly on the structure
of this file and `PROMPT-E2.md`. That generated prompt must:

1. Reflect the **post-E3 repo state**: the new HEAD commit, the `make check` test count, which E3
   tasks are DONE vs BLOCKED, any ADRs landed (LiteLLM/embeddings), the golden-set gate status, and
   the live DB/fixtures state.
2. Enumerate the **E4 tasks from TASKS.md** (E4-T1 full resolution rule library, E4-T2 base rates
   from trailing 5-year history [owner: scoring-quant], E4-T3 edge cases EC-1..EC-12, E4-T4
   contradiction detection, E4-T5 methodology version recompute [owner: scoring-quant]) with their
   real owners and dependency shape, and call out the E4-specific binding constraints (the scoring
   methodology is the credibility moat — any formula/convention change needs an ADR + a methodology
   version bump + full-history recompute per FR-304/AC-4; CoinGecko/CCXT price sources behind the
   mock-first seam with fixture closes — no live price API in CI; the same ADR gate for any new
   dependency).
3. Carry forward the orchestration rules (including the LOG-ownership mitigation above), the ADR
   gate, the binding constraints, and the environment notes, updated for E4.
4. **Itself end with this same "Final phase — write the next session prompt" instruction**, so the
   chain continues (E4 writes `PROMPT-E5.md`, and so on through E6). This is what makes the epic
   chain self-perpetuating: every epic prompt closes by generating the next one.

Append a LOG.md NOTE line recording that `PROMPT-E4.md` was written, and mention it in the closing
report. Do not commit `PROMPT-E4.md` (session tooling stays untracked, like this file).


## ═══════════════════════ PROMPT-E4.md ═══════════════════════

# Session prompt — Implement Epic E4 (Resolution + Scoring hardening) via workflows

Copy everything below the line into a fresh Claude Code session started at the repo root
(`/Users/ae/repo/brier-claude`). This file is session tooling, not product code — leave it
untracked (like `PROMPT-E1.md` … `PROMPT-E3.md`) once the session is launched.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube
analysts). Epics E1 (Walking Skeleton), E2 (Ingestion), and E3 (Extraction + QA) are complete and
committed — HEAD `052c9e7`, `make check` green (**446 pytest** + copy-lint + ruff lint/format + mypy
strict (33 files) + tsc + eslint all clean). The qa-reviewer audited E3 as **PASS_WITH_NOTES**. Your
mission this session: **implement Epic E4 — Resolution + Scoring hardening — end to end (tasks E4-T1
through E4-T5 in TASKS.md), driving each task to the Definition of Done, then run the qa-reviewer
session audit and write the next epic's session prompt (`PROMPT-E5.md`).**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to workflows for
this session. Orchestrate with the scoped subagents in `.claude/agents/`: `pipeline-engineer` owns
E4-T1, E4-T3, E4-T4; **`scoring-quant` owns E4-T2 and E4-T5** (the scoring/methodology tasks — the
methodology is the credibility moat, treat it accordingly); `qa-reviewer` owns the audits. Run an
adversarial verification panel before each gate (this caught real blockers every single E3 task —
e.g. a classifier that let analysts dodge scoring by hedging, a vacuous AC-1 gate, a dedup
horizon-bridge — so do not skip it).

## Current state (verified at HEAD `052c9e7`)

- **Dev DB:** docker-compose Postgres (container `brier-db`, dsn
  `postgresql://brier:brier@localhost:5432/brier`). Migrations 0001–0006 applied; pgvector enabled;
  `claims.embedding vector(384)` exists. Fixture data present: 3 analysts, 14 videos, 14 transcripts,
  35 claims, 26 resolutions, score ledger, `price_daily` (1674 fixture closes). Docker may be stopped
  after a reboot: `open -a Docker`, wait for the daemon, then `make seed` is idempotent.
- **Fixtures are fictional:** NorthChain, Aylin Markets, VectorEdge (`data/fixtures/analysts.json`),
  plus a 50-analyst fictional roster (`data/fixtures/roster.json`, imported on demand). E3 added
  `data/fixtures/golden_set.jsonl` (200 fictional labeled spans) and `data/fixtures/llm/*.json`
  (recorded extraction request/response pairs). Keep all new fixture/price data fictional and
  brandkit-voiced; `scripts/copy_lint.py` scans `data/fixtures/*.json` **and** `*.jsonl`.
- **E3 status (this is what E4 builds on):**
  - **DONE:** E3-T1 pass-1 detection (`extraction/extractor.py:LlmExtractor.detect_candidates` via an
    injected `completion()` seam — stdlib `urllib` REST to the Anthropic Messages API, **ADR-0005**),
    E3-T2 pass-2 structuring (`structure_claim` → full FR-202 tuple; `extraction/assets.py` controlled
    vocab + alias table; EC-3 excluded spans flagged + **not persisted**; EC-7 unresolvable asset →
    void; **ADR-0006** reconciles PRD EC-3 vs METHODOLOGY §6 on the F denominator — proposed),
    E3-T3 QA-queue loop (`qa/queue.py`: `route_low_confidence`/`route_and_enqueue`/`record_review`;
    Label Studio behind a stdlib-REST `LabelStudioQueue` seam + `InMemoryReviewQueue` CI fake),
    E3-T4 non-falsifiable classifier (`classify_non_falsifiable`, FR-204; **ADR-0007** documents the
    classifier conventions — proposed), E3-T6 golden-set eval harness (`qa/golden_eval.py` +
    `tests/test_golden_set.py` — the **AC-1 build gate**: precision ≥95% AND recall ≥80%, non-vacuous,
    runs in `make check`).
  - **BLOCKED-by-design (ADR-gated heavy dep; seam + full logic + mocked-boundary tests are the CI
    path):** E3-T5 semantic dedup (`extraction/extractor.py:dedup_claims` + `extraction/embeddings.py`).
    FR-205/EC-2 dedup logic is **fully implemented and tested** — grouping by
    analyst+asset+direction+overlapping-horizon, representative-linkage clustering (no horizon
    bridging), one `dedup_cluster_id`, re-uploads keep the earliest `uttered_at`, and the DB path uses
    the real **pgvector `<=>`** cosine-distance operator. Only the production embedding model
    (`sentence-transformers`) is ADR-gated (**ADR-0008**, proposed): the `SentenceTransformerEmbedder`
    seam lazily imports it and raises `RuntimeError`→ADR-0008 when absent; an injected fake embedder /
    synthetic 384-dim vectors are the CI path. Its TASKS.md checkbox is intentionally UNTICKED with a
    `BLOCKED` LOG line; recorded in `EX-dept.md`. **This does not block E4** — E4-T4 depends only on the
    dedup *scaffolding*, which is present and tested.
- **Technical-debt ledger (`EX-dept.md`):** tracks the blocked-by-design tasks (E2-T4, E2-T5, E3-T5)
  and their ADR/seam/commit pointers. Add any new E4 blocked-by-design items there (keep it current).
- **The job queue is the spine (§11):** the worker (`jobs/worker.py`) dispatches by kind via
  `worker.register_handler(...)`. E3 did not register an `extract` handler (the demo uses
  `FakeExtractor`). **E4 may register `resolve_claims`/`score_analysts` handlers** on the existing loop
  without reshaping it, exactly as `ingestion/poller.py` registers `poll_channels`.
- **The mock-first seams for E4 already exist as stubs:** `resolve_conditional` and
  `detect_contradictions` (`resolution/rules.py`, `# TASK: E4-T1` / `# TASK: E4-T4`), `base_rate`
  (`resolution/base_rates.py`, `# TASK: E4-T2`), `CoinGeckoPriceSource.daily_closes`
  (`resolution/prices.py`, `# TASK: E4-T2`), `recompute_all` (`scoring/fas.py`, `# TASK: E4-T5`). Each
  raises `NotImplementedError` and is guarded by a probe in `tests/test_smoke.py`'s
  `NOT_IMPLEMENTED_PROBES`. Implementing a task = replacing its stub, removing the marker, and removing
  its smoke probe (+ any now-unused import, ruff F401). `FakePriceSource` (fixture closes) stays the
  CI/demo path.

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, and the **binding 5-rule logging contract**.
2. `TASKS.md` — the E4 task definitions and acceptance criteria are authoritative; E1, the four DONE
   E2 tasks, and the five DONE E3 tasks are ticked; E2-T4/T5 and E3-T5 are unticked (BLOCKED).
3. `docs/METHODOLOGY.md` — **the whole document is the credibility moat.** At minimum §1 (claim tuple,
   imputed-confidence + default-horizon conventions), §2 (resolution: close basis, target vs
   directional, partial credit 0.5, conditional activation, macro), §3 (base rates b = empirical
   probability over trailing 5-year history), §6 (two-tier + falsifiability F + the convention pins
   from ADR-0002), and the changelog/version conventions.
4. `docs/PRD.md` — FR-302 (resolution rule library), FR-303 (base rates), FR-304/AC-4/HP-6/US-010
   (methodology versioning + full-history recompute + archived/queryable prior ledger + changelog),
   FR-305 (n≥20 ranked), §12 (the twelve edge cases EC-1…EC-12), EC-6 (both-direction hedging →
   contradiction void), EC-11 (explicit reversal closes the original claim at the reversal date),
   §18 (price sources: CoinGecko composite + CCXT cross-check), NFR-3 (append-only ledger).
5. `docs/adr/0001`–`0008` — ADR-0002 (scoring convention pins, **accepted**) is binding scoring law;
   ADR-0003/0004/0005/0006/0007/0008 are **proposed**. Two are E4's business to **ratify or revise
   with scoring-quant** because they touch the falsifiability semantics scoring reads: **ADR-0006**
   (EC-3 excluded spans are not persisted → not in the F denominator; EC-7 voids + non_falsifiable
   stay) and **ADR-0007** (the FR-204 non-falsifiable classifier conventions). Resolve their status as
   part of E4-T5 / E4-T2.
6. `LOG.md` tail — confirm the last line is the E3 qa-reviewer `AUDIT | DONE` entry (PASS_WITH_NOTES)
   before appending anything.
7. The E4 stub modules listed under Current state — implement against the existing interfaces.

## The five tasks and their dependency shape (owners as noted)

- **E4-T1 — Full resolution rule library** · deps: E1-T3 (done) · PRD FR-302 · owner: pipeline-engineer.
  `resolve_conditional` (`resolution/rules.py`): conditional claims activate only when the trigger
  fires, then score over the default horizon (METHODOLOGY §2). Default horizons computed at resolution
  time (soon=30d, "this year"=Dec 31, none=90d — the **dates** E3-T2 deliberately deferred; E3 records
  only `horizon_basis`). Explicit reversal closes the original claim at the reversal date (EC-11).
  **Every rule documented on `/methodology`.** Outcomes append to `resolutions` with rule_id +
  rationale + price citation (append-only).
- **E4-T2 — Base rates from trailing 5-year history** · deps: E1-T3 · PRD FR-303 · owner: **scoring-quant**.
  `base_rate()` (`resolution/base_rates.py`) = empirical probability a naive position matching the
  claim's direction succeeded over horizon T on that asset, from composite daily closes
  (`CoinGeckoPriceSource` + a CCXT cross-check). **Replaces the E1 fixture base rates** — this is a
  methodology change, so it needs the version-bump + recompute discipline below. Published with the
  methodology. `FakePriceSource` (fixture closes) stays the CI path; **no live price API in CI**.
- **E4-T3 — Edge cases EC-1…EC-12** · deps: E4-T1 · PRD §12 · owner: pipeline-engineer.
  One test per edge case, implementation where missing: EC-1 deletion persistence, EC-2 re-uploads
  (done in E3-T5 dedup — add the test), EC-3 sarcasm residue (done in E3-T2 — add the test), EC-4
  sponsor segments, EC-5 guests/diarization (routing done in E3-T3 — add the test), EC-6 hedging (see
  E4-T4), EC-7 asset ambiguity (done in E3-T2 — add the test), EC-8 price gaps defer (done in E1-T3 —
  add the test), EC-9 depegs/token death, EC-10 legal fast-track flag, EC-11 reversals (see E4-T1),
  EC-12 version-pinned disputes. Shares `resolution/rules.py` with E4-T1/E4-T4.
- **E4-T4 — Contradiction detection** · deps: E3-T5 (dedup scaffolding present) · PRD EC-6 · owner:
  pipeline-engineer. `detect_contradictions` (`resolution/rules.py`): opposite-direction claims, same
  asset, overlapping horizons → void both + raise a hedging flag. Reuses the E3-T5 grouping
  (analyst/asset/direction/overlapping-horizon) scaffolding.
- **E4-T5 — Methodology version recompute** · deps: E1-T2 · PRD FR-304, AC-4, HP-6, US-010 · owner:
  **scoring-quant**. `recompute_all` (`scoring/fas.py`): a methodology version bump triggers a
  full-history recompute into a NEW `score_run`; the prior ledger is archived and remains queryable;
  a changelog entry lands on `/methodology`. This is the mechanism that makes E4-T2 (and any future
  methodology change) safe and auditable.

Suggested workflow shape: **E4-T1 → E4-T3** (T3 builds on the rule library; both edit
`resolution/rules.py`, so they serialize). **E4-T4 also edits `resolution/rules.py`, so serialize the
rules.py trio E4-T1 → E4-T4 → E4-T3** (do not run two agents editing `rules.py` concurrently — the
same shared-file lesson as E2-T3/T4 and E3-T4/T5). **E4-T2 (`resolution/prices.py` + `base_rates.py`)
and E4-T5 (`scoring/fas.py`) are disjoint from `rules.py`** and can run in parallel with the rules.py
work — but both are scoring-quant + methodology-touching, so coordinate them and run E4-T2's
recompute *through* E4-T5's mechanism. Serialize the full gate per the rules below.

## The methodology-change gate (E4-specific — this is the credibility moat)

The scoring methodology is the product's entire credibility. Hold this line:

- **Any change to a scoring formula, a published convention, or a base-rate source requires an ADR +
  a methodology version bump + a full-history recompute (FR-304/AC-4).** E4-T2 (real base rates
  replacing the E1 fixtures) IS such a change: draft an ADR, bump the methodology version
  (`config.METHODOLOGY_VERSION`), and recompute the full history into a new `score_run` via E4-T5's
  `recompute_all`. The prior ledger must be archived and stay queryable; a changelog entry lands on
  `/methodology`. Worked examples in `tests/test_fas.py` (FAS_A≈47.02, FAS_B≈66.74, the inversion) are
  binding — if a change moves them, that is a methodology bump with human sign-off, not a silent edit.
- **Ratify or revise the proposed scoring-adjacent ADRs.** ADR-0006 (EC-3 not in the F denominator)
  and ADR-0007 (FR-204 classifier conventions) are proposed and affect the falsifiability ratio
  scoring reads. scoring-quant must confirm they are consistent with METHODOLOGY §6 (or file a revision
  + version bump). Record the ratification in the LOG and the ADR status.
- **Price sources behind the mock-first seam.** CoinGecko (composite) is reachable via stdlib `urllib`
  REST (no new dependency, like the Deepgram/Anthropic precedent) — structure it behind the
  `PriceSource` seam and keep `FakePriceSource` (fixture closes) the CI/demo path. **CCXT is a heavy
  new dependency** — do NOT add it silently: either draft an ADR and stop for approval, or land the
  cross-check adapter as a *seam* (lazy import, mocked boundary, `RuntimeError`→ADR when absent) with a
  `BLOCKED` LOG line + UNTICKED checkbox, exactly as E2-T4/T5 and E3-T5 did. **Never hit a live price
  API, use real credentials, or touch the network in any test or in `make check`/CI.**

## The ADR gate (carry it forward)

The stack is **locked**: no new dependency without my approval + an ADR (`docs/adr/`, via the
`new-adr` skill — note subagents lack the Skill tool, so they Write the ADR file directly, modeled on
`docs/adr/0003`). For each heavy dependency (CCXT, any new price/SDK lib): either (a) draft an ADR,
present it, and **stop for my approval before adding the dependency**, or (b) land the real adapter's
*seam* — interface honored, real call site structured and unit-tested against a **mocked** boundary,
with the fixture-backed fake remaining the CI/demo path — and append a `BLOCKED` LOG line for the
dependency-requiring portion + leave the checkbox UNTICKED + record it in `EX-dept.md`. **Choose (b)
and keep moving if I am not available to approve.** Calling a REST API via stdlib `urllib` instead of
an SDK is a legitimate no-new-dependency route — structure it behind the same seam and note the
deviation in an ADR. Report all of this in the closing report.

## Orchestration rules (these prevent real races — follow them)

1. **The orchestrator (you, the main loop) owns LOG.md, TASKS.md checkboxes, and git.** Subagents must
   NOT write LOG.md, tick checkboxes, or commit. **Hard-won lesson from E2 and E3: the `qa-reviewer`
   agent definition makes verification subagents habitually append audit NOTE/DONE lines to LOG.md even
   when explicitly told not to — this happened on nearly every E3 task.** Mitigate explicitly: in every
   verification-agent prompt, instruct the agent to **RETURN its findings as its final message only and
   write NOTHING to LOG.md/TASKS.md**, and have the orchestrator transcribe any needed NOTE/AUDIT line
   itself (with a correct `date -u` UTC timestamp). **After every subagent batch, check the
   working-tree LOG.md for pollution** (`git --no-pager diff HEAD -- LOG.md`); if a subagent appended,
   clean it pre-commit (`git checkout HEAD -- LOG.md` then re-append your own legitimate STARTED lines)
   and record the cleanup in an orchestrator NOTE — the committed ledger is the append-only artifact.
   You append the STARTED line (attributed to the executing agent) before launching each task, and the
   DONE/BLOCKED line only after you have verified the gate. LOG.md is append-only — new lines at the
   bottom, never edit or reorder. Format:
   `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`.
2. **Parallel agents run only scoped checks** (their own pytest files; `ruff check --no-cache`;
   `mypy --config-file services/pipeline/pyproject.toml` with a private `--cache-dir`;
   `python3 scripts/copy_lint.py`). The full `make check` runs serially, by you, at each integration
   point — concurrent full gates race the venv. Never run `make check` / `make install` / pip / npm
   install inside an agent. Never run two agents editing the same file concurrently (e.g. both editing
   `resolution/rules.py` or both editing `scoring/fas.py`) — serialize them.
3. **One conventional commit per completed task**, made by you after its gate is green, e.g.
   `feat(resolution): full rule library — conditional activation + default horizons + reversals (E4-T1)`.
   Commits end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Commit the ledger
   (LOG.md + TASKS.md + EX-dept.md) at the epic close (a `chore:` commit), as E2/E3 did.
4. **DoD triple per task:** `make check` green + TASKS.md checkbox ticked + LOG.md DONE line stating
   the verification evidence (test count) and modules touched. For an ADR-gated BLOCKED task: seam
   committed + `BLOCKED` line + ADR drafted (proposed) + checkbox left UNTICKED + EX-dept.md entry.
5. If a task is blocked (ADR-gated dependency) or an agent fails after a retry (an implementation agent
   died on a socket error mid-task during E3 — spawn a fresh agent to finish the remaining, precisely
   scoped work), append a `BLOCKED` line with the reason and continue with whatever is unblocked;
   report it at the end. Bring the DB up before ledger/claims/price-touching tasks so DB-backed tests
   actually run (they skip hermetically via `db_conn` when the DB is down) — say so in the DONE evidence.

## Binding constraints (violations are session failures)

- **Append-only ledger (NFR-3):** `resolutions` and `scores` are never UPDATEd/DELETEd (DB triggers
  enforce). Corrections and recomputes APPEND superseding rows (`supersedes_resolution_id` /
  `supersedes_score_id`); E4-T5 archives the prior ledger and keeps it queryable. `claims` is mutable
  working state (status transitions, dedup_cluster_id, flags are normal UPDATEs).
- **Mock-first integrations:** every external dependency (price APIs, CCXT, embeddings, LLM, Label
  Studio) sits behind a small interface with a fixture-backed fake; CI and the demo never touch the
  network, real credentials, or a live model/price feed. `FakePriceSource` stays the CI path.
- **AC-1 golden-set gate stays green:** the E3-T6 harness is a required check (precision ≥95% AND
  recall ≥80%, non-vacuous). Do not weaken it; if an E4 change touches extraction-visible behavior,
  keep it green by fixing the data/logic, never the threshold.
- **Boring stack, locked:** no new dependencies / no formula or convention changes without my approval
  + an ADR (the gates above). A helper used once gets inlined.
- **Regulatory firewall (AC-7):** no buy/sell/hold/signal/moon/guaranteed/recommendation/financial-
  advice language in any user-visible copy, fixture/price/methodology strings included.
  `scripts/copy_lint.py` enforces it (it scans `apps/web/**/*.ts(x)`, `data/fixtures/*.json` + `*.jsonl`,
  and `docs/METHODOLOGY.md`); fix the wording, never the linter.
- **Reproducibility (NFR-2):** every published claim/resolution/score records its
  model/prompt/methodology version, source offset, transcript span, rule_id, price citation, and
  reviewer_id when QA-touched.
- **Scope lock:** crypto + YouTube only; no auth, no payments; nothing from E5–E6 sneaks in (no real
  embeds / OG cards / dispute forms — that is E5; no dispute SLA / freshness alert / GDPR tooling —
  that is E6). Quotes stay ≤15 words (NFR-4).
- **Never silence a gate** (no `# type: ignore`, `# noqa`, eslint-disable, test deletion, skipped/
  trivially-true assertions to reach green). For an optional/ADR-gated package mypy can't resolve, add
  a scoped `[[tool.mypy.overrides]] ... ignore_missing_imports = true` stanza in
  `services/pipeline/pyproject.toml` (the agreed mechanism — see the faster_whisper/boto3/
  sentence_transformers entries), not an inline suppression.

## Environment notes (carried from the E1/E2/E3 sessions)

- Python 3.12 venv at `services/pipeline/.venv`; run workers/CLIs directly, e.g.
  `services/pipeline/.venv/bin/python -m brier_pipeline.demo`. `make check` =
  copy-lint → ruff (lint+format over `services/pipeline scripts`) → mypy strict → pytest → tsc →
  eslint; mypy needs `--config-file services/pipeline/pyproject.toml` (the Makefile handles it).
- Docker CLI is `/usr/local/bin/docker`; daemon may need `open -a Docker` first. The pipeline-demo runs
  the full fixture thread (`make pipeline-demo`); it is idempotent.
- DB-backed tests use the rolled-back `db_conn` fixture (`tests/conftest.py`); prefer a synthetic
  in-test fixture over coupling to committed demo state. Remove each E4 smoke probe in
  `tests/test_smoke.py`'s `NOT_IMPLEMENTED_PROBES` as you implement it (`rules.resolve_conditional`,
  `rules.detect_contradictions`, `fas.recompute_all`, `base_rates.base_rate`,
  `CoinGeckoPriceSource.daily_closes`), plus any now-unused imports (ruff F401).
- Recorded-fixture pattern for any new external seam: check canned request/response pairs into
  `data/fixtures/` (copy-lint clean, fictional) and have the adapter accept an injected callable
  defaulting to the real one; tests inject the recorded boundary. No network in CI.
- **The adversarial verification panel earns its keep.** Every E3 task hit a real blocker the
  scoped checks missed (hedge-word scoring dodge, vacuous AC-1 gate, dedup horizon-bridge, EC-3/F
  denominator conflict, two `# type: ignore` smuggled into tests). Run a multi-lens panel (correctness,
  spec-fidelity, ledger/append-only, gate-silencing) after each task's `make check` and before each
  commit; fix what it finds.

## Closing report (required — covers the whole epic)

End the session with: (1) per-task status table E4-T1..E4-T5 (DONE/BLOCKED + evidence line),
(2) final `make check` output summary, (3) a short demonstration that the resolution rule library,
base rates, contradiction detection, and a methodology-version recompute work on fixtures (e.g.
`make pipeline-demo` plus the recompute producing a new archived `score_run`), (4) any ADR drafts
(CCXT / base-rate methodology) and the ratification status of ADR-0006/0007, (5) the methodology
version before/after + the changelog entry, (6) LOG.md tail, (7) `git log --oneline 052c9e7..HEAD`,
(8) the qa-reviewer audit findings, (9) `EX-dept.md` state, (10) next unblocked tasks with suggested
owners (E5 web-completion: E5-T1 real embeds, E5-T2 corrections log, E5-T3 dispute flow, E5-T4 OG
cards, E5-T5 SEO, E5-T6 waitlist; plus the E6 trust/ops tasks).

## Final phase — write the next session prompt (do not skip)

After the qa-reviewer audit and the closing report, the **last phase of the workflow must spawn one
agent (or do it yourself as the orchestrator) that writes `PROMPT-E5.md`** — the session prompt for
**Epic E5 (Web completion)** — into the repo root, modeled exactly on the structure of this file and
`PROMPT-E3.md`/`PROMPT-E4.md`. That generated prompt must:

1. Reflect the **post-E4 repo state**: the new HEAD commit, the `make check` test count, which E4 tasks
   are DONE vs BLOCKED, any ADRs landed/ratified (CCXT / base-rate methodology / ADR-0006/0007), the
   new methodology version + recompute/changelog status, and the live DB/fixtures state.
2. Enumerate the **E5 tasks from TASKS.md** (E5-T1 receipts with real embeds [owner: frontend-engineer],
   E5-T2 corrections-log page, E5-T3 dispute flow [frontend-engineer form + pipeline-engineer intake],
   E5-T4 OG share cards, E5-T5 SEO + name-query metadata, E5-T6 badge waitlist + newsletter capture)
   with their real owners and dependency shape, and call out the E5-specific binding constraints (the
   AC-7 regulatory firewall on all new user-visible copy; the `apps/web` server-components-by-default +
   `lib/db.ts`-only read layer; AC-2 receipt player starts within 3s; AC-6 deletion flag on receipts;
   Lighthouse mobile ≥90 / p95 <2s; no auth/payments; the same ADR gate for any new dependency such as
   Resend/Buttondown/Vercel-OG, behind a mock-first seam).
3. Carry forward the orchestration rules (including the LOG-ownership mitigation above), the ADR gate,
   the binding constraints, and the environment notes, updated for E5 (note `frontend-engineer` owns
   most E5 tasks and the `apps/web` checks — eslint/tsc/`npm run build` — matter more there).
4. **Itself end with this same "Final phase — write the next session prompt" instruction**, so the
   chain continues (E5 writes `PROMPT-E6.md`, and so on through E6). This is what makes the epic chain
   self-perpetuating: every epic prompt closes by generating the next one.

Append a LOG.md NOTE line recording that `PROMPT-E5.md` was written, and mention it in the closing
report. Do not commit `PROMPT-E5.md` (session tooling stays untracked, like this file).


## ═══════════════════════ PROMPT-E5.md ═══════════════════════

# Session prompt — Implement Epic E5 (Web completion) via workflows

Copy everything below the line into a fresh Claude Code session started at the repo root on the
**Ubuntu 24.04 VPS** (your `git clone` location — referred to below as `$REPO`). Unlike
`PROMPT-E1.md`…`PROMPT-E4.md`, **this file is committed to the repo on purpose** so it travels with
`git clone` to the VPS and is the first thing you read there.

---

## Environment migration — this session runs on an Ubuntu 24.04 VPS (READ FIRST)

**The project has moved from a macOS laptop to an Ubuntu 24.04 LTS VPS, and this is the first session
to run there.** The rest of this prompt was written on macOS; translate the environment as below.
Wherever a later section says `open -a Docker`, `/usr/local/bin/docker`, or a
`/Users/ae/repo/brier-claude/...` path, use the Ubuntu equivalents established here — they OVERRIDE the
macOS-specific commands wherever they appear.

- **Repo root (`$REPO`).** The macOS path `/Users/ae/repo/brier-claude` does not exist on the VPS. The
  repo root is your clone location (e.g. `~/brier-claude` or `/srv/brier-claude`); `cd` into it and run
  every command from there. Read every `/Users/ae/repo/brier-claude/...` path in this file as `$REPO/...`.
- **Docker = Engine + systemd, not Desktop.** Ubuntu runs Docker Engine + the compose plugin under
  systemd (there is no Docker Desktop / `open -a Docker`). The daemon normally auto-starts on boot;
  start/verify it with `sudo systemctl enable --now docker` then `docker info`. The CLI is `docker` on
  PATH (`/usr/bin/docker`), NOT `/usr/local/bin/docker`. Wherever this file says `open -a Docker`, do
  `sudo systemctl start docker`. If `docker` needs `sudo`, add your user to the group once
  (`sudo usermod -aG docker $USER`, then re-login). The dev DB still runs in compose
  (`docker compose up -d db`, driven by `make seed`); no host Postgres is required.
- **First-run VPS setup (do once, before the mission):**
  1. `sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3-pip build-essential git ca-certificates curl` (Ubuntu 24.04 ships Python 3.12).
  2. Install Docker Engine + the compose plugin (docker.com convenience script or distro packages),
     `sudo systemctl enable --now docker`, and add your user to the `docker` group.
  3. Install Node.js ≥20 LTS (nodesource or nvm) for `apps/web` (Next.js); confirm with `node -v`.
  4. From `$REPO`: `make install` (creates `services/pipeline/.venv` + installs pipeline deps; or do it
     by hand — `python3.12 -m venv services/pipeline/.venv && services/pipeline/.venv/bin/python -m pip install -e "services/pipeline[dev]"`), then `cd apps/web && npm install` for the web deps.
  5. `make seed` (idempotent: runs `docker compose up -d db`, applies migrations 0001–0006, seeds the 3 fixture analysts).
  6. **Migration acceptance test — both must pass before starting E5:** `make check` green (≈564 pytest
     + 1 benign skip; copy-lint + ruff + mypy strict + tsc + eslint clean) AND `make pipeline-demo`
     prints the v1.1 ranked board (NorthChain 59.3 / VectorEdge 58.0 / Aylin 54.7). If either fails, fix
     the *environment* (not the code) until both are green, then begin the mission.
- **What travels vs what you must re-set.** `.claude/` (scoped agents, skills, settings), the
  `docker-compose` file, the `Makefile`, and `migrations/` are repo-relative and portable — they arrive
  with the clone. You must re-set on the VPS: your git identity, and (only for live runs, never for
  CI/tests) any API keys such as `BRIER_ANTHROPIC_API_KEY` / `BRIER_COINGECKO_API_KEY` — `make check`
  and the demo are mock-first and need none. Interactively-authenticated MCP servers (claude.ai
  Gmail/Calendar/Drive) may be absent on a headless VPS; this project does not use them.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube
analysts). Epics E1 (Walking Skeleton), E2 (Ingestion), E3 (Extraction + QA), and E4 (Resolution +
Scoring hardening) are complete and committed — HEAD `9d480a2`, `make check` green (**564 pytest + 1
benign skip** + copy-lint + ruff lint/format + mypy strict (34 files) + tsc + eslint all clean). The
qa-reviewer audited E4 as **PASS** (no blockers, no should-fixes). Your mission this session:
**implement Epic E5 — Web completion — end to end (tasks E5-T1 through E5-T6 in TASKS.md), driving
each task to the Definition of Done, then run the qa-reviewer session audit and write the next epic's
session prompt (`PROMPT-E6.md`).**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to workflows for
this session. Orchestrate with the scoped subagents in `.claude/agents/`: **`frontend-engineer` owns
E5-T1, E5-T2, E5-T4, E5-T5, E5-T6 and the form half of E5-T3** (all `apps/web` work);
**`pipeline-engineer` owns the intake half of E5-T3** (dispute ticket persistence + SLA fields in
`services/pipeline`); `qa-reviewer` owns the audits. Run an adversarial verification panel before each
gate (this caught a real blocker or a load-bearing should-fix on **every single E4 task** — a
conditional price-window that deferred forever, a void sentinel that would have violated a DB CHECK
constraint, a `# type: ignore` smuggled into tests, a misleading credibility-moat demo narrative, an
EC-4/EC-10 flag with no enforcement — so do not skip it).

## Current state (verified at HEAD `9d480a2`)

- **Dev DB:** docker-compose Postgres (container `brier-db`, dsn
  `postgresql://brier:brier@localhost:5432/brier`). Migrations 0001–0006 applied; pgvector enabled;
  `claims.embedding vector(384)` exists. Fixture data present: 3 analysts, 14 videos, 14 transcripts,
  35 claims, 26 resolutions, score ledger (now stamped **v1.1**), `price_daily` (1674 fixture closes).
  Docker may be stopped after a reboot: `sudo systemctl start docker` (Ubuntu — see the migration
  section), wait for the daemon, then `make seed` is idempotent. `make pipeline-demo` runs the full
  fixture thread and prints the ranked board (now under
  methodology **v1.1**: NorthChain 59.3 / VectorEdge 58.0 / Aylin 54.7 — the VectorEdge-over-Aylin
  inversion demonstrates "higher raw hit rate ≠ higher FAS").
- **The web app already renders real data (E1-T5):** `apps/web` (Next.js App Router, TS strict,
  Tailwind; server components by default; reads via `lib/db.ts` only). Pages: `app/page.tsx`
  (leaderboard), `app/a/[slug]/page.tsx` (analyst), `app/r/[claimId]/page.tsx` (receipt),
  `app/methodology/page.tsx` (renders the methodology doc). Components: `FASBadge`, `ClaimTable`,
  `ClaimStatusChip`, `PriceChart` (lightweight-charts), `ReceiptPlayer` (**placeholder** player —
  E5-T1 replaces it with a real embed), `TrendSparkline`. Read layer: `lib/db.ts`, `lib/types.ts`.
  Numbers on every page must match the ledger exactly (AC-3). `apps/web` web deps so far: Next + React
  + Tailwind + lightweight-charts — **no Resend/Buttondown/Vercel-OG yet** (E5 adds them behind the
  ADR gate + a mock-first seam).
- **Fixtures are fictional:** NorthChain, Aylin Markets, VectorEdge (`data/fixtures/analysts.json`),
  plus a 50-analyst fictional roster (`data/fixtures/roster.json`), `data/fixtures/golden_set.jsonl`
  (200 labeled spans), `data/fixtures/llm/*.json` (recorded extraction pairs), and
  `data/fixtures/coingecko/*.json` (E4 recorded price pair). Keep all new fixture/copy fictional and
  brandkit-voiced; `scripts/copy_lint.py` scans `apps/web/**/*.ts(x)`, `data/fixtures/*.json` **and**
  `*.jsonl`, and `docs/METHODOLOGY.md`.
- **E4 status (this is what E5 builds on):**
  - **DONE:** E4-T1 full resolution rule library (`resolution/rules.py` + `resolver.py`:
    `materialise_horizon_deadline`, `resolve_conditional` with defer-vs-void never-fires conventions,
    `resolve_reversal_close` EC-11; published as METHODOLOGY §2.1–2.3, rule_ids
    `conditional_at_horizon.v0`/`conditional_void.v0`/`reversal_close.v0`); E4-T4 contradiction
    detection (`detect_contradictions`, EC-6 hedging void → both void + `contradiction_void.v0` flag,
    METHODOLOGY §2.4; enforced in a resolver pre-pass); E4-T5 methodology recompute
    (`scoring/fas.py:recompute_all` → new `methodology_bump` score_run, prior ledger archived +
    queryable); E4-T2 real base rates (`resolution/base_rates.py:base_rate` from trailing-≤5y history,
    replacing `fixture_base_rate`; `CoinGeckoPriceSource` stdlib-urllib seam; **methodology bumped
    v1.0 → v1.1** with ADR-0009 + changelog + full recompute); E4-T3 edge cases EC-1..EC-12
    (`rules.py` flag helpers + tests; EC-4 sponsor + EC-10 legal-fast-track enforced in
    `qa/queue.route_low_confidence`).
  - **BLOCKED-by-design (ADR-gated heavy dep; seam is the CI path):** the **CCXT cross-check** for
    price-outage detection (E4-T2 sub-item) — `CcxtCrossCheckSource` seam landed (lazy import,
    `RuntimeError`→ADR-0009, mocked boundary, `ccxt` NOT in deps, scoped mypy override). E4-T2 itself
    is **DONE** (the core base-rate engine + CoinGecko composite + version bump ship without it);
    recorded in `EX-dept.md`. Also still blocked from earlier epics: **E2-T4/E2-T5** (real
    transcription + R2 storage, ADR-0003/0004) and **E3-T5** (production embedding model, ADR-0008).
- **Methodology version: v1.1.** `config.METHODOLOGY_VERSION = "v1.1"`. The bump was the sanctioned
  base-rate methodology change (ADR-0009, recompute via `recompute_all`). **The binding worked
  examples in `tests/test_fas.py` (FAS_A≈47.02, FAS_B≈66.74, B-outranks-A, k=25, min n=20) are
  unchanged** — they use explicit base rates. E5 is **web only and changes no scoring** — do not touch
  `scoring/`, `resolution/`, the methodology, or the version. If an E5 change would move a published
  number, that is a bug in E5, not a methodology bump.
- **ADRs:** **ADR-0002 accepted** (binding scoring pins); **ADR-0006 + ADR-0007 accepted** (ratified in
  the E4 methodology gate — EC-3 not in F denominator; FR-204 classifier conventions); **ADR-0003,
  0004, 0005, 0008, 0009 proposed** (implementation landed behind seams, pending human approval). Any
  new E5 dependency needs its own ADR (see the ADR gate below).
- **Known follow-up (not an E5 task, carry as backlog):** the demo price fixtures are only ~18 months,
  so E4 base rates over them are thin/extreme (b=0.0/1.0) and the demo inversion's VectorEdge half is
  the min-windows fallback, not a measured prior (documented in `test_demo_e2e.py` + ADR-0009). Extending
  the price fixtures to a multi-year span would give a fully-measured demo. Mention it in the closing
  report; do not action it in E5 unless it blocks a web task (it does not).

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, and the **binding 5-rule logging contract**.
2. `TASKS.md` — the E5 task definitions and acceptance criteria are authoritative; E1, E2 (four done),
   E3 (five done), and E4 (all five done) are ticked; E2-T4/T5, E3-T5 are unticked (BLOCKED).
3. `docs/PRD.md` — **the E5 acceptance criteria are the spec.** At minimum FR-403 (receipt player +
   rationale + dispute link) / **AC-2 (player starts within 3s)** / **EC-1 + AC-6 (deletion flag on
   receipts; claims/resolutions persist)**; FR-405 (corrections log + dispute flow) / **AC-5 (100% of
   disputes adjudicated within 7 days)** / US-006 / UF-3; §19 (social/OG layer); FR-407 + §18 (SEO,
   name-query metadata, **Lighthouse mobile ≥90, p95 <2s** on the leaderboard); FR-406/FR-408 +
   US-007/US-008 (waitlist + newsletter, double opt-in, one-click unsubscribe); **NFR-3** (the
   corrections log is the public face of the append-only ledger); **AC-7** (the regulatory firewall on
   all new user-visible copy).
4. `docs/BRANDKIT.md` — voice/register for all new user-visible copy (the corrections log + dispute
   pages are neutral-register; no buy/sell/hold/recommendation/hype language — copy-lint enforces it).
5. `apps/web` — the E1-T5 pages/components/read-layer you extend. Server components by default; **reads
   go through `lib/db.ts` only** (never query the DB from a component). `lib/types.ts` is the shared
   shape. Keep numbers ledger-exact (AC-3).
6. `docs/adr/0001`–`0009` — the ADR ledger and the **proposed vs accepted** status of each; ADR-0001 is
   the ADR process; the seam pattern (stdlib-REST, lazy-import, mocked boundary, `RuntimeError`→ADR) is
   how every external dependency is introduced.
7. `LOG.md` tail — confirm the last line is the E4 qa-reviewer `AUDIT | NOTE` entry (PASS) before
   appending anything.
8. `EX-dept.md` — the blocked-by-design ledger (E2-T4/T5, E3-T5, E4-T2 CCXT sub-item). Add any new E5
   blocked-by-design items (a heavy web dep you seam instead of installing).

## The six tasks and their dependency shape (owners as noted)

- **E5-T1 — Receipts with real embeds** · deps: E1-T5 · PRD FR-403, AC-2, US-003, EC-1 · owner:
  **frontend-engineer**. Replace the placeholder `ReceiptPlayer` with the official YouTube IFrame
  player auto-seeked to the claim's `source_offset_seconds` (**must start within 3 s — AC-2**); a
  **deletion-flag overlay** for dead sources (**AC-6** — read the `source_status`/`source_deleted`
  signal E4-T3/E6-T3 surface; the claim + resolution still render, marked deleted, never erased — NFR-3);
  the resolution rationale + price citation; and a dispute link (wired in E5-T3). Keep the embed
  mock-first for CI: no network hit in tests/build — the IFrame is a client island; SSR renders the
  card + a deterministic placeholder until hydration.
- **E5-T2 — Corrections log page** · deps: E1-T5 · PRD FR-405, NFR-3 · owner: **frontend-engineer**.
  A public, chronological page pairing each superseded resolution with its superseding one
  (`supersedes_resolution_id` chains in the append-only ledger) and each prior score with its recompute
  successor (`supersedes_score_id` / `score_runs`). Neutral register (copy-lint). This is the public
  proof that corrections are append-only events, not silent edits (NFR-3 / AC-4). Reads via `lib/db.ts`.
- **E5-T3 — Dispute flow** · deps: E5-T2 · PRD FR-405, US-006, AC-5, UF-3 · owner: **frontend-engineer
  (form)** + **pipeline-engineer (intake)**. A per-claim dispute form → a tracked ticket with an
  auto-emailed ID → a **7-day SLA countdown (AC-5)** → adjudication recorded → a public corrections-log
  entry when the outcome is corrective. **Pipeline-engineer** owns the intake: a `disputes` table
  (migration `0007_*.sql`), ticket persistence, SLA-clock fields, and an adjudication path that, when
  corrective, **appends a superseding resolution** (never edits — NFR-3) and links the corrections log.
  Email is an external dependency → **seam it** (a `Notifier` interface with a fixture-backed fake; the
  real Resend/SES adapter is ADR-gated — see the ADR gate). **Frontend-engineer** owns the form +
  ticket-status display. The actual SLA *alerting* job is **E6-T1** — do not build it here.
- **E5-T4 — OG share cards** · deps: E1-T5 · PRD §19 social layer · owner: **frontend-engineer**.
  Per-receipt and per-analyst Open Graph cards (score, claim, outcome) with **alt text on every card**.
  Vercel-OG (`@vercel/og`/`next/og`) is a new dependency → ADR + mock-first seam (render the card via a
  route handler; tests assert the card's data/markup deterministically, never fetch a live image).
- **E5-T5 — SEO + name-query metadata** · deps: E1-T5 · PRD FR-407, §18 · owner: **frontend-engineer**.
  Server-rendered per-analyst metadata for name queries (`generateMetadata`), a sitemap, structured
  data, **Lighthouse mobile ≥90**, and **p95 <2s on the leaderboard** (materialized views + a cache
  layer — keep numbers ledger-exact). No new heavy dep needed; if you add a caching lib, ADR-gate it.
- **E5-T6 — Badge waitlist + newsletter capture** · deps: E1-T5 · PRD FR-406, FR-408, US-007, US-008 ·
  owner: **frontend-engineer**. A waitlist CTA on analyst pages; a site-wide newsletter signup with
  **double opt-in** and **one-click unsubscribe**. Buttondown/Resend is a new dependency → ADR +
  mock-first seam (a `Subscriber`/`Notifier` interface + fixture-backed fake; CI never calls the API).

**Suggested workflow shape.** E5-T1, E5-T2, E5-T4, E5-T5, E5-T6 are **all `apps/web`-only and largely
file-disjoint** (distinct pages/components/route-handlers) — they can run in parallel groups, but watch
for shared touch-points: `lib/db.ts`, `lib/types.ts`, `app/layout.tsx`, `package.json`, and
`next.config.ts` are shared files — **serialize any two tasks that edit the same shared file** (the
hard-won shared-file lesson from E2-T3/T4, E3-T4/T5, and the E4 rules.py trio). A good order:
**E5-T2 → E5-T3** (T3's corrections-log entry depends on T2's page; and the form half + intake half of
T3 serialize on the dispute data shape — land the migration + `lib/db.ts` reader first, then the form).
**E5-T1, E5-T4, E5-T5, E5-T6** can each run as their own parallel lane once their shared-file edits are
sequenced. Run E5-T3's **migration `0007` and `lib/db.ts`/`lib/types.ts` changes through one agent
first**, then fan out the rest. Serialize the full `make check` per the rules below.

## The web-completion gate (E5-specific — frontend rigor is the credibility surface)

The web app is what users actually see; a broken receipt or a leaked recommendation is a public failure.

- **AC-2 — the receipt player starts within 3 s.** Structure the embed so first interaction is fast:
  SSR the card immediately, lazy-load the IFrame as a client island, auto-seek on load. Demonstrate the
  3 s budget (e.g. a Lighthouse/trace note or a documented measurement) in the closing report.
- **AC-6 / EC-1 — deletion is a visible flag, never an erasure.** A receipt for a deleted/privated
  source still renders the claim + resolution, marked deleted (NFR-3). Read the `source_status` signal;
  do not hide or delete the row.
- **Lighthouse mobile ≥90 and p95 <2s on the leaderboard (FR-407/§18).** Use materialized views + a
  cache for the leaderboard read; keep every rendered number ledger-exact (AC-3). Report the measured
  Lighthouse score + p95 in the closing report (you may use the `/benchmark` skill or a documented run).
- **NFR-3 on the public surface.** The corrections log and any corrective dispute adjudication must
  reflect **append-only** events: superseded/superseding pairs, never an edited row. Pipeline-side, a
  corrective adjudication **appends a superseding resolution** (`supersedes_resolution_id`) — the DB
  triggers will reject an UPDATE/DELETE on `resolutions`/`scores`.
- **Mock-first for every external service.** Email (Resend/SES), newsletter (Buttondown), OG image
  rendering, and the YouTube IFrame all sit behind a small interface with a fixture-backed fake; CI and
  `npm run build` never hit the network, real credentials, or a live API. The fake is the test/build
  path.

## The ADR gate (carry it forward)

The stack is **locked**: no new dependency without my approval + an ADR (`docs/adr/`, via the
`new-adr` skill — note subagents lack the Skill tool, so they Write the ADR file directly, modeled on
`docs/adr/0003`). E5 introduces several candidate web deps — **`@vercel/og`/`next/og` (E5-T4), a
Resend/SES email client (E5-T3), Buttondown/Resend newsletter (E5-T6), any caching lib (E5-T5)**. For
each: either (a) draft an ADR, present it, and **stop for my approval before adding the dependency**,
or (b) land the real adapter's **seam** — interface honored, real call site structured and unit-tested
against a **mocked** boundary, with the fixture-backed fake remaining the CI/build path — and append a
`BLOCKED` LOG line for the dependency-requiring portion + leave the checkbox UNTICKED + record it in
`EX-dept.md`. **Choose (b) and keep moving if I am not available to approve.** Note that `next/og` ships
*with* Next (no new top-level dependency for OG if you use the built-in `next/og` ImageResponse) — if so,
say so in an ADR note rather than treating it as a heavy add. Calling a REST API via `fetch`/stdlib
instead of an SDK is a legitimate no-new-dependency route — structure it behind the same seam and note
the deviation in an ADR. Report all of this in the closing report.

## Orchestration rules (these prevent real races — follow them)

1. **The orchestrator (you, the main loop) owns LOG.md, TASKS.md checkboxes, and git.** Subagents must
   NOT write LOG.md, tick checkboxes, or commit. **Hard-won lesson from E2/E3/E4: the `qa-reviewer`
   agent definition makes verification subagents habitually append audit NOTE/DONE lines to LOG.md even
   when told not to.** Mitigate explicitly: in every verification-agent prompt, instruct the agent to
   **RETURN its findings as its final message only and write NOTHING to LOG.md/TASKS.md**, and have the
   orchestrator transcribe any needed NOTE/AUDIT line itself (with a correct `date -u` UTC timestamp).
   **After every subagent batch, check the working-tree LOG.md/TASKS.md for pollution**
   (`git --no-pager diff HEAD -- LOG.md TASKS.md`); if a subagent appended, clean it pre-commit
   (`git checkout HEAD -- LOG.md` then re-append your own legitimate lines) and record the cleanup in an
   orchestrator NOTE. (In E4 the structured-output panels wrote nothing — keep that going.) You append
   the STARTED line (attributed to the executing agent) before launching each task, and the DONE/BLOCKED
   line only after you have verified the gate. LOG.md is append-only — new lines at the bottom, never
   edit or reorder. Format:
   `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`.
2. **Parallel agents run only scoped checks.** For `apps/web` tasks that is the frontend gate scoped to
   their files: `cd apps/web && npx tsc --noEmit`, `cd apps/web && npm run lint`, and (when they touched
   build-affecting code) `cd apps/web && npm run build`; plus `python3 scripts/copy_lint.py` for any new
   user-visible copy. For pipeline-side E5-T3 intake: their own pytest file, `ruff check --no-cache`,
   `mypy --config-file services/pipeline/pyproject.toml` with a private `--cache-dir`. The full
   `make check` runs **serially, by you, at each integration point** — concurrent full gates race the
   venv/`.next` build. Never run `make check` / `make install` / `npm install` / pip inside an agent.
   Never run two agents editing the same file concurrently (`lib/db.ts`, `lib/types.ts`,
   `app/layout.tsx`, `package.json`, `next.config.ts`, or a shared migration) — serialize them.
3. **One conventional commit per completed task**, made by you after its gate is green, e.g.
   `feat(web): receipts with real IFrame embed + deletion flag (E5-T1)`. Commits end with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Commit the ledger (LOG.md + TASKS.md +
   EX-dept.md) at the epic close (a `chore:` commit), as E2/E3/E4 did.
4. **DoD triple per task:** `make check` green + TASKS.md checkbox ticked + LOG.md DONE line stating the
   verification evidence (test count + the frontend gate result: `tsc`/`eslint`/`npm run build`, and the
   measured AC-2/Lighthouse/p95 where relevant) and modules touched. For an ADR-gated BLOCKED task: seam
   committed + `BLOCKED` line + ADR drafted (proposed) + checkbox left UNTICKED + EX-dept.md entry.
5. If a task is blocked (ADR-gated dependency) or an agent fails after a retry (an implementation agent
   died on a socket error mid-task during E3 — spawn a fresh agent to finish the remaining, precisely
   scoped work), append a `BLOCKED` line with the reason and continue with whatever is unblocked; report
   it at the end. Bring the DB up before any task whose tests read the ledger (`sudo systemctl start
   docker`, wait, `make seed`) so DB-backed tests actually run — say so in the DONE evidence.

## Binding constraints (violations are session failures)

- **Regulatory firewall (AC-7):** the product never outputs buy/sell/hold or any recommendation
  language — **this is most at risk in E5** because E5 adds the most new user-visible copy (corrections
  log, dispute pages, OG cards, waitlist/newsletter, SEO metadata, alt text). `scripts/copy_lint.py`
  scans `apps/web/**/*.ts(x)`, `data/fixtures/*.json(l)`, and `docs/METHODOLOGY.md`; fix the wording,
  never the linter. Neutral register per `docs/BRANDKIT.md`.
- **Server-components-by-default + `lib/db.ts`-only reads:** never query the DB from a component; all
  reads go through `lib/db.ts`. Keep client islands minimal (the IFrame, form interactivity). Numbers
  rendered must equal the ledger exactly (AC-3).
- **Append-only ledger (NFR-3):** `resolutions` and `scores` are never UPDATEd/DELETEd (DB triggers
  enforce). A corrective dispute adjudication APPENDS a superseding resolution
  (`supersedes_resolution_id`); the corrections log shows the pair. The `disputes` table (new in E5-T3)
  is mutable working state (ticket status/SLA-clock are normal UPDATEs); the *outcome* of a corrective
  dispute is an appended resolution, not an edit.
- **Mock-first integrations:** every external dependency (email, newsletter, OG rendering, YouTube
  embed, any cache backend) sits behind a small interface with a fixture-backed fake; CI and
  `npm run build` never touch the network, real credentials, or a live API/model.
- **Boring stack, locked:** no new dependency without my approval + an ADR (the ADR gate above). A
  helper used once gets inlined.
- **AC-1 golden-set gate stays green:** the E3-T6 harness (precision ≥95% AND recall ≥80%, non-vacuous)
  is a required check; E5 must not touch extraction, but keep the gate green.
- **No scoring/methodology changes in E5.** Do not edit `scoring/`, `resolution/`,
  `config.METHODOLOGY_VERSION`, or `docs/METHODOLOGY.md`. E5 is web. The binding worked examples and the
  v1.1 ledger numbers must not move.
- **Reproducibility (NFR-2):** disputes record the methodology_version in force at adjudication; a
  corrective resolution stamps its own model/prompt/methodology version, rule_id, price citation, and
  reviewer_id. (EC-12 version-pinning + `get_pinned_methodology_version` already exist — use them.)
- **Scope lock:** crypto + YouTube only; no auth, no payments; nothing from E6 sneaks in (no dispute
  *SLA alerting* job / freshness alert / deletion-detection crawler / cost guardrails / GDPR erasure
  tooling — that is E6; E5 builds the dispute *form + intake + corrections log surface*, E6 builds the
  *SLA clock + breach alerts*). Quotes stay ≤15 words (NFR-4).
- **Never silence a gate** (no `# type: ignore`, `# noqa`, `eslint-disable`, `@ts-ignore`, test
  deletion, skipped/trivially-true assertions to reach green). For an optional/ADR-gated package mypy
  or tsc can't resolve, add a scoped config stanza (the agreed mechanism — `[[tool.mypy.overrides]]` for
  Python; a typed module declaration / `tsconfig` path for TS), not an inline suppression. **The E4
  panels caught a `# type: ignore` in E4-T1 and four in E4-T5 pre-commit — assume your agents will try
  the same and catch it in the panel.**

## Environment notes (carried from the E1–E4 sessions)

- **`frontend-engineer` owns most of E5 and the `apps/web` checks matter more here:** `cd apps/web &&
  npx tsc --noEmit` (strict TS), `cd apps/web && npm run lint` (eslint), and `cd apps/web && npm run
  build` (the Next production build — run it for any task that changes routing, metadata, OG handlers,
  or `next.config.ts`). `make check` already runs tsc + eslint; the **production `npm run build`** is
  the extra signal for E5 and should be green before you close a routing/metadata/OG task — note it in
  the DONE evidence.
- Python 3.12 venv at `services/pipeline/.venv` for the E5-T3 intake half; `make check` =
  copy-lint → ruff (lint+format over `services/pipeline scripts`) → mypy strict → pytest → tsc → eslint;
  mypy needs `--config-file services/pipeline/pyproject.toml` (the Makefile handles it).
- Docker CLI is `docker` on PATH (`/usr/bin/docker` on Ubuntu); the daemon is systemd-managed —
  `sudo systemctl start docker` if it is down (see the migration section). `make seed` is idempotent;
  `make pipeline-demo` runs the full fixture thread. Bring the DB up for any ledger-reading web page
  test or the E5-T3 intake tests.
- DB-backed tests use the rolled-back `db_conn` fixture (`tests/conftest.py`); prefer a synthetic
  in-test fixture over coupling to committed demo state. The new `disputes` migration (`0007`) follows
  the numbered `migrations/*.sql` + tiny runner pattern.
- Recorded-fixture pattern for any new external seam (email, newsletter, OG): check canned
  request/response or rendered-output fixtures into `data/fixtures/` (copy-lint clean, fictional) and
  have the adapter accept an injected callable defaulting to the real one; tests inject the recorded
  boundary. No network in CI/build.
- **The adversarial verification panel earns its keep.** Every E4 task hit a real blocker or
  load-bearing should-fix the scoped checks missed (a forever-deferring conditional, a DB-CHECK-violating
  void sentinel, smuggled `# type: ignore`s, a misleading credibility-moat narrative, an unenforced
  EC-4/EC-10 flag). Run a multi-lens panel (correctness, spec-fidelity vs the PRD AC, AC-7 firewall on
  new copy, NFR-3/append-only, accessibility/alt-text + AC-2/Lighthouse budgets, gate-silencing) after
  each task's `make check` and before each commit; fix what it finds.

## Closing report (required — covers the whole epic)

End the session with: (1) per-task status table E5-T1..E5-T6 (DONE/BLOCKED + evidence line incl. the
measured AC-2 player-start, Lighthouse mobile, and leaderboard p95 where relevant), (2) final
`make check` + `npm run build` output summary, (3) a short demonstration that the receipt embed,
corrections log, dispute flow (form → ticket → adjudication → corrections entry), OG cards, SEO
metadata, and waitlist/newsletter work on fixtures (screenshots or a documented dogfood via the
`/browse` skill, plus the dispute-intake DB-backed test), (4) any ADR drafts (Vercel-OG / email /
newsletter / cache) and their proposed-vs-blocked status, (5) any new migration (`0007_*`) and its
schema, (6) LOG.md tail, (7) `git log --oneline 9d480a2..HEAD`, (8) the qa-reviewer audit findings,
(9) `EX-dept.md` state (incl. any new E5 blocked-by-design web deps + the carried E2-T4/T5, E3-T5,
E4-T2-CCXT items), (10) next unblocked tasks with suggested owners (the **E6 trust/ops tasks**: E6-T1
dispute SLA tooling [pipeline-engineer], E6-T2 freshness alerts [pipeline-engineer], E6-T3 deletion
tracking [pipeline-engineer], E6-T4 monitoring + cost guardrails [pipeline-engineer], E6-T5 GDPR/KVKK
erasure handling [pipeline-engineer]) — plus the carried backlog note to extend the demo price fixtures
to a multi-year span for a fully-measured base-rate demo.

## Final phase — write the next session prompt (do not skip)

After the qa-reviewer audit and the closing report, the **last phase of the workflow must spawn one
agent (or do it yourself as the orchestrator) that writes `PROMPT-E6.md`** — the session prompt for
**Epic E6 (Trust + Ops)** — into the repo root, modeled exactly on the structure of this file and
`PROMPT-E4.md`/`PROMPT-E5.md`. That generated prompt must:

1. Reflect the **post-E5 repo state**: the new HEAD commit, the `make check` + `npm run build` test
   counts, which E5 tasks are DONE vs BLOCKED, any ADRs landed (Vercel-OG / email / newsletter / cache)
   and their status, the new migration(s), and the live DB/fixtures state.
2. Enumerate the **E6 tasks from TASKS.md** (E6-T1 dispute SLA tooling, E6-T2 freshness alerts, E6-T3
   deletion tracking, E6-T4 monitoring + cost guardrails, E6-T5 GDPR/KVKK erasure handling — all
   **owner: pipeline-engineer**) with their real owners and dependency shape, and call out the
   E6-specific binding constraints (AC-5 100%-disputes-within-7-days as a launch metric; NFR-1 ≤48h
   freshness; EC-1/AC-6 deletion persistence; NFR-5 hard monthly spend caps with 70% alerts; NFR-6
   GDPR/KVKK erasure with the legitimate-interest balancing test; the same mock-first seam + ADR gate
   for any new monitoring/alerting dependency such as Sentry/Axiom/Better Stack).
3. Carry forward the orchestration rules (including the LOG-ownership mitigation above), the ADR gate,
   the binding constraints, and the environment notes, updated for E6 (note `pipeline-engineer` owns all
   E6 tasks and the `services/pipeline` checks — ruff/mypy/pytest — matter most there; E6 also closes
   several long-blocked items if their ADRs are approved — E2-T4/T5, E3-T5, E4-T2-CCXT).
4. **Itself end with this same "Final phase — write the next session prompt" instruction**, so the
   chain continues (E6 writes `PROMPT-E7.md` if any epic follows, or a "project complete / launch
   readiness" closeout if E6 is the final epic). This is what makes the epic chain self-perpetuating:
   every epic prompt closes by generating the next one.

Append a LOG.md NOTE line recording that `PROMPT-E6.md` was written, and mention it in the closing
report. **Commit `PROMPT-E6.md`** in a small `chore:` commit — as of the VPS migration the epic prompts
are committed (like this file) so they travel with `git clone` and are available on the VPS; this
reverses the earlier "leave it untracked" convention from PROMPT-E1..E4.


## ═══════════════════════ PROMPT-E6.md ═══════════════════════

# Session prompt — Implement Epic E6 (Trust + Ops) via workflows

Copy everything below the line into a fresh Claude Code session started at the repo root on the
**Ubuntu 24.04 VPS**. Like `PROMPT-E5.md`, **this file is committed to the repo on purpose** so it
travels with `git clone` and is the first thing you read on the VPS.

---

## Environment — Ubuntu 24.04 VPS (READ FIRST)

The project runs on an Ubuntu 24.04 LTS VPS (migrated from macOS during E5). **If you are continuing on
the same VPS the E5 session used, the toolchain is already installed** — you only need to verify it and
bring the DB up. If you are on a fresh clone/box, do the first-run setup below.

- **Repo root (`$REPO`).** `cd` into your clone location (e.g. `~/brier-claude` or `/srv/brier-claude`)
  and run every command from there. Read any `/Users/ae/repo/brier-claude/...` path in older docs as `$REPO/...`.
- **Docker = Engine + systemd (no Docker Desktop).** The daemon auto-starts on boot; if down,
  `sudo systemctl start docker`. The CLI is `docker` on PATH (`/usr/bin/docker`). **Hard-won E5 gotcha:**
  the dev user may be a member of the `docker` group in `/etc/group` but the *login session predates it*,
  so `id` does not show the group and `docker` is permission-denied. If `sudo` needs a password you cannot
  supply, wrap docker/compose/`make seed`/`make pipeline-demo` in `sg docker -c '...'` (e.g.
  `sg docker -c 'make -C $REPO seed'`). **`make check` itself needs no docker** once the DB container is up —
  pytest connects to `localhost:5432` over TCP; only `seed`/`pipeline-demo`/`dev`/`db-up` call the docker API.
  A fully fresh login session (new SSH) picks up the group and avoids `sg` entirely.
- **Node ≥20 + the pipeline venv (already installed on the E5 VPS).** Node 20 was installed via `nvm` and
  symlinked into `~/.local/bin` (`node`/`npm`/`npx`) so non-interactive shells (which skip the `~/.bashrc`
  nvm init) still resolve it. The Python 3.12 venv lives at `services/pipeline/.venv`. If you are on a
  fresh box where `apt` needs an unavailable sudo password, the E5 workarounds were: Node via nvm
  (`curl … nvm install 20`) symlinked into `~/.local/bin`; venv via `python3.12 -m venv --without-pip
  services/pipeline/.venv` then `curl https://bootstrap.pypa.io/get-pip.py | services/pipeline/.venv/bin/python`
  (the distro lacked `python3.12-venv`/`ensurepip`), then `make install`.
- **First-run-or-resume acceptance test — both must pass before starting E6:** `make check` green
  (**596 pytest + 1 benign skip**; copy-lint + ruff + mypy strict (33 files) + tsc + eslint clean — bring the
  DB up first: `sg docker -c 'make -C $REPO seed'`) AND `make pipeline-demo` prints the v1.1 ranked board
  (**NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7**, 20 cumulative resolutions). If either fails, fix the
  *environment* (not the code) until both are green, then begin the mission. **Note the canonical board is
  20 resolutions / 59.0·57.5·51.7** — the pre-E5 baseline fix corrected the stale "26 / 59.3·58.0·54.7"
  numbers that earlier prompts cited (those depended on a stale macOS dev DB; see the E5 NOTE in LOG.md).
- **What travels vs what you re-set.** `.claude/`, `docker-compose.yml`, the `Makefile`, and `migrations/`
  arrive with the clone. Re-set on a fresh box: your git identity, and (only for *live* runs, never for
  CI/tests) any API keys — `make check`, the demo, and `npm run build` are mock-first and need none.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube analysts).
Epics E1 (Walking Skeleton), E2 (Ingestion), E3 (Extraction + QA), E4 (Resolution + Scoring hardening),
and **E5 (Web completion)** are complete and committed. `make check` is green (**596 pytest + 1 benign
skip** + copy-lint + ruff lint/format + mypy strict (33 files) + tsc + eslint all clean); `npm run build`
is clean and offline-safe. The qa-reviewer audited E5 as **PASS** (no blockers). Your mission this
session: **implement Epic E6 — Trust + Ops — end to end (tasks E6-T1 through E6-T5 in TASKS.md), driving
each task to the Definition of Done, then run the qa-reviewer session audit and write the next session
prompt (`PROMPT-E7.md`, or a project-complete / launch-readiness closeout if E6 is the final epic).**

**Use the Workflow tool for multi-agent orchestration.** I am explicitly opting in to workflows for this
session. **All five E6 tasks are owned by `pipeline-engineer`** (`services/pipeline` work);
`qa-reviewer` owns the audits; `scoring-quant` only if a trust metric touches scoring (it should not).
Run an adversarial verification panel before each gate — in E5 the panels caught a real blocker or
load-bearing should-fix on **every task** (missing `corrections`-table INSERT, a smuggled
`eslint-disable @next/next/no-img-element`, a dead "alt-via-response-header", a per-request DB pool leak,
a Buttondown 400-swallowing bug, the stale-DB latent baseline defect) — do not skip it.

## Current state (verified at the E5 close)

- **HEAD:** the E5 epic-close `chore:` ledger commit (on top of `2bf641c` "fix(web,tests): E5 audit
  should-fixes"). `git log --oneline 9d480a2..HEAD` shows the E5 chain: baseline fix `4551720`, lockfile
  `b2c7210`, E5-T3 intake `2f8d204`, E5-T2 `f28488a`, E5-T1 `1fd4332`, E5-T3 form `a8e82da`, E5-T4
  `cdb6ac3`, E5-T5 `8173eb8`, E5-T6 `0d8ff12`, audit fixes `2bf641c`, + the ledger close.
- **Dev DB:** docker-compose Postgres (container `brier-db`, dsn
  `postgresql://brier:brier@localhost:5432/brier`). **Migrations 0001–0007 applied** (0007 = additive
  disputes columns `reviewer_id` + `resolution_id`; it reuses the pre-existing `0006_ops.sql` `disputes`
  + `corrections` tables and the `models.py` `Dispute`/`Correction` models — no rename). pgvector enabled.
  Fixtures on a fresh `make seed`+`make pipeline-demo`: 3 analysts, 14 videos, 14 transcripts, 35 claims,
  **20 resolutions**, score ledger v1.1, `price_daily` (1674 closes); `disputes` + `corrections` start
  **empty** (populated by the dispute flow). Canonical board: NorthChain 59.0 / VectorEdge 57.5 /
  Aylin 51.7 (the VE-over-Aylin FAS inversion with Aylin's higher raw hit rate still holds).
- **The web app is COMPLETE (E5):** `apps/web` (Next 15 App Router, TS strict, Tailwind; server
  components by default; reads via `lib/db.ts` only). Pages/routes: leaderboard (`app/page.tsx`, Next
  built-in cached, p95≈38ms), analyst (`app/a/[slug]` + `generateMetadata` + JSON-LD + `opengraph-image`),
  receipt (`app/r/[claimId]` real YouTube IFrame embed + deletion overlay + dispute link + `opengraph-image`),
  methodology, **corrections log** (`app/corrections`), **dispute form** (`app/r/[claimId]/dispute` +
  `app/api/disputes`), **newsletter/waitlist** (`app/api/newsletter`, `app/api/waitlist`,
  `app/newsletter/unsubscribe`, footer + analyst CTA), `sitemap.ts`, `robots.ts`. Read/write layer:
  `lib/db.ts` (reads, `getAnalyst`/`getReceipt` are `React.cache`-wrapped), `lib/dispute-intake.ts` +
  `lib/subscriber.ts` (request-time write seams), `lib/types.ts`, `lib/og.tsx`. Numbers are ledger-exact (AC-3).
- **E5 status (what E6 builds on):**
  - **DONE (all five):** E5-T1 receipts w/ real embeds (`1fd4332`); E5-T2 corrections log (`f28488a`);
    E5-T3 dispute flow — pipeline intake `2f8d204` (`brier_pipeline/disputes/{intake,notify}.py`,
    `create_dispute`/`record_adjudication`: corrective **appends a superseding resolution** via
    `resolver._insert_resolution` + writes the `corrections` table — NFR-3) + web form `a8e82da`;
    E5-T4 OG cards via built-in `next/og` (`cdb6ac3`); E5-T5 SEO/metadata/sitemap/JSON-LD + leaderboard
    cache (`8173eb8`); E5-T6 waitlist + newsletter (`0d8ff12`).
  - **ADR-gated seams (real adapter pending human approval + keys; the TASK is DONE, the fake is CI):**
    **ADR-0010** Resend transactional email (the dispute ticket-id confirmation; `getNotifier()` factory
    in both the pipeline and `apps/web/lib/dispute-intake.ts`); **ADR-0013** Buttondown newsletter
    (`apps/web/lib/subscriber.ts`, `getSubscriber()` factory, double opt-in + one-click unsubscribe);
    **ADR-0012** leaderboard cache (Next built-in `unstable_cache` ships now, NO Upstash dep; matview +
    Redis deferred prod-scale); **ADR-0011** OG via `next/og` (built-in, NO new dependency). All four are
    **proposed**. Recorded in `EX-dept.md`.
- **Methodology version: v1.1** (`config.METHODOLOGY_VERSION = "v1.1"`). **E6 is trust/ops and changes no
  scoring** — do not touch `scoring/`, `resolution/`, the methodology, or the version. The binding worked
  examples (`tests/test_fas.py`: FAS_A≈47.02, FAS_B≈66.74, B-outranks-A, k=25, min n=20) must not move.
- **ADRs:** **ADR-0002 accepted** (scoring pins); **ADR-0006 + ADR-0007 accepted** (E4 methodology gate).
  **ADR-0003, 0004, 0005, 0008, 0009, 0010, 0011, 0012, 0013 proposed** (implementations landed behind
  seams). **E6 is the natural place to revisit the long-blocked items** — if a human approves the relevant
  ADR this session, you may activate: **E2-T4/T5** (real transcription + R2; ADR-0003/0004), **E3-T5**
  (production embedding model; ADR-0008), the **E4-T2 CCXT cross-check** (ADR-0009), and the **E5 Resend /
  Buttondown** adapters (ADR-0010/0013). Absent approval, leave them seamed (the option-(b) pattern) and
  keep the checkboxes honest.
- **Known follow-ups (carry as backlog, not E6 tasks unless a task needs them):** (1) the demo price
  fixtures are only ~18 months, so E4 base rates are thin/extreme (documented in `test_demo_e2e.py` +
  ADR-0009) — a multi-year span would give a fully-measured demo; (2) `apps/web/components/PriceChart.tsx`
  carries 4 pre-existing `eslint-disable @typescript-eslint/no-explicit-any` (E1-T5 lightweight-charts
  typing) — a typed binding or a scoped eslint stanza would close them. Both are in `EX-dept.md` → Backlog.

## Read first (in this order, before any code)

1. `CLAUDE.md` — conventions, commands, and the **binding 5-rule logging contract**.
2. `TASKS.md` — the E6 task definitions and acceptance criteria are authoritative; E1–E5 are ticked;
   E2-T4/T5 and E3-T5 are unticked (BLOCKED-by-design, see `EX-dept.md`).
3. `docs/PRD.md` — **the E6 acceptance criteria are the spec.** At minimum: **AC-5** (100% of disputes
   adjudicated within 7 days — a launch metric) + §7 trust metrics (E6-T1); **NFR-1** (≤48h freshness;
   any analyst stale >48h alerts) (E6-T2); **EC-1 + AC-6** (deletion persistence — detect deleted/privated
   sources, set `source_status`, the receipt already surfaces the flag) (E6-T3); **NFR-5** (hard monthly
   spend caps on transcription/LLM with alerts at 70%) + §18 monitoring (E6-T4); **NFR-6** (GDPR/KVKK
   erasure within 30 days + the legitimate-interest balancing test) (E6-T5).
4. `docs/BRANDKIT.md` — voice for any new user-visible copy (an /about legitimate-interest notice, an
   erasure-request page, alert/report copy that could surface publicly): neutral register, copy-lint enforced.
5. `services/pipeline` — the modules E6 extends: `jobs` (the `run_at`/`SKIP LOCKED` worker loop from
   E2-T6 — E6's SLA/freshness/cost jobs are job kinds), `disputes` (E5-T3 — E6-T1 adds the SLA clock +
   breach alert + weekly report on top), `ingestion` (E2 — E6-T2 freshness + E6-T3 deletion read the
   poller), `qa`, `resolution`, `scoring` (do NOT modify). Migrations are numbered `migrations/*.sql` +
   the tiny runner; the next is `0008_*.sql`.
6. `apps/web` — E6 is pipeline-side, but E6-T3 (deletion) + E6-T5 (GDPR /about notice) may need a small
   read-only surface; if so, reads go through `lib/db.ts` only and copy is copy-lint-clean. E6-T3's
   deletion flag is **already rendered** on the receipt (E5-T1) — E6-T3 supplies the *detection* that sets
   `videos.source_status`.
7. `docs/adr/0001`–`0013` — the ADR ledger and **proposed vs accepted** status; the seam pattern
   (stdlib/`fetch` REST, lazy import, mocked boundary, `RuntimeError`/clear error → ADR) is how every
   external dependency is introduced. New E6 monitoring/alerting deps follow the same gate.
8. `LOG.md` tail — confirm the last line is the E5 epic-close entry before appending.
9. `EX-dept.md` — the blocked-by-design + E5-seam + backlog ledger. Add any new E6 blocked-by-design items
   (a heavy monitoring dep you seam instead of installing).

## The five tasks and their dependency shape (all owner: pipeline-engineer)

- **E6-T1 — Dispute SLA tooling** · deps: E5-T3 · PRD AC-5, §7 trust metrics. Build the **SLA clock**
  (the `disputes.sla_deadline` already exists — compute time-to-breach), **breach alerts** (a job that
  flags disputes past `sla_deadline` still in `state='open'/'adjudicating'`), and a **weekly dispute
  report** (counts, median time-to-adjudication, % within 7 days — AC-5 is "100% within 7 days" as a
  launch metric). Wire as `jobs` kinds (no Celery). Alerting destination (Better Stack / Sentry / email)
  is an external dependency → **seam it** (reuse the `Notifier` seam / a new `Alerter` seam; fixture-backed
  fake is the CI path). Do NOT re-adjudicate disputes here (that is the E5 `record_adjudication` path);
  E6-T1 is the *clock + alert + report*.
- **E6-T2 — Freshness alerts** · deps: E2-T2 · PRD NFR-1. A `freshness_check` job: any registered analyst
  whose latest upload/poll is **stale >48h** raises a freshness alert (the staleness flag exists from
  E2-T2). Alerter seam (Better Stack/Sentry), fixture-backed fake in CI. Idempotent; a `jobs` kind.
- **E6-T3 — Deletion tracking** · deps: E2-T2 · PRD EC-1, AC-6. Detect deleted/privated source videos
  (the YouTube client returns a not-found/private signal), set `videos.source_status` accordingly
  (`flag_source_deleted` from E4-T3 exists), and ensure **claims + resolutions persist** (NFR-3 — never
  erase; the receipt already shows the deletion flag from E5-T1). A `jobs` kind + the `FakeYouTubeClient`
  signal in CI. **This closes the EC-1/AC-6 loop end-to-end** (E4-T3 added the flag helper, E5-T1 renders
  it, E6-T3 supplies the detection that sets it).
- **E6-T4 — Monitoring + cost guardrails** · deps: E2-T4, E3-T2 · PRD NFR-5, §18. **Hard monthly spend
  caps** on transcription + LLM with **alerts at 70%** of cap and a hard stop at 100% (the extraction /
  transcription seams meter spend). Sentry + Axiom wiring is an external dependency → **seam it** (an
  `Observability`/metrics seam + fixture-backed fake; CI asserts the cap logic + the 70% alert
  deterministically, never a live Sentry/Axiom call). The cap enforcement must actually gate the spending
  call sites, not just log (the E4 lesson: a flag with no enforcing call-site is vacuous).
- **E6-T5 — GDPR/KVKK erasure handling** · deps: E2-T1 · PRD NFR-6. An **erasure-request intake** + a
  **30-day policy workflow**, and the **legitimate-interest balancing test** documented and **linked from
  /about**. Reconcile erasure with NFR-3 (the append-only ledger): published statistics about public
  statements are retained under legitimate interest; personal data outside that scope is erasable — encode
  the balancing test, do not silently hard-delete ledger rows. Any erasure that touches a published claim
  is a documented, reviewed exception, not an automatic delete.

**Suggested workflow shape.** E6-T2 and E6-T3 are both ingestion-adjacent and largely file-disjoint
(`freshness_check` vs deletion detection) — they can run as parallel lanes. E6-T1 depends on the E5
disputes module; E6-T4 and E6-T5 are mostly independent. A good order: land the shared **`Alerter`/
`Observability` seam(s)** + any **migration `0008`** through one agent first (the hard-won shared-file
lesson), then fan out E6-T1 / E6-T2 / E6-T3 / E6-T4 / E6-T5 as their own lanes, serializing any two that
edit the same shared file (`jobs.py`, `config.py`, `models.py`, a shared migration). Run the adversarial
panel after each task's scoped checks and before each commit; serialize the full `make check` per the
orchestration rules below.

## The trust-and-ops gate (E6-specific — this epic is the launch-readiness surface)

- **AC-5 is a launch metric (100% of disputes adjudicated within 7 days).** E6-T1's report must compute it
  honestly from the `disputes` ledger; the breach alert must fire before the 7-day line, not after. Demo it
  on fixtures (seed a near-breach dispute via the E5 `create_dispute` path).
- **NFR-1 (≤48h freshness).** E6-T2 must alert on real staleness computed from the poll/upload timestamps,
  not a stub; demonstrate a stale-analyst alert on fixtures.
- **EC-1/AC-6 (deletion persists, never erased).** E6-T3 sets `source_status` and **must not delete** the
  video/claim/resolution rows; the receipt keeps rendering the claim + resolution behind the flag (NFR-3).
- **NFR-5 (hard spend caps + 70% alerts).** The cap must **enforce** at the transcription/LLM call sites
  (block the spend at 100%, alert at 70%), proven by a test that drives spend past each threshold — not a
  logged-but-ignored counter.
- **NFR-6 (GDPR/KVKK).** The legitimate-interest balancing test is a real, documented artifact linked from
  /about; erasure honours the 30-day policy and does not silently violate the append-only ledger.
- **Mock-first for every external service.** Sentry, Axiom, Better Stack, Resend, Buttondown, the YouTube
  deletion probe — all behind a small interface with a fixture-backed fake; CI / `make check` / `npm run
  build` never hit the network, real credentials, or a live API. The fake is the test path.

## The ADR gate (carry it forward)

The stack is **locked**: no new dependency without human approval + an ADR (`docs/adr/`, via the
`new-adr` skill — note subagents lack the Skill tool, so they Write the ADR file directly, modeled on
`docs/adr/0005`). E6 introduces candidate deps — **Sentry / Axiom / Better Stack SDKs (E6-T4/T2/T1)**. For
each: either (a) draft an ADR, present it, and **stop for my approval before adding the dependency**, or
(b) land the real adapter's **seam** — interface honored, real call site structured + unit-tested against
a **mocked** boundary, fixture-backed fake as the CI path — and append a `BLOCKED` LOG line + leave the
checkbox UNTICKED (if the task core genuinely needs the dep) + record it in `EX-dept.md`. **Choose (b) and
keep moving if I am not available to approve.** Calling a REST API via `fetch`/stdlib instead of an SDK is
a legitimate no-new-dependency route (precedent: ADR-0005/0010/0013) — structure it behind the same seam
and note the deviation in an ADR. **E6 may also activate previously-blocked items** (E2-T4/T5, E3-T5,
E4-T2-CCXT, E5 Resend/Buttondown) *if* I approve their ADRs this session; report the outcome either way.

## Orchestration rules (these prevent real races — follow them)

1. **The orchestrator (you, the main loop) owns LOG.md, TASKS.md checkboxes, and git.** Subagents must NOT
   write LOG.md, tick checkboxes, or commit. **Hard-won lesson from E2–E5: the `qa-reviewer` agent
   definition makes verification subagents habitually append audit NOTE/DONE lines to LOG.md even when told
   not to — and in E5 an *implementation* agent also appended a stray NOTE.** Mitigate explicitly: in every
   subagent prompt (implementation AND verification), instruct the agent to **RETURN findings as its final
   message only and write NOTHING to LOG.md/TASKS.md**; the orchestrator transcribes any NOTE/AUDIT line
   itself (with a correct `date -u` UTC timestamp). **After every subagent batch, check the working tree for
   pollution** — `git --no-pager diff HEAD -- LOG.md TASKS.md` AND scan for stray agent NOTE lines (not just
   `qa-reviewer`/`DONE`/`[x]`) — and clean it pre-commit (remove the uncommitted polluting line, or
   `git checkout HEAD -- LOG.md` then re-append your own legitimate lines) and record the cleanup in an
   orchestrator NOTE. You append the STARTED line (attributed to the executing agent) before launching each
   task, and the DONE/BLOCKED line only after you have verified the gate. LOG.md is append-only — new lines
   at the bottom. Format: `<UTC timestamp> | <agent> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <note>`.
2. **Parallel agents run only scoped checks.** For pipeline tasks: their own pytest file, `ruff check
   --no-cache`, `ruff format --check`, `mypy --config-file services/pipeline/pyproject.toml` with a private
   `--cache-dir`. For any small `apps/web` surface: `cd apps/web && npx tsc --noEmit`, `npm run lint`,
   `npm run build`; plus `python3 scripts/copy_lint.py` for new user-visible copy. The full `make check`
   runs **serially, by you, at each integration point**. Never run `make check` / `make install` /
   `npm install` / pip inside an agent. Never run two agents editing the same file concurrently (`jobs.py`,
   `config.py`, `models.py`, a shared migration) — serialize them. Bring the DB up before any DB-backed
   test (`sg docker -c 'make -C $REPO seed'`).
3. **One conventional commit per completed task**, made by you after its gate is green, e.g.
   `feat(pipeline): dispute SLA clock + breach alert + weekly report (E6-T1)`. Commits end with
   `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` (the harness sets the actual
   model trailer; use the running model). Commit the ledger (LOG.md + TASKS.md + EX-dept.md) at the epic
   close (a `chore:` commit), as E2–E5 did.
4. **DoD triple per task:** `make check` green + TASKS.md checkbox ticked + LOG.md DONE line stating the
   verification evidence (test count + scoped-check results) and modules touched. For an ADR-gated BLOCKED
   task: seam committed + `BLOCKED` line + ADR drafted (proposed) + checkbox left UNTICKED + EX-dept.md entry.
5. If a task is blocked (ADR-gated dependency) or an agent fails after a retry, append a `BLOCKED`/recovery
   line and continue with whatever is unblocked; report it at the end.

## Binding constraints (violations are session failures)

- **Regulatory firewall (AC-7):** the product never outputs buy/sell/hold or any recommendation language.
  `scripts/copy_lint.py` scans `apps/web/**/*.ts(x)`, `data/fixtures/*.json(l)`, and `docs/METHODOLOGY.md`;
  fix the wording, never the linter. New E6 user-visible copy (alert/report text that could surface, the
  /about legitimate-interest notice, the erasure-request page) is neutral register per `docs/BRANDKIT.md`.
- **Append-only ledger (NFR-3):** `resolutions` and `scores` are never UPDATEd/DELETEd (DB triggers
  enforce). E6-T3 deletion sets a flag, never erases; E6-T5 erasure must not silently delete ledger rows —
  encode the legitimate-interest balancing test and treat any published-claim erasure as a reviewed
  exception. The `disputes` table is mutable working state (SLA/state UPDATEs are fine).
- **Mock-first integrations:** every external dependency (Sentry, Axiom, Better Stack, Resend, Buttondown,
  the YouTube deletion probe, any spend meter) sits behind a small interface with a fixture-backed fake; CI
  / `make check` / `npm run build` never touch the network, real credentials, or a live API.
- **Boring stack, locked:** no new dependency without my approval + an ADR. A helper used once gets inlined.
- **AC-1 golden-set gate stays green** (precision ≥95% AND recall ≥80%, non-vacuous).
- **No scoring/methodology changes in E6.** Do not edit `scoring/`, `resolution/`,
  `config.METHODOLOGY_VERSION`, or `docs/METHODOLOGY.md`. The binding worked examples and the v1.1 ledger
  numbers must not move.
- **Reproducibility (NFR-2):** disputes record the methodology_version in force at adjudication (EC-12 +
  `get_pinned_methodology_version` exist); SLA reports and erasure decisions stamp their inputs.
- **Scope lock:** crypto + YouTube only; no auth, no payments; quotes ≤15 words (NFR-4). E6 is trust/ops —
  do not regress the E5 web surface or change scoring.
- **Never silence a gate** (no `# type: ignore`, `# noqa`, `eslint-disable`, `@ts-ignore`,
  `ts-expect-error`, test deletion, or trivially-true assertions). For an optional/ADR-gated package
  mypy/tsc can't resolve, add a scoped config stanza (`[[tool.mypy.overrides]]` / a typed module
  declaration), not an inline suppression. **The E4/E5 panels caught smuggled suppressions on multiple
  tasks — assume your agents will try the same and catch it in the panel.**

## Environment notes (carried from E1–E5)

- `make check` = copy-lint → ruff (lint+format over `services/pipeline scripts`) → mypy strict
  (`--config-file services/pipeline/pyproject.toml`) → pytest → tsc → eslint. The full gate needs the DB
  container up (pytest connects over TCP); only `seed`/`pipeline-demo`/`dev` call docker (wrap in
  `sg docker -c` if your session lacks the docker group).
- DB-backed tests use the rolled-back `db_conn` fixture (`tests/conftest.py`); the committing demo path
  uses `db_conn_live`. Prefer a synthetic in-test fixture over coupling to committed demo state. The new
  E6 migration (`0008_*.sql`) follows the numbered `migrations/*.sql` + tiny runner pattern.
- Recorded-fixture pattern for any new external seam (Sentry/Axiom/Better Stack/YouTube deletion): check
  canned request/response fixtures into `data/fixtures/` (copy-lint clean, fictional) and have the adapter
  accept an injected callable defaulting to the real one; tests inject the recorded boundary. No network in CI.
- **The adversarial verification panel earns its keep.** Run a multi-lens panel (correctness, spec-fidelity
  vs the PRD AC, AC-7 firewall on new copy, NFR-3/append-only + enforcement-not-just-a-flag, mock-first +
  ADR gate, gate-silencing) after each task's `make check` and before each commit; fix what it finds.

## Closing report (required — covers the whole epic)

End the session with: (1) per-task status table E6-T1..E6-T5 (DONE/BLOCKED + evidence line incl. the
demonstrated AC-5 dispute-SLA report, NFR-1 freshness alert, EC-1/AC-6 deletion persistence, NFR-5 cap +
70% alert, NFR-6 balancing test); (2) final `make check` + `npm run build` summary; (3) a short
demonstration that the SLA clock/report, freshness alert, deletion detection, cost cap+alert, and erasure
workflow work on fixtures (documented dogfood + the DB-backed tests); (4) any ADR drafts (Sentry/Axiom/
Better Stack) + their proposed-vs-blocked status, and which previously-blocked ADRs (0003/0004/0008/0009/
0010/0013) were approved+activated this session, if any; (5) any new migration (`0008_*`) + its schema;
(6) LOG.md tail; (7) `git log --oneline <E6-base>..HEAD`; (8) the qa-reviewer audit findings; (9)
`EX-dept.md` state (incl. any new E6 blocked-by-design items + the carried E2-T4/T5, E3-T5, E4-T2-CCXT,
E5 Resend/Buttondown/cache items + the backlog notes); (10) next steps — if E6 is the final MVP epic, a
**launch-readiness assessment** against the PRD §14 acceptance criteria (AC-1…AC-7) and §3 goals; else the
next epic's tasks with suggested owners.

## Final phase — write the next session prompt (do not skip)

After the qa-reviewer audit and the closing report, the **last phase of the workflow must spawn one agent
(or do it yourself as the orchestrator) that writes the next session prompt into the repo root**, modeled
exactly on the structure of this file and `PROMPT-E5.md`. If another epic follows E6, write `PROMPT-E7.md`
for it. **If E6 is the final MVP epic** (E1–E6 complete), instead write `PROMPT-LAUNCH.md` — a
launch-readiness / project-closeout prompt that: maps every PRD §14 acceptance criterion (AC-1…AC-7) and
§3 goal (G1…G5) to its delivering task + evidence; lists the ADRs still **proposed** that must be
human-approved before production (every external dep: transcription, R2, embeddings, CCXT, Resend,
Buttondown, monitoring) with the exact activation step for each; enumerates the carried `EX-dept.md` items;
and gives a go/no-go checklist for the first production deploy. That generated prompt must **itself end
with this same "Final phase" instruction**, so the chain continues (or, for `PROMPT-LAUNCH.md`, with the
deploy/runbook handoff). This is what makes the chain self-perpetuating: every prompt closes by generating
the next.

Append a LOG.md NOTE line recording that the next prompt was written, and mention it in the closing report.
**Commit the next prompt** in a small `chore:` commit — as of the VPS migration the session prompts are
committed (like this file) so they travel with `git clone`.


## ═══════════════════════ PROMPT-LAUNCH.md ═══════════════════════

# Session prompt — Launch readiness & production cutover (MVP epics E1–E6 complete)

Copy everything below the line into a fresh Claude Code session started at the repo root on the
**Ubuntu 24.04 VPS**. Like `PROMPT-E5.md`/`PROMPT-E6.md`, **this file is committed to the repo on purpose**
so it travels with `git clone` and is the first thing you read. The six MVP build epics are done; this
prompt is the **project closeout + go/no-go for the first production deploy**, not another build epic.

---

## Environment — Ubuntu 24.04 VPS (READ FIRST)

Same as PROMPT-E6.md. The toolchain is already installed if you are on the E5/E6 VPS — verify, then bring
the DB up:

- **Repo root (`$REPO`).** `cd` into your clone (e.g. `~/brier-claude` or `/srv/brier-claude`); run every
  command from there.
- **Docker = Engine + systemd (no Desktop).** Daemon auto-starts; if down, `sudo systemctl start docker`.
  **Hard-won gotcha:** the dev user is in the `docker` group in `/etc/group` but the *login session predates
  it*, so `docker` is permission-denied. Wrap docker/compose/`make seed`/`make pipeline-demo` in
  `sg docker -c '...'` (e.g. `sg docker -c 'make -C $REPO seed'`). `make check` itself needs no docker once
  the DB container is up (pytest connects to `localhost:5432` over TCP). A fresh SSH login picks up the group.
- **Node ≥20 + the pipeline venv** are installed (Node via nvm symlinked into `~/.local/bin`; venv at
  `services/pipeline/.venv`).
- **First-run acceptance test — both must pass before any cutover work:** `make check` green
  (**760 pytest + 1 benign skip**; copy-lint + ruff + ruff-format + mypy strict (45 files) + tsc + eslint
  clean — bring the DB up first: `sg docker -c 'make -C $REPO seed'`) AND `make pipeline-demo` prints the
  v1.1 ranked board (**NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7**, 20 cumulative resolutions). If
  either fails, fix the *environment* (not the code) until both are green.
- **What travels vs what you re-set.** `.claude/`, `docker-compose.yml`, `Makefile`, `migrations/`, and the
  `PROMPT-*.md` files arrive with the clone. Re-set on a fresh box: git identity, and (only for *live* runs,
  never CI/tests) any API keys/tokens listed in "ADRs to approve" below.

---

You are the lead engineer on **Brier** (prediction track-record engine for crypto YouTube analysts). **All
six MVP build epics are complete and committed: E1 (Walking Skeleton), E2 (Ingestion), E3 (Extraction+QA),
E4 (Resolution+Scoring), E5 (Web completion), E6 (Trust+Ops).** `make check` is green (760 + 1 skip);
`npm run build` is clean and offline-safe; the qa-reviewer audited E6 as PASS. There is **no E7 build
epic** — every TASKS.md item is either ticked or recorded blocked-by-design in `EX-dept.md`.

Your mission this session is **launch readiness**, not new features: take the system from
"all code green on fixtures" to "go/no-go for the first production deploy." Concretely:
1. Re-verify the full gate + the fixture demo (the acceptance test above).
2. Walk the **ADR approval gate** (below): for each *proposed* ADR, either get human approval and **activate
   the real adapter** (install the gated dep / set the key, wire it, flip the checkbox + ADR status to
   accepted + EX-dept → Resolved), or leave it seamed and explain the blocker. **Do not add any dependency
   or call any live external API without explicit human approval.**
3. Execute (or write the runbook for) the **production data backfill** — the 50-analyst roster ingest and
   the 24-month backfill that turns the 3-fixture demo into the ≥10,000-resolved-claim launch dataset (G3).
   This is gated on the transcription/embedding ADRs; if they are not approved, produce the runbook and stop.
4. Produce the **go/no-go checklist** and, if go, the deploy runbook.

## Read first (in this order)

1. `CLAUDE.md` — conventions + the binding 5-rule logging contract.
2. `TASKS.md` — E1–E6 ticked; E2-T4/E2-T5/E3-T5 unticked (BLOCKED-by-design; see EX-dept.md).
3. `docs/PRD.md` — §14 acceptance criteria (AC-1..AC-7) and §3 goals (G1..G5) are the launch gate.
4. `EX-dept.md` — the blocked-by-design + seam-activation ledger. **This is your activation worklist.**
5. `docs/adr/0001`–`0014` — the ADR ledger and proposed-vs-accepted status.
6. `LOG.md` tail — last line is the E6 epic-close entry.

## PRD §14 acceptance criteria → delivering task + evidence (verify each still holds)

- **AC-1** golden-set precision ≥95% & recall ≥80% → **E3-T6** (`tests/test_golden_set.py`, a required CI
  gate). Evidence: the golden gate is green inside `make check`. *Launch caveat:* run it against the real
  extraction model output once ADR-0005's key is live, not only the fixture replay.
- **AC-2** receipt embed starts <3s + chart t0→resolution → **E1-T5 + E5-T1** (`ReceiptPlayer` facade,
  lightweight-charts). Evidence: `/r/[claimId]` builds + renders.
- **AC-3** leaderboard FAS/n/falsifiability/trend match the ledger exactly → **E1-T5 + E5-T5**. Evidence:
  leaderboard p95≈38ms, ledger-exact (`getLeaderboardCached`).
- **AC-4** methodology bump → prior scores queryable in the archived ledger → **E4-T5** (`recompute_all`,
  append-only). Evidence: `tests/test_recompute.py`.
- **AC-5** dispute adjudicated within 7 days + public log if corrective → **E5-T3 (flow) + E6-T1 (SLA
  clock/breach+at-risk alerts/weekly report)**. Evidence: `tests/test_disputes.py`, `tests/test_sla.py`.
- **AC-6** deleted source → claim, deletion flag, resolution remain visible → **E5-T1 (overlay) + E6-T3
  (detection sets `source_status`)**. Evidence: `tests/test_deletion.py` (claims+resolutions persist, NFR-3).
- **AC-7** zero buy/sell/hold recommendation language → **`scripts/copy_lint.py`** across all copy (now also
  scans `docs/LEGITIMATE_INTEREST.md`). Evidence: copy-lint clean in `make check` + manual review.

## PRD §3 goals → status

- **G1** 50 named analysts, receipt-backed → registry + 50-roster import (**E2-T1**) + the web surface ship;
  **launch action:** run the real roster ingest (currently 3 fixture analysts).
- **G2** precision ≥95% / recall ≥80% → **E3-T6** (AC-1). Re-run on real model output post-ADR-0005.
- **G3** ≥10,000 resolved claims from the 24-month backfill → **E2-T3 backfill + E1-T3/E4 resolution**;
  **launch action (gated):** the real backfill needs transcription (ADR-0003/0004) + embeddings (ADR-0008).
  Demo today = 20 resolutions on fixtures.
- **G4** launch moment (25k visitors, 1k subscribers in 30d) → **E5-T5 SEO + E5-T6 newsletter/waitlist**;
  post-launch growth metric (activate Buttondown, ADR-0013).
- **G5** withstand disputes, zero retractions from extraction error → **E3 QA + E5-T3 disputes + E6-T1 SLA +
  corrections log**. Trust metric; the SLA report (E6-T1) is the launch instrument.

## ADRs to approve before production (each is a go/no-go gate)

Accepted: **0001, 0002, 0006, 0007**. The rest are **proposed** — the implementation is landed behind a
seam; activation needs your approval. For each: approve → do the activation step → set ADR status to
accepted, tick any task, move the EX-dept entry to Resolved.

- **ADR-0003 faster-whisper transcription** (E2-T4): heavy GPU dep. *Activate:* approve → add the pinned
  `faster-whisper` optional extra to `pyproject.toml`, install only on the rented-GPU backfill host. Gates G3.
- **ADR-0004 boto3 / Cloudflare R2 storage** (E2-T5): *Activate:* approve → add pinned `boto3` optional
  extra; set R2 creds; `ensure_audio_ttl_lifecycle`. Gates the audio/transcript storage path.
- **ADR-0005 LLM via stdlib REST** (extraction): **no dependency** — *Activate:* set `BRIER_ANTHROPIC_API_KEY`
  on the worker host; accept the ADR. Gates real extraction (and a true AC-1/G2 run).
- **ADR-0008 sentence-transformers embeddings** (E3-T5): heavy dep. *Activate:* approve → add pinned
  `sentence-transformers` optional extra where dedup runs. Gates semantic dedup (FR-205) on real data.
- **ADR-0009 base rates / CCXT cross-check**: the base-rate engine (v1.1) is **accepted-in-effect and
  shipped**; the **CCXT** cross-check sub-item is the only blocked piece (heavy dep). *Activate (optional):*
  approve a CCXT ADR → add the dep for EC-8 outage detection.
- **ADR-0010 Resend transactional email** (E5-T3): **no dependency** — *Activate:* set
  `BRIER_RESEND_API_KEY`; `getNotifier()` returns `ResendNotifier`. Sends the dispute ticket email.
- **ADR-0011 OG via next/og** & **ADR-0012 leaderboard cache via Next built-in**: **no dependency, nothing
  to activate** — accept for the record. (Upstash/matview is a deferred prod-scale option, not required.)
- **ADR-0013 Buttondown newsletter** (E5-T6): **no dependency** — *Activate:* set
  `BRIER_BUTTONDOWN_API_KEY`; `getSubscriber()` returns `ButtondownSubscriber`. Gates G4 capture.
- **ADR-0014 monitoring/alerting** (E6): **no dependency** — *Activate:* set `BRIER_BETTER_STACK_TOKEN`
  and/or `BRIER_SENTRY_DSN`; `get_alerter()` returns the real adapter. **Axiom** is deferred-by-design
  (the `alerts` table + Better Stack + Sentry cover §18). Gates NFR-1/NFR-5 real alerting.

## Carried EX-dept.md items (the activation worklist)

The seam is built and CI-exercised for each; only the real external service is pending: E2-T4 transcription
(ADR-0003), E2-T5 R2 (ADR-0004), E3-T5 embeddings (ADR-0008), E4-T2 CCXT cross-check (ADR-0009), E5-T3
Resend (ADR-0010), E5-T6 Buttondown (ADR-0013), E5-T5 Upstash/matview (ADR-0012, optional), E6 monitoring
sinks + Axiom (ADR-0014). Backlog (quality, not blocked): the 4 PriceChart `eslint-disable
@typescript-eslint/no-explicit-any` (E1-T5 lightweight-charts typing); the ~18-month demo price fixtures
(extend to multi-year for fully-measured base rates).

## Go / no-go checklist for the first production deploy

1. `make check` green + `make pipeline-demo` board unchanged on the deploy box (the acceptance test).
2. **ADRs accepted** for every external dep you intend to run in prod (above), each with its key/token set
   and **no key committed to the repo** (env only; CI stays mock-first).
3. **Real data:** the 50-analyst roster ingested (G1) and the 24-month backfill run to **≥10,000 resolved
   claims** (G3); the golden-set gate (AC-1) re-run **against real model output** at ≥95%/≥80% (G2).
4. **NFR-3 spot check:** corrections/disputes append superseding rows; no UPDATE/DELETE on
   resolutions/scores (DB triggers enforce).
5. **Trust ops live:** dispute SLA job + freshness job + deletion sweep + cost-cap guardrails scheduled as
   `jobs` kinds; the `alerts` sink wired (ADR-0014); the spend caps set to the real monthly budget.
6. **AC-7** copy-lint clean on the final build; **NFR-6** /about legitimate-interest notice published; the
   30-day erasure workflow has an owner.
7. **Monitoring + rollback:** Better Stack/Sentry receiving events; a tested rollback (the append-only
   ledger means recompute, never destructive edits).

## Binding constraints (unchanged — violations are session failures)

- **AC-7** regulatory firewall (`scripts/copy_lint.py`); **NFR-3** append-only ledger (triggers); **mock-first**
  for every external service; **boring stack locked** (no dep without approval + an ADR); **scope lock**
  (crypto + YouTube only; no auth/payments; quotes ≤15 words). **No scoring/methodology change** — v1.1 and
  the binding worked examples (`tests/test_fas.py`: FAS_A≈47.02, FAS_B≈66.74, B-outranks-A, k=25, min n=20)
  must not move. Activating a real adapter must not regress `make check` (the fake stays the CI path).

## Orchestration (if you use workflows)

The orchestrator (main loop) owns LOG.md, TASKS.md, EX-dept.md, and git; subagents RETURN findings only and
write nothing to the ledger (the hard-won E2–E6 lesson — verify the working tree for LOG/TASKS pollution and
a stray `services/pipeline/LOG.md` after every subagent batch, and clean it pre-commit). Run an adversarial
verification panel before any activation commit. One conventional commit per logical change; commit the
ledger at the close.

## Final phase — keep the chain going (do not skip)

After the go/no-go assessment, the last phase must **write the next session prompt into the repo root** and
commit it in a small `chore:`:
- If production is **NO-GO** (ADRs unapproved / backfill not run), write `PROMPT-LAUNCH.md`'s successor
  (e.g. `PROMPT-CUTOVER.md`) capturing exactly which gates remain, the precise activation steps, and the
  runbook — and have it **end with this same Final-phase instruction**.
- If production is **GO**, write `PROMPT-RUNBOOK.md`: the deploy steps, the scheduled-jobs cron, the
  monitoring dashboards, the dispute/erasure on-call playbook, and the first-week launch-metric watch
  (G4) — and have it end with an operations-handoff instruction.
Append a LOG.md NOTE recording which prompt was written, mention it in the closing report, and commit it.
This is what makes the chain self-perpetuating: every prompt closes by generating the next.


## ═══════════════════════ PROMPT-CUTOVER.md ═══════════════════════

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

## Roles & handoff — who does what (read this first)

This is a **gated** session: the agent does the engineering, but several gates are the **human owner's call**,
and the agent must STOP and ask at each one. Nothing proceeds past a gate without the human.

**You, the human owner, must provide (the agent cannot self-serve these):**
- **ADR approvals** for the heavy dependencies you want in production — `0003` faster-whisper, `0004`
  boto3/R2, `0008` sentence-transformers, and (optional) a CCXT ADR for `0009`'s EC-8 cross-check. No
  dependency is added to `pyproject.toml` without your explicit approval.
- **Production credentials** — you set them as env vars on the hosts (never pasted into the repo or a commit):
  `BRIER_ANTHROPIC_API_KEY`, `BRIER_RESEND_API_KEY`, `BRIER_BUTTONDOWN_API_KEY`,
  `BRIER_BETTER_STACK_TOKEN`/`BRIER_SENTRY_DSN`.
- **Infrastructure** — the rented GPU host (whisper backfill), the Cloudflare R2 bucket + creds, the real
  monthly spend budget, the **named erasure-request owner** (NFR-6), and which channels make up the
  50-analyst roster.
- **The final GO call.**

**The agent (next session) does — and stops to ask at each gated step above:**
- Run the acceptance test (`make ci`); once you approve a dep/key, perform that seam activation and re-verify
  the gate stays green (the fake stays the CI path).
- Build + ingest the roster (G1), run the 24-month backfill to ≥10k resolutions (G3), re-run the golden gate
  on **real** model output (AC-1/G2), schedule the trust-ops jobs, wire monitoring, and fix the four tracked
  launch-quality defects (below).
- Update the ledgers (LOG/TASKS/EX-dept/ADR statuses), commit per logical change, push, and **write the
  successor prompt** (see "Final phase").

**Hard rule (unchanged):** the agent never adds a dependency or calls a live external API without your
explicit approval, and never commits a key. If a gate is unmet, the session stays NO-GO and says so plainly.

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


## ═══════════════════════ PROMPT-MASTER.md ═══════════════════════

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

## 2. Where the project stands (as of 2026-06-18)

- **All six MVP build epics are complete and committed** (E1 Walking Skeleton → E6 Trust+Ops). Every
  `TASKS.md` item is ticked or recorded blocked-by-design in `EX-dept.md`.
- **Launch-readiness review is done. Verdict: NO-GO** for the first production deploy — gated on operational
  steps, not code defects. Full evidence in `docs/LAUNCH-READINESS.md`.
- **Cutover round 1 (2026-06-18) closed every ungated launch-quality code defect** — AC-3 trend (`630afb8`),
  worker bootstrap + scheduled-ops handlers (`8dc908e`), AC-5/UF-3 analyst notification (`4fe62b6`); all
  mock-first, no new deps/keys, adversarially verified (4-agent refute panel, zero blockers). The
  `transcribe`/`extract` handler registration and the AC-1/G2 golden re-run remain part of the **human-gated
  activation**. Verdict still **NO-GO** on the hard gates.
- **CI/CD is hardened and green on a clean checkout:** `.github/workflows/ci.yml` runs a pgvector Postgres
  service so the full DB-backed suite + the end-to-end `pipeline-demo` smoke + the Next `web-build` gate
  every push. Local equivalent: `sg docker -c 'make ci'`.
- **Acceptance test (must hold):** `make check` green (**775 passed + 1 benign skip**); `make pipeline-demo`
  prints the canonical board **NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7** (20 cumulative resolutions);
  `make web-build` clean.

## 3. The prompt chain — which one is ACTIVE

Each session closes by writing the next session's prompt (self-perpetuating). The chain so far:

`PROMPT-E5.md` → `PROMPT-E6.md` → `PROMPT-LAUNCH.md` → `PROMPT-CUTOVER.md` → **`PROMPT-CUTOVER-2.md` ← ACTIVE: open this next.**

**Start here now:** read `PROMPT-CUTOVER-2.md`. `PROMPT-CUTOVER.md`'s round 1 (2026-06-18) closed every
ungated launch-quality *code* defect; `PROMPT-CUTOVER-2.md` is the **human-gated activation** worklist (heavy-dep
ADRs, prod keys, real roster + backfill, golden re-run, final GO) and opens with an explicit **"Roles &
handoff"** section. Its companion is `docs/RUNBOOK-PRODUCTION.md` (the step-by-step activation + backfill +
deploy runbook).

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
Then open **`PROMPT-CUTOVER-2.md`** and work it top to bottom, stopping to ask the human at each gated step.

## 7. Orchestration note (hard-won)

The orchestrator (main loop) owns `LOG.md`, `TASKS.md`, `EX-dept.md`, ADR statuses, and git. Subagents
RETURN findings only and must write nothing to the ledger — **even read-only agents with Bash can write
files**, so after every subagent batch verify the working tree (`git status`) for `LOG.md`/`TASKS.md`
pollution and a stray `services/pipeline/LOG.md`, and clean it before committing. A real example: a
launch-readiness audit agent left a (correct) test fix in the working tree; it was caught by the tree check,
independently verified, and committed. Always verify, never blindly trust or discard.
