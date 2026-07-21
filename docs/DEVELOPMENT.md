# ADU Atlas API - local development

End-to-end local workflow for the deterministic feasibility API: bring up
PostGIS, apply the schema, seed data, run the FastAPI service, run the tests,
and call `POST /v1/feasibility`. Every command below maps to a file that exists
in this repo (`docker-compose.yml`, `Makefile`, `supabase/migrations/`,
`supabase/seed_baselines.sql`, `services/`, `ingestion/`, `tests/integration/`).

No LLM runs on the request path. Everything here is deterministic rules +
PostGIS + source-linked data.

## 1. Prerequisites

- Docker (for the local Postgres/PostGIS container).
- Python 3.12 and pip.
- The `psql` client (used by `make migrate` and the integration tests to apply
  SQL files). On macOS: `brew install libpq` then add its `bin` to `PATH`, or
  `brew install postgresql@15`.
- Node 20 + npm only if you also work on the portal (`portal/`).

Install the Python dependencies (the single shared manifest for `services/api`
and `services/core`):

```bash
pip install -r services/requirements.txt
# Optional, only if you run ingestion or the pre-pivot test suite:
pip install -r ingestion/gis/requirements.txt
pip install -r ingestion/code/requirements.txt
pip install -r tests/requirements-dev.txt
```

## 2. Environment

```bash
cp .env.example .env
```

The only variable the API strictly needs locally is `SUPABASE_DB_URL`. The
default in `.env.example` points at the local docker-compose database:

```
SUPABASE_DB_URL=postgresql://postgres:postgres@localhost:54329/postgres
```

Export it into your shell so `make migrate` and `make api-dev` can see it:

```bash
export SUPABASE_DB_URL=postgresql://postgres:postgres@localhost:54329/postgres
```

Secrets (`SUPABASE_SERVICE_ROLE_KEY`, `AZURE_OPENAI_*`, RapidAPI values) come
from the environment and are never hardcoded. None are required just to run the
request path locally.

## 3. Start the local database

The repo-root `docker-compose.yml` defines a `db` service
(`postgis/postgis:15-3.4`) on host port 54329:

```bash
make db-up            # docker compose up -d db, then waits for healthcheck
# optional table/geometry inspector at http://localhost:8081
docker compose --profile tools up -d adminer
```

Stop it with `make db-down`.

## 4. Create the Supabase auth roles (one-time, local only)

The RLS policies in `supabase/migrations/0002_rls.sql` and
`supabase/migrations/0006_rls_indexes.sql` grant to the Supabase roles
`anon`, `authenticated`, and `service_role`. A hosted Supabase project already
has these; a vanilla PostGIS container does not, so create them once before the
first `make migrate` (idempotent - safe to re-run):

```bash
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 <<'SQL'
do $$
begin
  if not exists (select from pg_roles where rolname = 'anon') then
    create role anon;
  end if;
  if not exists (select from pg_roles where rolname = 'authenticated') then
    create role authenticated;
  end if;
  if not exists (select from pg_roles where rolname = 'service_role') then
    create role service_role;
  end if;
end
$$;
SQL
```

## 5. Apply migrations

`make migrate` applies every file in `supabase/migrations/` in filename order
(0001 -> 0006), exactly like the CI migration-validation job:

```bash
make migrate
```

This drops the pre-pivot scraper tables and creates the 16-table ADU Atlas
schema with PostGIS geometry columns, GIST + B-tree indexes, and RLS.

## 6. Seed baselines and jurisdictions

The California state-law baselines and the 8 target jurisdictions live in
`supabase/seed_baselines.sql` (not a migration - apply it separately):

```bash
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f supabase/seed_baselines.sql
```

After this, `state_rule_baselines` is fully populated and Los Angeles exists
with `coverage_status = 'ingesting'`; the other seven cities are `planned`.
Do NOT apply `supabase/seed.sql` - that is a leftover from the pre-pivot
product and references dropped tables.

## 7. Ingest Los Angeles (optional; hits the network)

LA is the only v1 target. Its parcels, zoning, and overlays come from ArcGIS
(ZIMAS, FEMA NFHL, CAL FIRE) and its rules from American Legal. This step needs
the ingestion requirements installed (step 1) and network access:

```bash
make ingest-la        # ingest-gis-la then ingest-code-la
make ingest-qa-la     # state-baseline QA cross-check
```

