// GET /v1/jurisdictions - coverage status, supported project types, and the
// source update date for every registered jurisdiction. Read-only, not billed.
//
// Run with: node jurisdictions.js
import { aduAtlasRequest } from "./client.js";

async function main() {
  const config = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const result = await aduAtlasRequest(config, "/v1/jurisdictions");

  for (const jurisdiction of result.data) {
    console.log(
      `${jurisdiction.display_name || jurisdiction.name} (${jurisdiction.slug}): ${jurisdiction.coverage_status}`,
    );
  }
}

main();
