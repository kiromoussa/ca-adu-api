"""American Legal Publishing adapter (codelibrary.amlegal.com).

Covers Los Angeles, San Diego, San Francisco, Sacramento. ALP serves an Angular
single-page app with a consistent node-ID URL structure:

    /codes/{city}/latest/{code}/{node-id}

Discovery drives the site-internal full-text search (the sourcing report's
recommended approach, since node numbering shifts after each ordinance update),
harvests result links under the same code path, and falls back to the per-city
hint URLs from keywords.py when the search UI drifts.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urljoin, urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..base import BaseScraper, ScrapedSection
from ..keywords import hints_for, search_terms_for

logger = logging.getLogger(__name__)

# ALP node ids look like "0-0-0-422835"; some codes use other trailing ids, so
# we accept any non-empty final path segment that is not a known landing route.
_NON_SECTION_TAILS = {"latest", "overview", "search", ""}
_NODE_RE = re.compile(r"^[0-9]+(?:-[0-9]+)+$")

# Candidate CSS search-box selectors, most specific first.
_SEARCH_BOX_SELECTORS = (
    "input[type='search']",
    "input[name='query']",
    "input[name='q']",
    "input#searchBox",
    "input[aria-label*='Search' i]",
    "input[placeholder*='Search' i]",
    ".search-box input",
    "form[role='search'] input",
)


class ALPScraper(BaseScraper):
    publisher = "alp"

    content_selectors = (
        "#codeContent",
        ".codeContent",
        ".code-content",
        "div.content .Section",
        ".xsl-content",
        "div.content",
        "main",
        "[role='main']",
        "article",
        ".chunks",
        "body",
    )
    heading_selectors = (
        ".codeContent h1",
        ".Section h1",
        "header h1",
        "h1",
        ".title",
        "h2",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._city_path, self._code_segment, self._code_root = self._parse_base_url(
            self.base_url
        )

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_base_url(base_url: str) -> tuple[str, str | None, str]:
        """Return (city_path, code_segment, code_root_url) from a base URL.

        Example: .../codes/sacramentoca/latest/sacramento_ca/0-0-0-32996
          city_path   -> "sacramentoca"
          code_segment-> "sacramento_ca"
          code_root   -> ".../codes/sacramentoca/latest/sacramento_ca"
        """
        parsed = urlparse(base_url)
        parts = [p for p in parsed.path.split("/") if p]
        city_path = ""
        code_segment: str | None = None
        try:
            idx = parts.index("codes")
            city_path = parts[idx + 1] if len(parts) > idx + 1 else ""
        except ValueError:
            idx = -1

        # segment immediately after "latest" (if present and not a node id)
        if "latest" in parts:
            lidx = parts.index("latest")
            if len(parts) > lidx + 1 and not _NODE_RE.match(parts[lidx + 1]):
                code_segment = parts[lidx + 1]

        origin = f"{parsed.scheme}://{parsed.netloc}"
        if code_segment:
            code_root = f"{origin}/codes/{city_path}/latest/{code_segment}"
        else:
            code_root = f"{origin}/codes/{city_path}/latest"
        return city_path, code_segment, code_root

    def _is_section_link(self, url: str) -> bool:
        parsed = urlparse(url)
        if "codelibrary.amlegal.com" not in parsed.netloc:
            return False
        if f"/codes/{self._city_path}/latest" not in parsed.path:
            return False
        tail = parsed.path.rstrip("/").split("/")[-1]
        if tail in _NON_SECTION_TAILS:
            return False
        # keep true node pages and code-segment sub-pages
        return _NODE_RE.match(tail) is not None or (
            self._code_segment is not None and self._code_segment in parsed.path
        )

    def _matches_hint(self, url: str, text: str | None) -> bool:
        hay = f"{url} {text or ''}".lower()
        return any(ch.lower() in hay for ch in hints_for(self.slug).get("chapters", []))

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    def discover_sections(self) -> list[str]:
        urls: list[str] = []
        page: Page = self.browser.new_page(user_agent=self.settings.user_agent)
        page.set_default_timeout(self.settings.nav_timeout_ms)
        try:
            for term in search_terms_for(self.slug)[:3]:
                self._rate_limit()
                try:
                    urls.extend(self._search(page, term))
                except PlaywrightError as exc:
                    logger.warning(
                        "[%s] ALP search for %r failed: %s", self.slug, term, exc
                    )
        finally:
            page.close()

        # Deterministic fallback: always include configured hint URLs and the
        # code root so a totally-drifted search still yields something to parse.
        urls.extend(hints_for(self.slug).get("hint_urls", []))
        if self.base_url:
            urls.append(self.base_url)
        return urls

    def _find_search_box(self, page: Page) -> Locator | None:
        for selector in _SEARCH_BOX_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.count() > 0 and locator.is_visible():
                    return locator
            except PlaywrightError:
                continue
        return None

    def _search(self, page: Page, term: str) -> list[str]:
        page.goto(self.base_url or self._code_root, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state(
                "networkidle", timeout=self.settings.selector_timeout_ms
            )
        except PlaywrightTimeoutError:
            pass

        box = self._find_search_box(page)
        if box is None:
            return self._search_via_url(page, term)

        try:
            box.click()
            box.fill(term)
            box.press("Enter")
        except PlaywrightError as exc:
            logger.debug("[%s] search box interaction failed: %s", self.slug, exc)
            return self._search_via_url(page, term)

        try:
            page.wait_for_load_state(
                "networkidle", timeout=self.settings.selector_timeout_ms
            )
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1200)
        return self._harvest_links(page)

    def _search_via_url(self, page: Page, term: str) -> list[str]:
        """Fallback: hit the code-root search route directly."""
        url = f"{self._code_root}/search?query={quote_plus(term)}"
        try:
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state(
                    "networkidle", timeout=self.settings.selector_timeout_ms
                )
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(1200)
            return self._harvest_links(page)
        except PlaywrightError as exc:
            logger.debug("[%s] search-via-url failed: %s", self.slug, exc)
            return []

    def _harvest_links(self, page: Page) -> list[str]:
        found: list[str] = []
        base = f"{urlparse(self.base_url).scheme}://{urlparse(self.base_url).netloc}"
        for anchor in page.query_selector_all("a[href]"):
            href = anchor.get_attribute("href")
            if not href:
                continue
            try:
                text = (anchor.inner_text() or "").strip()
            except PlaywrightError:
                text = ""
            absolute = urljoin(base + "/", href)
            if not self._is_section_link(absolute):
                continue
            if self.link_is_relevant(text, absolute) or self._matches_hint(
                absolute, text
            ):
                found.append(absolute)
        return found

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    def parse_section(self, url: str, html: str) -> ScrapedSection | None:
        soup = self.soup(html)
        text, _ = self.select_content(soup)
        heading = self.find_heading(soup)
        nums = self.parse_numbering(heading, text)
        return ScrapedSection(
            section_url=url,
            raw_text=text,
            title_number=nums["title_number"],
            chapter_number=nums["chapter_number"],
            section_number=nums["section_number"],
        )
