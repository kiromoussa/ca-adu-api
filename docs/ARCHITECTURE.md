# Architecture

The CA ADU Zoning API turns messy municipal ADU/zoning code into a small set of
state-law-validated boolean/numeric fields, served as a rate-limited REST API for
8 California cities. This document traces the data flow end to end and names the
concrete file that owns each stage.

## One-line data flow

```
Render scraper  ->  zoning_sections  ->  extraction + validation  ->  adu_rules  ->  Supabase Edge Functions  ->  Vercel  ->  developer
   (weekly)          (raw code text)      (LLM + state baselines)     (structured)    (/v1/*, quota, logging)     (docs, dashboard, billing)
```

## Components

Three deploy targets, one shared Postgres database.

| Layer | Runtime | Owns | Writes / reads |
|---|---|---|---|
| Scraper worker | Render cron (Python + Playwright) | `scraper/` | writes `zoning_sections`, stamps `cities.last_scraped_at` |
| Extraction + validation pipeline | Render cron (Python + LLM) | `scraper/pipeline/` | reads `zoning_sections`, writes `adu_rules` |
| Compliance QA job (Prompt 6) | Render cron (Python) | `scraper/qa/` | reads `adu_rules`, writes `qa_alerts`, posts Slack |
| API layer | Supabase Edge Functions (Deno) | `supabase/functions/` | reads `cities` / `adu_rules`, writes `usage_logs`, increments `api_keys` |
| Frontend | Vercel (Next.js 14 App Router) | `frontend/` | reads `usage_logs`, writes `api_keys`, Stripe billing |
| Database + auth | Supabase Postgres | `supabase/migrations/`, `supabase/seed.sql` | tables, RLS, `increment_api_usage()` |

## Stage by stage

### 1. Scrape (Render -> zoning_sections)

`scraper/main.py` reads every row from `cities` (seeded by `supabase/seed.sql`)
and dispatches each city by `publisher_type` to an adapter:

- `scraper/adapters/alp.py` (`ALPScraper`) for American Legal Publishing cities:
  Los Angeles, San Diego, San Francisco, Sacramento.
- `scraper/adapters/municode.py` (`MunicodeScraper`) for Municode cities: San
  Jose, Irvine, Long Beach, Oakland.

Both publishers serve JavaScript-rendered pages behind bot protection, so
`scraper/browser.py` drives headless Chromium via Playwright and pages are parsed
with BeautifulSoup. Each adapter finds ADU sections via the publisher's full-text
search using `scraper/keywords.py`, extracts the rendered text, sha256-hashes it
for change detection, and upserts through `scraper/db.py` into `zoning_sections`
(unique on `city_id, section_url`). On success `cities.last_scraped_at` is
stamped. A section whose `content_hash` is unchanged is skipped so weekly runs do
not churn `last_updated`.

Writes use the service-role key (`SUPABASE_SERVICE_ROLE_KEY`), which satisfies the
`service_role`-only write policy in `supabase/migrations/0002_rls.sql`.

### 2. Extract + validate (Render -> adu_rules)

