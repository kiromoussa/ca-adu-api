-- ============================================================================
-- 0006_rls_indexes.sql
-- Indexes (GIST spatial + B-tree lookup paths) and Row Level Security for the
-- ADU Atlas schema created in 0005.
--
-- RLS policy model:
--   - service_role has full read/write on every table (it also bypasses RLS on
--     Supabase; the explicit FOR ALL policy makes the intent auditable).
--   - Public catalog tables get anon/authenticated SELECT: jurisdictions,
--     zoning_rules, rule_attributes, changelog_entries, state_rule_baselines.
--   - Everything else has RLS enabled with NO public policy, so anon/
--     authenticated cannot read or write. In particular property_analyses and
--     api_usage_events (which hold request/consumer data) are never publicly
--     readable; the API serves individual analyses through the service role.
-- ============================================================================

set search_path = public, extensions;

-- ----------------------------------------------------------------------------
-- Spatial indexes (GIST) on every geometry column.
-- ----------------------------------------------------------------------------
create index if not exists idx_jurisdictions_boundary_gist   on jurisdictions     using gist (boundary);
create index if not exists idx_jurisdictions_centroid_gist   on jurisdictions     using gist (centroid);
create index if not exists idx_parcels_geom_gist             on parcels           using gist (geom);
create index if not exists idx_parcels_centroid_gist         on parcels           using gist (centroid);
create index if not exists idx_zoning_districts_geom_gist    on zoning_districts  using gist (geom);
create index if not exists idx_overlay_features_geom_gist    on overlay_features  using gist (geom);
create index if not exists idx_property_analyses_geocode_gist on property_analyses using gist (geocode);

-- ----------------------------------------------------------------------------
-- B-tree indexes on lookup paths.
-- ----------------------------------------------------------------------------
-- jurisdictions
create index if not exists idx_jurisdictions_slug            on jurisdictions (slug);
create index if not exists idx_jurisdictions_coverage_status on jurisdictions (coverage_status);

-- source_registry
create index if not exists idx_source_registry_jurisdiction  on source_registry (jurisdiction_id);
create index if not exists idx_source_registry_type          on source_registry (source_type);
create index if not exists idx_source_registry_provider      on source_registry (provider);

-- source_snapshots
create index if not exists idx_source_snapshots_registry     on source_snapshots (source_registry_id);
create index if not exists idx_source_snapshots_jurisdiction on source_snapshots (jurisdiction_id);
create index if not exists idx_source_snapshots_content_hash on source_snapshots (content_hash);
create index if not exists idx_source_snapshots_retrieved_at on source_snapshots (retrieved_at);

-- zoning_sections
create index if not exists idx_zoning_sections_jurisdiction  on zoning_sections (jurisdiction_id);
create index if not exists idx_zoning_sections_snapshot      on zoning_sections (source_snapshot_id);

-- state_rule_baselines
create index if not exists idx_state_baselines_field         on state_rule_baselines (field_name);

-- zoning_rules
create index if not exists idx_zoning_rules_lookup           on zoning_rules (jurisdiction_id, zone_code, project_type);
create index if not exists idx_zoning_rules_current          on zoning_rules (jurisdiction_id, is_current);
create index if not exists idx_zoning_rules_section          on zoning_rules (zoning_section_id);

-- rule_attributes
create index if not exists idx_rule_attributes_rule          on rule_attributes (zoning_rule_id);
create index if not exists idx_rule_attributes_field         on rule_attributes (field_name);
create index if not exists idx_rule_attributes_baseline      on rule_attributes (state_baseline_id);

-- parcels
create index if not exists idx_parcels_jurisdiction_apn      on parcels (jurisdiction_id, apn);

-- zoning_districts
create index if not exists idx_zoning_districts_jur_zone     on zoning_districts (jurisdiction_id, zone_code);

-- overlay_features
create index if not exists idx_overlay_features_type         on overlay_features (overlay_type);
create index if not exists idx_overlay_features_jurisdiction on overlay_features (jurisdiction_id);

-- property_analyses
create index if not exists idx_property_analyses_fingerprint on property_analyses (request_fingerprint);
create index if not exists idx_property_analyses_consumer    on property_analyses (consumer_id, created_at);
create index if not exists idx_property_analyses_idem        on property_analyses (idempotency_key);
create index if not exists idx_property_analyses_jurisdiction on property_analyses (jurisdiction_id);

-- analysis_findings
create index if not exists idx_analysis_findings_analysis    on analysis_findings (property_analysis_id);
create index if not exists idx_analysis_findings_type        on analysis_findings (finding_type);

