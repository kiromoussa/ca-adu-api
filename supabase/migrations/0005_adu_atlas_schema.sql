-- ============================================================================
-- 0005_adu_atlas_schema.sql
-- ADU Atlas API - full 16-table schema (structural DDL only; indexes + RLS in
-- 0006, seeds in seed_baselines.sql).
--
-- This is the data contract every other component (services/core rule engine,
-- services/api request path, ingestion pipelines) depends on. Design rules:
--   - UUID primary keys via gen_random_uuid().
--   - created_at / updated_at timestamps (updated_at maintained by trigger).
--   - Foreign keys with explicit ON DELETE behavior.
--   - CHECK constraints (not enum types) on every enum-like field so the set of
--     legal values is visible in the table definition and easy to extend.
--   - PostGIS geometry columns in SRID 4326; GIST + B-tree indexes live in 0006.
--   - source_snapshots is append-only / immutable (content-hashed history that is
--     never mutated); enforced by a trigger below.
--   - Provenance is first-class: rule_attributes and analysis_findings carry
--     per-field source_url / source_title / source_section / source_layer /
--     retrieved_at / last_verified_at / confidence / data_status.
--
-- PostGIS was enabled in 0004 (installed into the `extensions` schema on
-- Supabase). Put `extensions` on the search_path so `geometry`, GIST operator
-- classes, and spatial functions resolve without schema-qualifying every use.
-- ============================================================================

set search_path = public, extensions;

create extension if not exists pgcrypto;   -- gen_random_uuid() (idempotent)

-- ----------------------------------------------------------------------------
-- Drop superseded prior-product (municipal-code scraper) objects so the new
-- schema is clean. cascade removes dependent policies, indexes, and FKs. Note
-- the prior product also had a table named `zoning_sections`; it is dropped
-- here and recreated below with the ADU Atlas shape.
-- ----------------------------------------------------------------------------
drop table if exists usage_logs      cascade;
drop table if exists qa_alerts       cascade;
drop table if exists adu_rules       cascade;
drop table if exists api_keys        cascade;
drop table if exists zoning_sections cascade;
drop table if exists cities          cascade;

drop function if exists increment_api_usage(text) cascade;

drop type if exists publisher_type  cascade;
drop type if exists compliance_flag cascade;   -- prior enum; now a CHECKed text column
drop type if exists api_tier        cascade;

-- ----------------------------------------------------------------------------
-- Shared trigger helpers.
-- ----------------------------------------------------------------------------

-- Maintain updated_at on any table that has the column.
create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Enforce append-only immutability on source_snapshots: history is never
-- rewritten or deleted. Corrections are new snapshots (new content_hash /
-- version), never in-place edits.
create or replace function forbid_snapshot_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception
    'source_snapshots is append-only and immutable; % is not permitted. Insert a new snapshot instead.',
    tg_op;
  return null;
end;
$$;

-- ============================================================================
-- 1. jurisdictions
-- ============================================================================
create table jurisdictions (
  id                      uuid primary key default gen_random_uuid(),
  slug                    text not null unique,
  name                    text not null,
  jurisdiction_type       text not null default 'city'
                            check (jurisdiction_type in ('city','county','state')),
  state_code              text not null default 'CA',
  county                  text,
  coverage_status         text not null default 'planned'
                            check (coverage_status in ('planned','ingesting','production','deprecated')),
  supported_project_types text[] not null default '{}',
  -- Boundary polygon used for step A (address -> jurisdiction boundary test).
  boundary                geometry(MultiPolygon, 4326),
  centroid                geometry(Point, 4326),
  source_update_date      date,
  last_source_refresh_at  timestamptz,
  notes                   text,
  created_at              timestamptz not null default now(),
  updated_at              timestamptz not null default now()
);

-- ============================================================================
-- 2. source_registry - every official source we track (code publishers, GIS
--    layers, state handbook/statute). jurisdiction_id is null for statewide
--    sources (HCD handbook, FEMA NFHL, CAL FIRE FHSZ, CA statewide zoning).
-- ============================================================================
create table source_registry (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid references jurisdictions(id) on delete cascade,
  source_type        text not null
                       check (source_type in (
                         'municipal_code','gis_parcel','gis_zoning','gis_overlay',
                         'state_handbook','state_statute','geocoder','other')),
  provider           text not null
                       check (provider in (
                         'american_legal','municode','arcgis','fema','cal_fire',
                         'hcd','ca_open_data','census','other')),
  name               text not null,
  description        text,
  url                text not null,
  endpoint           text,          -- ArcGIS MapServer / FeatureServer base
  layer_id           text,          -- ArcGIS layer id or docid, when applicable
  layer_name         text,
  license_notes      text,
  publisher          text,
  active             boolean not null default true,
  refresh_interval_days integer,
  etag               text,
  last_modified      text,
  last_checked_at    timestamptz,
  last_retrieved_at  timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (jurisdiction_id, source_type, url)
);

