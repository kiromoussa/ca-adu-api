"""In-memory fakes for unit testing the deterministic core.

``FakeRepository`` satisfies :class:`FeasibilityRepository` with canned,
constructor-configurable data so the orchestrator can be exercised end to end
without a database. ``StaticGeocoder`` (from the core) supplies deterministic,
network-free geocoding.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.core.repository import (
    Baseline,
    BufferedArea,
    GeoPoint,
    JurisdictionMatch,
    OverlayResult,
    ParcelMatch,
    SourceRef,
    ZoneMatch,
    ZoningResult,
    ZoningRuleSet,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def hcd_source(confidence: str = "high") -> SourceRef:
    return SourceRef(
        source_url="https://www.hcd.ca.gov/building-standards/adu/handbook",
        source_title="HCD ADU Handbook",
        source_section="AB 2221",
        retrieved_at=_now(),
        last_verified_at=_now(),
        confidence=confidence,
        data_status="current",
    )


def default_baselines() -> list[Baseline]:
    """A representative slice of the seeded California baselines for detached_adu."""
    common = dict(
        applies_to=("detached_adu",),
        source_url="https://www.hcd.ca.gov/building-standards/adu/handbook",
        source_title="HCD ADU Handbook",
        last_verified_at=_now(),
    )
    return [
        Baseline(field_name="max_height_detached_standard_ft", operator="floor",
                 baseline_value=16, unit="ft", legal_citation="AB 2221", **common),
        Baseline(field_name="side_rear_setback_min_ft", operator="ceiling",
                 baseline_value=4, unit="ft", legal_citation="AB 2221", **common),
        Baseline(field_name="parking_required", operator="must_equal",
                 baseline_value=False, unit=None, legal_citation="SB 897", **common),
        Baseline(field_name="owner_occupancy_required_adu", operator="must_equal",
                 baseline_value=False, unit=None, legal_citation="Gov 66323", **common),
        Baseline(field_name="permit_review_days", operator="lte",
                 baseline_value=60, unit="days", legal_citation="SB 897", **common),
        Baseline(field_name="impact_fee_exempt_sqft_threshold", operator="eq",
                 baseline_value=750, unit="sqft", legal_citation="AB 68", **common),
        Baseline(field_name="max_size_sqft_1br", operator="gte",
                 baseline_value=850, unit="sqft", legal_citation="Gov 66323", **common),
        Baseline(field_name="fire_sprinkler_trigger", operator="must_equal",
                 baseline_value=False, unit=None, legal_citation="SB 897", **common),
    ]


class FakeRepository:
    """Configurable in-memory repository for orchestrator tests."""

    def __init__(
        self,
        *,
        jurisdiction: Optional[JurisdictionMatch] = None,
        parcel: Optional[ParcelMatch] = None,
        zoning: Optional[ZoningResult] = None,
        overlays: Optional[list[OverlayResult]] = None,
        ruleset: Optional[ZoningRuleSet] = None,
        baselines: Optional[list[Baseline]] = None,
        buffered: Optional[BufferedArea] = None,
        cached: Optional[dict[str, Any]] = None,
    ):
        self._jurisdiction = jurisdiction
        self._parcel = parcel or ParcelMatch(matched=False)
        self._zoning = zoning or ZoningResult(zones=[])
        self._overlays = overlays or []
        self._ruleset = ruleset
        self._baselines = baselines if baselines is not None else default_baselines()
        self._buffered = buffered
        self._cached = cached
        # Captured writes for assertions.
        self.inserted_analyses: list[dict[str, Any]] = []
        self.inserted_findings: list[dict[str, Any]] = []
        self.usage_events: list[dict[str, Any]] = []
        self._idempotency: dict[tuple, dict[str, Any]] = {}

    # --- Step A/B ---
    def find_jurisdiction_for_point(self, point: GeoPoint):
        return self._jurisdiction

    def get_jurisdiction_by_slug(self, slug: str):
        return self._jurisdiction

    def list_jurisdictions(self):
        return []

    def find_parcel_for_point(self, jurisdiction_id, point, tolerance_m):
        return self._parcel

    # --- Step C/D ---
    def find_zoning_for_parcel(self, jurisdiction_id, parcel_id, point):
        return self._zoning

    def find_overlays_for_parcel(self, jurisdiction_id, parcel_id, point):
        return list(self._overlays)

    # --- Step E ---
    def get_zoning_rule(self, jurisdiction_id, zone_code, project_type):
        return self._ruleset

    def get_state_baselines(self, project_type):
        return list(self._baselines)

    # --- Step F ---
    def compute_inward_buffer_area(self, parcel_id, inset_m):
        return self._buffered or BufferedArea(available=False, inset_m=inset_m)

    # --- Cache + persistence ---
    def find_cached_analysis(self, request_fingerprint, within_hours):
        return self._cached

    def find_by_idempotency_key(self, consumer_id, idempotency_key):
        return self._idempotency.get((consumer_id or "", idempotency_key))

    def seed_idempotency(self, consumer_id, idempotency_key, record):
        self._idempotency[(consumer_id or "", idempotency_key)] = record

    def insert_analysis(self, record):
        self.inserted_analyses.append(record)
        return record.get("id") or "fake-analysis-id"

    def insert_findings(self, analysis_id, findings):
        self.inserted_findings.extend(findings)

    def get_analysis(self, analysis_id):
        for a in self.inserted_analyses:
            if a.get("id") == analysis_id:
                return {
                    "id": analysis_id,
                    "consumer_id": a.get("consumer_id"),
                    "share_token": a.get("share_token"),
                    "result_json": a.get("result_json"),
                }
        return None

    def get_analysis_by_share_token(self, token):
        for a in self.inserted_analyses:
            if a.get("share_token") == token:
                return {
                    "id": a.get("id"),
                    "consumer_id": a.get("consumer_id"),
                    "share_token": token,
                    "result_json": a.get("result_json"),
                }
        return None

    # --- Metadata ---
    def get_jurisdiction_rules(self, slug, zone, project_type):
        return None

    def get_changelog(self, jurisdiction, limit):
        return []

    def get_source_freshness(self):
        return []

    # --- Metering ---
    def record_usage_event(self, event):
        self.usage_events.append(event)

    def count_billable_this_month(self, consumer_id):
        return sum(1 for e in self.usage_events if e.get("billable"))

    def count_requests_last_minute(self, consumer_id):
        return len(self.usage_events)


# ---- Convenience builders -------------------------------------------------
def la_jurisdiction(coverage_status: str = "production") -> JurisdictionMatch:
    return JurisdictionMatch(
        id="00000000-0000-0000-0000-0000000000aa",
        slug="los_angeles",
        name="Los Angeles",
        display_name="City of Los Angeles",
        coverage_status=coverage_status,
        matched_confidence="high",
        source=SourceRef(
            source_url="https://api.aduatlas.example.com/v1/jurisdictions/los_angeles",
            source_title="ADU Atlas jurisdiction boundary (Los Angeles)",
            source_layer="jurisdictions.boundary",
            retrieved_at=_now(),
            confidence="high",
            data_status="current",
        ),
        supported_project_types=(
            "detached_adu", "attached_adu", "garage_conversion", "jadu",
            "sb9_duplex", "sb9_urban_lot_split",
        ),
    )


def matched_parcel() -> ParcelMatch:
    src = SourceRef(
        source_url="https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer",
        source_title="LA City ZIMAS parcels",
        source_layer="parcels",
        retrieved_at=_now(),
        last_verified_at=_now(),
        confidence="high",
        data_status="current",
    )
    return ParcelMatch(
        matched=True,
        id="00000000-0000-0000-0000-0000000000bb",
        apn="5123-014-007",
        lot_size_sqft=6500.0,
        centroid=GeoPoint(lon=-118.27, lat=34.03),
        match_method="st_contains",
        match_tolerance_m=0.0,
        source=src,
    )


def r1_zoning() -> ZoningResult:
    src = SourceRef(
        source_url="https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer",
        source_title="LA City ZIMAS zoning districts",
        source_layer="zoning",
        retrieved_at=_now(),
        last_verified_at=_now(),
        confidence="high",
        data_status="current",
    )
    return ZoningResult(zones=[ZoneMatch("R1", "One-Family Residential", "residential", None, src)])
