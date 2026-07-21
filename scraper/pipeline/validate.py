"""State-law validation of extracted adu_rules against baselines.py.

For each extracted zone-district row, compare every field to its state-law
baseline and produce:

  - a per-field detail record (status, expected threshold, actual value, law,
    note) collected into compliance_notes (jsonb), and
  - a single row-level compliance_flag drawn from the schema enum
    ('compliant' | 'more_restrictive' | 'needs_review').

Row-level flag precedence: any more_restrictive field -> 'more_restrictive';
else any needs_review field -> 'needs_review'; else 'compliant'.

baselines.py is the only source of thresholds - this module contains no
hard-coded numbers.
"""

from __future__ import annotations

from baselines import (
    BASELINES,
    KIND_CEILING,
    KIND_CONDITIONAL,
    KIND_FLOOR,
    KIND_INFORMATIONAL,
    KIND_MUST_EQUAL,
    RULE_FIELDS,
    Baseline,
)

# compliance_flag enum values (must match the Postgres enum in 0001).
COMPLIANT = "compliant"
MORE_RESTRICTIVE = "more_restrictive"
NEEDS_REVIEW = "needs_review"

# Row flag precedence, most severe first.
_FLAG_PRECEDENCE = [MORE_RESTRICTIVE, NEEDS_REVIEW, COMPLIANT]


def _coerce_number(value: object) -> float | None:
    """Best-effort numeric coercion; returns None if not interpretable."""
    if value is None:
        return None
    if isinstance(value, bool):  # guard: bool is a subclass of int
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        # keep leading number if a unit slipped through (e.g. "16 ft")
        token = ""
        for ch in cleaned:
            if ch.isdigit() or ch in ".-":
                token += ch
            elif token:
                break
        try:
            return float(token) if token not in ("", "-", ".", "-.") else None
        except ValueError:
            return None
    return None


def _coerce_bool(value: object) -> bool | None:
    """Best-effort boolean coercion; returns None if not interpretable."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "y", "required", "1"):
            return True
        if low in ("false", "no", "n", "not required", "0"):
            return False
    return None


def _detail(baseline: Baseline, status: str, actual: object, note: str) -> dict:
    """Assemble a per-field compliance-notes record."""
    return {
        "field": baseline.field,
        "status": status,
        "kind": baseline.kind,
        "expected": baseline.value,
        "actual": actual,
        "law": baseline.law,
        "note": note,
    }


def _evaluate_floor(baseline: Baseline, actual: object) -> dict:
    num = _coerce_number(actual)
    if actual is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value missing; cannot verify")
    if num is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value not numeric; cannot verify")
    if num >= baseline.value:
        return _detail(
            baseline, COMPLIANT, num,
            f"{num} meets or exceeds state floor of {baseline.value}",
        )
    return _detail(
        baseline, MORE_RESTRICTIVE, num,
        f"{num} is below the state floor of {baseline.value} "
        f"({baseline.law}); local rule is more restrictive",
    )


def _evaluate_ceiling(baseline: Baseline, actual: object) -> dict:
    num = _coerce_number(actual)
    if actual is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value missing; cannot verify")
    if num is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value not numeric; cannot verify")
    if num <= baseline.value:
        return _detail(
            baseline, COMPLIANT, num,
            f"{num} is within the state ceiling of {baseline.value}",
        )
    return _detail(
        baseline, MORE_RESTRICTIVE, num,
        f"{num} exceeds the state ceiling of {baseline.value} "
        f"({baseline.law}); local rule is more restrictive",
    )


def _evaluate_must_equal(baseline: Baseline, actual: object) -> dict:
    val = _coerce_bool(actual)
    if actual is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value missing; cannot verify")
    if val is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value not boolean; cannot verify")
    if val == baseline.value:
        return _detail(
            baseline, COMPLIANT, val,
            f"matches required value {baseline.value}",
        )
    if baseline.restrictive_value is not None and val == baseline.restrictive_value:
        return _detail(
            baseline, MORE_RESTRICTIVE, val,
            f"expected {baseline.value} per {baseline.law}; local value {val} is "
            f"more restrictive than state law allows",
        )
    # Non-expected value that is over-permissive / potentially unlawful.
    return _detail(
        baseline, NEEDS_REVIEW, val,
        f"expected {baseline.value} per {baseline.law}; local value {val} is more "
        f"permissive than state law contemplates and needs review",
    )


def _evaluate_conditional(baseline: Baseline, actual: object) -> dict:
    val = _coerce_bool(actual)
    if actual is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value missing; cannot verify")
    if val is None:
        return _detail(baseline, NEEDS_REVIEW, actual, "value not boolean; cannot verify")
    if val == baseline.value:
        return _detail(
            baseline, COMPLIANT, val,
            f"value {val} is the compliant default; lawful without further facts",
        )
    return _detail(
        baseline, NEEDS_REVIEW, val,
        f"value {val} is lawful only under specific conditions ({baseline.law}); "
        f"needs review to confirm those conditions apply",
    )


def _evaluate_informational(baseline: Baseline, actual: object) -> dict:
    return _detail(
        baseline, COMPLIANT, actual,
        f"informational / optional local opt-in ({baseline.law}); not flagged",
    )


_EVALUATORS = {
    KIND_FLOOR: _evaluate_floor,
    KIND_CEILING: _evaluate_ceiling,
    KIND_MUST_EQUAL: _evaluate_must_equal,
    KIND_CONDITIONAL: _evaluate_conditional,
    KIND_INFORMATIONAL: _evaluate_informational,
}


def evaluate_field(field: str, actual: object) -> dict:
    """Evaluate one field's extracted value against its baseline."""
    baseline = BASELINES[field]
    return _EVALUATORS[baseline.kind](baseline, actual)


