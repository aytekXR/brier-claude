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

---

## Resolved

_(none yet)_
