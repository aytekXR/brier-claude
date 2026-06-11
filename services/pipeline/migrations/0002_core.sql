-- Core ingestion tables: analyst registry, video metadata, transcript pointers.

-- FR-101: analyst registry. Scope lock: crypto YouTube analysts only.
create table analysts (
    id                 bigint generated always as identity primary key,
    channel_id         text not null unique,        -- YouTube channel ID (official API)
    display_name       text not null,
    slug               text not null unique,        -- /a/[slug] page path
    status             text not null default 'active',  -- active | paused | removed
    jurisdiction_flag  text,                        -- legal posture note (no Turkey-domiciled subjects)
    created_at         timestamptz not null default now()
);

-- FR-102/FR-104: video metadata via the official Data API.
-- NFR-4: no raw video is ever hosted; playback is official embeds only.
create table videos (
    id                 bigint generated always as identity primary key,
    analyst_id         bigint not null references analysts(id),
    youtube_video_id   text not null unique,
    title              text not null,
    published_at       timestamptz not null,
    duration_seconds   integer,
    source_status      text not null default 'live',  -- live | deleted | private (EC-1: claims persist, deletion is flagged)
    sponsor_segments   jsonb,                         -- EC-4: claims inside sponsor reads are excluded from scoring
    created_at         timestamptz not null default now()
);
create index videos_analyst_idx on videos (analyst_id);

-- FR-103: transcript metadata + storage pointer. The transcript body (with
-- second-level offsets) lives in object storage; audio is transient with a
-- 30-day TTL and is never referenced from the schema.
create table transcripts (
    id                 bigint generated always as identity primary key,
    video_id           bigint not null references videos(id),
    source             text not null,               -- captions | whisper | deepgram
    storage_pointer    text not null,               -- Storage adapter key
    language           text,
    quality_note       text,                        -- captions are draft quality; verify offsets (PRD §20)
    created_at         timestamptz not null default now(),
    unique (video_id, source)
);
