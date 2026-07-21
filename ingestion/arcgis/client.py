"""Robust ArcGIS REST client for the ADU Atlas ingestion pipeline.

This is the single HTTP entrypoint every GIS ingester goes through. It talks to
ArcGIS ``MapServer`` / ``FeatureServer`` endpoints and provides:

- service metadata            ``{service}?f=pjson``
- layer listing               ``{service}/layers?f=pjson``
- single layer metadata       ``{service}/{layer_id}?f=pjson``
- feature query               ``{service}/{layer_id}/query?...&f=geojson``
- record count                ``.../query?returnCountOnly=true``
- transparent pagination      via ``resultOffset`` / ``resultRecordCount``
- retries + exponential backoff (tenacity) on 429 / 5xx / transport errors
- polite rate limiting        (minimum interval between requests)
- ETag / Last-Modified caching with conditional requests (304 -> cached body)

Design notes
------------
* ``f=geojson`` output from ArcGIS is always WGS84 (EPSG:4326) per the GeoJSON
  spec, regardless of the layer's native spatial reference. We additionally pass
  ``outSR=4326`` so services that honour it are explicit. Downstream inserts
  therefore always ``ST_SetSRID(..., 4326)``.
* ArcGIS returns errors as an HTTP 200 body ``{"error": {...}}``. Those are
  detected and raised as :class:`ArcGISQueryError` so a bad query never looks
  like an empty result set.
* A genuinely *unavailable* source (network failure, repeated 5xx, timeout)
  raises :class:`ArcGISUnavailableError`. Callers use this to distinguish
  "source unavailable" from "queried fine, zero features" - a trust
  non-negotiable for overlay lookups.

No secrets are read here. No LLM. Deterministic HTTP only.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator
from urllib.parse import urlsplit

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 "
    "adu-atlas-ingestion/0.1 (+https://github.com/ca-adu-api)"
)

# ArcGIS ``esriFieldType*`` -> coarse python category, used for field discovery.
_GEOMETRY_FIELD_TYPE = "esriFieldTypeGeometry"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class ArcGISError(Exception):
    """Base class for all ArcGIS client errors."""


class ArcGISUnavailableError(ArcGISError):
    """The source could not be reached (network / timeout / repeated 5xx).

    Distinct from an empty-but-successful query. Overlay ingesters translate
    this into ``data_status = 'unavailable'`` rather than "no feature".
    """


class ArcGISQueryError(ArcGISError):
    """ArcGIS returned a structured error envelope (HTTP 200 with ``error``)."""

    def __init__(self, message: str, *, code: int | None = None, details: Any = None):
        super().__init__(message)
        self.code = code
        self.details = details


class LayerNotFoundError(ArcGISError):
    """A requested / discovered layer does not exist in the service."""


# Internal marker used to drive tenacity retries on transient HTTP failures.
class _RetryableHTTP(Exception):
    pass


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LayerRef:
    """A resolved layer within a service."""

    service_url: str
    layer_id: int
    name: str
    geometry_type: str | None = None
    fields: tuple[str, ...] = ()
    max_record_count: int | None = None
    spatial_reference_wkid: int | None = None

    @property
    def query_url(self) -> str:
        return f"{self.service_url.rstrip('/')}/{self.layer_id}/query"

    def has_field(self, name: str) -> bool:
        lname = name.lower()
        return any(f.lower() == lname for f in self.fields)

    def first_field(self, candidates: Iterable[str]) -> str | None:
        """Return the first candidate field name present (case-insensitive),
        preserving the layer's own casing."""
        lower_map = {f.lower(): f for f in self.fields}
        for cand in candidates:
            hit = lower_map.get(cand.lower())
            if hit is not None:
                return hit
        return None


@dataclass
class ServiceMetadata:
    """Parsed ``{service}?f=pjson`` metadata plus the raw payload."""

    service_url: str
    raw: dict[str, Any]
    current_version: Any = None
    max_record_count: int | None = None
    layers: list[dict[str, Any]] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None


