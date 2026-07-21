// Non-negotiable disclaimer text (verbatim, per product spec). This exact
// string must appear on every feasibility_status response from the API and
// is surfaced prominently in the portal so nothing here is ever mistaken
// for legal, architectural, surveying, engineering, title, environmental, or
// permit advice.
export const DISCLAIMER_TEXT =
  "This is preliminary informational zoning and GIS analysis, not legal, " +
  "architectural, surveying, engineering, title, environmental, or permit " +
  "advice. Verify all results with the applicable jurisdiction and " +
  "qualified professionals before making decisions or spending money.";

export const FEASIBILITY_STATUSES = [
  {
    value: "likely_feasible",
    label: "Likely feasible",
    description:
      "The parcel, zoning, and rule inputs resolved cleanly and do not surface a blocking constraint.",
  },
  {
    value: "likely_constrained",
    label: "Likely constrained",
    description:
      "One or more identified rules, overlays, or size/height/setback limits materially constrain the project as proposed.",
  },
  {
    value: "needs_professional_review",
    label: "Needs professional review",
    description:
      "Ambiguous parcel, zoning, or overlay data, or a local-versus-state conflict, requires a qualified professional before proceeding.",
  },
  {
    value: "insufficient_data",
    label: "Insufficient data",
    description:
      "The address, parcel, zoning, or rule data required to reach a determination is not available for this jurisdiction.",
  },
] as const;

export const PROJECT_TYPE_LABELS: Record<string, string> = {
  detached_adu: "Detached ADU",
  attached_adu: "Attached ADU",
  garage_conversion: "Garage conversion",
  jadu: "JADU",
  sb9_duplex: "SB 9 duplex",
  sb9_urban_lot_split: "SB 9 urban lot split",
};

export const COVERAGE_STATUS_LABELS: Record<string, string> = {
  production: "Live",
  ingesting: "In progress",
  planned: "Planned",
};

export const COVERAGE_STATUS_DESCRIPTIONS: Record<string, string> = {
  production:
    "Source registry, GIS layers, and rules are ingested, tested, and verified. Feasibility requests are billable.",
  ingesting:
    "Data ingestion is underway and not yet production-verified. Feasibility requests may return insufficient_data or needs_professional_review.",
  planned:
    "Registered but not yet ingested. Feasibility requests for this jurisdiction return unsupported_coverage and are not billed.",
};

export function getApiBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
}

export function getRapidApiUrl(): string {
  return process.env.NEXT_PUBLIC_RAPIDAPI_URL ?? "https://rapidapi.com";
}

export const SITE_NAME = "Atlas Property Feasibility API";

export const SITE_TAGLINE =
  "The API for property feasibility. Deterministic, source-cited, address-level results - live today for California ADU, JADU, and SB 9.";
