# Brier — development glue. Definition of done for any task: `make check` green
# + TASKS.md checkbox + LOG.md DONE line.
#
# A `pipeline-demo` target (fixtures -> FakeExtractor -> resolution -> scoring
# -> leaderboard) arrives with task E1-T1; it is intentionally absent here.

SHELL := /bin/bash
PIPELINE := services/pipeline
VENV := $(PIPELINE)/.venv
PY := $(VENV)/bin/python
WEB := apps/web

.PHONY: dev seed test check copy-lint lint typecheck install install-pipeline install-web db-up pipeline-demo handler-demo web-build coverage ci

# ---------- setup ----------

# The pipeline is Python 3.12 (locked stack); prefer the versioned binary.
BOOTSTRAP_PY := $(shell command -v python3.12 || command -v python3)

$(VENV)/bin/python:
	$(BOOTSTRAP_PY) -m venv $(VENV)
	$(PY) -m pip install --quiet --upgrade pip

install-pipeline: $(VENV)/bin/python
	$(PY) -m pip install --quiet -e "$(PIPELINE)[dev]"

$(WEB)/node_modules/.install-stamp: $(WEB)/package.json
	cd $(WEB) && npm install --no-audit --no-fund
	touch $@

install-web: $(WEB)/node_modules/.install-stamp

install: install-pipeline install-web

# ---------- dev loop ----------

# Bring up the dev database. Locally this starts the docker-compose Postgres.
# In CI a Postgres *service container* is already running, so setting
# BRIER_DB_EXTERNAL=1 makes this a no-op (and seed/pipeline-demo then run
# against the service DB without invoking docker compose).
db-up:
	@if [ -z "$$BRIER_DB_EXTERNAL" ]; then \
		docker compose up -d db; \
		until docker compose exec db pg_isready -U brier -d brier > /dev/null 2>&1; do sleep 1; done; \
	else \
		echo "db-up: BRIER_DB_EXTERNAL set — using external Postgres, skipping docker compose"; \
	fi

dev: db-up install-web
	cd $(WEB) && npm run dev

seed: db-up install-pipeline
	$(PY) $(PIPELINE)/migrations/migrate.py
	$(PY) scripts/seed.py

# ---------- quality gates ----------

copy-lint:
	python3 scripts/copy_lint.py

lint: install
	$(VENV)/bin/ruff check $(PIPELINE) scripts
	$(VENV)/bin/ruff format --check $(PIPELINE) scripts
	cd $(WEB) && npm run lint

typecheck: install
	$(VENV)/bin/mypy --config-file $(PIPELINE)/pyproject.toml $(PIPELINE)/brier_pipeline scripts
	cd $(WEB) && npx tsc --noEmit

test: install-pipeline
	cd $(PIPELINE) && .venv/bin/python -m pytest -q

pipeline-demo: db-up install-pipeline
	$(PY) -m brier_pipeline.demo

# Shows the transcribe + extract job handlers running end to end on the fixture
# fakes (real worker dispatch path), then the EC-3/AC-7/FR-203 extract gates.
# Runs in a rolled-back transaction — the dev DB is left unchanged.
handler-demo: db-up install-pipeline
	$(PY) -m brier_pipeline.handler_demo

# Production Next.js build. tsc/eslint (in `check`) do not catch build-time
# failures in server components or the OG image routes — `next build` does.
# Offline-safe: the build reads only local data + fixtures (no network).
web-build: install-web
	cd $(WEB) && npm run build

check: install copy-lint lint typecheck test
	@echo "make check: all gates green"

# Coverage gate (ADR-0015, Track T3). Kept SEPARATE from `make check` so the
# fast gate stays instrumentation-free. Needs the dev DB up + seeded so the
# DB-backed suite RUNS (skipped tests would make the measurement meaningless);
# `coverage report` exits non-zero under the fail_under floor in pyproject.toml.
coverage: db-up install-pipeline
	cd $(PIPELINE) && .venv/bin/coverage run -m pytest -q
	cd $(PIPELINE) && .venv/bin/coverage report
	@echo "make coverage: line coverage at or above the ADR-0015 floor"

# Full launch-style verification — exactly what .github/workflows/ci.yml runs:
# migrate+seed, the full gate (DB-backed tests included), the coverage floor
# (ADR-0015), the end-to-end demo (canonical board), and the production web
# build. Locally needs the dev DB (run via `sg docker -c 'make ci'` on the VPS);
# in CI db-up is a no-op.
ci: seed check coverage pipeline-demo web-build
	@echo "make ci: full gate + coverage floor + end-to-end demo + web build all green"
