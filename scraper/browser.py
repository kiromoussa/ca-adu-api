"""Playwright browser lifecycle helper.

Both publishers (American Legal Publishing and Municode) serve JavaScript-
rendered single-page apps behind bot protection that returns 403 to plain HTTP
clients, so a real headless browser is required to obtain rendered HTML.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, sync_playwright

from .config import Settings

logger = logging.getLogger(__name__)


@contextmanager
def launch_browser(settings: Settings) -> Iterator[Browser]:
    """Launch a Chromium browser for the duration of the context.

    Yields a single shared Browser; adapters open and close their own pages so
    a slow or hung page never leaks into the next city.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        logger.info("Launched Chromium (headless=%s)", settings.headless)
        try:
            yield browser
        finally:
            try:
                browser.close()
            except Exception:  # pragma: no cover - best-effort teardown
                logger.warning("Browser close raised; ignoring during teardown")
            logger.info("Closed Chromium")
