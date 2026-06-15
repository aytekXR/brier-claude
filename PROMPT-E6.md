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
