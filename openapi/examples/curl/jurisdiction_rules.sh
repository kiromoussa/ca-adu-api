#!/usr/bin/env bash
# GET /v1/jurisdictions/{slug}/rules - citywide and zone-level rules for a
# jurisdiction, each attribute carrying per-field provenance and a
# state-baseline compliance flag, plus citations and version history.
# Read-only, not billed. Optional ?zone= and ?project_type= filters.
set -euo pipefail

SLUG="los_angeles"
ZONE="R1"
PROJECT_TYPE="detached_adu"

# Option A: RapidAPI gateway (the Hub-registered path has no /v1 prefix)
curl -sS "https://property-feasibility4.p.rapidapi.com/jurisdictions/${SLUG}/rules?zone=${ZONE}&project_type=${PROJECT_TYPE}" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: property-feasibility4.p.rapidapi.com" | python3 -m json.tool

# Option B: Direct API
curl -sS "https://api.aduatlas.example.com/v1/jurisdictions/${SLUG}/rules?zone=${ZONE}&project_type=${PROJECT_TYPE}" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" | python3 -m json.tool
