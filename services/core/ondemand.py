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
  disable it, and scoped to jurisdictions that have on-demand layers configured
  (see :data:`JURISDICTION_LAYERS`); an unconfigured jurisdiction is skipped, not
  blindly queried against another city's services. Los Angeles ships configured;
  adding a city is a config entry (its parcel + zoning (+ overlay) ArcGIS query
  URLs and field names), not a code change.

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
    # Per-layer source-attribute field mappings. These are the ArcGIS attribute
    # names (checked case-insensitively, first-present wins) used to extract the
    # value we cache. Defaults match the proven LA v1 services, so a jurisdiction
    # whose services use the same field names needs no override. A new city that
    # names its fields differently just sets these tuples in its config.
    apn_fields: tuple[str, ...] = ("APN", "AIN", "ain")
    situs_fields: tuple[str, ...] = (
        "SitusFullAddress", "SitusAddress", "situs_address",
    )
    zone_code_fields: tuple[str, ...] = (
        "ZONE_CLASS", "ZONE_CMPLT", "zone_cmplt", "zone",
    )
    zone_name_fields: tuple[str, ...] = ("ZONE_CMPLT", "ZONE_CLASS")
    # Overlay layers only: the overlay_features.overlay_type CHECK value this
    # layer feeds and the attribute field(s) holding the hazard designation.
    overlay_type: Optional[str] = None
    designation_fields: tuple[str, ...] = ()

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
    overlay_type="flood",
    designation_fields=("FLD_ZONE",),
)

# The Los Angeles v1 jurisdiction slug (the first proven-production city).
_LA_SLUG = "los_angeles"


# ---------------------------------------------------------------------------
# Per-jurisdiction layer registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class JurisdictionLayers:
    """The on-demand ArcGIS layers for one jurisdiction, keyed by slug.

    Adding a new production city is data, not code: append a
    :class:`JurisdictionLayers` entry to :data:`JURISDICTION_LAYERS` (or a
    ``jurisdiction_layers`` block in ``config/sources.yaml``) with the city's
    parcel + zoning (+ overlay) ArcGIS ``/query`` URLs and, where the services
    name their attributes differently from LA, the field-name overrides on each
    :class:`LayerConfig`. The resolver logic below is fully jurisdiction-agnostic.

    ``overlays`` is a tuple because a jurisdiction can layer several hazard
    services (flood, fire, ...). Federal/statewide overlays (e.g. FEMA NFHL) are
    shared verbatim across cities.
    """

    slug: str
    parcel: Optional[LayerConfig] = None
    zoning: Optional[LayerConfig] = None
    overlays: tuple[LayerConfig, ...] = ()


# Los Angeles v1: the proven, live-verified services. FEMA flood is federal and
# reused by every jurisdiction until a city-specific overlay is added.
_LA_LAYERS = JurisdictionLayers(
    slug=_LA_SLUG,
    parcel=PARCEL_LAYER,
    zoning=ZONING_LAYER,
    overlays=(FLOOD_LAYER,),
)

# San Diego v2: City of San Diego services, live-verified (see
# docs/data-sources/san_diego.md). Situs is split across fields on the SD parcel
# layer, so the street field is used for the cached situs_address.
_SD_LAYERS = JurisdictionLayers(
    slug="san_diego",
    parcel=LayerConfig(
        name="San Diego City parcels (GeocoderMerged/1)",
        query_url="https://webmaps.sandiego.gov/arcgis/rest/services/GeocoderMerged/MapServer/1/query",
        provider="arcgis", source_type="gis_parcel", layer_name="GeocoderMerged/1",
        apn_fields=("APN", "APN_8"),
        situs_fields=("SITUS_STREET", "SITUS_ADDRESS"),
    ),
    zoning=LayerConfig(
        name="San Diego DSD Official Zoning (Zoning_Base/0)",
        query_url="https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0/query",
        provider="arcgis", source_type="gis_zoning", layer_name="DSD/Zoning_Base/0",
        zone_code_fields=("ZONE_NAME",), zone_name_fields=("ZONE_NAME",),
    ),
    overlays=(FLOOD_LAYER,),  # FEMA flood is federal, shared across cities.
)

# The authoritative in-code registry. Only cities whose sources have been
# ingested and verified belong here (coverage honesty non-negotiable).
JURISDICTION_LAYERS: dict[str, JurisdictionLayers] = {
    _LA_SLUG: _LA_LAYERS,
    "san_diego": _SD_LAYERS,
}


