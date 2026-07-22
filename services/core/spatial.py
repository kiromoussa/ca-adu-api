"""Spatial helpers: unit conversion and the approximate-envelope assembly.

The heavy geometry (ST_Contains / ST_Intersects parcel matching, the zoning
spatial join, overlay intersection, and the inward ST_Buffer used for the
envelope) executes in PostGIS behind the :class:`FeasibilityRepository` seam.
What lives here is the deterministic, network-free glue:

- exact foot <-> meter conversion (the correctness-critical bit that is unit
  tested), and
- assembly of the ``ApproximateEnvelope`` object from a PostGIS buffered area,
  including honest downgrading to a limitation when parcel orientation
  (front/side/rear) is unknown, and never asserting easements, slopes, utilities,
  trees, HOA, title, or survey facts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .repository import BufferedArea, SourceRef


def _env_float_module(name: str, default: float) -> float:
    """Read a float from the environment, falling back to default on any error."""
    try:
        raw = os.environ.get(name)
        return float(raw) if raw is not None else default
    except (TypeError, ValueError):
        return default

# International foot definition (exact). 1 ft == 0.3048 m, 1 m == 1/0.3048 ft.
FEET_PER_METER = 1.0 / 0.3048            # ~= 3.280839895
METERS_PER_FOOT = 0.3048                 # exact
SQFT_PER_SQM = FEET_PER_METER ** 2       # ~= 10.76391041671
SQM_PER_SQFT = METERS_PER_FOOT ** 2      # ~= 0.09290304

# Default spatial tolerance for parcel matching. ST_Contains is tried first; the
# ST_DWithin fallback (nearest parcel within this radius, ordered by distance)
# handles the common case where an address geocodes to the street centerline /
# right-of-way rather than onto the parcel polygon. Measured need: interpolated
# geocodes land ~8-20 m off the nearest parcel (street half-width + setback), so
# 5 m was far too small and produced spurious parcel_unmatched results in cities
# with wider streets (e.g. San Jose). 25 m comfortably covers the ROW case while
# the distance ordering still selects the correct (nearest) parcel, so it does not
# reach across an arterial to the wrong block. Override with PARCEL_TOLERANCE_M.
DEFAULT_PARCEL_TOLERANCE_M = _env_float_module("PARCEL_TOLERANCE_M", 25.0)

# Envelope label, verbatim per the OpenAPI ApproximateEnvelope.label default.
ENVELOPE_LABEL = "approximate conceptual envelope"


def feet_to_meters(feet: float) -> float:
    """Convert feet to meters (exact international foot)."""
    return feet * METERS_PER_FOOT


def meters_to_feet(meters: float) -> float:
    """Convert meters to feet (exact international foot)."""
    return meters * FEET_PER_METER


def sqm_to_sqft(sqm: float) -> float:
    """Convert square meters to square feet."""
    return sqm * SQFT_PER_SQM


def sqft_to_sqm(sqft: float) -> float:
    """Convert square feet to square meters."""
    return sqft * SQM_PER_SQFT


@dataclass
class EnvelopeResult:
    """Assembled approximate conceptual envelope (mirrors OpenAPI schema)."""

    available: bool
    label: str = ENVELOPE_LABEL
    buildable_area_sqft: Optional[float] = None
    method: Optional[str] = None
    orientation_known: bool = False
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    source: Optional[SourceRef] = None

    @property
    def needs_review(self) -> bool:
        """Orientation-unknown envelopes must not report false precision."""
        return self.available and not self.orientation_known


def choose_uniform_inset_ft(
    side_setback_ft: Optional[float],
    rear_setback_ft: Optional[float],
    front_setback_ft: Optional[float],
) -> float:
    """Pick a single conservative inset (feet) when edge orientation is unknown.

    With no way to tell which parcel edge is front/side/rear, a uniform inward
    buffer is used and the largest known applicable setback is chosen so the
    result is conservative (never over-optimistic about buildable area). Falls
    back to the AB 2221 side/rear ceiling of 4 ft when nothing is known.
    """
    candidates = [
        v for v in (side_setback_ft, rear_setback_ft, front_setback_ft) if v is not None
    ]
    if not candidates:
        return 4.0
    return max(candidates)


def build_envelope(
    buffered: BufferedArea,
    *,
    inset_ft: float,
    orientation_known: bool,
) -> EnvelopeResult:
    """Assemble an :class:`EnvelopeResult` from a PostGIS buffered area.

    ``buffered.buffered_area_sqm`` is a true metric area (measured on the
    geography type). We convert to square feet and attach explicit assumptions
    and limitations. When ``orientation_known`` is False the result stays
    available but is flagged as needing professional review, per spec.
    """
    if not buffered.available or buffered.buffered_area_sqm is None:
        return EnvelopeResult(
            available=False,
            source=buffered.source,
            limitations=[
                "Buildable envelope could not be computed for this parcel "
                "(parcel geometry unavailable or too small after setbacks)."
            ],
        )

    area_sqft = round(sqm_to_sqft(buffered.buffered_area_sqm), 1)
    assumptions = [
        f"Uniform inward setback of {inset_ft:g} ft applied to the parcel "
        "polygon as an approximation.",
        "Buildable area is measured on the parcel geography; it does not model "
        "the primary dwelling footprint, lot coverage limits, or floor-area "
        "ratio.",
    ]
    limitations = [
        "Approximate conceptual envelope only. Not a survey and not a site plan.",
        "Does not account for easements, slopes, utilities, trees, HOA, title, "
        "or existing structures.",
    ]
    if not orientation_known:
        limitations.append(
            "Parcel edge orientation (front / side / rear) is unknown; a single "
            "uniform setback was applied. Per-edge setbacks require professional "
            "review."
        )
    method = (
        f"PostGIS ST_Buffer inward by {feet_to_meters(inset_ft):.4f} m "
        f"({inset_ft:g} ft) on the parcel geography, then ST_Area."
    )
    return EnvelopeResult(
        available=True,
        buildable_area_sqft=area_sqft,
        method=method,
        orientation_known=orientation_known,
        assumptions=assumptions,
        limitations=limitations,
        source=buffered.source,
    )
