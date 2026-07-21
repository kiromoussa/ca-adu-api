#!/usr/bin/env bash
# GET /v1/jurisdictions - coverage status, supported project types, and the
# source update date for every registered jurisdiction. Read-only, not billed.
set -euo pipefail

# Option A: RapidAPI gateway
curl -sS "https://aduatlas.p.rapidapi.com/v1/jurisdictions" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: aduatlas.p.rapidapi.com" | python3 -m json.tool

# Option B: Direct API
curl -sS "https://api.aduatlas.example.com/v1/jurisdictions" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" | python3 -m json.tool
