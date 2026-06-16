# Brier — Production Activation, Backfill & Deploy Runbook

**Audience:** the operator executing the first production cutover.
**Status as of 2026-06-16:** **NO-GO** (see the go/no-go assessment in
`docs/LAUNCH-READINESS.md`). The application code is launch-ready and the gate is
green on fixtures; what remains is operational — real credentials, the
heavy-dependency installs on their dedicated hosts, the real roster ingest, and
the 24-month backfill. This runbook is the exact sequence to close those gates.

**Binding rule for every step:** never commit a key or token to the repo. All
credentials are environment variables on the production/worker hosts only. CI
and `make check` stay mock-first (the fakes are the CI path) — activating a real
adapter must never regress the gate.

---

## 0. Pre-flight on the deploy box (the acceptance test)

Run the full launch-style verification and confirm it is green before any
activation work. On the Ubuntu VPS the DB comes up via docker (`sg docker`):

```bash
cd "$REPO"
sg docker -c 'make ci'      # = migrate+seed → make check → pipeline-demo → web-build
```

Expect: `make check` green (**760 + the new migration/seam guards, 1 benign
skip**; copy-lint / ruff / ruff-format / mypy-strict / tsc / eslint clean), the
demo board **NorthChain 59.0 / VectorEdge 57.5 / Aylin 51.7** (20 cumulative
resolutions), and the Next build clean. If anything is red, fix the environment
(not the code) until green. The identical sequence runs in CI on every push
(`.github/workflows/ci.yml`, now with a Postgres service container).

---

## 1. Activate external adapters (the ADR gate)

ADRs **0001/0002/0005/0006/0007/0010/0011/0012/0013/0014 are accepted**; the
no-dependency adapters need only a production env var. ADRs **0003/0004/0008**
(and optionally **0009-CCXT**) are still *proposed* heavy-dependency seams —
approve each (flip its ADR status + tick its TASKS.md box + move its EX-dept
entry to Resolved) before installing its optional extra.

| Adapter | ADR | New dependency? | Activate by | Verify |
| --- | --- | --- | --- | --- |
| LLM extraction (Anthropic) | 0005 ✅ | none (stdlib REST) | `export BRIER_ANTHROPIC_API_KEY=…` on the worker host | extraction uses the real model, not `FakeExtractor` |
| Transactional email (Resend) | 0010 ✅ | none (stdlib REST) | `export BRIER_RESEND_API_KEY=…` (web host) | `getNotifier()` returns `ResendNotifier`; dispute ticket email sends |
| Newsletter (Buttondown) | 0013 ✅ | none (native fetch) | `export BRIER_BUTTONDOWN_API_KEY=…` (web host) | `getSubscriber()` returns `ButtondownSubscriber` |
| Monitoring/alerting | 0014 ✅ | none (stdlib REST) | `export BRIER_BETTER_STACK_TOKEN=…` and/or `BRIER_SENTRY_DSN=…` | `get_alerter()` returns the real adapter (test: `test_seams.py`) |
| Whisper transcription | 0003 ⏳ | `faster-whisper` (GPU) | approve ADR → add the pinned **optional extra** to `pyproject.toml`; `pip install 'brier-pipeline[whisper]'` **on the rented-GPU backfill host only** | `WhisperTranscriber.transcribe()` no longer raises the ADR-0003 RuntimeError |
| R2 object storage | 0004 ⏳ | `boto3` | approve ADR → add the pinned optional extra; `pip install 'brier-pipeline[r2]'`; set R2 creds; call `ensure_audio_ttl_lifecycle` (30-day `audio/` rule) | `R2Storage` round-trips; transcripts persist, audio expires |
| Semantic embeddings | 0008 ⏳ | `sentence-transformers` | approve ADR → add the pinned optional extra; `pip install 'brier-pipeline[embed]'` where dedup runs | `SentenceTransformerEmbedder.embed()` no longer raises ADR-0008 |
| CCXT cross-check (optional) | 0009 ⏳ | `ccxt` | approve a CCXT ADR → add the optional extra; wire `CcxtCrossCheckSource` | EC-8 outage detection active; base rates unchanged |

The four no-dep activations are reversible by unsetting the env var (the factory
falls back to the fake — and `get_alerter()` logs a warning if a prod host is
missing its token). The mock-first contract is guarded by `test_seams.py`.

---

## 2. Roster ingest — G1 (50 named analysts, receipt-backed)

The fixture roster is 3 analysts. Build the real 50-analyst roster as a JSON file
in the same shape as `data/fixtures/analysts.json` (crypto + YouTube only —
**scope lock**; set `jurisdiction_flag` where applicable), then bulk-upsert it:

```bash
$PY -m brier_pipeline.ingestion.registry import-roster path/to/roster-50.json
$PY -m brier_pipeline.ingestion.registry list           # verify count + status + jurisdiction
```

`import_roster` is an idempotent upsert (on `channel_id`); safe to re-run as the
roster is curated. Out-of-scope jurisdictions are rejected by `_assert_in_scope`.

---

## 3. 24-month backfill — G3 (≥10,000 resolved claims)

**Gated on §1**: transcription (ADR-0003 + GPU host), R2 (ADR-0004), embeddings
(ADR-0008), and the LLM key (ADR-0005). Without those the backfill cannot
produce real transcripts/claims and you must stop here.

The thread is enqueue-then-drain. `backfill_channel` is **resumable** (skips
already-ingested videos) and **capped** (`max_videos` per call, NFR-5).

