"""POST /v1/feasibility - run a preliminary feasibility analysis for one
address and one project_type.

This is the only billable endpoint: one completed analysis (terminal
feasibility_status) is one billable unit. Errors, validation failures, and
unsupported_coverage responses are not billed. Passing an Idempotency-Key
makes retries safe.

Run: python feasibility.py
Requires: pip install httpx
"""
from __future__ import annotations

import uuid

from client import AduAtlasApiError, AduAtlasConfig, direct_config_from_env, rapidapi_config_from_env, request

REQUEST_BODY = {
    "address": "1234 S Main St, Los Angeles, CA 90015",
    "project_type": "detached_adu",
    "target_sqft": 800,
    "bedrooms": 1,
    "proposed_height_ft": 16,
    "existing_structure": {
        "type": "single_family",
        "has_garage": True,
        "year_built": 1948,
    },
    "options": {
        "near_transit": False,
        "historic_property": False,
        "include_envelope": True,
    },
}


def run_feasibility_analysis(config: AduAtlasConfig) -> dict:
    return request(
        config,
        "POST",
        "/v1/feasibility",
        json=REQUEST_BODY,
        extra_headers={"Idempotency-Key": str(uuid.uuid4())},
    )


def main() -> None:
    # Option A: RapidAPI gateway.
    config = rapidapi_config_from_env()

    # Option B: direct API key.
    # config = direct_config_from_env()

    try:
        analysis = run_feasibility_analysis(config)
    except AduAtlasApiError as exc:
        # unsupported_coverage, quota_exceeded, validation_error, etc. are all
        # raised as this typed exception and are never billed.
        print(f"ADU Atlas API error: {exc}")
        return

    print("analysis_id:", analysis["analysis_id"])
    print("feasibility_status:", analysis["feasibility_status"])
    print("disclaimer:", analysis["disclaimer"])


if __name__ == "__main__":
    main()


# --------------------------------------------------------------------------
# requests equivalent (pip install requests), if you prefer it to httpx:
#
#   import requests, uuid
#
#   resp = requests.post(
#       "https://property-feasibility4.p.rapidapi.com/feasibility",
#       headers={
#           "Content-Type": "application/json",
#           "X-RapidAPI-Key": RAPIDAPI_KEY,
#           "X-RapidAPI-Host": "property-feasibility4.p.rapidapi.com",
#           "Idempotency-Key": str(uuid.uuid4()),
#       },
#       json=REQUEST_BODY,
#       timeout=15,
#   )
#   resp.raise_for_status()
#   analysis = resp.json()
# --------------------------------------------------------------------------
