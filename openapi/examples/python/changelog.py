"""GET /v1/changelog - public update history: ingestion runs, rule-version
changes, and coverage changes, grouped by jurisdiction. Read-only, not billed.

Run: python changelog.py
Requires: pip install httpx
"""
from __future__ import annotations

from client import direct_config_from_env, rapidapi_config_from_env, request


def main() -> None:
    # Option A: RapidAPI gateway.
    config = rapidapi_config_from_env()

    # Option B: direct API key.
    # config = direct_config_from_env()

    changelog = request(
        config,
        "GET",
        "/v1/changelog",
        params={"jurisdiction": "los_angeles", "limit": 20},
    )

    for entry in changelog["data"]:
        print(f"[{entry['occurred_at']}] {entry['jurisdiction_slug']} - {entry['change_type']}: {entry['summary']}")


if __name__ == "__main__":
    main()
