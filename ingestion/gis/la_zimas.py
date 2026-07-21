"""LA City ZIMAS ingestion: parcels + zoning districts.

Source: LA City Zone Information and Map Access System (ZIMAS) ArcGIS REST
service. This is the *City of Los Angeles* authoritative parcel/zoning source.

    Do NOT substitute unincorporated LA County zoning for LA City. That is a
    trust non-negotiable. This module only ever reads from the configured LA
    City ZIMAS service (and an explicitly configured LA City parcel service).

Confirmed via live metadata (?f=pjson) on the ZIMAS MapServer:

- Zoning is a Feature Layer (default id 1102, group "Zoning") with fields:
  ZONE_CMPLT (complete zone string, e.g. "R1-1"), ZONE_CLASS, ZONE_CODE,
  ZONELEGEND. Native SR is EPSG:2229 (NAD83 CA State Plane V, US feet); we
  request f=geojson (always WGS84) with outSR=4326.
- The ZIMAS MapServer does NOT expose a parcel-polygon layer carrying an APN /
  PIN attribute (its "lotlines" layers are polylines). Parcel geometry with an
  APN therefore comes from an explicitly configured LA City parcel feature
  service (LA_PARCEL_SERVICE_URL / LA_PARCEL_LAYER_ID). If none is configured we
  do NOT fall back to any County layer - we record the gap and skip parcels,
  distinguishing "not configured" from "ingested zero".

Both writers create an immutable, content-hashed source_snapshot (hash of the
layer metadata + query params) and are wrapped in an ingest_runs row by run.py.
"""

from __future__ import annotations

import logging

from ..arcgis.client import (
    ArcGISError,
    ArcGISUnavailableError,
    LayerNotFoundError,
    LayerRef,
)
from .common import (
    GisContext,
    IngestResult,
    content_hash,
    pick,
    snapshot_metadata_for_layer,
    utc_now,
)

logger = logging.getLogger(__name__)

JURISDICTION_SLUG = "los_angeles"

# Candidate field names (case-insensitive) for discovery / extraction.
_ZONE_CODE_FIELDS = ("ZONE_CMPLT", "ZONE_CLASS", "ZONE_CODE", "ZONE", "ZONING")
_ZONE_NAME_FIELDS = ("ZONELEGEND", "ZONE_DESC", "DESCRIPTION", "ZONE_NAME")
_ZONE_CLASS_FIELDS = ("ZONE_CLASS", "ZONE_CMPLT", "CATEGORY")
_APN_FIELDS = ("APN", "AIN", "PIN", "PIN_NUM", "ASSESSOR_ID", "AsmtParcelNbr")
_ADDRESS_FIELDS = (
    "SitusAddress",
    "SITUS_ADDR",
    "SITUS_ADDRESS",
    "ADDRESS",
    "SITE_ADDR",
    "FullAddress",
)

_PREFERRED_ZONING_LAYER_IDS = (1102, 1101)

_LICENSE = (
    "LA City ZIMAS (Zone Information and Map Access System). Official City of "
    "Los Angeles parcel/zoning service. Not a substitute for LA County zoning. "
    "Public records; immutable content-hashed snapshots preserved."
)


def _discover_zoning_layer(ctx: GisContext) -> LayerRef:
    service = ctx.settings.la_zimas_service_url
    return ctx.client.find_layer(
        service,
        any_fields=_ZONE_CODE_FIELDS,
        geometry_types=("esriGeometryPolygon",),
        preferred_ids=_PREFERRED_ZONING_LAYER_IDS,
    )


def _discover_parcel_layer(ctx: GisContext) -> LayerRef | None:
    """Resolve the LA City parcel layer.

    Only uses an explicitly configured parcel service (LA_PARCEL_SERVICE_URL).
    Returns None when no parcel source is configured - we never guess a County
    layer. If a service is configured but no APN-bearing polygon layer is found,
    raises LayerNotFoundError so the misconfiguration is visible.
    """
    service = ctx.settings.la_parcel_service_url
    if not service:
        return None
    if ctx.settings.la_parcel_layer_id is not None:
        ref = ctx.client.layer_ref(service, ctx.settings.la_parcel_layer_id)
        return ref
    return ctx.client.find_layer(
        service,
        any_fields=_APN_FIELDS,
        geometry_types=("esriGeometryPolygon",),
    )


