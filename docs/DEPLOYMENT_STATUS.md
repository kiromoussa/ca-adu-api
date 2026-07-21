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

The 18 rows from the trial runs were mismatched to their nodes and were deleted
so the DB is not misleading; `zoning_sections` and `adu_rules` are empty. No
fabricated data was inserted. Hardening these two adapters (anti-bot for ALP,
per-node chunk selection for Municode) is the next engineering task before real
ADU rules can be populated and served.
