"""Deterministic rule engine: state-baseline validation and rule merging.

This is the heart of the trust guarantee. Local rule attributes and California
state baselines are merged WITHOUT overwriting local provenance: the local
value and its source are preserved verbatim, and the state baseline is attached
alongside as a comparison, together with a ``compliance_flag``.

The non-negotiable rule (spec 5 / ADR 7): when a local value is more restrictive
than the current state baseline, it is flagged
``possibly_more_restrictive_than_state_baseline`` and routed to review - it is
NEVER silently discarded and we never infer the local rule is invalid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .constants import (
    DB_COMPLIANCE_MATCHES,
    DB_COMPLIANCE_MORE_RESTRICTIVE,
    DB_COMPLIANCE_NEEDS_REVIEW,
    DB_COMPLIANCE_NOT_APPLICABLE,
)
from .repository import Baseline, RuleAttr, SourceRef, ZoningRuleSet


@dataclass
class MergedFinding:
    """A single rule field after state-baseline validation.

    ``value`` and ``source`` come from the LOCAL rule (or, when there is no local
    rule, from the state baseline used as a conservative fallback). ``origin``
    records which of the two supplied the value so callers can be honest about it.
    """

    field_name: str
    value: Any
    unit: Optional[str]
    source: SourceRef
    state_baseline: Any
    compliance_flag: str  # DB-level flag
    origin: str           # "local" | "state_baseline"
    operator: Optional[str] = None
    note: Optional[str] = None


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def evaluate_compliance(operator: str, local_value: Any, baseline_value: Any) -> str:
    """Compare a local value to the state baseline and return a DB compliance flag.

    Semantics (see seed_baselines.sql operator legend):

    - ``floor`` / ``gte``: the baseline is a state minimum the local ordinance
      must at least allow. A local value BELOW it is more restrictive.
    - ``ceiling`` / ``lte``: the baseline is a state maximum. A local value ABOVE
      it is more restrictive (imposes more than the state permits).
    - ``must_equal``: a boolean/exact state mandate. Any deviation is more
      restrictive (the local rule withholds something the state guarantees).
    - ``eq``: an exact expected value; a mismatch (or a conditional baseline) is
      routed to human review rather than asserted as a conflict.

    Anything indeterminate (missing values, dict/conditional baselines) returns
    ``needs_review`` - never a false "compliant".
    """
    if local_value is None or baseline_value is None:
        return DB_COMPLIANCE_NEEDS_REVIEW
    if isinstance(local_value, dict) or isinstance(baseline_value, dict):
        return DB_COMPLIANCE_NEEDS_REVIEW

    op = operator

    if op in ("floor", "gte"):
        if not (_is_number(local_value) and _is_number(baseline_value)):
            return DB_COMPLIANCE_NEEDS_REVIEW
        if local_value >= baseline_value:
            return DB_COMPLIANCE_MATCHES
        return DB_COMPLIANCE_MORE_RESTRICTIVE

    if op in ("ceiling", "lte"):
        if not (_is_number(local_value) and _is_number(baseline_value)):
            return DB_COMPLIANCE_NEEDS_REVIEW
        if local_value <= baseline_value:
            return DB_COMPLIANCE_MATCHES
        return DB_COMPLIANCE_MORE_RESTRICTIVE

    if op == "must_equal":
        return (
            DB_COMPLIANCE_MATCHES
            if local_value == baseline_value
            else DB_COMPLIANCE_MORE_RESTRICTIVE
        )

    if op == "eq":
        return (
            DB_COMPLIANCE_MATCHES
            if local_value == baseline_value
            else DB_COMPLIANCE_NEEDS_REVIEW
        )

    return DB_COMPLIANCE_NEEDS_REVIEW


def baselines_by_field(baselines: list[Baseline], project_type: str) -> dict[str, Baseline]:
    """Index applicable baselines by field name for a given project type.

    A baseline with an empty ``applies_to`` applies to every project type.
    """
    out: dict[str, Baseline] = {}
    for b in baselines:
        applies = tuple(b.applies_to or ())
        if applies and project_type not in applies:
            continue
        out[b.field_name] = b
    return out


def merge_attribute(
    attr: RuleAttr,
    baseline: Optional[Baseline],
) -> MergedFinding:
    """Merge one local attribute with its state baseline, preserving provenance."""
    if attr.source is None:
        raise ValueError(
            f"rule attribute {attr.field_name!r} is missing provenance; every "
            "substantive value must carry a source."
        )
    if baseline is None:
        return MergedFinding(
            field_name=attr.field_name,
            value=attr.value,
            unit=attr.unit,
            source=attr.source,
            state_baseline=None,
            compliance_flag=DB_COMPLIANCE_NOT_APPLICABLE,
            origin="local",
            operator=attr.operator,
            note="No matching California state baseline for this field.",
        )
    op = attr.operator or baseline.operator
    flag = evaluate_compliance(op, attr.value, baseline.baseline_value)
    note = None
    if flag == DB_COMPLIANCE_MORE_RESTRICTIVE:
        note = (
            "Local value appears more restrictive than the current California "
            "state baseline (" + baseline.legal_citation + "). Local source is "
            "preserved; verify against state law with a professional."
        )
    return MergedFinding(
        field_name=attr.field_name,
        value=attr.value,
        unit=attr.unit or baseline.unit,
        source=attr.source,          # local provenance, never overwritten
        state_baseline=baseline.baseline_value,
        compliance_flag=flag,
        origin="local",
        operator=op,
        note=note,
    )


def baseline_as_finding(baseline: Baseline) -> MergedFinding:
    """Represent a state baseline as a finding when no local rule exists yet.

    This keeps results useful during ``ingesting`` coverage: the state floor /
    ceiling is surfaced with HCD/statute provenance and clearly marked as a state
    baseline (origin ``state_baseline``), never presented as the local ordinance.
    """
    source = SourceRef(
        source_url=baseline.source_url,
        source_title=baseline.source_title or "California state law baseline",
        source_section=baseline.legal_citation,
        retrieved_at=baseline.last_verified_at,
        last_verified_at=baseline.last_verified_at,
        confidence=baseline.confidence,
        data_status=baseline.data_status,
    )
    return MergedFinding(
        field_name=baseline.field_name,
        value=baseline.baseline_value,
        unit=baseline.unit,
        source=source,
        state_baseline=baseline.baseline_value,
        compliance_flag=DB_COMPLIANCE_NOT_APPLICABLE,
        origin="state_baseline",
        operator=baseline.operator,
        note=(
            "California state baseline shown; the local ordinance value has not "
            "yet been ingested for this jurisdiction and zone."
        ),
    )


def merge_ruleset(
    ruleset: Optional[ZoningRuleSet],
    baselines: list[Baseline],
    project_type: str,
) -> list[MergedFinding]:
    """Produce a condition-by-condition finding set for a project type.

    Every local attribute is validated against its baseline. Any baseline that
    has no corresponding local attribute is added as a state-baseline finding so
    the caller sees the full applicable rule surface. Deterministic ordering:
    local findings first (in rule order), then remaining baselines by field name.
    """
    by_field = baselines_by_field(baselines, project_type)
    findings: list[MergedFinding] = []
    seen: set[str] = set()

    local_attrs = ruleset.attributes if ruleset else []
    for attr in local_attrs:
        baseline = by_field.get(attr.field_name)
        findings.append(merge_attribute(attr, baseline))
        seen.add(attr.field_name)

    for field_name in sorted(by_field.keys()):
        if field_name in seen:
            continue
        findings.append(baseline_as_finding(by_field[field_name]))

    return findings
