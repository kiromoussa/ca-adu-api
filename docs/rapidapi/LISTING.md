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
Send a California address and project type. Get a fast, source-cited,
preliminary ADU/JADU/SB 9 feasibility result - zoning, setbacks, height,
hazard overlays, and citations. No LLM guessing, no legal opinions.
```

---

## Long description (main listing body)

```
ADU Atlas API turns a California street address and a proposed project type
into a fast, deterministic, source-cited preliminary feasibility result for
accessory dwelling units (ADUs), junior ADUs (JADUs), and SB 9 duplex /
urban lot split projects.

Send POST /v1/feasibility with an address and a project_type
(detached_adu, attached_adu, garage_conversion, jadu, sb9_duplex, or
sb9_urban_lot_split) and receive, in one call:

- Parcel and zoning context (APN, lot size, zone code, general plan),
  matched with PostGIS spatial joins against official city GIS layers.
- Eligible development paths (ADU / JADU / SB 9) with a plain-language,
  condition-by-condition explanation for each.
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

The request path is 100% deterministic: versioned structured rules, PostGIS
spatial logic, and source-linked data only. No large language model is used
at request time for any legal or geospatial determination. Every response
includes this disclaimer verbatim:

"This is preliminary informational zoning and GIS analysis, not legal,
architectural, surveying, engineering, title, environmental, or permit
advice. Verify all results with the applicable jurisdiction and qualified
professionals before making decisions or spending money."

Coverage: Los Angeles City is the v1 target and the only jurisdiction whose
feasibility calls are billable today. San Diego, San Jose, San Francisco,
Sacramento, Irvine, Long Beach, and Oakland are registered and visible via
GET /v1/jurisdictions, but return unsupported_coverage (and are not billed)
until each city's sources, GIS layers, and rule set are ingested, tested,
and marked production-ready. Check GET /v1/jurisdictions for live coverage
status before integrating a city into your workflow.

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
| POST | `/v1/feasibility` | Yes (on completion) | Preliminary ADU/JADU/SB 9 feasibility for one address and project type. |
| GET | `/v1/jurisdictions` | No | Coverage status, supported project types, source update date per jurisdiction. |
| GET | `/v1/jurisdictions/{slug}/rules` | No | Citywide and zone-level rules, citations, and version history for a jurisdiction. |
| GET | `/v1/analyses/{analysis_id}` | No | Retrieve a previously computed analysis (private, or public via share token). |
| GET | `/v1/changelog` | No | Public update history: ingestion runs, rule changes, coverage changes. |
| GET | `/v1/health` | No | Service liveness, uptime, and non-sensitive source freshness. No auth required. |

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
the disclaimer returned on every /v1/feasibility response.

Data corrections: if you believe a rule, citation, or GIS finding is
incorrect or stale, report it through the support channel with the
analysis_id (or jurisdiction slug + zone) and the source you believe is
authoritative. Corrections are tracked in GET /v1/changelog
(change_type = "correction") once verified and published.

Status and incidents: see GET /v1/health for live service status and
per-source data freshness. There is no separate status page in v1.
```
