"""GET /v1/health - service liveness, uptime, API/rules versions, and
non-sensitive source freshness. No authentication required, not billed.

Run: python health.py
Requires: pip install httpx
"""
from __future__ import annotations

import httpx


def main() -> None:
    # No auth headers required for /v1/health, on either host.
    with httpx.Client(timeout=15.0) as client:
        resp = client.get("https://api.aduatlas.example.com/v1/health")
    resp.raise_for_status()
    health = resp.json()

    print(f"status: {health['status']} (api {health['api_version']})")
    for source in health.get("sources", []):
        print(f"  {source['key']}: {source['data_status']}")


if __name__ == "__main__":
    main()
