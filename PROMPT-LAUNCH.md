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
