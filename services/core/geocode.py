"""Address normalization and the geocoder seam (step A input).

Two concerns, cleanly separated:

1. :func:`normalize_address` - pure, deterministic string normalization used for
   display, for the request fingerprint, and to feed the geocoder. No network.
2. :class:`Geocoder` - a small protocol for turning a normalized address into a
   point with a confidence and provenance. The default implementation talks to
   the free US Census Bureau geocoder (no API key), but it is injected so the
   deterministic core never hard-codes a paid key and unit tests can supply a
   fake. When confidence is low or the address does not resolve, the geocoder
   returns ``None`` (or a ``low`` confidence) and the orchestrator degrades the
   analysis to ``insufficient_data`` rather than guessing.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol

from .repository import GeoPoint, SourceRef

# Common USPS street-suffix and directional abbreviations for light normalization.
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[.,]+")

_DIRECTIONALS = {
    "north": "N",
    "south": "S",
    "east": "E",
    "west": "W",
    "northeast": "NE",
    "northwest": "NW",
    "southeast": "SE",
    "southwest": "SW",
}

_SUFFIXES = {
    "street": "ST",
    "st": "ST",
    "avenue": "AVE",
    "ave": "AVE",
    "boulevard": "BLVD",
    "blvd": "BLVD",
    "road": "RD",
    "rd": "RD",
    "drive": "DR",
    "dr": "DR",
    "lane": "LN",
    "ln": "LN",
    "court": "CT",
    "ct": "CT",
    "place": "PL",
    "pl": "PL",
    "terrace": "TER",
    "way": "WAY",
    "circle": "CIR",
    "cir": "CIR",
    "highway": "HWY",
    "parkway": "PKWY",
}


def normalize_address(raw: str) -> str:
    """Deterministically normalize a free-form US street address.

    Uppercases, collapses whitespace, strips stray punctuation, and canonicalizes
    common directionals and street suffixes. This is intentionally conservative:
    it standardizes formatting for fingerprinting and geocoding without trying to
    validate or reorder the address. Pure and side-effect free.
    """
    if raw is None:
        return ""
    text = _PUNCT_RE.sub(" ", raw)
    text = _WHITESPACE_RE.sub(" ", text).strip().upper()
    if not text:
        return ""
    tokens = text.split(" ")
    out: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low in _DIRECTIONALS:
            out.append(_DIRECTIONALS[low])
        elif low in _SUFFIXES:
            out.append(_SUFFIXES[low])
        else:
            out.append(tok)
    return " ".join(out)


@dataclass
class GeocodeResult:
    """Outcome of geocoding one address."""

    point: Optional[GeoPoint]
    confidence: str  # high | medium | low
    matched_address: Optional[str]
    source: SourceRef

    @property
    def resolved(self) -> bool:
        return self.point is not None and self.confidence in ("high", "medium")


class Geocoder(Protocol):
    """Turns a (normalized) address into a point + confidence + provenance."""

    def geocode(self, address: str) -> GeocodeResult:
        ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CensusGeocoder:
    """Default geocoder backed by the free US Census Bureau geocoding service.

    No API key required. This is the only place in the core that performs network
    IO, and it sits behind the :class:`Geocoder` seam so it is trivially replaced
    in tests. It never raises on network failure: it returns a ``low`` confidence
    result so the orchestrator can degrade to ``insufficient_data``.
    """

    ENDPOINT = (
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
    )
    SOURCE_TITLE = "US Census Bureau Geocoding Services"

    def __init__(self, *, timeout_s: float = 8.0, benchmark: str = "Public_AR_Current"):
        self._timeout_s = timeout_s
        self._benchmark = benchmark

    def _source(self, data_status: str, confidence: str) -> SourceRef:
        return SourceRef(
            source_url=self.ENDPOINT,
            source_title=self.SOURCE_TITLE,
            source_layer=f"benchmark={self._benchmark}",
            retrieved_at=_now(),
            last_verified_at=_now(),
            confidence=confidence,
            data_status=data_status,
        )

    def geocode(self, address: str) -> GeocodeResult:
        # Imported here so the module imports cleanly even if httpx is absent in
        # a minimal environment; httpx is a declared dependency.
        try:
            import httpx
        except Exception:  # pragma: no cover - dependency guard
            return GeocodeResult(
                point=None,
                confidence="low",
                matched_address=None,
                source=self._source("unavailable", "low"),
            )

        params = {
            "address": address,
            "benchmark": self._benchmark,
            "format": "json",
        }
        # Census is the keyless primary. Transient failures (network / timeout /
        # 5xx / throttling under burst) are retried with exponential backoff
        # before we degrade, since the free Census service can rate-limit rapid
        # calls from one IP. A successful-but-empty response is a genuine no-match
        # and is not retried. For sustained volume, configure a paid fallback
        # geocoder (GOOGLE_MAPS_GEOCODING_API_KEY / MAPBOX_ACCESS_TOKEN).
        import time as _time

        payload = None
        last_error = True
        for attempt in range(3):
            try:
                resp = httpx.get(self.ENDPOINT, params=params, timeout=self._timeout_s)
                resp.raise_for_status()
                payload = resp.json()
                last_error = False
                break
            except Exception:
                last_error = True
                if attempt < 2:
                    _time.sleep(0.6 * (2 ** attempt))  # 0.6s, 1.2s backoff
                continue
        if last_error or payload is None:
            return GeocodeResult(
                point=None,
                confidence="low",
                matched_address=None,
                source=self._source("unavailable", "low"),
            )

        matches = (
            payload.get("result", {}).get("addressMatches", []) if payload else []
        )
        if not matches:
            return GeocodeResult(
                point=None,
                confidence="low",
                matched_address=None,
                source=self._source("current", "low"),
            )

        best = matches[0]
        coords = best.get("coordinates", {})
        lon = coords.get("x")
        lat = coords.get("y")
        if lon is None or lat is None:
            return GeocodeResult(
                point=None,
                confidence="low",
                matched_address=None,
                source=self._source("current", "low"),
            )
        # A single unambiguous match is high confidence; multiple candidates are
        # medium (we take the top one but flag the ambiguity via confidence).
        confidence = "high" if len(matches) == 1 else "medium"
        return GeocodeResult(
            point=GeoPoint(lon=float(lon), lat=float(lat)),
            confidence=confidence,
            matched_address=best.get("matchedAddress"),
            source=self._source("current", confidence),
        )


class GoogleGeocoder:
    """Optional Google Maps Geocoding API fallback (used only when a key is set).

    Never fabricates a point: an unresolved or low-precision result is returned
    as ``low`` confidence so the orchestrator degrades to ``insufficient_data``.
    location_type ROOFTOP / RANGE_INTERPOLATED is treated as reliable; the coarse
    GEOMETRIC_CENTER / APPROXIMATE geometries (and any partial_match) are low.
    """

    ENDPOINT = "https://maps.googleapis.com/maps/api/geocode/json"
    SOURCE_TITLE = "Google Maps Geocoding API"

    def __init__(self, api_key: str, *, timeout_s: float = 8.0):
        self._api_key = api_key
        self._timeout_s = timeout_s

    def _source(self, data_status: str, confidence: str) -> SourceRef:
        return SourceRef(
            source_url=self.ENDPOINT,
            source_title=self.SOURCE_TITLE,
            source_layer="geocode/json",
            retrieved_at=_now(),
            last_verified_at=_now(),
            confidence=confidence,
            data_status=data_status,
        )

    def geocode(self, address: str) -> GeocodeResult:
        try:
            import httpx
        except Exception:  # pragma: no cover - dependency guard
            return GeocodeResult(None, "low", None, self._source("unavailable", "low"))

        params = {"address": address, "key": self._api_key}
        try:
            resp = httpx.get(self.ENDPOINT, params=params, timeout=self._timeout_s)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return GeocodeResult(None, "low", None, self._source("unavailable", "low"))

        status = payload.get("status") if isinstance(payload, dict) else None
        results = payload.get("results", []) if isinstance(payload, dict) else []
        if status != "OK" or not results:
            return GeocodeResult(None, "low", None, self._source("current", "low"))

        best = results[0]
        geom = best.get("geometry", {}) or {}
        loc = geom.get("location", {}) or {}
        lat = loc.get("lat")
        lon = loc.get("lng")
        if lat is None or lon is None:
            return GeocodeResult(None, "low", None, self._source("current", "low"))

        location_type = geom.get("location_type")
        partial = bool(best.get("partial_match"))
        if partial or location_type in ("GEOMETRIC_CENTER", "APPROXIMATE"):
            confidence = "low"
        elif location_type == "ROOFTOP":
            confidence = "high" if len(results) == 1 else "medium"
        elif location_type == "RANGE_INTERPOLATED":
            confidence = "medium"
        else:
            confidence = "low"
        return GeocodeResult(
            point=GeoPoint(lon=float(lon), lat=float(lat)),
            confidence=confidence,
            matched_address=best.get("formatted_address"),
            source=self._source("current", confidence),
        )


class MapboxGeocoder:
    """Optional Mapbox Geocoding fallback (used only when an access token is set).

    Maps Mapbox ``relevance`` (0..1) to confidence and never fabricates a point:
    a weak or missing result is ``low`` confidence -> ``insufficient_data``.
    """

    ENDPOINT = "https://api.mapbox.com/geocoding/v5/mapbox.places"
    SOURCE_TITLE = "Mapbox Geocoding API"

    def __init__(self, access_token: str, *, timeout_s: float = 8.0):
        self._token = access_token
        self._timeout_s = timeout_s

    def _source(self, data_status: str, confidence: str) -> SourceRef:
        return SourceRef(
            source_url=self.ENDPOINT,
            source_title=self.SOURCE_TITLE,
            source_layer="mapbox.places",
            retrieved_at=_now(),
            last_verified_at=_now(),
            confidence=confidence,
            data_status=data_status,
        )

    def geocode(self, address: str) -> GeocodeResult:
        try:
            import httpx
        except Exception:  # pragma: no cover - dependency guard
            return GeocodeResult(None, "low", None, self._source("unavailable", "low"))

        from urllib.parse import quote

        url = f"{self.ENDPOINT}/{quote(address)}.json"
        params = {
            "access_token": self._token,
            "limit": "1",
            "country": "us",
            "types": "address",
        }
        try:
            resp = httpx.get(url, params=params, timeout=self._timeout_s)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return GeocodeResult(None, "low", None, self._source("unavailable", "low"))

        features = payload.get("features", []) if isinstance(payload, dict) else []
        if not features:
            return GeocodeResult(None, "low", None, self._source("current", "low"))

        best = features[0]
        center = best.get("center") or []
        if len(center) < 2:
            return GeocodeResult(None, "low", None, self._source("current", "low"))
        lon, lat = center[0], center[1]
        relevance = best.get("relevance")
        try:
            rel = float(relevance) if relevance is not None else 0.0
        except (TypeError, ValueError):
            rel = 0.0
        if rel >= 0.9:
            confidence = "high"
        elif rel >= 0.6:
            confidence = "medium"
        else:
            confidence = "low"
        return GeocodeResult(
            point=GeoPoint(lon=float(lon), lat=float(lat)),
            confidence=confidence,
            matched_address=best.get("place_name"),
            source=self._source("current", confidence),
        )


class NominatimGeocoder:
    """Keyless OpenStreetMap Nominatim geocoder (used as a fallback to Census).

    Census (the keyless primary) intermittently returns empty bodies under load
    and has US address-coverage gaps; Nominatim covers those cases at no cost and
    with no API key, so the request path is not a single point of failure when no
    paid geocoder key is configured. Confidence is derived from Nominatim's
    ``place_rank`` / ``addresstype`` (a house/building match is high; a street is
    medium; anything coarser is low). Never fabricates: a coarse or missing result
    is low confidence, so the orchestrator degrades to ``insufficient_data``.

    Note: Nominatim's usage policy caps bulk use (~1 req/s) and requires an
    identifying User-Agent. It is a FALLBACK here (only runs when Census does not
    resolve), so volume stays low; for heavy production traffic set a paid key
    (GOOGLE_MAPS_GEOCODING_API_KEY / MAPBOX_ACCESS_TOKEN) instead.
    """

    ENDPOINT = "https://nominatim.openstreetmap.org/search"
    SOURCE_TITLE = "OpenStreetMap Nominatim"

    def __init__(self, *, timeout_s: float = 8.0, user_agent: Optional[str] = None):
        self._timeout_s = timeout_s
        self._user_agent = user_agent or os.environ.get(
            "NOMINATIM_USER_AGENT", "ADU-Atlas-API/1.0 (+https://adu-atlas-api.onrender.com)"
        )

    def _source(self, data_status: str, confidence: str) -> SourceRef:
        return SourceRef(
            source_url=self.ENDPOINT,
            source_title=self.SOURCE_TITLE,
            source_layer="nominatim/search",
            retrieved_at=_now(),
            last_verified_at=_now(),
            confidence=confidence,
            data_status=data_status,
        )

    def geocode(self, address: str) -> GeocodeResult:
        try:
            import httpx
        except Exception:  # pragma: no cover - dependency guard
            return GeocodeResult(None, "low", None, self._source("unavailable", "low"))

        params = {
            "q": address,
            "format": "jsonv2",
            "limit": "1",
            "addressdetails": "1",
            "countrycodes": "us",
        }
        headers = {"User-Agent": self._user_agent}
        try:
            resp = httpx.get(self.ENDPOINT, params=params, headers=headers, timeout=self._timeout_s)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return GeocodeResult(None, "low", None, self._source("unavailable", "low"))

        if not isinstance(payload, list) or not payload:
            return GeocodeResult(None, "low", None, self._source("current", "low"))

        best = payload[0]
        try:
            lat = float(best["lat"])
            lon = float(best["lon"])
        except (KeyError, TypeError, ValueError):
            return GeocodeResult(None, "low", None, self._source("current", "low"))

        # place_rank is Nominatim's specificity signal: 30 == house/building.
        try:
            rank = int(best.get("place_rank", 0))
        except (TypeError, ValueError):
            rank = 0
        addresstype = str(best.get("addresstype") or "").lower()
        if rank >= 30 or addresstype in ("building", "house", "address"):
            confidence = "high"
        elif rank >= 26:  # street / road level
            confidence = "medium"
        else:  # neighbourhood, city, postcode, etc. - not precise enough
            confidence = "low"
        return GeocodeResult(
            point=GeoPoint(lon=lon, lat=lat),
            confidence=confidence,
            matched_address=best.get("display_name"),
            source=self._source("current", confidence),
        )


class ChainedGeocoder:
    """Try a primary geocoder, then fall back to others until one resolves.

    A result is accepted (chain stops) only when ``resolved`` is True (a point at
    high/medium confidence). If no provider resolves, the best-effort result from
    the first provider that at least produced a source is returned so the
    orchestrator degrades to ``insufficient_data`` - a point is never fabricated.
    """

    def __init__(self, primary: "Geocoder", *fallbacks: "Geocoder"):
        self._providers = [primary, *fallbacks]

    def geocode(self, address: str) -> GeocodeResult:
        first: Optional[GeocodeResult] = None
        for provider in self._providers:
            result = provider.geocode(address)
            if first is None:
                first = result
            if result.resolved:
                return result
        # Nothing resolved: return the primary's (low/unavailable) result so the
        # caller degrades honestly rather than guessing.
        assert first is not None  # at least the primary always runs
        return first


def build_default_geocoder(*, timeout_s: float = 8.0) -> "Geocoder":
    """Build the request-path geocoder chain.

    Census (keyless, US-gov) is primary. A keyless OpenStreetMap Nominatim
    fallback follows so the path is not a single point of failure when Census
    returns empty / rate-limits (unless ``NOMINATIM_DISABLED`` is set). Google
    and/or Mapbox are appended when ``GOOGLE_MAPS_GEOCODING_API_KEY`` /
    ``MAPBOX_ACCESS_TOKEN`` are set - the recommended geocoders for heavy
    production traffic. Order = Census -> Nominatim -> Google -> Mapbox.
    """
    fallbacks: list[Geocoder] = []
    if not os.environ.get("NOMINATIM_DISABLED"):
        fallbacks.append(NominatimGeocoder(timeout_s=timeout_s))
    google_key = os.environ.get("GOOGLE_MAPS_GEOCODING_API_KEY")
    if google_key:
        fallbacks.append(GoogleGeocoder(google_key, timeout_s=timeout_s))
    mapbox_token = os.environ.get("MAPBOX_ACCESS_TOKEN")
    if mapbox_token:
        fallbacks.append(MapboxGeocoder(mapbox_token, timeout_s=timeout_s))
    primary = CensusGeocoder(timeout_s=timeout_s)
    if not fallbacks:
        return primary
    return ChainedGeocoder(primary, *fallbacks)


class StaticGeocoder:
    """A deterministic, network-free geocoder for tests and offline demos.

    Maps normalized addresses to points from an in-memory table. Any unmapped
    address resolves to ``low`` confidence with no point.
    """

    SOURCE_TITLE = "Static test geocoder"

    def __init__(self, table: dict[str, GeoPoint]):
        # Keys are normalized addresses.
        self._table = {normalize_address(k): v for k, v in table.items()}

    def geocode(self, address: str) -> GeocodeResult:
        key = normalize_address(address)
        point = self._table.get(key)
        source = SourceRef(
            source_url="urn:aduatlas:static-geocoder",
            source_title=self.SOURCE_TITLE,
            retrieved_at=_now(),
            confidence="high" if point else "low",
            data_status="current",
        )
        return GeocodeResult(
            point=point,
            confidence="high" if point else "low",
            matched_address=key if point else None,
            source=source,
        )
