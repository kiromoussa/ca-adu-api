"""Pipeline entrypoint: extract + validate + upsert adu_rules.

Runs on Render after the scraper populates zoning_sections. For each
unprocessed (or changed) zoning_sections row it:

  1. calls extract.extract_rules() to turn raw_text into per-zone rule dicts,
  2. validates each row against baselines via validate.validate_rule(),
  3. upserts the result into adu_rules (unique on city_id + zone_district),
     setting compliance_flag, compliance_notes (jsonb), source_section_id, and
     last_validated_at.

Auth uses the Supabase service-role key (SUPABASE_SERVICE_ROLE_KEY) so RLS
write policies are satisfied. Secrets come only from the environment.

Usage:
    python run.py                 # process new / changed sections
    python run.py --all           # reprocess every section
    python run.py --city san_jose # limit to one city slug
    python run.py --limit 5       # cap sections processed this run
    python run.py --dry-run       # extract + validate, print, do not write
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

from baselines import RULE_FIELDS
from extract import ExtractionError, extract_rules
from validate import validate_rule

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("adu.pipeline")


# ---------------------------------------------------------------------------
# supabase client
# ---------------------------------------------------------------------------
def get_client():
    """Create a Supabase client authenticated with the service-role key."""
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        sys.exit(2)
    return create_client(url, key)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _parse_ts(value: str | None) -> datetime | None:
    """Parse a Postgres timestamptz string into an aware datetime."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _section_label(section: dict) -> str:
    parts = [
        section.get("title_number"),
        section.get("chapter_number"),
        section.get("section_number"),
    ]
    label = " / ".join(p for p in parts if p)
    return label or section.get("section_url", "")


def load_cities(sb) -> dict[str, dict]:
    """Map city id -> city row."""
    rows = sb.table("cities").select("id,name,slug").execute().data or []
    return {row["id"]: row for row in rows}


def sections_to_process(sb, city_id: str | None, reprocess_all: bool) -> list[dict]:
    """Return zoning_sections needing (re)processing."""
    query = sb.table("zoning_sections").select("*")
    if city_id:
        query = query.eq("city_id", city_id)
    sections = query.execute().data or []

    if reprocess_all:
        return sections

    # Latest last_validated_at per source section already in adu_rules.
    existing = (
        sb.table("adu_rules")
        .select("source_section_id,last_validated_at")
        .execute()
        .data
        or []
    )
    latest: dict[str, datetime | None] = {}
    for row in existing:
        sid = row.get("source_section_id")
        if not sid:
            continue
        ts = _parse_ts(row.get("last_validated_at"))
        prev = latest.get(sid)
        if sid not in latest or (ts and (prev is None or ts > prev)):
            latest[sid] = ts

    todo: list[dict] = []
    for section in sections:
        sid = section["id"]
        if sid not in latest:
            todo.append(section)  # never processed
            continue
        validated_at = latest[sid]
        updated_at = _parse_ts(section.get("last_updated"))
        # Reprocess if the section changed after it was last validated, or if
        # we cannot establish ordering.
        if validated_at is None or updated_at is None or updated_at > validated_at:
            todo.append(section)
    return todo


def build_row(city_id: str, zone: dict, section_id: str) -> dict | None:
    """Turn one extracted zone dict into a validated adu_rules row."""
    zone_district = (zone.get("zone_district") or "").strip()
    if not zone_district:
        return None

    flag, notes = validate_rule(zone)
    row = {field: zone.get(field) for field in RULE_FIELDS}
    row.update(
        {
            "city_id": city_id,
            "zone_district": zone_district,
            "source_section_id": section_id,
            "compliance_flag": flag,
            "compliance_notes": notes,
            "last_validated_at": _now_iso(),
        }
    )
    return row


def process_section(sb, section: dict, cities: dict, dry_run: bool) -> int:
    """Extract, validate and upsert rules for one section. Returns rows written."""
    city_id = section["city_id"]
    city = cities.get(city_id, {})
    city_name = city.get("name", city_id)
    label = _section_label(section)

    try:
        zones = extract_rules(
            section.get("raw_text") or "",
            city_name=city_name,
            section_label=label,
        )
    except ExtractionError as exc:
        log.warning("Extraction failed for %s (%s): %s", city_name, label, exc)
        return 0

    rows: list[dict] = []
    for zone in zones:
        row = build_row(city_id, zone, section["id"])
        if row is None:
            log.debug("Skipping zone with empty zone_district in %s", label)
            continue
        rows.append(row)

    if not rows:
        log.info("No usable zone rules extracted for %s (%s)", city_name, label)
        return 0

    if dry_run:
        for row in rows:
            log.info(
                "[dry-run] %s / %s -> %s",
                city_name,
                row["zone_district"],
                row["compliance_flag"],
            )
        return len(rows)

    sb.table("adu_rules").upsert(rows, on_conflict="city_id,zone_district").execute()
    log.info("Upserted %d rule row(s) for %s (%s)", len(rows), city_name, label)
    return len(rows)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADU extraction + validation pipeline")
    parser.add_argument("--all", action="store_true", help="reprocess every section")
    parser.add_argument("--city", help="limit to a single city slug (e.g. san_jose)")
    parser.add_argument("--limit", type=int, help="max sections to process this run")
    parser.add_argument(
        "--dry-run", action="store_true", help="extract + validate but do not write"
    )
    args = parser.parse_args(argv)

    sb = get_client()
    cities = load_cities(sb)

    city_id = None
    if args.city:
        match = next(
            (cid for cid, c in cities.items() if c.get("slug") == args.city), None
        )
        if match is None:
            log.error("Unknown city slug: %s", args.city)
            return 2
        city_id = match

    sections = sections_to_process(sb, city_id, args.all)
    if args.limit is not None:
        sections = sections[: args.limit]

    if not sections:
        log.info("No sections to process.")
        return 0

    log.info("Processing %d section(s)...", len(sections))
    total_rows = 0
    for section in sections:
        total_rows += process_section(sb, section, cities, args.dry_run)

    log.info(
        "Done. %d section(s), %d rule row(s) %s.",
        len(sections),
        total_rows,
        "validated (dry-run)" if args.dry_run else "upserted",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
