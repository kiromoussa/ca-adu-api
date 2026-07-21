#!/usr/bin/env bash
# GET /v1/health - service liveness, uptime, API/rules versions, and
# non-sensitive source freshness. No authentication required, not billed.
set -euo pipefail

curl -sS "https://api.aduatlas.example.com/v1/health" | python3 -m json.tool

# Also reachable through the RapidAPI gateway (Hub-registered path has no
# /v1 prefix); still no auth headers required:
curl -sS "https://property-feasibility4.p.rapidapi.com/health" | python3 -m json.tool
