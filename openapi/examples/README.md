# ADU Atlas API - SDK examples

Copy-paste, runnable request/response examples for every endpoint in
`openapi/openapi.yaml`, in curl, TypeScript, Python, and JavaScript. Every
language directory includes both auth variants:

- **RapidAPI gateway** (primary distribution): `X-RapidAPI-Key` +
  `X-RapidAPI-Host` against `https://property-feasibility4.p.rapidapi.com`.
  The Hub-registered endpoint paths omit the `/v1` prefix (the origin's
  `/v1` base path lives in the provider's Base URL setting on the Hub,
  invisible to consumers) - call `POST /feasibility`, not
  `POST /v1/feasibility`, through this host.
- **Direct API key** (self-serve, no RapidAPI): `X-API-Key` against
  `https://api.aduatlas.example.com`. Paths keep the `/v1` prefix on this
  host.

Never send both auth variants on the same request.

## Files

| File (per language dir) | Endpoint (RapidAPI path / direct path) |
|---|---|
| `feasibility.*` | `POST /feasibility` / `POST /v1/feasibility` (the only billable endpoint) |
| `jurisdictions.*` | `GET /jurisdictions` / `GET /v1/jurisdictions` |
| `jurisdiction_rules.*` | `GET /jurisdictions/{slug}/rules` / `GET /v1/jurisdictions/{slug}/rules` |
| `get_analysis.*` | `GET /analyses/{analysis_id}` / `GET /v1/analyses/{analysis_id}` |
| `changelog.*` | `GET /changelog` / `GET /v1/changelog` |
| `health.*` | `GET /health` / `GET /v1/health` (no auth required) |

- `curl/` - plain `.sh` scripts, runnable with `bash <file>.sh` given
  `RAPIDAPI_KEY` or `ADU_ATLAS_API_KEY` in the environment.
- `typescript/` - fetch-based, Node 18+ (`npx tsx <file>.ts`). `client.ts`
  holds the shared auth/error-handling helper the other files import.
- `javascript/` - the same examples in plain ESM JavaScript (`node <file>.js`).
  `client.js` is the shared helper.
- `python/` - httpx-based (`pip install httpx`, then `python <file>.py`).
  `client.py` is the shared helper; a requests-based equivalent is included
  as a comment at the bottom of `feasibility.py`.

## Realistic request/response pair

`feasibility.request.json` and `feasibility.response.json` are a full,
schema-valid example for a detached ADU at a Los Angeles address, including
provenance on every substantive field, a `needs_review`-style
`compliance_flag` walkthrough (front-yard setback orientation could not be
confirmed from GIS data alone), an approximate conceptual envelope, and the
verbatim disclaimer. Validate them against the schema at any time:

```bash
python3 -c "import json; json.load(open('feasibility.response.json'))"
```

Two things about this example that match current live behavior, not just
the schema: `eligible_paths` contains exactly one entry, for the requested
`project_type` (a single call does not simultaneously evaluate ADU, JADU,
and SB 9 eligibility); and `score` is `null` - the field is reserved by the
schema but not yet computed by the live scoring model. See three additional
real, live-captured examples (not schema mockups) in
`docs/rapidapi/LISTING.md`'s "Getting started in 60 seconds" section.

## Trust fields present in every feasibility example

- `disclaimer` - the exact non-negotiable disclaimer string.
- `feasibility_status` - one of `likely_feasible`, `likely_constrained`,
  `needs_professional_review`, `insufficient_data`. Never an approval or a
  legal yes/no.
- Provenance (`source_url`, `source_title`, `source_section`/`source_layer`,
  `retrieved_at`, `last_verified_at`, `confidence`, `data_status`,
  `snapshot_hash`) on every substantive value.
- `compliance_flag` comparing local values against the California state
  baseline (`compliant`, `needs_review`,
  `possibly_more_restrictive_than_state_baseline`).

See `docs/API.md` for the full auth, idempotency, versioning, error, and
freshness model, and `docs/rapidapi/` for the RapidAPI listing package.
