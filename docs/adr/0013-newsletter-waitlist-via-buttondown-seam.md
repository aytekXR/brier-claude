# ADR-0013: Newsletter and badge waitlist via Buttondown seam (no SDK)

- **Status:** accepted (ratified 2026-06-16, launch-readiness ADR gate; no dependency — live activation pending the production `BRIER_BUTTONDOWN_API_KEY`. CI/dev/build stays mock-first via the FakeSubscriber.)
- **Date:** 2026-06-15 (proposed); 2026-06-16 (accepted)
- **Deciders:** human owner (approved 2026-06-16) + frontend-engineer (E5-T6)

## Context

Task E5-T6 (FR-406, FR-408, US-007, US-008) adds two capture surfaces to the
web application:

1. **Site-wide newsletter signup** (US-007): a compact form in the footer that
   invites readers to subscribe to the weekly digest of notable resolutions.
2. **Badge waitlist CTA** (US-008): a form on each analyst page so an analyst
   can join the waitlist for the public accuracy badge feature (PRD §19.2).

PRD §18 names **Buttondown** as the newsletter provider ("Newsletter:
Buttondown"). Both surfaces require double opt-in (FR-406) so no subscriber is
enrolled without confirming their email. One-click unsubscribe is also required
(FR-406).

The stack is **locked** (CLAUDE.md): no new dependency lands without human
approval and an ADR. A Buttondown SDK or a third-party email-service SDK would
add install-time weight and introduce a network dependency into the CI/build path.

A direct precedent for the seam pattern exists in ADR-0010 (Resend transactional
email): the `Notifier` protocol uses native `fetch` (or stdlib) behind an
injected boundary, with a `FakeNotifier` as the CI path. The Buttondown
Subscribers API (`POST https://api.buttondown.email/v1/subscribers`) follows the
same REST-over-HTTP convention: a single `Authorization: Token <key>` header and
a JSON body. No SDK is needed.

**No self-owned subscriber store is needed.** Buttondown provides double opt-in
confirm emails and one-click unsubscribe natively. Our application initiates
`subscribe` (returns `pending` — waiting for the subscriber's email confirm) and
offers a `GET /newsletter/unsubscribe` route whose single click calls
`unsubscribe` on the Buttondown API. No token table, no local opt-in store.

**No DB table is required.** Subscriber state lives entirely in Buttondown.
The `FakeSubscriber` in-process module array suffices for CI and dev.

**Mock-first discipline:** The `FakeSubscriber` records every action in a
module-level array and returns the appropriate status object without any network
call. It is the CI/build/dev default — the factory selects `FakeSubscriber`
unless `BRIER_BUTTONDOWN_API_KEY` is set. The `ButtondownSubscriber` raises a
clear `Error` mentioning `BRIER_BUTTONDOWN_API_KEY` and `ADR-0013` when the key
is absent. Route handlers (which execute at request time only, never at build or
CI) are the only code that reaches the seam at runtime; the seam is never
exercised during `npm run build` or `make check`.

## Decision (proposed)

Implement the `Subscriber` seam in `apps/web/lib/subscriber.ts` using native
`fetch` (global, no SDK):

- A `Subscriber` interface with two methods:
  - `subscribe({ email, kind, analystSlug? }): Promise<{ status: "pending" }>`
  - `unsubscribe({ email }): Promise<{ status: "unsubscribed" }>`
  - `kind` is `"newsletter" | "waitlist"`.
- `FakeSubscriber`: records actions in a module-level array, validates email,
  returns `{ status: "pending" }` or `{ status: "unsubscribed" }`. No network.
  This is the **CI/build/dev default**.
- `ButtondownSubscriber`: calls the Buttondown Subscribers API via native `fetch`
  (injected, defaults to global `fetch`). Subscribe sets `type: "regular"` (which
  triggers Buttondown's double opt-in flow). Unsubscribe sends a DELETE or a
  PATCH to mark the subscriber unsubscribed. The `analystSlug` is forwarded as a
  Buttondown metadata tag for waitlist tracking. Raises a clear `Error`
  referencing `BRIER_BUTTONDOWN_API_KEY` and `ADR-0013` when the key is absent.
- A `getSubscriber()` factory: returns `FakeSubscriber` unless
  `BRIER_BUTTONDOWN_API_KEY` is set, in which case it returns
  `ButtondownSubscriber`. This ensures CI and offline builds always use the fake.
- A shared `validateEmail(email: string): boolean` helper (simple, robust regex;
  rejects empty and malformed addresses).
- Nothing is added to `package.json` dependencies or devDependencies.

Route handlers (request-time only):

- `POST /api/newsletter` — calls `subscribe({ email, kind: "newsletter" })`,
  returns `200 { status: "pending" }`.
- `POST /api/waitlist` — calls `subscribe({ email, kind: "waitlist", analystSlug })`,
  returns `200 { status: "pending" }`.
- `GET /newsletter/unsubscribe` — one-click unsubscribe from email links, reads
  `?email=` query param, calls `unsubscribe({ email })`, returns a neutral
  HTML/text confirmation. A single click completes the unsubscribe; no further
  interaction is required.

## Consequences

- Zero new install-time dependencies. `npm run build` and `make check` succeed
  fully offline; no Buttondown API call is ever made during CI or build.
- The `Subscriber` interface is provider-neutral. If the human owner later
  approves switching to Resend, Mailchimp, or another service, only the
  `ButtondownSubscriber` body changes; no route handler or component changes.
- `FakeSubscriber._log` is the test and dev assertion surface; it can be
  inspected via the module API.
- Double opt-in is provided by Buttondown natively (the subscriber receives a
  confirmation email; they are not enrolled until they click it).
- One-click unsubscribe is a `GET /newsletter/unsubscribe?email=<addr>` route
  that calls `unsubscribe` without any further confirmation step.
- `analystSlug` is forwarded as a Buttondown tag for waitlist tracking, so the
  human owner can filter subscribers by analyst.
- AC-7 firewall: all user-visible copy is neutral ("weekly digest of notable
  resolutions", "join the badge waitlist"). No buy/sell/hold, no hype vocabulary.
  `scripts/copy_lint.py` scans `apps/web/**/*.ts(x)` and will catch violations.
- **Token-less unsubscribe (MVP trade-off, accepted risk):** The app's own
  `GET /newsletter/unsubscribe?email=` route is token-less — any caller who
  knows a subscriber's address can unsubscribe it (CSRF / enumeration surface).
  This is accepted for MVP because Buttondown's native unsubscribe links (the
  ones included in every outgoing email) carry a per-subscriber token generated
  by Buttondown, so the primary unsubscribe flow is already token-protected. The
  app route exists only as a convenience redirect target. A tokened first-party
  unsubscribe route is deferred to a post-MVP task.
- **This ADR is not yet accepted.** Until the human owner approves, the
  `ButtondownSubscriber` is unreachable (the factory always returns
  `FakeSubscriber` without the key). Accepting this ADR authorises setting
  `BRIER_BUTTONDOWN_API_KEY` in the production environment. No npm package is
  added even after acceptance.
