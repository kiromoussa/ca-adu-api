// Centralised environment access. Server-only values are read lazily so the
// browser bundle never trips over missing secrets.

export function getPublicSupabaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!url) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not set");
  }
  return url;
}

export function getPublicSupabaseAnonKey(): string {
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!key) {
    throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY is not set");
  }
  return key;
}

// Server only. Prefers SUPABASE_URL, falls back to the public URL.
export function getServerSupabaseUrl(): string {
  return process.env.SUPABASE_URL || getPublicSupabaseUrl();
}

export function getServiceRoleKey(): string {
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) {
    throw new Error("SUPABASE_SERVICE_ROLE_KEY is not set");
  }
  return key;
}

export function getStripeSecretKey(): string {
  const key = process.env.STRIPE_SECRET_KEY;
  if (!key) {
    throw new Error("STRIPE_SECRET_KEY is not set");
  }
  return key;
}

export function getStripeWebhookSecret(): string {
  const key = process.env.STRIPE_WEBHOOK_SECRET;
  if (!key) {
    throw new Error("STRIPE_WEBHOOK_SECRET is not set");
  }
  return key;
}

export function getSiteUrl(): string {
  return process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
}
