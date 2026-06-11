# ADR-0001: Record architecture decisions

- **Status:** accepted
- **Date:** 2026-06-11
- **Deciders:** founding team

## Context

The build is executed across many sessions by humans and scoped subagents. Any deviation from the locked stack, the PRD, or the scoring methodology needs an explicit, reviewable record — the project's credibility rests on "no silent edits" applying to the codebase as much as to the score ledger.

## Decision

Every deviation from `docs/PRD.md`, `docs/METHODOLOGY.md`, the locked stack, or the scaffold prompt requires human approval plus a numbered ADR in `docs/adr/`, created from `template.md`. New dependencies require an ADR. Scoring-formula changes require an ADR and a methodology version bump with full-history recomputation.

## Consequences

Slightly more ceremony for changes; in exchange, every later session can reconstruct why the repository looks the way it does, and the regulatory/methodology posture stays defensible.
