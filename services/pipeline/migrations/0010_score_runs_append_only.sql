-- ============================================================================
-- score_runs MUTABILITY NARROWED (NFR-3 hardening; launch-readiness audit A2#8).
--
-- score_runs is intentionally NOT a fully append-only ledger: _finish_score_run
-- (scoring/fas.py) issues `update score_runs set finished_at = now()` to stamp a
-- run complete. Every OTHER column (methodology_version, started_at, trigger,
-- notes, id) is write-once: it must never change after insert, and a run row
-- must never be deleted — the retained prior-run archive is what makes a
-- methodology recompute auditable (AC-4, HP-6). The prior schema left those
-- columns unprotected; only resolutions and scores carried a mutation guard
-- (0005_ledger.sql), so a stray UPDATE/DELETE on score_runs would have silently
-- rewritten ledger history.
--
-- This trigger closes that gap: an UPDATE is allowed only when it changes
-- nothing but finished_at; any other column change, and any DELETE, raises.
-- Purely additive and idempotent (create-or-replace + drop-if-exists). It does
-- not change the existing finished_at stamp, any scored value, or the
-- methodology. Do not drop or disable it outside a reviewed ADR.
-- ============================================================================

create or replace function forbid_score_runs_mutation() returns trigger
language plpgsql as $$
begin
    if tg_op = 'DELETE' then
        raise exception
            'append-only ledger: score_runs rows are never deleted; the prior-run archive must stay queryable (NFR-3)';
    end if;
    -- UPDATE: finished_at may be stamped; every other column is immutable.
    if new.id is distinct from old.id
       or new.methodology_version is distinct from old.methodology_version
       or new.started_at is distinct from old.started_at
       or new.trigger is distinct from old.trigger
       or new.notes is distinct from old.notes then
        raise exception
            'append-only ledger: score_runs columns other than finished_at are immutable; append a new run instead (NFR-3)';
    end if;
    return new;
end;
$$;

drop trigger if exists score_runs_append_only on score_runs;
create trigger score_runs_append_only
    before update or delete on score_runs
    for each row execute function forbid_score_runs_mutation();
