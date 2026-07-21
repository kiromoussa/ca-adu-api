"""GET /v1/analyses/{analysis_id} - retrieve a previously computed analysis.

Private analyses require the same API key/consumer that created them. A
public shareable analysis can instead be fetched with a share token and no
API credentials at all. Read-only, not billed.

Run: python get_analysis.py
Requires: pip install httpx
"""
from __future__ import annotations

import httpx

from client import AduAtlasApiError, direct_config_from_env, rapidapi_config_from_env, request

ANALYSIS_ID = "b8e6f9d2-4b7d-4b0e-9a45-1e6a9d5c9d2f"


def main() -> None:
    # Option A: authenticated retrieval of a private analysis (RapidAPI gateway).
    config = rapidapi_config_from_env()

    # Option B: direct API key.
    # config = direct_config_from_env()

    try:
        analysis = request(config, "GET", f"/v1/analyses/{ANALYSIS_ID}")
        print("feasibility_status:", analysis["feasibility_status"])
    except AduAtlasApiError as exc:
        print(f"ADU Atlas API error: {exc}")

    # Option C: public shareable analysis via token, no API credentials.
    share_token = "shr_9k2m4p1qz7x3vb6n"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(
            f"https://api.aduatlas.example.com/v1/analyses/{ANALYSIS_ID}",
            params={"token": share_token},
        )
    resp.raise_for_status()
    public_analysis = resp.json()
    print("shared feasibility_status:", public_analysis["feasibility_status"])


if __name__ == "__main__":
    main()
