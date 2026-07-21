"""End-to-end integration tests for the ADU Atlas request path.

Exercises POST /v1/feasibility (the only billable endpoint) plus the read-only
metadata endpoints against a real PostGIS database seeded with a tiny Los
Angeles fixture (see conftest.py). These assert the trust-critical contract:
the verbatim disclaimer, a terminal feasibility_status that is never a yes/no,
per-field source provenance, the state-baseline compliance surface, honest
overlay reporting (hit vs no_hit vs source_unavailable), coverage honesty
(planned jurisdictions are not billed), and the 24h no-double-bill cache.

Every test depends on the ``client`` fixture, which SKIPS the suite when the
test database is not available, so this file is safe to collect in any CI job.
"""

from __future__ import annotations

from typing import Any

from services.api.schemas import FeasibilityResponse
from services.core.constants import DISCLAIMER

VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_DATA_STATUS = {"current", "stale", "needs_review", "unavailable"}


def _assert_provenance(prov: dict[str, Any]) -> None:
    """Every provenance object must carry the non-negotiable source fields."""
    assert prov is not None
    assert prov.get("source_url")
    assert prov.get("source_title")
    assert prov.get("retrieved_at")
    assert prov.get("confidence") in VALID_CONFIDENCE
    assert prov.get("data_status") in VALID_DATA_STATUS


def _detached_adu_body(address: str) -> dict[str, Any]:
    return {
        "address": address,
        "project_type": "detached_adu",
        "target_sqft": 800,
        "bedrooms": 1,
        "proposed_height_ft": 16,
        "existing_structure": {"type": "single_family", "has_garage": True},
        "options": {"near_transit": False},
    }


