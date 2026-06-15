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