# ---------------------------------------------------------------------------
# Zoning
# ---------------------------------------------------------------------------
def ingest_zoning(ctx: GisContext) -> IngestResult:
    result = IngestResult(source="la_zimas_zoning")
    db = ctx.db
    jid = db.require_jurisdiction_id(JURISDICTION_SLUG)
    service = ctx.settings.la_zimas_service_url

    try:
        service_meta = ctx.client.service_metadata(service)
        layer = _discover_zoning_layer(ctx)
    except LayerNotFoundError as exc:
        raise RuntimeError(
            f"No ZIMAS zoning polygon layer found in {service}: {exc}"
        ) from exc

    layer_meta = ctx.client.layer_metadata(service, layer.layer_id)
    source_layer = f"{service}/{layer.layer_id} ({layer.name})"

    source_registry_id = db.ensure_source_registry(
        jurisdiction_id=jid,
        source_type="gis_zoning",
        provider="arcgis",
        name="LA City ZIMAS zoning districts (ArcGIS REST)",
        url=service,
        endpoint=service,
        layer_id=str(layer.layer_id),
        layer_name=layer.name,
        license_notes=_LICENSE,
        publisher="city_gis",
    )

    query_params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": True,
        "outSR": 4326,
        "f": "geojson",
    }
    snap_payload = snapshot_metadata_for_layer(
        service_metadata={"service_url": service, **service_meta.raw},
        layer_metadata=layer_meta,
        query_params=query_params,
    )
    chash = content_hash(snap_payload)
    snap_id, version, created = db.insert_snapshot(
        source_registry_id=source_registry_id,
        jurisdiction_id=jid,
        chash=chash,
        metadata=snap_payload,
        etag=service_meta.etag,
        last_modified=service_meta.last_modified,
    )
    result.snapshot_id, result.snapshot_version, result.snapshot_created = (
        snap_id,
        version,
        created,
    )
    db.update_source_validators(
        source_registry_id,
        etag=service_meta.etag,
        last_modified=service_meta.last_modified,
        checked=True,
        retrieved=True,
    )

    code_field = layer.first_field(_ZONE_CODE_FIELDS)
    name_field = layer.first_field(_ZONE_NAME_FIELDS)
    class_field = layer.first_field(_ZONE_CLASS_FIELDS)
    retrieved_at = utc_now()

    # Idempotent refresh: clear this source's prior districts, then insert fresh.
    db.replace_scope("zoning_districts", source_registry_id)

    try:
        for feat in ctx.client.query_all(
            service,
            layer.layer_id,
            page_size=ctx.settings.page_size,
            max_features=ctx.settings.max_features,
            order_by="OBJECTID",
        ):
            result.processed += 1
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            zone_code = pick(props, (code_field,) if code_field else _ZONE_CODE_FIELDS)
            if zone_code is None:
                result.failed += 1
                continue
            zone_name = pick(props, (name_field,) if name_field else _ZONE_NAME_FIELDS)
            zone_cat = pick(props, (class_field,) if class_field else _ZONE_CLASS_FIELDS)
            try:
                db.insert_zoning_district(
                    jurisdiction_id=jid,
                    zone_code=str(zone_code),
                    zone_name=str(zone_name) if zone_name is not None else None,
                    zone_category=str(zone_cat) if zone_cat is not None else None,
                    geometry_geojson=geom,
                    source_registry_id=source_registry_id,
                    source_snapshot_id=snap_id,
                    source_url=service,
                    source_layer=source_layer,
                    raw_attributes=props,
                    confidence="high",
                    data_status="current",
                    retrieved_at=retrieved_at,
                )
                result.inserted += 1
            except Exception as exc:  # noqa: BLE001 - per-feature isolation
                logger.warning("zoning feature insert failed: %s", exc)
                result.failed += 1
        db.commit()
    except ArcGISUnavailableError:
        db.rollback()
        raise
    except ArcGISError:
        db.rollback()
        raise

    result.stats = {
        "layer_id": layer.layer_id,
        "layer_name": layer.name,
        "zone_code_field": code_field,
        "zone_name_field": name_field,
    }
    result.status = "success" if result.failed == 0 else "partial"
    return result


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------
def ingest_parcels(ctx: GisContext) -> IngestResult:
    result = IngestResult(source="la_zimas_parcels")
    db = ctx.db
    jid = db.require_jurisdiction_id(JURISDICTION_SLUG)

    layer = _discover_parcel_layer(ctx)
    if layer is None:
        # Honest gap: no LA City parcel service configured. Do NOT use County.
        result.status = "skipped"
        result.error_message = (
            "No LA City parcel service configured. Set LA_PARCEL_SERVICE_URL "
            "(and optionally LA_PARCEL_LAYER_ID) to an official City of Los "
            "Angeles parcel feature service exposing an APN/PIN field. The "
            "ZIMAS MapServer does not expose parcel polygons, and LA County "
            "parcels are not a permitted substitute."
        )
        result.stats = {"reason": "parcel_source_not_configured"}
        logger.warning(result.error_message)
        return result

    service = ctx.settings.la_parcel_service_url
    layer_meta = ctx.client.layer_metadata(service, layer.layer_id)
    source_layer = f"{service}/{layer.layer_id} ({layer.name})"

    apn_field = layer.first_field(_APN_FIELDS)
    if apn_field is None:
        raise RuntimeError(
            f"Configured LA parcel layer {source_layer} has no APN/PIN field "
            f"(looked for {_APN_FIELDS}). Refusing to ingest parcels without an "
            f"APN."
        )
    address_field = layer.first_field(_ADDRESS_FIELDS)

    source_registry_id = db.ensure_source_registry(
        jurisdiction_id=jid,
        source_type="gis_parcel",
        provider="arcgis",
        name="LA City parcels (ArcGIS REST)",
        url=service,
        endpoint=service,
        layer_id=str(layer.layer_id),
        layer_name=layer.name,
        license_notes=_LICENSE,
        publisher="city_gis",
    )

    query_params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": True,
        "outSR": 4326,
        "f": "geojson",
    }
    snap_payload = snapshot_metadata_for_layer(
        service_metadata={"service_url": service},
        layer_metadata=layer_meta,
        query_params=query_params,
    )
    chash = content_hash(snap_payload)
    parcel_etag = getattr(ctx.client, "last_etag", None)
    parcel_last_modified = getattr(ctx.client, "last_modified", None)
    snap_id, version, created = db.insert_snapshot(
        source_registry_id=source_registry_id,
        jurisdiction_id=jid,
        chash=chash,
        metadata=snap_payload,
        etag=parcel_etag,
        last_modified=parcel_last_modified,
    )
    result.snapshot_id, result.snapshot_version, result.snapshot_created = (
        snap_id,
        version,
        created,
    )
    db.update_source_validators(
        source_registry_id,
        etag=parcel_etag,
        last_modified=parcel_last_modified,
        checked=True,
        retrieved=True,
    )

    retrieved_at = utc_now()
    try:
        for feat in ctx.client.query_all(
            service,
            layer.layer_id,
            page_size=ctx.settings.page_size,
            max_features=ctx.settings.max_features,
            order_by=apn_field,
        ):
            result.processed += 1
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            apn = pick(props, (apn_field,))
            if apn is None:
                result.failed += 1
                continue
            situs = pick(props, (address_field,) if address_field else _ADDRESS_FIELDS)
            situs_str = str(situs) if situs is not None else None
            try:
                action = db.upsert_parcel(
                    jurisdiction_id=jid,
                    apn=str(apn),
                    geometry_geojson=geom,
                    situs_address=situs_str,
                    normalized_address=situs_str.upper() if situs_str else None,
                    source_registry_id=source_registry_id,
                    source_snapshot_id=snap_id,
                    source_url=service,
                    source_layer=source_layer,
                    raw_attributes=props,
                    confidence="high",
                    data_status="current",
                    retrieved_at=retrieved_at,
                )
                if action == "inserted":
                    result.inserted += 1
                else:
                    result.updated += 1
            except Exception as exc:  # noqa: BLE001 - per-feature isolation
                logger.warning("parcel upsert failed for APN %s: %s", apn, exc)
                result.failed += 1
        db.commit()
    except ArcGISError:
        db.rollback()
        raise

    result.stats = {
        "layer_id": layer.layer_id,
        "layer_name": layer.name,
        "apn_field": apn_field,
        "address_field": address_field,
    }
    result.status = "success" if result.failed == 0 else "partial"
    return result


def ingest(ctx: GisContext) -> list[IngestResult]:
    """Ingest LA ZIMAS zoning then parcels. Zoning always runs; parcels run
    only when a City parcel service is configured."""
    results = [ingest_zoning(ctx)]
    results.append(ingest_parcels(ctx))
    return results
