# ADR 0001 - ADU Atlas API architecture

Status: accepted. Date: 2026-07-21.

## Context

ADU Atlas API is a self-serve, developer-facing California parcel feasibility API
for ADUs, JADUs, and SB 9 preliminary analysis. The paid product is a fast,
deterministic, source-cited, address-level feasibility result - not a municipal
code scraper. The request path must be deterministic (no LLM), spatially aware
(PostGIS), and source-cited.

## Decisions

1. **Primary API: FastAPI (Python) on Render.**
   The request path needs PostGIS spatial joins, a deterministic versioned rule
   engine, and data sourced from ArcGIS REST services. Ingestion is already
   Python (ArcGIS client, shapely, municipal-code extraction). One language for
   ingestion + rule engine + API avoids duplicating geospatial logic across a
   TS/Python split and keeps the deterministic core in one tested package
   (`services/core`). Supabase Edge Functions (Deno) are not a good fit for
   heavy spatial + rule logic. Chosen over a TS API service for this reason.

2. **Supabase = Postgres 15 + PostGIS + Storage.** PostGIS for parcels, zoning
   districts, overlays; Storage for immutable raw source snapshots. Auth is not
   required for v1 (RapidAPI gateway handles consumer identity); the direct API
   uses hashed API keys / consumer ids.

3. **Render** runs the FastAPI service and scheduled ingestion/QA workers.
   **Vercel** hosts only the Next.js developer portal + OpenAPI docs.

4. **No LLM at request time.** The request path uses versioned `zoning_rules` +
   `rule_attributes` + `state_rule_baselines` + PostGIS. LLMs are used offline
   only to produce extraction candidates and QA queue items; every candidate
   requires source/human validation before `review_status = verified`.

5. **Spec-first.** OpenAPI 3.1 is authored before/with the implementation and
   validated in CI. Pydantic models are the single source of truth on the server.

6. **Provenance everywhere.** Every substantive field carries source_url,
   source_title, source_section/layer, retrieved_at, last_verified_at,
   confidence, data_status. Raw snapshots are immutable (content-hashed, stored
   in Supabase Storage, never overwritten).

7. **State-law baseline validation is explicit.** Local values more restrictive
   than the current state baseline are flagged
   `possibly_more_restrictive_than_state_baseline` / `needs_review`; the local
   source is preserved and never silently discarded.

8. **RapidAPI first.** Billable unit = one completed address-level feasibility
   analysis (one address + one project_type). Errors and unsupported-coverage
   responses are not billed. Same-customer identical inputs within 24h are a
   cache hit and not double-billed. Plan tiers are config-driven
   (`config/plans.yaml`), not hardcoded.

9. **Coverage honesty.** A city is `production` only after its source registry,
   GIS layers, and rule set are ingested, tested, and marked production-ready.
   Los Angeles City is the v1 target; all others start `planned`.

## Repository layout (target)

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
openapi/               openapi.yaml (3.1) + SDK examples (curl/ts/python/js)
portal/                Next.js developer portal (Vercel)
docker/                Dockerfiles + docker-compose (postgis + api + ingestion)
.github/workflows/     CI: lint, tests, migration + openapi validation, security
docs/                  ADRs, runbooks, RapidAPI listing package
```
