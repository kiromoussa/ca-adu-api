"""Shared infrastructure for the GIS ingesters.

Holds the runtime settings, the PostGIS database layer (psycopg v3), immutable
``source_snapshots`` handling, ``source_registry`` resolution, ``ingest_runs``
lifecycle, and the geometry-insert SQL used by every source-specific ingester.

Why psycopg (not supabase-py / PostgREST): every GIS row carries PostGIS
geometry that must be built with ``ST_GeomFromGeoJSON`` / ``ST_SetSRID`` /
``ST_Multi`` / ``ST_Centroid`` and have its area computed with
``ST_Area(ST_Transform(...))``. That is spatial SQL, which PostgREST cannot
express cleanly. Ingestion runs offline on Render where the direct Postgres URL
(``SUPABASE_DB_URL``) is reachable, so we use it directly.

Secrets come only from the environment. Nothing is hardcoded. No LLM.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)

# California Albers (meters) - used only for accurate area computation, never
# for storage. All stored geometry stays in EPSG:4326.
_AREA_SRID = 3310
_SQM_TO_SQFT = 10.7639104167


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None:
        return default
    val = val.strip()
    return val or default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int | None) -> int | None:
    raw = _env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot built from the environment.

    Required:
      SUPABASE_DB_URL              direct Postgres connection string, OR
      SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY  (a DB URL is derived / required)

    The ingesters need spatial SQL, so a direct Postgres URL is required. If
    only SUPABASE_URL is provided we cannot open a psycopg connection and fail
    with an actionable message.
    """

    db_url: str
    supabase_url: str | None = None
    service_role_key: str | None = None

    # HTTP client tuning
    http_timeout: float = 60.0
    rate_limit_seconds: float = 0.5
    max_retries: int = 4

    # Ingest tuning
    page_size: int | None = None
    max_features: int | None = None
    triggered_by: str = "cli"

    # Source service overrides (config-driven; empty falls back to defaults).
    la_zimas_service_url: str = "https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer"
    la_parcel_service_url: str | None = None
    la_parcel_layer_id: int | None = None
    fema_service_url: str = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"
    fema_flood_layer_id: int = 28
    calfire_service_url: str = "https://services.gis.ca.gov/arcgis/rest/services/Environment/Fire_Severity_Zones/MapServer"
    statewide_zoning_service_url: str | None = None
    statewide_zoning_layer_id: int | None = None
    target_jurisdiction_slug: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        db_url = _env("SUPABASE_DB_URL") or _env("DATABASE_URL")
        supabase_url = _env("SUPABASE_URL")
        service_role_key = _env("SUPABASE_SERVICE_ROLE_KEY")
        if not db_url:
            raise RuntimeError(
                "SUPABASE_DB_URL (a direct Postgres connection string) is "
                "required for GIS ingestion because it writes PostGIS geometry "
                "with spatial SQL. Set SUPABASE_DB_URL (or DATABASE_URL) in the "
                "environment; on Render declare it in render.yaml (sync:false)."
            )
        return cls(
            db_url=db_url,
            supabase_url=supabase_url,
            service_role_key=service_role_key,
            http_timeout=_env_float("ARCGIS_HTTP_TIMEOUT", 60.0),
            rate_limit_seconds=_env_float("ARCGIS_RATE_LIMIT_SECONDS", 0.5),
            max_retries=_env_int("ARCGIS_MAX_RETRIES", 4) or 4,
            page_size=_env_int("INGEST_PAGE_SIZE", None),
            max_features=_env_int("INGEST_MAX_FEATURES", None),
            triggered_by=_env("INGEST_TRIGGERED_BY", "cli") or "cli",
            la_zimas_service_url=_env(
                "LA_ZIMAS_SERVICE_URL",
                "https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer",
            ),
            la_parcel_service_url=_env("LA_PARCEL_SERVICE_URL"),
            la_parcel_layer_id=_env_int("LA_PARCEL_LAYER_ID", None),
            fema_service_url=_env(
                "FEMA_NFHL_SERVICE_URL",
                "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer",
            ),
            fema_flood_layer_id=_env_int("FEMA_FLOOD_LAYER_ID", 28) or 28,
            calfire_service_url=_env(
                "CALFIRE_FHSZ_SERVICE_URL",
                "https://services.gis.ca.gov/arcgis/rest/services/Environment/Fire_Severity_Zones/MapServer",
            ),
            statewide_zoning_service_url=_env("CA_STATEWIDE_ZONING_SERVICE_URL"),
            statewide_zoning_layer_id=_env_int("CA_STATEWIDE_ZONING_LAYER_ID", None),
            target_jurisdiction_slug=_env("INGEST_JURISDICTION_SLUG"),
        )


