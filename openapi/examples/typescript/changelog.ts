// GET /v1/changelog - public update history: ingestion runs, rule-version
// changes, and coverage changes, grouped by jurisdiction. Read-only, not
// billed.
//
// Run with: npx tsx changelog.ts
import { aduAtlasRequest, type AduAtlasConfig } from "./client";

export interface ChangelogEntry {
  id: string;
  jurisdiction_slug: string;
  change_type:
    | "coverage_change"
    | "rule_update"
    | "source_ingested"
    | "source_refreshed"
    | "correction";
  summary: string;
  occurred_at: string;
}

export interface ChangelogResponse {
  data: ChangelogEntry[];
  count: number;
}

async function main() {
  const config: AduAtlasConfig = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const params = new URLSearchParams({ jurisdiction: "los_angeles", limit: "20" });
  const changelog = await aduAtlasRequest<ChangelogResponse>(
    config,
    `/v1/changelog?${params.toString()}`,
  );

  for (const entry of changelog.data) {
    console.log(`[${entry.occurred_at}] ${entry.jurisdiction_slug} - ${entry.change_type}: ${entry.summary}`);
  }
}

main();
