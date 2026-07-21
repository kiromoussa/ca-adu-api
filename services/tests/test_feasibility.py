"""Feasibility tests: status selection, fingerprinting, and full orchestration.

The orchestrator is exercised end to end with fakes (no DB, no network). Results
are validated against the Pydantic FeasibilityResponse (which enforces the
verbatim disclaimer), proving the core emits an OpenAPI-conformant object.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.api.schemas import FeasibilityResponse
from services.core.constants import DISCLAIMER
from services.core.feasibility import (
    FeasibilityInput,
    _StatusInputs,
    compute_request_fingerprint,
    run_feasibility,
    select_feasibility_status,
)
from services.core.geocode import StaticGeocoder
from services.core.repository import (
    GeoPoint,
    OverlayResult,
    RuleAttr,
    SourceRef,
    ZoningRuleSet,
)
from services.tests import fakes


LA_POINT = GeoPoint(lon=-118.27, lat=34.03)


def _geocoder():
    return StaticGeocoder({"1234 S MAIN ST, LOS ANGELES, CA 90015": LA_POINT})


def _input(**kw):
    base = dict(address="1234 S Main St, Los Angeles, CA 90015", project_type="detached_adu")
    base.update(kw)
    return FeasibilityInput(**base)


# --- select_feasibility_status --------------------------------------------
def _status(**kw):
    base = dict(
        resolved_jurisdiction=True, parcel_matched=True, zoning_resolved=True,
        low_confidence=False, cross_zone_ambiguity=False, compliance_flags=[],
        hazard_overlay_hit=False, requested_path_status="likely_eligible",
        orientation_unknown=False,
    )
    base.update(kw)
    return select_feasibility_status(_StatusInputs(**base))


def test_status_insufficient_data():
    assert _status(parcel_matched=False) == "insufficient_data"
    assert _status(zoning_resolved=False) == "insufficient_data"
    assert _status(low_confidence=True) == "insufficient_data"


def test_status_needs_professional_review():
    assert _status(cross_zone_ambiguity=True) == "needs_professional_review"
    assert _status(compliance_flags=["possibly_more_restrictive_than_state_baseline"]) == "needs_professional_review"
    assert _status(compliance_flags=["needs_review"]) == "needs_professional_review"
    assert _status(orientation_unknown=True) == "needs_professional_review"
    assert _status(requested_path_status="needs_professional_review") == "needs_professional_review"


def test_status_likely_constrained():
    assert _status(hazard_overlay_hit=True) == "likely_constrained"
    assert _status(requested_path_status="conditional") == "likely_constrained"
    assert _status(requested_path_status="likely_ineligible") == "likely_constrained"


def test_status_likely_feasible():
    assert _status() == "likely_feasible"


# --- fingerprint -----------------------------------------------------------
def test_fingerprint_is_deterministic_and_input_sensitive():
    inp = _input()
    f1 = compute_request_fingerprint("c_1", "1234 S MAIN ST", inp)
    f2 = compute_request_fingerprint("c_1", "1234 S MAIN ST", inp)
    assert f1 == f2
    f3 = compute_request_fingerprint("c_1", "1234 S MAIN ST", _input(bedrooms=3))
    assert f1 != f3
    f4 = compute_request_fingerprint("c_2", "1234 S MAIN ST", inp)
    assert f1 != f4


# --- orchestration ---------------------------------------------------------
def test_unsupported_coverage_not_billed_or_persisted():
    repo = fakes.FakeRepository(jurisdiction=fakes.la_jurisdiction("planned"))
    outcome = run_feasibility(repo, _geocoder(), _input(), consumer_id="c_1")
    assert outcome.kind == "unsupported_coverage"
    assert outcome.billable is False
    assert outcome.result is None
    assert repo.inserted_analyses == []
    assert outcome.unsupported_detail["coverage_status"] == "planned"


def test_insufficient_data_when_geocode_fails():
    repo = fakes.FakeRepository(jurisdiction=fakes.la_jurisdiction("production"))
    geocoder = StaticGeocoder({})  # nothing resolves
    outcome = run_feasibility(repo, geocoder, _input(), consumer_id="c_1")
    assert outcome.feasibility_status == "insufficient_data"
    assert outcome.billable is False
    FeasibilityResponse.model_validate(outcome.result)


def test_no_local_rules_yields_constrained_with_state_baselines():
    repo = fakes.FakeRepository(
        jurisdiction=fakes.la_jurisdiction("production"),
        parcel=fakes.matched_parcel(),
        zoning=fakes.r1_zoning(),
        overlays=[OverlayResult("flood", "no_hit"), OverlayResult("fire", "no_hit")],
        ruleset=None,
    )
    outcome = run_feasibility(repo, _geocoder(), _input(bedrooms=1), consumer_id="c_1")
    # State law permits statewide; local ordinance detail pending -> conditional path.
    assert outcome.feasibility_status == "likely_constrained"
    assert outcome.billable is True
    model = FeasibilityResponse.model_validate(outcome.result)
    assert model.disclaimer == DISCLAIMER
    assert model.coverage.jurisdiction_slug == "los_angeles"
    assert model.parcel.matched is True
    # Development constraints populated from state baselines.
    assert model.development_constraints.max_height_ft.value == 16
    # Persisted exactly one analysis, marked billable.
    assert len(repo.inserted_analyses) == 1
    assert repo.inserted_analyses[0]["billable"] is True


def test_verified_local_rules_compliant_is_likely_feasible():
    src = SourceRef(
        source_url="https://codelibrary.amlegal.com/lamc",
        source_title="LAMC 12.22 A.33", source_section="LAMC 12.22 A.33",
        retrieved_at=datetime.now(timezone.utc), last_verified_at=datetime.now(timezone.utc),
        confidence="high", data_status="current",
    )
    ruleset = ZoningRuleSet(
        zone_code="R1", project_type="detached_adu", review_status="verified",
        attributes=[
            RuleAttr("max_height_detached_standard_ft", 16, "ft", "floor", src),
            RuleAttr("side_rear_setback_min_ft", 4, "ft", "ceiling", src),
            RuleAttr("parking_required", False, None, "must_equal", src),
        ],
    )
    repo = fakes.FakeRepository(
        jurisdiction=fakes.la_jurisdiction("production"),
        parcel=fakes.matched_parcel(),
        zoning=fakes.r1_zoning(),
        overlays=[OverlayResult("flood", "no_hit"), OverlayResult("fire", "no_hit")],
        ruleset=ruleset,
    )
    outcome = run_feasibility(repo, _geocoder(), _input(), consumer_id="c_1")
    assert outcome.feasibility_status == "likely_feasible"
    assert outcome.billable is True
    FeasibilityResponse.model_validate(outcome.result)


def test_more_restrictive_local_rule_forces_professional_review():
    src = SourceRef(
        source_url="https://codelibrary.amlegal.com/lamc",
        source_title="LAMC 12.22 A.33", source_section="LAMC 12.22 A.33",
        retrieved_at=datetime.now(timezone.utc), confidence="high", data_status="current",
    )
    ruleset = ZoningRuleSet(
        zone_code="R1", project_type="detached_adu", review_status="verified",
        attributes=[
            # 6 ft required setback exceeds the 4 ft state ceiling -> more restrictive.
            RuleAttr("side_rear_setback_min_ft", 6, "ft", "ceiling", src),
        ],
    )
    repo = fakes.FakeRepository(
        jurisdiction=fakes.la_jurisdiction("production"),
        parcel=fakes.matched_parcel(),
        zoning=fakes.r1_zoning(),
        overlays=[OverlayResult("flood", "no_hit"), OverlayResult("fire", "no_hit")],
        ruleset=ruleset,
    )
    outcome = run_feasibility(repo, _geocoder(), _input(), consumer_id="c_1")
    assert outcome.feasibility_status == "needs_professional_review"
    model = FeasibilityResponse.model_validate(outcome.result)
    setback = model.development_constraints.side_setback_ft
    assert setback.value == 6
    assert setback.state_baseline == 4
    assert setback.compliance_flag == "possibly_more_restrictive_than_state_baseline"


def test_cross_zone_ambiguity_forces_review():
    from services.core.repository import ZoneMatch, ZoningResult

    src = SourceRef(source_url="https://zimas", source_title="ZIMAS zoning",
                    retrieved_at=datetime.now(timezone.utc), confidence="high",
                    data_status="current")
    zoning = ZoningResult(zones=[
        ZoneMatch("R1", "One-Family", "res", None, src),
        ZoneMatch("R2", "Two-Family", "res", None, src),
    ])
    repo = fakes.FakeRepository(
        jurisdiction=fakes.la_jurisdiction("production"),
        parcel=fakes.matched_parcel(),
        zoning=zoning,
        overlays=[OverlayResult("flood", "no_hit"), OverlayResult("fire", "no_hit")],
    )
    outcome = run_feasibility(repo, _geocoder(), _input(), consumer_id="c_1")
    assert outcome.feasibility_status == "needs_professional_review"
    model = FeasibilityResponse.model_validate(outcome.result)
    assert model.zoning.cross_zone_ambiguity is True
