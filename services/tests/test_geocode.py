"""Geocoder robustness tests (item 4): Census retry, provider fallback chain,
and honest degradation. No network: httpx.get is monkeypatched and the fallback
geocoders are exercised through fakes.

The invariant under test everywhere: a low-confidence or no-match outcome yields
a result with NO point (so the orchestrator degrades to insufficient_data) - a
point is never fabricated.
"""

from __future__ import annotations

import httpx

from services.core.geocode import (
    CensusGeocoder,
    ChainedGeocoder,
    GeocodeResult,
    GoogleGeocoder,
    MapboxGeocoder,
    build_default_geocoder,
)
from services.core.repository import GeoPoint, SourceRef


ADDR = "1234 S MAIN ST, LOS ANGELES, CA 90015"


class _Resp:
    def __init__(self, payload, *, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        return self._payload


def _src(conf):
    return SourceRef(source_url="urn:test", source_title="test", confidence=conf,
                     data_status="current")


class _Fake:
    """A Geocoder that returns a canned result and counts calls."""

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def geocode(self, address):
        self.calls += 1
        return self.result


def _resolved():
    return GeocodeResult(GeoPoint(-118.27, 34.03), "high", ADDR, _src("high"))


def _unresolved():
    return GeocodeResult(None, "low", None, _src("low"))


# ---- ChainedGeocoder ------------------------------------------------------
def test_chain_stops_at_primary_when_it_resolves():
    primary = _Fake(_resolved())
    fallback = _Fake(_resolved())
    out = ChainedGeocoder(primary, fallback).geocode(ADDR)
    assert out.resolved is True
    assert primary.calls == 1 and fallback.calls == 0  # fallback not consulted


def test_chain_falls_back_when_primary_unresolved():
    primary = _Fake(_unresolved())
    fallback = _Fake(_resolved())
    out = ChainedGeocoder(primary, fallback).geocode(ADDR)
    assert out.resolved is True and out.point is not None
    assert primary.calls == 1 and fallback.calls == 1


def test_chain_returns_primary_when_none_resolve_and_never_fabricates():
    primary = _Fake(_unresolved())
    fallback = _Fake(_unresolved())
    out = ChainedGeocoder(primary, fallback).geocode(ADDR)
    assert out.resolved is False
    assert out.point is None  # no fabricated point


# ---- build_default_geocoder (env-driven) ----------------------------------
def test_default_geocoder_is_census_with_no_keys(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_GEOCODING_API_KEY", raising=False)
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)
    g = build_default_geocoder()
    assert isinstance(g, CensusGeocoder)


def test_default_geocoder_adds_fallbacks_when_keys_present(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_GEOCODING_API_KEY", "gkey")
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "mtok")
    g = build_default_geocoder()
    assert isinstance(g, ChainedGeocoder)
    assert len(g._providers) == 3  # census + google + mapbox


# ---- Census retry-once -----------------------------------------------------
def _census_ok_payload():
    return {"result": {"addressMatches": [
        {"coordinates": {"x": -118.27, "y": 34.03}, "matchedAddress": ADDR},
    ]}}


def test_census_retries_once_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky_get(url, params=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("transient")
        return _Resp(_census_ok_payload())

    monkeypatch.setattr(httpx, "get", flaky_get)
    out = CensusGeocoder().geocode(ADDR)
    assert calls["n"] == 2  # one retry
    assert out.resolved is True and out.point is not None


def test_census_gives_up_after_retry_without_fabricating(monkeypatch):
    calls = {"n": 0}

    def always_fail(url, params=None, timeout=None):
        calls["n"] += 1
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", always_fail)
    out = CensusGeocoder().geocode(ADDR)
    assert calls["n"] == 3  # 3 attempts with exponential backoff, then degraded
    assert out.point is None and out.confidence == "low"
    assert out.source.data_status == "unavailable"


def test_census_empty_match_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def empty_get(url, params=None, timeout=None):
        calls["n"] += 1
        return _Resp({"result": {"addressMatches": []}})

    monkeypatch.setattr(httpx, "get", empty_get)
    out = CensusGeocoder().geocode(ADDR)
    assert calls["n"] == 1  # a clean no-match is not a transient failure
    assert out.point is None


# ---- Google parsing --------------------------------------------------------
def _google_get(payload):
    def _get(url, params=None, timeout=None):
        return _Resp(payload)
    return _get


def test_google_rooftop_is_high(monkeypatch):
    payload = {"status": "OK", "results": [
        {"geometry": {"location": {"lat": 34.03, "lng": -118.27},
                      "location_type": "ROOFTOP"},
         "formatted_address": ADDR},
    ]}
    monkeypatch.setattr(httpx, "get", _google_get(payload))
    out = GoogleGeocoder("k").geocode(ADDR)
    assert out.confidence == "high" and out.resolved is True


def test_google_approximate_and_partial_are_low(monkeypatch):
    payload = {"status": "OK", "results": [
        {"geometry": {"location": {"lat": 34.0, "lng": -118.0},
                      "location_type": "APPROXIMATE"},
         "partial_match": True, "formatted_address": "LOS ANGELES, CA"},
    ]}
    monkeypatch.setattr(httpx, "get", _google_get(payload))
    out = GoogleGeocoder("k").geocode(ADDR)
    # Coarse geometry -> low confidence -> unresolved (no false precision).
    assert out.confidence == "low" and out.resolved is False


def test_google_zero_results_is_low_no_point(monkeypatch):
    monkeypatch.setattr(httpx, "get", _google_get({"status": "ZERO_RESULTS", "results": []}))
    out = GoogleGeocoder("k").geocode(ADDR)
    assert out.point is None and out.confidence == "low"


# ---- Mapbox parsing --------------------------------------------------------
def _mapbox_get(payload):
    def _get(url, params=None, timeout=None):
        return _Resp(payload)
    return _get


def test_mapbox_high_relevance_resolves(monkeypatch):
    payload = {"features": [
        {"center": [-118.27, 34.03], "relevance": 0.98, "place_name": ADDR},
    ]}
    monkeypatch.setattr(httpx, "get", _mapbox_get(payload))
    out = MapboxGeocoder("t").geocode(ADDR)
    assert out.confidence == "high" and out.point is not None


def test_mapbox_low_relevance_is_low(monkeypatch):
    payload = {"features": [
        {"center": [-118.0, 34.0], "relevance": 0.4, "place_name": "somewhere"},
    ]}
    monkeypatch.setattr(httpx, "get", _mapbox_get(payload))
    out = MapboxGeocoder("t").geocode(ADDR)
    assert out.confidence == "low" and out.resolved is False


def test_mapbox_no_features_no_point(monkeypatch):
    monkeypatch.setattr(httpx, "get", _mapbox_get({"features": []}))
    out = MapboxGeocoder("t").geocode(ADDR)
    assert out.point is None
