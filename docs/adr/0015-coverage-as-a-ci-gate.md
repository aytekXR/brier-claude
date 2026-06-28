# ADR-0015: Line coverage as a permanent CI gate (coverage[toml])

- **Status:** accepted (approved by the human owner 2026-06-28; Track T3)
- **Date:** 2026-06-28
- **Deciders:** human owner (approved 2026-06-28) + orchestrator (Track T hardening)

## Context

Track T3 (`next-prompt.md`) calls for making test coverage a permanent,
CI-reported gate so a future change that drops the safety net fails the build
loudly instead of drifting unnoticed. An ephemeral measurement on 2026-06-22 put
pipeline **line coverage at 90%** (3208 statements, 331 missed; lowest modules
`demo.py` 59%, `registry.py` 81%, `poller.py` 84%, `youtube.py` 87%). Nothing in
the repo measures or enforces this today — `coverage`/`pytest-cov` are absent.

The stack is **locked** (CLAUDE.md): no new dependency lands without human
approval and an ADR. Measuring coverage requires one dev-only dependency.

## Decision

Add **`coverage[toml]`** (Ned Batchelder's `coverage.py`, TOML-config flavour) as
a **pipeline dev extra only** (`[project.optional-dependencies].dev`). It is not a
runtime dependency, ships nothing to production, and is already a transitive-free,
pure-Python, widely-vendored tool. We deliberately choose plain `coverage` over
`pytest-cov` to keep the pytest invocation in `make check` unchanged (the gate
stays fast and instrumentation-free); coverage runs as a **separate `make
coverage` target**.

- `[tool.coverage.run]` measures `source = ["brier_pipeline"]`, **line** coverage
  (matching the documented baseline; branch coverage is a future ratchet).
- `[tool.coverage.report]` sets `fail_under` to the floor below (the measured
  baseline, rounded down to leave a one-run buffer) and `show_missing = true`.
- `make coverage` runs `coverage run -m pytest` then `coverage report` and **exits
  non-zero under the floor**. CI runs it as a dedicated step after `make check`.
- The floor is a **ratchet**: it starts at the committed baseline and only ever
  moves up. Lowering it requires a follow-up ADR note.
- `make check` (the fast gate) is unchanged — coverage instrumentation would slow
  it and the two concerns are kept separate, exactly as `next-prompt` T3 specifies.

## Consequences

- One dev-only dependency; CI install footprint grows by a single pure-Python
  package. Production and the locked runtime dependency set are untouched.
- A change that removes or guts tests, or adds substantial unexercised code, fails
  CI at the coverage step instead of silently lowering the safety net.
- The floor is honest and enforceable: `make coverage` is reproducible locally and
  in CI, and the number is reported on every push.
- `demo.py` (an end-to-end illustrative harness) is included in the measurement
  rather than omitted, so the gate reflects all shipped pipeline code; the demo
  path is exercised by `make pipeline-demo` in `make ci`.
- Future hardening can flip `branch = true` and ratchet the floor upward; both are
  one-line changes behind this ADR.
