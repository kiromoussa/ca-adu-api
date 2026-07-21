# Tests

Integration and unit tests for the ADU Atlas API. Everything here runs fully
offline except `tests/integration`, which needs a local ephemeral PostGIS
container (see below) and skips itself cleanly when one isn't available.

For the deterministic feasibility engine's own unit tests (pure Python, no
database, no network - the ones exercised on every request path change), see
`services/tests/` instead; this directory covers the edge-function auth layer,
Vitest-side, plus the full-stack integration path.

## Layout

| File | Runner | What it covers |
|---|---|---|
| `api.test.ts` | Vitest | Edge-function auth/quota layer (`supabase/functions/_shared/auth.ts`): `401` on missing/invalid/revoked key, `429` when over quota, allow when under quota. |
| `integration/test_feasibility_flow.py` | pytest | Full request path against a real, migrated PostGIS: seeds a tiny LA fixture and drives `POST /v1/feasibility` through FastAPI's `TestClient`. |

## Python (pytest)

```bash
pip install -r tests/requirements-dev.txt
cd tests && pytest
```

- `tests/integration/conftest.py` puts the repo root on `sys.path` itself (no
  root-level `conftest.py` is needed) so `import services...` resolves.
- The integration suite is destructive (it resets the `public` schema), so it
  only ever runs against `ADU_TEST_DB_URL` (default: the isolated PostGIS in
  `tests/integration/docker-compose.yml` on port 54330) and skips itself
  entirely - not a failure - if psycopg, `psql`, or that database aren't
  reachable.

## TypeScript (Vitest)

```bash
cd tests && npm install && npm test
```

- `api.test.ts` imports `supabase/functions/_shared/auth.ts` directly and
  drives it with a fake Supabase client - no network, no real database.
