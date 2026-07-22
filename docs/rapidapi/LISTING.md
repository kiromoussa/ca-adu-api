# ADU Atlas API - RapidAPI listing package

This is the exact copy package for the RapidAPI Hub listing. Each section
below maps to a field in the RapidAPI "Add API" / "Edit API" form. Copy each
section verbatim into the matching field. Do not add emojis or em dashes
anywhere in the listing (use a hyphen).

---

## Title

```
ADU Atlas API - California ADU/JADU/SB 9 Feasibility
```

Alternate (if the primary title exceeds RapidAPI's title length limit):

```
ADU Atlas - CA ADU Feasibility API
```

---

## Short description (tagline, shown in search results and cards)

```
The API for property feasibility. Send a California address and project
type, get a fast, deterministic, source-cited ADU/JADU/SB 9 result -
zoning, setbacks, height, hazard overlays, citations. No LLM guessing.
```

---

## Long description (main listing body)

```
ADU Atlas is the API for property feasibility: address in, source-cited
feasibility out. Send a California street address and a proposed project
type, and get back a fast, deterministic, preliminary feasibility result
for accessory dwelling units (ADUs), junior ADUs (JADUs), and SB 9 duplex /
urban lot split projects - the kind of answer that today takes a manual
zoning-code search and a phone call to the planning department.

Why developers trust the result: the request path is 100% deterministic.
No large language model ever touches a legal or geospatial determination.
Every substantive field is backed by versioned structured rules, PostGIS
spatial joins against official city GIS layers, and a source citation you
can click and verify yourself - not a paraphrase of an ordinance, the
ordinance.

Send POST /feasibility with an address and a project_type
(detached_adu, attached_adu, garage_conversion, jadu, sb9_duplex, or
sb9_urban_lot_split) and receive, in one call:

- Parcel and zoning context (APN, lot size, zone code, general plan),
  matched with PostGIS spatial joins against official city GIS layers.
- Eligibility for the project_type you requested (ADU, JADU, or an SB 9
  variant), with a plain-language, condition-by-condition explanation and
  its own source citations.
- Development constraints: max height, max size, setbacks, parking,
  owner-occupancy, permit review timeline, impact-fee thresholds, and fire
  sprinkler triggers - every value compared against the current California
  state-law baseline (AB 2221, SB 897, SB 9, Gov. Code Sections 66310-66342)
  and flagged if the local rule is more restrictive.
- Hazard and overlay findings: FEMA flood, CAL FIRE fire hazard severity
  zone, historic preservation overlay, hillside, and more - with "no hit"
  explicitly distinguished from "source unavailable".
- An approximate conceptual buildable envelope (Los Angeles v1 only),
  clearly labeled approximate, with assumptions and limitations spelled out.
- A feasibility_status of likely_feasible, likely_constrained,
  needs_professional_review, or insufficient_data - never "approved",
  "legal", "guaranteed", or a final yes/no.
- Full source citations and per-field provenance: source URL, title,
  code section or GIS layer, retrieved/last-verified timestamps, confidence,
  and data status, on every substantive field.

Every response includes this disclaimer verbatim, and the API never states
that a permit is approved, that a project is legal to build, or a final
yes/no:

"This is preliminary informational zoning and GIS analysis, not legal,
architectural, surveying, engineering, title, environmental, or permit
advice. Verify all results with the applicable jurisdiction and qualified
professionals before making decisions or spending money."

Coverage, honestly stated: eight California cities are live and billable
today - Los Angeles, San Diego, San Jose, San Francisco, Sacramento, Long
Beach, Irvine, and Oakland - each verified end-to-end against a real address
before being marked production. A city is marked production only after its
sources, GIS layers, and rule set are ingested, tested, and verified; other
jurisdictions are registered and visible via GET /jurisdictions but return
unsupported_coverage (and are not billed) until they clear that bar. Call
GET /jurisdictions at request time for live status - never hardcode which
cities are covered.

Built for PropTech platforms, architects, real estate and lending
workflows, and AI agents that need a fast, structured, citable answer
instead of a manual zoning-code search.

Billing: one billable unit is one completed address-level feasibility
analysis (one address plus one project_type that resolves to a terminal
feasibility_status). Errors, validation failures, and unsupported-coverage
responses are never billed. Identical inputs from the same customer within
24 hours are served from cache and are not billed a second time.
```

---

## Getting started in 60 seconds

Subscribe on RapidAPI, grab your `X-RapidAPI-Key` from the app, and run:

```bash
curl -X POST "https://property-feasibility4.p.rapidapi.com/feasibility" \
  -H "Content-Type: application/json" \
  -H "X-RapidAPI-Key: YOUR_RAPIDAPI_KEY" \
  -H "X-RapidAPI-Host: property-feasibility4.p.rapidapi.com" \
  -d '{
    "address": "1122 S Cochran Ave, Los Angeles, CA 90019",
    "project_type": "detached_adu"
  }'
```

That is the entire integration: one address, one project_type, one call.
No signup flow beyond RapidAPI, no separate API key to manage, no SDK
required (though curl, Python, TypeScript, and JavaScript SDK snippets are
included in `openapi/examples/` if you want them).

The three examples below are real calls against the live API today (not
mocked), trimmed to the fields most callers check first. Full,
untrimmed response shapes - including per-field provenance on every
value - are in `openapi/examples/feasibility.response.json` and
`docs/rapidapi/RESPONSE_EXAMPLES.md`.

**Example 1 - a clean likely_feasible result (R3, West Adams)**

```json
{
  "analysis_id": "52ec113d-bf36-4823-8ff7-7f66a9258398",
  "request": { "address": "1122 S Cochran Ave, Los Angeles, CA 90019", "project_type": "detached_adu" },
  "coverage": { "jurisdiction_slug": "los_angeles", "jurisdiction_name": "Los Angeles", "coverage_status": "production" },
  "parcel": { "apn": "5084-018-020", "matched": true, "lot_size_sqft": 8823.2 },
  "zoning": { "zone_code": "R3", "zone_name": "R3-1-O-HPOZ", "cross_zone_ambiguity": false },
  "feasibility_status": "likely_feasible",
  "eligible_paths": [ { "path_type": "detached_adu", "status": "likely_eligible" } ],
  "development_constraints": {
    "max_height_ft": { "value": 16.0, "unit": "ft", "state_baseline": 16.0, "compliance_flag": "compliant" },
    "max_size_sqft": { "value": 850.0, "unit": "sqft", "state_baseline": 850.0 }
  },
  "overlay_findings": [
    { "overlay_type": "flood", "status": "hit", "severity": "info" },
    { "overlay_type": "fire", "status": "source_unavailable", "severity": null }
  ],
  "disclaimer": "This is preliminary informational zoning and GIS analysis, not legal, architectural, surveying, engineering, title, environmental, or permit advice. Verify all results with the applicable jurisdiction and qualified professionals before making decisions or spending money."
}
```

**Example 2 - likely_feasible in a single-family zone (R1, Studio City)**

```json
{
  "analysis_id": "5ab1403e-731a-4240-af00-2d1450f27e30",
  "request": { "address": "4200 Klump Ave, Studio City, CA 91604", "project_type": "detached_adu" },
  "coverage": { "jurisdiction_slug": "los_angeles", "jurisdiction_name": "Los Angeles", "coverage_status": "production" },
  "parcel": { "apn": "2366-015-022", "matched": true, "lot_size_sqft": 6305.7 },
  "zoning": { "zone_code": "R1", "zone_name": "R1-1-RIO", "cross_zone_ambiguity": false },
  "feasibility_status": "likely_feasible",
  "eligible_paths": [ { "path_type": "detached_adu", "status": "likely_eligible" } ],
  "development_constraints": {
    "max_height_ft": { "value": 16.0, "unit": "ft", "state_baseline": 16.0, "compliance_flag": "compliant" },
    "max_size_sqft": { "value": 850.0, "unit": "sqft", "state_baseline": 850.0 }
  },
  "overlay_findings": [
    { "overlay_type": "flood", "status": "hit", "severity": "info" },
    { "overlay_type": "fire", "status": "source_unavailable", "severity": null }
  ],
  "disclaimer": "This is preliminary informational zoning and GIS analysis, not legal, architectural, surveying, engineering, title, environmental, or permit advice. Verify all results with the applicable jurisdiction and qualified professionals before making decisions or spending money."
}
```

**Example 3 - needs_professional_review, honestly flagged (cross-zone parcel, Hollywood)**

```json
{
  "analysis_id": "3bed8446-4198-490f-89fb-a3955627e64a",
  "request": { "address": "5678 Franklin Ave, Los Angeles, CA 90028", "project_type": "detached_adu" },
  "coverage": { "jurisdiction_slug": "los_angeles", "jurisdiction_name": "Los Angeles", "coverage_status": "production" },
  "parcel": { "apn": "5544-002-044", "matched": true, "lot_size_sqft": 4433.3 },
  "zoning": { "zone_code": "RD1.5", "zone_name": "RD1.5-1XL", "cross_zone_ambiguity": true },
  "feasibility_status": "needs_professional_review",
  "eligible_paths": [ { "path_type": "detached_adu", "status": "likely_eligible" } ],
  "development_constraints": {
    "max_height_ft": { "value": 16.0, "unit": "ft", "state_baseline": 16.0, "compliance_flag": "compliant" },
    "max_size_sqft": { "value": 850.0, "unit": "sqft", "state_baseline": 850.0 }
  },
  "overlay_findings": [
    { "overlay_type": "flood", "status": "hit", "severity": "info" },
    { "overlay_type": "fire", "status": "source_unavailable", "severity": null }
  ],
  "limitations": [
    { "code": "cross_zone_ambiguity", "text": "The parcel intersects more than one zoning district (R3, RD1.5); the primary zone was used. Verify." }
  ],
  "disclaimer": "This is preliminary informational zoning and GIS analysis, not legal, architectural, surveying, engineering, title, environmental, or permit advice. Verify all results with the applicable jurisdiction and qualified professionals before making decisions or spending money."
}
```

Two honest notes on what these three real calls show: `max_size_sqft` above
is the California state-law baseline (Gov Code 66323, 850 sqft for a studio
ADU); it carries no `compliance_flag` because the LA-specific ordinance
value has not been ingested for these zones yet - the field says so, it
does not silently invent a local number. And the flood `overlay_findings`
entry with `"severity": "info"` means "FEMA Zone X, minimal hazard, no
constraint" - a real hit, correctly distinguished from `no_hit` and from
`source_unavailable` (the honest state of the fire-hazard layer above,
which is not yet ingested).

---

## Category

Primary category:

```
Location
```

Secondary category (if the Hub allows a second):

```
Business
```

---

## Tags

```
real-estate, zoning, adu, jadu, sb9, california, gis, postgis, permits,
property-data, proptech, land-use, feasibility, parcel-data, housing
```

---

## Website / documentation links

```
Documentation: https://api.aduatlas.example.com/docs
OpenAPI spec:  https://api.aduatlas.example.com/openapi.yaml
Support:       https://aduatlas.example.com/support
Terms:         https://aduatlas.example.com/terms
```

---

## Endpoint summary

| Method | Path | Billed | Summary |
|---|---|---|---|
| POST | `/feasibility` | Yes (on completion) | Preliminary ADU/JADU/SB 9 feasibility for one address and project type. |
| GET | `/jurisdictions` | No | Coverage status, supported project types, source update date per jurisdiction. |
| GET | `/jurisdictions/{slug}/rules` | No | Citywide and zone-level rules, citations, and version history for a jurisdiction. |
| GET | `/analyses/{analysis_id}` | No | Retrieve a previously computed analysis (private, or public via share token). |
| GET | `/changelog` | No | Public update history: ingestion runs, rule changes, coverage changes. |
| GET | `/health` | No | Service liveness, uptime, and non-sensitive source freshness. No auth required. |

Full request/response schemas: `openapi/openapi.yaml`. Copy-paste examples in
curl, TypeScript, Python, and JavaScript: `openapi/examples/`.

---

## Logo requirements

RapidAPI requires a square logo, minimum 200x200px, PNG or JPG, no
transparency issues on a light background (the Hub renders logos on both
light and dark cards, so avoid a logo that disappears on either).

Spec for the ADU Atlas mark:

- Square canvas, 512x512px source (downscale for the 200x200px upload).
- Simple mark: a stylized house/parcel outline over a location pin or map
  grid motif, communicating "place plus structure". No literal city
  skyline, no photographic elements.
- Two-color max for the icon itself (a dark ink color plus one accent);
  legible at 32px (browser tab / small card size).
- No emojis, no stock-photo textures, no gradients that fail at small size.
- Background: transparent PNG with a solid-color fallback (near-white)
  baked in for hosts that do not composite transparency correctly.
- File naming: `aduatlas-logo-512.png` (master), `aduatlas-logo-200.png`
  (Hub upload size).

---

## Support / contact policy

```
Support channel: https://aduatlas.example.com/support
Support email:   support@aduatlas.example.com
Response time:   Best-effort within 2 business days for Basic and Pro plans.
                 Priority support (target: 1 business day) for Ultra and
                 Mega plans, per config/plans.yaml features.priority_support.

Scope: We support API integration questions, error/response interpretation,
data freshness/coverage questions, and billing/quota questions. We do not
provide legal, architectural, engineering, surveying, or permitting advice.
This API is preliminary informational zoning and GIS analysis, not a
substitute for the applicable jurisdiction or a qualified professional - see
the disclaimer returned on every /feasibility response.

Data corrections: if you believe a rule, citation, or GIS finding is
incorrect or stale, report it through the support channel with the
analysis_id (or jurisdiction slug + zone) and the source you believe is
authoritative. Corrections are tracked in GET /changelog
(change_type = "correction") once verified and published.

Status and incidents: see GET /health for live service status and
per-source data freshness. There is no separate status page in v1.
```
