"""California statewide zoning bootstrap ingestion (LOWER AUTHORITY).

Source: California statewide zoning dataset (data.ca.gov lab). This is a
BOOTSTRAP source only. Local jurisdiction zoning (e.g. LA ZIMAS) always wins
where it has been ingested. This module exists so that jurisdictions not yet on
their own official GIS have *something* to reason about, clearly marked as lower
authority and never production-authoritative.

Guardrails baked in:
- Every row is written with confidence='low' and data_status='needs_review'.
- zone_category is prefixed 'statewide_bootstrap' and raw_attributes records
  authority_rank=5 plus an explicit is_bootstrap flag, so the rule engine and
  QA can see this is not a local adopted source.
- The target jurisdiction MUST be provided (INGEST_JURISDICTION_SLUG or --slug)
  and MUST NOT be a production jurisdiction; production jurisdictions have their
  own local zoning and refuse the bootstrap to avoid overwriting authority.
- The service URL is not hardcoded (sources.yaml lists it null): it is supplied
  via CA_STATEWIDE_ZONING_SERVICE_URL. Without it, the ingester exits as
  'skipped' rather than guessing.

Written to zoning_districts (which requires a non-null jurisdiction_id), scoped
to the target jurisdiction's boundary via an envelope filter when a boundary is
available.
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

_ZONE_CODE_FIELDS = ("ZONE_CODE", "ZONING", "ZONE", "ZONE_CMPLT", "GEN_CLASS", "zoning")
_ZONE_NAME_FIELDS = ("ZONE_NAME", "DESCRIPTION", "ZONE_DESC", "GEN_DESC", "zdescr")
_AUTHORITY_RANK = 5


def _resolve_layer(ctx: GisContext, service: str) -> LayerRef:
    if ctx.settings.statewide_zoning_layer_id is not None:
        return ctx.client.layer_ref(service, ctx.settings.statewide_zoning_layer_id)
    return ctx.client.find_layer(
        service,
        any_fields=_ZONE_CODE_FIELDS,
        geometry_types=("esriGeometryPolygon",),
        preferred_ids=(0,),
    )


def _boundary_envelope(db, jurisdiction_id: str) -> dict | None:
    """Return an Esri envelope (WGS84) for the jurisdiction boundary, if set."""
    with db.conn.cursor() as cur:
        cur.execute(
            """
            select st_xmin(env) as xmin, st_ymin(env) as ymin,
                   st_xmax(env) as xmax, st_ymax(env) as ymax
            from (
                select st_envelope(boundary::geometry) as env
                from jurisdictions where id = %s and boundary is not null
            ) e
            """,
            (jurisdiction_id,),
        )
        row = cur.fetchone()
    if not row or row.get("xmin") is None:
        return None
    return {
        "type": "esriGeometryEnvelope",
        "geometry": {
            "xmin": row["xmin"],
            "ymin": row["ymin"],
            "xmax": row["xmax"],
            "ymax": row["ymax"],
        },
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
    }


def ingest(ctx: GisContext) -> IngestResult:
    result = IngestResult(source="ca_statewide_zoning")
    db = ctx.db
    service = ctx.settings.statewide_zoning_service_url

    if not service:
        result.status = "skipped"
        result.error_message = (
            "CA_STATEWIDE_ZONING_SERVICE_URL is not set. The statewide zoning "
            "bootstrap requires an explicit ArcGIS feature-service URL "
            "(sources.yaml lists it as null). Skipping rather than guessing."
        )
        result.stats = {"reason": "service_url_not_configured"}
        logger.warning(result.error_message)
        return result

    slug = ctx.settings.target_jurisdiction_slug
    if not slug:
        result.status = "skipped"
        result.error_message = (
            "No target jurisdiction. Set INGEST_JURISDICTION_SLUG (or pass "
            "--slug) - the statewide bootstrap writes zoning_districts scoped to "
            "one jurisdiction."
        )
        result.stats = {"reason": "no_target_jurisdiction"}
        logger.warning(result.error_message)
        return result

    jid = db.require_jurisdiction_id(slug)

    # Refuse to bootstrap a production jurisdiction: it has authoritative local
    # zoning and the bootstrap must never overwrite / dilute that authority.
    with db.conn.cursor() as cur:
        cur.execute("select coverage_status from jurisdictions where id = %s", (jid,))
        cov = (cur.fetchone() or {}).get("coverage_status")
    if cov == "production":
        result.status = "skipped"
        result.error_message = (
            f"Jurisdiction '{slug}' is production; it has authoritative local "
            f"zoning. Refusing to apply the lower-authority statewide bootstrap "
            f"(local source always wins)."
        )
        result.stats = {"reason": "production_jurisdiction", "coverage_status": cov}
        logger.warning(result.error_message)
        return result

    service_meta = ctx.client.service_metadata(service)
    try:
        layer = _resolve_layer(ctx, service)
    except LayerNotFoundError as exc:
        raise RuntimeError(
            f"No statewide zoning polygon layer found in {service}: {exc}"
        ) from exc

    layer_meta = ctx.client.layer_metadata(service, layer.layer_id)
    source_layer = f"{service}/{layer.layer_id} ({layer.name})"

    source_registry_id = db.ensure_source_registry(
        jurisdiction_id=None,  # statewide source; not owned by one jurisdiction
        source_type="gis_zoning",
        provider="ca_open_data",
        name="California statewide zoning (bootstrap only)",
        url=service,
        endpoint=service,
        layer_id=str(layer.layer_id),
        layer_name=layer.name,
        license_notes=(
            "California statewide zoning bootstrap (data.ca.gov). Lower authority "
            "than local adopted zoning; local source always wins where ingested. "
            f"authority_rank={_AUTHORITY_RANK}. Never authoritative for a "
            "production jurisdiction."
        ),
        publisher="ca_open_data",
    )

    envelope = _boundary_envelope(db, jid)
    query_params = {
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": True,
        "outSR": 4326,
        "f": "geojson",
        "geometry_filter": "jurisdiction_boundary_envelope" if envelope else "none",
        "target_jurisdiction": slug,
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
    retrieved_at = utc_now()

    db.replace_scope("zoning_districts", source_registry_id)

    try:
        for feat in ctx.client.query_all(
            service,
            layer.layer_id,
            page_size=ctx.settings.page_size,
            max_features=ctx.settings.max_features,
            geometry=envelope,
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
            raw = dict(props)
            raw["_is_bootstrap"] = True
            raw["_authority_rank"] = _AUTHORITY_RANK
            try:
                db.insert_zoning_district(
                    jurisdiction_id=jid,
                    zone_code=str(zone_code),
                    zone_name=str(zone_name) if zone_name is not None else None,
                    zone_category="statewide_bootstrap",
                    geometry_geojson=geom,
                    source_registry_id=source_registry_id,
                    source_snapshot_id=snap_id,
                    source_url=service,
                    source_layer=source_layer,
                    raw_attributes=raw,
                    confidence="low",
                    data_status="needs_review",
                    retrieved_at=retrieved_at,
                )
                result.inserted += 1
            except Exception as exc:  # noqa: BLE001 - per-feature isolation
                logger.warning("statewide zoning insert failed: %s", exc)
                result.failed += 1
        db.commit()
    except ArcGISError:
        db.rollback()
        raise

    result.stats = {
        "layer_id": layer.layer_id,
        "target_jurisdiction": slug,
        "authority_rank": _AUTHORITY_RANK,
        "scoped_to_boundary": envelope is not None,
    }
    result.status = "success" if result.failed == 0 else "partial"
    return result
