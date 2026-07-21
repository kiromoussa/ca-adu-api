// GET /v1/jurisdictions/{slug}/rules - citywide and zone-level rules for a
// jurisdiction, each attribute carrying per-field provenance and a
// state-baseline compliance flag, plus citations and version history.
// Read-only, not billed.
//
// Run with: npx tsx jurisdiction_rules.ts
import { aduAtlasRequest, type AduAtlasConfig } from "./client";

export interface RuleAttribute {
  key: string;
  value: number | boolean | string | null;
  unit?: string | null;
  state_baseline?: number | boolean | string | null;
  compliance_flag?: "compliant" | "needs_review" | "possibly_more_restrictive_than_state_baseline";
  provenance: Record<string, unknown>;
}

export interface JurisdictionRulesResponse {
  jurisdiction: Record<string, unknown>;
  citywide: RuleAttribute[];
  zones: Array<{ zone_code: string; zone_name?: string | null; attributes: RuleAttribute[] }>;
  citations: Record<string, unknown>[];
  version_history?: Record<string, unknown>[];
}

async function main() {
  const config: AduAtlasConfig = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const slug = "los_angeles";
  const params = new URLSearchParams({ zone: "R1", project_type: "detached_adu" });

  const rules = await aduAtlasRequest<JurisdictionRulesResponse>(
    config,
    `/v1/jurisdictions/${slug}/rules?${params.toString()}`,
  );

  for (const zone of rules.zones) {
    console.log(`Zone ${zone.zone_code}:`);
    for (const attr of zone.attributes) {
      console.log(`  ${attr.key} = ${attr.value} (${attr.compliance_flag ?? "n/a"})`);
    }
  }
}

main();
