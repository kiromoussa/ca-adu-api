"""CAL FIRE / OSFM Fire Hazard Severity Zone (FHSZ) ingestion.

Source: CAL FIRE / Office of the State Fire Marshal Fire Hazard Severity Zones,
hosted on the California state GIS ArcGIS MapServer. Confirmed via ?f=pjson the
service exposes responsibility-area layers:

  0  State Responsibility Areas (SRA), Severity   fields: SRA, HAZ_CODE, HAZ_CLASS
  1  Local Responsibility Areas (LRA)             fields: SRA, INCORP, HAZ_CODE,
                                                            HAZ_CLASS, VH_REC, ...

Both are polygons. Native SR is EPSG:3857; we request f=geojson (WGS84) with
outSR=4326. Every FHSZ polygon lands in overlay_features with
overlay_type='fire', preserving the raw hazard class (Moderate / High / Very
High), hazard code, and SRA/LRA responsibility flag in raw_value. A "no hit"
is distinguished from a "source unavailable" failure (the latter propagates and
fails the ingest_runs row).

By default both SRA (0) and LRA (1) responsibility-area layers are ingested;
override with CALFIRE_FHSZ_LAYER_IDS (comma-separated) if needed.
"""

from __future__ import annotations

import logging
import os

from ..arcgis.client import ArcGISError, LayerRef
from .common import (
    GisContext,
    IngestResult,
    content_hash,
    pick,
    snapshot_metadata_for_layer,
    utc_now,
)

logger = logging.getLogger(__name__)

OVERLAY_TYPE = "fire"

_HAZ_CLASS_FIELDS = ("HAZ_CLASS", "FHSZ", "FHSZ_lyr", "SEVERITY")
_HAZ_CODE_FIELDS = ("HAZ_CODE",)
_SRA_FIELDS = ("SRA",)
_FEATURE_ID_FIELDS = ("OBJECTID", "OBJECTID_1")

_DEFAULT_LAYER_IDS = (0, 1)

_LICENSE = (
    "CAL FIRE / Office of the State Fire Marshal Fire Hazard Severity Zones, "
    "hosted on the California state GIS service. California open data. Raw "
    "hazard class and responsibility area preserved; immutable snapshots kept."
)


def _layer_ids() -> tuple[int, ...]:
    raw = os.environ.get("CALFIRE_FHSZ_LAYER_IDS", "").strip()
    if not raw:
        return _DEFAULT_LAYER_IDS
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                logger.warning("ignoring non-integer CALFIRE_FHSZ_LAYER_IDS entry: %s", part)
    return tuple(ids) or _DEFAULT_LAYER_IDS


def ingest(ctx: GisContext) -> IngestResult:
    result = IngestResult(source="calfire_fhsz")
    db = ctx.db
    service = ctx.settings.calfire_service_url

    service_meta = ctx.client.service_metadata(service)
    source_registry_id = db.ensure_source_registry(
        jurisdiction_id=None,
        source_type="gis_overlay",
        provider="cal_fire",
        name="CAL FIRE / OSFM Fire Hazard Severity Zones (FHSZ)",
        url=service,
        endpoint=service,
        layer_id=",".join(str(i) for i in _layer_ids()),
        layer_name="Fire Hazard Severity Zones",
        license_notes=_LICENSE,
        publisher="cal_fire",
    )

    # Resolve the target layers, keeping only usable polygon layers.
    layers: list[LayerRef] = []
    for lid in _layer_ids():
        try:
            ref = ctx.client.layer_ref(service, lid)
        except ArcGISError as exc:
            logger.warning("CAL FIRE layer %s unavailable: %s", lid, exc)
            continue
        if ref.geometry_type and "polygon" in ref.geometry_type.lower():
            layers.append(ref)
        else:
            logger.warning("CAL FIRE layer %s is not a polygon layer; skipping", lid)
    if not layers:
        raise RuntimeError(
            f"No usable CAL FIRE FHSZ polygon layers found in {service} "
            f"(tried ids {_layer_ids()})."
        )

    # Build one immutable snapshot covering every ingested layer.
    layer_metas = {
        ref.layer_id: ctx.client.layer_metadata(service, ref.layer_id) for ref in layers
    }
    query_params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": True,
        "outSR": 4326,
        "f": "geojson",
        "layers": [ref.layer_id for ref in layers],
    }
    snap_payload = {
        "service": {
            "url": service,
            "currentVersion": service_meta.current_version,
            "mapName": service_meta.raw.get("mapName"),
        },
        "layers": [
            snapshot_metadata_for_layer(
                service_metadata={"service_url": service},
                layer_metadata=layer_metas[ref.layer_id],
                query_params=query_params,
            )["layer"]
            for ref in layers
        ],
        "query": query_params,
    }
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

    retrieved_at = utc_now()
    # Idempotent refresh across all layers for this source, once.
    db.replace_scope("overlay_features", source_registry_id)

    per_layer: dict[int, int] = {}
    try:
        for ref in layers:
            haz_class_field = ref.first_field(_HAZ_CLASS_FIELDS)
            sra_field = ref.first_field(_SRA_FIELDS)
            fid_field = ref.first_field(_FEATURE_ID_FIELDS)
            source_layer = f"{service}/{ref.layer_id} ({ref.name})"
            count_before = result.inserted
            for feat in ctx.client.query_all(
                service,
                ref.layer_id,
                page_size=ctx.settings.page_size,
                max_features=ctx.settings.max_features,
                order_by=fid_field or "OBJECTID",
            ):
                result.processed += 1
                props = feat.get("properties") or {}
                geom = feat.get("geometry")
                haz_class = pick(
                    props, (haz_class_field,) if haz_class_field else _HAZ_CLASS_FIELDS
                )
                sra = pick(props, (sra_field,) if sra_field else _SRA_FIELDS)
                designation = str(haz_class) if haz_class is not None else None
                if designation and sra:
                    designation = f"{designation} ({sra})"
                raw_fid = pick(props, (fid_field,) if fid_field else _FEATURE_ID_FIELDS)
                try:
                    db.insert_overlay_feature(
                        jurisdiction_id=None,
                        overlay_type=OVERLAY_TYPE,
                        name=f"CAL FIRE FHSZ - {ref.name}",
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
                    logger.warning("fire feature insert failed: %s", exc)
                    result.failed += 1
            per_layer[ref.layer_id] = result.inserted - count_before
        db.commit()
    except ArcGISError:
        db.rollback()
        raise

    result.stats = {
        "layers": [ref.layer_id for ref in layers],
        "per_layer_inserted": per_layer,
    }
    result.status = "success" if result.failed == 0 else "partial"
    return result
