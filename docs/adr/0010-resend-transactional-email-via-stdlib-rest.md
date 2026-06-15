# ADR-0010: Resend transactional email via stdlib REST (no resend SDK)

- **Status:** proposed (pending human approval)
- **Date:** 2026-06-15
- **Deciders:** human owner (approval pending) + pipeline-engineer (proposing, E5-T3)

## Context

Task E5-T3 (FR-405, US-006, AC-5) implements the dispute intake pipeline. When
a dispute ticket is created, the submitter receives an auto-emailed ticket-ID
confirmation (UF-3 happy path HP-5). PRD §18 names **Resend** as the
transactional email provider ("Email: Resend (transactional) + Buttondown
(newsletter)").

The stack is **locked** (CLAUDE.md): no new dependency lands without human
approval and an ADR. The `resend` Python SDK pulls in `httpx`, `pydantic`, and
other transitive dependencies that would change the CI install footprint.

A direct precedent exists from ADR-0005 (LLM extraction) and ADR-0009 (base
rates): both use stdlib `urllib.request` + `json` to call REST APIs that only
require standard headers and a JSON body. The Resend Emails API
(`POST https://api.resend.com/emails`) is identical in structure — three
headers (`Authorization: Bearer <key>`, `Content-Type: application/json`) and a
JSON body with `from`, `to`, `subject`, and `text`. No SDK is needed.

**Mock-first discipline:** The real Resend path is never reachable without
`BRIER_RESEND_API_KEY`. CI and tests inject `FakeNotifier` (which records
messages in a list) through the `Notifier` protocol. The `ResendNotifier` raises
a clear `RuntimeError` mentioning `BRIER_RESEND_API_KEY` and this ADR when the
key is absent, so the CI path fails loudly if misconfigured rather than silently
dropping notifications.

## Decision (proposed)

Implement the `Notifier` seam in `brier_pipeline/disputes/notify.py` using only
stdlib `urllib.request` and `json`:

- A `Notifier` `Protocol` with `send(*, to, subject, body)` is the seam.
- `FakeNotifier` records sent messages in `self.sent` (list of `SentMessage`);
  it is the CI/test path and the default when no notifier is injected.
- `ResendNotifier` POSTs to `https://api.resend.com/emails` with:
  - `Authorization: Bearer <BRIER_RESEND_API_KEY>`
  - `Content-Type: application/json`
  - JSON body: `{"from": "<from_address>", "to": ["<to>"], "subject": "<subject>", "text": "<body>"}`
- The HTTP POST callable is injected (defaults to a real `urllib.request`
  implementation) so tests can supply a recorded-fixture fake without touching
  the network.
- If `BRIER_RESEND_API_KEY` is absent, `ResendNotifier.send()` raises
  `RuntimeError` with a message pointing to `BRIER_RESEND_API_KEY` and this ADR.
  This is the expected failure mode in CI — `FakeNotifier` is the CI path.
- Nothing is added to `[project.dependencies]` or any
  `[project.optional-dependencies]` in `pyproject.toml`.

If/when the human owner approves adding the `resend` SDK, the transport swap is:
replace the body of `ResendNotifier.send()` with an SDK call. No Notifier
Protocol or call-site changes are required.

## Consequences

- Zero new install-time dependencies. CI and dev are unaffected.
- The `Notifier` protocol is provider-neutral; swapping to another
  transactional provider (Postmark, SendGrid, etc.) is a new implementation
  behind the same seam.
- `FakeNotifier.sent` is the test assertion surface for all dispute notification
  tests.
- Real email is only sent when `BRIER_RESEND_API_KEY` is configured on the
  production host; no accidental sends are possible in CI.
- Spend is subject to the NFR-5 cost guardrails (E6-T4). The seam is UNUSED
  in CI; real API calls only occur in the production dispute intake path.
- **This ADR is not yet accepted.** Until the human owner approves, no `resend`
  SDK is added. Changing this requires the owner's approval recorded here
  (status → accepted) per ADR-0001 and CLAUDE.md.
