// GET /v1/analyses/{analysis_id} - retrieve a previously computed analysis.
// Private analyses require the same API key/consumer that created them; a
// public shareable analysis can instead be fetched with a share token and no
// API credentials at all. Read-only, not billed.
//
// Run with: npx tsx get_analysis.ts
import { aduAtlasRequest, AduAtlasApiError, type AduAtlasConfig } from "./client";
import type { FeasibilityResponse } from "./feasibility";

async function main() {
  const analysisId = "b8e6f9d2-4b7d-4b0e-9a45-1e6a9d5c9d2f";

  // Option A: authenticated retrieval of a private analysis.
  const config: AduAtlasConfig = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  try {
    const analysis = await aduAtlasRequest<FeasibilityResponse>(
      config,
      `/v1/analyses/${analysisId}`,
    );
    console.log("feasibility_status:", analysis.feasibility_status);
  } catch (err) {
    if (err instanceof AduAtlasApiError) {
      console.error(`ADU Atlas API error [${err.status} ${err.code}]: ${err.message}`);
    } else {
      throw err;
    }
  }

  // Option B: public shareable analysis via token, no API credentials.
  const shareToken = "shr_9k2m4p1qz7x3vb6n";
  const publicRes = await fetch(
    `https://api.aduatlas.example.com/v1/analyses/${analysisId}?token=${shareToken}`,
  );
  const publicAnalysis = (await publicRes.json()) as FeasibilityResponse;
  console.log("shared feasibility_status:", publicAnalysis.feasibility_status);
}

main();
