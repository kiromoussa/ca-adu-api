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
    CachingGeocoder,
    CensusGeocoder,
    ChainedGeocoder,
    GeocodeResult,
    GoogleGeocoder,
    MapboxGeocoder,
    NominatimGeocoder,
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


# ---- CachingGeocoder -------------------------------------------------------
def test_caching_geocoder_serves_resolved_from_cache():
    inner = _Fake(_resolved())
    g = CachingGeocoder(inner)
    a = g.geocode(ADDR)
    b = g.geocode(ADDR)  # second call served from cache
    assert a.resolved and b.resolved
    assert inner.calls == 1  # underlying geocoder hit only once


def test_caching_geocoder_does_not_cache_unresolved():
    inner = _Fake(_unresolved())
    g = CachingGeocoder(inner)
    g.geocode(ADDR)
    g.geocode(ADDR)  # retried, not served from cache
    assert inner.calls == 2  # a transient failure is never stuck in cache


def test_caching_geocoder_evicts_when_full():
    inner = _Fake(_resolved())
    g = CachingGeocoder(inner, max_entries=1)
    g.geocode("addr one")
    g.geocode("addr two")  # evicts "addr one"
    inner.calls = 0
    g.geocode("addr one")  # was evicted -> re-fetched
    assert inner.calls == 1


# ---- build_default_geocoder (env-driven) ----------------------------------
def _unwrap_cache(g):
    """Peel the default CachingGeocoder wrapper to assert on the inner chain."""
    return g._inner if isinstance(g, CachingGeocoder) else g


def test_default_geocoder_chains_census_then_nominatim_with_no_keys(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_GEOCODING_API_KEY", raising=False)
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("NOMINATIM_DISABLED", raising=False)
    monkeypatch.delenv("GEOCODE_CACHE_DISABLED", raising=False)
    g = build_default_geocoder()
    assert isinstance(g, CachingGeocoder)  # cache wraps by default
    inner = _unwrap_cache(g)
    # With no paid keys, the path is Census -> Nominatim (both keyless, not a
    # single point of failure).
    assert isinstance(inner, ChainedGeocoder)
    assert isinstance(inner._providers[0], CensusGeocoder)
    assert isinstance(inner._providers[1], NominatimGeocoder)
    assert len(inner._providers) == 2


def test_default_geocoder_is_pure_census_when_fallbacks_and_cache_disabled(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_GEOCODING_API_KEY", raising=False)
    monkeypatch.delenv("MAPBOX_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("NOMINATIM_DISABLED", "1")
    monkeypatch.setenv("GEOCODE_CACHE_DISABLED", "1")
    g = build_default_geocoder()
    assert isinstance(g, CensusGeocoder)


def test_paid_provider_is_primary_when_key_present(monkeypatch):
    # Accuracy-first: a paid provider must lead so an inaccurate Census point can
    # never short-circuit the precise result. Order = Google, Mapbox, Census, Nominatim.
    monkeypatch.setenv("GOOGLE_MAPS_GEOCODING_API_KEY", "gkey")
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "mtok")
    monkeypatch.delenv("NOMINATIM_DISABLED", raising=False)
    monkeypatch.delenv("GEOCODE_CACHE_DISABLED", raising=False)
    g = build_default_geocoder()
    inner = _unwrap_cache(g)
    assert isinstance(inner, ChainedGeocoder)
    kinds = [type(p).__name__ for p in inner._providers]
    assert kinds == ["GoogleGeocoder", "MapboxGeocoder", "CensusGeocoder", "NominatimGeocoder"]


def test_mapbox_is_primary_when_only_mapbox_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_GEOCODING_API_KEY", raising=False)
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "mtok")
    monkeypatch.delenv("NOMINATIM_DISABLED", raising=False)
    monkeypatch.delenv("GEOCODE_CACHE_DISABLED", raising=False)
    inner = _unwrap_cache(build_default_geocoder())
    kinds = [type(p).__name__ for p in inner._providers]
    assert kinds[0] == "MapboxGeocoder"  # paid provider leads
    assert kinds == ["MapboxGeocoder", "CensusGeocoder", "NominatimGeocoder"]


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


# ---- Nominatim parsing -----------------------------------------------------
def _nominatim_get(payload):
    def _get(url, params=None, headers=None, timeout=None):
        return _Resp(payload)
    return _get


def test_nominatim_building_is_high(monkeypatch):
    payload = [{"lat": "32.7112", "lon": "-117.1540", "place_rank": 30,
                "addresstype": "building", "display_name": "550 Park Blvd, San Diego"}]
    monkeypatch.setattr(httpx, "get", _nominatim_get(payload))
    out = NominatimGeocoder().geocode(ADDR)
    assert out.confidence == "high" and out.resolved is True
    assert out.point is not None


def test_nominatim_street_level_is_medium(monkeypatch):
    payload = [{"lat": "34.0", "lon": "-118.0", "place_rank": 26,
                "addresstype": "road", "display_name": "Main St"}]
    monkeypatch.setattr(httpx, "get", _nominatim_get(payload))
    out = NominatimGeocoder().geocode(ADDR)
    assert out.confidence == "medium" and out.resolved is True


def test_nominatim_city_level_is_low_and_unresolved(monkeypatch):
    payload = [{"lat": "34.0", "lon": "-118.0", "place_rank": 16,
                "addresstype": "city", "display_name": "Los Angeles"}]
    monkeypatch.setattr(httpx, "get", _nominatim_get(payload))
    out = NominatimGeocoder().geocode(ADDR)
    # Coarse match -> low -> not resolved (no false precision).
    assert out.confidence == "low" and out.resolved is False


def test_nominatim_empty_list_no_point(monkeypatch):
    monkeypatch.setattr(httpx, "get", _nominatim_get([]))
    out = NominatimGeocoder().geocode(ADDR)
    assert out.point is None and out.confidence == "low"


def test_nominatim_network_error_degrades_without_fabricating(monkeypatch):
    def boom(url, params=None, headers=None, timeout=None):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "get", boom)
    out = NominatimGeocoder().geocode(ADDR)
    assert out.point is None and out.source.data_status == "unavailable"
