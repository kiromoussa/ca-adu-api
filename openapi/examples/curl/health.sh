#!/usr/bin/env bash
# GET /v1/health - service liveness, uptime, API/rules versions, and
# non-sensitive source freshness. No authentication required, not billed.
set -euo pipefail

curl -sS "https://api.aduatlas.example.com/v1/health" | python3 -m json.tool

# Also reachable through the RapidAPI gateway with no auth headers required:
curl -sS "https://aduatlas.p.rapidapi.com/v1/health" | python3 -m json.tool