`scraper/pipeline/run.py` runs after the scraper and processes new or changed
sections (no `adu_rules` row references the section yet, or the section's
`last_updated` is newer than the derived rows' `last_validated_at`):

1. `scraper/pipeline/extract.py` sends the raw section text to an LLM (Azure
   OpenAI if the `AZURE_OPENAI_*` vars are set, otherwise Anthropic) with output
   forced to the strict JSON schema in `scraper/pipeline/schema.py` (one object
   per zone district, every field required and nullable, no extra keys), then
   validates the response with `jsonschema`.
2. `scraper/pipeline/validate.py` compares each extracted field to its state-law
   baseline in `scraper/pipeline/baselines.py` (the single source of truth for
   floors/ceilings/must-equal values from AB 2221, SB 897, SB 9, Gov. Code
   66310-66342, AB 68/SB 13) and produces a per-field status plus a row-level
   `compliance_flag`.
3. `run.py` upserts into `adu_rules` (unique on `city_id, zone_district`), stores
   the per-field detail in `compliance_notes` (jsonb), and sets
   `last_validated_at`.

Compliance semantics (from `scraper/pipeline/README.md`): the row-level
`compliance_flag` enum is `compliant` / `more_restrictive` / `needs_review`, set
to the most severe field status (`more_restrictive` > `needs_review` >
`compliant`). The field list and per-field state floors/ceilings are also
documented inline in `supabase/migrations/0001_initial_schema.sql`.

### 3. Serve (Supabase Edge Functions)

Three Deno/TypeScript functions in `supabase/functions/` implement the public
API:

| Function | Public route | Returns |
|---|---|---|
| `cities` | `GET /v1/cities` | covered cities |
| `adu-rules` | `GET /v1/adu-rules?city=&zone=` | `adu_rules` rows joined to city |
| `compliance-flags` | `GET /v1/compliance-flags?city=` | compliance-flag summary |

Every request:

1. `_shared/auth.ts` extracts the raw key from `Authorization: Bearer ...` or
   `x-api-key`, sha256-hashes it, and calls the `increment_api_usage(key_hash)`
   RPC defined in `0001_initial_schema.sql`. That function atomically rolls the
   monthly window, checks the tier quota (free 50, starter 1000, pro 10000,
   enterprise effectively unlimited), and increments the counter.
2. `_shared/log.ts` writes a row to `usage_logs` with `status_code` and
   `billable` (2xx billable, 429/errors non-billable).
3. Missing/invalid/revoked keys return `401`; a reached quota returns `429` with
   `tier` and `limit` in the body.

Functions use the service-role client (`_shared/supabase.ts`, reading
`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` injected by the Edge runtime) because
they write `usage_logs` and increment `api_keys`, both `service_role`-restricted.
The clean `/v1/*` routes are produced by Vercel rewrites in front of the deployed
`https://<project-ref>.supabase.co/functions/v1/<name>` URLs.

### 4. Frontend (Vercel)

`frontend/` is a Next.js 14 App Router app:

- Marketing landing page with pricing from `frontend/lib/pricing.ts` (Free $0,
  Starter $19, Pro $49, Enterprise custom; quotas mirror `increment_api_usage()`).
- OpenAPI docs (`frontend/app/docs/`) rendering `docs/openapi.yaml`
  (served from `frontend/public/openapi.yaml`).
- Developer dashboard (`frontend/app/dashboard/`) behind Supabase Auth: API key
  generation (`frontend/lib/keys.ts` - raw key `adu_live_<48 hex>` shown once,
  only the sha256 hash and a 16-char prefix persisted), usage graphs from
  `usage_logs`, and Stripe billing.
- Stripe checkout (`frontend/app/api/stripe/checkout/route.ts`) and webhook
  (`frontend/app/api/stripe/webhook/route.ts`, `maxDuration` 30 in
  `frontend/vercel.json`). The webhook maps a Stripe price id to a tier via
  `frontend/lib/stripe.ts` and updates `api_keys.tier` for the user.
- `frontend/middleware.ts` refreshes the Supabase auth session using the anon key
  only. The service-role key is used only in server actions / route handlers.

### 5. Compliance QA (Render -> qa_alerts, Prompt 6)

The `qa_alerts` table already exists in `0001_initial_schema.sql` (columns:
`city_id`, `source`, `field`, `scraped_value`, `hcd_finding`, `severity`,
`resolved`). The scheduled QA worker (`scraper/qa/`, Prompt 6) pulls HCD's Housing
Element APR dataset and ADU ordinance review letters, cross-references flagged
jurisdictions against `adu_rules.compliance_flag`, writes discrepancies to
`qa_alerts`, and posts to Slack (`SLACK_WEBHOOK_URL`). Until Prompt 6 lands this
subtree is a placeholder; the table and env vars are already in place.

## Trust and security boundaries

- Public reads (`cities`, `zoning_sections`, `adu_rules`) go through the anon
  key; RLS in `0002_rls.sql` makes them read-only to anon and writable only by
  `service_role`. `api_keys` is owner-only.
- Only the backend workers and Edge Functions hold `SUPABASE_SERVICE_ROLE_KEY`;
  it is never shipped to the browser. It is always read from the environment,
  never hard-coded.
- API keys are stored only as sha256 hashes; the raw value is shown to the user
  once at creation.
- Quota enforcement is atomic in Postgres (`increment_api_usage()` uses
  `select ... for update`), so it cannot be raced from concurrent requests.

## Related docs

- `docs/DEPLOY.md` - ordered end-to-end deploy runbook.
- `docs/LAUNCH_CHECKLIST.md` - production launch checklist and monitoring.
- `docs/openapi.yaml` - the public API contract.
- Component READMEs: `scraper/README.md`, `scraper/pipeline/README.md`,
  `supabase/functions/README.md`.

<!-- easymd:log -->
## 🧾 Activity
- agent created the document (8248 chars)
- agent replaced the document (8347 chars)
- agent replaced the document (8390 chars)
- agent replaced the document (8433 chars)
<!-- /easymd:log -->
