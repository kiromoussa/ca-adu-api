# CA ADU Zoning API - Edge Functions

Supabase Edge Functions (Deno / TypeScript) implementing the public REST API.

## Endpoints

| Function            | Route                                    | Description                                   |
| ------------------- | ---------------------------------------- | --------------------------------------------- |
| `cities`            | `GET /v1/cities`                         | List the cities covered by the API.           |
| `adu-rules`         | `GET /v1/adu-rules?city=&zone=`          | ADU rule rows joined to city, filtered.       |
| `compliance-flags`  | `GET /v1/compliance-flags?city=`         | Compliance-flag summary per city/zone.        |

All routes require an API key and count against the caller's monthly quota
(Free 50, Starter 1000, Pro 10000 requests/month). The full contract is in
`../../docs/openapi.yaml`.

## Authentication

Send the raw API key in either header:

```
Authorization: Bearer adu_live_xxxxxxxx
```

or

```
x-api-key: adu_live_xxxxxxxx
```

The function sha256-hashes the key, looks it up in `api_keys.key_hash`, and calls
the `increment_api_usage(key_hash)` RPC to atomically roll the monthly window,
check the tier quota, and increment the counter.

- `401 unauthorized` - key missing, invalid, or revoked.
- `429 quota_exceeded` - monthly quota reached; body includes `tier` and `limit`.
- Every request (allowed or 429) is written to `usage_logs` with `status_code`
  and `billable` (2xx = billable, 429/errors = non-billable).

## Layout

```
functions/
  _shared/
    cors.ts        CORS headers + JSON/preflight helpers
    supabase.ts    service-role client (reads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)
    auth.ts        API key extraction, sha256 hash, quota enforcement
    log.ts         usage_logs writer
  adu-rules/index.ts
  cities/index.ts
  compliance-flags/index.ts
  import_map.json  npm:@supabase/supabase-js pin
  deno.json        import map + fmt/compiler config
```

## Environment

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected automatically into the
Edge runtime by Supabase. For local serving, set them (do not commit secrets):

```bash
supabase secrets set SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY"
```

The service-role client is used because the functions write `usage_logs` and
increment `api_keys`, both restricted to `service_role` by RLS.

## Local development

Serve all functions with the shared import map:

```bash
supabase start
supabase functions serve --import-map ./supabase/functions/import_map.json --env-file ./supabase/functions/.env
```

Then call an endpoint (local functions are served under `/functions/v1/<name>`):

```bash
curl -s "http://127.0.0.1:54321/functions/v1/cities" \
  -H "x-api-key: <raw-api-key>"

curl -s "http://127.0.0.1:54321/functions/v1/adu-rules?city=los_angeles&zone=R-1" \
  -H "Authorization: Bearer <raw-api-key>"

curl -s "http://127.0.0.1:54321/functions/v1/compliance-flags?city=oakland" \
  -H "x-api-key: <raw-api-key>"
```

Type-check locally (optional, requires Deno):

```bash
deno check --import-map ./supabase/functions/import_map.json supabase/functions/**/index.ts
```

## Deploy

```bash
supabase functions deploy cities
supabase functions deploy adu-rules
supabase functions deploy compliance-flags
```

The clean public routes (`/v1/adu-rules`, etc.) are produced by the Vercel
gateway / rewrites in front of the deployed function URLs
(`https://<project-ref>.supabase.co/functions/v1/<name>`).