def test_detached_adu_la_is_source_cited_and_feasible(client, auth_headers, addresses):
    resp = client.post(
        "/v1/feasibility",
        json=_detached_adu_body(addresses["la_billable"]),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # A first-time completed analysis is billed exactly once.
    assert resp.headers.get("X-Billable") == "true"

    # It validates against the Pydantic response model (which itself enforces
    # the verbatim disclaimer), and the disclaimer is byte-identical.
    FeasibilityResponse.model_validate(body)
    assert body["disclaimer"] == DISCLAIMER

    # Terminal status is one of the four allowed values, and for this clean,
    # verified-rule, no-hazard parcel it is likely_feasible.
    assert body["feasibility_status"] == "likely_feasible"

    # Coverage honesty: resolved to production Los Angeles.
    assert body["coverage"]["jurisdiction_slug"] == "los_angeles"
    assert body["coverage"]["coverage_status"] == "production"

    # Parcel matched, never approximated as exact, and source-cited.
    assert body["parcel"]["matched"] is True
    assert body["parcel"]["apn"]["value"] == "5123-014-007"
    _assert_provenance(body["parcel"]["apn"]["provenance"])

    # Zoning resolved to R1 with provenance, no cross-zone ambiguity.
    assert body["zoning"]["zone_code"]["value"] == "R1"
    assert body["zoning"]["cross_zone_ambiguity"] is False
    _assert_provenance(body["zoning"]["zone_code"]["provenance"])

    # Development constraint from the LOCAL ordinance (not the state baseline),
    # carrying its own provenance and matching the state baseline for height.
    max_h = body["development_constraints"]["max_height_ft"]
    assert max_h["value"] == 16
    assert "amlegal.com" in max_h["provenance"]["source_url"]
    _assert_provenance(max_h["provenance"])

    # A side setback surfaced from the state baseline (no local value ingested).
    assert body["development_constraints"]["side_setback_ft"]["value"] == 4

    # The requested path is reported without a hard yes/no.
    paths = {p["path_type"]: p for p in body["eligible_paths"]}
    assert paths["detached_adu"]["status"] == "likely_eligible"

    # Top-level sources are all well-formed provenance objects.
    assert body["sources"], "expected at least one cited source"
    for src in body["sources"]:
        _assert_provenance(src)

    # Freshness carries the analysis version and a generation timestamp.
    assert body["freshness"]["analysis_version"]
    assert body["freshness"]["generated_at"]


def test_overlay_reporting_distinguishes_no_hit_from_unavailable(
    client, auth_headers, addresses
):
    resp = client.post(
        "/v1/feasibility",
        json=_detached_adu_body(addresses["la_billable"]),
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    findings = {f["overlay_type"]: f for f in resp.json()["overlay_findings"]}

    # The historic overlay intersects the parcel: a hit, with preserved raw
    # values and provenance.
    assert findings["historic"]["status"] == "hit"
    _assert_provenance(findings["historic"]["provenance"])
    assert findings["historic"]["raw_values"]

    # The fire layer is loaded but does not cover the parcel: an explicit no_hit.
    assert findings["fire"]["status"] == "no_hit"

    # Flood was never ingested: it must be reported as source_unavailable, not
    # silently treated as "no hit".
    assert findings["flood"]["status"] == "source_unavailable"


def test_identical_request_is_cached_not_double_billed(client, auth_headers, addresses):
    body = _detached_adu_body(addresses["la_dedupe"])

    first = client.post("/v1/feasibility", json=body, headers=auth_headers)
    assert first.status_code == 200, first.text

    second = client.post("/v1/feasibility", json=body, headers=auth_headers)
    assert second.status_code == 200, second.text

    # The repeat within the dedupe window is served from cache and not billed,
    # and returns the same stored analysis.
    assert second.headers.get("X-Billable") == "false"
    assert second.json()["analysis_id"] == first.json()["analysis_id"]


def test_unsupported_coverage_is_not_billed(client, auth_headers, addresses):
    resp = client.post(
        "/v1/feasibility",
        json=_detached_adu_body(addresses["oakland"]),
        headers=auth_headers,
    )
    # Oakland is registered but only 'planned': 422, no feasibility result, and
    # explicitly not billed.
    assert resp.status_code == 422, resp.text
    assert resp.headers.get("X-Billable") != "true"
    err = resp.json()["error"]
    assert err["code"] == "unsupported_coverage"
    assert err["details"]["jurisdiction_slug"] == "oakland"
    assert err["details"]["coverage_status"] == "planned"


def test_missing_credentials_are_rejected(client, addresses):
    resp = client.post(
        "/v1/feasibility",
        json=_detached_adu_body(addresses["la"]),
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["error"]["code"] == "unauthorized"


def test_list_jurisdictions_reports_coverage(client, auth_headers):
    resp = client.get("/v1/jurisdictions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_slug = {j["slug"]: j for j in body["data"]}
    assert body["count"] == len(body["data"])
    assert by_slug["los_angeles"]["coverage_status"] == "production"
    assert by_slug["oakland"]["coverage_status"] == "planned"
    assert "detached_adu" in by_slug["los_angeles"]["supported_project_types"]


def test_jurisdiction_rules_are_cited(client, auth_headers):
    resp = client.get("/v1/jurisdictions/los_angeles/rules", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jurisdiction"]["slug"] == "los_angeles"

    zones = {z["zone_code"]: z for z in body["zones"]}
    assert "R1" in zones
    attrs = {a["key"]: a for a in zones["R1"]["attributes"]}
    height = attrs["max_height_detached_standard_ft"]
    assert height["value"] == 16
    assert height["compliance_flag"] == "compliant"
    _assert_provenance(height["provenance"])


def test_changelog_is_public_history(client, auth_headers):
    resp = client.get("/v1/changelog", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] >= 1
    kinds = {e["change_type"] for e in body["data"]}
    assert "coverage_change" in kinds


def test_health_reports_source_freshness(client):
    resp = client.get("/v1/health")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok"
    assert body["api_version"]
    keys = {s["key"] for s in body["sources"]}
    assert keys, "expected at least one source freshness entry"