def _roll_up(statuses: list[str]) -> str:
    for flag in _FLAG_PRECEDENCE:
        if flag in statuses:
            return flag
    return COMPLIANT


def validate_rule(rule: dict) -> tuple[str, dict]:
    """Validate one extracted rule row.

    Args:
        rule: dict of extracted values keyed by adu_rules field name (missing
              keys are treated as None / not stated).

    Returns:
        (compliance_flag, compliance_notes) where compliance_notes is a jsonb-
        ready dict of {field: detail-record}.
    """
    notes: dict[str, dict] = {}
    statuses: list[str] = []
    for field in RULE_FIELDS:
        detail = evaluate_field(field, rule.get(field))
        notes[field] = detail
        statuses.append(detail["status"])
    return _roll_up(statuses), notes


if __name__ == "__main__":  # simple self-check
    # Fully-compliant row.
    ok = {
        "max_height_detached_standard_ft": 16,
        "max_height_near_transit_ft": 18,
        "max_height_multifamily_lot_ft": 18,
        "max_height_attached_ft": 25,
        "side_rear_setback_min_ft": 4,
        "front_setback_restriction": False,
        "owner_occupancy_required_adu": False,
        "owner_occupancy_required_jadu": False,
        "jadu_allowed": True,
        "jadu_separate_sale_allowed": False,
        "adu_condo_sale_allowed": False,
        "parking_required": False,
        "demolition_permit_concurrent": True,
        "permit_review_days": 60,
        "fire_sprinkler_trigger": False,
        "impact_fee_exempt_sqft_threshold": 750,
        "max_size_sqft_1br": 850,
        "max_size_sqft_2br": 1000,
        "max_size_sqft_general_cap": 1200,
        "nonconforming_zoning_denial_allowed": False,
        "pre_2018_unpermitted_adu_amnesty": True,
        "sb9_duplex_ministerial": True,
        "sb9_lot_split_min_lot_sqft": 1200,
        "sb9_lot_split_ratio": 0.4,
        "sb9_one_split_per_owner": True,
    }
    flag, _ = validate_rule(ok)
    assert flag == COMPLIANT, flag

    # Stricter-than-state values -> more_restrictive.
    strict = dict(ok, side_rear_setback_min_ft=5, owner_occupancy_required_adu=True,
                  max_height_detached_standard_ft=12, permit_review_days=90)
    flag, notes = validate_rule(strict)
    assert flag == MORE_RESTRICTIVE, flag
    assert notes["side_rear_setback_min_ft"]["status"] == MORE_RESTRICTIVE
    assert notes["owner_occupancy_required_adu"]["status"] == MORE_RESTRICTIVE

    # Missing value -> needs_review.
    partial = dict(ok, permit_review_days=None)
    flag, notes = validate_rule(partial)
    assert flag == NEEDS_REVIEW, flag
    assert notes["permit_review_days"]["status"] == NEEDS_REVIEW

    print("validate OK")
