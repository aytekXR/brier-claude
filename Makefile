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

.PHONY: dev seed test check copy-lint lint typecheck install install-pipeline install-web db-up

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

db-up:
	docker compose up -d db
	@until docker compose exec db pg_isready -U brier -d brier > /dev/null 2>&1; do sleep 1; done

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

check: install copy-lint lint typecheck test
	@echo "make check: all gates green"
