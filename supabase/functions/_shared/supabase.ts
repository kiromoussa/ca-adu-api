// Service-role Supabase client used by the API layer.
//
// The Edge Functions read public data (cities, adu_rules) and write usage_logs
// / increment api_keys quota. Those writes are restricted to service_role by the
// RLS policies in 0002_rls.sql, so we authenticate with the service-role key.
//
// The raw service-role key is read from the environment (never hard-coded).
// Supabase injects SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY into the function
// runtime automatically; they can also be set via `supabase secrets set`.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let cached: SupabaseClient | null = null;

export function getServiceClient(): SupabaseClient {
  if (cached) return cached;

  const url = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");

  if (!url || !serviceRoleKey) {
    throw new Error(
      "Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in the function environment.",
    );
  }

  cached = createClient(url, serviceRoleKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
    },
  });

  return cached;
}
