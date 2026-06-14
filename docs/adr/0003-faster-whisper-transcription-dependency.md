# ADR-0003: faster-whisper as an optional transcription dependency

- **Status:** proposed (pending human approval)
- **Date:** 2026-06-14
- **Deciders:** human owner (approval pending) + pipeline-engineer (proposing, E2-T4)

## Context

Task E2-T4 (FR-103) implements real transcription. PRD §18 names the stack:
faster-whisper large-v3 on a rented GPU for the 24-month backfill batch, and a
hosted API (Deepgram/Groq) for incremental uploads. Captions are tried first.

The stack is **locked** (CLAUDE.md "Boring stack, locked"): no new dependency
lands without human approval **and** an ADR. Two of the three transcription
paths need no dependency and are implemented directly with the standard library:

- **Captions** (`DataApiYouTubeClient.fetch_captions`) — stdlib `urllib`.
- **Deepgram incremental** (`DeepgramTranscriber`) — Deepgram exposes a plain
  REST endpoint (`POST https://api.deepgram.com/v1/listen`), so it is called
  with stdlib `urllib` + `json`; **no SDK dependency is added.**

Only **faster-whisper** genuinely requires a heavy new dependency: the
`faster-whisper` package pulls in CTranslate2 and downloads multi-GB model
weights, and runs on a GPU. It cannot be reduced to a stdlib call.

Per the E2 ADR gate, the `WhisperTranscriber` adapter is landed as a **seam**:
the interface is honored, the real call site is structured (lazy `import` of
`faster_whisper` *inside* the method so import-time has no dependency), and it is
unit-tested against a **mocked** model module. The fixture-backed
`FakeTranscriber` remains the only path exercised by `make check`, CI, and the
demo. The dependency itself is **not installed** until this ADR is approved.

## Decision (proposed)

Add `faster-whisper` (pinned) as an **optional extra**, not a core dependency:

```
[project.optional-dependencies]
transcribe = ["faster-whisper==<pinned>"]
```

- It is installed only on the rented-GPU backfill host, never in CI or dev.
- `WhisperTranscriber.transcribe` lazily imports `faster_whisper`; absent the
  extra it raises a clear, actionable error (not at import time).
- The Deepgram path stays stdlib-REST (no SDK). Captions stay stdlib.
- `FakeTranscriber` stays the fixture-backed CI/demo path; no test downloads a
  model or makes a network call.
- Audio is transient with a 30-day TTL (NFR-4); transcripts persist. The audio
  key convention is `audio/<youtube_video_id>` (TTL handled in E2-T5).

## Consequences

- Backfill transcription becomes real once the extra is installed on the GPU
  host; CI and dev are unaffected (the extra is never installed there).
- Cost falls under the NFR-5 guardrails (backfill is a bounded one-off; the
  E6-T4 caps apply to ongoing spend).
- The seam is already merged, so approval only flips installation on — no code
  reshape is required.
- **This ADR is not yet accepted.** Until the human owner approves, the
  `transcribe` extra is not added to `pyproject.toml` and faster-whisper is not
  installed. Changing this requires the owner's approval recorded here (status →
  accepted) per ADR-0001 and CLAUDE.md.