@dataclass
class _CacheEntry:
    etag: str | None
    last_modified: str | None
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class ArcGISClient:
    """Synchronous ArcGIS REST client built on ``httpx``.

    Parameters
    ----------
    timeout:
        Per-request timeout in seconds.
    user_agent:
        UA string. Some public services (behind Cloudflare / WAF) reject empty
        or obviously-bot UAs, so a browser-like default is used.
    rate_limit_seconds:
        Minimum wall-clock interval enforced between outbound requests.
    max_retries:
        Attempts for transient failures (429 / 5xx / transport errors).
    cache_enabled:
        Enable in-memory ETag / Last-Modified conditional caching.
    """

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        user_agent: str = _DEFAULT_UA,
        rate_limit_seconds: float = 0.5,
        max_retries: int = 4,
        cache_enabled: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout = timeout
        self._rate_limit_seconds = max(0.0, rate_limit_seconds)
        self._max_retries = max(1, max_retries)
        self._cache_enabled = cache_enabled
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._last_request_at = 0.0
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,
        )

    # -- context manager -------------------------------------------------
    def __enter__(self) -> "ArcGISClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- rate limiting ---------------------------------------------------
    def _throttle(self) -> None:
        if self._rate_limit_seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._rate_limit_seconds - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    # -- low level GET ---------------------------------------------------
    def _get(
        self,
        url: str,
        params: dict[str, Any],
        *,
        use_cache: bool = False,
    ) -> dict[str, Any]:
        """GET ``url`` with retry/backoff, rate limiting and optional caching.

        Returns the parsed JSON body. Raises :class:`ArcGISUnavailableError`
        on unrecoverable transport failures and :class:`ArcGISQueryError` on an
        ArcGIS error envelope.
        """
        cache_key = None
        conditional_headers: dict[str, str] = {}
        if use_cache and self._cache_enabled:
            cache_key = self._cache_key(url, params)
            entry = self._cache.get(cache_key)
            if entry is not None:
                if entry.etag:
                    conditional_headers["If-None-Match"] = entry.etag
                if entry.last_modified:
                    conditional_headers["If-Modified-Since"] = entry.last_modified

        @retry(
            retry=retry_if_exception_type(_RetryableHTTP),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.75, min=0.75, max=20),
            reraise=True,
        )
        def _do_request() -> httpx.Response:
            self._throttle()
            try:
                resp = self._client.get(url, params=params, headers=conditional_headers)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                logger.warning("ArcGIS transport error for %s: %s", url, exc)
                raise _RetryableHTTP(str(exc)) from exc
            if resp.status_code in (429, 500, 502, 503, 504):
                logger.warning(
                    "ArcGIS transient status %s for %s", resp.status_code, url
                )
                raise _RetryableHTTP(f"status {resp.status_code}")
            return resp

        try:
            resp = _do_request()
        except _RetryableHTTP as exc:
            raise ArcGISUnavailableError(
                f"ArcGIS source unavailable after {self._max_retries} attempts: {url}"
            ) from exc

        # Conditional cache hit: reuse the previously stored payload.
        if resp.status_code == 304 and cache_key is not None:
            entry = self._cache.get(cache_key)
            if entry is not None:
                logger.debug("ArcGIS 304 cache hit for %s", url)
                return entry.payload

        if resp.status_code >= 400:
            raise ArcGISUnavailableError(
                f"ArcGIS returned HTTP {resp.status_code} for {url}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            raise ArcGISUnavailableError(
                f"ArcGIS returned non-JSON body for {url}"
            ) from exc

        # ArcGIS error envelope (HTTP 200 with an ``error`` object).
        if isinstance(body, dict) and "error" in body and body.get("error"):
            err = body["error"]
            raise ArcGISQueryError(
                str(err.get("message", "ArcGIS query error")),
                code=err.get("code"),
                details=err.get("details"),
            )

        if use_cache and cache_key is not None and isinstance(body, dict):
            self._cache[cache_key] = _CacheEntry(
                etag=resp.headers.get("ETag"),
                last_modified=resp.headers.get("Last-Modified"),
                payload=body,
            )
        # Stash the most recent validators so callers can persist them onto
        # source_registry (etag / last_modified columns).
        self.last_etag = resp.headers.get("ETag")
        self.last_modified = resp.headers.get("Last-Modified")
        return body

    @staticmethod
    def _cache_key(url: str, params: dict[str, Any]) -> str:
        items = sorted((str(k), str(v)) for k, v in params.items())
        return url + "?" + "&".join(f"{k}={v}" for k, v in items)

    # -- prime cache from persisted validators ---------------------------
    def seed_validators(
        self, service_url: str, *, etag: str | None, last_modified: str | None
    ) -> None:
        """Seed the cache with previously persisted ETag / Last-Modified so the
        next metadata fetch can send a conditional request. The payload is empty
        until a real 200 is received (a 304 with no stored payload falls through
        to a normal fetch)."""
        if not self._cache_enabled or (not etag and not last_modified):
            return
        key = self._cache_key(f"{service_url.rstrip('/')}", {"f": "pjson"})
        existing = self._cache.get(key)
        if existing is None:
            # No stored payload yet; skip - a bare 304 could not be served.
            return
        existing.etag = etag or existing.etag
        existing.last_modified = last_modified or existing.last_modified

    # -- metadata --------------------------------------------------------
    def service_metadata(self, service_url: str) -> ServiceMetadata:
        """Fetch ``{service_url}?f=pjson`` and return parsed metadata."""
        service_url = service_url.rstrip("/")
        body = self._get(service_url, {"f": "pjson"}, use_cache=True)
        sr = body.get("spatialReference") or {}
        return ServiceMetadata(
            service_url=service_url,
            raw=body,
            current_version=body.get("currentVersion"),
            max_record_count=body.get("maxRecordCount"),
            layers=list(body.get("layers") or []),
            etag=getattr(self, "last_etag", None),
            last_modified=getattr(self, "last_modified", None),
        )

    def list_layers(self, service_url: str) -> list[dict[str, Any]]:
        """Return the ``layers`` array. Uses ``/layers?f=pjson`` and falls back
        to the ``layers`` field from the service metadata if that route is
        unavailable."""
        service_url = service_url.rstrip("/")
        try:
            body = self._get(f"{service_url}/layers", {"f": "pjson"}, use_cache=True)
            layers = body.get("layers")
            if layers:
                return list(layers)
        except ArcGISError:
            logger.debug("/layers route unavailable for %s; using service meta", service_url)
        return list(self.service_metadata(service_url).layers)

    def layer_metadata(self, service_url: str, layer_id: int) -> dict[str, Any]:
        """Fetch ``{service_url}/{layer_id}?f=pjson``."""
        service_url = service_url.rstrip("/")
        return self._get(f"{service_url}/{layer_id}", {"f": "pjson"}, use_cache=True)

    def layer_ref(self, service_url: str, layer_id: int) -> LayerRef:
        """Resolve a single layer's metadata into a :class:`LayerRef`."""
        meta = self.layer_metadata(service_url, layer_id)
        return self._layer_ref_from_meta(service_url, layer_id, meta)

    @staticmethod
    def _layer_ref_from_meta(
        service_url: str, layer_id: int, meta: dict[str, Any]
    ) -> LayerRef:
        fields = tuple(
            f.get("name", "")
            for f in (meta.get("fields") or [])
            if f.get("type") != _GEOMETRY_FIELD_TYPE and f.get("name")
        )
        extent = meta.get("extent") or {}
        sr = extent.get("spatialReference") or {}
        wkid = sr.get("latestWkid") or sr.get("wkid")
        return LayerRef(
            service_url=service_url.rstrip("/"),
            layer_id=layer_id,
            name=meta.get("name", ""),
            geometry_type=meta.get("geometryType"),
            fields=fields,
            max_record_count=meta.get("maxRecordCount"),
            spatial_reference_wkid=wkid,
        )

    # -- layer discovery -------------------------------------------------
    def find_layer(
        self,
        service_url: str,
        *,
        required_fields: Iterable[str] = (),
        any_fields: Iterable[str] = (),
        name_contains: Iterable[str] = (),
        geometry_types: Iterable[str] = (),
        preferred_ids: Iterable[int] = (),
    ) -> LayerRef:
        """Discover a feature layer inside a service by metadata.

        Resolution order:
        1. ``preferred_ids`` (in order) that satisfy the field/geometry filters.
        2. Any feature layer satisfying ``required_fields`` (all present) plus at
           least one of ``any_fields`` (if given) and ``geometry_types`` /
           ``name_contains`` filters.

        Raises :class:`LayerNotFoundError` if nothing matches. This is how the
        ingesters stay robust to ArcGIS layer-id churn without hardcoding.
        """
        service_url = service_url.rstrip("/")
        required = [f.lower() for f in required_fields]
        any_f = [f.lower() for f in any_fields]
        gtypes = {g.lower() for g in geometry_types}
        name_terms = [t.lower() for t in name_contains]

        def _matches(ref: LayerRef) -> bool:
            flower = {f.lower() for f in ref.fields}
            if required and not all(r in flower for r in required):
                return False
            if any_f and not any(a in flower for a in any_f):
                return False
            if gtypes and (ref.geometry_type or "").lower() not in gtypes:
                return False
            if name_terms and not any(t in (ref.name or "").lower() for t in name_terms):
                return False
            return True

        # 1. Preferred ids first.
        for lid in preferred_ids:
            try:
                ref = self.layer_ref(service_url, int(lid))
            except ArcGISError:
                continue
            # Group layers have no fields / geometry; skip if filters demand them.
            if _matches(ref):
                return ref

        # 2. Scan all layers advertised by the service.
        for layer in self.list_layers(service_url):
            lid = layer.get("id")
            if lid is None:
                continue
            # Cheap pre-filter on the summary before fetching full metadata.
            if name_terms:
                summary_name = (layer.get("name") or "").lower()
                if not any(t in summary_name for t in name_terms) and not (
                    required or any_f
                ):
                    continue
            try:
                ref = self.layer_ref(service_url, int(lid))
            except ArcGISError:
                continue
            if _matches(ref):
                return ref

        raise LayerNotFoundError(
            f"No layer in {service_url} matched "
            f"required={list(required_fields)} any={list(any_fields)} "
            f"geometry={list(geometry_types)} name={list(name_contains)}"
        )

    # -- feature queries -------------------------------------------------
    def query_count(
        self,
        service_url: str,
        layer_id: int,
        *,
        where: str = "1=1",
        geometry: dict[str, Any] | None = None,
    ) -> int:
        """Return the feature count for a query (``returnCountOnly=true``)."""
        params: dict[str, Any] = {
            "where": where,
            "returnCountOnly": "true",
            "f": "json",
        }
        params.update(self._geometry_params(geometry))
        url = f"{service_url.rstrip('/')}/{layer_id}/query"
        body = self._get(url, params)
        return int(body.get("count", 0))

    def query_page(
        self,
        service_url: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str = "*",
        result_offset: int = 0,
        result_record_count: int | None = None,
        out_sr: int = 4326,
        return_geometry: bool = True,
        geometry: dict[str, Any] | None = None,
        order_by: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a single ``/query`` page and return the parsed GeoJSON body.

        Output is GeoJSON (``f=geojson``) which ArcGIS always returns in WGS84.
        ``outSR=4326`` is sent as well for services that honour it explicitly.
        """
        params: dict[str, Any] = {
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true" if return_geometry else "false",
            "outSR": out_sr,
            "f": "geojson",
            "resultOffset": result_offset,
        }
        if result_record_count is not None:
            params["resultRecordCount"] = result_record_count
        if order_by:
            params["orderByFields"] = order_by
        params.update(self._geometry_params(geometry))
        if extra_params:
            params.update(extra_params)
        url = f"{service_url.rstrip('/')}/{layer_id}/query"
        return self._get(url, params)

    def query_all(
        self,
        service_url: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str = "*",
        out_sr: int = 4326,
        page_size: int | None = None,
        geometry: dict[str, Any] | None = None,
        order_by: str | None = None,
        max_features: int | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Yield every GeoJSON feature for a query, paging transparently.

        Pagination uses ``resultOffset`` / ``resultRecordCount`` and stops when
        a page returns fewer than ``page_size`` features or the service reports
        ``exceededTransferLimit == false``. ``page_size`` defaults to the
        layer's advertised ``maxRecordCount`` (capped at 2000).
        """
        service_url = service_url.rstrip("/")
        if page_size is None:
            ref = self.layer_ref(service_url, layer_id)
            page_size = min(ref.max_record_count or 1000, 2000)
        page_size = max(1, page_size)

        offset = 0
        yielded = 0
        while True:
            body = self.query_page(
                service_url,
                layer_id,
                where=where,
                out_fields=out_fields,
                result_offset=offset,
                result_record_count=page_size,
                out_sr=out_sr,
                geometry=geometry,
                order_by=order_by,
                extra_params=extra_params,
            )
            features = body.get("features") or []
            if not features:
                break
            for feat in features:
                yield feat
                yielded += 1
                if max_features is not None and yielded >= max_features:
                    return
            exceeded = bool(
                body.get("exceededTransferLimit")
                or (body.get("properties") or {}).get("exceededTransferLimit")
            )
            if len(features) < page_size and not exceeded:
                break
            offset += len(features)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _geometry_params(geometry: dict[str, Any] | None) -> dict[str, Any]:
        """Build spatial-filter query params from an Esri geometry dict.

        ``geometry`` example (envelope):
            {"type": "esriGeometryEnvelope", "geometry": {...}, "inSR": 4326,
             "spatialRel": "esriSpatialRelIntersects"}
        """
        if not geometry:
            return {}
        import json as _json

        geom = geometry.get("geometry", geometry)
        params: dict[str, Any] = {
            "geometryType": geometry.get("type", "esriGeometryEnvelope"),
            "spatialRel": geometry.get("spatialRel", "esriSpatialRelIntersects"),
            "geometry": _json.dumps(geom),
        }
        in_sr = geometry.get("inSR")
        if in_sr is not None:
            params["inSR"] = in_sr
        return params

    @staticmethod
    def host_of(url: str) -> str:
        return urlsplit(url).netloc
