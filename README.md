# CA ADU Zoning API

Self-serve developer API mapping ADU / housing-density zoning codes for 8 major California cities. State-law-validated boolean/numeric fields, flat low-cost tiers.

Wedge vs. Zoneomics: narrow (CA ADU-only), deep (state-law-validated fields), cheap (flat tiers, no cliff overage).

## Stack

- **Supabase** - Postgres schema, Auth, RLS, Edge Functions, Storage for cached snapshots.
- **Render** - Python scraper cron worker + LLM extraction/validation pipeline + HCD QA cross-check job.
- **Vercel** - Next.js marketing site, OpenAPI docs, developer dashboard, Stripe billing.

## Layout

```
supabase/
  migrations/   Postgres schema, RLS, indexes
  functions/    Edge Functions: /v1/adu-rules, /v1/cities, /v1/compliance-flags
  seed.sql      8 cities + reference rows
scraper/
  adapters/     ALPScraper (LA, SD, SF, Sac) + MunicodeScraper (SJ, Irvine, LB, Oak)
  pipeline/     LLM extraction + state-law validation
  qa/           HCD APR CSV cross-check + alerts
frontend/       Next.js 14 App Router: marketing, docs, dashboard, billing
tests/          pytest (scraper/pipeline) + Vitest/Playwright (frontend)
docs/           OpenAPI spec, launch checklist
```

## Target cities

| City | Publisher | Adapter |
|---|---|---|
| Los Angeles | American Legal Publishing | ALP |
| San Diego | American Legal Publishing | ALP |
| San Francisco | American Legal Publishing | ALP |
| Sacramento | American Legal Publishing | ALP |
| San Jose | Municode | Municode |
| Irvine | Municode | Municode |
| Long Beach | Municode | Municode |
| Oakland | Municode | Municode |

## State-law ground truth

Every scraped numeric/boolean field is validated against state floors/ceilings (AB 2221, SB 897, SB 9, Gov. Code §§66310-66342). A local value more restrictive than the state baseline is flagged `more_restrictive` or `needs_review`. See `supabase/migrations` comments and `scraper/pipeline/baselines.py`.

## Build sequence

1. Supabase schema + RLS
2. Scraper worker (Render)
3. Extraction + state-law validation pipeline
4. Supabase Edge Function API layer
5. Vercel frontend + dashboard + billing
6. HCD compliance QA job
7. Testing + launch checklist

See `docs/LAUNCH_CHECKLIST.md`.
