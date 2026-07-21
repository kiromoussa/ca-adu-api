// GET /v1/health - service liveness, uptime, API/rules versions, and
// non-sensitive source freshness. No authentication required, not billed.
//
// Run with: npx tsx health.ts
export interface SourceFreshness {
  key: string;
  name?: string | null;
  data_status: "current" | "stale" | "needs_review" | "unavailable";
  last_refreshed_at?: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  uptime_seconds: number;
  api_version: string;
  rules_version?: string | null;
  sources?: SourceFreshness[];
}

async function main() {
  // No auth headers required for /v1/health, on either host.
  const res = await fetch("https://api.aduatlas.example.com/v1/health");
  const health = (await res.json()) as HealthResponse;

  console.log(`status: ${health.status} (api ${health.api_version})`);
  for (const source of health.sources ?? []) {
    console.log(`  ${source.key}: ${source.data_status}`);
  }
}

main();
