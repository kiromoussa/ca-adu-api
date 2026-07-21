"""Spatial tests: exact foot<->meter conversion and envelope assembly."""

from __future__ import annotations

import math

from services.core.repository import BufferedArea, SourceRef
from services.core.spatial import (
    build_envelope,
    choose_uniform_inset_ft,
    feet_to_meters,
    meters_to_feet,
    sqft_to_sqm,
    sqm_to_sqft,
)


def test_feet_meter_conversion_is_exact():
    # International foot: exactly 0.3048 m.
    assert feet_to_meters(1) == 0.3048
    assert feet_to_meters(4) == 4 * 0.3048
    assert math.isclose(meters_to_feet(1), 3.280839895013123, rel_tol=1e-12)


def test_conversion_round_trips():
    for ft in (0.0, 4.0, 16.0, 100.0, 1234.5):
        assert math.isclose(meters_to_feet(feet_to_meters(ft)), ft, rel_tol=1e-12)


def test_area_conversion():
    assert math.isclose(sqm_to_sqft(1.0), 10.763910416709722, rel_tol=1e-12)
    assert math.isclose(sqft_to_sqm(sqm_to_sqft(50.0)), 50.0, rel_tol=1e-12)


def test_choose_uniform_inset_prefers_max_known_setback():
    assert choose_uniform_inset_ft(4.0, 5.0, None) == 5.0
    assert choose_uniform_inset_ft(None, None, None) == 4.0  # AB 2221 fallback


def _src():
    return SourceRef(source_url="https://example/parcel", source_title="Parcel GIS")


def test_build_envelope_converts_area_and_flags_orientation_unknown():
    buffered = BufferedArea(available=True, buffered_area_sqm=100.0,
                            orientation_known=False, inset_m=1.2192, source=_src())
    env = build_envelope(buffered, inset_ft=4.0, orientation_known=False)
    assert env.available is True
    assert math.isclose(env.buildable_area_sqft, round(sqm_to_sqft(100.0), 1), rel_tol=1e-9)
    # Orientation unknown -> needs review + explicit limitation, no false precision.
    assert env.needs_review is True
    assert any("orientation" in lim.lower() for lim in env.limitations)
    assert env.label == "approximate conceptual envelope"


def test_build_envelope_unavailable_when_no_buffer():
    buffered = BufferedArea(available=False, inset_m=1.2192)
    env = build_envelope(buffered, inset_ft=4.0, orientation_known=False)
    assert env.available is False
    assert env.buildable_area_sqft is None
    assert env.needs_review is False
