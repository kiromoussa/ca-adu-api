# Deployment Status - live resources

This documents what has actually been provisioned and deployed (as of the initial
go-live). Secrets live only in the gitignored `.secrets/` dir locally and in each
platform's env store; none are committed.

## Supabase (API + database) - LIVE

- Project: `ca-adu-api`, ref `abtapphfcpmootzctmec`, region us-east-1, free tier.
- URL: `https://abtapphfcpmootzctmec.supabase.co`
- Migrations applied: `0001_initial_schema`, `0002_rls`, `0003_fix_increment_usage_ambiguity`.
- Seeded: 8 cities.
- Edge Functions deployed (verify_jwt off; they do their own API-key auth):
  - `GET /functions/v1/cities`
  - `GET /functions/v1/adu-rules?city=&zone=`
  - `GET /functions/v1/compliance-flags?city=`
- Verified live: 401 without key, 200 with a valid key (8 cities), 429 when the
  free 50/mo quota is exceeded. usage_logs records each call.

Base API URL: `https://abtapphfcpmootzctmec.supabase.co/functions/v1`

## Vercel (frontend) - LIVE

- Project: `kiro-moussas-projects/ca-adu-api`
- Production: `https://ca-adu-api.vercel.app` (landing, `/docs`, `/dashboard` all 200).
- Env set for production + preview: Supabase URL/anon/service-role, Stripe
  secret/publishable/prices/webhook secret, site URL.

## Stripe (billing) - LIVE (TEST MODE)

- Account: `acct_...` (Plateform), test mode.
- Products/prices: Starter `$19/mo`, Pro `$49/mo`.
- Webhook endpoint -> `https://ca-adu-api.vercel.app/api/stripe/webhook`
  (checkout.session.completed, customer.subscription.created/updated/deleted).
- Note: created under the existing Stripe account in TEST mode. Move to a
  dedicated account / live mode before charging real customers.

## GitHub - LIVE

- Repo: `https://github.com/kiromoussa/ca-adu-api` (private), branch `main`.

## Render (scraper / pipeline / QA workers) - PENDING one dashboard step

Render provisions blueprints through its GitHub App, which must be installed on
the repo from the dashboard (not scriptable headlessly). To finish:

1. Render Dashboard -> New -> Blueprint -> connect `kiromoussa/ca-adu-api`.
2. Render auto-detects the root `render.yaml` (3 cron workers: scraper 03:00,
   pipeline 04:30, QA 06:00 UTC Mondays).
3. Set the `sync:false` secrets once in the dashboard: `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`, an LLM provider (`ANTHROPIC_API_KEY` or the
   `AZURE_OPENAI_*` trio), `SLACK_WEBHOOK_URL`, `HCD_APR_CSV_URL`.

Until then, `adu_rules` is empty, so `/adu-rules` returns `[]` and
`/compliance-flags` shows zero counts.

## Scraper - live-run findings (data population BLOCKED on adapter hardening)

The scraper was run locally against the live sites and the real Supabase project.
It executes end-to-end (launches Chromium, discovers nodes, writes to
`zoning_sections`), but the extracted text is not yet clean enough to feed the
LLM extractor. Two concrete issues, both known-hard anti-bot/SPA problems:

1. ALP sites (LA, San Diego, SF, Sacramento) - `codelibrary.amlegal.com` is
   behind a Cloudflare bot check. The headless browser receives the "security
   verification" interstitial instead of code text. Needs: a stealth/undetected
   browser profile or a residential proxy, or Cloudflare-clearance handling.

2. Municode sites (San Jose, Irvine, Long Beach, Oakland) - node discovery works
   (correct ADU node ids are found via the internal search API), but the DOM
   content extraction returns the wrong chunk: the SPA hydrates the whole
   chapter and `?nodeId=` only anchors, so multiple nodes yielded identical
   unrelated text. Needs: scope extraction to the specific chunk element that
   matches the requested nodeId (wait for and read `#<nodeId>` / the matching
   `.chunk` container), not the first content wrapper.

### Update - full pipeline proven live end to end (San Jose)

The extraction pipeline now runs against the live system:

- LLM: created a `gpt-5.4-mini` deployment on the Azure OpenAI resource
  `kiromoussaai` (via `az`; no chat model had been deployed). `extract.py` was
  updated to support the Azure OpenAI-compatible "v1" endpoint surface
  (`/openai/v1`, `max_completion_tokens`) in addition to the classic surface.
- San Jose: Playwright renders the real ADU chapter (Title 20, Ch 20.80 Part
  2.75), the ADU section text is isolated, `gpt-5.4-mini` extracts structured
  fields, `validate.py` flags them against the state-law baselines, and the rows
  are upserted. `GET /v1/adu-rules?city=san_jose` now returns real, validated
  data (e.g. side/rear setback 4 ft, owner-occupancy false, JADU allowed,
  parking not required). This is genuine extracted ordinance data, not seeded.

Remaining to reach full production quality/coverage (iterative, not blocking):

1. ALP cities (LA, San Diego, SF, Sacramento): the headless browser still hits
   Cloudflare's bot interstitial. Needs a stealth browser profile / clearance
   handling or a residential proxy.
2. Municode text isolation: currently a keyword-window slice of the rendered
   page; scoping extraction to the exact `nodeId` chunk (or Municode's content
   API, whose endpoint is not yet resolved) would improve precision.
3. Extraction field mapping: the mini model occasionally maps a value to a
   neighbouring field (e.g. the attached-height limit into the detached field);
   a stronger model or few-shot examples tightens this. Rows the model is unsure
   about are correctly flagged `needs_review`.

No fabricated data was inserted at any point; empty/uncertain fields are null or
`needs_review`.