-- ============================================================================
-- 3. source_snapshots - immutable, content-hashed raw captures. Append-only:
--    never updated or deleted (enforced by trigger). Corrections are new rows.
--    Raw bytes live in Supabase Storage; storage_path points at them.
-- ============================================================================
create table source_snapshots (
  id                 uuid primary key default gen_random_uuid(),
  source_registry_id uuid not null references source_registry(id) on delete restrict,
  jurisdiction_id    uuid references jurisdictions(id) on delete restrict,
  version            integer not null,            -- monotonic per source_registry_id
  content_hash       text not null,               -- sha256 of the raw payload
  storage_path       text,                        -- Supabase Storage object path
  content_type       text,
  byte_size          bigint,
  http_status        integer,
  etag               text,
  last_modified      text,
  retrieved_at       timestamptz not null,
  metadata           jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now(),
  unique (source_registry_id, version),
  unique (source_registry_id, content_hash)       -- dedup identical captures
);

-- Append-only enforcement: block UPDATE and DELETE entirely.
create trigger trg_source_snapshots_no_update
  before update on source_snapshots
  for each row execute function forbid_snapshot_mutation();

create trigger trg_source_snapshots_no_delete
  before delete on source_snapshots
  for each row execute function forbid_snapshot_mutation();

-- ============================================================================
-- 4. zoning_sections - extracted municipal-code sections (raw text + heading)
--    tied to the snapshot they came from. Provenance for zoning_rules.
-- ============================================================================
create table zoning_sections (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid not null references jurisdictions(id) on delete cascade,
  source_registry_id uuid references source_registry(id) on delete set null,
  source_snapshot_id uuid references source_snapshots(id) on delete set null,
  code_title         text,          -- e.g. LAMC
  title_number       text,
  chapter_number     text,
  section_number     text,          -- e.g. 12.22 A.33
  section_label      text,
  heading            text,
  section_url        text not null,
  raw_text           text,
  content_hash       text,
  confidence         text not null default 'medium'
                       check (confidence in ('high','medium','low')),
  data_status        text not null default 'current'
                       check (data_status in ('current','stale','needs_review','unavailable')),
  retrieved_at       timestamptz,
  last_verified_at   timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (jurisdiction_id, section_url)
);

-- ============================================================================
-- 5. state_rule_baselines - California statewide floors/ceilings the rule
--    engine validates local rules against. Seeded in seed_baselines.sql.
-- ============================================================================
create table state_rule_baselines (
  id                  uuid primary key default gen_random_uuid(),
  field_name          text not null,
  applies_to          text[] not null default '{}',   -- project_type scope; empty = all
  operator            text not null
                        check (operator in ('gte','lte','eq','must_equal','floor','ceiling')),
  baseline_value_json jsonb not null,
  unit                text,
  legal_citation      text not null,
  description         text,
  source_url          text not null,
  source_title        text,
  effective_from      date not null,
  effective_to        date,
  confidence          text not null default 'high'
                        check (confidence in ('high','medium','low')),
  data_status         text not null default 'current'
                        check (data_status in ('current','stale','needs_review','unavailable')),
  last_verified_at    timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (field_name, effective_from)
);

-- ============================================================================
-- 6. zoning_rules - versioned local rule set per (jurisdiction, zone,
--    project_type). Individual fields + provenance live in rule_attributes.
-- ============================================================================
create table zoning_rules (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid not null references jurisdictions(id) on delete cascade,
  zone_code          text not null,
  zone_name          text,
  project_type       text not null
                       check (project_type in (
                         'detached_adu','attached_adu','garage_conversion',
                         'jadu','sb9_duplex','sb9_urban_lot_split')),
  zoning_section_id  uuid references zoning_sections(id) on delete set null,
  source_registry_id uuid references source_registry(id) on delete set null,
  source_snapshot_id uuid references source_snapshots(id) on delete set null,
  version            integer not null default 1,
  is_current         boolean not null default true,
  effective_from     date,
  effective_to       date,
  summary            text,
  review_status      text not null default 'pending'
                       check (review_status in ('pending','in_review','verified','rejected','superseded')),
  compliance_flag    text not null default 'needs_review'
                       check (compliance_flag in (
                         'matches_state_baseline','possibly_more_restrictive_than_state_baseline',
                         'needs_review','not_applicable')),
  confidence         text not null default 'medium'
                       check (confidence in ('high','medium','low')),
  data_status        text not null default 'current'
                       check (data_status in ('current','stale','needs_review','unavailable')),
  retrieved_at       timestamptz,
  last_verified_at   timestamptz,
  notes              text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (jurisdiction_id, zone_code, project_type, version)
);

