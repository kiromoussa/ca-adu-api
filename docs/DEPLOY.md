# Deploy Runbook

Ordered end-to-end deploy for the **ADU Atlas API** (the deterministic,
source-cited California ADU/JADU/SB 9 feasibility API - see
`docs/PRODUCT_SPEC.md` and `docs/adr/0001-architecture.md`). Follow the steps
in order: each layer depends on the one before it (database -> request-path API
-> ingestion workers that fill it -> portal that documents it -> RapidAPI
listing that sells it).

Per-component detail lives alongside the code: `docker/Dockerfile.api` and
`docker/Dockerfile.ingestion` (header comments document the exact entrypoint
contract), `portal/README.md`, `docs/rapidapi/` (the RapidAPI Hub listing
copy package).

## Conventions

- `SUPABASE_SERVICE_ROLE_KEY` and every LLM/API key are secrets: read from the
  environment only, marked `sync: false` in `render.yaml`, never committed.
- `.env.example` at the repo root is the full variable reference for every
  component (`services/api`, ingestion, portal). Copy it to `.env` for local
  development: `cp .env.example .env`.
- The request path (`POST /v1/feasibility`) is deterministic - no LLM. LLM
  calls happen only in the offline `adu-atlas-ingest-code` cron worker
  (extraction candidates, never auto-verified). Nothing in this runbook should
  change that.
- Do a full pass against a staging Supabase project / a Render + Vercel
  preview before repeating it against production.

## Prerequisites

- CLIs: `supabase`, `vercel` (or the dashboards). Render is dashboard-gated for
  the initial Blueprint connect (see Step 2).
- Node 20+ and Python 3.12 locally if you want to run the test suites or a
  local dry run before deploying (`make api-dev`, `make test`).
- Accounts/keys ready: a Supabase project, a Render account, a Vercel account,
  a RapidAPI developer account, and a registered domain if you want a custom
  API host instead of Render's default `*.onrender.com`.

## Step 1 - Database (Supabase)

Schema is fully authored: `supabase/migrations/0001_initial_schema.sql`
through `0006_rls_indexes.sql`, including `0004_enable_postgis.sql` (PostGIS
3.3+) and `0005_adu_atlas_schema.sql` (the ADU Atlas tables - `parcels`,
`zoning_districts`, `overlay_features`, `zoning_sections`, `zoning_rules`,
`rule_attributes`, `state_rule_baselines`, `qa_issues`, `property_analyses` -
see that file for exact columns).

```bash
# Link the CLI to the target project.
supabase link --project-ref <project-ref>

# Apply every migration in supabase/migrations/ in filename order.
supabase db push
# equivalently, against any Postgres connection string directly:
#   make migrate   # SUPABASE_DB_URL must be set; runs each file with psql
```

If migrations are already applied against this project (re-running this
runbook, or connecting a service to an existing project), skip straight to
confirming connectivity:

```bash
psql "$SUPABASE_DB_URL" -c "select postgis_full_version();"
psql "$SUPABASE_DB_URL" -c "select to_regclass('public.property_analyses') is not null as ok;"
```

Auth is not used for v1 (no Supabase Auth-gated endpoints; RapidAPI/direct API
keys handle caller identity - see `services/api/rapidapi.py`), so there is no
`site_url` / redirect URL configuration step here.

## Step 2 - API + ingestion workers (Render)

Blueprint: root `render.yaml` provisions four services from the two Docker
images in `docker/`:

| Service | Type | Image | Purpose |
|---|---|---|---|
| `adu-atlas-api` | web | `docker/Dockerfile.api` | `POST /v1/feasibility` + read-only metadata endpoints. Deterministic, no LLM. |
| `adu-atlas-ingest-gis` | cron (Mon 03:00 UTC) | `docker/Dockerfile.ingestion` | LA parcels/zoning, FEMA flood, CAL FIRE FHSZ -> `parcels`, `zoning_districts`, `overlay_features`. |
| `adu-atlas-ingest-code` | cron (Mon 04:30 UTC) | `docker/Dockerfile.ingestion` | LAMC sections + offline LLM extraction candidates -> `zoning_sections`, `zoning_rules`, `rule_attributes`. |
| `adu-atlas-qa-crosscheck` | cron (Mon 06:00 UTC) | `docker/Dockerfile.ingestion` | Baselines vs. extracted rules -> `qa_issues`. Runs last so it reads the current week's ingestion output. |

1. **Connect the Blueprint** (dashboard-gated - Render must install its GitHub
   App on the repo; this step cannot be scripted headlessly): Render
   Dashboard -> New -> Blueprint -> connect `github.com/kiromoussa/ca-adu-api`.
   Render detects `render.yaml` and proposes all four services.
