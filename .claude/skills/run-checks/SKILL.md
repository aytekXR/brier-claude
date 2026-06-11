---
name: run-checks
description: Run the full quality gate (make check) and summarize any failures with file:line pointers. Use before declaring work done, before commits that close a task, or when asked "are we green?".
---

# run-checks

1. Run `make check` from the repo root. It chains: copy_lint (AC-7 firewall) → ruff lint + format check → mypy → pytest → tsc --noEmit → eslint.
2. If everything passes, report the one-line summary (test count included) — this is the evidence a LOG.md DONE line cites.
3. If anything fails:
   - Summarize each failure as `gate · file:line · what's wrong · smallest correct fix`.
   - copy-lint failures are regulatory, not stylistic: the fix is rewording the copy, never weakening `scripts/copy_lint.py` or sprinkling `copy-lint-ignore` (the marker is reserved for verbatim quoted evidence, with a stated reason).
   - Never silence a gate (no `# type: ignore`, `# noqa`, eslint-disable, or test deletion) to get to green; fix the cause or log BLOCKED.
4. Database-backed tests skip when the dev DB is down; for ledger-touching work run `docker compose up -d db && make seed` first so the append-only trigger tests actually execute.
