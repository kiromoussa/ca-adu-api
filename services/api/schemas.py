"""Pydantic v2 models mirroring ``openapi/openapi.yaml``.

These are the single source of truth on the server (ADR decision 5). Request
models forbid unknown fields (the OpenAPI uses ``additionalProperties: false``);
response models ignore extras so an additive core change never breaks
serialization. The feasibility disclaimer is validated to be byte-identical to
the spec constant.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..core.constants import DISCLAIMER

# ---- Enums (as Literals) ---------------------------------------------------
ProjectType = Literal[
    "detached_adu",
    "attached_adu",
    "garage_conversion",
    "jadu",
    "sb9_duplex",
    "sb9_urban_lot_split",
]
FeasibilityStatus = Literal[
    "likely_feasible",
    "likely_constrained",
    "needs_professional_review",
    "insufficient_data",
]
PathStatus = Literal[
    "likely_eligible",
    "likely_ineligible",
    "conditional",
    "needs_professional_review",
    "insufficient_data",
]
ConfidenceLevel = Literal["high", "medium", "low"]
DataStatus = Literal["current", "stale", "needs_review", "unavailable"]
ComplianceFlag = Literal[
    "compliant", "needs_review", "possibly_more_restrictive_than_state_baseline"
]
CoverageStatus = Literal["planned", "ingesting", "production"]
OverlayType = Literal[
    "flood", "fire", "historic", "coastal", "hillside", "environmental", "hpoz", "other"
]


class _Resp(BaseModel):
    """Base for response models: tolerate additive fields from the core."""

    model_config = ConfigDict(extra="ignore")


# ---- Provenance + sourced wrappers ----------------------------------------
class Provenance(_Resp):
    source_url: str
    source_title: str
    source_section: Optional[str] = None
    source_layer: Optional[str] = None
    retrieved_at: str
    last_verified_at: Optional[str] = None
    confidence: ConfidenceLevel
    data_status: DataStatus
    snapshot_hash: Optional[str] = None


class SourcedNumber(_Resp):
    value: Optional[float] = None
    unit: Optional[str] = None
    provenance: Provenance
    state_baseline: Optional[float] = None
    compliance_flag: Optional[ComplianceFlag] = None
    note: Optional[str] = None


class SourcedBoolean(_Resp):
    value: Optional[bool] = None
    provenance: Provenance
    state_baseline: Optional[bool] = None
    compliance_flag: Optional[ComplianceFlag] = None
    note: Optional[str] = None


class SourcedString(_Resp):
    value: Optional[str] = None
    provenance: Provenance
    note: Optional[str] = None


# ---- Request ---------------------------------------------------------------
class ExistingStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Optional[Literal["single_family", "multifamily", "none", "unknown"]] = None
    has_garage: Optional[bool] = None
    year_built: Optional[int] = None


class FeasibilityOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    near_transit: Optional[bool] = None
    historic_property: Optional[bool] = None
    include_envelope: Optional[bool] = None


class FeasibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(min_length=5)
    project_type: ProjectType
    target_sqft: Optional[float] = Field(default=None, ge=0)
    bedrooms: Optional[int] = Field(default=None, ge=0)
    proposed_height_ft: Optional[float] = Field(default=None, ge=0)
    existing_structure: Optional[ExistingStructure] = None
    options: Optional[FeasibilityOptions] = None


# ---- Response building blocks ---------------------------------------------
class RequestSummary(_Resp):
    address: str
    normalized_address: Optional[str] = None
    project_type: ProjectType
    target_sqft: Optional[float] = None
    bedrooms: Optional[int] = None
    proposed_height_ft: Optional[float] = None


class CoverageContext(_Resp):
    jurisdiction_slug: str
    jurisdiction_name: str
    coverage_status: CoverageStatus
    matched_confidence: Optional[ConfidenceLevel] = None
    provenance: Optional[Provenance] = None


class Centroid(_Resp):
    lon: float
    lat: float


class ParcelContext(_Resp):
    apn: Optional[SourcedString] = None
    matched: bool
    match_method: Optional[Literal["st_contains", "st_intersects", "geocode_point"]] = None
    match_tolerance_m: Optional[float] = None
    lot_size_sqft: Optional[SourcedNumber] = None
    centroid: Optional[Centroid] = None


class ZoningContext(_Resp):
    zone_code: Optional[SourcedString] = None
    zone_name: Optional[SourcedString] = None
    cross_zone_ambiguity: bool = False
    general_plan: Optional[SourcedString] = None


class EligiblePath(_Resp):
    path_type: ProjectType
    status: PathStatus
    reason: Optional[str] = None
    sources: list[Provenance] = Field(default_factory=list)


class DevelopmentConstraints(_Resp):
    max_height_ft: Optional[SourcedNumber] = None
    max_size_sqft: Optional[SourcedNumber] = None
    side_setback_ft: Optional[SourcedNumber] = None
    rear_setback_ft: Optional[SourcedNumber] = None
    front_setback_ft: Optional[SourcedNumber] = None
    parking_required: Optional[SourcedBoolean] = None
    owner_occupancy_required: Optional[SourcedBoolean] = None
    permit_review_days: Optional[SourcedNumber] = None
    impact_fee_exempt_sqft_threshold: Optional[SourcedNumber] = None
    fire_sprinkler_required: Optional[SourcedBoolean] = None


class OverlayFinding(_Resp):
    overlay_type: OverlayType
    status: Literal["hit", "no_hit", "source_unavailable"]
    # Severity of a hit: "info" for minimal-hazard designations (e.g. FEMA Zone
    # X/D) that do not constrain, "warning" for genuinely constraining hazards.
    severity: Optional[Literal["info", "warning", "critical"]] = None
    raw_values: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    provenance: Optional[Provenance] = None


class ApproximateEnvelope(_Resp):
    available: bool
    label: str = "approximate conceptual envelope"
    buildable_area_sqft: Optional[SourcedNumber] = None
    method: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Assumption(_Resp):
    text: str
    provenance: Optional[Provenance] = None


class Limitation(_Resp):
    code: Optional[str] = None
    text: str


class Freshness(_Resp):
    analysis_version: str
    rules_version: Optional[str] = None
    state_baseline_version: Optional[str] = None
    generated_at: str
    data_as_of: Optional[str] = None


class ScoreBlock(_Resp):
    value: float = Field(ge=0, le=100)
    explanation: str


class FeasibilityResponse(_Resp):
    analysis_id: str
    request: RequestSummary
    coverage: CoverageContext
    parcel: Optional[ParcelContext] = None
    zoning: Optional[ZoningContext] = None
    feasibility_status: FeasibilityStatus
    score: Optional[ScoreBlock] = None
    eligible_paths: list[EligiblePath] = Field(default_factory=list)
    development_constraints: Optional[DevelopmentConstraints] = None
    overlay_findings: list[OverlayFinding] = Field(default_factory=list)
    approximate_envelope: Optional[ApproximateEnvelope] = None
    assumptions: list[Assumption] = Field(default_factory=list)
    limitations: list[Limitation] = Field(default_factory=list)
    sources: list[Provenance] = Field(default_factory=list)
    freshness: Freshness
    share_token: Optional[str] = None
    disclaimer: str

    @field_validator("disclaimer")
    @classmethod
    def _disclaimer_verbatim(cls, v: str) -> str:
        if v != DISCLAIMER:
            raise ValueError("disclaimer must be the exact spec string, verbatim.")
        return v


# ---- Jurisdictions ---------------------------------------------------------
class Jurisdiction(_Resp):
    slug: str
    name: str
    display_name: Optional[str] = None
    state: Optional[str] = None
    county: Optional[str] = None
    publisher_type: Optional[Literal["american_legal", "municode"]] = None
    official_code_url: Optional[str] = None
    coverage_status: CoverageStatus
    supported_project_types: list[ProjectType] = Field(default_factory=list)
    sources_last_updated_at: Optional[str] = None


class JurisdictionList(_Resp):
    data: list[Jurisdiction]
    count: int


class RuleAttribute(_Resp):
    key: str
    value: Optional[Any] = None
    unit: Optional[str] = None
    state_baseline: Optional[Any] = None
    compliance_flag: Optional[ComplianceFlag] = None
    provenance: Provenance


class ZoneRuleSet(_Resp):
    zone_code: str
    zone_name: Optional[str] = None
    project_type: Optional[ProjectType] = None
    attributes: list[RuleAttribute] = Field(default_factory=list)


class RuleVersion(_Resp):
    version: str
    effective_at: str
    change_summary: Optional[str] = None
    source: Optional[Provenance] = None


class JurisdictionRulesResponse(_Resp):
    jurisdiction: Jurisdiction
    citywide: list[RuleAttribute] = Field(default_factory=list)
    zones: list[ZoneRuleSet] = Field(default_factory=list)
    citations: list[Provenance] = Field(default_factory=list)
    version_history: list[RuleVersion] = Field(default_factory=list)


# ---- Changelog -------------------------------------------------------------
class ChangelogEntry(_Resp):
    id: str
    jurisdiction_slug: str
    change_type: Literal[
        "coverage_change", "rule_update", "source_ingested", "source_refreshed", "correction"
    ]
    summary: str
    occurred_at: str
    source: Optional[Provenance] = None


class ChangelogResponse(_Resp):
    data: list[ChangelogEntry]
    count: int


# ---- Health ----------------------------------------------------------------
class SourceFreshness(_Resp):
    key: str
    name: Optional[str] = None
    data_status: DataStatus
    last_refreshed_at: Optional[str] = None


class HealthResponse(_Resp):
    status: Literal["ok", "degraded"]
    uptime_seconds: float
    api_version: str
    rules_version: Optional[str] = None
    sources: list[SourceFreshness] = Field(default_factory=list)


# ---- Error envelope --------------------------------------------------------
class ErrorBody(_Resp):
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    request_id: Optional[str] = None


class ErrorEnvelope(_Resp):
    error: ErrorBody
