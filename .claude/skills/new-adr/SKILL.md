---
name: new-adr
description: Create a numbered Architecture Decision Record from the template. Use whenever a change deviates from the PRD, METHODOLOGY, the locked stack, or adds a dependency — approval + ADR are required before the change lands.
---

# new-adr

1. Confirm the deviation actually needs an ADR: new dependency, stack change, scoring-formula change, schema-discipline change, or any departure from `docs/PRD.md` / `docs/METHODOLOGY.md` / the scaffold conventions in `CLAUDE.md`. If it doesn't, say so and stop.
2. Confirm the human has approved the deviation (or ask now). No ADR lands without approval; the ADR records the decision, it does not grant it.
3. Find the next number: `ls docs/adr/` → next `NNNN`.
4. Copy `docs/adr/template.md` to `docs/adr/NNNN-short-kebab-title.md` and fill in Context (cite the PRD section or task ID that forced the decision), Decision, and Consequences. Scoring changes must state the methodology version bump and the recompute plan (FR-304, AC-4).
5. Reference the ADR from the code or doc it affects, and append a LOG.md NOTE line:
   `<UTC timestamp> | <agent> | <task-id> | NOTE | ADR-NNNN: <title> accepted`
