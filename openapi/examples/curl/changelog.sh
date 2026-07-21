#!/usr/bin/env bash
# GET /v1/changelog - public update history: ingestion runs, rule-version
# changes, and coverage changes, grouped by jurisdiction. Read-only, not
# billed. Optional ?jurisdiction= and ?limit= (default 50, max 200).
set -euo pipefail

# Option A: RapidAPI gateway (the Hub-registered path has no /v1 prefix)
curl -sS "https://property-feasibility4.p.rapidapi.com/changelog?jurisdiction=los_angeles&limit=20" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: property-feasibility4.p.rapidapi.com" | python3 -m json.tool

# Option B: Direct API
curl -sS "https://api.aduatlas.example.com/v1/changelog?jurisdiction=los_angeles&limit=20" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" | python3 -m json.tool
