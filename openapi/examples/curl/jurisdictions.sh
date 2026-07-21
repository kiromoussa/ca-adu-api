#!/usr/bin/env bash
# GET /v1/jurisdictions - coverage status, supported project types, and the
# source update date for every registered jurisdiction. Read-only, not billed.
set -euo pipefail

# Option A: RapidAPI gateway (the Hub-registered path has no /v1 prefix)
curl -sS "https://property-feasibility4.p.rapidapi.com/jurisdictions" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: property-feasibility4.p.rapidapi.com" | python3 -m json.tool

# Option B: Direct API
curl -sS "https://api.aduatlas.example.com/v1/jurisdictions" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" | python3 -m json.tool
