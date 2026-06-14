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
