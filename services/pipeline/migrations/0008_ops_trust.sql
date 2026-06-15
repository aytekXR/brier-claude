-- E6 shared foundation: Ops + Trust tables (NFR-5, NFR-6, AC-5, §18).
--
-- This migration is PURELY ADDITIVE and IDEMPOTENT:
--   - uses "create table if not exists" and "create index if not exists"
--   - adds no column to any existing table
--   - changes no trigger, no append-only ledger, no scored schema
--
-- Three new working-state tables (NOT append-only ledgers; mutable by design):
--   alerts         — durable alert ledger written by the Alerter seam
--   spend_ledger   — metered spend per category (NFR-5 cost guardrails)
--   erasure_requests — GDPR/KVKK intake + 30-day policy workflow (NFR-6)

-- alerts: durable alert ledger (kind, severity, dedup_key).
-- dedup_key unique constraint makes alert-raising idempotent.
create table if not exists alerts (
    id          bigint generated always as identity primary key,
    kind        text not null,                             -- dispute_sla_breach | dispute_sla_at_risk | freshness | cost_threshold | cost_cap | erasure_overdue
    severity    text not null default 'warning',           -- info | warning | critical
    subject     text,                                      -- free-form ref (analyst slug, ticket code, spend category...)
    summary     text not null,                             -- neutral-register human summary (AC-7)
    detail      jsonb not null default '{}'::jsonb,
    dedup_key   text not null unique,
    created_at  timestamptz not null default now()
);
create index if not exists alerts_kind_idx on alerts (kind, created_at);

-- spend_ledger: metered spend per category and billing period (NFR-5).
create table if not exists spend_ledger (
    id           bigint generated always as identity primary key,
    category     text not null,                            -- transcription | llm
    period       text not null,                            -- 'YYYY-MM' UTC billing month
    amount_usd   double precision not null check (amount_usd >= 0),
    note         text,
    incurred_at  timestamptz not null default now()
);
create index if not exists spend_ledger_period_idx on spend_ledger (category, period);

-- erasure_requests: GDPR/KVKK intake + 30-day policy workflow (NFR-6).
-- state transitions: received -> in_review -> completed | rejected
create table if not exists erasure_requests (
    id                  bigint generated always as identity primary key,
    subject_ref         text not null,                     -- requester identifier
    scope               text not null,                     -- what is requested erased
    state               text not null default 'received',  -- received | in_review | completed | rejected
    balancing_outcome   text,                              -- retain_legitimate_interest | erase | partial | null
    received_at         timestamptz not null default now(),
    due_at              timestamptz not null,               -- received_at + 30 days (NFR-6)
    decided_at          timestamptz,
    decision_note       text
);
create index if not exists erasure_requests_state_idx on erasure_requests (state, due_at);
