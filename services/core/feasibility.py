"""Feasibility orchestrator (steps A-F) into an OpenAPI-shaped result.

``run_feasibility`` wires the deterministic pieces together:

    A. normalize + geocode the address                       (geocode)
    B. address -> jurisdiction via boundary test             (repo)
    C. parcel lookup (documented tolerance)                  (repo)
    D. zoning lookup + cross-zone ambiguity                  (repo)
    E. overlay/hazard intersection (hit / no_hit / unavailable)
    F. rule engine + state-baseline validation               (rules)
    G. approximate envelope (LA v1 only)                     (spatial)

It then selects a terminal ``feasibility_status`` deterministically, assembles a
dict that validates against the OpenAPI ``FeasibilityResponse`` schema, computes
a request fingerprint for the 24h dedupe cache, and (optionally) persists the
analysis and its per-field findings.

No LLM is used anywhere on this path.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from . import constants
from .constants import (
    ANALYSIS_VERSION,
    DB_COMPLIANCE_MORE_RESTRICTIVE,
    DB_COMPLIANCE_NEEDS_REVIEW,
    DISCLAIMER,
    RULES_VERSION,
    STATE_BASELINE_VERSION,
    db_compliance_to_api,
)
from .geocode import Geocoder, normalize_address
from .repository import (
    FeasibilityRepository,
    OverlayResult,
    SourceRef,
)
from .rules import MergedFinding, merge_ruleset
from .spatial import (
    DEFAULT_PARCEL_TOLERANCE_M,
    build_envelope,
    choose_uniform_inset_ft,
    feet_to_meters,
)

# Terminal statuses that count as a completed, billable analysis. insufficient_data
# is terminal but NOT billable (plans.yaml do_not_meter: insufficient_data_error).
BILLABLE_STATUSES = (
    "likely_feasible",
    "likely_constrained",
    "needs_professional_review",
)

# Overlay types that, on a hit, constrain feasibility.
HAZARD_OVERLAY_TYPES = ("flood", "fire", "coastal", "hillside")

# FEMA flood tuning. Only real Special Flood Hazard Areas (SFHAs) actually
# constrain an ADU. Minimal-hazard designations (Zone X, Zone D, and any "area of
# minimal flood hazard") are recorded as informational overlay hits but must NOT
# downgrade feasibility_status. The raw designation + provenance are kept either
# way; we never discard the source value.
SFHA_FLOOD_ZONES = frozenset(
    {"A", "AE", "AH", "AO", "AR", "A99", "V", "VE"}
)


def _flood_zone_token(ov: OverlayResult) -> Optional[str]:
    """Extract the FEMA FLD_ZONE token from an overlay hit (case-insensitive)."""
    raw = ov.raw_values or {}
    candidate: Optional[Any] = None
    for key in ("FLD_ZONE", "fld_zone", "designation", "zone"):
        if isinstance(raw, dict) and raw.get(key):
            candidate = raw.get(key)
            break
    if candidate is None:
        candidate = ov.description
    if candidate is None:
        return None
    return str(candidate).strip().upper()


def flood_hit_severity(ov: OverlayResult) -> str:
    """Classify a flood overlay hit as ``warning`` (SFHA) or ``info`` (minimal).

    A designation is constraining only when its zone token is a recognized SFHA
    (A/AE/AH/AO/AR/A99/V/VE). Everything else - Zone X, Zone D, "area of minimal
    flood hazard", or an absent designation - is informational and does not
    downgrade feasibility.
    """
    token = _flood_zone_token(ov)
    if not token:
        return "info"
    # A token may look like "AE" or "X (unshaded)" or "AREA OF MINIMAL FLOOD HAZARD".
    head = token.replace("(", " ").replace(")", " ").split()[0] if token.split() else token
    if head in SFHA_FLOOD_ZONES:
        return "warning"
    return "info"

# LA single-family zone-code prefixes used for coarse SB 9 gating. Anything not
# clearly single-family is treated as unknown (routed to review), never denied.
_LA_SINGLE_FAMILY_PREFIXES = ("R1", "RS", "RE", "RA", "RW1", "RD")

_KIND_COMPLETED = "completed"
_KIND_UNSUPPORTED = "unsupported_coverage"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------
@dataclass
class FeasibilityInput:
    address: str
    project_type: str
    target_sqft: Optional[float] = None
    bedrooms: Optional[int] = None
    proposed_height_ft: Optional[float] = None
    existing_structure: Optional[dict[str, Any]] = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeasibilityOutcome:
    kind: str                      # completed | unsupported_coverage
    feasibility_status: Optional[str]
    analysis_id: Optional[str]
    result: Optional[dict[str, Any]]
    billable: bool
    cache_hit: bool
    jurisdiction_slug: Optional[str] = None
    coverage_status: Optional[str] = None
    request_fingerprint: Optional[str] = None
    # Populated on the unsupported path so the API can build the 422 envelope.
    unsupported_detail: Optional[dict[str, Any]] = None


@dataclass
class _StatusInputs:
    resolved_jurisdiction: bool
    parcel_matched: bool
    zoning_resolved: bool
    low_confidence: bool
    cross_zone_ambiguity: bool
    compliance_flags: list[str]
    hazard_overlay_hit: bool
    requested_path_status: str
    orientation_unknown: bool


# ---------------------------------------------------------------------------
# Pure: feasibility status selection
# ---------------------------------------------------------------------------
def select_feasibility_status(inp: _StatusInputs) -> str:
    """Deterministically pick one terminal feasibility status.

    Precedence (first match wins):

    1. ``insufficient_data`` - could not resolve jurisdiction, parcel, or zoning,
       or the underlying match confidence is low.
    2. ``needs_professional_review`` - genuine ambiguity or a state-baseline
       conflict: cross-zone ambiguity, any finding flagged more-restrictive or
       needs-review, the requested path needs review, or an orientation-unknown
       envelope.
    3. ``likely_constrained`` - resolvable but limited: a hazard/overlay hit or a
       conditional / likely-ineligible requested path.
    4. ``likely_feasible`` - resolved and clean.
    """
    if (
        not inp.resolved_jurisdiction
        or not inp.parcel_matched
        or not inp.zoning_resolved
        or inp.low_confidence
    ):
        return "insufficient_data"

    review_flags = {DB_COMPLIANCE_NEEDS_REVIEW, DB_COMPLIANCE_MORE_RESTRICTIVE}
    if (
        inp.cross_zone_ambiguity
        or inp.requested_path_status == "needs_professional_review"
        or inp.orientation_unknown
        or any(f in review_flags for f in inp.compliance_flags)
    ):
        return "needs_professional_review"

    if inp.hazard_overlay_hit or inp.requested_path_status in (
        "conditional",
        "likely_ineligible",
    ):
        return "likely_constrained"

    return "likely_feasible"


# ---------------------------------------------------------------------------
# Fingerprint (24h dedupe / no-double-bill)
# ---------------------------------------------------------------------------
def compute_request_fingerprint(
    consumer_id: Optional[str], normalized_address: str, inp: FeasibilityInput
) -> str:
    """SHA-256 over the plans.yaml fingerprint fields (no time component).

    The 24h window is applied by the repository at cache-lookup time, so the
    fingerprint itself is stable for identical inputs from the same consumer.
    """
    payload = {
        "consumer_id": consumer_id or "",
        "normalized_address": normalized_address,
        "project_type": inp.project_type,
        "target_sqft": inp.target_sqft,
        "bedrooms": inp.bedrooms,
        "proposed_height_ft": inp.proposed_height_ft,
        "existing_structure": inp.existing_structure or None,
        "options": inp.options or {},
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Provenance / sourced-value builders
# ---------------------------------------------------------------------------
def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _prov(src: SourceRef, generated_at: datetime) -> dict[str, Any]:
    """Serialize a SourceRef to an OpenAPI Provenance object (required fields filled)."""
    retrieved = src.retrieved_at or generated_at
    return {
        "source_url": src.source_url,
        "source_title": src.source_title,
        "source_section": src.source_section,
        "source_layer": src.source_layer,
        "retrieved_at": _iso(retrieved),
        "last_verified_at": _iso(src.last_verified_at),
        "confidence": src.confidence,
        "data_status": src.data_status,
        "snapshot_hash": src.snapshot_hash,
    }


def _sourced_number(
    value: Optional[float],
    unit: Optional[str],
    src: SourceRef,
    generated_at: datetime,
    *,
    state_baseline: Any = None,
    compliance_flag: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "value": value,
        "unit": unit,
        "provenance": _prov(src, generated_at),
        "state_baseline": state_baseline,
    }
    if compliance_flag is not None:
        out["compliance_flag"] = compliance_flag
    if note is not None:
        out["note"] = note
    return out


def _sourced_boolean(
    value: Optional[bool],
    src: SourceRef,
    generated_at: datetime,
    *,
    state_baseline: Any = None,
    compliance_flag: Optional[str] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "value": value,
        "provenance": _prov(src, generated_at),
        "state_baseline": state_baseline,
    }
    if compliance_flag is not None:
        out["compliance_flag"] = compliance_flag
    if note is not None:
        out["note"] = note
    return out


def _sourced_string(
    value: Optional[str],
    src: SourceRef,
    generated_at: datetime,
    *,
    note: Optional[str] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "provenance": _prov(src, generated_at)}
    if note is not None:
        out["note"] = note
    return out


# ---------------------------------------------------------------------------
# Development constraints assembly
# ---------------------------------------------------------------------------
def _pick_height_field(project_type: str, options: dict[str, Any]) -> str:
    if project_type == "attached_adu":
        return "max_height_attached_ft"
    if options.get("near_transit"):
        return "max_height_near_transit_ft"
    return "max_height_detached_standard_ft"


def _pick_size_field(bedrooms: Optional[int]) -> str:
    if bedrooms is not None and bedrooms >= 2:
        return "max_size_sqft_2br"
    return "max_size_sqft_1br"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    return None


def build_development_constraints(
    findings_by_field: dict[str, MergedFinding],
    project_type: str,
    options: dict[str, Any],
    bedrooms: Optional[int],
    generated_at: datetime,
) -> dict[str, Any]:
    """Map merged rule findings onto the OpenAPI DevelopmentConstraints fields.

    Only fields we actually resolved are emitted; each carries provenance, the
    state baseline, and the API compliance flag. Nothing is invented.
    """
    dc: dict[str, Any] = {}

    def number_from(field_name: str, out_key: str) -> None:
        f = findings_by_field.get(field_name)
        if f is None:
            return
        dc[out_key] = _sourced_number(
            _num(f.value),
            f.unit,
            f.source,
            generated_at,
            state_baseline=_num(f.state_baseline),
            compliance_flag=db_compliance_to_api(f.compliance_flag),
            note=f.note,
        )

    def boolean_from(field_name: str, out_key: str) -> None:
        f = findings_by_field.get(field_name)
        if f is None:
            return
        dc[out_key] = _sourced_boolean(
            _bool(f.value),
            f.source,
            generated_at,
            state_baseline=_bool(f.state_baseline),
            compliance_flag=db_compliance_to_api(f.compliance_flag),
            note=f.note,
        )

    number_from(_pick_height_field(project_type, options), "max_height_ft")
    number_from(_pick_size_field(bedrooms), "max_size_sqft")
    number_from("side_rear_setback_min_ft", "side_setback_ft")
    number_from("side_rear_setback_min_ft", "rear_setback_ft")

    # Front setback is expressed by the state as a "may not preclude" restriction,
    # not a numeric minimum; surface it with a null value and an explanatory note.
    front = findings_by_field.get("front_setback_restriction")
    if front is not None:
        dc["front_setback_ft"] = _sourced_number(
            None,
            "ft",
            front.source,
            generated_at,
            state_baseline=None,
            compliance_flag=db_compliance_to_api(front.compliance_flag),
            note=(
                "State law provides that a front setback may not preclude an ADU "
                "of at least 800 sqft; no numeric front setback is asserted here."
            ),
        )

    boolean_from("parking_required", "parking_required")

    # Owner occupancy: ADU field is a hard false; JADU is conditional.
    if project_type == "jadu":
        occ = findings_by_field.get("owner_occupancy_required_jadu")
        if occ is not None:
            dc["owner_occupancy_required"] = _sourced_boolean(
                None,
                occ.source,
                generated_at,
                state_baseline=None,
                compliance_flag="needs_review",
                note=(
                    "JADU owner-occupancy is conditional on the shared-sanitation "
                    "arrangement; verify with the jurisdiction."
                ),
            )
    else:
        boolean_from("owner_occupancy_required_adu", "owner_occupancy_required")

    number_from("permit_review_days", "permit_review_days")
    number_from("impact_fee_exempt_sqft_threshold", "impact_fee_exempt_sqft_threshold")
    boolean_from("fire_sprinkler_trigger", "fire_sprinkler_required")

    return dc


# ---------------------------------------------------------------------------
# Eligible paths
# ---------------------------------------------------------------------------
def _is_single_family_zone(zone_code: Optional[str]) -> Optional[bool]:
    if not zone_code:
        return None
    z = zone_code.strip().upper()
    if any(z.startswith(p) for p in _LA_SINGLE_FAMILY_PREFIXES):
        return True
    # Multifamily / commercial prefixes are clearly not single-family.
    if z[:1] in ("C", "M") or z.startswith(("R2", "R3", "R4", "R5", "RAS")):
        return False
    return None


def determine_path_status(
    project_type: str,
    zone_code: Optional[str],
    has_local_rules: bool,
    zoning_resolved: bool,
) -> tuple[str, str]:
    """Deterministic per-path status + plain-language reason. Never a hard yes/no."""
    if not zoning_resolved:
        return "insufficient_data", "Zoning could not be resolved for this parcel."

    if project_type in constants.SB9_PROJECT_TYPES:
        sf = _is_single_family_zone(zone_code)
        if sf is False:
            return (
                "likely_ineligible",
                "SB 9 applies in single-family residential zones; this parcel's "
                f"zone ({zone_code}) does not appear to be single-family. Verify.",
            )
        if sf is None:
            return (
                "needs_professional_review",
                "SB 9 eligibility depends on single-family zoning and several "
                "site conditions that could not be confirmed automatically.",
            )
        return (
            "conditional",
            "Parcel appears to be single-family zoned. SB 9 has additional "
            "ministerial conditions (lot history, tenancy, environmental) that "
            "require verification.",
        )

    # ADU / JADU family.
    if has_local_rules:
        return (
            "likely_eligible",
            "State ADU law and the local ordinance both permit this project type "
            "in this zone, subject to the constraints listed.",
        )
    return (
        "conditional",
        "California state ADU law permits this project type statewide; the local "
        f"ordinance detail for {zone_code or 'this zone'} has not yet been "
        "ingested, so specific limits are shown from the state baseline.",
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_feasibility(
    repo: FeasibilityRepository,
    geocoder: Geocoder,
    inp: FeasibilityInput,
    *,
    consumer_id: Optional[str] = None,
    provider: str = "direct",
    plan: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    allow_share_token: bool = False,
    persist: bool = True,
    generated_at: Optional[datetime] = None,
) -> FeasibilityOutcome:
    """Run steps A-G and return a :class:`FeasibilityOutcome`.

    On an unsupported (non-production) jurisdiction, returns the
    ``unsupported_coverage`` kind WITHOUT persisting or billing.
    """
    generated_at = generated_at or _now()
    options = inp.options or {}
    normalized = normalize_address(inp.address)
    fingerprint = compute_request_fingerprint(consumer_id, normalized, inp)

    # 24h dedupe cache (no double-bill). A cache hit is a completed, non-billable
    # response returning the stored analysis verbatim.
    cached = repo.find_cached_analysis(fingerprint, within_hours=24)
    if cached is not None:
        return FeasibilityOutcome(
            kind=_KIND_COMPLETED,
            feasibility_status=cached.get("feasibility_status"),
            analysis_id=cached.get("id") or cached.get("analysis_id"),
            result=cached.get("result_json"),
            billable=False,
            cache_hit=True,
            jurisdiction_slug=cached.get("jurisdiction_slug"),
            coverage_status=cached.get("coverage_status"),
            request_fingerprint=fingerprint,
        )

    # --- Step A: geocode ---------------------------------------------------
    geo = geocoder.geocode(normalized or inp.address)

    sources: list[SourceRef] = []
    limitations: list[dict[str, Any]] = []
    assumptions: list[dict[str, Any]] = []

    if geo.source is not None:
        sources.append(geo.source)

    request_summary = {
        "address": inp.address,
        "normalized_address": normalized or None,
        "project_type": inp.project_type,
        "target_sqft": inp.target_sqft,
        "bedrooms": inp.bedrooms,
        "proposed_height_ft": inp.proposed_height_ft,
    }

    if not geo.resolved or geo.point is None:
        limitations.append(
            {
                "code": "geocode_failed",
                "text": "The address could not be geocoded with sufficient "
                "confidence, so no parcel-level analysis was performed.",
            }
        )
        return _insufficient_outcome(
            repo,
            inp,
            request_summary,
            normalized,
            fingerprint,
            sources,
            assumptions,
            limitations,
            generated_at,
            consumer_id,
            provider,
            plan,
            idempotency_key,
            persist,
            coverage=None,
        )

    point = geo.point

    # --- Step B: jurisdiction boundary test --------------------------------
    juris = repo.find_jurisdiction_for_point(point)
    if juris is None:
        limitations.append(
            {
                "code": "jurisdiction_unresolved",
                "text": "The point did not fall within any registered "
                "jurisdiction boundary.",
            }
        )
        return _insufficient_outcome(
            repo, inp, request_summary, normalized, fingerprint, sources,
            assumptions, limitations, generated_at, consumer_id, provider, plan,
            idempotency_key, persist, coverage=None,
        )

    sources.append(juris.source)
    coverage_block = {
        "jurisdiction_slug": juris.slug,
        "jurisdiction_name": juris.display_name or juris.name,
        "coverage_status": juris.coverage_status,
        "matched_confidence": juris.matched_confidence,
        "provenance": _prov(juris.source, generated_at),
    }

    # Coverage honesty: only production jurisdictions return a billable result.
    if juris.coverage_status != "production":
        return FeasibilityOutcome(
            kind=_KIND_UNSUPPORTED,
            feasibility_status=None,
            analysis_id=None,
            result=None,
            billable=False,
            cache_hit=False,
            jurisdiction_slug=juris.slug,
            coverage_status=juris.coverage_status,
            request_fingerprint=fingerprint,
            unsupported_detail={
                "jurisdiction_slug": juris.slug,
                "coverage_status": juris.coverage_status,
            },
        )

    # --- Step C: parcel lookup ---------------------------------------------
    parcel = repo.find_parcel_for_point(
        juris.id, point, tolerance_m=DEFAULT_PARCEL_TOLERANCE_M
    )
    parcel_block: dict[str, Any] = {"matched": parcel.matched}
    parcel_low_conf = False
    if parcel.matched and parcel.source is not None:
        sources.append(parcel.source)
        parcel_block["match_method"] = parcel.match_method
        parcel_block["match_tolerance_m"] = parcel.match_tolerance_m
        if parcel.apn is not None:
            parcel_block["apn"] = _sourced_string(parcel.apn, parcel.source, generated_at)
        if parcel.lot_size_sqft is not None:
            parcel_block["lot_size_sqft"] = _sourced_number(
                round(float(parcel.lot_size_sqft), 1), "sqft", parcel.source, generated_at
            )
        if parcel.centroid is not None:
            parcel_block["centroid"] = {
                "lon": parcel.centroid.lon,
                "lat": parcel.centroid.lat,
            }
        parcel_low_conf = (parcel.source.confidence == "low")
    else:
        limitations.append(
            {
                "code": "parcel_unmatched",
                "text": "No parcel polygon contained or intersected the geocoded "
                "point within the documented tolerance.",
            }
        )

    # --- Step D: zoning lookup ---------------------------------------------
    zoning = repo.find_zoning_for_parcel(juris.id, parcel.id, point)
    zoning_block: dict[str, Any] = {"cross_zone_ambiguity": zoning.cross_zone_ambiguity}
    primary_zone = zoning.primary
    zoning_resolved = primary_zone is not None
    if primary_zone is not None:
        sources.append(primary_zone.source)
        zoning_block["zone_code"] = _sourced_string(
            primary_zone.zone_code, primary_zone.source, generated_at
        )
        if primary_zone.zone_name is not None:
            zoning_block["zone_name"] = _sourced_string(
                primary_zone.zone_name, primary_zone.source, generated_at
            )
        if primary_zone.general_plan is not None:
            zoning_block["general_plan"] = _sourced_string(
                primary_zone.general_plan, primary_zone.source, generated_at
            )
        if zoning.cross_zone_ambiguity:
            others = ", ".join(sorted({z.zone_code for z in zoning.zones}))
            limitations.append(
                {
                    "code": "cross_zone_ambiguity",
                    "text": f"The parcel intersects more than one zoning district "
                    f"({others}); the primary zone was used. Verify.",
                }
            )
    else:
        limitations.append(
            {
                "code": "zoning_unresolved",
                "text": "No zoning district could be joined to this parcel.",
            }
        )

    zone_code = primary_zone.zone_code if primary_zone else None

    # --- Step E: overlay / hazard lookup -----------------------------------
    overlays: list[OverlayResult] = repo.find_overlays_for_parcel(
        juris.id, parcel.id, point
    )
    overlay_findings: list[dict[str, Any]] = []
    hazard_hit = False
    for ov in overlays:
        if ov.source is not None:
            sources.append(ov.source)
        severity: Optional[str] = None
        if ov.status == "hit" and ov.overlay_type in HAZARD_OVERLAY_TYPES:
            if ov.overlay_type == "flood":
                # Minimal-hazard flood zones (X, D, ...) are info-only and do not
                # constrain; only true SFHAs downgrade feasibility.
                severity = flood_hit_severity(ov)
            else:
                severity = "warning"
            if severity != "info":
                hazard_hit = True
        elif ov.status == "hit":
            severity = "info"
        raw_values = dict(ov.raw_values) if isinstance(ov.raw_values, dict) else ov.raw_values
        if severity is not None:
            if not isinstance(raw_values, dict):
                raw_values = {}
            raw_values.setdefault("severity", severity)
        overlay_findings.append(
            {
                "overlay_type": ov.overlay_type,
                "status": ov.status,
                "severity": severity,
                "raw_values": raw_values,
                "description": ov.description,
                "provenance": _prov(ov.source, generated_at) if ov.source else None,
            }
        )

    # --- Step F: rules + state-baseline validation -------------------------
    baselines = repo.get_state_baselines(inp.project_type)
    ruleset = repo.get_zoning_rule(juris.id, zone_code, inp.project_type) if zone_code else None
    has_local_rules = ruleset is not None and (ruleset.review_status == "verified")
    merged: list[MergedFinding] = merge_ruleset(ruleset, baselines, inp.project_type)
    findings_by_field = {f.field_name: f for f in merged}
    for f in merged:
        sources.append(f.source)
    compliance_flags = [f.compliance_flag for f in merged]

    development_constraints = build_development_constraints(
        findings_by_field, inp.project_type, options, inp.bedrooms, generated_at
    )

    # --- Eligible paths ----------------------------------------------------
    req_status, req_reason = determine_path_status(
        inp.project_type, zone_code, has_local_rules, zoning_resolved
    )
    path_sources = [
        _prov(f.source, generated_at)
        for f in merged
        if f.field_name.startswith(("max_", "parking", "owner", "sb9", "jadu"))
    ][:6]
    eligible_paths = [
        {
            "path_type": inp.project_type,
            "status": req_status,
            "reason": req_reason,
            "sources": path_sources,
        }
    ]

    # --- Step G: approximate envelope (LA v1 only, on request) -------------
    envelope_block: Optional[dict[str, Any]] = None
    orientation_unknown = False
    want_envelope = bool(options.get("include_envelope"))
    if want_envelope and juris.slug == "los_angeles" and parcel.matched and parcel.id:
        side_f = findings_by_field.get("side_rear_setback_min_ft")
        side_val = _num(side_f.value) if side_f else None
        inset_ft = choose_uniform_inset_ft(side_val, side_val, None)
        buffered = repo.compute_inward_buffer_area(
            parcel.id, inset_m=feet_to_meters(inset_ft)
        )
        env = build_envelope(buffered, inset_ft=inset_ft, orientation_known=False)
        if env.source is not None:
            sources.append(env.source)
        envelope_block = {
            "available": env.available,
            "label": env.label,
            "method": env.method,
            "assumptions": env.assumptions,
            "limitations": env.limitations,
        }
        if env.buildable_area_sqft is not None and env.source is not None:
            envelope_block["buildable_area_sqft"] = _sourced_number(
                env.buildable_area_sqft, "sqft", env.source, generated_at
            )
        orientation_unknown = env.needs_review
        if orientation_unknown:
            limitations.append(
                {
                    "code": "envelope_orientation_unknown",
                    "text": "Parcel edge orientation (front / side / rear) is unknown; "
                    "the envelope is a uniform-setback approximation pending "
                    "professional review.",
                }
            )
    elif want_envelope and juris.slug != "los_angeles":
        limitations.append(
            {
                "code": "envelope_unsupported_city",
                "text": "Approximate envelopes are supported for Los Angeles only "
                "in v1.",
            }
        )

    # --- Assumptions -------------------------------------------------------
    if options.get("near_transit"):
        assumptions.append(
            {
                "text": "Caller asserted the parcel is near transit; transit-based "
                "state provisions (height, parking) were applied.",
                "provenance": None,
            }
        )
    if not has_local_rules:
        assumptions.append(
            {
                "text": "Local ordinance rules for this zone are not yet ingested; "
                "constraints are shown from California state baselines and are "
                "labeled accordingly.",
                "provenance": None,
            }
        )

    # --- Feasibility status ------------------------------------------------
    low_confidence = (geo.confidence == "low") or parcel_low_conf
    status = select_feasibility_status(
        _StatusInputs(
            resolved_jurisdiction=True,
            parcel_matched=parcel.matched,
            zoning_resolved=zoning_resolved,
            low_confidence=low_confidence,
            cross_zone_ambiguity=zoning.cross_zone_ambiguity,
            compliance_flags=compliance_flags,
            hazard_overlay_hit=hazard_hit,
            requested_path_status=req_status,
            orientation_unknown=orientation_unknown,
        )
    )

    analysis_id = str(uuid.uuid4())
    dedup_sources = _dedup_sources(sources, generated_at)
    data_as_of = _max_verified(sources)

    result: dict[str, Any] = {
        "analysis_id": analysis_id,
        "request": request_summary,
        "coverage": coverage_block,
        "parcel": parcel_block,
        "zoning": zoning_block,
        "feasibility_status": status,
        "eligible_paths": eligible_paths,
        "development_constraints": development_constraints,
        "overlay_findings": overlay_findings,
        "assumptions": assumptions,
        "limitations": limitations,
        "sources": dedup_sources,
        "freshness": {
            "analysis_version": ANALYSIS_VERSION,
            "rules_version": RULES_VERSION,
            "state_baseline_version": STATE_BASELINE_VERSION,
            "generated_at": _iso(generated_at),
            "data_as_of": _iso(data_as_of),
        },
        "share_token": None,
        "disclaimer": DISCLAIMER,
    }
    if envelope_block is not None:
        result["approximate_envelope"] = envelope_block

    billable = status in BILLABLE_STATUSES

    # Mint a public share token only for completed, billable analyses when the
    # caller's plan permits it.
    share_token: Optional[str] = None
    if allow_share_token and billable:
        import secrets

        share_token = secrets.token_urlsafe(16)
        result["share_token"] = share_token

    if persist:
        _persist(
            repo,
            analysis_id,
            fingerprint,
            idempotency_key,
            consumer_id,
            provider,
            plan,
            inp,
            normalized,
            point,
            juris,
            parcel,
            status,
            result,
            merged,
            overlay_findings,
            billable,
            generated_at,
            share_token,
        )

    return FeasibilityOutcome(
        kind=_KIND_COMPLETED,
        feasibility_status=status,
        analysis_id=analysis_id,
        result=result,
        billable=billable,
        cache_hit=False,
        jurisdiction_slug=juris.slug,
        coverage_status=juris.coverage_status,
        request_fingerprint=fingerprint,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _insufficient_outcome(
    repo,
    inp,
    request_summary,
    normalized,
    fingerprint,
    sources,
    assumptions,
    limitations,
    generated_at,
    consumer_id,
    provider,
    plan,
    idempotency_key,
    persist,
    coverage,
) -> FeasibilityOutcome:
    """Build (and optionally persist) an insufficient_data result. Not billable."""
    analysis_id = str(uuid.uuid4())
    result = {
        "analysis_id": analysis_id,
        "request": request_summary,
        "coverage": coverage
        or {
            "jurisdiction_slug": "unknown",
            "jurisdiction_name": "Unknown",
            "coverage_status": "planned",
        },
        "parcel": {"matched": False},
        "feasibility_status": "insufficient_data",
        "eligible_paths": [],
        "assumptions": assumptions,
        "limitations": limitations,
        "sources": _dedup_sources(sources, generated_at),
        "freshness": {
            "analysis_version": ANALYSIS_VERSION,
            "rules_version": RULES_VERSION,
            "state_baseline_version": STATE_BASELINE_VERSION,
            "generated_at": _iso(generated_at),
            "data_as_of": None,
        },
        "share_token": None,
        "disclaimer": DISCLAIMER,
    }
    if persist:
        try:
            repo.insert_analysis(
                {
                    "id": analysis_id,
                    "request_fingerprint": fingerprint,
                    "idempotency_key": idempotency_key,
                    "share_token": None,
                    "consumer_id": consumer_id,
                    "provider": provider,
                    "plan": plan,
                    "input_address": inp.address,
                    "normalized_address": normalized or None,
                    "geocode_lon": None,
                    "geocode_lat": None,
                    "project_type": inp.project_type,
                    "target_sqft": inp.target_sqft,
                    "bedrooms": inp.bedrooms,
                    "proposed_height_ft": inp.proposed_height_ft,
                    "existing_structure": _existing_structure_bool(inp.existing_structure),
                    "options": inp.options or {},
                    "jurisdiction_id": None,
                    "parcel_id": None,
                    "coverage_status": None,
                    "feasibility_status": "insufficient_data",
                    "score": None,
                    "analysis_version": ANALYSIS_VERSION,
                    "result_json": result,
                    "disclaimer": DISCLAIMER,
                    "billable": False,
                    "billed": False,
                    "cache_hit": False,
                }
            )
        except Exception:
            # Persistence must never turn a valid analysis into a 500; the result
            # stands on its own. (Real errors are logged by the API layer.)
            pass
    return FeasibilityOutcome(
        kind=_KIND_COMPLETED,
        feasibility_status="insufficient_data",
        analysis_id=analysis_id,
        result=result,
        billable=False,
        cache_hit=False,
        request_fingerprint=fingerprint,
    )


def _existing_structure_bool(es: Optional[dict[str, Any]]) -> Optional[bool]:
    if not es:
        return None
    t = es.get("type")
    if t in (None, "none", "unknown"):
        return None
    return True


def _dedup_sources(sources: list[SourceRef], generated_at: datetime) -> list[dict[str, Any]]:
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for s in sources:
        key = (s.source_url, s.source_section, s.source_layer)
        if key in seen:
            continue
        seen.add(key)
        out.append(_prov(s, generated_at))
    return out


def _max_verified(sources: list[SourceRef]) -> Optional[datetime]:
    stamps = [s.last_verified_at for s in sources if s.last_verified_at is not None]
    return max(stamps) if stamps else None


def _persist(
    repo,
    analysis_id,
    fingerprint,
    idempotency_key,
    consumer_id,
    provider,
    plan,
    inp,
    normalized,
    point,
    juris,
    parcel,
    status,
    result,
    merged,
    overlay_findings,
    billable,
    generated_at,
    share_token,
) -> None:
    try:
        repo.insert_analysis(
            {
                "id": analysis_id,
                "request_fingerprint": fingerprint,
                "idempotency_key": idempotency_key,
                "share_token": share_token,
                "consumer_id": consumer_id,
                "provider": provider,
                "plan": plan,
                "input_address": inp.address,
                "normalized_address": normalized or None,
                "geocode_lon": point.lon,
                "geocode_lat": point.lat,
                "project_type": inp.project_type,
                "target_sqft": inp.target_sqft,
                "bedrooms": inp.bedrooms,
                "proposed_height_ft": inp.proposed_height_ft,
                "existing_structure": _existing_structure_bool(inp.existing_structure),
                "options": inp.options or {},
                "jurisdiction_id": juris.id,
                "parcel_id": parcel.id if parcel.matched else None,
                "coverage_status": juris.coverage_status,
                "feasibility_status": status,
                "score": None,
                "analysis_version": ANALYSIS_VERSION,
                "result_json": result,
                "disclaimer": DISCLAIMER,
                "billable": billable,
                "billed": billable,
                "cache_hit": False,
            }
        )
        findings_rows: list[dict[str, Any]] = []
        for i, f in enumerate(merged):
            findings_rows.append(
                {
                    "finding_type": "constraint",
                    "project_path": inp.project_type,
                    "field_name": f.field_name,
                    "detail": f.note,
                    "value_json": f.value,
                    "compliance_flag": f.compliance_flag,
                    "source_url": f.source.source_url,
                    "source_title": f.source.source_title,
                    "source_section": f.source.source_section,
                    "source_layer": f.source.source_layer,
                    "retrieved_at": _iso(f.source.retrieved_at or generated_at),
                    "last_verified_at": _iso(f.source.last_verified_at),
                    "confidence": f.source.confidence,
                    "data_status": f.source.data_status,
                    "sort_order": i,
                }
            )
        for j, ov in enumerate(overlay_findings):
            findings_rows.append(
                {
                    "finding_type": "overlay",
                    "field_name": ov["overlay_type"],
                    "detail": ov.get("description"),
                    "value_json": ov.get("raw_values"),
                    "sort_order": len(merged) + j,
                }
            )
        if findings_rows:
            repo.insert_findings(analysis_id, findings_rows)
    except Exception:
        pass