2. **Set every `sync: false` secret once**, per service, in the dashboard:
   - `adu-atlas-api`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
     `SUPABASE_DB_URL`, `RAPIDAPI_PROXY_SECRET` (only if RapidAPI's gateway is
     configured to send `X-RapidAPI-Proxy-Secret`; leave unset otherwise -
     `services/api/rapidapi.py` skips that check when it is unset),
     `GOOGLE_MAPS_GEOCODING_API_KEY` / `MAPBOX_ACCESS_TOKEN` (optional
     geocoder-fallback keys; `GEOCODER_PROVIDER=census` and `WEB_CONCURRENCY=2`
     already ship as plain `value:` entries in `render.yaml`, not secrets).
   - `adu-atlas-ingest-gis`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
   - `adu-atlas-ingest-code`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, plus
     exactly one LLM provider - either `ANTHROPIC_API_KEY`, or the
     `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` /
     `AZURE_OPENAI_DEPLOYMENT` / `AZURE_OPENAI_API_VERSION` quartet.
   - `adu-atlas-qa-crosscheck`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
     `SLACK_WEBHOOK_URL`, `HCD_APR_DATASET_URL`, and the same LLM provider
     vars as `adu-atlas-ingest-code`.
3. **Deploy `adu-atlas-api`** and confirm the health check passes: Render's
   `healthCheckPath: /v1/health` (declared in `render.yaml`) must return 200
   before the service is marked live. Watch the deploy logs for the same
   `docker build -f docker/Dockerfile.api -t adu-atlas-api .` your local
   `make api-build` runs.
4. **Trigger one manual run of `adu-atlas-ingest-gis` first** (Render dashboard
   -> service -> "Trigger Run"), since the API needs `parcels` and
   `zoning_districts` populated for LA City before `/v1/feasibility` can
   resolve a real address. Confirm rows land: `select count(*) from parcels;`
   and `select count(*) from zoning_districts;`.
5. Trigger `adu-atlas-ingest-code` next, then `adu-atlas-qa-crosscheck` - or
   just wait for their staggered Monday schedule (03:00 -> 04:30 -> 06:00 UTC)
   now that the Blueprint is live. All three crons have `autoDeploy: false`, so
   a new ingestion image is only rolled out when you intentionally redeploy
   that service, not on every push to `main`.
6. Note the API's Render URL (`https://adu-atlas-api.onrender.com` or your
   custom domain once mapped) - the portal and the RapidAPI listing both need
   it.

Local dry run before touching Render (optional, requires the local Postgres
stack):

```bash
cp .env.example .env      # fill in SUPABASE_DB_URL etc.
make db-up                # local PostGIS via docker-compose
make migrate               # applies supabase/migrations/*.sql locally
make api-dev                # uvicorn --reload against services.api.main:app
make ingest-gis-la           # python -m ingestion.gis.run all
```

## Step 3 - Developer portal (Vercel)

Config: `portal/vercel.json` (framework `nextjs`, `npm install` / `npm run
build` / `.next` output). Reference: `portal/README.md`.

1. In the Vercel dashboard, import the repo and set **Root Directory =
   `portal`**.
2. Enable the project setting **"Include source files outside of the Root
   Directory in the Build Step"** (Project Settings -> General -> Root
   Directory). The portal reads `../config/plans.yaml`,
   `../config/jurisdictions.yaml`, and `../config/sources.yaml` directly at
   build/request time (no hardcoded pricing or coverage claims); without this
   setting those files are outside Vercel's upload and the build fails.
   `portal/next.config.js` already sets `outputFileTracingRoot` to the repo
   root to match.
3. Set environment variables (Production, and Preview with the same or a
   staging value) per `portal/.env.example`:
   - `NEXT_PUBLIC_API_BASE_URL` - the Render API URL from Step 2 (no trailing
     slash), e.g. `https://adu-atlas-api.onrender.com`. Powers the live
     OpenAPI spec on `/docs` and the live entries on `/changelog`; both
     degrade gracefully (bundled fallback spec / empty state) if unset or
     unreachable.
   - `NEXT_PUBLIC_RAPIDAPI_URL` - the RapidAPI listing URL from Step 4 below
     (the "Get API key on RapidAPI" call to action on every page).
4. Deploy:

```bash
cd portal
vercel link            # first time only, links to the Vercel project
vercel                  # preview deploy
vercel --prod           # production deploy
```

5. Confirm `/`, `/coverage`, `/docs`, `/pricing`, and `/changelog` all return
   200 and that `/coverage` and `/pricing` reflect `config/jurisdictions.yaml`
   and `config/plans.yaml` (not hardcoded copy).

## Step 4 - RapidAPI listing

