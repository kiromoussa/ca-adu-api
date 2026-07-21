# ADU Atlas API - developer Makefile.
#
# Conventions:
#   - Python targets assume services/api, services/core, and ingestion are on
#     PYTHONPATH (run `pip install -e .` per package, or export
#     PYTHONPATH=$(pwd) - whichever convention the services/ingestion subtrees
#     land on) and their requirements.txt files are already installed. This
#     Makefile does not install anything itself except portal npm deps.
#   - PORTAL_DIR autodetects portal/ (target layout, docs/adr/0001) with a
#     fallback to frontend/ (pre-pivot name) so this Makefile keeps working
#     during the rename without edits.
#   - JURISDICTION defaults to los_angeles (the only v1 target per the product
#     spec); override with `make ingest-la JURISDICTION=san_diego` once other
#     cities are ingested.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PYTHON ?= python3
COMPOSE ?= docker compose
JURISDICTION ?= los_angeles
PORTAL_DIR := $(shell [ -d portal ] && echo portal || echo frontend)

.PHONY: help db-up db-down db-logs migrate api-dev api-build \
        ingest-la ingest-gis-la ingest-code-la ingest-qa-la \
        test test-python test-portal lint lint-python lint-portal \
        fmt openapi-validate docker-build clean

help:
	@echo "ADU Atlas API - make targets"
	@echo "  db-up             start local Postgres/PostGIS (docker compose)"
	@echo "  db-down           stop the local stack"
	@echo "  migrate           apply supabase/migrations/*.sql to \$$SUPABASE_DB_URL"
	@echo "  api-dev           run the FastAPI service locally with autoreload"
	@echo "  ingest-la         run GIS + code ingestion for Los Angeles (v1 target)"
	@echo "  test              run python + portal test suites"
	@echo "  lint              ruff (python) + next lint / tsc (portal)"
	@echo "  fmt               ruff format + ruff --fix"
	@echo "  openapi-validate  validate openapi/openapi.yaml (OpenAPI 3.1)"
	@echo "  docker-build      build both docker images locally"

## --- Local database (postgis/postgis:15-3.4 via docker-compose.yml) -------

db-up:
	$(COMPOSE) up -d db
	@echo "Waiting for local Postgres/PostGIS to report healthy..."
	@until [ "$$($(COMPOSE) ps -q db | xargs -r docker inspect -f '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do \
		sleep 1; \
	done
	@echo "db is up: postgresql://postgres:postgres@localhost:$${LOCAL_DB_PORT:-54329}/postgres"

db-down:
	$(COMPOSE) down

db-logs:
	$(COMPOSE) logs -f db

## --- Schema migrations -----------------------------------------------------
## Applies every file in supabase/migrations/ in filename order (0001, 0002,
## ...) with psql, matching what CI's migration-validation job does against a
## disposable postgis service container. Point SUPABASE_DB_URL at the local
## db-up stack (postgresql://postgres:postgres@localhost:54329/postgres) or at
## a real Supabase project's connection string.

migrate:
	@test -n "$$SUPABASE_DB_URL" || { echo "SUPABASE_DB_URL is not set" >&2; exit 1; }
	@for f in supabase/migrations/*.sql; do \
		echo "applying $$f"; \
		psql "$$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f "$$f"; \
	done

## --- API (services/api) ----------------------------------------------------
## services/api/main.py exposes an ASGI `app` instance, imported as
## services.api.main:app (the same path docker/Dockerfile.api runs). Run from
## the repo root so the `services` package resolves; assumes services/core +
## services/requirements.txt are already installed in the active environment.

api-dev:
	uvicorn services.api.main:app --reload --host 0.0.0.0 --port $${PORT:-8000}

api-build:
	docker build -f docker/Dockerfile.api -t adu-atlas-api .

## --- Ingestion (ingestion/) -------------------------------------------------
## Entrypoint convention (see docker/Dockerfile.ingestion header for the same
## assumption):
##   - GIS: `python -m ingestion.gis.run <source>` (positional source, no
##     --jurisdiction flag; LA City is hardcoded inside ingestion/gis/la_zimas.py).
##   - Code: ingestion/code/run.py uses flat, non-package imports by design, so
##     it must run with ingestion/code/ itself as the working directory:
##     `cd ingestion/code && python run.py <stage> --jurisdiction <slug>`, where
##     stage is one of ingest/extract/validate/all. `validate` is the
##     compliance QA cross-check (there is no separate `ingestion.code.qa`).

ingest-gis-la:
	$(PYTHON) -m ingestion.gis.run all

ingest-code-la:
	cd ingestion/code && $(PYTHON) run.py ingest --jurisdiction $(JURISDICTION) \
		&& $(PYTHON) run.py extract --jurisdiction $(JURISDICTION)

ingest-qa-la:
	cd ingestion/code && $(PYTHON) run.py validate --jurisdiction $(JURISDICTION)

# Full LA v1 pipeline: GIS layers first, then municipal code + offline
# extraction candidates. Run ingest-qa-la separately (it reads the output of
# both and is scheduled after them in render.yaml).
ingest-la: ingest-gis-la ingest-code-la

## --- Tests ------------------------------------------------------------------

test: test-python test-portal

test-python:
	pytest

test-portal:
	@if [ ! -d "$(PORTAL_DIR)" ]; then \
		echo "no portal/ or frontend/ directory found, skipping" >&2; \
	elif node -e "process.exit(require('./$(PORTAL_DIR)/package.json').scripts.test ? 0 : 1)" 2>/dev/null; then \
		cd "$(PORTAL_DIR)" && npm test; \
	else \
		echo "$(PORTAL_DIR)/package.json has no \"test\" script; running typecheck + build instead" >&2; \
		cd "$(PORTAL_DIR)" && npx tsc --noEmit && npm run build; \
	fi

## --- Lint / format ------------------------------------------------------------

lint: lint-python lint-portal

lint-python:
	ruff check services ingestion tests

lint-portal:
	@if [ -d "$(PORTAL_DIR)" ]; then \
		cd "$(PORTAL_DIR)" && npm run lint; \
	else \
		echo "no portal/ or frontend/ directory found, skipping" >&2; \
	fi

fmt:
	ruff format services ingestion tests
	ruff check --fix services ingestion tests

## --- OpenAPI ------------------------------------------------------------------
## openapi-spec-validator supports OpenAPI 3.1 (>=0.7). Installed on demand via
## pipx/uvx so this target works without a persistent dev-dependency install.

openapi-validate:
	@if command -v openapi-spec-validator >/dev/null 2>&1; then \
		openapi-spec-validator openapi/openapi.yaml; \
	elif command -v uvx >/dev/null 2>&1; then \
		uvx --from openapi-spec-validator openapi-spec-validator openapi/openapi.yaml; \
	else \
		echo "openapi-spec-validator not found; install it (pip install openapi-spec-validator) or install uv" >&2; \
		exit 1; \
	fi

## --- Docker -------------------------------------------------------------------

docker-build:
	docker build -f docker/Dockerfile.api -t adu-atlas-api .
	docker build -f docker/Dockerfile.ingestion -t adu-atlas-ingestion .

clean:
	find . -name '__pycache__' -not -path './.venv/*' -not -path './*/node_modules/*' -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
