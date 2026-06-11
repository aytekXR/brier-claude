-- FR-202: structured claims. One row per extracted prediction span, including
-- classified non-falsifiable statements (FR-204), which count toward the
-- falsifiability ratio but never score.
-- NFR-2 reproducibility: source pointer, transcript span, model/prompt
-- versions, and reviewer id (when QA-touched) are all recorded here.
create table claims (
    id                     bigint generated always as identity primary key,
    analyst_id             bigint not null references analysts(id),
    video_id               bigint not null references videos(id),
    transcript_id          bigint not null references transcripts(id),

    -- the falsifiable tuple (METHODOLOGY.md §1)
    asset                  text,             -- controlled vocabulary + alias table; null when unresolvable -> void (EC-7)
    direction              text,             -- bullish | bearish
    target_price           numeric,          -- explicit price target, when stated
    magnitude_pct          numeric,          -- stated magnitude, when stated
    horizon_deadline       date,             -- deadline T
    horizon_basis          text,             -- stated | default_30d | default_90d | default_eoy (published conventions)
    stated_confidence      numeric,          -- stated, or imputed: "will"=0.85, "likely"=0.70
    confidence_basis       text,             -- stated | imputed_will | imputed_likely
    conditionality         jsonb,            -- activation condition; null when unconditional
    specificity_class      text not null,    -- direction_only | direction_magnitude | target_deadline | conditional | non_falsifiable
    source_offset_seconds  integer not null, -- second offset into the video; receipt seek point (FR-403, AC-2)
    quote                  text,             -- verbatim quote, <= 15 words (NFR-4)
    uttered_at             timestamptz not null,
    p0_price               numeric,          -- price at utterance

    -- extraction provenance and review state
    extraction_confidence  numeric,          -- pass-2 confidence; below threshold routes to QA (FR-203)
    model_version          text not null,
    prompt_version         text not null,
    reviewer_id            text,             -- set when QA-touched (US-009, NFR-2)
    review_state           text not null default 'unreviewed',  -- unreviewed | approved | corrected | voided
    publishable            boolean not null default false,      -- FR-203: nothing below threshold publishes unreviewed

    -- lifecycle and anti-gaming
    status                 text not null default 'open',  -- open | resolved | void
    dedup_cluster_id       bigint,           -- FR-205: repeats reinforce, not multiply
    embedding              vector(384),      -- semantic-similarity dedup
    flags                  jsonb not null default '{}'::jsonb,  -- sponsor_read (EC-4), hedging (EC-6), diarization_uncertain (EC-5), ...

    created_at             timestamptz not null default now()
);
create index claims_analyst_idx on claims (analyst_id);
create index claims_status_idx on claims (status);
create index claims_asset_idx on claims (asset);
