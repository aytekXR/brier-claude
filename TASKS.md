# Brier Task Backlog

Execution rules:

- Tasks are executed by scoped subagents (`.claude/agents/`), one task at a time, picked via the `next-task` skill: highest-priority unblocked task, epics in order E1 → E6, tasks in order within an epic unless dependencies say otherwise.
- Definition of done for any task: `make check` green + the checkbox below ticked + a matching `LOG.md` DONE line. One without the others is a defect.
- Every stub in the codebase carries a `# TASK: <id>` comment pointing here. Implementing a task means replacing its stubs and removing those markers.
- Deviations from PRD/METHODOLOGY/the locked stack need human approval + an ADR (`docs/adr/`).
- Suggested owner is the default subagent; any agent may take a task if scopes allow.

---

## E1 — Walking Skeleton Slice (first, unblocked, highest priority)

The end-to-end thread on fixtures: transcripts → FakeExtractor → claims → resolution → scoring → leaderboard (PRD HP-1 and HP-2 on fakes), with the four pages rendering real data.

- [x] **E1-T1 — Fixture dataset + `make pipeline-demo` harness** · deps: none · PRD: FR-202, FR-301, HP-1 · owner: pipeline-engineer
  Create fixture claims (~30, realistic specificity spread) in `data/fixtures/claims.json` plus fixture transcripts in `data/fixtures/transcripts/` that the FakeExtractor replays, and 18 months of fixture BTC/ETH/SOL daily closes in `data/fixtures/prices/`. Implement the fixture-backed fakes (`FakeYouTubeClient`, `FakeTranscriber`, `FakeExtractor`, `FakePriceSource`, `LocalFSStorage`) and add the `pipeline-demo` Makefile target that runs the full thread on fixtures (stages may be stubs until E1-T2/T3 land; the target must run and report which stages are pending). Include precomputed fixture base rates per claim so scoring (E1-T2) is unblocked before the real base-rate engine (E4-T2).
- [x] **E1-T2 — FAS scoring engine** · deps: E1-T1 · PRD: FR-304, FR-305, AC-3 · owner: scoring-quant
  Implement `brier_pipeline/scoring/fas.py` exactly per `docs/METHODOLOGY.md` with unit tests encoding both worked examples: B outranks A despite a lower raw hit rate; A lands in the 45-60 band; B lands in the 60-80 band and is flagged provisional; shrinkage k=25; minimum n=20. Scores write to the append-only `scores` ledger under a `score_runs` row tagged with the methodology version.
- [x] **E1-T3 — Resolution engine v0** · deps: E1-T1 · PRD: FR-302, HP-2 · owner: pipeline-engineer
  Implement `resolve_target_by_deadline`, `resolve_directional_at_horizon` (with partial credit 0.5), and `resolve_open_claims` against fixture prices. Close basis only. Outcomes append to `resolutions` with rule_id, rationale, and price citation. HP-2's claim ("BTC daily close above $80k by Jul 31" resolving HIT on a qualifying close) is the canonical test case.
- [x] **E1-T4 — Wire `make pipeline-demo` end to end** · deps: E1-T2, E1-T3 · PRD: HP-1, HP-2 · owner: pipeline-engineer
  `make pipeline-demo` runs transcripts → FakeExtractor → claims → resolution → scoring → leaderboard on fixtures and prints the ranked board (PRD HP-1 and HP-2 on fakes). Idempotent; safe to re-run; finishes against a fresh `make seed` database.
- [x] **E1-T5 — Four pages rendering real data** · deps: E1-T4 · PRD: FR-401, FR-402, FR-403, FR-404, AC-3 · owner: frontend-engineer
  Leaderboard rows (rank, FAS badge, n, falsifiability, trend) from the score ledger; analyst page with component bars, outcome chips, and the claim table; receipt page with claim card, placeholder player, and a real lightweight-charts price chart t0 → resolution; methodology page already renders the doc. Numbers must match the ledger exactly (AC-3). copy-lint stays green.

## E2 — Ingestion

- [x] **E2-T1 — Analyst registry operations** · deps: E1-T4 · PRD: FR-101 · owner: pipeline-engineer
  Registry CRUD (plain SQL + small CLI), status and jurisdiction flags, 50-analyst roster import.
