"use client";

import { createBrowserClient } from "@supabase/ssr";
import type { Database } from "@/lib/database.types";
import { getPublicSupabaseAnonKey, getPublicSupabaseUrl } from "@/lib/env";

// Browser client. Uses the anon key only; RLS protects the data.
export function createClient() {
  return createBrowserClient<Database>(
    getPublicSupabaseUrl(),
    getPublicSupabaseAnonKey()
  );
}
