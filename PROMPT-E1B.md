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
