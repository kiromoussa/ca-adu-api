# ADU Atlas - ArcGIS client + GIS ingestion

Deterministic, source-cited GIS ingestion for the ADU Atlas API. This subtree
owns:

- `ingestion/arcgis/` - a robust ArcGIS REST client (metadata, layer discovery,
  paginated feature queries, retries + backoff, rate limiting, ETag /
  Last-Modified caching).
- `ingestion/gis/` - source-specific ingesters that write PostGIS geometry plus
  immutable, content-hashed `source_snapshots` and `ingest_runs` rows.

There is **no LLM anywhere in here**. Ingestion is deterministic HTTP + spatial
SQL. LLM use (extraction candidates / QA) lives in `ingestion/code/`, a
different subtree.

## What gets ingested

| Source | Module | Target table | Notes |
| --- | --- | --- | --- |
| LA City ZIMAS zoning | `gis/la_zimas.py` | `zoning_districts` | Layer 1102 (`ZONE_CMPLT`, `ZONE_CLASS`, `ZONE_CODE`, `ZONELEGEND`). Official City of LA source. |
| LA City parcels | `gis/la_zimas.py` | `parcels` | Requires `LA_PARCEL_SERVICE_URL` (see below). APN + situs + geometry + centroid + area_sqft. |
| FEMA NFHL flood | `gis/fema_flood.py` | `overlay_features` (`flood`) | Layer 28 "Flood Hazard Zones". Raw `FLD_ZONE` / `ZONE_SUBTY` / `SFHA_TF` preserved. |
| CAL FIRE FHSZ | `gis/calfire_fhsz.py` | `overlay_features` (`fire`) | SRA (layer 0) + LRA (layer 1). Raw `HAZ_CLASS` / `HAZ_CODE` / `SRA` preserved. |
| CA statewide zoning | `gis/statewide_zoning.py` | `zoning_districts` | Bootstrap ONLY, lower authority. Local source always wins. |

### LA parcels and the "do not substitute LA County" rule

The public ZIMAS `MapServer` (`.../zma/zimas/MapServer`) exposes queryable
**zoning** polygons but **not** parcel polygons carrying an APN - its `lotlines`
layers are polylines. Parcel geometry with an APN therefore comes from an
explicitly configured **City of Los Angeles** parcel feature service:

```
export LA_PARCEL_SERVICE_URL="https://<official-la-city-parcel-service>/FeatureServer"
export LA_PARCEL_LAYER_ID=0            # optional; auto-discovered by APN field if omitted
```

If no parcel service is configured, `la_parcels` exits `skipped` (recorded on
`ingest_runs`) and **never** falls back to an unincorporated LA County layer.
Zoning ingestion is independent and always runs.

## Trust guarantees honored in code

- **Immutable snapshots.** Every ingest writes a `source_snapshots` row whose
  `content_hash` is a sha256 over the layer metadata + exact query params.
  Identical captures dedupe; a changed layer/query yields a new version. The DB
  also blocks UPDATE/DELETE on that table (append-only trigger).
- **Provenance.** Every parcel / district / overlay row carries
  `source_registry_id`, `source_snapshot_id`, `source_url`, `source_layer`,
  `retrieved_at`, `confidence`, `data_status`.
- **"No feature" vs "source unavailable".** A reachable layer returning zero
  features is a success with zero inserts. An unreachable source (timeout /
  repeated 5xx / transport error) raises `ArcGISUnavailableError`, which fails
  the `ingest_runs` row - it never masquerades as "no hit".
- **State-baseline / authority.** The statewide zoning bootstrap is written with
  `confidence='low'`, `data_status='needs_review'`,
  `zone_category='statewide_bootstrap'`, and `authority_rank=5` in
  `raw_attributes`; it refuses to run against a `production` jurisdiction.
- **Geometry.** All geometry is stored in EPSG:4326. `f=geojson` output from
  ArcGIS is always WGS84; centroid and `area_sqft` are computed in PostGIS
  (`ST_Centroid`, `ST_Area(ST_Transform(geom, 3310)) * 10.7639104167`).

## Running

```bash
pip install -r ingestion/gis/requirements.txt

export SUPABASE_DB_URL="postgresql://postgres:<pw>@<host>:5432/postgres"

python -m ingestion.gis.run la_zimas            # LA zoning (+ parcels if configured)
python -m ingestion.gis.run la_zoning           # LA zoning only
python -m ingestion.gis.run la_parcels          # LA parcels only
python -m ingestion.gis.run fema_flood          # FEMA flood overlays
python -m ingestion.gis.run calfire_fhsz        # CAL FIRE fire overlays
python -m ingestion.gis.run statewide_zoning --slug san_diego   # bootstrap
python -m ingestion.gis.run all                 # la_zimas + fema_flood + calfire_fhsz

# smoke test with a small feature cap:
python -m ingestion.gis.run fema_flood --max-features 50

# `source` is optional (defaults to "all"), and --jurisdiction is accepted as
# an alias for --slug - this is the exact form render.yaml's cron
# dockerCommand and `make ingest-gis-la` invoke:
python -m ingestion.gis.run --jurisdiction los_angeles
```

The process prints a JSON summary and exits non-zero if any source failed
(`skipped` / `partial` are not hard failures).

## Environment / configuration (never hardcoded)

| Variable | Purpose | Default |
| --- | --- | --- |
| `SUPABASE_DB_URL` (required) | Direct Postgres connection string (spatial SQL). | - |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Optional; informational / future Storage uploads. | - |
| `LA_ZIMAS_SERVICE_URL` | LA ZIMAS MapServer. | `.../zma/zimas/MapServer` |
| `LA_PARCEL_SERVICE_URL`, `LA_PARCEL_LAYER_ID` | LA City parcel feature service + layer. | unset (parcels skipped) |
| `FEMA_NFHL_SERVICE_URL`, `FEMA_FLOOD_LAYER_ID` | FEMA NFHL service + flood layer. | NFHL MapServer, `28` |
| `CALFIRE_FHSZ_SERVICE_URL`, `CALFIRE_FHSZ_LAYER_IDS` | CAL FIRE service + layer ids (CSV). | CA GIS service, `0,1` |
| `CA_STATEWIDE_ZONING_SERVICE_URL`, `CA_STATEWIDE_ZONING_LAYER_ID` | Statewide bootstrap service. | unset (skipped) |
| `INGEST_JURISDICTION_SLUG` | Target jurisdiction for the bootstrap. | unset |
| `INGEST_PAGE_SIZE`, `INGEST_MAX_FEATURES` | Pagination page size / hard cap. | layer max / none |
| `ARCGIS_HTTP_TIMEOUT`, `ARCGIS_RATE_LIMIT_SECONDS`, `ARCGIS_MAX_RETRIES` | HTTP client tuning. | `60`, `0.5`, `4` |
| `INGEST_TRIGGERED_BY` | Recorded on `ingest_runs.triggered_by`. | `cli` |

## Dependencies

`httpx`, `tenacity`, `psycopg[binary]` (v3), `shapely`, `pyproj`, `supabase`,
`python-dotenv`. See `requirements.txt`.