- [x] **E2-T2 — New-upload poller** · deps: E2-T1, E2-T6 · PRD: FR-102, HP-1, NFR-1 · owner: pipeline-engineer
  `DataApiYouTubeClient.list_uploads_since` + `poll_registered_channels` at ≤2h latency via playlistItems (1 unit, never search). Staleness >48h raises the freshness flag.
- [x] **E2-T3 — 24-month backfill crawler** · deps: E2-T2 · PRD: FR-104, G3 · owner: pipeline-engineer
  `backfill_channel` over the trailing 24 months, resumable, quota-aware, capped per the cost guardrails (NFR-5).
- [ ] **E2-T4 — Captions + transcription adapters (real)** · deps: E2-T2 · PRD: FR-103 · owner: pipeline-engineer
  Caption-first acquisition; `WhisperTranscriber` (batch GPU) and `DeepgramTranscriber` (incremental) producing second-level offsets; audio transient with 30-day TTL.
- [ ] **E2-T5 — R2 storage adapter + audio TTL** · deps: E2-T4 · PRD: NFR-4 · owner: pipeline-engineer
  `R2Storage` implementation, lifecycle rule for audio, transcripts persistent.
- [x] **E2-T6 — Jobs worker loop** · deps: E1-T4 · PRD: §11 data flows · owner: pipeline-engineer
  `claim_next_job`/`run_forever` over the `jobs` table with SKIP LOCKED, retries, and per-kind dispatch. No Celery.

## E3 — Extraction + QA

- [x] **E3-T1 — Pass-1 candidate detection** · deps: E1-T4 · PRD: FR-201 · owner: pipeline-engineer
  `LlmExtractor.detect_candidates` via LiteLLM (Haiku-class, structured outputs), batch over transcripts, spend within NFR-5 caps.
- [x] **E3-T2 — Pass-2 structuring** · deps: E3-T1 · PRD: FR-202, EC-3, EC-7 · owner: pipeline-engineer
  `LlmExtractor.structure_claim` into the full FR-202 tuple with model/prompt versions; controlled asset vocabulary + alias table; sarcasm/hypothetical/paraphrase exclusion (EC-3); unresolvable asset → void (EC-7).
- [x] **E3-T3 — Confidence threshold + QA queue loop** · deps: E3-T2 · PRD: FR-203, US-009, HP-4, NFR-2 · owner: pipeline-engineer
  Label Studio queue wiring, `route_low_confidence` + `record_review`, reviewer_id recorded, nothing below threshold publishes unreviewed. Diarization uncertainty routes here (EC-5).
- [ ] **E3-T4 — Non-falsifiable classifier** · deps: E3-T2 · PRD: FR-204 · owner: pipeline-engineer
  Classify prediction-like but unfalsifiable statements; they count toward the falsifiability ratio, never score.
- [ ] **E3-T5 — Semantic dedup** · deps: E3-T2 · PRD: FR-205, EC-2 · owner: pipeline-engineer
  `dedup_claims` via pgvector embeddings; repeats reinforce, not multiply; re-uploads keep the original timestamp.
- [ ] **E3-T6 — Golden-set eval harness** · deps: E3-T2 · PRD: AC-1, G2, §18 eval · owner: qa-reviewer (spec) + pipeline-engineer (harness)
  `data/fixtures/golden_set.jsonl` (200 hand-labeled claims from 40 videos), pytest/promptfoo harness in CI as a required check: precision ≥95%, recall ≥80% or the build fails.

## E4 — Resolution + Scoring hardening

- [ ] **E4-T1 — Full resolution rule library** · deps: E1-T3 · PRD: FR-302 · owner: pipeline-engineer
  Conditional activation (`resolve_conditional`), default horizons (soon=30d, this year=Dec 31, none=90d), explicit reversal closes the original claim at reversal date (EC-11). Every rule documented on /methodology.
- [ ] **E4-T2 — Base rates from trailing 5-year history** · deps: E1-T3 · PRD: FR-303 · owner: scoring-quant
  `base_rate()` per claim from composite closes (CoinGecko + CCXT cross-check); replaces E1 fixture base rates; published with the methodology.
