import "server-only";

import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import type { Database } from "@/lib/database.types";
import { getServerSupabaseUrl, getServiceRoleKey } from "@/lib/env";

// Service-role client. Bypasses RLS - use ONLY in server actions / route
// handlers, and always after verifying the caller's identity. Never import
// this into a client component.
export function createServiceClient() {
  return createSupabaseClient<Database>(
    getServerSupabaseUrl(),
    getServiceRoleKey(),
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false
      }
    }
  );
}
