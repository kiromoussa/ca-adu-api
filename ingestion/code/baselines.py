"""Field catalog for ADU / JADU / SB 9 rule extraction + validation.

This is the single source of truth for:
  - which structured fields the offline LLM is asked to extract (schema.py),
  - each field's data type + description (schema.py prompt),
  - each field's comparison semantics for state-baseline validation
    (validate.py), and
  - which project_type(s) each field governs, so extraction can split a
    per-zone-district candidate into per-project_type zoning_rules rows that
    match the DB schema (zoning_rules is keyed by project_type).

The authoritative numeric floors/ceilings + legal citations live in the
`state_rule_baselines` table (seeded from the product spec). validate.py reads
those rows at runtime for the threshold value + citation + source_url, and uses
the `kind` here for the comparison direction. Values in this file are the spec
defaults, present so the catalog is self-describing and the offline self-checks
run without a database.

Laws: AB 68 / AB 881 / AB 2221 / SB 13 / SB 897 / SB 9 (Gov. Code 65852.21,
66411.7), ADU/JADU statute recodified to Gov. Code 66310-66342 / 66333-66339.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# project types (mirror config/jurisdictions.yaml + the DB CHECK constraints)
# ---------------------------------------------------------------------------
PT_DETACHED = "detached_adu"
PT_ATTACHED = "attached_adu"
PT_GARAGE = "garage_conversion"
PT_JADU = "jadu"
PT_SB9_DUPLEX = "sb9_duplex"
PT_SB9_SPLIT = "sb9_urban_lot_split"

PROJECT_TYPES: tuple[str, ...] = (
    PT_DETACHED,
    PT_ATTACHED,
    PT_GARAGE,
    PT_JADU,
    PT_SB9_DUPLEX,
    PT_SB9_SPLIT,
)

# Convenience groupings.
_ADU_BUILD = (PT_DETACHED, PT_ATTACHED, PT_GARAGE)          # physical ADU builds
_ADU_ALL = (PT_DETACHED, PT_ATTACHED, PT_GARAGE, PT_JADU)   # ADU family + JADU

# ---------------------------------------------------------------------------
# data types
# ---------------------------------------------------------------------------
DTYPE_NUMERIC = "numeric"
DTYPE_BOOLEAN = "boolean"

# comparison kinds (drive validate.py's flag decision):
#   floor        - local value must be >= baseline; below -> more_restrictive
#   ceiling      - local value must be <= baseline; above -> more_restrictive
#   must_equal   - boolean must equal baseline; the stricter opposite ->
#                  more_restrictive, the over-permissive opposite -> needs_review
#   conditional  - boolean whose lawful value depends on facts not knowable from
#                  zone text (transit proximity, shared sanitation); the
#                  non-preferred value -> needs_review, never auto more_restrictive
#   informational- optional local opt-in (AB 1033); never flagged
KIND_FLOOR = "floor"
KIND_CEILING = "ceiling"
KIND_MUST_EQUAL = "must_equal"
KIND_CONDITIONAL = "conditional"
KIND_INFORMATIONAL = "informational"

# Map catalog kind -> the operator vocabulary used by state_rule_baselines and
# rule_attributes in the DB schema (CHECK: gte/lte/eq/must_equal/floor/ceiling).
_KIND_TO_OPERATOR = {
    KIND_FLOOR: "floor",
    KIND_CEILING: "ceiling",
    KIND_MUST_EQUAL: "must_equal",
    KIND_CONDITIONAL: "eq",
    KIND_INFORMATIONAL: None,
}

_UNSET = object()


@dataclass(frozen=True)
class Field:
    """One extractable + validatable rule field."""

    name: str
    dtype: str
    kind: str
    value: object                    # spec default threshold / expected bool / None
    law: str
    description: str
    applies_to: tuple[str, ...]      # project_type(s) this field governs
    unit: str | None = None
    # KIND_MUST_EQUAL only: the value indicating a STRICTER-than-state local rule
    # (-> more_restrictive). None means the opposite value is over-permissive
    # (-> needs_review). _UNSET for every non-must_equal field.
    restrictive_value: object = _UNSET

    @property
    def operator(self) -> str | None:
        return _KIND_TO_OPERATOR[self.kind]


_FIELDS: list[Field] = [
    # --- heights (ft) ---
    Field(
        name="max_height_detached_standard_ft",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=16, unit="ft",
        law="AB 2221 (2023)", applies_to=(PT_DETACHED, PT_GARAGE),
        description=(
            "Maximum height a jurisdiction may impose on a standard detached ADU. "
            "State floor: at least 16 ft. A local cap below 16 ft is more "
            "restrictive than state law."
        ),
    ),
    Field(
        name="max_height_near_transit_ft",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=18, unit="ft",
        law="AB 2221 / SB 897", applies_to=(PT_DETACHED, PT_ATTACHED),
        description=(
            "Maximum detached ADU height within 1/2 mile of a major transit stop "
            "or high-quality transit corridor. State floor: at least 18 ft. A "
            "local cap below 18 ft is more restrictive."
        ),
    ),
    Field(
        name="max_height_multifamily_lot_ft",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=18, unit="ft",
        law="AB 2221 (2023)", applies_to=(PT_DETACHED, PT_ATTACHED),
        description=(
            "Maximum detached ADU height on a lot with an existing or proposed "
            "multi-story multifamily dwelling. State floor: at least 18 ft. A "
            "local cap below 18 ft is more restrictive."
        ),
    ),
    Field(
        name="max_height_attached_ft",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=25, unit="ft",
        law="AB 2221 (2023)", applies_to=(PT_ATTACHED,),
        description=(
            "Maximum height for an ADU attached to the primary dwelling: 25 ft or "
            "the underlying zone limit, whichever is lower. Treated as a 25 ft "
            "floor; a local cap below 25 ft may be lawful only if the zone base "
            "height is lower, so verify against the zone's base height."
        ),
    ),
    # --- setbacks ---
    Field(
        name="side_rear_setback_min_ft",
        dtype=DTYPE_NUMERIC, kind=KIND_CEILING, value=4, unit="ft",
        law="AB 2221 / 2020 ADU law", applies_to=_ADU_BUILD,
        description=(
            "Minimum side and rear setback a jurisdiction may require for an ADU. "
            "State ceiling: no more than 4 ft. A required setback greater than 4 "
            "ft is more restrictive than state law."
        ),
    ),
    Field(
        name="front_setback_restriction",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=False,
        restrictive_value=True, law="AB 2221", applies_to=_ADU_BUILD,
        description=(
            "Whether a front-setback requirement is used to restrict siting. A "
            "front setback cannot preclude an ADU under 800 sq ft. Must be false; "
            "true is more restrictive."
        ),
    ),
    # --- occupancy / JADU ---
    Field(
        name="owner_occupancy_required_adu",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=False,
        restrictive_value=True, law="Gov. Code 66315 / 66323", applies_to=_ADU_BUILD,
        description=(
            "Whether owner-occupancy is required for a standalone ADU. Prohibited "
            "statewide. Must be false; true is more restrictive."
        ),
    ),
    Field(
        name="owner_occupancy_required_jadu",
        dtype=DTYPE_BOOLEAN, kind=KIND_CONDITIONAL, value=False,
        law="Gov. Code 66333(b)", applies_to=(PT_JADU,),
        description=(
            "Whether owner-occupancy is required for a JADU. Conditional: lawful "
            "only when the JADU shares sanitation with the main house. False is "
            "compliant; true needs review to confirm the shared-sanitation "
            "condition."
        ),
    ),
    Field(
        name="jadu_allowed",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=True,
        restrictive_value=False, law="Gov. Code 66333(a),(d),(f)", applies_to=(PT_JADU,),
        description=(
            "Whether at least one JADU per single-family lot is permitted (within "
            "existing walls, efficiency kitchen). Must be true; false is more "
            "restrictive."
        ),
    ),
    Field(
        name="jadu_separate_sale_allowed",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=False,
        restrictive_value=None,  # true = over-permissive / unlawful -> needs_review
        law="Gov. Code 66333(c)(1)", applies_to=(PT_JADU,),
        description=(
            "Whether a JADU may be sold separately from the primary residence. "
            "Prohibited. Must be false; true is an unlawful over-permission and "
            "needs review."
        ),
    ),
    Field(
        name="adu_condo_sale_allowed",
        dtype=DTYPE_BOOLEAN, kind=KIND_INFORMATIONAL, value=None,
        law="AB 1033 (2023)", applies_to=_ADU_BUILD,
        description=(
            "Whether the jurisdiction has opted in to allowing ADUs to be sold as "
            "condominiums under AB 1033. Optional local adoption; either value is "
            "lawful. Informational only, never flagged."
        ),
    ),
    # --- parking / permitting ---
    Field(
        name="parking_required",
        dtype=DTYPE_BOOLEAN, kind=KIND_CONDITIONAL, value=False,
        law="SB 897", applies_to=_ADU_ALL,
        description=(
            "Whether ADU parking is required. State law forbids requiring parking "
            "within 1/2 mile of transit, in historic districts, when part of a new "
            "SFD/MFD, when on-street permit parking is unavailable, or with "
            "car-share within a block. Context-dependent: false is compliant; true "
            "needs review to confirm no exemption applies."
        ),
    ),
    Field(
        name="demolition_permit_concurrent",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=True,
        restrictive_value=False, law="SB 897", applies_to=_ADU_BUILD,
        description=(
            "Whether a demolition permit is processed concurrently with the ADU "
            "building permit (historic excepted). Must be true; false is more "
            "restrictive."
        ),
    ),
    Field(
        name="permit_review_days",
        dtype=DTYPE_NUMERIC, kind=KIND_CEILING, value=60, unit="days",
        law="SB 897 / AB 2221", applies_to=_ADU_ALL,
        description=(
            "Maximum days the jurisdiction may take to approve or deny an ADU "
            "application. State ceiling: 60 days. More than 60 days is more "
            "restrictive."
        ),
    ),
    Field(
        name="fire_sprinkler_trigger",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=False,
        restrictive_value=True, law="SB 897", applies_to=_ADU_ALL,
        description=(
            "Whether building an ADU triggers a fire-sprinkler requirement in the "
            "existing primary dwelling. Prohibited. Must be false; true is more "
            "restrictive."
        ),
    ),
    # --- fees / size ---
    Field(
        name="impact_fee_exempt_sqft_threshold",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=750, unit="sqft",
        law="AB 68 / SB 13", applies_to=_ADU_BUILD,
        description=(
            "Square-footage threshold at or below which ADUs are exempt from "
            "impact fees. State floor: ADUs of 750 sq ft or less must be exempt, "
            "so the threshold must be at least 750. A lower threshold is more "
            "restrictive."
        ),
    ),
    Field(
        name="max_size_sqft_1br",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=850, unit="sqft",
        law="Gov. Code ADU statute", applies_to=(PT_DETACHED, PT_ATTACHED),
        description=(
            "Local maximum-size cap for a one-bedroom ADU. A local cap cannot go "
            "below 850 sq ft. A cap under 850 is more restrictive."
        ),
    ),
    Field(
        name="max_size_sqft_2br",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=1000, unit="sqft",
        law="Gov. Code ADU statute", applies_to=(PT_DETACHED, PT_ATTACHED),
        description=(
            "Local maximum-size cap for a two-or-more-bedroom ADU. A local cap "
            "cannot go below 1,000 sq ft. A cap under 1,000 is more restrictive."
        ),
    ),
    Field(
        name="max_size_sqft_general_cap",
        dtype=DTYPE_NUMERIC, kind=KIND_FLOOR, value=800, unit="sqft",
        law="Gov. Code ADU statute", applies_to=_ADU_BUILD,
        description=(
            "General maximum-size cap the jurisdiction applies to ADUs. Statewide, "
            "an ADU of at least 800 sq ft must be allowed regardless of other "
            "standards (1,200 sq ft is the commonly recognized ceiling). A general "
            "cap below 800 is more restrictive."
        ),
    ),
    # --- misc compliance ---
    Field(
        name="nonconforming_zoning_denial_allowed",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=False,
        restrictive_value=True, law="SB 897", applies_to=_ADU_ALL,
        description=(
            "Whether the jurisdiction may deny an ADU due to unrelated "
            "nonconforming conditions absent a health/safety finding. Prohibited. "
            "Must be false; true is more restrictive."
        ),
    ),
    Field(
        name="pre_2018_unpermitted_adu_amnesty",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=True,
        restrictive_value=False, law="SB 897", applies_to=_ADU_ALL,
        description=(
            "Whether unpermitted ADUs built before Jan 1, 2018 receive amnesty "
            "absent a safety finding. Required. Must be true; false is more "
            "restrictive."
        ),
    ),
    # --- SB 9 ---
    Field(
        name="sb9_duplex_ministerial",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=True,
        restrictive_value=False, law="SB 9 / Gov. Code 65852.21", applies_to=(PT_SB9_DUPLEX,),
        description=(
            "Whether duplexes are approved ministerially (no discretionary review) "
            "in single-family zones within urbanized areas. Required. Must be "
            "true; false is more restrictive."
        ),
    ),
    Field(
        name="sb9_lot_split_min_lot_sqft",
        dtype=DTYPE_NUMERIC, kind=KIND_CEILING, value=1200, unit="sqft",
        law="SB 9 / Gov. Code 66411.7", applies_to=(PT_SB9_SPLIT,),
        description=(
            "Minimum resulting-lot size the jurisdiction may require for an SB 9 "
            "lot split. State allows lots as small as 1,200 sq ft, so a "
            "jurisdiction may not require more than 1,200 sq ft. A required minimum "
            "above 1,200 is more restrictive."
        ),
    ),
    Field(
        name="sb9_lot_split_ratio",
        dtype=DTYPE_NUMERIC, kind=KIND_CEILING, value=0.4, unit="ratio",
        law="SB 9 / Gov. Code 66411.7", applies_to=(PT_SB9_SPLIT,),
        description=(
            "Minimum fraction of the original lot the smaller resulting parcel "
            "must be. State law caps this at 40% (0.4) - a 60/40 split. Requiring "
            "a larger fraction (more even split) is more restrictive, so the value "
            "must be <= 0.4."
        ),
    ),
    Field(
        name="sb9_one_split_per_owner",
        dtype=DTYPE_BOOLEAN, kind=KIND_MUST_EQUAL, value=True,
        restrictive_value=None,  # false = more permissive than statute -> needs_review
        law="SB 9 / Gov. Code 66411.7", applies_to=(PT_SB9_SPLIT,),
        description=(
            "Whether the one-lot-split-per-owner/property limit is enforced. State "
            "law sets this limit, so it must be true. False permits more splits "
            "than the statute contemplates and needs review."
        ),
    ),
]

# ---------------------------------------------------------------------------
# derived lookups
# ---------------------------------------------------------------------------
FIELDS: dict[str, Field] = {f.name: f for f in _FIELDS}
FIELD_NAMES: list[str] = [f.name for f in _FIELDS]
NUMERIC_FIELDS: list[str] = [f.name for f in _FIELDS if f.dtype == DTYPE_NUMERIC]
BOOLEAN_FIELDS: list[str] = [f.name for f in _FIELDS if f.dtype == DTYPE_BOOLEAN]


def fields_for_project_type(project_type: str) -> list[str]:
    """Ordered field names that govern a given project_type."""
    return [f.name for f in _FIELDS if project_type in f.applies_to]


if __name__ == "__main__":  # offline self-check
    assert len(FIELD_NAMES) == len(set(FIELD_NAMES)), "duplicate field"
    for f in _FIELDS:
        assert f.kind in {
            KIND_FLOOR, KIND_CEILING, KIND_MUST_EQUAL, KIND_CONDITIONAL,
            KIND_INFORMATIONAL,
        }, f.name
        assert set(f.applies_to) <= set(PROJECT_TYPES), f.name
        if f.kind == KIND_MUST_EQUAL:
            assert f.dtype == DTYPE_BOOLEAN and f.restrictive_value is not _UNSET, f.name
    # every project type is governed by at least one field
    for pt in PROJECT_TYPES:
        assert fields_for_project_type(pt), pt
    print(
        f"baselines OK: {len(FIELD_NAMES)} fields "
        f"({len(NUMERIC_FIELDS)} numeric, {len(BOOLEAN_FIELDS)} boolean), "
        f"{len(PROJECT_TYPES)} project types"
    )