- [ ] **E4-T3 — Edge cases EC-1 to EC-12** · deps: E4-T1 · PRD: §12 · owner: pipeline-engineer
  One test per edge case, implementation where missing: EC-1 deletion persistence, EC-2 re-uploads, EC-3 sarcasm residue, EC-4 sponsor segments, EC-5 guests, EC-6 hedging, EC-7 asset ambiguity, EC-8 price gaps defer, EC-9 depegs/token death, EC-10 legal fast-track flag, EC-11 reversals, EC-12 version-pinned disputes.
- [ ] **E4-T4 — Contradiction detection** · deps: E3-T5 · PRD: EC-6 · owner: pipeline-engineer
  `detect_contradictions`: opposite-direction claims, same asset, overlapping horizons → void both + hedging flag.
- [ ] **E4-T5 — Methodology version recompute** · deps: E1-T2 · PRD: FR-304, AC-4, HP-6, US-010 · owner: scoring-quant
  `recompute_all`: version bump → full-history recompute into a new score_run; prior ledger archived and queryable; changelog entry on /methodology.

## E5 — Web completion

- [ ] **E5-T1 — Receipts with real embeds** · deps: E1-T5 · PRD: FR-403, AC-2, US-003, EC-1 · owner: frontend-engineer
  Official IFrame player auto-seeked to the claim offset (starts within 3s), deletion flag overlay for dead sources (AC-6), resolution rationale and dispute link.
- [ ] **E5-T2 — Corrections log page** · deps: E1-T5 · PRD: FR-405, NFR-3 · owner: frontend-engineer
  Public, chronological, paired superseded/superseding resolutions, neutral register.
- [ ] **E5-T3 — Dispute flow** · deps: E5-T2 · PRD: FR-405, US-006, AC-5, UF-3 · owner: frontend-engineer (form) + pipeline-engineer (intake)
  Per-claim form → tracked ticket with auto-emailed ID → 7-day SLA countdown → adjudication recorded → public log entry when corrective.
- [ ] **E5-T4 — OG share cards** · deps: E1-T5 · PRD: §19 social layer · owner: frontend-engineer
  Vercel OG cards per receipt and per analyst (score, claim, outcome); alt text on all cards.
- [ ] **E5-T5 — SEO + name-query metadata** · deps: E1-T5 · PRD: FR-407, §18 · owner: frontend-engineer
  Server-rendered analyst metadata for name queries, sitemap, Lighthouse mobile ≥90, p95 <2s on the leaderboard (materialized views + cache).
- [ ] **E5-T6 — Badge waitlist + newsletter capture** · deps: E1-T5 · PRD: FR-406, FR-408, US-007, US-008 · owner: frontend-engineer
  Waitlist CTA on analyst pages; site-wide signup, double opt-in, one-click unsubscribe (Buttondown/Resend).

## E6 — Trust + Ops

- [ ] **E6-T1 — Dispute SLA tooling** · deps: E5-T3 · PRD: AC-5, §7 trust metrics · owner: pipeline-engineer
  SLA clock, breach alerts, weekly dispute report; 100% within 7 days is a launch metric.
- [ ] **E6-T2 — Freshness alerts** · deps: E2-T2 · PRD: NFR-1 · owner: pipeline-engineer
  `freshness_check` job: any analyst stale >48h alerts (Better Stack/Sentry).
- [ ] **E6-T3 — Deletion tracking** · deps: E2-T2 · PRD: EC-1, AC-6 · owner: pipeline-engineer
  Detect deleted/privated sources, set source_status, surface the flag on receipts; claims and resolutions persist.
- [ ] **E6-T4 — Monitoring + cost guardrails** · deps: E2-T4, E3-T2 · PRD: NFR-5, §18 · owner: pipeline-engineer
  Sentry + Axiom wiring, hard monthly caps on transcription/LLM spend with alerts at 70%.
- [ ] **E6-T5 — GDPR/KVKK erasure handling** · deps: E2-T1 · PRD: NFR-6 · owner: pipeline-engineer
  Erasure-request intake and 30-day policy workflow; legitimate-interest balancing test linked from /about.
