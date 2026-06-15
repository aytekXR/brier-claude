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
