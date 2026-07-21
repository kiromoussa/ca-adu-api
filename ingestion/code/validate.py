"""State-law validation of extracted rule_attributes against state_rule_baselines.

For every candidate rule_attribute, compare the extracted value to the matching
row in the state_rule_baselines table (California floors/ceilings + citations)
and:

  - set the attribute's compliance_flag + link state_baseline_id,
  - queue a qa_issue for any local value more restrictive than state law, any
    over-permissive/unlawful anomaly, any conditional value needing facts, and
    any field with no baseline to check against, and
  - roll the per-field flags up to the zoning_rule's compliance_flag.

The comparison DIRECTION comes from the field catalog (baselines.py kind); the
authoritative THRESHOLD + citation + source_url come from the DB baseline row.
Local rules more restrictive than the baseline are flagged, never discarded, and
the local source is preserved (trust non-negotiable #5). Nothing here marks a
rule verified.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import baselines
from baselines import (
    DTYPE_NUMERIC,
    FIELDS,
    KIND_CEILING,
    KIND_CONDITIONAL,
    KIND_FLOOR,
    KIND_INFORMATIONAL,
    KIND_MUST_EQUAL,
    Field,
)
from db import (
    FLAG_MATCHES,
    FLAG_MORE_RESTRICTIVE,
    FLAG_NEEDS_REVIEW,
    FLAG_NOT_APPLICABLE,
    REVIEW_STATUS_CANDIDATE,
)

logger = logging.getLogger(__name__)

# Roll-up precedence for the rule-level compliance_flag (most severe first).
_FLAG_PRECEDENCE = [
    FLAG_MORE_RESTRICTIVE,
    FLAG_NEEDS_REVIEW,
    FLAG_MATCHES,
    FLAG_NOT_APPLICABLE,
]


def _coerce_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
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
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value) if value in (0, 1) else None
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "y", "required", "1"):
            return True
        if low in ("false", "no", "n", "not required", "0"):
            return False
    return None


@dataclass
class Verdict:
    """Result of comparing one extracted attribute to its state baseline."""

    flag: str                       # FLAG_* value for rule_attributes.compliance_flag
    issue_type: str | None          # None when no qa_issue is warranted
    severity: str                   # info | warning | critical
    expected: object                # baseline value (for the qa_issue)
    observed: object                # extracted value
    note: str                       # human-readable explanation


def compare_attribute(
    field: Field, baseline_row: dict[str, Any] | None, observed: object
) -> Verdict:
    """Compare one extracted value to its state baseline using field semantics."""
    if field.kind == KIND_INFORMATIONAL:
        return Verdict(
            FLAG_NOT_APPLICABLE, None, "info", None, observed,
            f"informational / optional local opt-in ({field.law}); not flagged",
        )

    if baseline_row is None:
        return Verdict(
            FLAG_NEEDS_REVIEW, "no_state_baseline", "info", None, observed,
            f"no state_rule_baselines row for '{field.name}'; cannot validate "
            f"automatically - needs human review",
        )

    citation = baseline_row.get("legal_citation") or field.law
    raw_baseline = baseline_row.get("baseline_value_json")

    if field.kind in (KIND_FLOOR, KIND_CEILING):
        expected = _coerce_number(raw_baseline)
        num = _coerce_number(observed)
        if observed is None:
            return Verdict(FLAG_NEEDS_REVIEW, "value_missing", "info", expected, observed,
                           "value not extracted; cannot verify against state baseline")
        if num is None or expected is None:
            return Verdict(FLAG_NEEDS_REVIEW, "value_not_numeric", "info", expected, observed,
                           "value or baseline not numeric; cannot verify")
        if field.kind == KIND_FLOOR:
            if num >= expected:
                return Verdict(FLAG_MATCHES, None, "info", expected, num,
                               f"{num} meets or exceeds state floor of {expected}")
            return Verdict(FLAG_MORE_RESTRICTIVE, "more_restrictive_than_state_baseline",
                           "warning", expected, num,
                           f"{num} is below the state floor of {expected} ({citation}); "
                           f"local rule is more restrictive than the state baseline")
        # ceiling
        if num <= expected:
            return Verdict(FLAG_MATCHES, None, "info", expected, num,
                           f"{num} is within the state ceiling of {expected}")
        return Verdict(FLAG_MORE_RESTRICTIVE, "more_restrictive_than_state_baseline",
                       "warning", expected, num,
                       f"{num} exceeds the state ceiling of {expected} ({citation}); "
                       f"local rule is more restrictive than the state baseline")

    if field.kind == KIND_MUST_EQUAL:
        expected = _coerce_bool(raw_baseline)
        val = _coerce_bool(observed)
        if observed is None:
            return Verdict(FLAG_NEEDS_REVIEW, "value_missing", "info", expected, observed,
                           "value not extracted; cannot verify against state baseline")
        if val is None or expected is None:
            return Verdict(FLAG_NEEDS_REVIEW, "value_not_boolean", "info", expected, observed,
                           "value or baseline not boolean; cannot verify")
        if val == expected:
            return Verdict(FLAG_MATCHES, None, "info", expected, val,
                           f"matches the required state value {expected}")
        restrictive = field.restrictive_value
        if restrictive is not None and val == restrictive:
            return Verdict(FLAG_MORE_RESTRICTIVE, "more_restrictive_than_state_baseline",
                           "warning", expected, val,
                           f"state requires {expected} ({citation}); local value {val} is "
                           f"more restrictive than state law allows")
        # over-permissive / potentially unlawful anomaly
        return Verdict(FLAG_NEEDS_REVIEW, "over_permissive_anomaly", "critical", expected, val,
                       f"state contemplates {expected} ({citation}); local value {val} is "
                       f"more permissive than state law and needs review")

    if field.kind == KIND_CONDITIONAL:
        expected = _coerce_bool(raw_baseline)
        val = _coerce_bool(observed)
        if observed is None:
            return Verdict(FLAG_NEEDS_REVIEW, "value_missing", "info", expected, observed,
                           "value not extracted; cannot verify against state baseline")
        if val is None:
            return Verdict(FLAG_NEEDS_REVIEW, "value_not_boolean", "info", expected, observed,
                           "value not boolean; cannot verify")
        if val == expected:
            return Verdict(FLAG_MATCHES, None, "info", expected, val,
                           f"value {val} is the compliant default; lawful without further facts")
        return Verdict(FLAG_NEEDS_REVIEW, "conditional_needs_facts", "warning", expected, val,
                       f"value {val} is lawful only under specific conditions ({citation}); "
                       f"needs review to confirm those conditions apply")

    return Verdict(FLAG_NEEDS_REVIEW, "unknown_kind", "info", None, observed,
                   f"unhandled comparison kind for {field.name}")


def _roll_up(flags: list[str]) -> str:
    for flag in _FLAG_PRECEDENCE:
        if flag in flags:
            return flag
    return FLAG_NOT_APPLICABLE


def validate_jurisdiction(
    slug: str, settings: Any, store: Any, *, dry_run: bool = False
) -> dict[str, int]:
    """Validate all candidate rules for a jurisdiction. Returns counts."""
    jurisdiction = store.get_jurisdiction(slug)
    if jurisdiction is None:
        raise ValueError(f"jurisdiction '{slug}' not found in the database")

    baseline_rows = store.get_state_baselines()
    baselines_by_field: dict[str, dict[str, Any]] = {}
    for row in baseline_rows:
        # applies_to empty = all project types; keep the first row per field
        # name (effective_to is null already, i.e. currently effective).
        baselines_by_field.setdefault(row["field_name"], row)

    run_id = None
    if not dry_run:
        run_id = store.start_ingest_run(
            jurisdiction_id=jurisdiction["id"],
            source_registry_id=None,
            run_type="qa",
            triggered_by="validate",
        )

    counts = {"rules": 0, "attributes": 0, "issues": 0, "more_restrictive": 0}
    try:
        for rule in store.get_candidate_rules(jurisdiction["id"]):
            counts["rules"] += 1
            attrs = store.get_rule_attributes(rule["id"])
            rule_flags: list[str] = []
            for attr in attrs:
                counts["attributes"] += 1
                field_name = attr.get("field_name")
                field = FIELDS.get(field_name)
                if field is None:
                    continue
                baseline_row = baselines_by_field.get(field_name)
                verdict = compare_attribute(field, baseline_row, attr.get("value_json"))
                rule_flags.append(verdict.flag)

                if not dry_run:
                    updates: dict[str, Any] = {"compliance_flag": verdict.flag}
                    if baseline_row is not None:
                        updates["state_baseline_id"] = baseline_row.get("id")
                    store.update_rule_attribute(attr["id"], updates)

                if verdict.issue_type and verdict.flag != FLAG_MATCHES:
                    if verdict.flag == FLAG_MORE_RESTRICTIVE:
                        counts["more_restrictive"] += 1
                    if not dry_run:
                        _queue_issue(
                            store, jurisdiction, rule, attr, field, baseline_row, verdict
                        )
                    counts["issues"] += 1

            rule_flag = _roll_up(rule_flags)
            if not dry_run:
                store.update_zoning_rule(rule["id"], {"compliance_flag": rule_flag})

        if run_id is not None:
            store.finish_ingest_run(
                run_id, status="success", processed=counts["rules"], stats=counts
            )
    except Exception as exc:
        if run_id is not None:
            store.finish_ingest_run(
                run_id, status="failed", processed=counts["rules"], error_message=str(exc)
            )
        raise

    logger.info(
        "[%s] validate done: %d rules, %d attributes, %d qa_issues "
        "(%d more_restrictive)",
        slug, counts["rules"], counts["attributes"], counts["issues"],
        counts["more_restrictive"],
    )
    return counts


def _queue_issue(
    store: Any,
    jurisdiction: dict[str, Any],
    rule: dict[str, Any],
    attr: dict[str, Any],
    field: Field,
    baseline_row: dict[str, Any] | None,
    verdict: Verdict,
) -> None:
    existing = store.find_open_qa_issue(
        zoning_rule_id=rule["id"], field_name=field.name, issue_type=verdict.issue_type
    )
    if existing:
        return
    evidence = attr.get("notes")
    citation = (baseline_row or {}).get("legal_citation") or field.law
    source_url = (baseline_row or {}).get("source_url")
    description_parts = [verdict.note]
    if evidence:
        description_parts.append(f"Local evidence: {evidence}")
    description_parts.append(f"State law: {citation}")
    if source_url:
        description_parts.append(f"Baseline source: {source_url}")
    if attr.get("source_url"):
        description_parts.append(f"Local source: {attr['source_url']}")

    store.create_qa_issue(
        {
            "jurisdiction_id": jurisdiction["id"],
            "zoning_rule_id": rule["id"],
            "rule_attribute_id": attr["id"],
            "issue_type": verdict.issue_type,
            "severity": verdict.severity,
            "status": "open",
            "detected_by": "state_baseline_check",
            "field_name": field.name,
            "expected_value": json.dumps(verdict.expected),
            "observed_value": json.dumps(verdict.observed),
            "description": " | ".join(description_parts),
        }
    )


if __name__ == "__main__":  # offline self-check (pure comparison logic)
    def bl(field_name, value):
        f = FIELDS[field_name]
        return {
            "id": f"bl-{field_name}",
            "field_name": field_name,
            "operator": f.operator,
            "baseline_value_json": value,
            "legal_citation": f.law,
            "source_url": "https://leginfo.legislature.ca.gov/",
        }

    # floor: below state floor -> more_restrictive
    f = FIELDS["max_height_detached_standard_ft"]
    v = compare_attribute(f, bl(f.name, 16), 12)
    assert v.flag == FLAG_MORE_RESTRICTIVE and v.severity == "warning", v
    v = compare_attribute(f, bl(f.name, 16), 18)
    assert v.flag == FLAG_MATCHES, v

    # ceiling: above ceiling -> more_restrictive
    f = FIELDS["side_rear_setback_min_ft"]
    v = compare_attribute(f, bl(f.name, 4), 5)
    assert v.flag == FLAG_MORE_RESTRICTIVE, v
    v = compare_attribute(f, bl(f.name, 4), 4)
    assert v.flag == FLAG_MATCHES, v

    # must_equal: stricter opposite -> more_restrictive; over-permissive -> needs_review
    f = FIELDS["owner_occupancy_required_adu"]  # must be False; True is stricter
    v = compare_attribute(f, bl(f.name, False), True)
    assert v.flag == FLAG_MORE_RESTRICTIVE, v
    f = FIELDS["jadu_separate_sale_allowed"]  # must be False; True is unlawful
    v = compare_attribute(f, bl(f.name, False), True)
    assert v.flag == FLAG_NEEDS_REVIEW and v.severity == "critical", v

    # conditional: non-default -> needs_review (not auto more_restrictive)
    f = FIELDS["parking_required"]
    v = compare_attribute(f, bl(f.name, False), True)
    assert v.flag == FLAG_NEEDS_REVIEW and v.issue_type == "conditional_needs_facts", v

    # informational -> not_applicable, never flagged
    f = FIELDS["adu_condo_sale_allowed"]
    v = compare_attribute(f, None, True)
    assert v.flag == FLAG_NOT_APPLICABLE and v.issue_type is None, v

    # missing baseline -> needs_review
    f = FIELDS["permit_review_days"]
    v = compare_attribute(f, None, 30)
    assert v.flag == FLAG_NEEDS_REVIEW and v.issue_type == "no_state_baseline", v

    # roll-up precedence
    assert _roll_up([FLAG_MATCHES, FLAG_MORE_RESTRICTIVE]) == FLAG_MORE_RESTRICTIVE
    assert _roll_up([FLAG_MATCHES, FLAG_NEEDS_REVIEW]) == FLAG_NEEDS_REVIEW
    assert _roll_up([FLAG_MATCHES, FLAG_NOT_APPLICABLE]) == FLAG_MATCHES
    print("validate OK")
