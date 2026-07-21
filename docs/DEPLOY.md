# Deploy Runbook

Ordered end-to-end deploy for the CA ADU Zoning API. Follow the steps in order:
each layer depends on the one before it (database -> API -> workers that fill it
-> frontend that fronts it). For the tick-box launch gate and monitoring setup see
`docs/LAUNCH_CHECKLIST.md`; for how the pieces fit together see
`docs/ARCHITECTURE.md`.

Per-component detail lives in the component READMEs, referenced at each step:
`scraper/README.md`, `scraper/pipeline/README.md`, `supabase/functions/README.md`.

## Conventions

- `SUPABASE_SERVICE_ROLE_KEY` is a secret. It is read from the environment in
  every component and must never be committed or exposed to the browser.
- Root `.env.example` lists the full variable set; `frontend/.env.example`,
  `scraper/.env.example`, and each README list the per-component subset.
- Do all of this against the production project only after it passes on a staging
  Supabase project and a Vercel preview.

## Prerequisites

- CLIs: `supabase`, `vercel`, `stripe` (or dashboards). Render via Blueprint.
- Node 20+ and Python 3.12 locally to run the test suites.
- Accounts/keys ready: Supabase prod project ref, Vercel project, Render account,
  Stripe account, Slack webhook, and a registered domain.

## Step 1 - Database and API (Supabase)

Schema is already authored (`supabase/migrations/0001_initial_schema.sql`,
`0002_rls.sql`) and Phase 1 is done. Reference: `supabase/functions/README.md`.

```bash
# Link the CLI to the production project.
supabase link --project-ref <prod-ref>

# Apply migrations (0001 schema + enums + increment_api_usage(), then 0002 RLS).
supabase db push

# Seed the 8 cities (idempotent: on conflict do update).
psql "$SUPABASE_DB_URL" -f supabase/seed.sql
# or run supabase/seed.sql from the SQL editor against prod.
```

Configure Auth for production in the dashboard (local reference is
`supabase/config.toml`): set `site_url` and `additional_redirect_urls` to the
prod frontend origin plus `/dashboard` and `/auth/callback`.

Deploy the three Edge Functions and set their secret:

```bash
supabase functions deploy cities
supabase functions deploy adu-rules
supabase functions deploy compliance-flags

# SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are injected by the Edge runtime;
# set explicitly only if serving outside Supabase.
supabase secrets set SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY"
```

Smoke test (a raw API key exists only after a user creates one in the dashboard,
so this fully verifies after Step 4; a key created via SQL works earlier):

```bash
curl -s "https://<prod-ref>.supabase.co/functions/v1/cities" \
  -H "x-api-key: <raw-api-key>"
```

## Step 2 - Scraper worker (Render)

Reference: `scraper/README.md` and the Blueprint `scraper/render.yaml` (cron
service `ca-adu-scraper`, schedule `0 3 * * 1`, `autoDeploy: false`).

1. In Render, create a Blueprint from this repo (or copy the `scraper/render.yaml`
   service block into a root-level `render.yaml`).
2. Confirm the commands from the Blueprint:
   - Build: `pip install -r scraper/requirements.txt && python -m playwright install --with-deps chromium`
   - Start: `python -m scraper.main`
3. Set secrets in the dashboard (declared `sync: false`): `SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`.
4. Keep the tuning vars (`SCRAPER_HEADLESS=true`, `SCRAPER_RATE_LIMIT_SECONDS=2`,
   `SCRAPER_MAX_SECTIONS_PER_CITY=25`, `PLAYWRIGHT_BROWSERS_PATH=0`,
   `PYTHON_VERSION=3.12.7`).
5. Trigger one manual run and confirm `zoning_sections` fills and
   `cities.last_scraped_at` is stamped. For a fast check set
   `SCRAPER_MAX_SECTIONS_PER_CITY=3`.

Local dry run before deploying:

```bash
pip install -r scraper/requirements.txt
python -m playwright install --with-deps chromium
cp scraper/.env.example scraper/.env   # set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
python -m scraper.main
```

## Step 3 - Extraction + validation pipeline (Render)

Reference: `scraper/pipeline/README.md`. This layer turns `zoning_sections` text
into `adu_rules`, so it must run after Step 2. `scraper/pipeline/` has no
`render.yaml` of its own; create a second Render `cron` service modeled on the
scraper's.

1. Create a Render `cron` service for the pipeline.
   - Build: `pip install -r scraper/pipeline/requirements.txt`
   - Start: `python scraper/pipeline/run.py`
2. Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, plus exactly one LLM
   provider:
   - Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
     `AZURE_OPENAI_DEPLOYMENT` (optional `AZURE_OPENAI_API_VERSION`), or
   - Anthropic: `ANTHROPIC_API_KEY` (default model `claude-opus-4-8`).
   If all Azure vars are set, the Azure path is used; otherwise Anthropic.
