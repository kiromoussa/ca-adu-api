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
        try:
            resp = httpx.get(self.ENDPOINT, params=params, timeout=self._timeout_s)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
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
