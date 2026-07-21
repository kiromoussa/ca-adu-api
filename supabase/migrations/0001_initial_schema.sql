-- CA ADU Zoning API - initial schema
-- Tables: cities, zoning_sections, adu_rules, api_keys, usage_logs, qa_alerts
-- State-law baselines documented inline per field (AB 2221, SB 897, SB 9, Gov. Code 66310-66342).

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- enums
-- ---------------------------------------------------------------------------
create type publisher_type as enum ('alp', 'municode');
create type compliance_flag as enum ('compliant', 'more_restrictive', 'needs_review');
create type api_tier as enum ('free', 'starter', 'pro', 'enterprise');

-- ---------------------------------------------------------------------------
-- cities
-- ---------------------------------------------------------------------------
create table cities (
  id              uuid primary key default gen_random_uuid(),
  name            text not null unique,
  slug            text not null unique,
  publisher_type  publisher_type not null,
  base_url        text not null,
  last_scraped_at timestamptz,
  created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- zoning_sections - raw scraped municipal code text
-- ---------------------------------------------------------------------------
create table zoning_sections (
  id             uuid primary key default gen_random_uuid(),
  city_id        uuid not null references cities(id) on delete cascade,
  title_number   text,
  chapter_number text,
  section_number text,
  section_url    text not null,
  raw_text       text,
  content_hash   text,                 -- sha256 of raw_text for change detection
  last_updated   timestamptz not null default now(),
  created_at     timestamptz not null default now(),
  unique (city_id, section_url)
);

-- ---------------------------------------------------------------------------
-- adu_rules - core product table (structured, state-law-validated fields)
-- ---------------------------------------------------------------------------
create table adu_rules (
  id           uuid primary key default gen_random_uuid(),
  city_id      uuid not null references cities(id) on delete cascade,
  zone_district text not null,          -- e.g. R-1, RS

  -- heights (numeric ft)
  max_height_detached_standard_ft numeric,   -- state floor 16 (AB 2221)
  max_height_near_transit_ft      numeric,   -- state floor 18 (AB 2221/SB 897)
  max_height_multifamily_lot_ft   numeric,   -- state floor 18 (AB 2221)
  max_height_attached_ft          numeric,   -- state ceiling 25 or zone limit (AB 2221)

  -- setbacks
  side_rear_setback_min_ft   numeric,        -- state ceiling 4 (AB 2221)
  front_setback_restriction  boolean,        -- must be false (AB 2221)

  -- occupancy / JADU
  owner_occupancy_required_adu   boolean,    -- must be false (Gov 66315/66323)
  owner_occupancy_required_jadu  boolean,    -- conditional on shared sanitation (Gov 66333(b))
  jadu_allowed                   boolean,    -- must be true (Gov 66333)
  jadu_separate_sale_allowed     boolean,    -- must be false (Gov 66333(c)(1))
  adu_condo_sale_allowed         boolean,    -- AB1033 opt-in

  -- parking / permitting
  parking_required             boolean,      -- false near transit/historic (SB 897)
  demolition_permit_concurrent boolean,      -- must be true (SB 897)
  permit_review_days           numeric,      -- must be <=60 (SB 897/AB 2221)
  fire_sprinkler_trigger       boolean,      -- must be false (SB 897)

  -- fees / size
  impact_fee_exempt_sqft_threshold numeric,  -- 750 (AB68/SB13)
  max_size_sqft_1br            numeric,       -- >=850
  max_size_sqft_2br            numeric,       -- >=1000
  max_size_sqft_general_cap   numeric,        -- up to 1200

  -- misc compliance
  nonconforming_zoning_denial_allowed boolean, -- must be false (SB 897)
  pre_2018_unpermitted_adu_amnesty    boolean, -- must be true (SB 897)

  -- SB9
  sb9_duplex_ministerial    boolean,          -- SB 9
  sb9_lot_split_min_lot_sqft numeric,         -- 1200 (SB 9)
  sb9_lot_split_ratio       numeric,          -- 0.4 (SB 9)
  sb9_one_split_per_owner   boolean,          -- true (SB 9)

  source_section_id uuid references zoning_sections(id) on delete set null,
  compliance_flag   compliance_flag not null default 'needs_review',
  compliance_notes  jsonb,                    -- per-field validation detail
  last_validated_at timestamptz,
  created_at        timestamptz not null default now(),
  unique (city_id, zone_district)
);

-- ---------------------------------------------------------------------------
-- api_keys
-- ---------------------------------------------------------------------------
create table api_keys (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references auth.users(id) on delete cascade,
  name                text,
  key_hash            text not null unique,   -- sha256 of the raw key; raw shown once on creation
  key_prefix          text not null,          -- first chars for dashboard display (e.g. adu_live_ab12)
  tier                api_tier not null default 'free',
  requests_this_month integer not null default 0,
  quota_reset_at      timestamptz not null default date_trunc('month', now()) + interval '1 month',
  stripe_customer_id     text,
  stripe_subscription_id text,
  revoked             boolean not null default false,
  created_at          timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- usage_logs
-- ---------------------------------------------------------------------------
create table usage_logs (
  id          uuid primary key default gen_random_uuid(),
  api_key_id  uuid not null references api_keys(id) on delete cascade,
  endpoint    text not null,
  city_id     uuid references cities(id) on delete set null,
  status_code integer,
  billable    boolean not null default true,
  created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- qa_alerts - HCD cross-check discrepancies (Prompt 6)
-- ---------------------------------------------------------------------------
create table qa_alerts (
  id            uuid primary key default gen_random_uuid(),
  city_id       uuid references cities(id) on delete set null,
  source        text not null,           -- 'hcd_apr' | 'hcd_ordinance_letter'
  field         text,
  scraped_value text,
  hcd_finding   text,
  severity      text not null default 'info',   -- info | warning | critical
  resolved      boolean not null default false,
  created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- indexes
-- ---------------------------------------------------------------------------
create index idx_zoning_sections_city on zoning_sections (city_id);
create index idx_adu_rules_city on adu_rules (city_id);
create index idx_adu_rules_zone on adu_rules (zone_district);
create index idx_adu_rules_city_zone on adu_rules (city_id, zone_district);
create index idx_adu_rules_flag on adu_rules (compliance_flag);
create index idx_api_keys_user on api_keys (user_id);
create index idx_api_keys_hash on api_keys (key_hash);
create index idx_usage_logs_key on usage_logs (api_key_id);
create index idx_usage_logs_created on usage_logs (created_at);
create index idx_qa_alerts_city on qa_alerts (city_id);

-- ---------------------------------------------------------------------------
-- helper: atomic quota increment used by the API layer
-- ---------------------------------------------------------------------------
create or replace function increment_api_usage(p_key_hash text)
returns table (allowed boolean, tier api_tier, requests_this_month integer)
language plpgsql
security definer
set search_path = public
as $$
declare
  v_key   api_keys%rowtype;
  v_limit integer;
begin
  select * into v_key from api_keys where key_hash = p_key_hash and revoked = false for update;
  if not found then
    return query select false, null::api_tier, 0; return;
  end if;

  -- roll the monthly window if elapsed
  if now() >= v_key.quota_reset_at then
    update api_keys
      set requests_this_month = 0,
          quota_reset_at = date_trunc('month', now()) + interval '1 month'
      where id = v_key.id
      returning * into v_key;
  end if;

  v_limit := case v_key.tier
    when 'free' then 50
    when 'starter' then 1000
    when 'pro' then 10000
    when 'enterprise' then 2147483647
  end;

  if v_key.requests_this_month >= v_limit then
    return query select false, v_key.tier, v_key.requests_this_month; return;
  end if;

  update api_keys set requests_this_month = requests_this_month + 1 where id = v_key.id
    returning * into v_key;

  return query select true, v_key.tier, v_key.requests_this_month;
end;
$$;
