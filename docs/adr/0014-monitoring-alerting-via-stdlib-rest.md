# ADR-0014: Monitoring and alerting via stdlib REST (no SDK)

- **Status:** accepted (ratified 2026-06-16, launch-readiness ADR gate; no dependency — live activation pending the production `BRIER_BETTER_STACK_TOKEN` and/or `BRIER_SENTRY_DSN`. CI/dev stays mock-first via the FakeAlerter; Axiom remains deferred-by-design.)
- **Date:** 2026-06-16 (proposed and accepted)
- **Deciders:** human owner (approved 2026-06-16) + pipeline-engineer (E6 foundation)

## Context

Epic E6 (Trust + Ops) introduces five operational check-jobs:
- E6-T1: Dispute SLA breach detection.
- E6-T2: Freshness alerts (analyst staleness > 48h, NFR-1).
- E6-T3: Deletion tracking (EC-1, AC-6).
- E6-T4: Monitoring + cost guardrails (NFR-5, PRD §18).
- E6-T5: GDPR/KVKK erasure handling (NFR-6).

PRD §18 names **Better Stack** (heartbeat and log ingestion), **Sentry** (error
capture), and **Axiom** (structured log aggregation) as monitoring targets. Each
provides a REST API that accepts a JSON payload with a bearer token — identical
in structure to the Resend email and CoinGecko price APIs already in use
(ADR-0010, ADR-0009).

The stack is **locked** (CLAUDE.md): no new dependency lands without human
approval and an ADR. The `better-stack`, `sentry-sdk`, and `axiom` Python
packages would each add significant transitive dependencies to the CI install
footprint. None are needed for the structural seam.

**Mock-first discipline:** Every check-job in E6 targets the `Alerter` protocol
with a `FakeAlerter` in CI/tests. The real paths (`BetterStackAlerter`, etc.)
raise `RuntimeError` when their tokens are absent (blocked-by-design), so CI
fails loudly if misconfigured rather than silently dropping alerts.

**Durable queryable record:** The `alerts` table (0008_ops_trust.sql) is the
primary persistence layer for all raised alerts. This means:
- Operational history is queryable via plain SQL without a live monitoring
  service.
- The dedup_key constraint makes alert-raising idempotent (re-running a
  check-job twice does not create duplicate alerts).
- External dispatch (Better Stack, Sentry, etc.) is the secondary notification
  path, gated behind the Alerter seam.

**NFR-5 spend-cap engine:** The spend-meter engine (`ops/spend.py`) emits
`cost_threshold` and `cost_cap` alerts through the same Alerter seam. The cap
values are configuration-driven (BRIER_TRANSCRIPTION_MONTHLY_CAP_USD,
BRIER_LLM_MONTHLY_CAP_USD) and default to the PRD §18 envelopes
($700 transcription, $300 LLM). The 70% alert threshold defaults to
BRIER_SPEND_ALERT_FRACTION (default 0.70).

## Decision (proposed)

Implement monitoring and alerting using only stdlib `urllib.request` and `json`:

- An `Alerter` `Protocol` with `dispatch(alert: Alert)` is the seam
  (`brier_pipeline/ops/alerts.py`).
- `FakeAlerter` records dispatched alerts in `self.dispatched` (list of `Alert`
  models); it is the CI/test path and the default when no alerter is injected.
- `BetterStackAlerter` POSTs to the Better Stack ingest endpoint with:
  - `Authorization: Bearer <BRIER_BETTER_STACK_TOKEN>`
  - `Content-Type: application/json`
  - JSON body with kind, severity, summary, dedup_key, detail fields.
  - The HTTP POST callable is injected (defaults to a real `urllib.request`
    implementation) so tests can supply a recorded-fixture fake without
    touching the network.
  - If `BRIER_BETTER_STACK_TOKEN` is absent, `BetterStackAlerter.dispatch()`
    raises `RuntimeError` with a message referencing this ADR. This is the
    expected failure mode in CI — `FakeAlerter` is the CI path.
- `record_alert(conn, ...)` INSERT into `alerts` with ON CONFLICT (dedup_key)
  DO NOTHING; returns True iff a new row was inserted. This is the durable
  record layer.
- `raise_alert(conn, alerter, ...)` is the unified gate: dedup via
  `record_alert`, then dispatch once to `alerter` if newly recorded.
- Nothing is added to `[project.dependencies]` or any
  `[project.optional-dependencies]` in `pyproject.toml`.

If/when the human owner approves adding a monitoring SDK, the transport swap is:
replace the body of `BetterStackAlerter.dispatch()` with an SDK call. No
`Alerter` Protocol or call-site changes are required.

`SentryAlerter` (error/event capture) is implemented in the same module and
pattern (E6-T4): it derives the Sentry store endpoint from `BRIER_SENTRY_DSN`
(`config.sentry_dsn()`), POSTs the event via the injected stdlib-REST boundary,
and raises `RuntimeError` when the DSN is absent. **Axiom** log aggregation
follows the identical Alerter-seam pattern and is **deferred** (blocked-by-design
behind this ADR — see EX-dept.md): the `alerts` table plus Better Stack and
Sentry already cover the §18 monitoring surface, so no Axiom adapter ships in
this epic (it would add a third sink with no new behaviour). Activating any real
sink requires setting its token/DSN on the production host; CI stays on
`FakeAlerter`.

## Consequences

- Zero new install-time dependencies. CI and dev are unaffected.
- The `Alerter` protocol is provider-neutral; swapping to another monitoring
  provider is a new implementation behind the same seam.
- `FakeAlerter.dispatched` is the test assertion surface for all E6 alert tests.
- The `alerts` table provides a durable, queryable history without any live
  monitoring service; dedup_key uniqueness makes raising idempotent.
- The spend-cap engine (`ops/spend.py`) uses `raise_alert` to emit
  `cost_threshold` (warning, 70% of cap) and `cost_cap` (critical, 100% of cap)
  alerts through the same seam.
- Real alerts are only dispatched when the relevant tokens are configured on the
  production host; no accidental dispatches are possible in CI.
- **Accepted 2026-06-16** at the launch-readiness ADR gate. No monitoring SDK is
  added (stdlib REST only); the only remaining step is setting
  `BRIER_BETTER_STACK_TOKEN` and/or `BRIER_SENTRY_DSN` in production so
  `get_alerter()` returns the real adapter. CI/dev stays mock-first via the
  `FakeAlerter`; Axiom remains deferred-by-design.
