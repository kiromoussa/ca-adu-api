# ADU Atlas API

A self-serve, developer-facing California parcel feasibility API for
accessory dwelling units (ADUs), junior ADUs (JADUs), and SB 9 preliminary
analysis. Send an address and a proposed project type. Get back a fast,
deterministic, source-cited, timestamped preliminary feasibility result:
parcel and zoning context, ADU/JADU/SB 9 eligible paths, setback/height/size
constraints, hazard and overlay flags, assumptions, confidence, and official
source citations.

This is a pivot from an earlier CA municipal-code scraper product in this
same repository. That product's infrastructure (Supabase, Render, the
scraping/extraction pipeline, PostGIS) is reused; the product surface and
schema are restructured around a single question - preliminary parcel
feasibility - instead of raw zoning-code lookup.

## What this is not

ADU Atlas is not a legal opinion, not a permitting system, and not a
guarantee. It never states that a project is approved, legal to build, or a
final yes/no. See "Trust and legal model" below - this is the part of the
product that is non-negotiable.

## Trust and legal model (non-negotiable)

- **No LLM on the request path.** Every `/v1/feasibility` call is answered
  by versioned structured rules, PostGIS spatial joins, and source-linked
  data only. Large language models are used strictly offline, to produce
  extraction candidates from municipal code text and QA queue items; every
  candidate requires source and human verification before it becomes a
  published rule.
- **Provenance on every substantive field.** `source_url`, `source_title`,
  `source_section` or `source_layer`, `retrieved_at`, `last_verified_at`,
  `confidence`, and `data_status` travel with every value the API asserts.
- **No false certainty.** `feasibility_status` is always one of
  `likely_feasible`, `likely_constrained`, `needs_professional_review`, or
  `insufficient_data`. Never "approved", "legal", "guaranteed", or a bare
  yes/no.
- **The disclaimer is verbatim on every response:**

  > This is preliminary informational zoning and GIS analysis, not legal,
  > architectural, surveying, engineering, title, environmental, or permit
  > advice. Verify all results with the applicable jurisdiction and
  > qualified professionals before making decisions or spending money.

- **Immutable source snapshots.** Every scraped code section and GIS layer
  fetch is content-hashed and stored as an immutable, versioned
  `source_snapshots` row. History is never overwritten.
- **State-law baselines are explicit.** Local zoning values are compared
  against the current California state-law floor/ceiling (AB 2221, SB 897,
  SB 9, Gov. Code Sections 66310-66342). A local value more restrictive than
  the state baseline is flagged `needs_review` or
  `possibly_more_restrictive_than_state_baseline` - the local source is
  always preserved, never silently discarded or overridden.

## Coverage honesty: eight California cities live

Eight California cities are `production` and billable: Los Angeles, San
Diego, San Jose, San Francisco, Sacramento, Long Beach, Irvine, and Oakland.
Each was verified end-to-end against a real address (parcel + zoning + a
source-cited feasibility result) before being marked `production`. A
jurisdiction reaches `production` only after its source registry, GIS
layers, and rule set are ingested, tested, and verified; any other
registered jurisdiction returns a `422 unsupported_coverage` response -
never billed - until it clears that bar.

`GET /v1/jurisdictions` is the live source of truth; nothing in this API or
its docs hardcodes which cities are "done". Resolution uses an accuracy-first
geocoder chain (a paid provider first when configured, then Census and
OpenStreetMap Nominatim) and on-demand ArcGIS parcel/zoning resolution with a
nearest-parcel tolerance and bounded retries, so any address in a covered
city resolves without bulk ingest.

## API at a glance

Base path `/v1`. Full schema: `openapi/openapi.yaml` (OpenAPI 3.1). Human
guide: `docs/API.md`.

| Method | Path | Billed | Purpose |
|---|---|---|---|
| POST | `/v1/feasibility` | Yes, on completion | The core product: preliminary ADU/JADU/SB 9 feasibility for one address and project type. |
| GET | `/v1/jurisdictions` | No | Coverage status, supported project types, source update date. |
| GET | `/v1/jurisdictions/{slug}/rules` | No | Citywide and zone-level rules, citations, version history. |
| GET | `/v1/analyses/{analysis_id}` | No | Retrieve a stored analysis (private, or public via share token). |
| GET | `/v1/changelog` | No | Public update history by city. |
| GET | `/v1/health` | No | Service liveness and non-sensitive source freshness. |

Billable unit: one completed address-level feasibility analysis (one
address plus one project_type resolving to a terminal
`feasibility_status`). Errors and unsupported-coverage responses are never
billed. Identical inputs from the same consumer within 24 hours are a cache
hit, not a second charge. Plan tiers (BASIC/PRO/ULTRA/MEGA) are config-driven
in `config/plans.yaml`, never hardcoded - see `docs/rapidapi/PRICING.md` for
the current tier copy.

Copy-paste request/response examples in curl, TypeScript, Python, and
JavaScript, for every endpoint and both auth variants (RapidAPI gateway and
direct API key): `openapi/examples/`.

## Distribution

