#!/usr/bin/env bash
# GET /v1/analyses/{analysis_id} - retrieve a previously computed analysis.
# Private analyses require the same API key/consumer that created them; a
# public shareable analysis can instead be fetched with ?token=<share_token>
# and no API credentials at all. Read-only, not billed.
set -euo pipefail

ANALYSIS_ID="b8e6f9d2-4b7d-4b0e-9a45-1e6a9d5c9d2f"

# Option A: RapidAPI gateway (private analysis, owned by this consumer;
# the Hub-registered path has no /v1 prefix)
curl -sS "https://property-feasibility4.p.rapidapi.com/analyses/${ANALYSIS_ID}" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: property-feasibility4.p.rapidapi.com" | python3 -m json.tool

# Option B: Direct API (private analysis)
curl -sS "https://api.aduatlas.example.com/v1/analyses/${ANALYSIS_ID}" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" | python3 -m json.tool

# Option C: Public share token, no API credentials required
SHARE_TOKEN="shr_9k2m4p1qz7x3vb6n"
curl -sS "https://api.aduatlas.example.com/v1/analyses/${ANALYSIS_ID}?token=${SHARE_TOKEN}" | python3 -m json.tool