> **Backfill-handler wiring (cutover prerequisite — flagged by the
> launch-readiness audit).** Only the operational handlers self-register today
> (`poll_channels`, `deletion_sweep`, `freshness_check`, `dispute_sla_check`,
> `weekly_dispute_report`, `erasure_sla_check`). The **backfill job kinds
> `transcribe` / `extract` / `resolve_claims` / `score_analysts` are NOT yet
> registered as job handlers** — the demo runs them as direct function calls.
> Wiring them as `jobs` handlers (so `backfill_channel`'s enqueued `transcribe`
> jobs are processed) is part of backfill activation and is gated on
> ADR-0003/0004/0008. Register them in the worker bootstrap below before draining.

```bash
# 1) Enqueue the trailing-24-month crawl per registered channel.
#    backfill_channel(client=DataApiYouTubeClient(...), channel_id, months=24,
#    max_videos=<cost-cap>) — it inserts videos and ENQUEUEs 'transcribe' jobs.

# 2) Run the jobs worker to drain the pipeline (E2-T6 loop, SKIP LOCKED + retries).
#    CRITICAL: import every handler module FIRST so its register_handler() runs
#    (run_forever does NOT auto-discover handlers — see its docstring):
$PY - <<'PY'
from brier_pipeline.ingestion import poller, deletion, freshness   # poll_channels, deletion_sweep, freshness_check
from brier_pipeline.disputes import sla                            # dispute_sla_check, weekly_dispute_report
from brier_pipeline.ops import erasure                             # erasure_sla_check
# from brier_pipeline... import <transcribe/extract/resolve/score handlers>  # wire these for the backfill (see note above)
from brier_pipeline.jobs.worker import run_forever
run_forever()
PY
```

Watch the NFR-5 spend caps (`$700 transcription / $300 LLM / alert at 70%`,
config-driven) — `MeteredCompletion`/`MeteredTranscriber` block the inner call at
100% of the monthly cap. Re-run after a cap reset / month rollover to continue
(the crawl is resumable).

**Verify G3:**

```sql
select count(*) from resolutions r
where not exists (select 1 from resolutions r2 where r2.supersedes_resolution_id = r.id);
-- must be >= 10000
```

---

## 4. Golden-set re-run on REAL model output — AC-1 / G2

With `BRIER_ANTHROPIC_API_KEY` live, re-run the golden harness against **real
extraction output** (not the fixture replay) and require **precision ≥ 95% &
recall ≥ 80%**:

```bash
cd services/pipeline && .venv/bin/python -m pytest tests/test_golden_set.py -q
# (configured to read real-model output; fails the run below either threshold)
```

This is the AC-1/G2 launch gate — do not ship if it is red on real output.

---

## 5. Schedule the trust-ops jobs

Register/enqueue these `jobs` kinds on a schedule (cron enqueuing into the
`jobs` table, drained by `run_forever`). **The long-running worker process must
import each handler module at startup (see §3's bootstrap) — `run_forever`
registers nothing on its own**, so a handler whose module is never imported
silently never runs. Set spend caps to the real monthly budget first.

| Job kind | Cadence | Purpose (PRD) |
| --- | --- | --- |
| `poll_channels` | ≤ 2h | new-upload poller (FR-102, NFR-1) |
| `freshness_check` | hourly/daily | alert when an analyst is stale > 48h (NFR-1) |
| `resolve_claims` | daily | resolve open claims past their horizon |
| `score_analysts` | nightly | recompute FAS into a new append-only score_run |
| `deletion_sweep` | daily | detect deleted/privated sources (EC-1/AC-6) |
| `dispute_sla_check` | daily | 7-day SLA clock + breach/at-risk alerts (AC-5) |
| `weekly_dispute_report` | weekly | dispute SLA report (launch trust metric) |
| `erasure_sla_check` | daily | 30-day GDPR/KVKK erasure SLA (NFR-6) |

---

## 6. Monitoring + rollback

- **Monitoring:** confirm Better Stack / Sentry are receiving events once their
  tokens are set (§1). The durable, dedup-keyed `alerts` table records every
  alert regardless of sink, so nothing is lost if a sink is down. Axiom is
  deferred-by-design (ADR-0014).
- **Rollback:** the ledger is **append-only (NFR-3)** — there is no destructive
  edit to roll back. A bad scoring/methodology change is corrected by a
  `recompute_all` into a new `score_run` (prior runs stay queryable, AC-4); a bad
  resolution is corrected by appending a superseding row. DB triggers
  (`resolutions_append_only`, `scores_append_only`) enforce this.

---

## 7. Final compliance checks before flipping live

- **AC-7:** `python scripts/copy_lint.py` clean on the final build (it scans web
  copy + `docs/METHODOLOGY.md` + `docs/LEGITIMATE_INTEREST.md`).
- **NFR-6:** the `/about` legitimate-interest notice is published, and the
  30-day erasure workflow has a named owner.
- **NFR-3 spot check:** attempt an `UPDATE`/`DELETE` on `resolutions` — it must
  raise `append-only ledger …` (guarded by `test_append_only_placeholder.py` +
  `test_migrations.py`).
- **Scope lock:** crypto + YouTube only; no auth/payments; quotes ≤ 15 words.
- **No scoring change:** v1.1 intact; the binding worked examples
  (`tests/test_fas.py`: FAS_A≈47.02, FAS_B≈66.74, B-outranks-A, k=25, min n=20)
  must not move.

---

## 8. Go / No-Go sign-off

Use the checklist in `docs/LAUNCH-READINESS.md`. Production is **GO** only when:
the acceptance test is green on the deploy box; every adapter you intend to run
is activated (key/dep set, no key committed); the 50-roster is ingested and the
24-month backfill has produced ≥ 10,000 resolved claims; the golden gate passes
on real model output; the trust-ops jobs are scheduled; monitoring is live; and
the compliance checks above pass. Otherwise it is **NO-GO** — record which gate
failed and resume here.
