"""Abstract base scraper shared by the ALP and Municode adapters.

Responsibilities provided here so adapters stay small:
  - fetch(): render a URL with Playwright, with tenacity retries + backoff,
    polite rate limiting, and raw-HTML snapshotting.
  - content extraction helpers with candidate-selector guards that raise a
    clear SelectorDriftError when a publisher changes its DOM.
  - content hashing (sha256) for change detection.
  - run(): orchestrate discover -> fetch -> parse -> upsert for one city.

Adapters implement two abstract hooks:
  - discover_sections(): return candidate section URLs (via site search + hints)
  - parse_section(url, html): return a ScrapedSection or None
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings
from .db import SupabaseWriter
from .keywords import text_matches_adu

logger = logging.getLogger(__name__)

# Minimum characters a container must hold to be treated as real section text
# rather than a nav shell or spinner.
_MIN_CONTENT_CHARS = 200


class SelectorDriftError(RuntimeError):
    """Raised when none of the candidate selectors match a rendered page.

    Signals that the publisher changed its DOM and the adapter needs updating,
    rather than a transient network error.
    """


@dataclass
class ScrapedSection:
    """One extracted municipal-code section, ready to upsert."""

    section_url: str
    raw_text: str
    title_number: str | None = None
    chapter_number: str | None = None
    section_number: str | None = None

    @property
    def content_hash(self) -> str:
        normalized = re.sub(r"\s+", " ", self.raw_text or "").strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class CityRunResult:
    """Per-city summary emitted by run()."""

    slug: str
    discovered: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def sections_written(self) -> int:
        return self.inserted + self.updated

    @property
    def ok(self) -> bool:
        # A city run is considered successful if it wrote or confirmed at least
        # one section. Zero sections means discovery or extraction fully failed.
        return (self.inserted + self.updated + self.unchanged) > 0


class BaseScraper(ABC):
    """Shared scraping machinery. One instance per city per run."""

    #: 'alp' or 'municode' - matches the cities.publisher_type enum.
    publisher: str = "base"

    #: Candidate CSS selectors, most specific first, for the main content
    #: region of a rendered section page. Adapters override.
    content_selectors: tuple[str, ...] = ("main", "[role='main']", "article", "body")

    #: Candidate CSS selectors for the section heading. Adapters override.
    heading_selectors: tuple[str, ...] = ("h1", "h2", "header h1", ".title")

    def __init__(
        self,
        city: dict[str, Any],
        db: SupabaseWriter,
        browser: Browser,
        settings: Settings,
    ) -> None:
        self.city = city
        self.slug = city.get("slug", "unknown")
        self.city_id = city["id"]
        self.base_url = city.get("base_url", "")
        self.db = db
        self.browser = browser
        self.settings = settings
        self._last_request_ts = 0.0

    # ------------------------------------------------------------------
    # networking
    # ------------------------------------------------------------------
    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.settings.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def fetch(self, url: str, wait_selector: str | None = None) -> str:
        """Render `url` and return its HTML. Rate limited + retried + snapshotted."""
        self._rate_limit()

        retrying = retry(
            reraise=True,
            stop=stop_after_attempt(self.settings.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(
                (PlaywrightTimeoutError, PlaywrightError)
            ),
            before_sleep=lambda rs: logger.warning(
                "[%s] fetch retry %s for %s", self.slug, rs.attempt_number, url
            ),
        )
        html = retrying(self._render)(url, wait_selector)
        if self.settings.save_snapshots:
            self._snapshot(url, html)
        return html

    def _render(self, url: str, wait_selector: str | None) -> str:
        page: Page = self.browser.new_page(user_agent=self.settings.user_agent)
        try:
            page.set_default_timeout(self.settings.nav_timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            # Give the SPA a chance to hydrate; networkidle is best-effort.
            try:
                page.wait_for_load_state(
                    "networkidle", timeout=self.settings.selector_timeout_ms
                )
            except PlaywrightTimeoutError:
                pass
            if wait_selector:
                try:
                    page.wait_for_selector(
                        wait_selector, timeout=self.settings.selector_timeout_ms
                    )
                except PlaywrightTimeoutError:
                    logger.debug(
                        "[%s] wait_selector %r not found on %s",
                        self.slug,
                        wait_selector,
                        url,
                    )
            return page.content()
        finally:
            page.close()

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------
    def _snapshot(self, url: str, html: str) -> None:
        try:
            city_dir = self.settings.snapshot_dir / self.slug
            city_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
            tail = urlparse(url).path.rstrip("/").split("/")[-1] or "index"
            tail = re.sub(r"[^A-Za-z0-9_.-]", "_", tail)[:60]
            path = city_dir / f"{tail}.{digest}.html"
            path.write_text(html, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - snapshotting is best-effort
            logger.warning("[%s] could not snapshot %s: %s", self.slug, url, exc)

    # ------------------------------------------------------------------
    # parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def soup(html: str) -> BeautifulSoup:
        try:
            return BeautifulSoup(html, "lxml")
        except Exception:  # lxml not available -> stdlib parser
            return BeautifulSoup(html, "html.parser")

    @staticmethod
    def clean_text(node: Any) -> str:
        text = node.get_text(separator="\n") if node is not None else ""
        lines = [ln.strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines).strip()

    def select_content(self, soup: BeautifulSoup) -> tuple[str, Any]:
        """Return (text, element) for the best content container.

        Tries each candidate selector, keeps the one with the most text over the
        minimum threshold. Raises SelectorDriftError if nothing qualifies.
        """
        best_text = ""
        best_node = None
        tried: list[str] = []
        for selector in self.content_selectors:
            tried.append(selector)
            for node in soup.select(selector):
                text = self.clean_text(node)
                if len(text) > len(best_text):
                    best_text = text
                    best_node = node
            if len(best_text) >= _MIN_CONTENT_CHARS:
                break

        if len(best_text) < _MIN_CONTENT_CHARS:
            raise SelectorDriftError(
                f"[{self.slug}] no content container >= {_MIN_CONTENT_CHARS} "
                f"chars matched selectors {tried}. Publisher DOM likely changed."
            )
        return best_text, best_node

    def find_heading(self, soup: BeautifulSoup) -> str | None:
        for selector in self.heading_selectors:
            node = soup.select_one(selector)
            if node:
                text = self.clean_text(node)
                if text:
                    return text.splitlines()[0][:300]
        return None

    @staticmethod
    def parse_numbering(heading: str | None, text: str) -> dict[str, str | None]:
        """Best-effort extraction of title / chapter / section numbers.

        Handles both dotted municipal-code numbering (e.g. 20.30.460, 12.22) and
        explicit "Title N" / "Chapter N" / "Sec. N" phrasing found in headings.
        """
        result: dict[str, str | None] = {
            "title_number": None,
            "chapter_number": None,
            "section_number": None,
        }
        haystack = heading or text[:400]
        if not haystack:
            return result

        m_title = re.search(r"\bTitle\s+(\d+[A-Za-z]?)", haystack, re.I)
        if m_title:
            result["title_number"] = m_title.group(1)

        m_chapter = re.search(r"\bChapter\s+([\d.]+[A-Za-z]?)", haystack, re.I)
        if m_chapter:
            result["chapter_number"] = m_chapter.group(1).rstrip(".")

        # Dotted section like 20.30.460 or 17.103 or 12.22
        m_dotted = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){1,3})\b", haystack)
        if m_dotted:
            dotted = m_dotted.group(1)
            result["section_number"] = dotted
            if result["chapter_number"] is None and dotted.count(".") >= 1:
                parts = dotted.split(".")
                result["chapter_number"] = ".".join(parts[:2])
            if result["title_number"] is None:
                result["title_number"] = dotted.split(".")[0]
        else:
            m_sec = re.search(r"\bSec(?:tion)?\.?\s*([\d.]+)", haystack, re.I)
            if m_sec:
                result["section_number"] = m_sec.group(1).rstrip(".")

        return result

    # ------------------------------------------------------------------
    # abstract hooks
    # ------------------------------------------------------------------
    @abstractmethod
    def discover_sections(self) -> list[str]:
        """Return candidate section URLs to scrape for this city."""

    @abstractmethod
    def parse_section(self, url: str, html: str) -> ScrapedSection | None:
        """Parse one rendered section page into a ScrapedSection (or None)."""

    # ------------------------------------------------------------------
    # orchestration
    # ------------------------------------------------------------------
    def run(self) -> CityRunResult:
        result = CityRunResult(slug=self.slug)
        logger.info("[%s] starting (%s)", self.slug, self.publisher)

        try:
            urls = self.discover_sections()
        except (SelectorDriftError, RetryError, PlaywrightError) as exc:
            msg = f"discovery failed: {exc}"
            logger.error("[%s] %s", self.slug, msg)
            result.errors.append(msg)
            return result

        # De-duplicate while preserving order, then cap.
        seen: set[str] = set()
        ordered: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
        ordered = ordered[: self.settings.max_sections_per_city]
        result.discovered = len(ordered)
        logger.info("[%s] discovered %d candidate section(s)", self.slug, len(ordered))

        for url in ordered:
            try:
                html = self.fetch(url)
                section = self.parse_section(url, html)
                if section is None or not section.raw_text.strip():
                    logger.debug("[%s] no section content at %s", self.slug, url)
                    continue
                outcome = self.db.upsert_zoning_section(
                    city_id=self.city_id,
                    section_url=section.section_url,
                    raw_text=section.raw_text,
                    content_hash=section.content_hash,
                    title_number=section.title_number,
                    chapter_number=section.chapter_number,
                    section_number=section.section_number,
                )
                if outcome == "inserted":
                    result.inserted += 1
                elif outcome == "updated":
                    result.updated += 1
                else:
                    result.unchanged += 1
                logger.info("[%s] %s %s", self.slug, outcome, url)
            except SelectorDriftError as exc:
                result.failed += 1
                result.errors.append(str(exc))
                logger.error("[%s] selector drift at %s: %s", self.slug, url, exc)
            except (RetryError, PlaywrightError) as exc:
                result.failed += 1
                result.errors.append(f"fetch/parse failed for {url}: {exc}")
                logger.error("[%s] fetch/parse failed at %s: %s", self.slug, url, exc)
            except Exception as exc:  # keep the run alive across one bad section
                result.failed += 1
                result.errors.append(f"unexpected error for {url}: {exc}")
                logger.exception("[%s] unexpected error at %s", self.slug, url)

        logger.info(
            "[%s] done: %d inserted, %d updated, %d unchanged, %d failed",
            self.slug,
            result.inserted,
            result.updated,
            result.unchanged,
            result.failed,
        )
        return result

    # small shared convenience for adapters
    @staticmethod
    def link_is_relevant(link_text: str | None, href: str | None) -> bool:
        return text_matches_adu(link_text) or text_matches_adu(href)
