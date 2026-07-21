# ADU Atlas API - RapidAPI endpoint docs and response examples

Paste each endpoint block below into the corresponding endpoint's
"Documentation" field on the RapidAPI Hub. Full JSON schemas live in
`openapi/openapi.yaml`; full copy-paste request code in curl, TypeScript,
Python, and JavaScript lives in `openapi/examples/`.

---

## POST /feasibility

Billable. One completed analysis (terminal `feasibility_status`) is one
billable unit. Not billed on error, validation failure, or
unsupported-coverage.

**Headers**

| Header | Required | Notes |
|---|---|---|
| `X-RapidAPI-Key` | Yes (RapidAPI) | Injected automatically by the gateway. |
| `X-RapidAPI-Host` | Yes (RapidAPI) | `property-feasibility4.p.rapidapi.com` |
| `Content-Type` | Yes | `application/json` |
| `Idempotency-Key` | No | Client-generated key to make retries safe. |

**Example request body**

See `openapi/examples/feasibility.request.json`:

```json
{
  "address": "1234 S Main St, Los Angeles, CA 90015",
  "project_type": "detached_adu",
  "target_sqft": 800,
  "bedrooms": 1,
  "proposed_height_ft": 16,
  "existing_structure": {
    "type": "single_family",
    "has_garage": true,
    "year_built": 1948
  },
  "options": {
    "near_transit": false,
    "historic_property": false,
    "include_envelope": true
  }
}
```

**Example 200 response (abridged)**

Full response: `openapi/examples/feasibility.response.json`. Abridged for
this doc:

```json
{
  "analysis_id": "b8e6f9d2-4b7d-4b0e-9a45-1e6a9d5c9d2f",
  "coverage": {
    "jurisdiction_slug": "los_angeles",
    "jurisdiction_name": "City of Los Angeles",
    "coverage_status": "production"
  },
  "feasibility_status": "likely_feasible",
  "score": null,
  "eligible_paths": [
    { "path_type": "detached_adu", "status": "likely_eligible" }
  ],
  "development_constraints": {
    "max_height_ft": { "value": 16, "unit": "ft", "state_baseline": 16, "compliance_flag": "compliant" },
    "side_setback_ft": { "value": 4, "unit": "ft", "state_baseline": 4, "compliance_flag": "compliant" }
  },
  "overlay_findings": [
    { "overlay_type": "flood", "status": "no_hit" },
    { "overlay_type": "fire", "status": "no_hit" }
  ],
  "disclaimer": "This is preliminary informational zoning and GIS analysis, not legal, architectural, surveying, engineering, title, environmental, or permit advice. Verify all results with the applicable jurisdiction and qualified professionals before making decisions or spending money."
}
```

Notes on current behavior: `eligible_paths` today contains exactly one
entry, for the `project_type` you requested (it does not simultaneously
evaluate ADU, JADU, and SB 9 in a single call). `score` is reserved by the
schema but not currently computed and is always `null`.
`approximate_envelope` is present only when the request body sets
`"options": {"include_envelope": true}`, and only for Los Angeles.

**Example 422 response - unsupported coverage (not billed)**

```json
{
  "error": {
    "code": "unsupported_coverage",
    "message": "The city of Oakland is registered but not yet production (coverage_status=planned). No feasibility result is available and you were not billed.",
    "details": { "jurisdiction_slug": "oakland", "coverage_status": "planned" },
    "request_id": "req_01HZY8Q9V5"
  }
}
```

**Example 429 response - quota exceeded (not billed)**

```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "Monthly quota exceeded for your plan. Upgrade or wait for the next billing cycle. There are no paid overages in v1.",
    "details": { "plan": "BASIC", "monthly_quota": 3, "used_this_month": 3 },
    "request_id": "req_01HZY8Q9V6"
  }
}
```

---

## GET /jurisdictions

Not billed. No request body, no path parameters.

**Example 200 response (abridged)**

```json
{
  "data": [
    {
      "slug": "los_angeles",
      "name": "Los Angeles",
      "display_name": "City of Los Angeles",
      "coverage_status": "production",
      "supported_project_types": ["detached_adu", "attached_adu", "garage_conversion", "jadu", "sb9_duplex", "sb9_urban_lot_split"],
      "sources_last_updated_at": "2026-07-18T09:12:00Z"
    },
    {
      "slug": "oakland",
      "name": "Oakland",
      "display_name": "City of Oakland",
      "coverage_status": "planned",
      "supported_project_types": ["detached_adu", "attached_adu", "garage_conversion", "jadu", "sb9_duplex", "sb9_urban_lot_split"],
      "sources_last_updated_at": null
    }
  ],
  "count": 8
}
```

