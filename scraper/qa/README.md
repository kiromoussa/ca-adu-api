# HCD Compliance QA Cross-Check (Prompt 6)

A weekly Render cron job that reconciles our scraped `adu_rules` data against
California HCD's published findings and flags discrepancies for review.

## What it does

1. Reads `cities` and `adu_rules` from Supabase (service role).
2. Fetches HCD's Housing Element APR CSV from data.ca.gov (`hcd.py`) and checks
   the known HCD ADU ordinance review letters.
3. Cross-references (`crosscheck.py`):
   - HCD published a review letter for a city, but our data flags no
     non-compliance -> `warning`.
   - APR shows zero ADU permits while we report fully compliant -> `info`.
   - We flag zones `more_restrictive`; APR activity attached as context -> `info`.
4. Writes every discrepancy to the `qa_alerts` table and sends Slack / email
   alerts (`alerts.py`).

## Files

| File | Role |
|---|---|
| `hcd.py` | Fetch/parse APR CSV (CKAN resolver) + ordinance-letter availability |
| `crosscheck.py` | Pure discrepancy logic over fetched inputs (unit-testable) |
| `alerts.py` | `qa_alerts` persistence + Slack + email fan-out |
| `run.py` | Entrypoint / cron target |
| `render.yaml` | Weekly cron blueprint (Mon 06:00 UTC) |

## Run locally

```bash
pip install -r scraper/qa/requirements.txt
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...
export SLACK_WEBHOOK_URL=...            # optional
python -m scraper.qa.run --dry-run      # print discrepancies, write nothing
python -m scraper.qa.run                # persist + alert
python -m scraper.qa.run --city irvine  # single jurisdiction
```

## Environment

| Var | Required | Purpose |
|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | yes | DB read + qa_alerts write |
| `SLACK_WEBHOOK_URL` | optional | Slack alert channel |
| `QA_ALERT_EMAIL_TO` (+ `QA_SMTP_HOST`/`QA_SMTP_PORT`/`QA_SMTP_USER`/`QA_SMTP_PASSWORD`/`QA_ALERT_EMAIL_FROM`) | optional | Email alerts |
| `HCD_APR_CSV_URL` | optional | Pin the APR CSV resource if CKAN discovery fails |

## Notes

- The APR feed is a bulk CSV, not a live API; the CKAN `package_show` resolver
  picks the newest CSV resource automatically. Set `HCD_APR_CSV_URL` to pin it.
- Ordinance review letters are tracked by URL in `hcd.ORDINANCE_REVIEW_LETTERS`;
  add new jurisdictions as HCD publishes them.
- The job degrades gracefully: if the APR feed is unreachable it still runs the
  letter-based checks.
