# Launch Checklist

Production launch checklist for the CA ADU Zoning API. Work top to bottom; the
ordered runbook with exact commands is in `docs/DEPLOY.md`, and the data flow is
in `docs/ARCHITECTURE.md`. Check each box before flipping DNS to production.

Provider CLIs assumed: `supabase`, `vercel`, `stripe`, and the Render dashboard
(Blueprint / `render.yaml`).

## 0. Prerequisites

- [ ] Supabase production project created; note the project ref.
- [ ] Vercel project created and linked to this repo (root `frontend/`).
- [ ] Render account with access to this repo.
- [ ] Stripe account (start in test mode, switch to live keys at cutover).
- [ ] Slack incoming webhook URL for QA alerts.
- [ ] A registered apex domain (for example `caaduapi.com`) and an `api`
      subdomain plan.
- [ ] `SUPABASE_SERVICE_ROLE_KEY` handled as a secret everywhere. Never commit
      it; it is read from the environment in every component.

## 1. Supabase production project

Migrations and schema are already written under `supabase/migrations/`
(`0001_initial_schema.sql`, `0002_rls.sql`) and `supabase/seed.sql`. Phase 1 is
done; this step promotes them to the prod project.

- [ ] Link the CLI to prod: `supabase link --project-ref <prod-ref>`.
- [ ] Push migrations: `supabase db push` (applies `0001` then `0002`).
- [ ] Seed the 8 cities: run `supabase/seed.sql` against prod (idempotent - it
      `on conflict (slug) do update`s `publisher_type` and `base_url`).
- [ ] Verify RLS is on: `cities` / `zoning_sections` / `adu_rules` readable by
      anon, writable only by `service_role`; `api_keys` owner-only.
- [ ] Confirm the `increment_api_usage()` function exists and its tier limits
      match `frontend/lib/pricing.ts` (free 50, starter 1000, pro 10000,
      enterprise unlimited).
- [ ] Configure Auth (`supabase/config.toml` is the local reference): set the
      production `site_url` and `additional_redirect_urls` to the prod frontend
      origin plus `/dashboard` and `/auth/callback`. Decide on email
      confirmations for prod (local has them disabled).
- [ ] Deploy the three Edge Functions:
      `supabase functions deploy cities`,
      `supabase functions deploy adu-rules`,
      `supabase functions deploy compliance-flags`.
      All three are configured `verify_jwt = false` in `config.toml` (API-key
      auth is enforced inside the function, not by the JWT gate).