def _layer_from_yaml(raw: dict[str, Any]) -> Optional[LayerConfig]:
    """Build a :class:`LayerConfig` from a config/sources.yaml layer mapping."""
    if not isinstance(raw, dict):
        return None
    query_url = raw.get("query_url") or raw.get("rest_query_url")
    if not query_url:
        return None

    def _tuple(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        v = raw.get(key)
        if v is None:
            return default
        if isinstance(v, str):
            return (v,)
        return tuple(str(x) for x in v)

    defaults = LayerConfig(name="", query_url="x", provider="arcgis",
                           source_type="gis_parcel", layer_name="")
    return LayerConfig(
        name=str(raw.get("name") or query_url),
        query_url=str(query_url),
        provider=str(raw.get("provider") or "arcgis"),
        source_type=str(raw.get("source_type") or "gis_parcel"),
        layer_name=str(raw.get("layer_name") or ""),
        verify_ssl=bool(raw.get("verify_ssl", True)),
        timeout_s=raw.get("timeout_s"),
        apn_fields=_tuple("apn_fields", defaults.apn_fields),
        situs_fields=_tuple("situs_fields", defaults.situs_fields),
        zone_code_fields=_tuple("zone_code_fields", defaults.zone_code_fields),
        zone_name_fields=_tuple("zone_name_fields", defaults.zone_name_fields),
        overlay_type=raw.get("overlay_type"),
        designation_fields=_tuple("designation_fields", ()),
    )


def _load_yaml_jurisdiction_layers() -> dict[str, JurisdictionLayers]:
    """Optionally merge a ``jurisdiction_layers`` block from config/sources.yaml.

    This is a pure additive/override seam so a city can be onboarded by editing
    config alone. It is defensive: any missing file, absent block, or malformed
    entry is ignored and the in-code registry stands. It never raises.
    """
    path = os.environ.get("ADU_SOURCES_YAML")
    if not path:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.normpath(
            os.path.join(here, "..", "..", "config", "sources.yaml")
        )
    try:
        import yaml  # lazy: pure core imports without pyyaml present

        with open(path, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
    except Exception:
        return {}
    block = doc.get("jurisdiction_layers") if isinstance(doc, dict) else None
    if not isinstance(block, dict):
        return {}
    out: dict[str, JurisdictionLayers] = {}
    for slug, cfg in block.items():
        if not isinstance(cfg, dict):
            continue
        try:
            parcel = _layer_from_yaml(cfg.get("parcel")) if cfg.get("parcel") else None
            zoning = _layer_from_yaml(cfg.get("zoning")) if cfg.get("zoning") else None
            overlays_raw = cfg.get("overlays") or []
            overlays = tuple(
                lc for lc in (_layer_from_yaml(o) for o in overlays_raw) if lc is not None
            )
            out[str(slug)] = JurisdictionLayers(
                slug=str(slug), parcel=parcel, zoning=zoning, overlays=overlays,
            )
        except Exception:
            continue
    return out


# Merge any yaml-declared jurisdictions over the in-code registry once at import.
# yaml entries win so a city can be tuned/onboarded without a code change.
try:
    JURISDICTION_LAYERS.update(_load_yaml_jurisdiction_layers())
except Exception:  # pragma: no cover - defensive
    pass


def get_jurisdiction_layers(slug: Optional[str]) -> Optional[JurisdictionLayers]:
    """Return the configured layers for ``slug`` or ``None`` if unconfigured."""
    if not slug:
        return None
    return JURISDICTION_LAYERS.get(slug)


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

    def _layers_for(self, jurisdiction_id: Optional[str]) -> Optional[JurisdictionLayers]:
        """Resolve the configured on-demand layers for a jurisdiction (by slug)."""
        slug = self._jurisdiction_slug(jurisdiction_id)
        return get_jurisdiction_layers(slug)

    def _in_scope(self, jurisdiction_id: Optional[str]) -> bool:
        # In scope for any jurisdiction that has on-demand layers configured. An
        # unknown / unconfigured jurisdiction is skipped rather than blindly
        # queried against another city's services.
        if not self.enabled:
            return False
        return self._layers_for(jurisdiction_id) is not None

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
    def _cache_parcels(
        self, jurisdiction_id: str, layer: LayerConfig, fetch: FetchResult
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
            apn = _prop(props, *layer.apn_fields)
            if geom is None or apn is None:
                continue
            situs = _prop(props, *layer.situs_fields)
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
                        "url": layer.source_url,
                        "layer": layer.layer_name,
                        "raw": json.dumps(raw, default=str),
                        "retrieved": retrieved,
                    },
                )
                inserted += 1
            except Exception:
                continue
        return inserted

    def _cache_zoning(
        self, jurisdiction_id: str, layer: LayerConfig, fetch: FetchResult
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
            zone_code = _prop(props, *layer.zone_code_fields)
            if geom is None or zone_code is None:
                continue
            zone_full = _prop(props, *layer.zone_name_fields)
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
                        "url": layer.source_url,
                        "layer": layer.layer_name,
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
        layer: LayerConfig,
        fetch: FetchResult,
    ) -> int:
        overlay_type = layer.overlay_type or "other"
        designation_fields = layer.designation_fields
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
        """Fetch parcel + zoning + overlay layer(s) in PARALLEL and cache them.

        Called when a point has no cached parcel. The layers fetched are whatever
        the point's jurisdiction has configured (LA today). A missing/slow source
        degrades silently (its layer is simply left uncached) rather than blocking
        the others or fabricating data.

        The result dict always carries ``parcel``, ``zoning`` and ``flood`` counts
        (``flood`` stays 0 when the jurisdiction has no flood overlay) plus a count
        per additional overlay_type and a ``fetched`` flag.
        """
        result: dict[str, Any] = {"parcel": 0, "zoning": 0, "flood": 0, "fetched": False}
        layers = self._layers_for(jurisdiction_id)
        if not self.enabled or layers is None:
            return result

        # Build the fetch jobs for exactly the layers this jurisdiction configures.
        jobs: dict[str, LayerConfig] = {}
        if layers.parcel is not None:
            jobs["parcel"] = layers.parcel
        if layers.zoning is not None:
            jobs["zoning"] = layers.zoning
        for i, ov in enumerate(layers.overlays):
            jobs[f"overlay:{i}"] = ov
        if not jobs:
            return result

        # If every configured layer was refreshed for this point recently, skip.
        if all(self._recently_done(layer.name, point) for layer in jobs.values()):
            return result

        fetched: dict[str, FetchResult] = {}
        try:
            with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as ex:
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
        if "parcel" in jobs:
            result["parcel"] = self._cache_parcels(
                jurisdiction_id, jobs["parcel"], fetched["parcel"]
            )
            self._mark_done(jobs["parcel"].name, point)
        if "zoning" in jobs:
            result["zoning"] = self._cache_zoning(
                jurisdiction_id, jobs["zoning"], fetched["zoning"]
            )
            self._mark_done(jobs["zoning"].name, point)
        for i, ov in enumerate(layers.overlays):
            name = f"overlay:{i}"
            key = ov.overlay_type or "other"
            # Federal / statewide overlays (e.g. FEMA NFHL) are not tied to a city.
            cached = self._cache_overlays(None, ov, fetched[name])
            result[key] = result.get(key, 0) + cached
            self._mark_done(ov.name, point)
        return result

    def hydrate_zoning(self, jurisdiction_id: str, point: GeoPoint) -> int:
        """Fetch + cache only the zoning layer (partial-coverage safety net)."""
        layers = self._layers_for(jurisdiction_id)
        if not self.enabled or layers is None or layers.zoning is None:
            return 0
        if self._recently_done(layers.zoning.name, point):
            return 0
        fetch = self._fetch(layers.zoning, point)
        n = self._cache_zoning(jurisdiction_id, layers.zoning, fetch)
        self._mark_done(layers.zoning.name, point)
        return n

    def hydrate_overlays(self, jurisdiction_id: Optional[str], point: GeoPoint) -> int:
        """Fetch + cache the jurisdiction's overlay layer(s) (partial-coverage net)."""
        layers = self._layers_for(jurisdiction_id)
        if not self.enabled or layers is None or not layers.overlays:
            return 0
        total = 0
        for ov in layers.overlays:
            if self._recently_done(ov.name, point):
                continue
            fetch = self._fetch(ov, point)
            total += self._cache_overlays(None, ov, fetch)
            self._mark_done(ov.name, point)
        return total
