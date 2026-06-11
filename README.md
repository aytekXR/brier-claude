# Brier

The rating agency for public prediction. Brier extracts falsifiable predictions from the public content of crypto YouTube analysts, resolves each one against subsequent market prices, and publishes a base-rate-corrected accuracy score per analyst — with a clip-level receipt behind every number.

**Proof, not opinion.** Brier publishes statistics about public statements; it never recommends instruments or actions, and the build enforces that (`scripts/copy_lint.py`, PRD AC-7).

## Quickstart (10 minutes)

Prerequisites: Docker Desktop, Node 20+, Python 3.12 (`brew install python@3.12`), GNU make.

```bash
git clone https://github.com/aytekXR/brier-claude.git && cd brier-claude

# 1. Database: Postgres 16 + pgvector, migrations, 3 fixture analysts (~2 min)
make seed

# 2. Web app on http://localhost:3000 (~2 min)
make dev

# 3. The quality gate the whole project lives by (~3 min first run)
make check
```

You should see: the leaderboard listing three fixture analysts at `/`, an analyst shell at `/a/aylin-markets`, a receipt shell at `/r/CLM-1`, and the scoring methodology rendered at `/methodology`.

## Repository map

| Path | What it is |
|---|---|
| `apps/web` | Next.js (App Router, TS strict, Tailwind). Server components; reads via `lib/db.ts`. |
| `services/pipeline` | Python 3.12 pipeline: ingestion → transcription → extraction → resolution → scoring. Plain SQL via psycopg; numbered migrations + tiny runner. |
| `data/fixtures` | Fixture data (3 analysts now; claims/prices/transcripts arrive with E1). |
| `scripts` | `copy_lint.py` — the regulatory firewall, fully implemented; `seed.py`. |
| `docs` | `PRD.md`, `METHODOLOGY.md` (scoring spec), `BRANDKIT.md` (binding brand tokens), `adr/`. |
| `TASKS.md` / `LOG.md` | The backlog subagents execute / the append-only worklog. |
| `.claude` | Four scoped agents + `next-task`, `run-checks`, `new-adr` skills. |

## Status

This is the **skeleton**: complete structure, tooling, schema, and contracts; zero business logic. Every stub carries a `# TASK: <id>` marker pointing at `TASKS.md`. Implementation proceeds task by task — start with `TASKS.md` epic E1 (the walking skeleton on fixtures) via the `next-task` skill.

## Working on Brier

- The gate: **`make check` green + TASKS.md checkbox + LOG.md DONE line** — that triple is the definition of done for every task.
- Conventions, the logging contract, and the firewall: `CLAUDE.md`.
- Deviations from the PRD, methodology, or locked stack: human approval + an ADR (`docs/adr/`), no exceptions.
