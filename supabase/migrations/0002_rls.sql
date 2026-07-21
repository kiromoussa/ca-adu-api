-- Row Level Security
-- Public data (cities, zoning_sections, adu_rules, qa_alerts) readable via anon key.
-- Writes restricted to service_role. api_keys/usage_logs are private to the owning user.

alter table cities          enable row level security;
alter table zoning_sections enable row level security;
alter table adu_rules       enable row level security;
alter table api_keys        enable row level security;
alter table usage_logs      enable row level security;
alter table qa_alerts       enable row level security;

-- ---- public read (anon + authenticated) -----------------------------------
create policy "public read cities"
  on cities for select using (true);

create policy "public read zoning_sections"
  on zoning_sections for select using (true);

create policy "public read adu_rules"
  on adu_rules for select using (true);

create policy "public read qa_alerts"
  on qa_alerts for select using (true);

-- ---- writes: service_role only ---------------------------------------------
-- service_role bypasses RLS entirely, so no write policies are granted to
-- anon/authenticated. The absence of insert/update/delete policies means only
-- service_role (which bypasses RLS) can mutate these tables. Made explicit:
create policy "service_role writes cities"
  on cities for all to service_role using (true) with check (true);
create policy "service_role writes zoning_sections"
  on zoning_sections for all to service_role using (true) with check (true);
create policy "service_role writes adu_rules"
  on adu_rules for all to service_role using (true) with check (true);
create policy "service_role writes qa_alerts"
  on qa_alerts for all to service_role using (true) with check (true);

-- ---- api_keys: owner-only --------------------------------------------------
create policy "owner reads own api_keys"
  on api_keys for select
  using (auth.uid() = user_id);

create policy "owner inserts own api_keys"
  on api_keys for insert
  with check (auth.uid() = user_id);

create policy "owner updates own api_keys"
  on api_keys for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "owner deletes own api_keys"
  on api_keys for delete
  using (auth.uid() = user_id);

-- ---- usage_logs: owner reads logs for their own keys -----------------------
create policy "owner reads own usage_logs"
  on usage_logs for select
  using (
    exists (
      select 1 from api_keys
      where api_keys.id = usage_logs.api_key_id
        and api_keys.user_id = auth.uid()
    )
  );

-- writes to api_keys/usage_logs from the API layer go through service_role.
create policy "service_role writes api_keys"
  on api_keys for all to service_role using (true) with check (true);
create policy "service_role writes usage_logs"
  on usage_logs for all to service_role using (true) with check (true);
