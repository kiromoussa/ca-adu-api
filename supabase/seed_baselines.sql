-- ============================================================================
-- seed_baselines.sql
-- Idempotent seed for:
--   (1) state_rule_baselines - every California statewide ADU/JADU/SB 9 floor
--       and ceiling from the product spec, with operator, value, legal citation,
--       source URL (HCD ADU Handbook), effective date, and verification date.
--   (2) jurisdictions - the 8 v1 target cities. Los Angeles is 'ingesting';
--       the other 7 are 'planned' until their sources + rules are ingested,
--       tested, and marked production.
--
-- Run after 0005 + 0006. Safe to re-run: ON CONFLICT upserts keep it current.
--
-- Operator legend (matches the CHECK on state_rule_baselines.operator):
--   floor      local value may not be LOWER than baseline (state minimum)
--   ceiling    local value may not be HIGHER than baseline (state maximum)
--   gte        local value must be >= baseline
--   lte        local value must be <= baseline
--   eq         local value must equal baseline (or, if conditional, see notes)
--   must_equal boolean field must equal baseline
-- ============================================================================

set search_path = public, extensions;

-- ----------------------------------------------------------------------------
-- (1) state_rule_baselines
-- ----------------------------------------------------------------------------
insert into state_rule_baselines
  (field_name, applies_to, operator, baseline_value_json, unit, legal_citation,
   description, source_url, source_title, effective_from, last_verified_at)
