---
name: next-task
description: Pick the highest-priority unblocked task from TASKS.md and drive it to done — log STARTED, restate acceptance criteria, plan, implement, run checks, log DONE, tick the checkbox. Use when asked to "pick up the next task", "continue the backlog", or at the start of an implementation session.
---

# next-task

Drive exactly one TASKS.md task to its definition of done. One task per invocation; do not batch.

## Steps

1. **Pick.** Read `TASKS.md`. Choose the first unchecked task whose dependencies are all checked, scanning epics in order (E1 → E6) and tasks in order within each epic. Cross-check `LOG.md` for an existing STARTED/BLOCKED line on it — if another agent is mid-flight, pick the next eligible task instead.
2. **Log STARTED.** Append to `LOG.md` (UTC, append-only):
   `<UTC timestamp> | <agent> | <task-id> | STARTED | <short note>`
3. **Restate acceptance criteria.** Quote the task's acceptance text from TASKS.md and its PRD references; read the cited PRD/METHODOLOGY sections. If the right owner is another agent per the task's `owner:` field, delegate to that subagent (or HANDOFF and stop).
4. **Plan.** List the files to change, the tests that will prove the acceptance criteria, and any `# TASK: <id>` stub markers being replaced. No new dependencies, no formula changes, no scope creep — those need human approval + an ADR first.
5. **Implement.** Small commits, conventional messages. Replace the task's stubs and remove their `# TASK:` markers. Keep the mock-first and append-only conventions (CLAUDE.md).
6. **Run checks.** `make check` must be green. For pipeline work also confirm `make test`; for web work also run `python3 scripts/copy_lint.py` explicitly.
7. **Log DONE and tick the box.** Append the DONE line stating the verification and modules touched, e.g.
   `<UTC timestamp> | <agent> | <task-id> | DONE | make check green, 23 tests; touched scoring/fas.py, tests/test_fas.py`
   then tick the task's checkbox in TASKS.md. Both or neither — one without the other is a defect.
8. **If stuck**, append a BLOCKED line with the reason (or HANDOFF naming the receiving agent) and stop cleanly; never leave a STARTED line dangling without a terminal line.

## Logging contract (binding for every session and every subagent)

1. Append a STARTED line before touching code for a task. Append DONE only after `make check` is green. Append BLOCKED with the reason when stopping early. Use HANDOFF when passing work to another agent, naming the receiving agent.
2. Every DONE line must state the verification (e.g. "make check green, 14 tests") and the main modules touched.
3. A task counts as complete only when its TASKS.md checkbox AND its LOG.md DONE line both exist and agree. One without the other is a defect.
4. LOG.md is append-only. No edits, no deletions, no reordering. Corrections are new NOTE lines referencing the earlier line.
5. qa-reviewer additionally audits LOG.md against TASKS.md and `git log` every session and files a NOTE line for any mismatch or missing entry.