# ---------------------------------------------------------------------------
# Content hashing for immutable snapshots
# ---------------------------------------------------------------------------
def content_hash(payload: dict[str, Any]) -> str:
    """Deterministic sha256 over a canonical JSON encoding of ``payload``.

    Used for ``source_snapshots.content_hash``. For GIS layers the hashed
    payload is the layer metadata plus the exact query parameters, so an
    identical capture dedupes and a changed layer / query yields a new
    immutable snapshot.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Database layer
# ---------------------------------------------------------------------------
class GISDatabase:
    """PostGIS-aware Supabase Postgres access for the GIS ingesters."""

    def __init__(self, db_url: str) -> None:
        # autocommit off; each ingester manages transactions explicitly.
        self._conn = psycopg.connect(db_url, row_factory=dict_row, autocommit=False)
        # Ensure PostGIS functions resolve (they live in the extensions schema
        # on Supabase). Harmless if already on the search_path.
        with self._conn.cursor() as cur:
            cur.execute("set search_path = public, extensions")
        self._conn.commit()

    # -- lifecycle -------------------------------------------------------
    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - best effort
            pass

    def __enter__(self) -> "GISDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.rollback()
        self.close()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    @property
    def conn(self) -> psycopg.Connection:
        return self._conn

    # -- jurisdictions ---------------------------------------------------
    def get_jurisdiction_id(self, slug: str) -> str | None:
        with self._conn.cursor() as cur:
            cur.execute("select id from jurisdictions where slug = %s", (slug,))
            row = cur.fetchone()
            return str(row["id"]) if row else None

    def require_jurisdiction_id(self, slug: str) -> str:
        jid = self.get_jurisdiction_id(slug)
        if jid is None:
            raise RuntimeError(
                f"Jurisdiction '{slug}' not found. Seed jurisdictions "
                f"(config/jurisdictions.yaml) before ingesting GIS data."
            )
        return jid

    # -- source_registry -------------------------------------------------
    def ensure_source_registry(
        self,
        *,
        jurisdiction_id: str | None,
        source_type: str,
        provider: str,
        name: str,
        url: str,
        endpoint: str | None = None,
        layer_id: str | None = None,
        layer_name: str | None = None,
        license_notes: str | None = None,
        publisher: str | None = None,
    ) -> str:
        """Get-or-create a ``source_registry`` row keyed by its unique
        ``(jurisdiction_id, source_type, url)`` constraint. Returns the id."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into source_registry
                    (jurisdiction_id, source_type, provider, name, url, endpoint,
                     layer_id, layer_name, license_notes, publisher)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict (jurisdiction_id, source_type, url) do update set
                    provider = excluded.provider,
                    name = excluded.name,
                    endpoint = coalesce(excluded.endpoint, source_registry.endpoint),
                    layer_id = coalesce(excluded.layer_id, source_registry.layer_id),
                    layer_name = coalesce(excluded.layer_name, source_registry.layer_name),
                    license_notes = coalesce(excluded.license_notes, source_registry.license_notes),
                    publisher = coalesce(excluded.publisher, source_registry.publisher)
                returning id
                """,
                (
                    jurisdiction_id,
                    source_type,
                    provider,
                    name,
                    url,
                    endpoint,
                    layer_id,
                    layer_name,
                    license_notes,
                    publisher,
                ),
            )
            return str(cur.fetchone()["id"])

    def update_source_validators(
        self,
        source_registry_id: str,
        *,
        etag: str | None,
        last_modified: str | None,
        checked: bool = True,
        retrieved: bool = False,
    ) -> None:
        """Persist ETag / Last-Modified and freshness timestamps."""
        now = utc_now()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update source_registry set
                    etag = coalesce(%s, etag),
                    last_modified = coalesce(%s, last_modified),
                    last_checked_at = case when %s then %s else last_checked_at end,
                    last_retrieved_at = case when %s then %s else last_retrieved_at end
                where id = %s
                """,
                (etag, last_modified, checked, now, retrieved, now, source_registry_id),
            )

    def get_source_validators(self, source_registry_id: str) -> tuple[str | None, str | None]:
        with self._conn.cursor() as cur:
            cur.execute(
                "select etag, last_modified from source_registry where id = %s",
                (source_registry_id,),
            )
            row = cur.fetchone()
            if not row:
                return (None, None)
            return (row.get("etag"), row.get("last_modified"))

    # -- source_snapshots (immutable) ------------------------------------
    def insert_snapshot(
        self,
        *,
        source_registry_id: str,
        jurisdiction_id: str | None,
        chash: str,
        metadata: dict[str, Any],
        content_type: str = "application/json",
        http_status: int | None = 200,
        etag: str | None = None,
        last_modified: str | None = None,
        storage_path: str | None = None,
        byte_size: int | None = None,
    ) -> tuple[str, int, bool]:
        """Insert an immutable snapshot. Returns (snapshot_id, version, created).

        Dedupe: if a row with the same ``(source_registry_id, content_hash)``
        already exists it is reused (``created = False``); history is never
        rewritten (the DB also enforces this with an append-only trigger).
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                select id, version from source_snapshots
                where source_registry_id = %s and content_hash = %s
                """,
                (source_registry_id, chash),
            )
            existing = cur.fetchone()
            if existing:
                return (str(existing["id"]), int(existing["version"]), False)

            cur.execute(
                "select coalesce(max(version), 0) + 1 as v from source_snapshots "
                "where source_registry_id = %s",
                (source_registry_id,),
            )
            version = int(cur.fetchone()["v"])

            payload_bytes = json.dumps(metadata, default=str).encode("utf-8")
            cur.execute(
                """
                insert into source_snapshots
                    (source_registry_id, jurisdiction_id, version, content_hash,
                     storage_path, content_type, byte_size, http_status, etag,
                     last_modified, retrieved_at, metadata)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                returning id
                """,
                (
                    source_registry_id,
                    jurisdiction_id,
                    version,
                    chash,
                    storage_path,
                    content_type,
                    byte_size if byte_size is not None else len(payload_bytes),
                    http_status,
                    etag,
                    last_modified,
                    utc_now(),
                    Jsonb(metadata),
                ),
            )
            return (str(cur.fetchone()["id"]), version, True)

    # -- ingest_runs -----------------------------------------------------
    def start_ingest_run(
        self,
        *,
        run_type: str,
        jurisdiction_id: str | None,
        source_registry_id: str | None,
        triggered_by: str,
    ) -> str:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into ingest_runs
                    (jurisdiction_id, source_registry_id, run_type, status,
                     triggered_by, started_at)
                values (%s,%s,%s,'running',%s,%s)
                returning id
                """,
                (jurisdiction_id, source_registry_id, run_type, triggered_by, utc_now()),
            )
            run_id = str(cur.fetchone()["id"])
        self._conn.commit()
        return run_id

    def finish_ingest_run(
        self,
        run_id: str,
        *,
        status: str,
        stats: dict[str, Any] | None = None,
        error_message: str | None = None,
        processed: int = 0,
        inserted: int = 0,
        updated: int = 0,
        failed: int = 0,
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                update ingest_runs set
                    status = %s,
                    finished_at = %s,
                    records_processed = %s,
                    records_inserted = %s,
                    records_updated = %s,
                    records_failed = %s,
                    error_message = %s,
                    stats = %s
                where id = %s
                """,
                (
                    status,
                    utc_now(),
                    processed,
                    inserted,
                    updated,
                    failed,
                    error_message,
                    Jsonb(stats or {}),
                    run_id,
                ),
            )
        self._conn.commit()

    # -- feature writers -------------------------------------------------
    def replace_scope(self, table: str, source_registry_id: str) -> int:
        """Delete rows previously ingested from a given source (idempotent
        refresh for tables without a natural unique key: zoning_districts,
        overlay_features). Returns rows deleted."""
        if table not in {"zoning_districts", "overlay_features"}:
            raise ValueError(f"replace_scope not allowed for table {table}")
        with self._conn.cursor() as cur:
            cur.execute(
                f"delete from {table} where source_registry_id = %s",  # noqa: S608 - table is allowlisted
                (source_registry_id,),
            )
            return cur.rowcount

    def upsert_parcel(
        self,
        *,
        jurisdiction_id: str,
        apn: str,
        geometry_geojson: dict[str, Any] | None,
        situs_address: str | None,
        normalized_address: str | None,
        source_registry_id: str,
        source_snapshot_id: str,
        source_url: str,
        source_layer: str,
        raw_attributes: dict[str, Any],
        confidence: str,
        data_status: str,
        retrieved_at: datetime,
    ) -> str:
        """Insert or update one parcel by (jurisdiction_id, apn). Geometry,
        centroid and area_sqft are computed in PostGIS. Returns 'inserted' or
        'updated'."""
        geom_json = json.dumps(geometry_geojson) if geometry_geojson else None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                with src as (
                    select case when %(geom)s is null then null
                           else st_multi(st_setsrid(st_geomfromgeojson(%(geom)s), 4326))
                           end as g
                )
                insert into parcels
                    (jurisdiction_id, apn, situs_address, normalized_address,
                     geom, centroid, area_sqft, source_registry_id,
                     source_snapshot_id, source_url, source_layer, raw_attributes,
                     confidence, data_status, retrieved_at)
                select %(jid)s, %(apn)s, %(situs)s, %(norm)s,
                       src.g,
                       case when src.g is null then null else st_centroid(src.g) end,
                       case when src.g is null then null
                            else st_area(st_transform(src.g, %(area_srid)s)) * %(sqft)s end,
                       %(srid)s, %(snap)s, %(url)s, %(layer)s, %(raw)s,
                       %(conf)s, %(status)s, %(ret)s
                from src
                on conflict (jurisdiction_id, apn) do update set
                    situs_address = excluded.situs_address,
                    normalized_address = excluded.normalized_address,
                    geom = excluded.geom,
                    centroid = excluded.centroid,
                    area_sqft = excluded.area_sqft,
                    source_registry_id = excluded.source_registry_id,
                    source_snapshot_id = excluded.source_snapshot_id,
                    source_url = excluded.source_url,
                    source_layer = excluded.source_layer,
                    raw_attributes = excluded.raw_attributes,
                    confidence = excluded.confidence,
                    data_status = excluded.data_status,
                    retrieved_at = excluded.retrieved_at
                returning (xmax = 0) as inserted
                """,
                {
                    "geom": geom_json,
                    "jid": jurisdiction_id,
                    "apn": apn,
                    "situs": situs_address,
                    "norm": normalized_address,
                    "area_srid": _AREA_SRID,
                    "sqft": _SQM_TO_SQFT,
                    "srid": source_registry_id,
                    "snap": source_snapshot_id,
                    "url": source_url,
                    "layer": source_layer,
                    "raw": Jsonb(raw_attributes),
                    "conf": confidence,
                    "status": data_status,
                    "ret": retrieved_at,
                },
            )
            row = cur.fetchone()
            return "inserted" if row and row.get("inserted") else "updated"

    def insert_zoning_district(
        self,
        *,
        jurisdiction_id: str,
        zone_code: str,
        zone_name: str | None,
        zone_category: str | None,
        geometry_geojson: dict[str, Any] | None,
        source_registry_id: str,
        source_snapshot_id: str,
        source_url: str,
        source_layer: str,
        raw_attributes: dict[str, Any],
        confidence: str,
        data_status: str,
        retrieved_at: datetime,
    ) -> None:
        geom_json = json.dumps(geometry_geojson) if geometry_geojson else None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into zoning_districts
                    (jurisdiction_id, zone_code, zone_name, zone_category, geom,
                     source_registry_id, source_snapshot_id, source_url,
                     source_layer, raw_attributes, confidence, data_status,
                     retrieved_at)
                values (
                    %(jid)s, %(code)s, %(name)s, %(cat)s,
                    case when %(geom)s is null then null
                         else st_multi(st_setsrid(st_geomfromgeojson(%(geom)s), 4326)) end,
                    %(srid)s, %(snap)s, %(url)s, %(layer)s, %(raw)s, %(conf)s,
                    %(status)s, %(ret)s
                )
                """,
                {
                    "jid": jurisdiction_id,
                    "code": zone_code,
                    "name": zone_name,
                    "cat": zone_category,
                    "geom": geom_json,
                    "srid": source_registry_id,
                    "snap": source_snapshot_id,
                    "url": source_url,
                    "layer": source_layer,
                    "raw": Jsonb(raw_attributes),
                    "conf": confidence,
                    "status": data_status,
                    "ret": retrieved_at,
                },
            )

    def insert_overlay_feature(
        self,
        *,
        jurisdiction_id: str | None,
        overlay_type: str,
        name: str | None,
        designation: str | None,
        geometry_geojson: dict[str, Any] | None,
        raw_feature_id: str | None,
        raw_value: dict[str, Any],
        source_registry_id: str,
        source_snapshot_id: str,
        source_url: str,
        source_layer: str,
        confidence: str,
        data_status: str,
        retrieved_at: datetime,
    ) -> None:
        geom_json = json.dumps(geometry_geojson) if geometry_geojson else None
        with self._conn.cursor() as cur:
            cur.execute(
                """
                insert into overlay_features
                    (jurisdiction_id, overlay_type, name, designation, geom,
                     raw_feature_id, raw_value, source_registry_id,
                     source_snapshot_id, source_url, source_layer, confidence,
                     data_status, retrieved_at)
                values (
                    %(jid)s, %(otype)s, %(name)s, %(desig)s,
                    case when %(geom)s is null then null
                         else st_setsrid(st_geomfromgeojson(%(geom)s), 4326) end,
                    %(rfid)s, %(raw)s, %(srid)s, %(snap)s, %(url)s, %(layer)s,
                    %(conf)s, %(status)s, %(ret)s
                )
                """,
                {
                    "jid": jurisdiction_id,
                    "otype": overlay_type,
                    "name": name,
                    "desig": designation,
                    "geom": geom_json,
                    "rfid": raw_feature_id,
                    "raw": Jsonb(raw_value),
                    "srid": source_registry_id,
                    "snap": source_snapshot_id,
                    "url": source_url,
                    "layer": source_layer,
                    "conf": confidence,
                    "status": data_status,
                    "ret": retrieved_at,
                },
            )


