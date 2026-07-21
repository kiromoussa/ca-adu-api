// GET /v1/jurisdictions/{slug}/rules - citywide and zone-level rules for a
// jurisdiction, each attribute carrying per-field provenance and a
// state-baseline compliance flag, plus citations and version history.
// Read-only, not billed.
//
// Run with: node jurisdiction_rules.js
import { aduAtlasRequest } from "./client.js";

async function main() {
  const config = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const slug = "los_angeles";
  const params = new URLSearchParams({ zone: "R1", project_type: "detached_adu" });

  const rules = await aduAtlasRequest(config, `/v1/jurisdictions/${slug}/rules?${params.toString()}`);

  for (const zone of rules.zones) {
    console.log(`Zone ${zone.zone_code}:`);
    for (const attr of zone.attributes) {
      console.log(`  ${attr.key} = ${attr.value} (${attr.compliance_flag || "n/a"})`);
    }
  }
}

main();
