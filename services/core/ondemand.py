"""On-demand, ingestion-lite coverage for the deterministic request path.

The request path stays deterministic and LLM-free. When a geocoded point has no
cached parcel, zoning district, or hazard overlay in Postgres, this resolver
fetches the missing layer(s) directly from the official ArcGIS services around
the point, caches the returned features into the existing tables (idempotently),
and records source_registry + source_snapshots provenance. The existing
ST_Contains / spatial-join queries in ``core.db`` then run against the freshly
cached rows.

These are source-linked GIS fetches (not model output), so they are allowed on
the request path, but they must be fast and degrade gracefully:

- all three layers are fetched in PARALLEL with a per-source timeout
  (``ONDEMAND_TIMEOUT_S``, default 6s); a slow or failed source never blocks the
  others and never fabricates data;
- caching is idempotent: parcels dedupe on ``(jurisdiction_id, apn)`` via
  ``ON CONFLICT DO NOTHING``; zoning and overlay features dedupe on a stable
  content key (``ondemand_key``) via ``NOT EXISTS`` so repeat requests do not
  bloat the tables;
- everything is gated behind ``ONDEMAND_ENABLED`` (default true) so tests can
  disable it, and behind the Los Angeles v1 scope (the proven ArcGIS layers).

No table names or columns are changed. httpx is imported lazily so the pure core
imports without the dependency present.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from .repository import GeoPoint

# ---------------------------------------------------------------------------
# Layer configuration (the PROVEN LA v1 ArcGIS services)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LayerConfig:
    name: str
    query_url: str          # ArcGIS layer /query endpoint
    provider: str           # source_registry.provider CHECK value
    source_type: str        # source_registry.source_type CHECK value
    layer_name: str
    verify_ssl: bool = True
    # Per-layer read timeout override (seconds). Falls back to the resolver's
    # ONDEMAND_TIMEOUT_S when None. ZIMAS is materially slower than the other
    # services (~9s vs <1s), so it gets a longer allowance.
    timeout_s: Optional[float] = None

    @property
    def source_url(self) -> str:
        # The layer base (without the trailing /query) is the citable source URL.
        if self.query_url.endswith("/query"):
            return self.query_url[: -len("/query")]
        return self.query_url


PARCEL_LAYER = LayerConfig(
    name="LA County parcels (LACounty_Parcel/0)",
    query_url="https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query",
    provider="arcgis",
    source_type="gis_parcel",
    layer_name="LACounty_Parcel/0",
)

ZONING_LAYER = LayerConfig(
    name="LA City ZIMAS zoning (zma/zimas/1102)",
    query_url="https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer/1102/query",
    provider="arcgis",
    source_type="gis_zoning",
    layer_name="zma/zimas/1102",
    verify_ssl=False,  # ZIMAS presents an SSL chain httpx rejects; proven-safe here.
    timeout_s=22.0,    # ZIMAS envelope queries take ~9s; the 6s default times out.
)

FLOOD_LAYER = LayerConfig(
    name="FEMA NFHL flood hazard (NFHL/28)",
    query_url="https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query",
    provider="fema",
    source_type="gis_overlay",
    layer_name="NFHL/28",
)

# The Los Angeles v1 jurisdiction slug this resolver is scoped to.
_LA_SLUG = "los_angeles"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# DB seam (so the resolver is trivially unit-testable without Postgres)
# ---------------------------------------------------------------------------
class DBExecutor(Protocol):
    def rows(self, sql: str, params: Any = ()) -> list[dict[str, Any]]: ...
    def row(self, sql: str, params: Any = ()) -> Optional[dict[str, Any]]: ...
    def execute(self, sql: str, params: Any = ()) -> None: ...


class RepoDBAdapter:
    """Adapts a :class:`core.db.PostgresRepository` to the :class:`DBExecutor` seam."""

    def __init__(self, repo: Any):
        self._repo = repo

    def rows(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        return self._repo._rows(sql, params)

    def row(self, sql: str, params: Any = ()) -> Optional[dict[str, Any]]:
        return self._repo._row(sql, params)

    def execute(self, sql: str, params: Any = ()) -> None:
        self._repo._execute(sql, params)


# ---------------------------------------------------------------------------
# HTTP fetch seam
# ---------------------------------------------------------------------------
@dataclass
class FetchResult:
    ok: bool
    status_code: Optional[int] = None
    content: Optional[bytes] = None
    features: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


# A fetcher turns (url, params, verify, timeout) into (status_code, content, features).
Fetcher = Callable[..., tuple]


def _default_fetch(url: str, params: dict[str, Any], *, verify: bool, timeout: float) -> tuple:
    """Default ArcGIS GeoJSON fetch using httpx (imported lazily)."""
    import httpx

    resp = httpx.get(url, params=params, verify=verify, timeout=timeout)
    resp.raise_for_status()
    content = resp.content
    data = resp.json()
    features = (data.get("features") if isinstance(data, dict) else None) or []
    return resp.status_code, content, features


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
def bbox_envelope(point: GeoPoint, radius_m: float) -> tuple[float, float, float, float]:
    """A small WGS84 envelope (xmin,ymin,xmax,ymax) ~radius_m around the point."""
    dlat = radius_m / 111320.0
    cos_lat = math.cos(math.radians(point.lat))
    dlon = radius_m / (111320.0 * max(0.01, abs(cos_lat)))
    return (point.lon - dlon, point.lat - dlat, point.lon + dlon, point.lat + dlat)


def arcgis_query_params(point: GeoPoint, radius_m: float) -> dict[str, str]:
    """ArcGIS envelope query returning WGS84 GeoJSON (the proven-working shape)."""
    xmin, ymin, xmax, ymax = bbox_envelope(point, radius_m)
    return {
        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
    }


def _prop(props: dict[str, Any], *names: str) -> Optional[Any]:
    """Case-insensitive first-present property lookup."""
    if not isinstance(props, dict):
        return None
    lower = {str(k).lower(): v for k, v in props.items()}
    for n in names:
        v = lower.get(n.lower())
        if v is not None and v != "":
            return v
    return None


def feature_key(feature: dict[str, Any], *extra: Any) -> str:
    """A stable content key for a feature, used to dedupe repeat on-demand writes.

    Hashes the geometry plus any extra discriminators (e.g. zone code) so an
    identical feature fetched again maps to the same key and is not re-inserted.
    """
    geom = feature.get("geometry") if isinstance(feature, dict) else None
    blob = json.dumps(
        {"g": geom, "x": [str(e) for e in extra]},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------
class OnDemandResolver:
    """Fetches + caches missing parcel / zoning / overlay layers around a point."""

    def __init__(
        self,
        db: DBExecutor,
        *,
        enabled: Optional[bool] = None,
        timeout_s: Optional[float] = None,
        radius_m: Optional[float] = None,
        memo_ttl_s: float = 60.0,
        fetch: Optional[Fetcher] = None,
        now: Callable[[], datetime] = _now,
    ):
        self._db = db
        self.enabled = _env_bool("ONDEMAND_ENABLED", True) if enabled is None else enabled
        self.timeout_s = _env_float("ONDEMAND_TIMEOUT_S", 6.0) if timeout_s is None else timeout_s
        self.radius_m = _env_float("ONDEMAND_ENVELOPE_M", 120.0) if radius_m is None else radius_m
        self._memo_ttl = memo_ttl_s
        self._fetch_fn: Fetcher = fetch or _default_fetch
        self._now = now
        # Short-lived memo so the three separate repo method calls in one request
        # (and quick repeats) do not refetch the same layer for the same point.
        self._done: dict[str, float] = {}
        self._slug_cache: dict[str, Optional[str]] = {}

    # -- memo ---------------------------------------------------------------
    def _memo_point(self, point: GeoPoint) -> str:
        return f"{round(point.lon, 5)},{round(point.lat, 5)}"

    def _recently_done(self, layer: str, point: GeoPoint) -> bool:
        key = f"{layer}:{self._memo_point(point)}"
        ts = self._done.get(key)
        return ts is not None and (time.monotonic() - ts) < self._memo_ttl

    def _mark_done(self, layer: str, point: GeoPoint) -> None:
        self._done[f"{layer}:{self._memo_point(point)}"] = time.monotonic()

    # -- jurisdiction scope -------------------------------------------------
    def _jurisdiction_slug(self, jurisdiction_id: Optional[str]) -> Optional[str]:
        if jurisdiction_id is None:
            return None
        if jurisdiction_id in self._slug_cache:
            return self._slug_cache[jurisdiction_id]
        slug: Optional[str] = None
        try:
            row = self._db.row(
                "select slug from jurisdictions where id = %s::uuid",
                (jurisdiction_id,),
            )
            slug = row.get("slug") if row else None
        except Exception:
            slug = None
        self._slug_cache[jurisdiction_id] = slug
        return slug

    def _in_scope(self, jurisdiction_id: Optional[str]) -> bool:
        if not self.enabled:
            return False
        slug = self._jurisdiction_slug(jurisdiction_id)
        # Proceed for LA (v1 scope) or when the slug is unknown (best effort);
        # skip for any other known jurisdiction to avoid pointless fetches.
        return slug is None or slug == _LA_SLUG

    # -- fetch --------------------------------------------------------------
    def _fetch(self, layer: LayerConfig, point: GeoPoint) -> FetchResult:
        params = arcgis_query_params(point, self.radius_m)
        try:
            status_code, content, features = self._fetch_fn(
                layer.query_url, params, verify=layer.verify_ssl,
                timeout=layer.timeout_s or self.timeout_s,
            )
            return FetchResult(
                ok=True,
                status_code=status_code,
                content=content,
                features=list(features or []),
            )
        except Exception as exc:  # network error / timeout / bad payload
            return FetchResult(ok=False, error=str(exc))

    # -- provenance ---------------------------------------------------------
    def _ensure_registry(self, layer: LayerConfig, jurisdiction_id: Optional[str]) -> Optional[str]:
        """Upsert a source_registry row for this layer; returns its id (or None)."""
        jid = jurisdiction_id if layer.provider == "arcgis" and layer.source_type != "gis_overlay" else None
        try:
            existing = self._db.row(
                """
                select id::text from source_registry
                 where source_type = %s and url = %s
                   and jurisdiction_id is not distinct from %s::uuid
                 limit 1
                """,
                (layer.source_type, layer.source_url, jid),
            )
            if existing and existing.get("id"):
                self._db.execute(
                    "update source_registry set last_checked_at = now(), "
                    "last_retrieved_at = now(), updated_at = now() where id = %s::uuid",
                    (existing["id"],),
                )
                return existing["id"]
            row = self._db.row(
                """
                insert into source_registry
                  (jurisdiction_id, source_type, provider, name, url, endpoint,
                   layer_name, active, last_checked_at, last_retrieved_at)
                values
                  (%s::uuid, %s, %s, %s, %s, %s, %s, true, now(), now())
                returning id::text
                """,
                (
                    jid,
                    layer.source_type,
                    layer.provider,
                    layer.name,
                    layer.source_url,
                    layer.source_url,
                    layer.layer_name,
                ),
            )
            return row["id"] if row and row.get("id") else None
        except Exception:
            return None

    def _ensure_snapshot(self, registry_id: Optional[str], fetch: FetchResult) -> Optional[str]:
        """Content-hash the response into an (append-only) source_snapshots row."""
        if not registry_id or not fetch.ok or fetch.content is None:
            return None
        try:
            content_hash = hashlib.sha256(fetch.content).hexdigest()
            existing = self._db.row(
                "select id::text from source_snapshots "
                "where source_registry_id = %s::uuid and content_hash = %s limit 1",
                (registry_id, content_hash),
            )
            if existing and existing.get("id"):
                return existing["id"]
            ver = self._db.row(
                "select coalesce(max(version), 0) + 1 as v from source_snapshots "
                "where source_registry_id = %s::uuid",
                (registry_id,),
            )
            version = int(ver["v"]) if ver and ver.get("v") is not None else 1
            row = self._db.row(
                """
                insert into source_snapshots
                  (source_registry_id, version, content_hash, content_type,
                   byte_size, http_status, retrieved_at)
                values
                  (%s::uuid, %s, %s, %s, %s, %s, now())
                on conflict (source_registry_id, content_hash) do nothing
                returning id::text
                """,
                (
                    registry_id,
                    version,
                    content_hash,
                    "application/geo+json",
                    len(fetch.content),
                    fetch.status_code,
                ),
            )
            if row and row.get("id"):
                return row["id"]
            # Lost a race (identical hash inserted concurrently): read it back.
            got = self._db.row(
                "select id::text from source_snapshots "
                "where source_registry_id = %s::uuid and content_hash = %s limit 1",
                (registry_id, content_hash),
            )
            return got["id"] if got and got.get("id") else None
        except Exception:
            return None

    # -- caching ------------------------------------------------------------
    def _cache_parcels(self, jurisdiction_id: str, fetch: FetchResult) -> int:
        if not fetch.ok or not fetch.features:
            return 0
        registry_id = self._ensure_registry(PARCEL_LAYER, jurisdiction_id)
        snapshot_id = self._ensure_snapshot(registry_id, fetch)
        retrieved = self._now()
        inserted = 0
        for feat in fetch.features:
            geom = feat.get("geometry")
            props = feat.get("properties") or {}
            apn = _prop(props, "APN", "AIN", "ain")
            if geom is None or apn is None:
                continue
            situs = _prop(props, "SitusFullAddress", "SitusAddress", "situs_address")
            raw = dict(props)
            raw["ondemand_key"] = feature_key(feat, apn)
            try:
                self._db.execute(
                    """
                    with g as (
                      select ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))) as geom
                    )
                    insert into parcels
                      (jurisdiction_id, apn, situs_address, normalized_address, geom,
                       centroid, area_sqft, source_registry_id, source_snapshot_id,
                       source_url, source_layer, raw_attributes, confidence,
                       data_status, retrieved_at, last_verified_at)
                    select
                      %(jid)s::uuid, %(apn)s, %(situs)s, %(situs)s, g.geom,
                      ST_Centroid(g.geom),
                      ST_Area(g.geom::geography) * 10.76391,
                      %(reg)s::uuid, %(snap)s::uuid, %(url)s, %(layer)s,
                      %(raw)s::jsonb, 'high', 'current', %(retrieved)s, %(retrieved)s
                    from g
                    on conflict (jurisdiction_id, apn) do nothing
                    """,
                    {
                        "geom": json.dumps(geom),
                        "jid": jurisdiction_id,
                        "apn": str(apn),
                        "situs": str(situs) if situs is not None else None,
                        "reg": registry_id,
                        "snap": snapshot_id,
                        "url": PARCEL_LAYER.source_url,
                        "layer": PARCEL_LAYER.layer_name,
                        "raw": json.dumps(raw, default=str),
                        "retrieved": retrieved,
                    },
                )
                inserted += 1
            except Exception:
                continue
        return inserted

    def _cache_zoning(self, jurisdiction_id: str, fetch: FetchResult) -> int:
        if not fetch.ok or not fetch.features:
            return 0
        registry_id = self._ensure_registry(ZONING_LAYER, jurisdiction_id)
        snapshot_id = self._ensure_snapshot(registry_id, fetch)
        retrieved = self._now()
        inserted = 0
        for feat in fetch.features:
            geom = feat.get("geometry")
            props = feat.get("properties") or {}
            zone_code = _prop(props, "ZONE_CLASS", "ZONE_CMPLT", "zone_cmplt", "zone")
            if geom is None or zone_code is None:
                continue
            zone_full = _prop(props, "ZONE_CMPLT", "ZONE_CLASS")
            key = feature_key(feat, zone_code)
            raw = dict(props)
            raw["ondemand_key"] = key
            try:
                self._db.execute(
                    """
                    with g as (
                      select ST_Multi(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))) as geom
                    )
                    insert into zoning_districts
                      (jurisdiction_id, zone_code, zone_name, zone_category, geom,
                       source_registry_id, source_snapshot_id, source_url, source_layer,
                       raw_attributes, confidence, data_status, retrieved_at, last_verified_at)
                    select
                      %(jid)s::uuid, %(zone)s, %(zname)s, %(zcat)s, g.geom,
                      %(reg)s::uuid, %(snap)s::uuid, %(url)s, %(layer)s,
                      %(raw)s::jsonb, 'high', 'current', %(retrieved)s, %(retrieved)s
                    from g
                    where not exists (
                      select 1 from zoning_districts zd
                       where zd.jurisdiction_id = %(jid)s::uuid
                         and zd.raw_attributes->>'ondemand_key' = %(key)s
                    )
                    """,
                    {
                        "geom": json.dumps(geom),
                        "jid": jurisdiction_id,
                        "zone": str(zone_code),
                        "zname": str(zone_full) if zone_full is not None else None,
                        "zcat": None,
                        "reg": registry_id,
                        "snap": snapshot_id,
                        "url": ZONING_LAYER.source_url,
                        "layer": ZONING_LAYER.layer_name,
                        "raw": json.dumps(raw, default=str),
                        "retrieved": retrieved,
                        "key": key,
                    },
                )
                inserted += 1
            except Exception:
                continue
        return inserted

    def _cache_overlays(
        self,
        jurisdiction_id: Optional[str],
        fetch: FetchResult,
        *,
        layer: LayerConfig,
        overlay_type: str,
        designation_fields: tuple[str, ...],
    ) -> int:
        if not fetch.ok or not fetch.features:
            return 0
        registry_id = self._ensure_registry(layer, jurisdiction_id)
        snapshot_id = self._ensure_snapshot(registry_id, fetch)
        retrieved = self._now()
        inserted = 0
        for feat in fetch.features:
            geom = feat.get("geometry")
            props = feat.get("properties") or {}
            if geom is None:
                continue
            designation = _prop(props, *designation_fields)
            raw_feature_id = _prop(props, "OBJECTID", "FLD_AR_ID", "objectid")
            key = feature_key(feat, overlay_type, designation)
            raw = dict(props)
            raw["ondemand_key"] = key
            if designation is not None:
                raw.setdefault("designation", designation)
            try:
                # overlay_features.geom is a generic Geometry (no ST_Multi).
                self._db.execute(
                    """
                    with g as (
                      select ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)) as geom
                    )
                    insert into overlay_features
                      (jurisdiction_id, overlay_type, name, designation, geom,
                       raw_feature_id, raw_value, source_registry_id, source_snapshot_id,
                       source_url, source_layer, confidence, data_status,
                       retrieved_at, last_verified_at)
                    select
                      %(jid)s::uuid, %(otype)s, %(dname)s, %(desig)s, g.geom,
                      %(fid)s, %(raw)s::jsonb, %(reg)s::uuid, %(snap)s::uuid,
                      %(url)s, %(layer)s, 'high', 'current', %(retrieved)s, %(retrieved)s
                    from g
                    where not exists (
                      select 1 from overlay_features ov
                       where ov.overlay_type = %(otype)s
                         and ov.raw_value->>'ondemand_key' = %(key)s
                    )
                    """,
                    {
                        "geom": json.dumps(geom),
                        "jid": jurisdiction_id,
                        "otype": overlay_type,
                        "dname": str(designation) if designation is not None else None,
                        "desig": str(designation) if designation is not None else None,
                        "fid": str(raw_feature_id) if raw_feature_id is not None else None,
                        "raw": json.dumps(raw, default=str),
                        "reg": registry_id,
                        "snap": snapshot_id,
                        "url": layer.source_url,
                        "layer": layer.layer_name,
                        "retrieved": retrieved,
                        "key": key,
                    },
                )
                inserted += 1
            except Exception:
                continue
        return inserted

    # -- public entry points ------------------------------------------------
    def hydrate_point(self, jurisdiction_id: str, point: GeoPoint) -> dict[str, Any]:
        """Fetch parcel + zoning + flood overlay in PARALLEL and cache them.

        Called when a point has no cached parcel. A missing/slow source degrades
        silently (its layer is simply left uncached) rather than blocking the
        others or fabricating data.
        """
        result = {"parcel": 0, "zoning": 0, "flood": 0, "fetched": False}
        if not self._in_scope(jurisdiction_id):
            return result
        # If every layer was refreshed for this point very recently, skip.
        if (
            self._recently_done("parcel", point)
            and self._recently_done("zoning", point)
            and self._recently_done("flood", point)
        ):
            return result

        jobs = {
            "parcel": PARCEL_LAYER,
            "zoning": ZONING_LAYER,
            "flood": FLOOD_LAYER,
        }
        fetched: dict[str, FetchResult] = {}
        try:
            with ThreadPoolExecutor(max_workers=3) as ex:
                futs = {name: ex.submit(self._fetch, layer, point) for name, layer in jobs.items()}
                for name, fut in futs.items():
                    try:
                        fetched[name] = fut.result()
                    except Exception as exc:
                        fetched[name] = FetchResult(ok=False, error=str(exc))
        except Exception:
            # Executor could not even start; nothing cached, degrade gracefully.
            return result

        result["fetched"] = True
        result["parcel"] = self._cache_parcels(jurisdiction_id, fetched["parcel"])
        self._mark_done("parcel", point)
        result["zoning"] = self._cache_zoning(jurisdiction_id, fetched["zoning"])
        self._mark_done("zoning", point)
        result["flood"] = self._cache_overlays(
            None, fetched["flood"], layer=FLOOD_LAYER,
            overlay_type="flood", designation_fields=("FLD_ZONE",),
        )
        self._mark_done("flood", point)
        return result

    def hydrate_zoning(self, jurisdiction_id: str, point: GeoPoint) -> int:
        """Fetch + cache only the zoning layer (partial-coverage safety net)."""
        if not self._in_scope(jurisdiction_id) or self._recently_done("zoning", point):
            return 0
        fetch = self._fetch(ZONING_LAYER, point)
        n = self._cache_zoning(jurisdiction_id, fetch)
        self._mark_done("zoning", point)
        return n

    def hydrate_overlays(self, jurisdiction_id: Optional[str], point: GeoPoint) -> int:
        """Fetch + cache only the flood overlay layer (partial-coverage safety net)."""
        if not self._in_scope(jurisdiction_id) or self._recently_done("flood", point):
            return 0
        fetch = self._fetch(FLOOD_LAYER, point)
        n = self._cache_overlays(
            None, fetch, layer=FLOOD_LAYER,
            overlay_type="flood", designation_fields=("FLD_ZONE",),
        )
        self._mark_done("flood", point)
        return n