-- ingest_runs
create index if not exists idx_ingest_runs_jurisdiction      on ingest_runs (jurisdiction_id);
create index if not exists idx_ingest_runs_status            on ingest_runs (status);
create index if not exists idx_ingest_runs_created_at        on ingest_runs (created_at);

-- qa_issues
create index if not exists idx_qa_issues_jurisdiction        on qa_issues (jurisdiction_id);
create index if not exists idx_qa_issues_status              on qa_issues (status);
create index if not exists idx_qa_issues_severity            on qa_issues (severity);

-- api_usage_events
create index if not exists idx_api_usage_events_consumer     on api_usage_events (consumer_id, created_at);
create index if not exists idx_api_usage_events_fingerprint  on api_usage_events (request_fingerprint);
create index if not exists idx_api_usage_events_analysis     on api_usage_events (analysis_id);

-- changelog_entries
create index if not exists idx_changelog_jurisdiction        on changelog_entries (jurisdiction_id);
create index if not exists idx_changelog_published_at        on changelog_entries (published_at);

-- ============================================================================
-- Row Level Security
-- ============================================================================
alter table jurisdictions        enable row level security;
alter table source_registry      enable row level security;
alter table source_snapshots     enable row level security;
alter table zoning_sections      enable row level security;
alter table state_rule_baselines enable row level security;
alter table zoning_rules         enable row level security;
alter table rule_attributes      enable row level security;
alter table parcels              enable row level security;
alter table zoning_districts     enable row level security;
alter table overlay_features     enable row level security;
alter table property_analyses    enable row level security;
alter table analysis_findings    enable row level security;
alter table ingest_runs          enable row level security;
alter table qa_issues            enable row level security;
alter table api_usage_events     enable row level security;
alter table changelog_entries    enable row level security;

-- ----------------------------------------------------------------------------
-- service_role: full access on every table. (service_role bypasses RLS; the
-- explicit policy documents the intended write surface.)
-- ----------------------------------------------------------------------------
create policy "service_role all jurisdictions"        on jurisdictions        for all to service_role using (true) with check (true);
create policy "service_role all source_registry"      on source_registry      for all to service_role using (true) with check (true);
create policy "service_role all source_snapshots"     on source_snapshots     for all to service_role using (true) with check (true);
create policy "service_role all zoning_sections"      on zoning_sections      for all to service_role using (true) with check (true);
create policy "service_role all state_rule_baselines" on state_rule_baselines for all to service_role using (true) with check (true);
create policy "service_role all zoning_rules"         on zoning_rules         for all to service_role using (true) with check (true);
create policy "service_role all rule_attributes"      on rule_attributes      for all to service_role using (true) with check (true);
create policy "service_role all parcels"              on parcels              for all to service_role using (true) with check (true);
create policy "service_role all zoning_districts"     on zoning_districts     for all to service_role using (true) with check (true);
create policy "service_role all overlay_features"     on overlay_features     for all to service_role using (true) with check (true);
create policy "service_role all property_analyses"    on property_analyses    for all to service_role using (true) with check (true);
create policy "service_role all analysis_findings"    on analysis_findings    for all to service_role using (true) with check (true);
create policy "service_role all ingest_runs"          on ingest_runs          for all to service_role using (true) with check (true);
create policy "service_role all qa_issues"            on qa_issues            for all to service_role using (true) with check (true);
create policy "service_role all api_usage_events"     on api_usage_events     for all to service_role using (true) with check (true);
create policy "service_role all changelog_entries"    on changelog_entries    for all to service_role using (true) with check (true);

-- ----------------------------------------------------------------------------
-- Public read on catalog tables (anon + authenticated). SELECT only.
-- ----------------------------------------------------------------------------
create policy "public read jurisdictions"        on jurisdictions        for select to anon, authenticated using (true);
create policy "public read zoning_rules"         on zoning_rules         for select to anon, authenticated using (true);
create policy "public read rule_attributes"      on rule_attributes      for select to anon, authenticated using (true);
create policy "public read changelog_entries"    on changelog_entries    for select to anon, authenticated using (true);
create policy "public read state_rule_baselines" on state_rule_baselines for select to anon, authenticated using (true);

-- All other tables (source_registry, source_snapshots, zoning_sections,
-- parcels, zoning_districts, overlay_features, property_analyses,
-- analysis_findings, ingest_runs, qa_issues, api_usage_events) intentionally
-- have NO anon/authenticated policy: only service_role may read or write them.
-- property_analyses and api_usage_events in particular are never public.
