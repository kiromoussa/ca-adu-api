# Tests

Integration and unit tests for the CA ADU Zoning API. Everything runs fully
offline: no live network, no real Supabase, and no real Stripe. External systems
(Playwright, the Municode/Stripe HTTP APIs, the Supabase client and the
`increment_api_usage` RPC) are mocked or stubbed.

## Layout

| File | Runner | What it covers |
|---|---|---|
| `test_pipeline.py` | pytest | State-law validation: known non-compliant fields (e.g. `owner_occupancy_required_adu=true`, `side_rear_setback_min_ft=5`) flag `more_restrictive`; missing / conditional / over-permissive values flag `needs_review`; flag precedence. Imports baselines from `scraper/pipeline/baselines.py`. |
| `test_scraper.py` | pytest | Each adapter (ALP + Municode) locates at least one ADU section per seed city from fixture links; section parsing extracts text + numbering; the Municode API path pulls node ids from a mocked response; the Supabase upsert payload shape matches the `zoning_sections` columns. |
| `api.test.ts` | Vitest | Edge-function auth/quota layer: `401` on missing/invalid/revoked key, `429` when over quota, allow when under quota. |
| `billing.test.ts` | Vitest | Stripe webhook upgrades `api_keys.tier` on `checkout.session.completed` and `customer.subscription.updated`; downgrades to `free` on cancel; `400` on bad signature. |

## Python (pytest)

```bash
pip install -r tests/requirements-dev.txt
cd tests && pytest
```

- `conftest.py` puts the repo root and `scraper/pipeline` on `sys.path` so
  `import scraper.adapters.alp` and `import baselines` / `import validate`
  resolve exactly as they do in production.
- `test_pipeline.py` needs only pytest. `test_scraper.py` needs the scraper
  runtime deps (Playwright, BeautifulSoup, httpx, tenacity, supabase); if any are
  missing it skips itself via `pytest.importorskip` rather than failing. Playwright
  is only imported, never launched - no `playwright install` is required.

## TypeScript (Vitest)

```bash
cd tests && npm install && npm test
```

- `vitest.config.ts` aliases `@` to the `frontend/` package (so the webhook
  route's `@/lib/...` imports resolve, then get replaced by `vi.mock`) and aliases
  `next/server` / `server-only` to local stubs in `stubs/` so no Next.js runtime is
  needed.
- `api.test.ts` imports `supabase/functions/_shared/auth.ts` directly (its only
  external import is a type-only one, erased at build time) and drives it with a
  fake Supabase client.
- `billing.test.ts` imports the real webhook route and mocks Stripe, the Supabase
  service client, and the env accessors.