-- ============================================================================
-- 7. rule_attributes - per-field structured value + full provenance. This is
--    where the "every substantive field carries provenance" rule is honored.
-- ============================================================================
create table rule_attributes (
  id                  uuid primary key default gen_random_uuid(),
  zoning_rule_id      uuid not null references zoning_rules(id) on delete cascade,
  field_name          text not null,
  value_json          jsonb not null,
  value_numeric       numeric,          -- convenience mirror for numeric fields
  unit                text,
  operator            text
                        check (operator is null or operator in ('gte','lte','eq','must_equal','floor','ceiling')),
  state_baseline_id   uuid references state_rule_baselines(id) on delete set null,
  compliance_flag     text not null default 'needs_review'
                        check (compliance_flag in (
                          'matches_state_baseline','possibly_more_restrictive_than_state_baseline',
                          'needs_review','not_applicable')),
  source_url          text,
  source_title        text,
  source_section      text,
  source_layer        text,
  retrieved_at        timestamptz,
  last_verified_at    timestamptz,
  confidence          text not null default 'medium'
                        check (confidence in ('high','medium','low')),
  data_status         text not null default 'current'
                        check (data_status in ('current','stale','needs_review','unavailable')),
  notes               text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (zoning_rule_id, field_name)
);

-- ============================================================================
-- 8. parcels - APN + geometry (MultiPolygon) + centroid (Point) + area_sqft,
--    with source provenance. Never approximated as exact (see data_status).
-- ============================================================================
create table parcels (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid not null references jurisdictions(id) on delete cascade,
  apn                text not null,
  situs_address      text,
  normalized_address text,
  geom               geometry(MultiPolygon, 4326),
  centroid           geometry(Point, 4326),
  area_sqft          numeric,
  source_registry_id uuid references source_registry(id) on delete set null,
  source_snapshot_id uuid references source_snapshots(id) on delete set null,
  source_url         text,
  source_layer       text,
  raw_attributes     jsonb not null default '{}'::jsonb,
  confidence         text not null default 'medium'
                       check (confidence in ('high','medium','low')),
  data_status        text not null default 'current'
                       check (data_status in ('current','stale','needs_review','unavailable')),
  retrieved_at       timestamptz,
  last_verified_at   timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (jurisdiction_id, apn)
);

