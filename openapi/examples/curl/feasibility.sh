#!/usr/bin/env bash
# POST /v1/feasibility - run a preliminary feasibility analysis for one
# address and one project_type. This is the only billable endpoint: one
# completed analysis (terminal feasibility_status) is one billable unit.
# Errors, validation failures, and unsupported_coverage responses are not
# billed. Supplying Idempotency-Key makes retries safe.
#
# Pick ONE of the two auth variants below. Never send both.
set -euo pipefail

REQUEST_BODY='{
  "address": "1234 S Main St, Los Angeles, CA 90015",
  "project_type": "detached_adu",
  "target_sqft": 800,
  "bedrooms": 1,
  "proposed_height_ft": 16,
  "existing_structure": {
    "type": "single_family",
    "has_garage": true,
    "year_built": 1948
  },
  "options": {
    "near_transit": false,
    "historic_property": false,
    "include_envelope": true
  }
}'

# -----------------------------------------------------------------------
# Option A: RapidAPI gateway (primary distribution)
# -----------------------------------------------------------------------
# RAPIDAPI_KEY is the "X-RapidAPI-Key" value shown on your RapidAPI app.
# Note: the RapidAPI-facing path is /feasibility (no /v1) - the version
# prefix lives in the origin base URL configured on the Hub, not in the
# path you call.
curl -sS -X POST "https://property-feasibility4.p.rapidapi.com/feasibility" \
  -H "Content-Type: application/json" \
  -H "X-RapidAPI-Key: ${RAPIDAPI_KEY}" \
  -H "X-RapidAPI-Host: property-feasibility4.p.rapidapi.com" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "${REQUEST_BODY}" | python3 -m json.tool

# -----------------------------------------------------------------------
# Option B: Direct API (self-serve API key, no RapidAPI gateway)
# -----------------------------------------------------------------------
# ADU_ATLAS_API_KEY is the raw key issued from the developer portal. It is
# sha256-hashed server-side and never logged or echoed back.
curl -sS -X POST "https://api.aduatlas.example.com/v1/feasibility" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${ADU_ATLAS_API_KEY}" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "${REQUEST_BODY}" | python3 -m json.tool
