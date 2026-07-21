// POST /v1/feasibility - run a preliminary feasibility analysis for one
// address and one project_type. This is the only billable endpoint: one
// completed analysis (terminal feasibility_status) is one billable unit.
// Errors, validation failures, and unsupported_coverage responses are not
// billed. Passing idempotencyKey makes retries safe.
//
// Run with: npx tsx feasibility.ts   (or compile with tsc, Node 18+)
import { randomUUID } from "node:crypto";
import { aduAtlasRequest, AduAtlasApiError, type AduAtlasConfig } from "./client";

export type ProjectType =
  | "detached_adu"
  | "attached_adu"
  | "garage_conversion"
  | "jadu"
  | "sb9_duplex"
  | "sb9_urban_lot_split";

export type FeasibilityStatus =
  | "likely_feasible"
  | "likely_constrained"
  | "needs_professional_review"
  | "insufficient_data";

export interface FeasibilityRequest {
  address: string;
  project_type: ProjectType;
  target_sqft?: number | null;
  bedrooms?: number | null;
  proposed_height_ft?: number | null;
  existing_structure?: {
    type?: "single_family" | "multifamily" | "none" | "unknown" | null;
    has_garage?: boolean | null;
    year_built?: number | null;
  } | null;
  options?: {
    near_transit?: boolean | null;
    historic_property?: boolean | null;
    include_envelope?: boolean | null;
  } | null;
}

// Only the fields most callers branch on are typed explicitly; every other
// field in the OpenAPI schema (parcel, zoning, development_constraints,
// overlay_findings, approximate_envelope, sources, freshness, ...) still
// comes through and is accessible, just as `unknown`.
export interface FeasibilityResponse {
  analysis_id: string;
  feasibility_status: FeasibilityStatus;
  disclaimer: string;
  share_token: string | null;
  [key: string]: unknown;
}

async function main() {
  // Pick ONE auth mode.
  const config: AduAtlasConfig = {
    mode: "rapidapi",
    rapidApiKey: process.env.RAPIDAPI_KEY,
    // mode: "direct",
    // apiKey: process.env.ADU_ATLAS_API_KEY,
  };

  const requestBody: FeasibilityRequest = {
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
    const analysis = await aduAtlasRequest<FeasibilityResponse>(
      config,
      "/v1/feasibility",
      {
        method: "POST",
        headers: { "Idempotency-Key": randomUUID() },
        body: JSON.stringify(requestBody),
      },
    );

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