# ---------------------------------------------------------------------------
# Ingestion context + result
# ---------------------------------------------------------------------------
@dataclass
class IngestResult:
    """Structured outcome of one source ingestion."""

    source: str
    status: str = "success"
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    failed: int = 0
    snapshot_id: str | None = None
    snapshot_version: int | None = None
    snapshot_created: bool = False
    stats: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "processed": self.processed,
            "inserted": self.inserted,
            "updated": self.updated,
            "failed": self.failed,
            "snapshot_id": self.snapshot_id,
            "snapshot_version": self.snapshot_version,
            "snapshot_created": self.snapshot_created,
            "stats": self.stats,
            "error_message": self.error_message,
        }


@dataclass
class GisContext:
    """Bundle passed to every ingester: HTTP client + DB + settings."""

    client: Any  # ingestion.arcgis.client.ArcGISClient (avoid import cycle)
    db: GISDatabase
    settings: Settings


def snapshot_metadata_for_layer(
    *,
    service_metadata: dict[str, Any],
    layer_metadata: dict[str, Any],
    query_params: dict[str, Any],
) -> dict[str, Any]:
    """Build the payload that is content-hashed for a GIS ``source_snapshot``.

    Includes only the fields that define what was queried and its shape, so the
    hash is stable across cosmetic differences but changes when the layer schema
    or query changes. Full raw metadata is kept in the snapshot ``metadata``
    jsonb for provenance.
    """
    layer_fields = [
        {"name": f.get("name"), "type": f.get("type")}
        for f in (layer_metadata.get("fields") or [])
    ]
    return {
        "service": {
            "url": service_metadata.get("service_url") or service_metadata.get("url"),
            "currentVersion": service_metadata.get("currentVersion"),
            "mapName": service_metadata.get("mapName"),
        },
        "layer": {
            "id": layer_metadata.get("id"),
            "name": layer_metadata.get("name"),
            "geometryType": layer_metadata.get("geometryType"),
            "maxRecordCount": layer_metadata.get("maxRecordCount"),
            "fields": layer_fields,
        },
        "query": query_params,
    }


def pick(props: dict[str, Any], candidates: Iterable[str]) -> Any:
    """Return the first present, non-empty value among candidate keys
    (case-insensitive)."""
    lower = {str(k).lower(): v for k, v in props.items()}
    for cand in candidates:
        val = lower.get(cand.lower())
        if val is not None and str(val).strip() != "":
            return val
    return None
