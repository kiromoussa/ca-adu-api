// GET /v1/jurisdictions - coverage status, supported project types, and the
// source update date for every registered jurisdiction. Read-only, not billed.
//
// Run with: npx tsx jurisdictions.ts
import { aduAtlasRequest, type AduAtlasConfig } from "./client";

export type CoverageStatus = "planned" | "ingesting" | "production";

export interface Jurisdiction {
  slug: string;
  name: string;
  display_name?: string;
  coverage_status: CoverageStatus;
  supported_project_types: string[];
  sources_last_updated_at?: string | null;
}

export interface JurisdictionList {
  data: Jurisdiction[];
  count: number;
}

async function main() {
  const config: AduAtlasConfig = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const result = await aduAtlasRequest<JurisdictionList>(config, "/v1/jurisdictions");

  for (const jurisdiction of result.data) {
    console.log(
      `${jurisdiction.display_name ?? jurisdiction.name} (${jurisdiction.slug}): ${jurisdiction.coverage_status}`,
    );
  }
}

main();
