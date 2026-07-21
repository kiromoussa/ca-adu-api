"""Unit tests for the state-law validation pass (scraper/pipeline).

These import the real baselines and validator from scraper/pipeline (baselines.py
is the single source of truth for every threshold, so the tests never restate a
number - they derive the compliant value from each Baseline and then perturb one
field at a time). They require no third-party dependencies, no network, and no
Supabase.

Ground truth: the compliance_flag enum is ('compliant','more_restrictive',
'needs_review') per supabase/migrations/0001_initial_schema.sql.
"""

from __future__ import annotations

import pytest

# Resolved via conftest.py, which puts scraper/pipeline on sys.path.
import baselines  # noqa: E402
import validate  # noqa: E402
from baselines import (  # noqa: E402
    BASELINES,
    KIND_CEILING,
    KIND_CONDITIONAL,
    KIND_FLOOR,
    KIND_INFORMATIONAL,
    KIND_MUST_EQUAL,
    RULE_FIELDS,
)
from validate import (  # noqa: E402
    COMPLIANT,
    MORE_RESTRICTIVE,
    NEEDS_REVIEW,
    evaluate_field,
    validate_rule,
)


def _compliant_value(field: str):
    """The value that should pass validation for one field, from its Baseline."""
    b = BASELINES[field]
    if b.kind in (KIND_FLOOR, KIND_CEILING):
        return b.value  # exactly on the floor/ceiling is compliant
    if b.kind in (KIND_MUST_EQUAL, KIND_CONDITIONAL):
        return b.value  # the required / compliant-default boolean
    if b.kind == KIND_INFORMATIONAL:
        return None  # never flagged either way
    raise AssertionError(f"unknown kind {b.kind!r}")


def compliant_row() -> dict:
    """A fully state-law-compliant extracted rule, derived from the baselines."""
    return {field: _compliant_value(field) for field in RULE_FIELDS}


# ---------------------------------------------------------------------------
# baseline / enum ground truth
# ---------------------------------------------------------------------------
def test_compliance_flag_enum_values():
    # Must match the Postgres enum in migration 0001.
    assert COMPLIANT == "compliant"
    assert MORE_RESTRICTIVE == "more_restrictive"
    assert NEEDS_REVIEW == "needs_review"


def test_known_baselines_match_spec():
    setback = BASELINES["side_rear_setback_min_ft"]
    assert setback.kind == KIND_CEILING
    assert setback.value == 4

    owner = BASELINES["owner_occupancy_required_adu"]
    assert owner.kind == KIND_MUST_EQUAL
    assert owner.value is False
    assert owner.restrictive_value is True

    height = BASELINES["max_height_detached_standard_ft"]
    assert height.kind == KIND_FLOOR
    assert height.value == 16


# ---------------------------------------------------------------------------
# row-level flag
# ---------------------------------------------------------------------------
def test_fully_compliant_row_is_compliant():
    flag, notes = validate_rule(compliant_row())
    assert flag == COMPLIANT
    # every per-field note is present and compliant
    assert set(notes) == set(RULE_FIELDS)
    assert all(n["status"] == COMPLIANT for n in notes.values())


def test_owner_occupancy_required_adu_is_more_restrictive():
    """The task's explicit known-non-compliant field."""
    row = compliant_row()
    row["owner_occupancy_required_adu"] = True  # prohibited statewide
    flag, notes = validate_rule(row)
    assert flag == MORE_RESTRICTIVE
    assert notes["owner_occupancy_required_adu"]["status"] == MORE_RESTRICTIVE
    assert notes["owner_occupancy_required_adu"]["law"]


def test_side_rear_setback_over_ceiling_is_more_restrictive():
    """The task's explicit known-non-compliant field: setback of 5 ft > 4 ft."""
    row = compliant_row()
    row["side_rear_setback_min_ft"] = 5
    flag, notes = validate_rule(row)
    assert flag == MORE_RESTRICTIVE
    assert notes["side_rear_setback_min_ft"]["status"] == MORE_RESTRICTIVE


def test_height_below_floor_is_more_restrictive():
    row = compliant_row()
    row["max_height_detached_standard_ft"] = 12  # below the 16 ft floor
    flag, _ = validate_rule(row)
    assert flag == MORE_RESTRICTIVE


def test_missing_numeric_value_needs_review():
    row = compliant_row()
    row["permit_review_days"] = None  # not stated -> cannot verify
    flag, notes = validate_rule(row)
    assert flag == NEEDS_REVIEW
    assert notes["permit_review_days"]["status"] == NEEDS_REVIEW


def test_over_permissive_boolean_needs_review():
    # jadu_separate_sale_allowed=True is unlawful over-permission (restrictive_value
    # is None) -> needs_review, never more_restrictive.
    row = compliant_row()
    row["jadu_separate_sale_allowed"] = True
    flag, notes = validate_rule(row)
    assert flag == NEEDS_REVIEW
    assert notes["jadu_separate_sale_allowed"]["status"] == NEEDS_REVIEW


def test_conditional_true_needs_review():
    # parking_required=True is lawful only if no exemption applies -> needs_review.
    row = compliant_row()
    row["parking_required"] = True
    flag, notes = validate_rule(row)
    assert flag == NEEDS_REVIEW
    assert notes["parking_required"]["status"] == NEEDS_REVIEW


def test_more_restrictive_wins_over_needs_review():
    # Precedence: a more_restrictive field outranks a needs_review field.
    row = compliant_row()
    row["side_rear_setback_min_ft"] = 5      # more_restrictive
    row["permit_review_days"] = None         # needs_review
    flag, _ = validate_rule(row)
    assert flag == MORE_RESTRICTIVE


# ---------------------------------------------------------------------------
# per-field evaluator
# ---------------------------------------------------------------------------
def test_evaluate_field_ceiling_boundary():
    # exactly on the ceiling is compliant; one over is more_restrictive.
    assert evaluate_field("side_rear_setback_min_ft", 4)["status"] == COMPLIANT
    assert evaluate_field("side_rear_setback_min_ft", 4.5)["status"] == MORE_RESTRICTIVE


def test_evaluate_field_floor_boundary():
    assert evaluate_field("max_height_detached_standard_ft", 16)["status"] == COMPLIANT
    assert (
        evaluate_field("max_height_detached_standard_ft", 15.9)["status"]
        == MORE_RESTRICTIVE
    )


def test_evaluate_field_coerces_string_numbers_with_units():
    # "5 ft" must be read as 5 and still exceed the 4 ft ceiling.
    assert evaluate_field("side_rear_setback_min_ft", "5 ft")["status"] == MORE_RESTRICTIVE


def test_informational_field_never_flagged():
    b = BASELINES["adu_condo_sale_allowed"]
    assert b.kind == KIND_INFORMATIONAL
    assert evaluate_field("adu_condo_sale_allowed", True)["status"] == COMPLIANT
    assert evaluate_field("adu_condo_sale_allowed", False)["status"] == COMPLIANT
    assert evaluate_field("adu_condo_sale_allowed", None)["status"] == COMPLIANT


def test_validate_rule_treats_missing_key_as_none():
    # Omitting a key entirely is the same as an explicit None (needs_review).
    with pytest.raises(KeyError):
        BASELINES["not_a_field"]  # sanity: unknown fields are not in the map
    partial = compliant_row()
    del partial["permit_review_days"]
    flag, notes = validate_rule(partial)
    assert flag == NEEDS_REVIEW
    assert notes["permit_review_days"]["status"] == NEEDS_REVIEW
