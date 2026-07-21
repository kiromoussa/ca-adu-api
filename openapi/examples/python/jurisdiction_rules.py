"""GET /v1/jurisdictions/{slug}/rules - citywide and zone-level rules for a
jurisdiction, each attribute carrying per-field provenance and a
state-baseline compliance flag, plus citations and version history.
Read-only, not billed.

Run: python jurisdiction_rules.py
Requires: pip install httpx
"""
from __future__ import annotations

from client import direct_config_from_env, rapidapi_config_from_env, request


def main() -> None:
    # Option A: RapidAPI gateway.
    config = rapidapi_config_from_env()

    # Option B: direct API key.
    # config = direct_config_from_env()

    slug = "los_angeles"
    rules = request(
        config,
        "GET",
        f"/v1/jurisdictions/{slug}/rules",
        params={"zone": "R1", "project_type": "detached_adu"},
    )

    for zone in rules["zones"]:
        print(f"Zone {zone['zone_code']}:")
        for attr in zone["attributes"]:
            flag = attr.get("compliance_flag") or "n/a"
            print(f"  {attr['key']} = {attr['value']} ({flag})")


if __name__ == "__main__":
    main()