values
  ('max_height_detached_standard_ft',
     array['detached_adu'], 'floor', '16'::jsonb, 'ft', 'AB 2221 (Gov Code 66323)',
     'Local ordinances must allow at least 16 ft for a standard detached ADU.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('max_height_near_transit_ft',
     array['detached_adu','attached_adu'], 'floor', '18'::jsonb, 'ft', 'AB 2221 / SB 897 (Gov Code 66323)',
     'At least 18 ft must be allowed within one-half mile walking distance of a major transit stop or high-quality transit corridor.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('max_height_multifamily_lot_ft',
     array['detached_adu'], 'floor', '18'::jsonb, 'ft', 'AB 2221 (Gov Code 66323)',
     'At least 18 ft must be allowed for a detached ADU on a lot with an existing or proposed multifamily dwelling.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('max_height_attached_ft',
     array['attached_adu'], 'ceiling', '25'::jsonb, 'ft', 'AB 2221 (Gov Code 66323)',
     'Attached ADU height limit is 25 ft or the zone limit, whichever is lower; local may not exceed this state ceiling framing.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('side_rear_setback_min_ft',
     array['detached_adu','attached_adu','garage_conversion'], 'ceiling', '4'::jsonb, 'ft', 'AB 2221 (Gov Code 66323)',
     'Local side and rear setback requirements for an ADU may not exceed 4 ft.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('front_setback_restriction',
     array['detached_adu','attached_adu'], 'must_equal', 'false'::jsonb, null, 'AB 2221 (Gov Code 66323)',
     'A front setback requirement may not preclude construction of an ADU of at least 800 sqft; must not block such an ADU.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('owner_occupancy_required_adu',
     array['detached_adu','attached_adu','garage_conversion'], 'must_equal', 'false'::jsonb, null, 'Gov Code 66315 / 66323',
     'Owner-occupancy may not be required for an ADU (for permits through the statutory window).',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('owner_occupancy_required_jadu',
     array['jadu'], 'eq', '{"conditional": true, "condition": "owner occupancy required unless shared sanitation exemption applies"}'::jsonb, null, 'Gov Code 66333(b)',
     'Owner-occupancy is generally required for a JADU; the requirement is conditional on the shared-sanitation arrangement.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('jadu_allowed',
     array['jadu'], 'must_equal', 'true'::jsonb, null, 'Gov Code 66333',
     'A JADU must be allowed, limited to one per single-family dwelling lot.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('jadu_separate_sale_allowed',
     array['jadu'], 'must_equal', 'false'::jsonb, null, 'Gov Code 66333(c)(1)',
     'A JADU may not be sold or conveyed separately from the primary dwelling.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('parking_required',
     array['detached_adu','attached_adu','garage_conversion','jadu'], 'must_equal', 'false'::jsonb, null, 'SB 897 (Gov Code 66314/66323)',
     'No parking may be required near transit, in a historic district, within one block of car-share, and other statutory cases.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('demolition_permit_concurrent',
     array['garage_conversion','detached_adu','attached_adu'], 'must_equal', 'true'::jsonb, null, 'SB 897 (Gov Code 66323)',
     'A demolition permit for a detached garage replaced by an ADU must be reviewed and issued concurrently with the ADU permit.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('permit_review_days',
     array['detached_adu','attached_adu','garage_conversion','jadu'], 'lte', '60'::jsonb, 'days', 'SB 897 / AB 2221 (Gov Code 66317)',
     'A complete ADU/JADU application must be approved or denied ministerially within 60 days.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('fire_sprinkler_trigger',
     array['detached_adu','attached_adu','garage_conversion','jadu'], 'must_equal', 'false'::jsonb, null, 'SB 897 (Gov Code 66323)',
     'An ADU may not trigger a fire-sprinkler requirement if sprinklers are not required for the primary dwelling.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('impact_fee_exempt_sqft_threshold',
     array['detached_adu','attached_adu','garage_conversion','jadu'], 'eq', '750'::jsonb, 'sqft', 'AB 68 / SB 13 (Gov Code 66324)',
     'ADUs under 750 sqft are exempt from impact fees; larger ADUs are charged proportionally to the primary dwelling.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('max_size_sqft_1br',
     array['detached_adu','attached_adu'], 'gte', '850'::jsonb, 'sqft', 'Gov Code 66323',
     'Local size limits must allow at least 850 sqft for a one-bedroom ADU.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('max_size_sqft_2br',
     array['detached_adu','attached_adu'], 'gte', '1000'::jsonb, 'sqft', 'Gov Code 66323',
     'Local size limits must allow at least 1000 sqft for an ADU with two or more bedrooms.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('max_size_sqft_general_cap',
     array['detached_adu','attached_adu'], 'gte', '1200'::jsonb, 'sqft', 'Gov Code 66323',
     'General ADU size cap; local ordinances may allow up to 1200 sqft and may not cap below the statutory minimums.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2020-01-01', now()),

  ('nonconforming_zoning_denial_allowed',
     array['detached_adu','attached_adu','garage_conversion','jadu'], 'must_equal', 'false'::jsonb, null, 'SB 897 (Gov Code 66314)',
     'An ADU application may not be denied due to nonconforming zoning conditions or unpermitted structures unless a health/safety threat.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('pre_2018_unpermitted_adu_amnesty',
     array['detached_adu','attached_adu','garage_conversion','jadu'], 'must_equal', 'true'::jsonb, null, 'SB 897 (Gov Code 66332)',
     'Permit corrections for ADUs built before 2018 must be delayed for eligible existing unpermitted ADUs (amnesty).',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2023-01-01', now()),

  ('sb9_duplex_ministerial',
     array['sb9_duplex'], 'must_equal', 'true'::jsonb, null, 'SB 9 (Gov Code 65852.21)',
     'Ministerial approval of up to two units is required in single-family zones within an urbanized area or urban cluster.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2022-01-01', now()),

  ('sb9_lot_split_min_lot_sqft',
     array['sb9_urban_lot_split'], 'gte', '1200'::jsonb, 'sqft', 'SB 9 (Gov Code 66411.7)',
     'An SB 9 urban lot split must produce lots of at least 1200 sqft each.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2022-01-01', now()),

  ('sb9_lot_split_ratio',
     array['sb9_urban_lot_split'], 'gte', '0.4'::jsonb, 'ratio', 'SB 9 (Gov Code 66411.7)',
     'An SB 9 lot split may not create lots smaller than 40 percent of the original (60/40 maximum).',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2022-01-01', now()),

  ('sb9_one_split_per_owner',
     array['sb9_urban_lot_split'], 'must_equal', 'true'::jsonb, null, 'SB 9 (Gov Code 66411.7)',
     'An owner (and their affiliates) may exercise only one SB 9 urban lot split.',
     'https://www.hcd.ca.gov/building-standards/adu/handbook', 'HCD ADU Handbook',
     date '2022-01-01', now())
on conflict (field_name, effective_from) do update set
  applies_to          = excluded.applies_to,
  operator            = excluded.operator,
  baseline_value_json = excluded.baseline_value_json,
  unit                = excluded.unit,
  legal_citation      = excluded.legal_citation,
  description         = excluded.description,
  source_url          = excluded.source_url,
  source_title        = excluded.source_title,
  last_verified_at    = excluded.last_verified_at,
  updated_at          = now();

-- ----------------------------------------------------------------------------
-- (2) jurisdictions - 8 v1 targets. Los Angeles ingesting; others planned.
--     supported_project_types lists the six project types the API accepts.
-- ----------------------------------------------------------------------------
insert into jurisdictions
  (slug, name, jurisdiction_type, state_code, county, coverage_status, supported_project_types)
values
  ('los_angeles',  'Los Angeles',   'city', 'CA', 'Los Angeles',   'ingesting',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('san_diego',    'San Diego',     'city', 'CA', 'San Diego',     'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('san_jose',     'San Jose',      'city', 'CA', 'Santa Clara',   'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('san_francisco','San Francisco', 'city', 'CA', 'San Francisco', 'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('sacramento',   'Sacramento',    'city', 'CA', 'Sacramento',    'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('irvine',       'Irvine',        'city', 'CA', 'Orange',        'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('long_beach',   'Long Beach',    'city', 'CA', 'Los Angeles',   'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split']),
  ('oakland',      'Oakland',       'city', 'CA', 'Alameda',       'planned',
     array['detached_adu','attached_adu','garage_conversion','jadu','sb9_duplex','sb9_urban_lot_split'])
on conflict (slug) do update set
  name                    = excluded.name,
  county                  = excluded.county,
  coverage_status         = excluded.coverage_status,
  supported_project_types = excluded.supported_project_types,
  updated_at              = now();
