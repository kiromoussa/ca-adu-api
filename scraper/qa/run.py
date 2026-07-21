"""Entrypoint for the HCD compliance QA cross-check job (Prompt 6).

Runs on Render as a weekly cron worker. Flow:

  1. Read cities + adu_rules from Supabase (service role).
  2. Fetch HCD APR CSV records and check ordinance review letters.
  3. Cross-reference to find discrepancies.
  4. Persist to qa_alerts and send Slack/email alerts.

Run: python -m scraper.qa.run   (flags: --dry-run, --city <slug>)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

from supabase import create_client

from . import alerts as alerts_mod
from . import crosscheck as crosscheck_mod
from . import hcd

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("qa.run")

try:  # local convenience; no-op in production
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        sys.exit(2)
    return create_client(url, key)


def _load_rules_by_slug(client, city_filter: str | None) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    cities_res = client.table("cities").select("id, name, slug").execute()
    cities = list(cities_res.data or [])
    id_to_slug = {c["id"]: c["slug"] for c in cities}

    q = client.table("adu_rules").select("id, city_id, zone_district, compliance_flag")
    rules = list((q.execute()).data or [])

    by_slug: dict[str, list[dict[str, Any]]] = {}
    for row in rules:
        slug = id_to_slug.get(row.get("city_id"))
        if not slug:
            continue
        if city_filter and slug != city_filter:
            continue
        by_slug.setdefault(slug, []).append(row)
    return cities, by_slug


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HCD compliance QA cross-check")
    parser.add_argument("--city", help="Restrict to a single city slug")
    parser.add_argument("--dry-run", action="store_true", help="Do not write qa_alerts or send alerts")
    args = parser.parse_args(argv)

    client = _supabase()
    cities, rules_by_slug = _load_rules_by_slug(client, args.city)
    logger.info("Loaded adu_rules for %d cities.", len(rules_by_slug))

    apr_records = hcd.fetch_apr_records()
    ordinance_letters = hcd.check_ordinance_letters()

    discrepancies = crosscheck_mod.cross_check(
        rules_by_slug=rules_by_slug,
        apr_records=apr_records,
        ordinance_letters=ordinance_letters,
    )

    if args.dry_run:
        for d in discrepancies:
            logger.info("[dry-run] %s/%s (%s): %s", d.slug, d.field, d.severity, d.hcd_finding)
        logger.info("Dry run complete: %d discrepancies (not persisted).", len(discrepancies))
        return 0

    sink = alerts_mod.AlertSink(client)
    report = sink.dispatch(discrepancies, cities)
    logger.info("QA run report: %s", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
