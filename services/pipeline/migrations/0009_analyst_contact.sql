-- AC-5 / UF-3: analyst contact for adjudication notification.
--
-- This migration is PURELY ADDITIVE and IDEMPOTENT:
--   - uses "add column if not exists"
--   - the analysts table is mutable working state (NOT an append-only ledger),
--     so adding a nullable column touches no NFR-3 trigger and no scored schema.
--
-- notify_email is the optional contact address used by record_adjudication to
-- notify an analyst when a dispute referencing their published claim is
-- adjudicated (PRD UF-3 / HP-5: "analyst notified").  It is null for the many
-- public analysts whose contact email is unknown; the notification is then a
-- no-op.  Population is part of roster ingest (import-roster) or manual entry.

alter table analysts add column if not exists notify_email text;

comment on column analysts.notify_email is
  'Optional contact email for AC-5/UF-3 adjudication notices; null when unknown.';
