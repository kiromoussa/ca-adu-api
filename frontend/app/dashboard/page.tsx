import type { Metadata } from "next";
import type { ApiTier } from "@/lib/database.types";
import { TIER_QUOTAS } from "@/lib/pricing";
import { createClient } from "@/lib/supabase/server";
import DashboardClient, {
  type DashboardData,
  type KeyRow
} from "./dashboard-client";
import LoginForm from "./login-form";
import type { UsageBucket } from "./usage-chart";

export const metadata: Metadata = {
  title: "Dashboard - CA ADU Zoning API"
};

// Force dynamic render; this page depends on the request's auth cookies.
export const dynamic = "force-dynamic";

const TIER_RANK: Record<ApiTier, number> = {
  free: 0,
  starter: 1,
  pro: 2,
  enterprise: 3
};

function highestTier(tiers: ApiTier[]): ApiTier {
  return tiers.reduce<ApiTier>(
    (best, t) => (TIER_RANK[t] > TIER_RANK[best] ? t : best),
    "free"
  );
}

function buildUsageBuckets(timestamps: string[], days = 30): UsageBucket[] {
  const buckets: UsageBucket[] = [];
  const counts = new Map<string, number>();

  for (const ts of timestamps) {
    const key = ts.slice(0, 10); // YYYY-MM-DD
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const today = new Date();
  today.setUTCHours(0, 0, 0, 0);

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setUTCDate(today.getUTCDate() - i);
    const iso = d.toISOString().slice(0, 10);
    buckets.push({
      fullLabel: iso,
      label: iso.slice(5), // MM-DD
      count: counts.get(iso) ?? 0
    });
  }

  return buckets;
}

export default async function DashboardPage() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return <LoginForm />;
  }

  // RLS restricts these reads to the signed-in user's own rows.
  const { data: keyRows } = await supabase
    .from("api_keys")
    .select(
      "id, name, key_prefix, tier, revoked, requests_this_month, quota_reset_at, stripe_subscription_id, created_at"
    )
    .order("created_at", { ascending: false });

  const keys = keyRows ?? [];
  const keyIds = keys.map((k) => k.id);

  let usageTimestamps: string[] = [];
  if (keyIds.length > 0) {
    const since = new Date();
    since.setUTCDate(since.getUTCDate() - 30);
    const { data: logs } = await supabase
      .from("usage_logs")
      .select("created_at")
      .in("api_key_id", keyIds)
      .gte("created_at", since.toISOString())
      .order("created_at", { ascending: true });
    usageTimestamps = (logs ?? []).map((l) => l.created_at);
  }

  const activeKeys = keys.filter((k) => !k.revoked);
  const currentTier = highestTier(activeKeys.map((k) => k.tier as ApiTier));
  const requestsThisMonth = activeKeys.reduce(
    (sum, k) => sum + (k.requests_this_month ?? 0),
    0
  );
  const quota = TIER_QUOTAS[currentTier];
  const billingActive = keys.some((k) => Boolean(k.stripe_subscription_id));
  const quotaResetAt =
    activeKeys.length > 0 ? activeKeys[0].quota_reset_at ?? null : null;

  const data: DashboardData = {
    email: user.email ?? "Signed in",
    currentTier,
    quota,
    requestsThisMonth,
    quotaResetAt,
    billingActive,
    keys: keys.map(
      (k): KeyRow => ({
        id: k.id,
        name: k.name,
        key_prefix: k.key_prefix,
        tier: k.tier as ApiTier,
        revoked: k.revoked,
        requests_this_month: k.requests_this_month ?? 0,
        created_at: k.created_at
      })
    ),
    usage: buildUsageBuckets(usageTimestamps, 30)
  };

  return <DashboardClient data={data} />;
}
