// API key authentication + quota enforcement.
//
// Flow for every request:
//   1. Read the raw key from `Authorization: Bearer <key>` or `x-api-key`.
//   2. sha256-hash it (keys are stored only as hashes in api_keys.key_hash).
//   3. Look up the (non-revoked) key row to get its id for usage logging.
//   4. Call the increment_api_usage(key_hash) RPC, which atomically rolls the
//      monthly window, checks the tier quota, and increments the counter.
//   5. Map the RPC result to allow / 401 / 429.
//
// increment_api_usage returns (allowed boolean, tier api_tier, requests_this_month int).
// It returns allowed=false, tier=null when the key hash is unknown/revoked.

import type { SupabaseClient } from "@supabase/supabase-js";

export type ApiTier = "free" | "starter" | "pro" | "enterprise";

// Monthly quotas per tier. Mirrors increment_api_usage() in 0001_initial_schema.sql.
export const TIER_LIMITS: Record<ApiTier, number> = {
  free: 50,
  starter: 1000,
  pro: 10000,
  enterprise: 2147483647,
};

export interface AuthSuccess {
  ok: true;
  apiKeyId: string;
  tier: ApiTier;
  requestsThisMonth: number;
  limit: number;
}

export interface AuthFailure {
  ok: false;
  status: number; // 401 or 429
  body: Record<string, unknown>;
  // Present only when the key was valid but over quota (so the caller can still
  // log the 429 against a real api_key_id). Null when the key was invalid.
  apiKeyId: string | null;
}

export type AuthResult = AuthSuccess | AuthFailure;

// Extract the raw API key from the request headers.
export function extractApiKey(req: Request): string | null {
  const authHeader = req.headers.get("authorization");
  if (authHeader) {
    const match = authHeader.match(/^Bearer\s+(.+)$/i);
    if (match) return match[1].trim();
  }
  const apiKeyHeader = req.headers.get("x-api-key");
  if (apiKeyHeader) return apiKeyHeader.trim();
  return null;
}

// SHA-256 hex digest using the Web Crypto API (available in the Deno runtime).
export async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function authenticate(
  client: SupabaseClient,
  req: Request,
): Promise<AuthResult> {
  const rawKey = extractApiKey(req);
  if (!rawKey) {
    return {
      ok: false,
      status: 401,
      apiKeyId: null,
      body: {
        error: "unauthorized",
        message:
          "Missing API key. Provide it via 'Authorization: Bearer <key>' or the 'x-api-key' header.",
      },
    };
  }

  const keyHash = await sha256Hex(rawKey);

  // Resolve the api_key id up front so we can attribute usage logs even for a
  // 429. A revoked or unknown key yields no row and is treated as unauthorized.
  const { data: keyRow, error: keyErr } = await client
    .from("api_keys")
    .select("id, tier, revoked")
    .eq("key_hash", keyHash)
    .eq("revoked", false)
    .maybeSingle();

  if (keyErr) {
    return {
      ok: false,
      status: 401,
      apiKeyId: null,
      body: {
        error: "unauthorized",
        message: "API key could not be validated.",
      },
    };
  }

  if (!keyRow) {
    return {
      ok: false,
      status: 401,
      apiKeyId: null,
      body: {
        error: "unauthorized",
        message: "Invalid or revoked API key.",
      },
    };
  }

  // Atomically roll the window, check quota, and increment.
  const { data: rpcData, error: rpcErr } = await client.rpc(
    "increment_api_usage",
    { p_key_hash: keyHash },
  );

  if (rpcErr) {
    return {
      ok: false,
      status: 401,
      apiKeyId: keyRow.id as string,
      body: {
        error: "unauthorized",
        message: "API key usage could not be recorded.",
      },
    };
  }

  // The RPC returns a table; supabase-js yields it as an array of rows.
  const row = Array.isArray(rpcData) ? rpcData[0] : rpcData;

  if (!row || (row.allowed === false && !row.tier)) {
    // Unknown / revoked between the two calls: treat as unauthorized.
    return {
      ok: false,
      status: 401,
      apiKeyId: keyRow.id as string,
      body: {
        error: "unauthorized",
        message: "Invalid or revoked API key.",
      },
    };
  }

  const tier = row.tier as ApiTier;
  const requestsThisMonth = Number(row.requests_this_month ?? 0);
  const limit = TIER_LIMITS[tier] ?? 0;

  if (row.allowed === false) {
    return {
      ok: false,
      status: 429,
      apiKeyId: keyRow.id as string,
      body: {
        error: "quota_exceeded",
        message:
          "Monthly request quota exceeded for your plan. Upgrade your tier or wait for the next billing cycle.",
        tier,
        limit,
        requests_this_month: requestsThisMonth,
      },
    };
  }

  return {
    ok: true,
    apiKeyId: keyRow.id as string,
    tier,
    requestsThisMonth,
    limit,
  };
}
