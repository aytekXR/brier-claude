-- Operational tables: disputes, public corrections log, job queue.

-- FR-405/US-006/AC-5: dispute intake creates a tracked ticket with a 7-day SLA.
create table disputes (
    id                                   bigint generated always as identity primary key,
    ticket_code                          text not null unique,   -- e.g. DSP-318, auto-emailed to the analyst
    claim_id                             bigint not null references claims(id),
    submitted_by                         text,                   -- contact email
    rationale                            text not null,
    state                                text not null default 'open',  -- open | adjudicating | upheld | corrected | rejected
    sla_deadline                         timestamptz not null,   -- submitted_at + 7 days (AC-5)
    submitted_at                         timestamptz not null default now(),
    adjudicated_at                       timestamptz,
    adjudication_note                    text,
    methodology_version_at_publication   text                    -- EC-12: adjudicated under the version in force at publication
);
create index disputes_state_idx on disputes (state, sla_deadline);

-- FR-405/NFR-3: the public corrections log. Corrections are public events that
-- pair the superseded resolution with its superseding append (never an edit).
create table corrections (
    id                          bigint generated always as identity primary key,
    claim_id                    bigint not null references claims(id),
    dispute_id                  bigint references disputes(id),
    summary                     text not null,   -- public, neutral-register copy
    superseded_resolution_id    bigint references resolutions(id),
    superseding_resolution_id   bigint references resolutions(id),
    published_at                timestamptz not null default now()
);

-- Postgres-backed job queue; cron-style worker loop, no Celery (locked stack).
create table jobs (
    id          bigint generated always as identity primary key,
    kind        text not null,       -- poll_channels | transcribe | extract | resolve_claims | score_analysts | weekly_digest | freshness_check
    payload     jsonb not null default '{}'::jsonb,
    run_at      timestamptz not null default now(),
    state       text not null default 'queued',  -- queued | running | done | failed
    attempts    integer not null default 0,
    last_error  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index jobs_due_idx on jobs (state, run_at);
