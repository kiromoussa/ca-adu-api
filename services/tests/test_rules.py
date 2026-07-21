"""Rule-engine tests: state-baseline merge and the more-restrictive flag.

Covers the non-negotiable trust rule: a local value more restrictive than the
current state baseline is flagged (never discarded), and local provenance is
preserved verbatim through the merge.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.core.constants import (
    DB_COMPLIANCE_MATCHES,
    DB_COMPLIANCE_MORE_RESTRICTIVE,
    DB_COMPLIANCE_NEEDS_REVIEW,
    DB_COMPLIANCE_NOT_APPLICABLE,
)
from services.core.repository import Baseline, RuleAttr, SourceRef, ZoningRuleSet
from services.core.rules import (
    baseline_as_finding,
    evaluate_compliance,
    merge_attribute,
    merge_ruleset,
)
from services.tests.fakes import default_baselines


def _src(title="Local LAMC 12.22"):
    return SourceRef(
        source_url="https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/x",
        source_title=title,
        source_section="LAMC 12.22 A.33",
        retrieved_at=datetime.now(timezone.utc),
        confidence="high",
        data_status="current",
    )


def _baseline(field, op, value, unit=None):
    return Baseline(
        field_name=field, operator=op, baseline_value=value, unit=unit,
        applies_to=("detached_adu",), legal_citation="AB 2221",
        source_url="https://www.hcd.ca.gov/building-standards/adu/handbook",
        source_title="HCD ADU Handbook", last_verified_at=datetime.now(timezone.utc),
    )


# --- evaluate_compliance ---------------------------------------------------
def test_floor_operator():
    assert evaluate_compliance("floor", 16, 16) == DB_COMPLIANCE_MATCHES
    assert evaluate_compliance("floor", 20, 16) == DB_COMPLIANCE_MATCHES
    # Local allows less than the state minimum -> more restrictive.
    assert evaluate_compliance("floor", 14, 16) == DB_COMPLIANCE_MORE_RESTRICTIVE


def test_ceiling_operator():
    assert evaluate_compliance("ceiling", 4, 4) == DB_COMPLIANCE_MATCHES
    assert evaluate_compliance("ceiling", 3, 4) == DB_COMPLIANCE_MATCHES
    # Local requires more setback than the state permits -> more restrictive.
    assert evaluate_compliance("ceiling", 6, 4) == DB_COMPLIANCE_MORE_RESTRICTIVE


def test_gte_and_lte():
    assert evaluate_compliance("gte", 850, 850) == DB_COMPLIANCE_MATCHES
    assert evaluate_compliance("gte", 800, 850) == DB_COMPLIANCE_MORE_RESTRICTIVE
    assert evaluate_compliance("lte", 60, 60) == DB_COMPLIANCE_MATCHES
    assert evaluate_compliance("lte", 90, 60) == DB_COMPLIANCE_MORE_RESTRICTIVE


def test_must_equal_and_eq():
    assert evaluate_compliance("must_equal", False, False) == DB_COMPLIANCE_MATCHES
    assert evaluate_compliance("must_equal", True, False) == DB_COMPLIANCE_MORE_RESTRICTIVE
    assert evaluate_compliance("eq", 750, 750) == DB_COMPLIANCE_MATCHES
    assert evaluate_compliance("eq", 700, 750) == DB_COMPLIANCE_NEEDS_REVIEW


def test_indeterminate_values_need_review():
    assert evaluate_compliance("floor", None, 16) == DB_COMPLIANCE_NEEDS_REVIEW
    assert evaluate_compliance("floor", 16, None) == DB_COMPLIANCE_NEEDS_REVIEW
    assert evaluate_compliance("eq", {"conditional": True}, 16) == DB_COMPLIANCE_NEEDS_REVIEW


# --- merge_attribute -------------------------------------------------------
def test_merge_preserves_local_provenance_and_flags_more_restrictive():
    local_src = _src()
    attr = RuleAttr(field_name="side_rear_setback_min_ft", value=6, unit="ft",
                    operator="ceiling", source=local_src)
    baseline = _baseline("side_rear_setback_min_ft", "ceiling", 4, "ft")

    merged = merge_attribute(attr, baseline)

    # Local value and its source survive unchanged.
    assert merged.value == 6
    assert merged.source is local_src
    assert merged.source.source_url == local_src.source_url
    # State baseline attached alongside, not overwriting.
    assert merged.state_baseline == 4
    assert merged.compliance_flag == DB_COMPLIANCE_MORE_RESTRICTIVE
    assert merged.origin == "local"
    assert merged.note and "more restrictive" in merged.note.lower()


def test_merge_compliant_local_value():
    attr = RuleAttr(field_name="max_height_detached_standard_ft", value=18, unit="ft",
                    operator="floor", source=_src())
    baseline = _baseline("max_height_detached_standard_ft", "floor", 16, "ft")
    merged = merge_attribute(attr, baseline)
    assert merged.compliance_flag == DB_COMPLIANCE_MATCHES
    assert merged.note is None


def test_merge_no_baseline_is_not_applicable():
    attr = RuleAttr(field_name="some_local_only_field", value=3, source=_src())
    merged = merge_attribute(attr, None)
    assert merged.compliance_flag == DB_COMPLIANCE_NOT_APPLICABLE
    assert merged.origin == "local"


# --- baseline_as_finding + merge_ruleset -----------------------------------
def test_baseline_as_finding_carries_state_provenance():
    b = _baseline("parking_required", "must_equal", False)
    f = baseline_as_finding(b)
    assert f.origin == "state_baseline"
    assert f.value is False
    assert f.source.source_url == b.source_url
    assert f.compliance_flag == DB_COMPLIANCE_NOT_APPLICABLE


def test_merge_ruleset_without_local_rules_falls_back_to_baselines():
    baselines = default_baselines()
    findings = merge_ruleset(None, baselines, "detached_adu")
    # One finding per applicable baseline, all state-origin.
    assert len(findings) == len(baselines)
    assert all(f.origin == "state_baseline" for f in findings)


def test_merge_ruleset_validates_local_and_appends_remaining_baselines():
    baselines = default_baselines()
    ruleset = ZoningRuleSet(
        zone_code="R1", project_type="detached_adu", review_status="verified",
        attributes=[
            RuleAttr(field_name="side_rear_setback_min_ft", value=5, unit="ft",
                     operator="ceiling", source=_src()),
        ],
    )
    findings = merge_ruleset(ruleset, baselines, "detached_adu")
    by_field = {f.field_name: f for f in findings}
    # The local attribute is validated (5 > 4 ceiling -> more restrictive).
    assert by_field["side_rear_setback_min_ft"].origin == "local"
    assert by_field["side_rear_setback_min_ft"].compliance_flag == DB_COMPLIANCE_MORE_RESTRICTIVE
    # Every other baseline still surfaces exactly once.
    assert len(findings) == len(baselines)
    assert by_field["parking_required"].origin == "state_baseline"