RapidAPI is the primary distribution channel; the public OpenAPI docs and
developer portal (`portal/`) are secondary, self-serve. The exact RapidAPI
Hub listing package (title, descriptions, categories, tags, FAQ, pricing
copy, endpoint docs, response examples, logo requirements, support policy)
lives in `docs/rapidapi/`.

## Stack

- **Supabase** - Postgres 15 + PostGIS for parcels, zoning districts, and
  overlay layers; Storage for immutable, content-hashed raw source
  snapshots. Sixteen tables in total (`supabase/migrations/`); see
  `docs/adr/0001-architecture.md` for the full list.
- **Render** - the FastAPI request-path service (`services/api`) plus
  scheduled ingestion and QA cron workers (`ingestion/`).
- **Vercel** - the Next.js developer portal (`portal/`): OpenAPI docs,
  coverage status, pricing, and changelog, all driven by `config/` and the
  live API, never hardcoded.

The deterministic rule engine and PostGIS spatial-feasibility logic live in
`services/core`, a pure, tested package shared by the API and (where
relevant) ingestion QA. See `docs/adr/0001-architecture.md` for why FastAPI
on Render was chosen over a Supabase Edge Function for this workload.

## Repository layout

```
supabase/migrations/   PostGIS + 16-table schema, RLS, indexes, baseline seed
services/
  core/                deterministic rule engine + PostGIS spatial feasibility (pure, tested)
  api/                 FastAPI app (request path), Pydantic schemas, RapidAPI gateway, limiter
ingestion/
  arcgis/              ArcGIS REST client (metadata, query, pagination, ETag, caching)
  gis/                 LA ZIMAS parcels+zoning, FEMA flood, CAL FIRE, statewide bootstrap
  code/                municipal-code ingestion + offline extraction candidates + QA
config/                plans.yaml, sources.yaml, jurisdictions.yaml (config-driven)
openapi/               openapi.yaml (3.1) + examples/ (curl/ts/python/js SDK examples)
portal/                Next.js developer portal (Vercel)
docker/                Dockerfiles for the API and ingestion images
docker-compose.yml     local Postgres/PostGIS + API stack
docs/                  ADRs, product spec, API guide, RapidAPI listing package
tests/                 pytest (services/core, services/api, ingestion) + portal tests
```

## Quickstart

Prerequisites: Docker, Node 20+, Python 3.12+, `make`.

```bash
git clone <this-repo>
cd ca-adu-api
cp .env.example .env        # fill in Supabase / geocoder vars; see comments in the file

# Bring up local Postgres/PostGIS and apply the schema.
make db-up
make migrate

# Run the FastAPI service with autoreload against the local database.
make api-dev
# ... or build and run the same thing in Docker:
docker compose up --build api

# Run the legacy municipal-code ingestion pipeline for Los Angeles.
make ingest-la

# Run the test suites (services/core + services/api + ingestion, then the portal).
make test

# Validate the OpenAPI 3.1 spec.
make openapi-validate
```

`.env.example` at the repository root is the complete environment variable
reference across every component. Never commit a real `.env`;
`SUPABASE_SERVICE_ROLE_KEY` and any LLM/geocoder API keys are secrets.

Try the API once it is running locally:

```bash
curl -sS -X POST "http://localhost:8000/v1/feasibility" \
  -H "Content-Type: application/json" \
  -d @openapi/examples/feasibility.request.json | python3 -m json.tool
```

More runnable examples (RapidAPI headers and direct-key variants, curl,
TypeScript, Python, JavaScript): `openapi/examples/`.

## Deploy summary

- **Supabase**: apply `supabase/migrations/*.sql` to the production project
  (PostGIS 3.3+ is already enabled there); Storage holds immutable source
  snapshots.
- **Render**: the FastAPI service (`services/api`, `docker/Dockerfile.api`)
  runs as a web service; ingestion and QA run as scheduled cron workers
  (`ingestion/`, `docker/Dockerfile.ingestion`). See `render.yaml`.
- **Vercel**: the developer portal (`portal/`) deploys from its own project,
  pointed at the deployed API's base URL.
- **RapidAPI**: the API is listed as a gateway-proxied product per
  `docs/rapidapi/LISTING.md`; the gateway forwards `X-RapidAPI-Key` /
  `X-RapidAPI-Host`, which the API verifies against the expected gateway
  pattern.

Full step-by-step runbook: `docs/DEPLOY.md`.

## Documentation map

- `docs/PRODUCT_SPEC.md` - authoritative product spec: trust/legal
  non-negotiables, the 16-table schema, spatial logic, API surface, RapidAPI
  requirements.
- `docs/adr/0001-architecture.md` - why FastAPI-on-Render, PostGIS,
  no-LLM-on-request-path, provenance-everywhere, and the repo layout above.
- `docs/API.md` - human API guide: auth, idempotency, versioning, errors,
  rate limits, the freshness/provenance model.
- `docs/rapidapi/` - the RapidAPI Hub listing package.
- `openapi/openapi.yaml` - the OpenAPI 3.1 spec (source of truth for
  request/response shapes).
- `openapi/examples/` - copy-paste SDK examples in curl, TypeScript, Python,
  and JavaScript.

## Style

No emojis. No em dashes (use a hyphen instead). `cursor: pointer` on every
portal button and link.
