"""Data contracts and the repository seam for the deterministic core.

This module holds ONLY plain dataclasses and a ``typing.Protocol``. It has no
third-party imports so it can be imported in unit tests without a database
driver installed. The concrete PostGIS implementation lives in ``core.db`` and
is imported lazily by the API layer; unit tests provide a fake that satisfies
:class:`FeasibilityRepository`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol, Sequence


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GeoPoint:
    """A WGS84 (SRID 4326) point. ``lon`` first, matching GeoJSON order."""

    lon: float
    lat: float


@dataclass
class SourceRef:
    """Provenance carried by every substantive value.

    Mirrors the OpenAPI ``Provenance`` schema. ``retrieved_at`` /
    ``last_verified_at`` are stored as timezone-aware datetimes and serialized to
    ISO-8601 in the API layer.
    """

    source_url: str
    source_title: str
    source_section: Optional[str] = None
    source_layer: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    confidence: str = "medium"
    data_status: str = "current"
    snapshot_hash: Optional[str] = None


@dataclass
class JurisdictionMatch:
    id: str
    slug: str
    name: str
    display_name: str
    coverage_status: str
    matched_confidence: str
    source: SourceRef
    supported_project_types: Sequence[str] = field(default_factory=tuple)


@dataclass
class ParcelMatch:
    matched: bool
    id: Optional[str] = None
    apn: Optional[str] = None
    lot_size_sqft: Optional[float] = None
    centroid: Optional[GeoPoint] = None
    match_method: Optional[str] = None
    match_tolerance_m: Optional[float] = None
    source: Optional[SourceRef] = None


@dataclass
class ZoneMatch:
    zone_code: str
    zone_name: Optional[str]
    zone_category: Optional[str]
    general_plan: Optional[str]
    source: SourceRef


@dataclass
class ZoningResult:
    """All zoning districts the parcel/centroid touches (for ambiguity)."""

    zones: list[ZoneMatch] = field(default_factory=list)

    @property
    def primary(self) -> Optional[ZoneMatch]:
        return self.zones[0] if self.zones else None

    @property
    def cross_zone_ambiguity(self) -> bool:
        distinct = {z.zone_code for z in self.zones}
        return len(distinct) > 1


@dataclass
class OverlayResult:
    overlay_type: str
    status: str  # hit | no_hit | source_unavailable
    raw_values: Optional[dict[str, Any]] = None
    description: Optional[str] = None
    source: Optional[SourceRef] = None


@dataclass
class Baseline:
    """A California statewide floor/ceiling from ``state_rule_baselines``."""

    field_name: str
    operator: str  # floor | ceiling | gte | lte | eq | must_equal
    baseline_value: Any
    unit: Optional[str]
    applies_to: Sequence[str]
    legal_citation: str
    source_url: str
    source_title: Optional[str]
    effective_from: Optional[str] = None
    last_verified_at: Optional[datetime] = None
    confidence: str = "high"
    data_status: str = "current"


@dataclass
class RuleAttr:
    """A single local rule attribute with its own provenance (never merged over)."""

    field_name: str
    value: Any
    unit: Optional[str] = None
    operator: Optional[str] = None
    source: Optional[SourceRef] = None
    state_baseline_id: Optional[str] = None


@dataclass
class ZoningRuleSet:
    zone_code: str
    project_type: str
    zone_name: Optional[str] = None
    version: Optional[int] = None
    review_status: str = "pending"
    attributes: list[RuleAttr] = field(default_factory=list)


@dataclass
class BufferedArea:
    """Result of a PostGIS inward-buffer envelope computation.

    ``buffered_area_sqm`` is measured on the geography type (true metric area).
    ``orientation_known`` is False whenever a uniform inset was used because
    per-edge (front/side/rear) orientation could not be determined - the caller
    must then downgrade precision.
    """

    available: bool
    buffered_area_sqm: Optional[float] = None
    orientation_known: bool = False
    inset_m: Optional[float] = None
    source: Optional[SourceRef] = None


# ---------------------------------------------------------------------------
# Repository protocol - the only seam between the deterministic core and Postgres
# ---------------------------------------------------------------------------
class FeasibilityRepository(Protocol):
    """Everything the feasibility orchestrator needs from the database.

    Implemented for real by ``core.db.PostgresRepository`` and by fakes in tests.
    All geometry is SRID 4326; tolerances are documented in meters.
    """

    # --- Step A: address -> jurisdiction (boundary test) --------------------
    def find_jurisdiction_for_point(self, point: GeoPoint) -> Optional[JurisdictionMatch]:
        ...

    def get_jurisdiction_by_slug(self, slug: str) -> Optional[JurisdictionMatch]:
        ...

    def list_jurisdictions(self) -> list[dict[str, Any]]:
        ...

    # --- Step B: parcel lookup ---------------------------------------------
    def find_parcel_for_point(
        self, jurisdiction_id: str, point: GeoPoint, tolerance_m: float
    ) -> ParcelMatch:
        ...

    # --- Step C: zoning lookup ---------------------------------------------
    def find_zoning_for_parcel(
        self, jurisdiction_id: str, parcel_id: Optional[str], point: GeoPoint
    ) -> ZoningResult:
        ...

    # --- Step D: overlay lookup --------------------------------------------
    def find_overlays_for_parcel(
        self, jurisdiction_id: Optional[str], parcel_id: Optional[str], point: GeoPoint
    ) -> list[OverlayResult]:
        ...

    # --- Step E: rules ------------------------------------------------------
    def get_zoning_rule(
        self, jurisdiction_id: str, zone_code: str, project_type: str
    ) -> Optional[ZoningRuleSet]:
        ...

    def get_state_baselines(self, project_type: str) -> list[Baseline]:
        ...

    # --- Step F: approximate envelope (LA v1 only) -------------------------
    def compute_inward_buffer_area(
        self, parcel_id: str, inset_m: float
    ) -> BufferedArea:
        ...

    # --- Persistence + cache -----------------------------------------------
    def find_cached_analysis(
        self, request_fingerprint: str, within_hours: int
    ) -> Optional[dict[str, Any]]:
        ...

    def find_by_idempotency_key(
        self, consumer_id: Optional[str], idempotency_key: str
    ) -> Optional[dict[str, Any]]:
        ...

    def insert_analysis(self, record: dict[str, Any]) -> str:
        ...

    def insert_findings(self, analysis_id: str, findings: list[dict[str, Any]]) -> None:
        ...

    def get_analysis(self, analysis_id: str) -> Optional[dict[str, Any]]:
        ...

    def get_analysis_by_share_token(self, token: str) -> Optional[dict[str, Any]]:
        ...

    # --- Metadata endpoints -------------------------------------------------
    def get_jurisdiction_rules(
        self, slug: str, zone: Optional[str], project_type: Optional[str]
    ) -> Optional[dict[str, Any]]:
        ...

    def get_changelog(self, jurisdiction: Optional[str], limit: int) -> list[dict[str, Any]]:
        ...

    def get_source_freshness(self) -> list[dict[str, Any]]:
        ...

    # --- Metering -----------------------------------------------------------
    def record_usage_event(self, event: dict[str, Any]) -> None:
        ...

    def count_billable_this_month(self, consumer_id: str) -> int:
        ...

    def count_requests_last_minute(self, consumer_id: str) -> int:
        ...
