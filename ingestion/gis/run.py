"""GIS ingestion entrypoint - dispatch by source.

Usage:
    python -m ingestion.gis.run [source] [options]
    python ingestion/gis/run.py [source] [options]

    ``source`` is optional and defaults to ``all`` - so
    ``python -m ingestion.gis.run --jurisdiction los_angeles`` (the exact
    invocation used by render.yaml's cron dockerCommand and the Makefile's
    ingest-gis-la target) runs the full "all" dispatch.

Sources:
    la_zimas            LA City ZIMAS zoning (+ parcels when configured)
    la_zoning           LA City ZIMAS zoning only
    la_parcels          LA City parcels only (requires LA_PARCEL_SERVICE_URL)
    fema_flood          FEMA NFHL flood hazard zones -> overlay_features(flood)
    calfire_fhsz        CAL FIRE FHSZ -> overlay_features(fire)
    statewide_zoning    CA statewide zoning bootstrap (lower authority)
    all                 la_zimas + fema_flood + calfire_fhsz (default)

Options:
    --slug SLUG, --jurisdiction SLUG
                        target jurisdiction (statewide_zoning); also settable
                        via INGEST_JURISDICTION_SLUG. Both flag spellings are
                        accepted and equivalent.
    --max-features N    cap features per layer (smoke tests); INGEST_MAX_FEATURES
    --triggered-by WHO  recorded on ingest_runs.triggered_by (default from env)

Environment (secrets/config - never hardcoded):
    SUPABASE_DB_URL (required)   direct Postgres connection string
    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY (optional, informational)
    LA_PARCEL_SERVICE_URL, LA_PARCEL_LAYER_ID
    CA_STATEWIDE_ZONING_SERVICE_URL, CA_STATEWIDE_ZONING_LAYER_ID
    FEMA_NFHL_SERVICE_URL, FEMA_FLOOD_LAYER_ID
    CALFIRE_FHSZ_SERVICE_URL, CALFIRE_FHSZ_LAYER_IDS
    ARCGIS_HTTP_TIMEOUT, ARCGIS_RATE_LIMIT_SECONDS, ARCGIS_MAX_RETRIES
    INGEST_PAGE_SIZE, INGEST_MAX_FEATURES, INGEST_TRIGGERED_BY

Each source records an immutable, content-hashed source_snapshots row and one
ingest_runs row (status running -> success / partial / failed / skipped). The
process prints a JSON summary to stdout and exits non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Callable

# Allow ``python ingestion/gis/run.py`` (script mode) as well as ``-m``.
if __package__ in (None, ""):
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)

# Optional .env convenience for local runs (no-op in production).
try:  # pragma: no cover - import guard only
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv optional
    pass

from ingestion.arcgis.client import ArcGISClient, ArcGISUnavailableError  # noqa: E402
from ingestion.gis import calfire_fhsz, fema_flood, la_zimas, statewide_zoning  # noqa: E402
from ingestion.gis.common import (  # noqa: E402
    GISDatabase,
    GisContext,
    IngestResult,
    Settings,
)

logger = logging.getLogger("ingestion.gis.run")

# run_type recorded on ingest_runs (must satisfy the CHECK in migration 0005).
_RUN_TYPE = {
    "la_zimas": "full",
    "la_zoning": "zoning",
    "la_parcels": "parcels",
    "fema_flood": "overlays",
    "calfire_fhsz": "overlays",
    "statewide_zoning": "zoning",
}


def _run_one(
    ctx: GisContext,
    *,
    key: str,
    run_type: str,
    jurisdiction_slug: str | None,
    fn: Callable[[GisContext], IngestResult | list[IngestResult]],
) -> list[IngestResult]:
    """Wrap a single ingester call in an ingest_runs lifecycle row."""
    db = ctx.db
    jid = db.get_jurisdiction_id(jurisdiction_slug) if jurisdiction_slug else None
    run_id = db.start_ingest_run(
        run_type=run_type,
        jurisdiction_id=jid,
        source_registry_id=None,
        triggered_by=ctx.settings.triggered_by,
    )
    try:
        outcome = fn(ctx)
        results = outcome if isinstance(outcome, list) else [outcome]
    except ArcGISUnavailableError as exc:
        db.rollback()
        db.finish_ingest_run(
            run_id, status="failed", error_message=f"source unavailable: {exc}"
        )
        res = IngestResult(source=key, status="failed", error_message=str(exc))
        return [res]
    except Exception as exc:  # noqa: BLE001 - top-level run isolation
        db.rollback()
        db.finish_ingest_run(run_id, status="failed", error_message=str(exc))
        logger.exception("ingestion %s failed", key)
        res = IngestResult(source=key, status="failed", error_message=str(exc))
        return [res]

    processed = sum(r.processed for r in results)
    inserted = sum(r.inserted for r in results)
    updated = sum(r.updated for r in results)
    failed = sum(r.failed for r in results)
    statuses = {r.status for r in results}
    if "failed" in statuses:
        run_status = "failed"
    elif "partial" in statuses:
        run_status = "partial"
    elif statuses == {"skipped"}:
        run_status = "cancelled"
    else:
        run_status = "success"
    db.finish_ingest_run(
        run_id,
        status=run_status,
        stats={"results": [r.as_dict() for r in results]},
        processed=processed,
        inserted=inserted,
        updated=updated,
        failed=failed,
    )
    return results


_DISPATCH: dict[str, list[str]] = {
    "la_zimas": ["la_zimas"],
    "la_zoning": ["la_zoning"],
    "la_parcels": ["la_parcels"],
    "fema_flood": ["fema_flood"],
    "calfire_fhsz": ["calfire_fhsz"],
    "statewide_zoning": ["statewide_zoning"],
    "all": ["la_zimas", "fema_flood", "calfire_fhsz"],
}


def _dispatch_one(ctx: GisContext, key: str) -> list[IngestResult]:
    if key == "la_zimas":
        return _run_one(
            ctx,
            key=key,
            run_type=_RUN_TYPE[key],
            jurisdiction_slug=la_zimas.JURISDICTION_SLUG,
            fn=la_zimas.ingest,
        )
    if key == "la_zoning":
        return _run_one(
            ctx,
            key=key,
            run_type=_RUN_TYPE[key],
            jurisdiction_slug=la_zimas.JURISDICTION_SLUG,
            fn=la_zimas.ingest_zoning,
        )
    if key == "la_parcels":
        return _run_one(
            ctx,
            key=key,
            run_type=_RUN_TYPE[key],
            jurisdiction_slug=la_zimas.JURISDICTION_SLUG,
            fn=la_zimas.ingest_parcels,
        )
    if key == "fema_flood":
        return _run_one(
            ctx, key=key, run_type=_RUN_TYPE[key], jurisdiction_slug=None, fn=fema_flood.ingest
        )
    if key == "calfire_fhsz":
        return _run_one(
            ctx, key=key, run_type=_RUN_TYPE[key], jurisdiction_slug=None, fn=calfire_fhsz.ingest
        )
    if key == "statewide_zoning":
        return _run_one(
            ctx,
            key=key,
            run_type=_RUN_TYPE[key],
            jurisdiction_slug=ctx.settings.target_jurisdiction_slug,
            fn=statewide_zoning.ingest,
        )
    raise ValueError(f"unknown source key: {key}")


def build_context(settings: Settings) -> GisContext:
    client = ArcGISClient(
        timeout=settings.http_timeout,
        rate_limit_seconds=settings.rate_limit_seconds,
        max_retries=settings.max_retries,
    )
    db = GISDatabase(settings.db_url)
    return GisContext(client=client, db=db, settings=settings)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="ADU Atlas GIS ingestion")
    parser.add_argument(
        "source",
        nargs="?",
        default="all",
        choices=sorted(_DISPATCH.keys()),
        help="Ingestion source to run (default: all).",
    )
    # --jurisdiction is accepted as an alias for --slug: the Render cron
    # service (render.yaml), the Dockerfile.ingestion documented contract,
    # and the Makefile's ingest-gis-la target all invoke this entrypoint as
    # `python -m ingestion.gis.run --jurisdiction <slug>` with no positional
    # source (relying on the "all" default above). Both flags set the same
    # target jurisdiction slug.
    parser.add_argument("--slug", "--jurisdiction", dest="slug", default=None)
    parser.add_argument("--max-features", dest="max_features", type=int, default=None)
    parser.add_argument("--triggered-by", dest="triggered_by", default=None)
    args = parser.parse_args(argv)

    # CLI overrides flow through the environment so Settings stays the single
    # source of truth.
    if args.slug:
        os.environ["INGEST_JURISDICTION_SLUG"] = args.slug
    if args.max_features is not None:
        os.environ["INGEST_MAX_FEATURES"] = str(args.max_features)
    if args.triggered_by:
        os.environ["INGEST_TRIGGERED_BY"] = args.triggered_by

    settings = Settings.from_env()
    ctx = build_context(settings)

    all_results: list[IngestResult] = []
    try:
        for key in _DISPATCH[args.source]:
            all_results.extend(_dispatch_one(ctx, key))
    finally:
        ctx.client.close()
        ctx.db.close()

    summary = {
        "source": args.source,
        "results": [r.as_dict() for r in all_results],
    }
    print(json.dumps(summary, indent=2, default=str))

    # Exit non-zero if anything failed (skipped / partial are not hard failures).
    if any(r.status == "failed" for r in all_results):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
