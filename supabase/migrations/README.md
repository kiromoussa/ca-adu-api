# Supabase migrations - ADU Atlas API

Applied in numeric order.

| File | Purpose |
| --- | --- |
| `0004_enable_postgis.sql` | Enables PostGIS, postgis_topology, pg_trgm, uuid-ossp (into the `extensions` schema on Supabase). |
| `0005_adu_atlas_schema.sql` | Drops the superseded scraper tables/enums/functions, then creates the full 16-table ADU Atlas schema with CHECK constraints, PostGIS geometry columns, and triggers. |
| `0006_rls_indexes.sql` | GIST + B-tree indexes and Row Level Security policies. |

Seed (run after 0006, not a migration): `supabase/seed_baselines.sql` loads the
California `state_rule_baselines` and the 8 target `jurisdictions`
(Los Angeles = `ingesting`, the other 7 = `planned`).

## The 16 tables

`jurisdictions`, `source_registry`, `source_snapshots`, `zoning_sections`,
`state_rule_baselines`, `zoning_rules`, `rule_attributes`, `parcels`,
`zoning_districts`, `overlay_features`, `property_analyses`,
`analysis_findings`, `ingest_runs`, `qa_issues`, `api_usage_events`,
`changelog_entries`.

## Conventions this schema guarantees (the contract)

- UUID PKs via `gen_random_uuid()`; `created_at` / `updated_at` timestamps
  (`updated_at` maintained by the `set_updated_at()` trigger on mutable tables).
- Enum-like fields use CHECK constraints (not Postgres enum types) so legal
  values are visible in the DDL and cheap to extend: `coverage_status`,
  `source_type`, `provider`, `overlay_type`, `feasibility_status`, `confidence`,
  `data_status`, `review_status`, `severity`, `status`, `compliance_flag`,
  `project_type`.
- Geometry in SRID 4326 with GIST indexes: `parcels.geom`
  (MultiPolygon) + `parcels.centroid` (Point) + `parcels.area_sqft`,
  `zoning_districts.geom` (MultiPolygon), `overlay_features.geom` (Geometry),
  plus `jurisdictions.boundary`/`centroid` and `property_analyses.geocode`.
- Provenance is per-field on `rule_attributes` and `analysis_findings`
  (`source_url`, `source_title`, `source_section`, `source_layer`,
  `retrieved_at`, `last_verified_at`, `confidence`, `data_status`).

## source_snapshots is append-only / immutable

`source_snapshots` is content-hashed history and is **never** mutated. UPDATE and
DELETE are blocked by the `forbid_snapshot_mutation()` trigger
(`trg_source_snapshots_no_update`, `trg_source_snapshots_no_delete`).
Corrections are recorded as a **new** snapshot row (new `version` and
`content_hash`), preserving the full history. `(source_registry_id, version)`
and `(source_registry_id, content_hash)` are unique.

## RLS model

- `service_role` has full read/write on every table (explicit `FOR ALL`
  policies, in addition to Supabase's built-in RLS bypass for that role).
- Public (`anon` + `authenticated`) SELECT only on the catalog tables:
  `jurisdictions`, `zoning_rules`, `rule_attributes`, `changelog_entries`,
  `state_rule_baselines`.
- All other tables have RLS enabled with no public policy. In particular
  `property_analyses` and `api_usage_events` are never publicly readable; the
  API serves individual analyses through the service role only.

## State-law baselines

`state_rule_baselines` encodes the California floors/ceilings (AB 2221, SB 897,
AB 68/SB 13, SB 9, Gov. Code 66310-66342). The rule engine compares local
`rule_attributes` against these. Local values more restrictive than the state
baseline are flagged `possibly_more_restrictive_than_state_baseline` /
`needs_review`; the local source is preserved, never discarded.

## Note on the legacy seed

`supabase/seed.sql` seeds the prior-product `cities` table, which `0005` drops.
That file is outside this schema's scope; if `supabase db reset` is used, replace
or remove that legacy seed and run `seed_baselines.sql` instead.
