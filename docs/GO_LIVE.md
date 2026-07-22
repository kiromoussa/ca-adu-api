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

## Coverage update - 8 California cities production

All eight major-market CA cities are live, each verified with a real address
returning a source-cited feasibility result, keyed to that city's zoning + ADU
ordinance:

| City | Parcel source | Zoning source | ADU rules | Verified |
|---|---|---|---|---|
| Los Angeles | LA County Assessor | ZIMAS | LAMC 12.22 | 180 rules |
| San Diego | City GeocoderMerged | DSD Zoning_Base | SDMC 141.0302 | 136 rules |
| San Jose | PLN parcels | PLN Zoning District | SJMC 20.30.460 | 68 rules |
| San Francisco | SF Planning parcels | SF Planning zoning | PC 207.2 | 72 rules |
| Sacramento | Sac County parcels | City zoning (BASE_ZONE) | 17.228.105 | 56 rules |
| Long Beach | LA County Assessor | LB Zoning | LBMC 21.52.206 | 112 rules |
| Irvine | cityofirvine OnlineParcel | OnlineParcel zoning | Ch 3-26 | 152 rules |
| Oakland | Alameda County (AC_Parcels2020) | Oakland Base Zones | Planning Code 17.103 | 56 rules |

Coverage is on-demand: any address in these cities resolves live (parcel + zoning
+ FEMA flood fetched from the official ArcGIS services and cached to PostGIS with
provenance). Adding a city is a config entry in services/core/ondemand.py
(JURISDICTION_LAYERS) + boundary + verified rules; the resolver is jurisdiction-agnostic.

## Production hardening (recommended before real volume)

1. Geocoder: the free US Census geocoder is the keyless default and is reliable
   for normal, spaced traffic, but it rate-limits rapid bursts from one IP (an
   8-address burst can throttle). For sustained volume set
   GOOGLE_MAPS_GEOCODING_API_KEY or MAPBOX_ACCESS_TOKEN on the Render service -
   the fallback is already wired in services/core/geocode.py. Census retry now
   uses exponential backoff.
2. Render plan: the free/starter web instance cold-starts after idle and is
   CPU-limited, so the first uncached request per city is ~5-12s (on-demand
   ArcGIS fetch). Upgrade to a plan without idle-sleep and consider a small
   warm-cache cron for launch-day latency.
3. Each city's on-demand fetch is cached after first use, so steady-state latency
   is sub-second; ZIMAS (LA) and cityofirvine.org (Irvine) are slower origins and
   have per-layer timeouts of 22s / 20s.
