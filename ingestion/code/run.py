"""OFFLINE entrypoint for municipal-code ingestion + extraction + QA.

This is an OFFLINE worker (run on Render as a scheduled job or locally). It must
NEVER be invoked on the API request path - the request path is deterministic
(versioned rules + PostGIS + source-linked data), no LLM.

Stages:
  ingest    scrape municipal code -> immutable source_snapshots + zoning_sections
  extract   OFFLINE LLM -> zoning_rules (candidates, review_status=pending) +
            rule_attributes (per-field value + provenance + confidence)
  validate  compare rule_attributes to state_rule_baselines -> qa_issues +
            per-field/rule compliance_flag
  all       ingest -> extract -> validate

Usage:
  python run.py ingest --jurisdiction los_angeles
  python run.py extract --jurisdiction los_angeles --limit 5
  python run.py validate --jurisdiction los_angeles
  python run.py all --jurisdiction los_angeles --dry-run
  python run.py ingest --all-jurisdictions

Secrets come only from the environment (SUPABASE_*, AZURE_OPENAI_*).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# Offline tripwire: this worker must never run on the API request path.
if os.environ.get("ADU_ATLAS_REQUEST_PATH") in {"1", "true", "yes", "on"}:
    raise RuntimeError(
        "ingestion/code/run.py is OFFLINE-only and must not run on the API "
        "request path (ADU_ATLAS_REQUEST_PATH is set)."
    )

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("adu.code")


def _resolve_slugs(args, settings) -> list[str]:
    import registry

    if args.all_jurisdictions:
        return registry.code_jurisdiction_slugs(settings.config_dir)
    return [args.jurisdiction]


def _stage_ingest(slugs, settings, store) -> int:
    from ingest import ingest_jurisdiction

    failures = 0
    for slug in slugs:
        result = ingest_jurisdiction(slug, settings, store, triggered_by="run.py")
        if not result.ok:
            failures += 1
    return failures


def _stage_extract(slugs, settings, store, args) -> int:
    from extract import ExtractionError, extract_jurisdiction

    failures = 0
    for slug in slugs:
        try:
            extract_jurisdiction(
                slug, settings, store,
                limit=args.limit, dry_run=args.dry_run, provider=args.provider,
            )
        except ExtractionError as exc:
            log.error("[%s] extraction error: %s", slug, exc)
            failures += 1
    return failures


def _stage_validate(slugs, settings, store, args) -> int:
    from validate import validate_jurisdiction

    failures = 0
    for slug in slugs:
        try:
            validate_jurisdiction(slug, settings, store, dry_run=args.dry_run)
        except Exception as exc:
            log.error("[%s] validation error: %s", slug, exc)
            failures += 1
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ADU Atlas OFFLINE code ingestion + extraction + QA"
    )
    parser.add_argument(
        "stage", choices=["ingest", "extract", "validate", "all"],
        help="pipeline stage to run",
    )
    parser.add_argument(
        "--jurisdiction", default="los_angeles",
        help="jurisdiction slug (default: los_angeles, the v1 target)",
    )
    parser.add_argument(
        "--all-jurisdictions", action="store_true",
        help="run for every jurisdiction with a configured municipal_code source",
    )
    parser.add_argument("--limit", type=int, help="cap sections processed (extract)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="extract/validate without writing to the database",
    )
    parser.add_argument(
        "--provider", choices=["azure_openai", "anthropic"],
        help="force an LLM provider for extraction (default: auto)",
    )
    args = parser.parse_args(argv)

    from config import Settings
    from db import CodeStore

    # Extraction needs an LLM; ingest/validate do not. Require Supabase always.
    settings = Settings.from_env(require_supabase=True)
    if args.stage in ("extract", "all") and not settings.has_azure_openai and not os.environ.get(
        "ANTHROPIC_API_KEY"
    ):
        log.error(
            "extraction requires AZURE_OPENAI_ENDPOINT (/openai/v1) + "
            "AZURE_OPENAI_API_KEY + AZURE_OPENAI_DEPLOYMENT, or ANTHROPIC_API_KEY."
        )
        return 2

    store = CodeStore(settings)
    slugs = _resolve_slugs(args, settings)
    if not slugs:
        log.error("no jurisdictions to process")
        return 2
    log.info("stage=%s jurisdictions=%s dry_run=%s", args.stage, slugs, args.dry_run)

    failures = 0
    if args.stage in ("ingest", "all"):
        failures += _stage_ingest(slugs, settings, store)
    if args.stage in ("extract", "all"):
        failures += _stage_extract(slugs, settings, store, args)
    if args.stage in ("validate", "all"):
        failures += _stage_validate(slugs, settings, store, args)

    if failures and len(slugs) == 1:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
