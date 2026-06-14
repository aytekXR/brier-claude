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
