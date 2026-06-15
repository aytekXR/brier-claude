# Brier — Exceptions & Deferred Tasks ledger (technical debt)

Purpose: a single place that records every task whose TASKS.md checkbox is **not
ticked** because it is intentionally deferred — almost always an ADR-gated heavy
dependency that the locked stack (CLAUDE.md "Boring stack, locked") will not let
us add without human approval. Each entry states what *is* delivered (the seam +
mock-first fake that CI exercises), what *remains* (the dependency install +
human ADR approval), and the exact pointers (ADR, LOG line, commit) to resume.

This file is **not** a substitute for the DoD: a task here is genuinely
incomplete until its dependency is approved, installed, and its checkbox ticked
with a matching LOG.md DONE line. It exists so that "blocked-by-design" never
silently reads as "forgotten."

Convention: when a blocked item is finally approved and closed, move its entry to
the **Resolved** section at the bottom (do not delete it) and tick the TASKS.md box.

---

## Open — blocked by design (pending human ADR approval)

### E2-T4 — Captions + transcription adapters (real) · FR-103
- **Status:** seam landed, dependency-requiring portion BLOCKED. TASKS.md checkbox UNTICKED.
- **Delivered (CI path, no network):** caption-first acquisition (`fetch_captions`,
  stdlib `urllib`), `DeepgramTranscriber` (stdlib REST, no SDK, second-level
  offsets) — both fully implemented and tested; `WhisperTranscriber` seam (lazy
  `faster_whisper` import, mocked-model test, clear `RuntimeError` → ADR-0003 when
  absent); `AUDIO_TTL_DAYS = 30` (NFR-4). `FakeTranscriber` remains the CI/demo path.
- **Remaining to close:** human approval of **ADR-0003** → add the pinned
  `faster-whisper` *optional extra* to `pyproject.toml` and install it only on the
  rented-GPU backfill host (never CI/dev). No code reshape required — the seam is merged.
- **Pointers:** ADR `docs/adr/0003-faster-whisper-transcription-dependency.md`
  (Status: proposed); commit `7f6cbde`; LOG.md E2-T4 `BLOCKED` line (2026-06-14 15:47).
- **Blast radius:** none on E3 — extraction reads transcripts, which captions/Deepgram/FakeTranscriber already produce.

### E2-T5 — R2 storage adapter + audio TTL · NFR-4
- **Status:** seam landed, dependency-requiring portion BLOCKED. TASKS.md checkbox UNTICKED.
- **Delivered (CI path, no network):** `R2Storage` seam (lazy `boto3`, injected
  client factory, `ensure_audio_ttl_lifecycle` 30-day `audio/` rule, clear
  `RuntimeError` → ADR-0004 when absent); `LocalFSStorage.sweep_expired_audio` is the
  **real** dependency-free 30-day audio TTL exercised by CI (never deletes
  `transcripts/`). `LocalFSStorage` remains the CI/demo path.
- **Remaining to close:** human approval of **ADR-0004** → add the pinned `boto3`
  *optional extra* to `pyproject.toml`, installed only where R2 is reached. No code reshape required.
- **Pointers:** ADR `docs/adr/0004-boto3-r2-storage-dependency.md` (Status: proposed);
  commit `571d167`; LOG.md E2-T5 `BLOCKED` line (2026-06-14 15:58).
- **Blast radius:** none on E3.

### E3-T5 — Semantic dedup: production embedding model · FR-205, EC-2
- **Status:** seam + full dedup logic landed, dependency-requiring portion BLOCKED. TASKS.md checkbox UNTICKED.
- **Delivered (CI path, no network/model):** `dedup_claims` fully implements FR-205 grouping
  (same analyst+asset+direction+overlapping-horizon), representative-linkage clustering with one
  shared `dedup_cluster_id` (repeats reinforce, not multiply), and EC-2 (re-uploads keep the
  earliest `uttered_at`). On the DB path the similarity query uses the real pgvector `<=>`
  cosine-distance operator on `claims.embedding vector(384)` (no migration needed — column exists).
  The `Embedder` seam: `SentenceTransformerEmbedder` lazily imports `sentence-transformers`
  (all-MiniLM-L6-v2, 384-dim) and raises a clear `RuntimeError` → ADR-0008 when absent; an injected
  fake embedder / synthetic vectors are the CI/test path (DB-backed tests run on the dev DB).
- **Remaining to close:** human approval of **ADR-0008** → add the pinned `sentence-transformers`
  *optional extra* to `pyproject.toml`, installed only where dedup runs (never CI/dev). Without it,
  dedup matches only identical text (the fake embedder); true *semantic* dedup needs the real model.
  No code reshape — the seam + pgvector query are merged.
- **Pointers:** ADR `docs/adr/0008-sentence-transformers-embedding-dependency.md` (Status: proposed);
  commit (E3-T5 seam); LOG.md E3-T5 `BLOCKED` line. mypy override for `sentence_transformers` added.
- **Blast radius:** none on the rest of E3; E4-T4 (contradiction detection) depends on E3-T5's dedup
  scaffolding, which is present and tested.

### E4-T2 (sub-item) — CCXT cross-check for price-outage detection · §18, EC-8
- **Status:** seam landed, dependency-requiring portion BLOCKED. **E4-T2 itself is DONE/ticked** — this
  is a robustness *sub-component*, not the task core. The core (real trailing-history `base_rate`, the
  CoinGecko composite source, the v1.1 methodology bump + recompute) is complete and shipped without it.
- **Delivered (CI path, no network):** `CoinGeckoPriceSource` (stdlib `urllib` REST, injected `http_get`
  boundary, recorded fixture `data/fixtures/coingecko/`, no new dependency) is the published composite
  source. `CcxtCrossCheckSource` is a seam: a lazy `import ccxt` inside the method that raises a clear
  `RuntimeError` → ADR-0009 when absent; an injected/mocked exchange boundary is the test path. `ccxt`
  is NOT in `pyproject.toml` deps; a scoped `[[tool.mypy.overrides]] ignore_missing_imports` stanza
  handles the optional import. `FakePriceSource` (fixture closes) remains the CI/demo path.
- **Remaining to close:** human approval to add the heavy `ccxt` dependency (an *optional extra*,
  installed only where the live cross-check runs, never CI/dev) → wire the real exchange call in
  `CcxtCrossCheckSource` and enable the CoinGecko-vs-CCXT divergence/outage check (EC-8). Until then the
  cross-check is structurally present but inert; base rates compute from the CoinGecko composite (prod)
  or fixtures (CI) without a second-source check.
- **Pointers:** ADR `docs/adr/0009-base-rates-from-trailing-history.md` (Status: proposed); LOG.md
  E4-T2 `NOTE` (CCXT seam) line; the E4-T2 commit. mypy override for `ccxt` added to `pyproject.toml`.
- **Blast radius:** none — scoring uses the CoinGecko composite / FakePriceSource; the cross-check only
  adds outage detection, which degrades gracefully to "no second source" when absent.

---

## Resolved

_(none yet)_
