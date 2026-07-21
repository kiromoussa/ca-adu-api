"""FEMA National Flood Hazard Layer (NFHL) ingestion.

Source: FEMA NFHL public ArcGIS MapServer. The "Flood Hazard Zones" layer
(default id 28, confirmed via ?f=pjson) carries the regulatory flood-zone
polygons. Fields preserved verbatim into overlay_features.raw_value:

  FLD_ZONE   the flood zone (A, AE, AH, AO, VE, X, D, ...)
  ZONE_SUBTY zone subtype (e.g. "0.2 PCT ANNUAL CHANCE FLOOD HAZARD")
  SFHA_TF    Special Flood Hazard Area true/false
  DFIRM_ID   DFIRM (map) id
  STATIC_BFE base flood elevation
  FLD_AR_ID  flood area id (feature id preserved verbatim)

Rows land in overlay_features with overlay_type='flood'. FEMA is federal
statewide data, so jurisdiction_id is NULL (national layer). raw flood-zone
values are never normalized away, and a "no feature" result is distinguished
from a "source unavailable" failure: an ArcGISUnavailableError propagates and
the ingest_runs row is marked failed instead of "ingested zero".

For a national service we scope the pull to California by default via an
envelope spatial filter (config-overridable) so we do not attempt to download
the entire country.
"""

from __future__ import annotations

import logging

from ..arcgis.client import ArcGISError, LayerNotFoundError, LayerRef
from .common import (
    GisContext,
    IngestResult,
    content_hash,
    pick,
    snapshot_metadata_for_layer,
    utc_now,
)

logger = logging.getLogger(__name__)

OVERLAY_TYPE = "flood"

_FLD_ZONE_FIELDS = ("FLD_ZONE",)
_ZONE_SUBTY_FIELDS = ("ZONE_SUBTY",)
_FEATURE_ID_FIELDS = ("FLD_AR_ID", "GFID", "DFIRM_ID", "OBJECTID")

# Rough bounding box of California (WGS84) used to scope the national layer.
_CA_ENVELOPE = {
    "type": "esriGeometryEnvelope",
    "geometry": {"xmin": -124.5, "ymin": 32.5, "xmax": -114.1, "ymax": 42.1},
    "inSR": 4326,
    "spatialRel": "esriSpatialRelIntersects",
}

_LICENSE = (
    "FEMA National Flood Hazard Layer (NFHL). US Government work, public domain. "
    "Updated monthly. Raw flood-zone values preserved; immutable snapshots kept."
)


def _resolve_layer(ctx: GisContext) -> LayerRef:
    service = ctx.settings.fema_service_url
    layer_id = ctx.settings.fema_flood_layer_id
    try:
        ref = ctx.client.layer_ref(service, layer_id)
        if ref.geometry_type and "polygon" in ref.geometry_type.lower() and (
            ref.first_field(_FLD_ZONE_FIELDS)
        ):
            return ref
    except ArcGISError:
        logger.debug("configured FEMA layer %s not usable; discovering", layer_id)
    # Fall back to discovery by field.
    return ctx.client.find_layer(
        service,
        required_fields=_FLD_ZONE_FIELDS,
        geometry_types=("esriGeometryPolygon",),
        preferred_ids=(layer_id,),
    )


def ingest(ctx: GisContext) -> IngestResult:
    result = IngestResult(source="fema_nfhl")
    db = ctx.db
    service = ctx.settings.fema_service_url

    service_meta = ctx.client.service_metadata(service)
    try:
        layer = _resolve_layer(ctx)
    except LayerNotFoundError as exc:
        raise RuntimeError(
            f"No FEMA flood-hazard polygon layer found in {service}: {exc}"
        ) from exc

    layer_meta = ctx.client.layer_metadata(service, layer.layer_id)
    source_layer = f"{service}/{layer.layer_id} ({layer.name})"

    source_registry_id = db.ensure_source_registry(
        jurisdiction_id=None,
        source_type="gis_overlay",
        provider="fema",
        name="FEMA National Flood Hazard Layer (NFHL)",
        url=service,
        endpoint=service,
        layer_id=str(layer.layer_id),
        layer_name=layer.name,
        license_notes=_LICENSE,
        publisher="fema",
    )

    query_params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": True,
        "outSR": 4326,
        "f": "geojson",
        "geometry_filter": "california_envelope",
    }
    snap_payload = snapshot_metadata_for_layer(
        service_metadata={"service_url": service, **service_meta.raw},
        layer_metadata=layer_meta,
        query_params=query_params,
    )
    chash = content_hash(snap_payload)
    snap_id, version, created = db.insert_snapshot(
        source_registry_id=source_registry_id,
        jurisdiction_id=None,
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

    zone_field = layer.first_field(_FLD_ZONE_FIELDS)
    subty_field = layer.first_field(_ZONE_SUBTY_FIELDS)
    fid_field = layer.first_field(_FEATURE_ID_FIELDS)
    retrieved_at = utc_now()

    # Idempotent refresh scoped to this source.
    db.replace_scope("overlay_features", source_registry_id)

    # ArcGISUnavailableError intentionally NOT caught here: an unreachable
    # source must fail the run, never masquerade as "no flood features".
    try:
        for feat in ctx.client.query_all(
            service,
            layer.layer_id,
            page_size=ctx.settings.page_size,
            max_features=ctx.settings.max_features,
            geometry=_CA_ENVELOPE,
            order_by="OBJECTID",
        ):
            result.processed += 1
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            fld_zone = pick(props, (zone_field,) if zone_field else _FLD_ZONE_FIELDS)
            subty = pick(props, (subty_field,) if subty_field else _ZONE_SUBTY_FIELDS)
            designation = str(fld_zone) if fld_zone is not None else None
            if designation and subty:
                designation = f"{designation} ({subty})"
            raw_fid = pick(props, (fid_field,) if fid_field else _FEATURE_ID_FIELDS)
            try:
                db.insert_overlay_feature(
                    jurisdiction_id=None,
                    overlay_type=OVERLAY_TYPE,
                    name="FEMA Flood Hazard Zone",
                    designation=designation,
                    geometry_geojson=geom,
                    raw_feature_id=str(raw_fid) if raw_fid is not None else None,
                    raw_value=props,
                    source_registry_id=source_registry_id,
                    source_snapshot_id=snap_id,
                    source_url=service,
                    source_layer=source_layer,
                    confidence="high",
                    data_status="current",
                    retrieved_at=retrieved_at,
                )
                result.inserted += 1
            except Exception as exc:  # noqa: BLE001 - per-feature isolation
                logger.warning("flood feature insert failed: %s", exc)
                result.failed += 1
        db.commit()
    except ArcGISError:
        db.rollback()
        raise

    result.stats = {
        "layer_id": layer.layer_id,
        "layer_name": layer.name,
        "fld_zone_field": zone_field,
        "scope": "california_envelope",
    }
    result.status = "success" if result.failed == 0 else "partial"
    return result