3. Schedule shortly after the scraper (for example `30 3 * * 1`).
4. Verify with a dry run before writing:

```bash
pip install -r scraper/pipeline/requirements.txt
python scraper/pipeline/run.py --dry-run --limit 5   # extract + validate, no writes
python scraper/pipeline/run.py                       # process new/changed sections
```

Confirm `adu_rules` rows appear with a `compliance_flag`, `compliance_notes`
populated, and `last_validated_at` set.

## Step 4 - Frontend, dashboard, billing (Vercel + Stripe)

Config: `frontend/vercel.json`. Env source of truth: `frontend/.env.example`.

### 4a. Stripe products and prices

Create monthly recurring Prices for Starter ($19) and Pro ($49); Free is the
default tier (no checkout) and Enterprise is contact-sales. Record the price ids
for `STRIPE_PRICE_STARTER` and `STRIPE_PRICE_PRO` (mapped in
`frontend/lib/stripe.ts`). Tier definitions live in `frontend/lib/pricing.ts`.

### 4b. Deploy the app

```bash
cd frontend
vercel link           # link to the Vercel project (first time)
vercel                # preview deploy
vercel --prod         # production deploy
```

Set env in the Vercel project (Production, and Preview with test/staging values):
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`, `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO`,
`NEXT_PUBLIC_SITE_URL`. Every helper in `frontend/lib/env.ts` throws on a missing
var, so a misconfiguration fails fast.

### 4c. Domain and API routing

- Add the domain in Vercel and point DNS at it.
- Expose the API under `/v1/*` either via an `api.` subdomain CNAMEd to
  `<prod-ref>.supabase.co` or via Vercel rewrites
  (`/v1/:path*` -> `https://<prod-ref>.supabase.co/functions/v1/:path*`).
- Ensure `docs/openapi.yaml` `servers:` matches the live host.

### 4d. Stripe webhook

Create a webhook at `https://<prod-domain>/api/stripe/webhook` subscribed to
`checkout.session.completed`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted` (handled in
`frontend/app/api/stripe/webhook/route.ts`). Put the signing secret in
`STRIPE_WEBHOOK_SECRET`. Test locally first:

```bash
stripe listen --forward-to localhost:3000/api/stripe/webhook
stripe trigger checkout.session.completed
```

Confirm a completed checkout updates `api_keys.tier` and stores the Stripe
customer/subscription ids; confirm a cancellation downgrades to `free`.

## Step 5 - Compliance QA worker (Render, Prompt 6)

Reference: `docs/ARCHITECTURE.md` section 5. The `qa_alerts` table already exists;
the worker code lands with Prompt 6. When it does, create a third Render `cron`
service for `scraper/qa/` with secrets `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `SLACK_WEBHOOK_URL`, `HCD_APR_DATASET_URL`, scheduled
after the pipeline (for example `0 5 * * 1`).

## Step 6 - Tests before flipping to production

Run both suites and confirm green (see spec Prompt 7). Do not `npm install` or
heavy installs in CI-restricted contexts; run these locally or in CI.

```bash
# Python: scraper + pipeline self-checks and tests
python -m py_compile scraper/pipeline/*.py
python scraper/pipeline/validate.py     # compliant / more_restrictive / needs_review cases
pytest                                  # scraper + pipeline integration tests

# Frontend: unit + e2e
cd frontend
npm test                                # vitest (pricing, keys, stripe)
npm run test:e2e                        # playwright (landing)
```

## Step 7 - Cutover

1. Swap Stripe env from test to live keys; recreate the webhook against the live
   endpoint.
2. Confirm all prod secrets are set (Supabase, Render x2/x3, Vercel) and none are
   committed.
3. Run the full manual end-to-end check from `docs/LAUNCH_CHECKLIST.md` section 6
   (sign up, generate key, call API, hit 429, upgrade, verify new quota).
4. Flip DNS to production and watch the `usage_logs` / `qa_alerts` dashboards for
   the first 24 hours.

## Ongoing operations

- Scraper runs weekly (`0 3 * * 1`); pipeline runs after it; both are
  `autoDeploy: false`, so deploy new code intentionally rather than on push.
- Reprocess everything after a baseline change:
  `python scraper/pipeline/run.py --all`.
- Regenerate frontend types after any schema migration:
  `cd frontend && npm run gen:types`.
- New Edge Function code ships with `supabase functions deploy <name>`.

<!-- easymd:log -->
## 🧾 Activity
- agent created the document (9177 chars)
- agent replaced the document (9276 chars)
- agent replaced the document (9319 chars)
- agent replaced the document (9362 chars)
<!-- /easymd:log -->
