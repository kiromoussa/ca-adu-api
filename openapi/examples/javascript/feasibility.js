// POST /v1/feasibility - run a preliminary feasibility analysis for one
// address and one project_type. This is the only billable endpoint: one
// completed analysis (terminal feasibility_status) is one billable unit.
// Errors, validation failures, and unsupported_coverage responses are not
// billed. Passing an Idempotency-Key makes retries safe.
//
// Run with: node feasibility.js
import { randomUUID } from "node:crypto";
import { aduAtlasRequest, AduAtlasApiError } from "./client.js";

async function main() {
  // Pick ONE auth mode.
  const config = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const requestBody = {
    address: "1234 S Main St, Los Angeles, CA 90015",
    project_type: "detached_adu",
    target_sqft: 800,
    bedrooms: 1,
    proposed_height_ft: 16,
    existing_structure: {
      type: "single_family",
      has_garage: true,
      year_built: 1948,
    },
    options: {
      near_transit: false,
      historic_property: false,
      include_envelope: true,
    },
  };

  try {
    const analysis = await aduAtlasRequest(config, "/v1/feasibility", {
      method: "POST",
      headers: { "Idempotency-Key": randomUUID() },
      body: JSON.stringify(requestBody),
    });

    console.log("analysis_id:", analysis.analysis_id);
    console.log("feasibility_status:", analysis.feasibility_status);
    console.log("disclaimer:", analysis.disclaimer);
  } catch (err) {
    if (err instanceof AduAtlasApiError) {
      // unsupported_coverage, quota_exceeded, validation_error, etc. are all
      // returned as this typed error and are never billed.
      console.error(`ADU Atlas API error [${err.status} ${err.code}]: ${err.message}`);
      return;
    }
    throw err;
  }
}

main();
