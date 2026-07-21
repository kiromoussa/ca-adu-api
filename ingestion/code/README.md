# ingestion/code - municipal-code ingestion + OFFLINE extraction + QA

OFFLINE-only component of ADU Atlas API. It turns official municipal code into
immutable, source-cited data that the deterministic request path can later use:

1. **ingest** - scrape a jurisdiction's municipal code, capture each section as
   an **immutable, content-hashed `source_snapshots` row** (raw bytes uploaded to
   Supabase Storage; history never overwritten), and write `zoning_sections`
   with a provenance link to that snapshot.
2. **extract** - run an **offline LLM** over each section to produce structured
   ADU / JADU / SB 9 **rule candidates**: `zoning_rules` (`review_status=pending`
   - never auto-verified) plus one `rule_attributes` row per field, each carrying
   value, unit, per-field confidence, verbatim evidence, and source provenance.
3. **validate** - compare every extracted attribute to the `state_rule_baselines`
   table and queue `qa_issues` for anything more restrictive than state law,
   over-permissive/unlawful, conditional, or lacking a baseline; set the
   per-field and per-rule `compliance_flag`.

> This package MUST NEVER be imported by the API request path
> (`services/api`, `services/core`). The request path is deterministic
> (versioned rules + PostGIS + source-linked data), with **no LLM**. Importing
> this package while `ADU_ATLAS_REQUEST_PATH` is set raises immediately.

## Non-negotiables honored here

- **No LLM on the request path.** The LLM runs only in `extract.py`, offline, and
  its output is always a review candidate (`review_status=pending`). Nothing is
  marked `verified` automatically.
- **Immutable snapshots.** `source_snapshots` is append-only and content-hashed;
  identical captures dedup on `content_hash`, changed captures get a new
  monotonic `version`. Enforced by a DB trigger and respected here.
- **Provenance everywhere.** Each `rule_attributes` row carries `source_url`,
  `source_title`, `source_section`, `retrieved_at`, `confidence`, `data_status`.
- **State-baseline honesty.** Local rules more restrictive than the state
  baseline are flagged `possibly_more_restrictive_than_state_baseline` /
  `needs_review` and queued to `qa_issues`; the local source is preserved and
  never discarded.
- **LA City first.** `los_angeles` is the v1 target and the CLI default. Other
  jurisdictions stay `coverage_status=planned` until ingested + tested.

## Publishers (proven approach reused from the prior scraper)

- **American Legal** (Los Angeles, San Diego, San Francisco, Sacramento):
  `curl_cffi` impersonating Chrome to clear Cloudflare, `/api/search` discovery
  (`s = base64(zlib(json({query})))`), and
  `/api/render-doc/{client}/{version}/{code}/{docid}/` for clean section HTML.
- **Municode** (San Jose, Irvine, Long Beach, Oakland): `api.municode.com`
  node-id discovery with a Playwright search fallback, then Playwright render of
  the `nodeId` page.

## Layout

```
config.py        env-driven Settings (Supabase, Azure OpenAI v1, politeness, snapshots)
registry.py      read-only loader for config/jurisdictions.yaml + sources.yaml
baselines.py     field catalog: dtype, comparison kind, project-type scope, spec value
schema.py        strict JSON schema for LLM extraction (value + confidence + evidence)
keywords.py      ADU search phrases + per-jurisdiction chapter hints
normalize.py     text/HTML helpers, numbering parser, hashing
fetchers/        american_legal.py (curl_cffi + render-doc), municode.py (Playwright)
db.py            service-role Supabase store for the 16-table ADU Atlas schema
ingest.py        scrape -> immutable snapshot -> zoning_sections
extract.py       OFFLINE LLM -> zoning_rules (pending) + rule_attributes
validate.py      rule_attributes vs state_rule_baselines -> qa_issues + flags
run.py           CLI entrypoint (ingest | extract | validate | all)
```

## Usage

```bash
pip install -r requirements.txt
playwright install --with-deps chromium      # Municode path only

# environment (never hard-coded)
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/openai/v1
export AZURE_OPENAI_API_KEY=... AZURE_OPENAI_DEPLOYMENT=gpt-5.4

python run.py ingest   --jurisdiction los_angeles
python run.py extract  --jurisdiction los_angeles --limit 5
python run.py validate --jurisdiction los_angeles
python run.py all      --jurisdiction los_angeles --dry-run
python run.py ingest   --all-jurisdictions
```

`extract` and `validate` support `--dry-run` (compute without writing).
`extract` supports `--provider {azure_openai,anthropic}` (default: auto, Azure
preferred). Run from within this directory (`ingestion/code/`).

## Configuration

| Env var | Purpose | Default |
| --- | --- | --- |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | service-role DB + Storage | required |
| `AZURE_OPENAI_ENDPOINT` | v1 endpoint ending `/openai/v1` | - |
| `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` | model auth + name | - |
| `AZURE_OPENAI_API_VERSION` | classic surface only | `2024-10-21` |
| `EXTRACTION_MAX_TOKENS` | `max_completion_tokens` cap | `16000` |
| `ADU_SNAPSHOT_BUCKET` | Storage bucket for raw snapshots | `source-snapshots` |
| `ADU_UPLOAD_SNAPSHOTS` | upload raw bytes to Storage | `true` |
| `ADU_CODE_RATE_LIMIT_SECONDS` | politeness delay between requests | `2.0` |
| `ADU_CODE_MAX_SECTIONS_PER_JURISDICTION` | discovery cap | `25` |
| `ADU_CONFIG_DIR` | override repo `config/` location | repo `config/` |

## Self-checks (offline, no network / no API key)

Each module runs its own check when executed directly:

```bash
python normalize.py && python baselines.py && python schema.py \
  && python keywords.py && python config.py && python registry.py \
  && python extract.py && python validate.py
```
