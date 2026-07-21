-- Fix: "column reference \"requests_this_month\" is ambiguous" at runtime.
--
-- increment_api_usage() declares RETURNS TABLE (..., requests_this_month integer),
-- which creates an OUT variable named requests_this_month. In the UPDATE
--   set requests_this_month = requests_this_month + 1
-- the right-hand `requests_this_month` is ambiguous between that OUT variable and
-- the api_keys column. We keep the output column names (the API layer reads
-- allowed / tier / requests_this_month), and disambiguate by qualifying the
-- table column and setting #variable_conflict use_column.

create or replace function increment_api_usage(p_key_hash text)
returns table (allowed boolean, tier api_tier, requests_this_month integer)
language plpgsql
security definer
set search_path = public
as $$
#variable_conflict use_column
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

  update api_keys
    set requests_this_month = api_keys.requests_this_month + 1
    where id = v_key.id
    returning * into v_key;

  return query select true, v_key.tier, v_key.requests_this_month;
end;
$$;
