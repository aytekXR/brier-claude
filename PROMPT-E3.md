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