A city stays `ingesting` until its sources + rules are ingested, tested, and
verified; only then is it manually promoted to `production` (the only status
that returns a billable feasibility result). Until LA is `production`,
`POST /v1/feasibility` for an LA address returns `422 unsupported_coverage`.

If you just want a working end-to-end request without running ingestion, the
integration suite (step 9) seeds a synthetic, self-consistent LA fixture and a
production LA jurisdiction for you.

## 8. Run the API

```bash
make api-dev          # uvicorn services.api.main:app --reload on :8000
```

- Interactive docs: http://localhost:8000/docs
- Generated OpenAPI: http://localhost:8000/openapi.json
- Authored spec (source of truth): `openapi/openapi.yaml`
  (`make openapi-validate` checks it against OpenAPI 3.1).

Health check (no auth):

```bash
curl -s http://localhost:8000/v1/health | python3 -m json.tool
```

## 9. Run the tests

### Unit tests (fakes, no database, no network)

The `services/tests` suite drives the deterministic core and the RapidAPI /
metering logic through in-memory fakes:

```bash
pytest services/tests -q
```

### Integration tests (real PostGIS, real migrations, real app)

`tests/integration/` applies every migration, seeds a tiny LA fixture, and
drives `POST /v1/feasibility` and the metadata endpoints through FastAPI's
TestClient with a deterministic (network-free) geocoder. It uses its own
isolated, ephemeral database on port 54330 (kept separate from your dev data on
54329):

```bash
docker compose -f tests/integration/docker-compose.yml up -d
pytest tests/integration -v
docker compose -f tests/integration/docker-compose.yml down
```

The suite reads `ADU_TEST_DB_URL` (default
`postgresql://postgres:postgres@localhost:54330/postgres`) and SKIPS itself
cleanly when `psql`, psycopg, or the test database is unavailable - so a plain
`pytest` from a machine without the test DB still passes (as skips). It never
touches `SUPABASE_DB_URL`.

Run everything Python at once:

```bash
pytest -q            # collects services/tests, tests/, and tests/integration
```

## 10. Call POST /v1/feasibility with curl

Authenticate with a direct API key via the `X-API-Key` header (the raw key is
sha256-hashed server-side; any non-empty string works locally and maps to the
BASIC plan):

```bash
curl -s -X POST http://localhost:8000/v1/feasibility \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: dev-local-key' \
  -d '{
        "address": "1234 S Main St, Los Angeles, CA 90015",
        "project_type": "detached_adu",
        "target_sqft": 800,
        "bedrooms": 1,
        "proposed_height_ft": 16,
        "options": { "near_transit": false }
      }' | python3 -m json.tool
```

What to expect, depending on your local data state:

- Bare DB (only `seed_baselines.sql`, LA still `ingesting`):
  `422 unsupported_coverage` - registered but not production, and not billed.
- After `make ingest-la` and promoting LA to `production`, or against the
  integration fixture: a `200` with a terminal `feasibility_status`
  (`likely_feasible` / `likely_constrained` / `needs_professional_review` /
  `insufficient_data`), per-field source provenance, the state-baseline
  compliance surface, overlay findings, and the verbatim disclaimer. The
  `X-Billable` response header is `true` for a first completed analysis and
  `false` when served from the 24h dedupe cache.

The API never returns a permit approval or a legal yes/no; it returns a
preliminary `feasibility_status` and always includes the disclaimer verbatim.

Other read-only endpoints (all support the same `X-API-Key`; `/v1/health` needs
no auth):

```bash
curl -s http://localhost:8000/v1/jurisdictions -H 'X-API-Key: dev-local-key'
curl -s "http://localhost:8000/v1/jurisdictions/los_angeles/rules" -H 'X-API-Key: dev-local-key'
curl -s http://localhost:8000/v1/changelog -H 'X-API-Key: dev-local-key'
```

## 11. Lint, format, and OpenAPI validation

```bash
make lint             # ruff check (python) + portal lint
make fmt              # ruff format + ruff --fix
make openapi-validate # validate openapi/openapi.yaml (OpenAPI 3.1)
```

CI (`.github/workflows/ci.yml`) runs the same: ruff lint + format check,
`pytest -q`, migration validation on a disposable PostGIS service, and
OpenAPI validation.
