import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import type { Database } from "@/lib/database.types";
import { getPublicSupabaseAnonKey, getPublicSupabaseUrl } from "@/lib/env";

// Authenticated server client bound to the request cookies. RLS applies with
// the signed-in user's identity (auth.uid()).
export function createClient() {
  const cookieStore = cookies();

  return createServerClient<Database>(
    getPublicSupabaseUrl(),
    getPublicSupabaseAnonKey(),
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) => {
              cookieStore.set(name, value, options);
            });
          } catch {
            // Called from a Server Component where cookies are read-only.
            // Session refresh is handled by middleware, so this is safe to ignore.
          }
        }
      }
    }
  );
}