-- ============================================================================
-- 9. zoning_districts - zoning polygons for the spatial join (step C).
-- ============================================================================
create table zoning_districts (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid not null references jurisdictions(id) on delete cascade,
  zone_code          text not null,
  zone_name          text,
  zone_category      text,
  geom               geometry(MultiPolygon, 4326),
  source_registry_id uuid references source_registry(id) on delete set null,
  source_snapshot_id uuid references source_snapshots(id) on delete set null,
  source_url         text,
  source_layer       text,
  raw_attributes     jsonb not null default '{}'::jsonb,
  confidence         text not null default 'medium'
                       check (confidence in ('high','medium','low')),
  data_status        text not null default 'current'
                       check (data_status in ('current','stale','needs_review','unavailable')),
  retrieved_at       timestamptz,
  last_verified_at   timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- ============================================================================
-- 10. overlay_features - hazard/overlay polygons (flood, fire, historic,
--     coastal, hillside, environmental, hpoz, other). Generic geometry so a
--     single table holds polygons/multipolygons from heterogeneous sources.
--     jurisdiction_id null for statewide layers (FEMA, CAL FIRE).
-- ============================================================================
create table overlay_features (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid references jurisdictions(id) on delete cascade,
  overlay_type       text not null
                       check (overlay_type in (
                         'flood','fire','historic','coastal','hillside',
                         'environmental','hpoz','other')),
  name               text,
  designation        text,          -- e.g. FEMA zone AE, FHSZ Very High
  geom               geometry(Geometry, 4326),
  raw_feature_id     text,          -- source feature id, preserved verbatim
  raw_value          jsonb not null default '{}'::jsonb,
  source_registry_id uuid references source_registry(id) on delete set null,
  source_snapshot_id uuid references source_snapshots(id) on delete set null,
  source_url         text,
  source_layer       text,
  confidence         text not null default 'medium'
                       check (confidence in ('high','medium','low')),
  data_status        text not null default 'current'
                       check (data_status in ('current','stale','needs_review','unavailable')),
  retrieved_at       timestamptz,
  last_verified_at   timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- ============================================================================
-- 11. property_analyses - one completed (or attempted) feasibility analysis.
--     request_fingerprint powers the 24h idempotent cache / no-double-bill rule.
--     Privacy: not publicly readable (RLS in 0006).
-- ============================================================================
create table property_analyses (
  id                  uuid primary key default gen_random_uuid(),
  request_fingerprint text not null,   -- hash(consumer + normalized address + project_type + window)
  idempotency_key     text,
  share_token         text unique,     -- optional public shareable-result token
  consumer_id         text,            -- hashed/opaque consumer identifier
  provider            text not null default 'direct'
                        check (provider in ('rapidapi','direct','portal')),
  plan                text,
  input_address       text not null,
  normalized_address  text,
  geocode             geometry(Point, 4326),
  project_type        text not null
                        check (project_type in (
                          'detached_adu','attached_adu','garage_conversion',
                          'jadu','sb9_duplex','sb9_urban_lot_split')),
  target_sqft         numeric,
  bedrooms            integer,
  proposed_height_ft  numeric,
  existing_structure  boolean,
  options             jsonb not null default '{}'::jsonb,
  jurisdiction_id     uuid references jurisdictions(id) on delete set null,
  parcel_id           uuid references parcels(id) on delete set null,
  coverage_status     text
                        check (coverage_status is null or coverage_status in (
                          'planned','ingesting','production','deprecated')),
  feasibility_status  text
                        check (feasibility_status is null or feasibility_status in (
                          'likely_feasible','likely_constrained',
                          'needs_professional_review','insufficient_data')),
  score               numeric,         -- omitted from response unless explainable
  analysis_version    text,
  result_json         jsonb not null default '{}'::jsonb,
  disclaimer          text,
  billable            boolean not null default false,
  billed              boolean not null default false,
  cache_hit           boolean not null default false,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- ============================================================================
-- 12. analysis_findings - per-field, source-linked findings that compose a
--     property_analysis (constraints, eligibility, overlays, assumptions,
--     limitations). Carries full provenance like rule_attributes.
-- ============================================================================
create table analysis_findings (
  id                   uuid primary key default gen_random_uuid(),
  property_analysis_id uuid not null references property_analyses(id) on delete cascade,
  finding_type         text not null
                         check (finding_type in (
                           'parcel','zoning','constraint','eligibility','overlay',
                           'envelope','assumption','limitation')),
  project_path         text
                         check (project_path is null or project_path in (
                           'detached_adu','attached_adu','garage_conversion',
                           'jadu','sb9_duplex','sb9_urban_lot_split')),
  field_name           text,
  title                text,
  detail               text,
  value_json           jsonb,
  feasibility_status   text
                         check (feasibility_status is null or feasibility_status in (
                           'likely_feasible','likely_constrained',
                           'needs_professional_review','insufficient_data')),
  compliance_flag      text
                         check (compliance_flag is null or compliance_flag in (
                           'matches_state_baseline','possibly_more_restrictive_than_state_baseline',
                           'needs_review','not_applicable')),
  rule_attribute_id    uuid references rule_attributes(id) on delete set null,
  state_baseline_id    uuid references state_rule_baselines(id) on delete set null,
  source_url           text,
  source_title         text,
  source_section       text,
  source_layer         text,
  retrieved_at         timestamptz,
  last_verified_at     timestamptz,
  confidence           text
                         check (confidence is null or confidence in ('high','medium','low')),
  data_status          text
                         check (data_status is null or data_status in (
                           'current','stale','needs_review','unavailable')),
  sort_order           integer not null default 0,
  created_at           timestamptz not null default now()
);

-- ============================================================================
-- 13. ingest_runs - one row per ingestion / QA job execution.
-- ============================================================================
create table ingest_runs (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid references jurisdictions(id) on delete set null,
  source_registry_id uuid references source_registry(id) on delete set null,
  run_type           text not null
                       check (run_type in (
                         'parcels','zoning','overlays','code','baselines','qa','full')),
  status             text not null default 'pending'
                       check (status in ('pending','running','success','failed','partial','cancelled')),
  triggered_by       text,
  started_at         timestamptz,
  finished_at        timestamptz,
  records_processed  integer not null default 0,
  records_inserted   integer not null default 0,
  records_updated    integer not null default 0,
  records_failed     integer not null default 0,
  error_message      text,
  stats              jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);

-- ============================================================================
-- 14. qa_issues - QA queue items (state-baseline conflicts, LLM extraction
--     candidates needing review, source discrepancies).
-- ============================================================================
create table qa_issues (
  id                 uuid primary key default gen_random_uuid(),
  jurisdiction_id    uuid references jurisdictions(id) on delete set null,
  ingest_run_id      uuid references ingest_runs(id) on delete set null,
  source_registry_id uuid references source_registry(id) on delete set null,
  zoning_rule_id     uuid references zoning_rules(id) on delete set null,
  rule_attribute_id  uuid references rule_attributes(id) on delete set null,
  issue_type         text not null,
  severity           text not null default 'warning'
                       check (severity in ('info','warning','critical')),
  status             text not null default 'open'
                       check (status in ('open','in_review','resolved','wont_fix','dismissed')),
  detected_by        text
                       check (detected_by is null or detected_by in (
                         'state_baseline_check','llm_qa','source_diff','human','automated')),
  field_name         text,
  expected_value     text,
  observed_value     text,
  description        text,
  resolution_notes   text,
  resolved_at        timestamptz,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

-- ============================================================================
-- 15. api_usage_events - privacy-minimized metering events. No PII, no full
--     address; consumer_id is opaque/hashed. Not publicly readable (RLS in 0006).
-- ============================================================================
create table api_usage_events (
  id                  uuid primary key default gen_random_uuid(),
  consumer_id         text not null,   -- opaque/hashed consumer identifier
  provider            text not null default 'direct'
                        check (provider in ('rapidapi','direct','portal')),
  plan                text,
  endpoint            text not null,
  method              text,
  project_type        text
                        check (project_type is null or project_type in (
                          'detached_adu','attached_adu','garage_conversion',
                          'jadu','sb9_duplex','sb9_urban_lot_split')),
  jurisdiction_slug   text,
  analysis_id         uuid references property_analyses(id) on delete set null,
  request_fingerprint text,
  status_code         integer,
  billable            boolean not null default false,
  billed              boolean not null default false,
  cache_hit           boolean not null default false,
  response_time_ms    integer,
  created_at          timestamptz not null default now()
);

-- ============================================================================
-- 16. changelog_entries - public per-city update history.
-- ============================================================================
create table changelog_entries (
  id              uuid primary key default gen_random_uuid(),
  jurisdiction_id uuid references jurisdictions(id) on delete set null,
  entry_type      text not null
                    check (entry_type in (
                      'coverage','rule_update','source_update','correction','release','other')),
  title           text not null,
  summary         text,
  details         jsonb not null default '{}'::jsonb,
  version         text,
  source_url      text,
  published_at    timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- updated_at triggers on mutable tables. (source_snapshots, analysis_findings,
-- ingest_runs, api_usage_events are append-only / event tables with no
-- updated_at column.)
-- ----------------------------------------------------------------------------
create trigger trg_jurisdictions_updated_at        before update on jurisdictions        for each row execute function set_updated_at();
create trigger trg_source_registry_updated_at      before update on source_registry      for each row execute function set_updated_at();
create trigger trg_zoning_sections_updated_at      before update on zoning_sections      for each row execute function set_updated_at();
create trigger trg_state_rule_baselines_updated_at before update on state_rule_baselines for each row execute function set_updated_at();
create trigger trg_zoning_rules_updated_at         before update on zoning_rules         for each row execute function set_updated_at();
create trigger trg_rule_attributes_updated_at      before update on rule_attributes      for each row execute function set_updated_at();
create trigger trg_parcels_updated_at              before update on parcels              for each row execute function set_updated_at();
create trigger trg_zoning_districts_updated_at     before update on zoning_districts     for each row execute function set_updated_at();
create trigger trg_overlay_features_updated_at     before update on overlay_features     for each row execute function set_updated_at();
create trigger trg_property_analyses_updated_at    before update on property_analyses    for each row execute function set_updated_at();
create trigger trg_qa_issues_updated_at            before update on qa_issues            for each row execute function set_updated_at();
create trigger trg_changelog_entries_updated_at    before update on changelog_entries    for each row execute function set_updated_at();
