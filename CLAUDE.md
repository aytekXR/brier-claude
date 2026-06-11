# Brier

Prediction track-record engine: scores crypto YouTube analysts on the accuracy of their public predictions, with clip-level receipts. PRD: `docs/PRD.md`. Scoring spec: `docs/METHODOLOGY.md`. Brand: `docs/BRANDKIT.md`. Backlog: `TASKS.md`. Worklog: `LOG.md`.

## Project map

- `apps/web` — Next.js App Router, TS strict, Tailwind. Server components by default; reads via `lib/db.ts` only.
- `services/pipeline` — Python 3.12, Pydantic, psycopg + plain SQL. Modules: ingestion, transcription, extraction, resolution, scoring, qa, jobs. Migrations: numbered `migrations/*.sql` + tiny runner.
- `data/fixtures` — fixture data; `scripts/` — copy_lint.py (AC-7 firewall), seed.py.
- `.claude/agents` — scoped subagents; `.claude/skills` — next-task, run-checks, new-adr.

## Commands

- `make dev` — db + Next dev server · `make seed` — migrate + seed 3 fixture analysts
- `make test` — pytest · `make check` — copy-lint + ruff + mypy + pytest + tsc + eslint (the gate)
- `make pipeline-demo` — arrives with task E1-T1

## Conventions

- **Regulatory firewall (AC-7):** the product never outputs buy/sell/hold or any recommendation language. `scripts/copy_lint.py` enforces it on all user-visible copy; it runs in `make check` and CI.
- **Append-only ledger (NFR-3):** `resolutions` and `scores` rows are never updated or deleted; corrections append a superseding row. DB triggers enforce it.
- **Scope lock:** crypto assets and YouTube only. No equities, no X, no podcasts, no auth, no payments.
- **Mock-first integrations:** every external dependency sits behind a small interface with a fixture-backed fake. New code follows the same pattern.
- **Boring stack, locked:** no new dependencies, no formula changes, no stack deviations without human approval + an ADR in `docs/adr/`. A helper used once gets inlined.
- Small commits, conventional messages. Stubs carry `# TASK: <id>` markers referencing TASKS.md.
- **Definition of done for any task = `make check` green + TASKS.md checkbox + LOG.md DONE line.**

## Logging contract (binding for every session and every subagent)

1. Append a STARTED line before touching code for a task. Append DONE only after `make check` is green. Append BLOCKED with the reason when stopping early. Use HANDOFF when passing work to another agent, naming the receiving agent.
2. Every DONE line must state the verification (e.g. "make check green, 14 tests") and the main modules touched.
3. A task counts as complete only when its TASKS.md checkbox AND its LOG.md DONE line both exist and agree. One without the other is a defect.
4. LOG.md is append-only. No edits, no deletions, no reordering. Corrections are new NOTE lines referencing the earlier line.
5. qa-reviewer additionally audits LOG.md against TASKS.md and `git log` every session and files a NOTE line for any mismatch or missing entry.

LOG.md line format: `<UTC timestamp> | <agent or human> | <task-id> | STARTED|DONE|BLOCKED|HANDOFF|NOTE | <short note>`