- [ ] Set function secrets:
      `supabase secrets set SUPABASE_SERVICE_ROLE_KEY="..."`.
      (`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected automatically
      by the Edge runtime; set explicitly only if serving elsewhere.)
- [ ] Smoke test a deployed function with a real key:
      `curl "https://<prod-ref>.supabase.co/functions/v1/cities" -H "x-api-key: <raw-key>"`.
- [ ] Regenerate frontend types if the schema changed:
      `npm run gen:types` (writes `frontend/lib/database.types.ts`).

## 2. Vercel (frontend, DNS, env)

Config lives in `frontend/vercel.json` (Next.js framework, `sfo1` region, and a
30s `maxDuration` for `app/api/stripe/webhook/route.ts`).

### Domain / DNS

- [ ] Add the apex domain and `www` to the Vercel project.
- [ ] Point DNS at Vercel (apex A/ALIAS record and `www` CNAME per Vercel's
      instructions).
- [ ] Decide how `/v1/*` reaches the Edge Functions: either an `api.` subdomain
      that CNAMEs to `<prod-ref>.supabase.co`, or Vercel rewrites from
      `/v1/:path*` to `https://<prod-ref>.supabase.co/functions/v1/:path*` (the
      clean public routes referenced in `supabase/functions/README.md`). Confirm
      `docs/openapi.yaml` `servers:` matches whichever you pick.
- [ ] Verify TLS certs issued for all hostnames.

### Environment variables

Source of truth is `frontend/.env.example`. Set these in the Vercel project for
Production (and Preview where noted).

- [ ] `NEXT_PUBLIC_SUPABASE_URL` (client-safe) - prod project URL.
- [ ] `NEXT_PUBLIC_SUPABASE_ANON_KEY` (client-safe) - prod anon key.
- [ ] `SUPABASE_URL` (server) - prod project URL.
- [ ] `SUPABASE_SERVICE_ROLE_KEY` (server, secret) - never exposed to browser.
- [ ] `STRIPE_SECRET_KEY` (live key at cutover).
- [ ] `STRIPE_WEBHOOK_SECRET` (from the prod webhook endpoint, step 4).
- [ ] `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` (live key at cutover).
- [ ] `STRIPE_PRICE_STARTER` / `STRIPE_PRICE_PRO` (live price ids from step 4).
- [ ] `NEXT_PUBLIC_SITE_URL` - the production origin (used for Stripe redirect
      URLs in `app/api/stripe/checkout/route.ts`). Every env helper in
      `frontend/lib/env.ts` throws if its var is missing, so a missing value
      fails fast rather than silently.

### Preview vs Production

- [ ] Preview deployments (PRs / non-prod branches) point at a separate Supabase
      project or a throwaway schema and Stripe test keys, so preview traffic
      never mutates production `api_keys` or bills real cards.
- [ ] `NEXT_PUBLIC_SITE_URL` differs per environment (preview URL vs prod
      domain); confirm Stripe success/cancel redirects resolve on each.
- [ ] Promote to Production only after a preview deploy passes the dashboard,
      docs, and checkout smoke tests.

## 3. Render (scraper, pipeline, QA workers)

The scraper ships a Blueprint at `scraper/render.yaml` (a `cron` service,
`ca-adu-scraper`, Python, `plan: starter`, schedule `0 3 * * 1` - Mondays 03:00
UTC). Create the sibling pipeline and QA cron services from the same pattern.

### Scraper service

- [ ] Create a Render Blueprint from this repo (or copy the `scraper/render.yaml`
      service block into a root-level `render.yaml`).
- [ ] Build command:
      `pip install -r scraper/requirements.txt && python -m playwright install --with-deps chromium`.
- [ ] Start command: `python -m scraper.main`.
- [ ] Secrets (declared `sync: false`, set in the dashboard):
      `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- [ ] Tuning env (defaults in `scraper/config.py`): `SCRAPER_HEADLESS=true`,
      `SCRAPER_RATE_LIMIT_SECONDS=2`, `SCRAPER_MAX_SECTIONS_PER_CITY=25`,
      `SCRAPER_SAVE_SNAPSHOTS=false`, `PLAYWRIGHT_BROWSERS_PATH=0`,
      `PYTHON_VERSION=3.12.7`.
- [ ] Cron schedule: `0 3 * * 1` (weekly). Playwright/Chromium is memory-hungry;
      keep `plan: starter` or higher and cap `SCRAPER_MAX_SECTIONS_PER_CITY` to
      control run time.

### Extraction + validation pipeline service

- [ ] Create a second Render `cron` service for `scraper/pipeline/`.
- [ ] Build command: `pip install -r scraper/pipeline/requirements.txt`.
- [ ] Start command: `python scraper/pipeline/run.py` (processes new/changed
      sections; add `--all` only for a full reprocess).
- [ ] Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and exactly one LLM
      provider - either the Azure trio (`AZURE_OPENAI_ENDPOINT`,
      `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, optional
      `AZURE_OPENAI_API_VERSION`) or `ANTHROPIC_API_KEY` (default model
      `claude-opus-4-8`). If the Azure vars are all set, the Azure path is used.
- [ ] Schedule it to run after the scraper (for example `30 3 * * 1`, 30 minutes
      after the 03:00 scrape) so it picks up freshly changed sections.

### Compliance QA worker (Prompt 6)

- [ ] Create a third Render `cron` service for `scraper/qa/` once Prompt 6 lands
      (the `qa_alerts` table and env vars already exist).
- [ ] Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SLACK_WEBHOOK_URL`,
      `HCD_APR_DATASET_URL`
      (`https://data.ca.gov/dataset/housing-element-annual-progress-report-apr-data-by-jurisdiction-and-year`).
- [ ] Schedule daily or weekly after the pipeline (for example `0 5 * * 1`).

### Scaling notes

- [ ] Set `autoDeploy: false` (as in `scraper/render.yaml`) so a push does not
      redeploy a worker mid-run; deploy intentionally.
- [ ] These are cron jobs, not web services - no horizontal scaling needed; size
      the instance for peak memory (Chromium) rather than concurrency.

## 4. Stripe (products, prices, webhook)

Tiers come from `frontend/lib/pricing.ts`; the tier<->price mapping is in
`frontend/lib/stripe.ts` (`priceIdForTier` / `tierForPriceId`), driven by the
`STRIPE_PRICE_STARTER` and `STRIPE_PRICE_PRO` env vars.

- [ ] Create Products + recurring monthly Prices:
      - Free - $0/month, 50 lookups. No Stripe price needed (default tier for a
        new user; no checkout).
      - Starter - $19/month, 1,000 lookups. Create price; set its id as
        `STRIPE_PRICE_STARTER`.
      - Pro - $49/month, 10,000 lookups. Create price; set its id as
        `STRIPE_PRICE_PRO`.
      - Enterprise - custom. No self-serve price; handled as "contact sales"
        (`checkoutTier` is absent in `pricing.ts`).
- [ ] (Optional) Configure metered overage at $0.02/lookup (`OVERAGE_RATE` in
      `pricing.ts`) if billing overage rather than hard-capping.
- [ ] Create a webhook endpoint pointing at
      `https://<prod-domain>/api/stripe/webhook` subscribed to:
      `checkout.session.completed`, `customer.subscription.created`,
      `customer.subscription.updated`, `customer.subscription.deleted` (the exact
      events handled in `app/api/stripe/webhook/route.ts`).
- [ ] Copy the endpoint signing secret into `STRIPE_WEBHOOK_SECRET` on Vercel.
      The handler verifies the signature with the raw body (`runtime = nodejs`,
      `dynamic = force-dynamic`) and rejects unsigned/invalid requests with 400.
- [ ] Verify the round trip: complete a test checkout, confirm the webhook
      updates `api_keys.tier` and stores `stripe_customer_id` /
      `stripe_subscription_id` for the user, and that a cancelled subscription
      downgrades the user to `free`.
- [ ] At cutover, swap all four Stripe env vars from test to live values and
      recreate the webhook against the live endpoint.

## 5. Monitoring and alerting

- [ ] Usage dashboards from `usage_logs`: track requests per key, per endpoint,
      per city, `status_code` distribution, and billable vs non-billable volume.
      Indexes `idx_usage_logs_key` and `idx_usage_logs_created` support these
      queries. The developer dashboard already surfaces per-key usage graphs from
      this table (`frontend/app/dashboard/`).
- [ ] Alert on the `429` rate (quota exhaustion) - a spike signals either a tier
      that is too small for a paying customer or a runaway integration.
- [ ] Alert on `5xx` from the Edge Functions and from the Stripe webhook route.
- [ ] QA discrepancies land in `qa_alerts` (`severity` info/warning/critical);
      route `critical` rows to Slack via `SLACK_WEBHOOK_URL`. Track unresolved
      alerts (`resolved = false`).
- [ ] Data freshness: alert if any city's `cities.last_scraped_at` is older than
      ~10 days (weekly cron plus slack), or if `adu_rules.last_validated_at` lags
      the source section's `last_updated`.
- [ ] Render cron health: alert on failed or skipped scraper/pipeline runs (the
      scraper exits non-zero only if every city fails, so also watch partial
      failures in logs).
- [ ] Stripe: enable Stripe's own failed-payment and dispute alerts.
- [ ] Supabase: watch DB connection count, error rate, and Edge Function logs.

## 6. Final pre-launch gate

- [ ] Tests green: `pytest` (scraper/pipeline) and `npm test` + `npm run
      test:e2e` (frontend) - see `docs/DEPLOY.md`.
- [ ] A real end-to-end run: sign up in the dashboard, generate a key, call
      `/v1/adu-rules` and `/v1/cities`, hit the free-tier `429`, upgrade via
      Stripe, confirm the higher quota takes effect.
- [ ] `docs/openapi.yaml` `servers:` URL matches the live API host.
- [ ] All secrets set in prod (Vercel, Render, Supabase); none committed to git.
- [ ] Flip DNS to production and monitor the dashboards for the first 24 hours.

<!-- easymd:log -->
## 🧾 Activity
- agent created the document (11696 chars)
- agent replaced the document (11796 chars)
- agent replaced the document (11840 chars)
- agent replaced the document (11884 chars)
<!-- /easymd:log -->
