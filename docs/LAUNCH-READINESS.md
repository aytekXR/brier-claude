# Brier — Launch-Readiness Assessment & Go/No-Go (2026-06-16)

## Verdict: **NO-GO** for the first production deploy

The fixture/mock path is **green end-to-end** (`make check` 766 passed + 1 benign
skip; demo board NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7; web build clean —
now all gated in CI on every push). Production go-live is gated on **operational**
steps that have not run, plus **two tracked launch-quality defects**. None of the
blockers is a structural failure of the shipped code; the NO-GO is narrow and
well-understood.

**Why NO-GO (the hard gates):** no production credentials are set, the
heavy-dependency adapters (transcription/storage/embeddings) are not installed,
the real 50-analyst roster is not ingested, the 24-month backfill (≥10,000
resolved claims) has not run, and the golden-set gate has not been re-run against
real model output.

## How this was assessed

An 18-agent adversarial workflow: **11 read-only auditors** (one per PRD AC, plus
the ADR gate, EX-dept ledger, NFR-3 triggers, and the test/CI coverage gap) and
**7 adversarial refute agents** that tried to break each "holds" verdict. The
findings below are **post-refutation** — the refute pass caught two real issues
the optimistic audit had marked green (AC-3 trend, backfill-handler wiring).

## PRD §14 acceptance criteria

