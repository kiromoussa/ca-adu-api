"""GET /v1/jurisdictions - coverage status, supported project types, and the
source update date for every registered jurisdiction. Read-only, not billed.

Run: python jurisdictions.py
Requires: pip install httpx
"""
from __future__ import annotations

from client import direct_config_from_env, rapidapi_config_from_env, request


def main() -> None:
    # Option A: RapidAPI gateway.
    config = rapidapi_config_from_env()

    # Option B: direct API key.
    # config = direct_config_from_env()

    result = request(config, "GET", "/v1/jurisdictions")

    for jurisdiction in result["data"]:
        name = jurisdiction.get("display_name") or jurisdiction["name"]
        print(f"{name} ({jurisdiction['slug']}): {jurisdiction['coverage_status']}")


if __name__ == "__main__":
    main()
