#!/usr/bin/env bash
# GET /v1/changelog - public update history: ingestion runs, rule-version
# changes, and coverage changes, grouped by jurisdiction. Read-only, not
# billed. Optional ?jurisdiction= and ?limit= (default 50, max 200).
set -euo pipefail

# Option A: RapidAPI gateway
curl -sS "https://aduatlas.p.rapidapi.com/v1/changelog?jurisdiction=los_angeles&limit=20" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: aduatlas.p.rapidapi.com" | python3 -m json.tool

# Option B: Direct API
curl -sS "https://api.aduatlas.example.com/v1/changelog?jurisdiction=los_angeles&limit=20" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" | python3 -m json.tool