| AC | Fixture/mock path | Remaining for production GO |
| --- | --- | --- |
| **AC-1** golden precision ≥95% / recall ≥80% | ✅ green & **non-vacuous** in `make check` (fixture: precision 0.9604, recall 0.8435; both threshold branches proven to fail on degraded data) | ⛔ **GO gate:** the gate runs against a **static `predicted` snapshot**, not the live extractor — a prompt/model regression would NOT fail the build. Re-run `test_golden_set.py` against real `LlmExtractor` output (ADR-0005 key) at ≥95%/≥80%. |
| **AC-2** receipt embed <3s + chart t0→resolution | ✅ structurally sound: facade defers the IFrame to the click with the seek offset baked into the URL; chart spans t0→resolution with 3 markers | ⚠️ "<3s" is not unit-testable (no JS test runner); needs real YouTube IDs + a populated `price_daily` from the backfill to verify end-to-end |
| **AC-3** leaderboard FAS/n/falsifiability/**trend** match the ledger exactly | ⚠️ **PARTIAL.** FAS / n / falsifiability are **ledger-exact** (`getLeaderboard` does zero arithmetic, only casts + renames). **The trend sub-column is non-functional** | ⛔ **Tracked defect:** `TrendSparkline` always receives `[]`/`null` (`apps/web/app/page.tsx:174,229`); real per-analyst trend points are never fetched/passed, so the trend renders "—" even in production with history. Wire trend points into `getLeaderboard` + the row. |
| **AC-4** methodology bump → prior scores queryable | ✅ `recompute_all` writes a new `score_run`; prior runs stay queryable (append-only) | none — ready |
| **AC-5** dispute adjudicated ≤7d + public corrective log | ✅ core present & tested: SLA clock, breach + **at-risk-before-7d** alerts, weekly report with honest `pct_within_sla` | ⚠️ **UF-3 gap:** the disputer is emailed the ticket id, but the **analyst is not notified** on adjudication. Confirm against PRD scope; wire if required. |
| **AC-6** deleted source → claim + flag + resolution persist | ✅ sweep sets `source_status`; **claims AND resolutions persist** (tested, NFR-3) | ⚠️ **Wiring:** the `deletion_sweep` handler self-registers on import, but the production worker bootstrap must import the module (runbook §3/§5) or the job never runs. |
| **AC-7** zero buy/sell/hold language | ✅ `copy_lint.py` clean; scans web copy + `METHODOLOGY.md` + `LEGITIMATE_INTEREST.md`; runs in `make check` + CI | none — keep clean on the final build |
| **NFR-3** append-only ledger | ✅ DB triggers forbid UPDATE **and** DELETE on `resolutions` + `scores`; refute could not break it; a scores-DELETE behavioral test was added this session | none — enforced at the DB layer |

## PRD §3 goals

- **G1** 50 named analysts — `import-roster` CLI ready; **3 fixture analysts today**. GO action: ingest the real 50-roster.
- **G2** precision ≥95% / recall ≥80% — see AC-1: re-run on real model output.
- **G3** ≥10,000 resolved claims — **gated** on ADR-0003/0004/0008 + the LLM key; **20 resolutions on fixtures today**.
- **G4** launch moment (25k/1k in 30d) — SEO + newsletter/waitlist seam shipped; activate Buttondown (key) for capture.
- **G5** withstand disputes, zero retraction-from-error — SLA + corrections + erasure live; the **weekly dispute report is the launch instrument**.

## ADR gate (post-ratification)

- **Accepted:** 0001, 0002, **0005**, 0006, 0007, **0009 (base-rate engine)**, **0010**, **0011**, **0012**, **0013**, **0014**. The no-dep adapters (0005/0010/0013/0014) need only a production env key; 0011/0012 need nothing.
- **Still proposed (heavy dependency — approve at cutover):** **0003** faster-whisper, **0004** boto3/R2, **0008** sentence-transformers, and the **0009 CCXT cross-check** sub-item.
- No key is committed to the repo; CI/dev stays mock-first (the fakes are the CI path, locked by `test_seams.py`).

## Go/No-Go checklist (PROMPT-LAUNCH §) — current status

1. `make check` + `pipeline-demo` board + web build on the deploy box — ✅ **green** (and now gated in CI on every push via a Postgres service container).
2. ADRs accepted + each prod key/token set, **no key committed** — ⛔ **keys not set** → NO-GO.
3. Real data: 50-roster ingested + 24-month backfill ≥10k resolved + golden re-run on real output — ⛔ **not run** → NO-GO.
4. NFR-3 spot check (corrections append; no UPDATE/DELETE) — ✅.
5. Trust-ops jobs scheduled + `alerts` sink wired + spend caps at real budget — ⛔ **jobs not scheduled in prod**; worker must import handler modules (runbook §3/§5).
6. AC-7 copy-lint clean + NFR-6 `/about` notice + named erasure owner — ✅ copy-lint + notice; ⛔ **erasure owner to be named**.
7. Monitoring receiving events + tested rollback — ⛔ **tokens not set**; rollback = `recompute_all` (append-only, ready).

## Launch-quality findings to carry into the cutover (tracked worklist)

1. **AC-3 trend wiring** — `TrendSparkline` never receives real points (`page.tsx:174,229`); wire per-analyst trend history into `getLeaderboard`.
2. **Backfill job handlers** — `transcribe` / `extract` / `resolve_claims` / `score_analysts` are **not registered** as job kinds (demo calls them directly); register them for the backfill (gated on ADR-0003/0004/0008).
3. **Worker bootstrap** — the long-running worker must import every handler module before `run_forever` (it auto-discovers nothing).
4. **AC-5 UF-3** — analyst-notification-on-adjudication is absent.
5. **AC-1/G2** — golden-set must be re-run on real model output before GO.

## What is solid (so the NO-GO is narrow, not a failure)

The whole fixture/mock path is verified end-to-end and now **gated in CI on every
push** (23 previously-skipping DB-backed test files now run; demo + web build
added). Scoring v1.1 and the binding worked examples are intact; NFR-3 is enforced
at the DB layer; AC-7 is clean; the mock-first contract is locked by `test_seams`.
The remaining gates are operational (keys, deps, real data) plus the four tracked
polish items above — not a structural defect in the shipped system.

## Next step

Execute **`docs/RUNBOOK-PRODUCTION.md`** top to bottom; the cutover session prompt
is **`PROMPT-CUTOVER.md`**.
