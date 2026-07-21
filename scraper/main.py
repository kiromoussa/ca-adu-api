"""Scraper worker entrypoint.

Run weekly on Render (see render.yaml) or locally:

    python -m scraper.main

Flow: load settings from env -> connect Supabase (service role) -> launch
Chromium -> for each city in the `cities` table, dispatch to the ALP or Municode
adapter by publisher_type, upsert extracted sections, and stamp
cities.last_scraped_at on success.
"""

from __future__ import annotations

import logging
import sys

from .base import BaseScraper, CityRunResult
from .browser import launch_browser
from .config import Settings
from .db import SupabaseWriter

logger = logging.getLogger("scraper")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # Playwright / httpx are chatty at DEBUG; keep them at WARNING.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _adapter_for(publisher_type: str) -> type[BaseScraper] | None:
    # Imported here so `import scraper.main` stays cheap and side-effect free.
    from .adapters import ALPScraper, MunicodeScraper

    return {"alp": ALPScraper, "municode": MunicodeScraper}.get(publisher_type)


def run() -> int:
    """Run one full scrape pass. Returns a process exit code."""
    _configure_logging()

    settings = Settings.from_env()
    db = SupabaseWriter(settings.supabase_url, settings.supabase_service_role_key)

    cities = db.get_cities()
    if not cities:
        logger.error("No cities found in the cities table. Run supabase/seed.sql.")
        return 1

    logger.info("Scraping %d cities", len(cities))
    results: list[CityRunResult] = []

    with launch_browser(settings) as browser:
        for city in cities:
            slug = city.get("slug", "unknown")
            publisher = city.get("publisher_type", "")
            adapter_cls = _adapter_for(publisher)
            if adapter_cls is None:
                logger.error("[%s] unknown publisher_type %r; skipping", slug, publisher)
                continue

            scraper = adapter_cls(city=city, db=db, browser=browser, settings=settings)
            try:
                result = scraper.run()
            except Exception as exc:  # one city must never abort the whole run
                logger.exception("[%s] fatal error, continuing", slug)
                result = CityRunResult(slug=slug, errors=[str(exc)])

            results.append(result)
            if result.ok:
                try:
                    db.touch_city_scraped(city["id"])
                except Exception:
                    logger.exception("[%s] failed to update last_scraped_at", slug)

    # ---- summary ----
    total_written = sum(r.sections_written for r in results)
    successes = [r for r in results if r.ok]
    logger.info(
        "Run complete: %d/%d cities produced sections, %d sections written/updated",
        len(successes),
        len(results),
        total_written,
    )
    for r in results:
        logger.info(
            "  %-14s discovered=%d inserted=%d updated=%d unchanged=%d failed=%d",
            r.slug,
            r.discovered,
            r.inserted,
            r.updated,
            r.unchanged,
            r.failed,
        )

    # Non-zero exit only if every city failed, so a single flaky site does not
    # mark the whole cron run red.
    if results and not successes:
        logger.error("All cities failed to produce any sections.")
        return 2
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
