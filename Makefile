# SolarReach — Project 1 task runner.
# Each target is wired so the canonical demo flow is a single sequence of
# `make` calls. Override MONGO_URI etc. via env or `.env`.
#
# Demo path (as in README.md):
#   make up           # start mongo, run init scripts
#   make ingest-lr CCOD=… OCOD=…
#   make ingest-inspire GML_DIR=…
#   make seed
#   make match-inspire
#   make test

SHELL := /usr/bin/env bash

PYTHON       ?= python3
PIP          ?= $(PYTHON) -m pip
MONGO_URI    ?= mongodb://solarreach_app:change-me-in-prod@localhost:27017/solarreach?authSource=admin
SEED_COUNT   ?= 250
SEED         ?= 42

.PHONY: help install dev install-prod install-dev install-agent up down logs \
        ingest-lr ingest-inspire match-inspire seed seed-fresh \
        agent agent-resume \
        test test-quick lint typecheck format clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	awk -F: '{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$3}' | sed 's/##//'

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------
install: install-dev ## Install package in editable mode with dev extras

install-prod: ## Install runtime deps only
	$(PIP) install -e .

install-dev: ## Install runtime + dev deps (pytest, ruff, mypy)
	$(PIP) install -e '.[dev]'

install-agent: ## Install the deepagents + langchain-mongodb stack
	$(PIP) install -e '.[agent]'

# ---------------------------------------------------------------------------
# Mongo lifecycle
# ---------------------------------------------------------------------------
up: ## Start mongo via docker-compose; init scripts run on first boot
	docker compose up -d mongo
	@echo "waiting for mongo to be ready..."
	@for i in $$(seq 1 30); do \
	  docker compose exec -T mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; \
	  sleep 1; \
	done
	@echo "mongo is up."

down: ## Stop mongo (data volume kept)
	docker compose down

logs: ## Tail mongo logs
	docker compose logs -f mongo

# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------
# Provide CCOD / OCOD as args, e.g. `make ingest-lr CCOD=/data/CCOD_FULL_2026_04.csv`
ingest-lr: ## Ingest Land Registry CCOD/OCOD (requires CCOD= and/or OCOD=)
	@if [ -z "$(CCOD)" ] && [ -z "$(OCOD)" ]; then \
	  echo "ERROR: pass CCOD=path/to/CCOD.csv and/or OCOD=path/to/OCOD.csv"; exit 2; \
	fi
	$(PYTHON) scripts/ingest_land_registry.py \
	  --mongo-uri "$(MONGO_URI)" \
	  $(if $(CCOD),--ccod $(CCOD)) \
	  $(if $(OCOD),--ocod $(OCOD)) \
	  -v

# Provide GML_DIR, e.g. `make ingest-inspire GML_DIR=/data/inspire/extracted`
ingest-inspire: ## Ingest INSPIRE polygons from a directory of .gml files
	@if [ -z "$(GML_DIR)" ]; then \
	  echo "ERROR: pass GML_DIR=path/to/extracted/inspire/dir"; exit 2; \
	fi
	$(PYTHON) scripts/ingest_inspire.py \
	  --mongo-uri "$(MONGO_URI)" \
	  --gml-dir "$(GML_DIR)" \
	  --bbox $(or $(BBOX),london) \
	  -v

match-inspire: ## Snap leads to nearest plausible INSPIRE polygon
	$(PYTHON) scripts/match_leads_to_inspire.py \
	  --mongo-uri "$(MONGO_URI)" -v

# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------
seed: ## Generate the deterministic 250-lead demo set
	$(PYTHON) scripts/seed.py \
	  --mongo-uri "$(MONGO_URI)" \
	  --seed $(SEED) \
	  --count $(SEED_COUNT) \
	  -v

seed-fresh: ## Wipe demo client leads first, then re-seed
	$(PYTHON) scripts/seed.py \
	  --mongo-uri "$(MONGO_URI)" \
	  --seed $(SEED) --count $(SEED_COUNT) --fresh -v

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
# Pass BATCH=N (default 5) and CLIENT=slug (default greensolar).
agent: ## Run the Lead Researcher agent on a batch of unscored leads
	MONGO_URI="$(MONGO_URI)" \
	$(PYTHON) scripts/run_lead_agent.py \
	  --client-slug $(or $(CLIENT),client-greensolar-uk) \
	  --batch-size $(or $(BATCH),5) \
	  -v

# Resume a run by passing THREAD=<thread_id>
agent-resume: ## Resume an agent run from its thread_id
	@if [ -z "$(THREAD)" ]; then \
	  echo "ERROR: pass THREAD=<thread_id> from the previous run output"; exit 2; \
	fi
	MONGO_URI="$(MONGO_URI)" \
	$(PYTHON) scripts/run_lead_agent.py \
	  --client-slug $(or $(CLIENT),client-greensolar-uk) \
	  --thread-id $(THREAD) -v

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------
test: ## Run the full test suite
	PYTHONPATH=packages/shared/py:packages/scoring:packages/agents $(PYTHON) -m pytest

test-quick: ## Run only the financial maths tests
	PYTHONPATH=packages/shared/py:packages/scoring:packages/agents $(PYTHON) -m pytest tests/test_financial.py -v

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff format .

typecheck:
	$(PYTHON) -m mypy packages

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
