# Extraction + State-Law Validation Pipeline

Turns raw `zoning_sections` text into structured, state-law-validated `adu_rules`
rows. Runs on Render after the scraper worker (Prompt 2) finishes.

```
zoning_sections.raw_text
        |
        v
   extract.py   ── LLM structured extraction (Azure OpenAI or Anthropic)
        |            forced to schema.py -> list of per-zone rule dicts
        v
   validate.py  ── compare each field to baselines.py (state floors/ceilings)
        |            -> compliance_flag + per-field compliance_notes
        v
   run.py       ── upsert into adu_rules (unique on city_id + zone_district)
```

## Files

| File | Role |
|---|---|
| `baselines.py` | **Single source of truth.** Every state-law floor / ceiling / must-equal for each `adu_rules` field, with the governing law (AB 2221, SB 897, SB 9, Gov. Code 66310-66342, AB 68/SB 13). Reused by `schema.py`, `validate.py`, and the test suite. |
| `schema.py` | Strict JSON schema (built from `baselines.RULE_FIELDS`) that constrains LLM output: one object per zone district, every field required and nullable, no extra keys. |
| `extract.py` | LLM extraction step. Picks Azure OpenAI or Anthropic from the environment, forces structured JSON output against `schema.py`, validates the result with `jsonschema`. |
| `validate.py` | Compares each extracted field to its baseline and produces `compliance_flag` (`compliant` / `more_restrictive` / `needs_review`) plus per-field `compliance_notes`. |
| `run.py` | Entrypoint. Reads unprocessed / changed sections, extracts, validates, upserts via the service role, sets `last_validated_at`. |

## Compliance semantics

For each field, `validate.py` classifies the local value against the state baseline:

- **`compliant`** — the local value is within the state floor/ceiling, or matches
  the required boolean value.
- **`more_restrictive`** — the local rule is stricter than state law allows.
  Examples: `side_rear_setback_min_ft > 4`, `max_height_detached_standard_ft < 16`,
  `owner_occupancy_required_adu = true`, `permit_review_days > 60`.
- **`needs_review`** — the value is missing / not numeric / not boolean, is
  lawful only under conditions not knowable from zone text (`parking_required`,
  `owner_occupancy_required_jadu`), or is more permissive than the statute
  contemplates (e.g. `jadu_separate_sale_allowed = true`).

The row-level `compliance_flag` is the most severe field status
(`more_restrictive` > `needs_review` > `compliant`). Every field's detail
(status, expected threshold, actual value, law, note) is stored in the
`compliance_notes` jsonb column.

## Environment

Set in Render (or `.env` locally). Read from the environment only; never
hard-coded.

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service-role key (satisfies RLS write policy on `adu_rules`) |
| `ANTHROPIC_API_KEY` | Anthropic path (model `claude-opus-4-8` by default) |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI path |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI path |
| `AZURE_OPENAI_DEPLOYMENT` | Azure OpenAI deployment name (used as the model) |
| `AZURE_OPENAI_API_VERSION` | Optional; default `2024-10-21` |
| `ANTHROPIC_MODEL` | Optional override; default `claude-opus-4-8` |
| `EXTRACTION_MAX_TOKENS` | Optional; default `16000` |
| `LOG_LEVEL` | Optional; default `INFO` |

**Provider selection:** if the Azure variables are all set, the Azure OpenAI
path is used; otherwise the Anthropic path is used. Configure exactly one.

## Running

```bash
pip install -r requirements.txt

python run.py                 # process new / changed sections
python run.py --all           # reprocess every section
python run.py --city san_jose # limit to one city slug
python run.py --limit 5       # cap sections processed this run
python run.py --dry-run       # extract + validate, log results, do not write
```

`run.py` treats a section as needing processing when no `adu_rules` row
references it yet, or when the section's `last_updated` is newer than the last
`last_validated_at` of its derived rows.

## Self-checks

Each module has a lightweight `__main__` check (no network required):

```bash
python -m py_compile baselines.py schema.py extract.py validate.py run.py
python baselines.py   # baseline coverage
python schema.py      # schema shape
python validate.py    # compliant / more_restrictive / needs_review cases
python extract.py     # prompt + schema wiring (providers not called)
```
