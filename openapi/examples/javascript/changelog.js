// GET /v1/changelog - public update history: ingestion runs, rule-version
// changes, and coverage changes, grouped by jurisdiction. Read-only, not
// billed.
//
// Run with: node changelog.js
import { aduAtlasRequest } from "./client.js";

async function main() {
  const config = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const params = new URLSearchParams({ jurisdiction: "los_angeles", limit: "20" });
  const changelog = await aduAtlasRequest(config, `/v1/changelog?${params.toString()}`);

  for (const entry of changelog.data) {
    console.log(`[${entry.occurred_at}] ${entry.jurisdiction_slug} - ${entry.change_type}: ${entry.summary}`);
  }
}

main();
