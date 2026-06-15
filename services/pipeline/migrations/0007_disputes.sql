-- E5-T3: Additive columns for the disputes table (FR-405, US-006, AC-5, UF-3, NFR-2, NFR-3).
--
-- The disputes table and the corrections public-log table were ALREADY created by
-- 0006_ops.sql using the authoritative column names:
--   disputes : ticket_code, submitted_by, state, sla_deadline,
--              submitted_at, methodology_version_at_publication
--   corrections : id, claim_id, dispute_id, summary,
--                 superseded_resolution_id, superseding_resolution_id, published_at
--
-- This migration is PURELY ADDITIVE: it adds only the two columns that E5-T3
-- intake.py needs beyond what 0006 already provides.  It does NOT rename any
-- column, does NOT remap any value, and does NOT recreate the corrections table.
--
-- New columns:
--   reviewer_id    text        -- set at adjudication time (NFR-2 reproducibility)
--   resolution_id  bigint FK   -- points to the superseding resolution when corrective (NFR-3)

alter table disputes add column if not exists reviewer_id   text;
alter table disputes add column if not exists resolution_id bigint references resolutions(id);
