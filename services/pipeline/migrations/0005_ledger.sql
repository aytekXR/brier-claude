-- ============================================================================
-- APPEND-ONLY LEDGER (NFR-3, AC-4).
-- Rows in `resolutions` and `scores` are NEVER updated or deleted in place.
-- Corrections append a new row that references the superseded one via
-- supersedes_*_id; methodology bumps write a whole new score_run while the
-- prior run stays archived and queryable. No silent edits — corrections are
-- public events (the corrections table, migration 0006).
-- The forbid_mutation triggers below enforce this at the database layer.
-- Do not drop or disable them outside a reviewed ADR.
-- ============================================================================

-- Resolution outcomes (FR-302). One row per resolution event.
create table resolutions (
    id                        bigint generated always as identity primary key,
    claim_id                  bigint not null references claims(id),
    outcome                   numeric not null check (outcome in (0, 0.5, 1)),  -- METHODOLOGY.md §2
    resolved_at               timestamptz not null default now(),
    rule_id                   text not null,     -- rule-library entry that produced this outcome (FR-302)
    rationale                 text not null,     -- shown on the receipt (FR-403)
    price_citation            jsonb not null,    -- {asset, day, close_usd, source} backing the outcome
    methodology_version       text not null,
    supersedes_resolution_id  bigint references resolutions(id)  -- set on corrective re-resolution (HP-5)
);
create index resolutions_claim_idx on resolutions (claim_id);

-- Scoring runs (FR-304). A version bump triggers a full-history recompute into
-- a new run; prior runs remain the archived ledger (AC-4, HP-6).
create table score_runs (
    id                   bigint generated always as identity primary key,
    methodology_version  text not null,
    started_at           timestamptz not null default now(),
    finished_at          timestamptz,
    trigger              text not null,  -- nightly | methodology_bump | correction | demo
    notes                text
);

-- Per-analyst scores within a run (FR-304/FR-305).
create table scores (
    id                   bigint generated always as identity primary key,
    score_run_id         bigint not null references score_runs(id),
    analyst_id           bigint not null references analysts(id),
    methodology_version  text not null,
    fas                  numeric not null,   -- 100 * (nR + kR_prior)/(n + k), k = 25
    directional_skill    numeric not null,
    calibration          numeric not null,
    consistency          numeric not null,
    falsifiability       numeric not null,
    n_resolved           integer not null,
    ranked               boolean not null,   -- n >= 20 (FR-305)
    provisional          boolean not null,   -- two-tier rule: flag clears at n >= 30 (METHODOLOGY.md §6)
    supersedes_score_id  bigint references scores(id),
    created_at           timestamptz not null default now(),
    unique (score_run_id, analyst_id)
);
create index scores_analyst_idx on scores (analyst_id);

-- The enforcement: any UPDATE or DELETE on ledger tables is an error.
create function forbid_mutation() returns trigger
language plpgsql as $$
begin
    raise exception 'append-only ledger: % rows are never updated or deleted; append a superseding row instead (NFR-3)',
        tg_table_name;
end;
$$;

create trigger resolutions_append_only
    before update or delete on resolutions
    for each row execute function forbid_mutation();

create trigger scores_append_only
    before update or delete on scores
    for each row execute function forbid_mutation();
