"""State-law baselines for CA ADU / density zoning fields.

This module is the single source of truth for validation. Every numeric and
boolean field on the `adu_rules` table (see supabase/migrations/0001_initial_schema.sql
and ca-adu-build-spec.md section 3) is encoded here as data: the comparison
operator, the state floor/ceiling/must-equal value, and the governing law.

Laws referenced: AB 2221 (2023), SB 897, SB 9 (Gov. Code 65852.21), AB 68 / SB 13,
and the ADU/JADU statute recodified into Gov. Code 66310-66342 / 66333-66339.5
(formerly 65852.2, renumbered by SB 477).

validate.py consumes BASELINES to compute compliance_flag + compliance_notes.
schema.py consumes RULE_FIELDS / dtype metadata to build the strict LLM schema.
Downstream tests should import from here rather than restating thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# data types + comparison kinds
# ---------------------------------------------------------------------------
DTYPE_NUMERIC = "numeric"
DTYPE_BOOLEAN = "boolean"

# floor    - local value must be >= baseline value, else more_restrictive
# ceiling  - local value must be <= baseline value, else more_restrictive
# must_equal - boolean must equal the expected value; the opposite value is
#              either more_restrictive (a stricter local rule) or, when the
#              opposite is illegally permissive, needs_review
# conditional - boolean whose lawful value depends on facts not knowable from
#               zone-district text (transit proximity, shared sanitation, etc.);
#               the non-preferred value is flagged needs_review, never auto-fail
# informational - optional local opt-in (e.g. AB 1033); never flagged
KIND_FLOOR = "floor"
KIND_CEILING = "ceiling"
KIND_MUST_EQUAL = "must_equal"
KIND_CONDITIONAL = "conditional"
KIND_INFORMATIONAL = "informational"

# sentinel: restrictive_value not applicable to this baseline
_UNSET = object()


@dataclass(frozen=True)
class Baseline:
    """One state-law comparison rule for a single adu_rules field."""

    field: str
    dtype: str  # DTYPE_NUMERIC | DTYPE_BOOLEAN
    kind: str  # KIND_*
    value: object  # numeric threshold, expected bool, or None (informational)
    law: str
    description: str
    # For KIND_MUST_EQUAL booleans only: the value that indicates the local
    # ordinance is *stricter* than the state allowance (-> more_restrictive).
    # If None, the non-expected value is an over-permissive anomaly
    # (-> needs_review). _UNSET for every non-must_equal baseline.
    restrictive_value: object = _UNSET


# ---------------------------------------------------------------------------
# the baselines - one entry per extractable adu_rules field
# ---------------------------------------------------------------------------
_BASELINE_LIST: list[Baseline] = [
    # --- heights (ft) ---
    Baseline(
        field="max_height_detached_standard_ft",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=16,
        law="AB 2221 (2023)",
        description=(
            "Maximum height a jurisdiction may impose on a standard detached ADU. "
            "State floor: cities must allow at least 16 ft. A local cap below 16 ft "
            "is more restrictive than state law."
        ),
    ),
    Baseline(
        field="max_height_near_transit_ft",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=18,
        law="AB 2221 / SB 897",
        description=(
            "Maximum detached ADU height within 1/2 mile of a major transit stop or "
            "high-quality transit corridor. State floor: at least 18 ft (plus up to "
            "2 ft to match roof pitch). A local cap below 18 ft is more restrictive."
        ),
    ),
    Baseline(
        field="max_height_multifamily_lot_ft",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=18,
        law="AB 2221 (2023)",
        description=(
            "Maximum detached ADU height on a lot with an existing or proposed "
            "multi-story multifamily dwelling. State floor: at least 18 ft. A local "
            "cap below 18 ft is more restrictive."
        ),
    ),
    Baseline(
        field="max_height_attached_ft",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=25,
        law="AB 2221 (2023)",
        description=(
            "Maximum height for an ADU attached to the primary dwelling: 25 ft or the "
            "underlying zone's height limit, whichever is lower. Treated as a 25 ft "
            "floor; a local cap below 25 ft may be lawful only if the underlying zone "
            "limit is lower, so verify against the zone's base height."
        ),
    ),
    # --- setbacks ---
    Baseline(
        field="side_rear_setback_min_ft",
        dtype=DTYPE_NUMERIC,
        kind=KIND_CEILING,
        value=4,
        law="AB 2221 / 2020 ADU law",
        description=(
            "Minimum side and rear setback a jurisdiction may require for an ADU. "
            "State ceiling: no more than 4 ft. A required setback greater than 4 ft "
            "is more restrictive than state law."
        ),
    ),
    Baseline(
        field="front_setback_restriction",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=False,
        restrictive_value=True,
        law="AB 2221",
        description=(
            "Whether a front-setback requirement is used to restrict siting. State "
            "law: a front setback cannot preclude an ADU under 800 sq ft. Must be "
            "false; true is more restrictive."
        ),
    ),
    # --- occupancy / JADU ---
    Baseline(
        field="owner_occupancy_required_adu",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=False,
        restrictive_value=True,
        law="Gov. Code 66315 / 66323",
        description=(
            "Whether owner-occupancy is required for a standalone ADU. Prohibited "
            "statewide. Must be false; true is more restrictive."
        ),
    ),
    Baseline(
        field="owner_occupancy_required_jadu",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_CONDITIONAL,
        value=False,
        law="Gov. Code 66333(b)",
        description=(
            "Whether owner-occupancy is required for a JADU. Conditional: lawful only "
            "when the JADU shares sanitation with the main house. False is compliant; "
            "true needs review to confirm the shared-sanitation condition."
        ),
    ),
    Baseline(
        field="jadu_allowed",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=True,
        restrictive_value=False,
        law="Gov. Code 66333(a),(d),(f)",
        description=(
            "Whether at least one JADU per single-family lot is permitted (within "
            "existing walls, efficiency kitchen). Must be true; false is more "
            "restrictive."
        ),
    ),
    Baseline(
        field="jadu_separate_sale_allowed",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=False,
        restrictive_value=None,  # true = over-permissive / unlawful -> needs_review
        law="Gov. Code 66333(c)(1)",
        description=(
            "Whether a JADU may be sold separately from the primary residence. "
            "Prohibited by state law. Must be false; true is an unlawful "
            "over-permission and needs review."
        ),
    ),
    Baseline(
        field="adu_condo_sale_allowed",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_INFORMATIONAL,
        value=None,
        law="AB 1033 (2023)",
        description=(
            "Whether the jurisdiction has opted in to allowing ADUs to be sold as "
            "condominiums under AB 1033. Optional local adoption; either value is "
            "lawful. Informational only, never flagged."
        ),
    ),
    # --- parking / permitting ---
    Baseline(
        field="parking_required",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_CONDITIONAL,
        value=False,
        law="SB 897",
        description=(
            "Whether ADU parking is required. State law forbids requiring parking "
            "within 1/2 mile of transit, in historic districts, when part of a new "
            "SFD/MFD, when on-street permit parking is unavailable, or with car-share "
            "within a block. Context-dependent: false is compliant; true needs review "
            "to confirm no exemption applies."
        ),
    ),
    Baseline(
        field="demolition_permit_concurrent",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=True,
        restrictive_value=False,
        law="SB 897",
        description=(
            "Whether a demolition permit is processed concurrently with the ADU "
            "building permit (no separate notice/placard, historic excepted). Must be "
            "true; false is more restrictive."
        ),
    ),
    Baseline(
        field="permit_review_days",
        dtype=DTYPE_NUMERIC,
        kind=KIND_CEILING,
        value=60,
        law="SB 897 / AB 2221",
        description=(
            "Maximum days the jurisdiction may take to approve or deny an ADU "
            "application. State ceiling: 60 days. More than 60 days is more "
            "restrictive."
        ),
    ),
    Baseline(
        field="fire_sprinkler_trigger",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=False,
        restrictive_value=True,
        law="SB 897",
        description=(
            "Whether building an ADU triggers a fire-sprinkler requirement in the "
            "existing primary dwelling. Prohibited. Must be false; true is more "
            "restrictive."
        ),
    ),
    # --- fees / size ---
    Baseline(
        field="impact_fee_exempt_sqft_threshold",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=750,
        law="AB 68 / SB 13",
        description=(
            "Square-footage threshold at or below which ADUs are exempt from impact "
            "fees. State floor: ADUs of 750 sq ft or less must be exempt, so the "
            "threshold must be at least 750. A lower threshold is more restrictive."
        ),
    ),
    Baseline(
        field="max_size_sqft_1br",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=850,
        law="Gov. Code ADU statute",
        description=(
            "Local maximum-size cap for a one-bedroom ADU. A local cap cannot go below "
            "850 sq ft. A cap under 850 is more restrictive."
        ),
    ),
    Baseline(
        field="max_size_sqft_2br",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=1000,
        law="Gov. Code ADU statute",
        description=(
            "Local maximum-size cap for a two-or-more-bedroom ADU. A local cap cannot "
            "go below 1,000 sq ft. A cap under 1,000 is more restrictive."
        ),
    ),
    Baseline(
        field="max_size_sqft_general_cap",
        dtype=DTYPE_NUMERIC,
        kind=KIND_FLOOR,
        value=800,
        law="Gov. Code ADU statute",
        description=(
            "General maximum-size cap the jurisdiction applies to ADUs. Statewide, an "
            "ADU of at least 800 sq ft must be allowed regardless of other standards "
            "(1,200 sq ft is the commonly recognized ceiling). A general cap below "
            "800 is more restrictive."
        ),
    ),
    # --- misc compliance ---
    Baseline(
        field="nonconforming_zoning_denial_allowed",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=False,
        restrictive_value=True,
        law="SB 897",
        description=(
            "Whether the jurisdiction may deny an ADU due to unrelated nonconforming "
            "conditions absent a health/safety finding. Prohibited. Must be false; "
            "true is more restrictive."
        ),
    ),
    Baseline(
        field="pre_2018_unpermitted_adu_amnesty",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=True,
        restrictive_value=False,
        law="SB 897",
        description=(
            "Whether unpermitted ADUs built before Jan 1, 2018 receive amnesty absent "
            "a safety finding. Required. Must be true; false is more restrictive."
        ),
    ),
    # --- SB 9 ---
    Baseline(
        field="sb9_duplex_ministerial",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=True,
        restrictive_value=False,
        law="SB 9 / Gov. Code 65852.21",
        description=(
            "Whether duplexes are approved ministerially (no discretionary review) in "
            "single-family zones within urbanized areas. Required. Must be true; false "
            "is more restrictive."
        ),
    ),
    Baseline(
        field="sb9_lot_split_min_lot_sqft",
        dtype=DTYPE_NUMERIC,
        kind=KIND_CEILING,
        value=1200,
        law="SB 9",
        description=(
            "Minimum resulting-lot size the jurisdiction may require for an SB 9 lot "
            "split. State allows lots as small as 1,200 sq ft, so a jurisdiction may "
            "not require more than 1,200 sq ft. A required minimum above 1,200 is more "
            "restrictive."
        ),
    ),
    Baseline(
        field="sb9_lot_split_ratio",
        dtype=DTYPE_NUMERIC,
        kind=KIND_CEILING,
        value=0.4,
        law="SB 9",
        description=(
            "Minimum fraction of the original lot the smaller resulting parcel must "
            "be. State law caps this at 40% (0.4) - a 60/40 split. Requiring the "
            "smaller parcel to be a larger fraction (a more even split) is more "
            "restrictive, so the value must be <= 0.4."
        ),
    ),
    Baseline(
        field="sb9_one_split_per_owner",
        dtype=DTYPE_BOOLEAN,
        kind=KIND_MUST_EQUAL,
        value=True,
        restrictive_value=None,  # false = more permissive than the statutory limit
        law="SB 9",
        description=(
            "Whether the one-lot-split-per-owner/property limit is enforced. State law "
            "sets this limit, so it must be true. False permits more splits than the "
            "statute contemplates and needs review."
        ),
    ),
]

# ---------------------------------------------------------------------------
# derived lookups (single source of truth for the rest of the pipeline)
# ---------------------------------------------------------------------------
BASELINES: dict[str, Baseline] = {b.field: b for b in _BASELINE_LIST}

# Ordered list of every extractable adu_rules field (excludes zone_district,
# which is the natural key, not a validated value).
RULE_FIELDS: list[str] = [b.field for b in _BASELINE_LIST]

NUMERIC_FIELDS: list[str] = [b.field for b in _BASELINE_LIST if b.dtype == DTYPE_NUMERIC]
BOOLEAN_FIELDS: list[str] = [b.field for b in _BASELINE_LIST if b.dtype == DTYPE_BOOLEAN]


def is_numeric(field: str) -> bool:
    return BASELINES[field].dtype == DTYPE_NUMERIC


def is_boolean(field: str) -> bool:
    return BASELINES[field].dtype == DTYPE_BOOLEAN


if __name__ == "__main__":  # simple self-check
    assert len(RULE_FIELDS) == len(set(RULE_FIELDS)), "duplicate field"
    assert len(RULE_FIELDS) == len(_BASELINE_LIST)
    for _b in _BASELINE_LIST:
        assert _b.kind in {
            KIND_FLOOR,
            KIND_CEILING,
            KIND_MUST_EQUAL,
            KIND_CONDITIONAL,
            KIND_INFORMATIONAL,
        }, _b.field
        if _b.kind == KIND_MUST_EQUAL:
            assert _b.dtype == DTYPE_BOOLEAN, _b.field
            assert _b.restrictive_value is not _UNSET, _b.field
    print(f"baselines OK: {len(RULE_FIELDS)} fields "
          f"({len(NUMERIC_FIELDS)} numeric, {len(BOOLEAN_FIELDS)} boolean)")