Reference: `docs/rapidapi/LISTING.md` (exact copy package - title, short/long
description, category), `docs/rapidapi/PRICING.md` (plan tiers - must match
`config/plans.yaml` verbatim; update the doc if the config changes, not the
other way around), `docs/rapidapi/RESPONSE_EXAMPLES.md` (sample
request/response bodies for the listing's example calls), and
`docs/rapidapi/FAQ.md`.

1. In the RapidAPI provider dashboard, add a new API pointing at the Render
   API's base URL from Step 2, using `openapi/openapi.yaml` (or the live
   `{NEXT_PUBLIC_API_BASE_URL}/openapi.json` FastAPI serves) to define the
   endpoints.
2. Copy each section of `docs/rapidapi/LISTING.md` verbatim into the matching
   Hub form field. No emojis, no em dashes (hyphen only) - the listing copy is
   already written that way; do not "improve" it in transit.
3. Configure plan tiers from `config/plans.yaml` (`plans.*.monthly_quota`,
   `plans.*.rate_limit_per_minute`, `plans.*.rapidapi_plan_slug`) matching
   `docs/rapidapi/PRICING.md`.
4. If RapidAPI's gateway is configured to inject a shared proxy secret, set the
   same value in RapidAPI's dashboard and in Render's `RAPIDAPI_PROXY_SECRET`
   for `adu-atlas-api` (Step 2). `services/api/rapidapi.py` only enforces the
   check when that secret is configured server-side.
5. Take the resulting listing URL and set it as `NEXT_PUBLIC_RAPIDAPI_URL` in
   Vercel (Step 3), redeploying the portal.

## Step 5 - Smoke test

Confirm the full path end to end against the deployed API. This calls
`POST /v1/feasibility` directly with a bare `X-API-Key` header (bypasses the
RapidAPI gateway, resolved as a `direct`-plan caller by
`services/api/rapidapi.py` - fine for a deploy smoke test; real consumers
authenticate through RapidAPI's `X-RapidAPI-Key` / `X-RapidAPI-Host` headers
instead).

```bash
API_BASE=https://adu-atlas-api.onrender.com   # or your custom domain

# Health check (also what Render's healthCheckPath polls).
curl -sS "$API_BASE/v1/health"

# Feasibility analysis for a real, previously-verified LA City address.
curl -sS -X POST "$API_BASE/v1/feasibility" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: smoke-test-key" \
  -d '{
    "address": "509 N Avenue 50, Los Angeles, CA 90042",
    "project_type": "detached_adu"
  }' | python3 -m json.tool
```

Expect a 200 with a terminal `feasibility_status`, the resolved zone
(`RD1.5` per LAMC 12.22), source-cited `provenance` (parcel via LA County
ArcGIS, zoning via ZIMAS, FEMA flood overlay), and the disclaimer string from
`services/core/constants.py` verbatim. A `503`/`insufficient_data` result
instead of a fabricated one means an upstream ArcGIS source was unavailable -
correct degrade behavior, not a bug; retry, or check `source_registry` /
`ingest_runs` for the last successful ingestion run.

Re-run the same request body a second time and confirm it returns
immediately from the 24-hour dedupe cache (see `config/plans.yaml`
`billing.dedupe.window_hours`) without incrementing quota.

## Step 6 - Tests before/after any redeploy

```bash
# Python: services/core + services/api + ingestion lint and tests.
ruff check services ingestion tests
ruff format --check services ingestion tests
pytest -q

# OpenAPI 3.1 spec validity.
make openapi-validate

# Portal typecheck + build.
cd portal && npx tsc --noEmit && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above plus PostGIS migration
validation, pip-audit, gitleaks, and npm audit on every push/PR to `main`;
treat a red CI run on `main` as blocking before triggering a Render redeploy.

## Ongoing operations

- `adu-atlas-api` has `autoDeploy: true` (deploys on every push to `main`);
  all three cron workers have `autoDeploy: false` (deploy them intentionally
  from the Render dashboard after verifying an ingestion-image change).
- Cron schedule is staggered by design (GIS 03:00 -> code 04:30 -> QA
  06:00 UTC, Mondays) so each stage reads data the previous stage already
  refreshed that run; do not reorder without updating `render.yaml`'s
  comments.
- Reprocess a jurisdiction on demand: `make ingest-la
  JURISDICTION=los_angeles` (GIS + code ingestion; run `make ingest-qa-la`
  separately afterward).
- Rotate `RAPIDAPI_PROXY_SECRET` by updating it in both the RapidAPI gateway
  config and Render's `adu-atlas-api` env vars together - a mismatch fails
  every RapidAPI-routed request with 401.
- Adding a new jurisdiction: update `config/jurisdictions.yaml`
  (`coverage_status: planned -> ingesting -> production` only once its
  sources + rules are ingested, tested, and verified - the portal's
  `/coverage` page reads this file directly), then extend `ingestion/gis` and
  `ingestion/code` per their READMEs.
