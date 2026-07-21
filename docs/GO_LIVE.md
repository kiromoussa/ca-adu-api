# ADU Atlas API - LIVE

Deployed entirely via CLI (Supabase CLI, Render CLI, Vercel CLI, gh).

## Live endpoints
- API:    https://adu-atlas-api.onrender.com  (FastAPI on Render, native python, srv-d9fu3hmrnols73edra9g)
- Portal: https://adu-atlas-portal.vercel.app  (Next.js on Vercel)
- DB:     Supabase project abtapphfcpmootzctmec (Postgres 15 + PostGIS 3.3)
- Repo:   https://github.com/kiromoussa/ca-adu-api (public, to enable CLI deploy from public git)

## Verified live (public internet)
- GET /v1/health -> 200 with source freshness.
- POST /v1/feasibility for a fresh West LA address (1023 S Wooster St) -> likely_feasible,
  LA production, parcel matched on-demand (APN 4332-016-038), zone R3, detached_adu likely_eligible,
  16ft height / 4ft setbacks / no parking (all cited to LAMC 12.22 + state baselines), 13 citations,
  disclaimer, analysis_id. Deterministic, no LLM on the request path.

## Coverage
- Los Angeles: production. Any LA address resolves via on-demand ArcGIS resolution
  (parcel = LA County Assessor, zoning = LA City ZIMAS, flood = FEMA NFHL), cached to PostGIS.
- Full LA City boundary loaded (473 sq mi). 180 verified LAMC rules across 45 residential zones.
- Other 7 cities: coverage_status=planned (return unsupported_coverage, never billed).

## Finish / operate
- RapidAPI listing package: docs/rapidapi/. Set RAPIDAPI_PROXY_SECRET on the Render service when listing.
- Portal API URL is set to the Render URL (NEXT_PUBLIC_API_BASE_URL).
- To make the repo private again, connect Render's GitHub App to the repo (dashboard) so Render can
  keep pulling; the public-git deploy path used here requires the repo to stay public.
