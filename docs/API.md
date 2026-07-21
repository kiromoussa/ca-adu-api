# ADU Atlas API - developer guide

This is the human-readable companion to `openapi/openapi.yaml` (the
authoritative machine schema) and `openapi/examples/` (copy-paste code).
Read `docs/PRODUCT_SPEC.md` and `docs/adr/0001-architecture.md` for the
product and architecture context behind the decisions in this guide.

## What this API is, and is not

ADU Atlas answers one question deterministically and with sources: for a
given California address and a proposed ADU/JADU/SB 9 project, what does the
parcel, zoning, state law, and hazard/overlay data say about preliminary
feasibility. It is not a permitting system, not a legal opinion, and not a
municipal-code search engine. The request path never calls a large language
model; it uses versioned structured rules, PostGIS spatial joins, and
source-linked data only. Every substantive response field carries
provenance, and every response carries the disclaimer verbatim - see
"Trust and provenance model" below.

## Base URLs

| Host | Use |
|---|---|
| `https://aduatlas.p.rapidapi.com` | RapidAPI gateway (primary distribution). Use `X-RapidAPI-Key` + `X-RapidAPI-Host`. |
| `https://api.aduatlas.example.com` | Direct API (self-serve API key). Use `X-API-Key`. |

All paths are versioned under `/v1`. Never send RapidAPI headers and
`X-API-Key` on the same request.

## Authentication

Two mutually exclusive auth modes, both enforced against the `security`
schemes in `openapi/openapi.yaml`:

1. **RapidAPI gateway.** RapidAPI injects `X-RapidAPI-Key` (your consumer
   identity and plan) and `X-RapidAPI-Host` on every proxied request. The
   API verifies the host header matches the expected gateway pattern (not
   as a secret by itself, as a sanity check that the request actually
   transited the gateway) and resolves your plan and quota from the
   RapidAPI key.
2. **Direct API key.** Issued from the developer portal as `X-API-Key`. The
   raw key is shown to you once; the server stores and matches only a
   sha256 hash of it. If you lose it, revoke and reissue a new key rather
   than asking support to recover it.

`GET /v1/health` requires no authentication at all.

## Idempotency

`POST /v1/feasibility` accepts an optional `Idempotency-Key` header (any
string, up to 255 characters). Behavior:

- A key reused with an **identical** request body returns the original
  stored response (same `analysis_id`) with no additional charge.
- A key reused with a **different** request body returns `409
  idempotency_key_conflict` and is not billed.
- Idempotency records are retained for 24 hours, matching the dedupe
  window described below.

Always send a fresh, unique `Idempotency-Key` per logical retry attempt of
the same logical request - do not reuse a key across genuinely different
analyses.

## The 24-hour dedupe window (separate from idempotency)

Independent of whether you send an `Idempotency-Key`, if the same consumer
sends the same normalized inputs (address, project_type, and the optional
fields that affect the result: `target_sqft`, `bedrooms`,
`proposed_height_ft`, `existing_structure`, `options`) within 24 hours, the
API returns the cached analysis and does **not** bill a second time. The
`X-Billable` response header on `POST /v1/feasibility` tells you which
happened: `"true"` means this call was metered as a new completed analysis,
`"false"` means it was served from the dedupe cache.

## Versioning

- The API path is versioned (`/v1`); breaking changes ship as `/v2` and
  later, with `/v1` supported for a documented deprecation window.
- Every feasibility response includes a `freshness` block:
  `analysis_version` (the rule-engine/software version that produced the
  result), `rules_version` (the version of the zoning rule set applied),
  `state_baseline_version` (the version of the California state-law
  baseline applied), and `generated_at` / `data_as_of` timestamps.
- `GET /v1/jurisdictions/{slug}/rules` returns `version_history` so you can
  see when a jurisdiction's rules last changed and why.
- `GET /v1/changelog` is the public, cross-jurisdiction update feed:
  coverage changes, rule updates, source ingestion/refresh events, and
  corrections.

Pin to `analysis_version` and `rules_version` if your workflow needs to
detect when a previously stored analysis might no longer reflect the
current rule set; a materially different `rules_version` since your stored
`analysis_id` was generated is a signal to re-run the analysis rather than
rely on the cached one indefinitely.

## Errors

Every non-2xx response uses the same envelope:

```json
{
  "error": {
    "code": "unsupported_coverage",
    "message": "Human-readable message. Never leaks internal detail.",
    "details": { "jurisdiction_slug": "oakland", "coverage_status": "planned" },
    "request_id": "req_01HZY8Q9V5"
  }
}
```

