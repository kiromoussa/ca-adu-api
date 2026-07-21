# CA ADU Zoning API - Scraper Worker

Python service that scrapes ADU / zoning municipal-code sections for the 8 target
California cities and upserts the raw section text into Supabase's
`zoning_sections` table. It runs on Render as a weekly cron worker; the downstream
extraction/validation pipeline (Prompt 3) turns that raw text into the structured
`adu_rules` rows.

## How it works

1. `main.py` reads all rows from the `cities` table (seeded by
   `supabase/seed.sql`).
2. Each city is dispatched by `publisher_type` to an adapter:
   - `adapters/alp.py` - American Legal Publishing (`codelibrary.amlegal.com`):
     Los Angeles, San Diego, San Francisco, Sacramento.
   - `adapters/municode.py` - Municode (`library.municode.com` /
     `api.municode.com`): San Jose, Irvine, Long Beach, Oakland.
3. Each adapter locates ADU sections via the publisher's full-text search (using
   the keyword list in `keywords.py`), extracts the rendered section text, hashes
   it (sha256) for change detection, and upserts into `zoning_sections`.
4. On success, `cities.last_scraped_at` is stamped.

Both publishers serve JavaScript-rendered single-page apps behind bot protection
(plain HTTP returns 403), so pages are rendered with **Playwright (Chromium)** and
parsed with **BeautifulSoup**. Municode additionally tries the documented
`api.municode.com` JSON endpoints first for faster discovery, falling back to the
rendered search UI.

## Resilience

- **Retries + backoff** on every fetch via `tenacity` (exponential, capped).
- **Polite rate limiting** (`SCRAPER_RATE_LIMIT_SECONDS`, default 2s between
  requests).
- **Snapshots** of raw HTML to `scraper/snapshots/<slug>/` (git-ignored) for
  debugging selector drift.
- **Selector-drift guards**: content extraction tries a list of candidate CSS
  selectors and raises a clear `SelectorDriftError` (naming the URL and selectors
  tried) when a publisher changes its DOM, instead of silently writing garbage.
- **Change detection**: a section whose content hash is unchanged is skipped, so
  weekly runs do not churn `last_updated` on stable ordinances.
- One bad section or one bad city never aborts the whole run; the process exits
  non-zero only if *every* city fails.

## Configuration

All config comes from environment variables (see `config.py` and `.env.example`).
Required:

| Var | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (write access; read from env, never hard-coded) |

Optional tuning: `SCRAPER_HEADLESS`, `SCRAPER_RATE_LIMIT_SECONDS`,
`SCRAPER_MAX_SECTIONS_PER_CITY`, `SCRAPER_SAVE_SNAPSHOTS`, `SCRAPER_SNAPSHOT_DIR`,
`SCRAPER_NAV_TIMEOUT_MS`, `SCRAPER_SELECTOR_TIMEOUT_MS`, `SCRAPER_MAX_RETRIES`.

## Run locally

From the repository root:

```bash
# 1. Install dependencies
pip install -r scraper/requirements.txt

# 2. Install the Chromium browser Playwright drives
python -m playwright install --with-deps chromium

# 3. Provide credentials (copy and edit the example)
cp scraper/.env.example scraper/.env
# ...set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY

# 4. Run one full scrape pass
python -m scraper.main
```

Tips:
- Set `SCRAPER_HEADLESS=false` to watch the browser drive the sites while
  debugging.
- Set `SCRAPER_MAX_SECTIONS_PER_CITY=3` for a fast smoke run.
- Snapshots land in `scraper/snapshots/<city_slug>/` when
  `SCRAPER_SAVE_SNAPSHOTS=true`.

## Deploy to Render

`scraper/render.yaml` defines a `cron` service running Mondays at 03:00 UTC
(`0 3 * * 1`).

1. In Render, create a new **Blueprint** from this repo (or copy the service
   block into a root-level `render.yaml`).
2. Set the two secret env vars in the dashboard (`SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`) - they are declared `sync: false` so they are
   never committed.
3. The build command installs Python deps and the Chromium browser:
   `pip install -r scraper/requirements.txt && python -m playwright install --with-deps chromium`
4. The start command is `python -m scraper.main`.

## Files

```
scraper/
  __init__.py
  main.py            entrypoint: iterate cities, dispatch, upsert, stamp
  config.py          env-driven Settings
  browser.py         Playwright Chromium lifecycle
  db.py              Supabase service-role wrapper (upsert_zoning_section)
  base.py            BaseScraper: fetch/retry/snapshot/parse/hash/orchestrate
  keywords.py        ADU keyword list + per-city chapter hints
  adapters/
    __init__.py
    alp.py           ALPScraper
    municode.py      MunicodeScraper + MunicodeApiClient
  requirements.txt
  render.yaml
  .env.example
```

> This subtree owns everything under `scraper/` **except** `scraper/pipeline/`
> (extraction + validation, Prompt 3) and `scraper/qa/` (HCD cross-check,
> Prompt 6), which are owned by other components.