---

## GET /jurisdictions/{slug}/rules

Not billed. Optional `?zone=` and `?project_type=` query filters.

**Example 200 response (abridged)**

```json
{
  "jurisdiction": { "slug": "los_angeles", "name": "Los Angeles", "coverage_status": "production" },
  "citywide": [
    {
      "key": "owner_occupancy_required_adu",
      "value": false,
      "state_baseline": false,
      "compliance_flag": "compliant",
      "provenance": {
        "source_url": "https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-422835",
        "source_title": "LAMC 12.22 A.33 - Accessory Dwelling Units",
        "source_section": "LAMC 12.22 A.33(b)",
        "retrieved_at": "2026-07-15T06:00:00Z",
        "confidence": "high",
        "data_status": "current"
      }
    }
  ],
  "zones": [
    {
      "zone_code": "R1",
      "zone_name": "One-Family Zone",
      "project_type": "detached_adu",
      "attributes": [
        { "key": "max_height_detached_standard_ft", "value": 16, "unit": "ft", "state_baseline": 16, "compliance_flag": "compliant", "provenance": { "...": "..." } }
      ]
    }
  ],
  "citations": [ { "...": "..." } ],
  "version_history": [
    { "version": "2026.07.1", "effective_at": "2026-07-15T00:00:00Z", "change_summary": "Verified LAMC 12.22 A.33 against the current HCD ADU Handbook baseline." }
  ]
}
```

---

## GET /analyses/{analysis_id}

Not billed. Requires the same API key/consumer that created the analysis,
or a valid `?token=` share token for a public shareable analysis.

**Example 200 response**

Same shape as `POST /feasibility` - see `openapi/examples/feasibility.response.json`.

**Example 403 response - private analysis owned by another consumer**

```json
{
  "error": {
    "code": "forbidden",
    "message": "This analysis is private to another consumer.",
    "request_id": "req_01HZY8Q9V2"
  }
}
```

---

## GET /changelog

Not billed. Optional `?jurisdiction=` and `?limit=` (default 50, max 200).

**Example 200 response (abridged)**

```json
{
  "data": [
    {
      "id": "3c1e2f4a-9b8d-4e7f-9a2b-1c3d4e5f6a7b",
      "jurisdiction_slug": "los_angeles",
      "change_type": "rule_update",
      "summary": "Re-verified LAMC 12.22 A.33 setback attributes against the July 2026 HCD ADU Handbook baseline; no local values changed.",
      "occurred_at": "2026-07-15T06:00:00Z"
    },
    {
      "id": "9d8c7b6a-5e4f-3d2c-1b0a-9f8e7d6c5b4a",
      "jurisdiction_slug": "san_diego",
      "change_type": "coverage_change",
      "summary": "San Diego moved from planned to ingesting.",
      "occurred_at": "2026-07-01T00:00:00Z"
    }
  ],
  "count": 2
}
```

---

## GET /health

Not billed. No authentication required.

**Example 200 response**

```json
{
  "status": "ok",
  "uptime_seconds": 1382940.5,
  "api_version": "1.0.0",
  "rules_version": "2026.07.1",
  "sources": [
    { "key": "la_zimas_zoning", "name": "LA City ZIMAS zoning districts", "data_status": "current", "last_refreshed_at": "2026-07-18T09:12:00Z" },
    { "key": "fema_nfhl", "name": "FEMA National Flood Hazard Layer", "data_status": "current", "last_refreshed_at": "2026-07-10T00:00:00Z" },
    { "key": "calfire_fhsz", "name": "CAL FIRE / OSFM Fire Hazard Severity Zones", "data_status": "current", "last_refreshed_at": "2026-07-05T00:00:00Z" }
  ]
}
```

**Example 503 response - degraded**

```json
{
  "status": "degraded",
  "uptime_seconds": 1382940.5,
  "api_version": "1.0.0",
  "rules_version": "2026.07.1",
  "sources": [
    { "key": "la_zimas_zoning", "name": "LA City ZIMAS zoning districts", "data_status": "stale", "last_refreshed_at": "2026-06-01T00:00:00Z" }
  ]
}
```