| HTTP | `error.code` | Billed | Meaning |
|---|---|---|---|
| 400 | `validation_error` | No | Malformed request body or query parameter. |
| 401 | `unauthorized` | No | Missing, invalid, or revoked credentials. |
| 403 | `forbidden` | No | Valid credentials, but not permitted for this resource (e.g. someone else's private analysis). |
| 404 | `not_found` | No | Resource does not exist (unknown jurisdiction slug, unknown analysis id). |
| 409 | `idempotency_key_conflict` | No | `Idempotency-Key` reused with a different request body. |
| 422 | `unsupported_coverage` | No | Address resolved to a jurisdiction whose `coverage_status` is not `production`. |
| 429 | `quota_exceeded` | No | Monthly plan quota exhausted. No overages in v1; upgrade or wait for the reset. |
| 429 | `rate_limited` | No | Short-window burst limiter tripped (see Rate limits below). |
| 500 | `internal_error` | No | Unexpected server error. Retry with backoff; no internal detail is ever included in `message`. |

`request_id` is a correlation id for support - include it whenever you
contact support about a specific failed call.

## Rate limits

Two independent limits apply:

1. **Monthly quota** (billable units), configured per plan in
   `config/plans.yaml` (see `docs/rapidapi/PRICING.md` for the current
   tier numbers). Resets on the 1st of each calendar month at 00:00 UTC.
   There are no overages in v1: once exhausted, `POST /v1/feasibility`
   returns `429 quota_exceeded` until the next reset or an upgrade.
2. **Short-window burst limiter** (requests per minute), also configured
   per plan, applied on top of the monthly quota on every plan to absorb
   accidental retry loops. A burst-limited response is `429 rate_limited`
   and is not billed.

RapidAPI gateway quota/rate-limit headers are the primary source of truth
when present; ADU Atlas also enforces its own limiter internally
(`api_usage_events`-backed) as a fallback so quota is honored even if a
gateway header is momentarily unavailable, and for direct API-key traffic
that never transits RapidAPI.

## Freshness and provenance model

Every substantive field in a feasibility or rules response is wrapped with
provenance:

| Field | Meaning |
|---|---|
| `source_url` | Canonical URL of the source document, code section, or GIS service. |
| `source_title` | Human-readable source title. |
| `source_section` | Municipal code section identifier (e.g. `"LAMC 12.22 A.33"`). Null for GIS sources. |
| `source_layer` | GIS layer/table identifier (e.g. `"NFHL/MapServer/28"`). Null for document sources. |
| `retrieved_at` | When the source content was retrieved and snapshotted. |
| `last_verified_at` | When the value was last verified against the source. |
| `confidence` | `high`, `medium`, or `low`. |
| `data_status` | `current`, `stale`, `needs_review`, or `unavailable`. |
| `snapshot_hash` | Content hash of the immutable source snapshot the value came from. |

Numeric and boolean development-constraint fields additionally carry
`state_baseline` (the applicable current California state-law value) and
`compliance_flag`:

- `compliant` - the local value is at least as permissive as the state
  baseline.
- `needs_review` - the comparison could not be fully resolved (e.g.
  orientation-dependent setback) and a human/professional should confirm.
- `possibly_more_restrictive_than_state_baseline` - the local rule appears
  more restrictive than current state law. ADU Atlas never infers the local
  rule is invalid or silently substitutes the state value; the local source
  is always preserved alongside the flag.

`overlay_findings` distinguish three states explicitly: `hit` (the parcel
intersects the hazard/overlay layer), `no_hit` (checked, does not
intersect), and `source_unavailable` (the layer could not be queried for
this request) - `no_hit` and `source_unavailable` are never conflated.

## `feasibility_status` and the disclaimer

`feasibility_status` is always exactly one of: `likely_feasible`,
`likely_constrained`, `needs_professional_review`, `insufficient_data`. The
API never returns "approved", "legal", "guaranteed", or a bare yes/no.

Every `POST /v1/feasibility` and `GET /v1/analyses/{analysis_id}` response
includes this exact disclaimer string:

```
This is preliminary informational zoning and GIS analysis, not legal,
architectural, surveying, engineering, title, environmental, or permit
advice. Verify all results with the applicable jurisdiction and qualified
professionals before making decisions or spending money.
```

Treat this as a contract in your own UI: if you surface `feasibility_status`
or any constraint value to an end user, surface the disclaimer next to it.

## Coverage honesty

`GET /v1/jurisdictions` is the live source of truth for which cities are
billable. `coverage_status` is one of `planned` (registered, no data yet),
`ingesting` (data pipeline in progress, not yet verified), or `production`
(sources, GIS layers, and rule set ingested, tested, and verified - the
only status that returns a billable feasibility result). Los Angeles City
is the v1 target. Do not hardcode which cities are supported in your
integration; check coverage at request time, and handle `422
unsupported_coverage` gracefully rather than treating it as a bug.

## Billing summary

See `docs/rapidapi/PRICING.md` for the full plan tiers. In short: one
billable unit is one completed address-level feasibility analysis (one
address plus one project_type resolving to a terminal
`feasibility_status`). Errors and unsupported-coverage responses are never
billed. Identical inputs from the same consumer within 24 hours are a cache
hit, not a second charge. There are no paid overages in v1.

## Where to go next

- `openapi/openapi.yaml` - the full OpenAPI 3.1 schema.
- `openapi/examples/` - copy-paste curl, TypeScript, Python, and JavaScript
  examples for every endpoint, including a full realistic
  request/response pair for a Los Angeles detached ADU.
- `docs/rapidapi/` - the RapidAPI Hub listing package (title, descriptions,
  categories, tags, FAQ, pricing copy, endpoint docs, logo requirements,
  support policy).
- `docs/PRODUCT_SPEC.md` and `docs/adr/0001-architecture.md` - the product
  and architecture decisions behind everything in this guide.
