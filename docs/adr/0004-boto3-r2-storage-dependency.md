# ADR-0004: boto3 as an optional dependency for Cloudflare R2 storage

- **Status:** proposed (pending human approval)
- **Date:** 2026-06-14
- **Deciders:** human owner (approval pending) + pipeline-engineer (proposing, E2-T5)

## Context

Task E2-T5 (NFR-4) implements the production object-storage adapter:
transcripts are persistent; audio is transient with a 30-day TTL; no raw video
is ever hosted. PRD §18 names **Cloudflare R2** (S3-compatible, zero egress).

The stack is **locked** (CLAUDE.md): no new dependency without human approval
**and** an ADR. R2's S3 API requires AWS SigV4-signed requests. Two options:

- **(a) boto3** — the standard, well-tested AWS SDK; points at R2's S3 endpoint
  via `endpoint_url`. Heavy, but the signing and retry logic are battle-tested.
- **(b) hand-rolled SigV4** over stdlib `hmac`/`hashlib`/`urllib` — no
  dependency, but it puts security-sensitive request-signing code in our
  repository to own and maintain. Rejected: we do not want to own crypto-signing
  for a credentialed production data path.

Per the E2 ADR gate, `R2Storage` is landed as a **seam**: the interface is
honored, the real call site is structured around an S3 client created by a lazy
`import boto3` *inside* the methods, and it is unit-tested against a **mocked**
S3 client. `LocalFSStorage` remains the path exercised by `make check`, CI, and
the demo, and it implements a **real, dependency-free** audio TTL sweep
(`sweep_expired_audio`) over file mtimes so the 30-day-TTL behaviour (NFR-4) is
genuinely tested without any cloud or dependency. The boto3 dependency itself is
**not installed** until this ADR is approved.

## Decision (proposed)

Add `boto3` (pinned) as an **optional extra**, not a core dependency:

```
[project.optional-dependencies]
storage = ["boto3==<pinned>"]
```

- Installed only where production storage runs; never in CI or dev.
- `R2Storage` lazily imports `boto3`; absent the extra it raises a clear,
  actionable error (not at import time).
- The audio 30-day TTL is enforced in production by an **R2 bucket lifecycle
  rule** on the `audio/` prefix (configured via boto3); transcripts under the
  `transcripts/` prefix are persistent. `LocalFSStorage.sweep_expired_audio`
  provides the equivalent for dev and is what tests exercise.
- `LocalFSStorage` stays the fixture/CI/demo path; no test touches R2, real
  credentials, or the network.
- Reject hand-rolled SigV4 (option b): not worth owning credentialed
  request-signing code.

## Consequences

- Production storage and the audio TTL lifecycle become real once the extra is
  installed and credentials are provisioned; CI and dev are unaffected.
- The seam is already merged, so approval only flips installation on — no code
  reshape is required.
- Zero-egress economics (R2) and NFR-4 (no raw video; transient audio) are met.
- **This ADR is not yet accepted.** Until the human owner approves, the
  `storage` extra is not added to `pyproject.toml` and boto3 is not installed.
  Changing this requires the owner's approval recorded here (status → accepted)
  per ADR-0001 and CLAUDE.md.
