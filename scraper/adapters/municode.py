"""Municode adapter (library.municode.com / api.municode.com).

Covers San Jose, Irvine, Long Beach, Oakland. Municode serves a single-page app
whose node URLs look like:

    https://library.municode.com/ca/{city}/codes/{code}?nodeId=TIT20ZO_CH20.30...

Discovery has two paths:
  1. Primary: the documented (reverse-engineered) JSON API at api.municode.com -
     resolve the client, pick the product matching the code path, run full-text
     search for "Accessory Dwelling Unit", and collect node ids. This is fast and
     avoids driving the SPA.
  2. Fallback: drive the site-internal search box with Playwright and harvest
     result links carrying ?nodeId=, then the per-city chapter hints.

Section content is always extracted from the rendered DOM (the SPA hydrates the
node's chunks into the content region), which is robust regardless of how the
node id was discovered.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ..base import BaseScraper, ScrapedSection
from ..keywords import hints_for, search_terms_for

logger = logging.getLogger(__name__)

_NODE_ID_RE = re.compile(r"[?&]nodeId=([^&#]+)", re.I)

_SEARCH_BOX_SELECTORS = (
    "input[type='search']",
    "input[name='searchText']",
    "input[ng-model*='search' i]",
    "input[aria-label*='Search' i]",
    "input[placeholder*='Search' i]",
    ".search input",
    "form[role='search'] input",
)


class MunicodeApiClient:
    """Best-effort client for the documented api.municode.com endpoints.

    Every method is defensive: any failure returns an empty / None result so the
    Playwright fallback can take over. Field names in Municode responses vary, so
    lookups scan for several plausible keys.
    """

    BASE = "https://api.municode.com"

    def __init__(self, user_agent: str, timeout_seconds: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=self.BASE,
            timeout=timeout_seconds,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://library.municode.com/",
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # pragma: no cover - best-effort
            pass

    @staticmethod
    def _get_ci(obj: dict, *names: str) -> Any:
        """Case-insensitive lookup across several candidate key names."""
        lowered = {k.lower(): v for k, v in obj.items()} if isinstance(obj, dict) else {}
        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None

    def get_client(self, client_name: str, state_abbr: str = "CA") -> dict | None:
        try:
            resp = self._client.get(
                "/Clients/name",
                params={"clientName": client_name, "stateAbbr": state_abbr},
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data[0] if data else None
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("municode get_client(%s) failed: %s", client_name, exc)
            return None

    def get_client_content(self, client_id: int) -> Any:
        try:
            resp = self._client.get(f"/ClientContent/{client_id}")
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("municode get_client_content(%s) failed: %s", client_id, exc)
            return None

    def search_node_ids(
        self,
        client_id: int,
        search_text: str,
        product_id: int | None = None,
        page_size: int = 20,
    ) -> list[str]:
        """Run full-text search and pull node ids out of the hit objects."""
        params: dict[str, Any] = {
            "clientId": client_id,
            "searchText": search_text,
            "pageNum": 1,
            "pageSize": page_size,
            "isAutocomplete": "false",
            "isAdvanced": "false",
            "titlesOnly": "false",
            "sort": 0,
        }
        if product_id is not None:
            params["productId"] = product_id
        try:
            resp = self._client.get("/search", params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("municode search(%s) failed: %s", search_text, exc)
            return []

        hits = self._get_ci(data, "Hits", "hits") if isinstance(data, dict) else None
        node_ids: list[str] = []
        if isinstance(hits, list):
            for hit in hits:
                node_ids.extend(self._node_ids_from_obj(hit))
        return node_ids

    def _node_ids_from_obj(self, obj: Any) -> list[str]:
        """Extract candidate node ids by scanning a hit for ids / URLs."""
        results: list[str] = []
        if not isinstance(obj, dict):
            return results

        direct = self._get_ci(obj, "NodeId", "nodeId", "DocId", "Id")
        if isinstance(direct, str) and direct:
            results.append(direct)

        for value in obj.values():
            if isinstance(value, str):
                m = _NODE_ID_RE.search(value)
                if m:
                    results.append(m.group(1))
            elif isinstance(value, dict):
                results.extend(self._node_ids_from_obj(value))
        return results


class MunicodeScraper(BaseScraper):
    publisher = "municode"

    content_selectors = (
        ".chunk-content-wrapper",
        ".chunk-content",
        ".chunks",
        "mcc-codes",
        "#genContent",
        ".content-wrapper",
        "div.content",
        "main",
        "[role='main']",
        "article",
        "body",
    )
    heading_selectors = (
        ".chunk-title-wrapper",
        ".chunk-title",
        ".chunk-content-wrapper h1",
        "h1",
        ".title",
        "h2",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._code_path = self._parse_code_path(self.base_url)

    @staticmethod
    def _parse_code_path(base_url: str) -> str:
        """Return the code path segment, e.g. 'planning_code' or 'code_of_ordinances'."""
        parts = [p for p in urlparse(base_url).path.split("/") if p]
        # .../ca/{city}/(codes|ordinances)/{code_path}
        return parts[-1] if parts else ""

    def _node_url(self, node_id: str) -> str:
        sep = "&" if "?" in self.base_url else "?"
        return f"{self.base_url}{sep}nodeId={quote_plus(node_id)}"

    def _matches_hint(self, url: str, text: str | None) -> bool:
        hay = f"{url} {text or ''}".lower()
        return any(ch.lower() in hay for ch in hints_for(self.slug).get("chapters", []))

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    def discover_sections(self) -> list[str]:
        node_ids = self._discover_via_api()
        urls = [self._node_url(n) for n in node_ids]

        if not urls:
            logger.info("[%s] API discovery empty; using Playwright search", self.slug)
            urls = self._discover_via_playwright()

        urls.extend(hints_for(self.slug).get("hint_urls", []))
        if self.base_url:
            urls.append(self.base_url)
        return urls

    def _discover_via_api(self) -> list[str]:
        api = MunicodeApiClient(user_agent=self.settings.user_agent)
        try:
            client = api.get_client(self.city.get("name", ""), "CA")
            if not client:
                return []
            client_id = api._get_ci(client, "ClientID", "ClientId", "Id")
            if client_id is None:
                return []

            product_id = self._resolve_product_id(api, int(client_id))

            node_ids: list[str] = []
            for term in search_terms_for(self.slug)[:3]:
                self._rate_limit()
                node_ids.extend(
                    api.search_node_ids(int(client_id), term, product_id)
                )
            # de-dup, preserve order
            seen: set[str] = set()
            ordered = [n for n in node_ids if not (n in seen or seen.add(n))]
            logger.info("[%s] API discovery found %d node id(s)", self.slug, len(ordered))
            return ordered
        except Exception as exc:  # never let the accelerator break the run
            logger.debug("[%s] API discovery error: %s", self.slug, exc)
            return []
        finally:
            api.close()

    def _resolve_product_id(self, api: MunicodeApiClient, client_id: int) -> int | None:
        content = api.get_client_content(client_id)
        products: list[Any] = []
        if isinstance(content, list):
            products = content
        elif isinstance(content, dict):
            maybe = api._get_ci(content, "Products", "ClientContent", "Items")
            if isinstance(maybe, list):
                products = maybe

        for product in products:
            if not isinstance(product, dict):
                continue
            name = str(api._get_ci(product, "ProductName", "Name", "CodeName") or "")
            # match the code path segment loosely, e.g. planning_code -> "planning"
            token = self._code_path.split("_")[0].lower()
            if token and token in name.lower().replace(" ", ""):
                pid = api._get_ci(product, "ProductId", "ProductID", "Id")
                if pid is not None:
                    return int(pid)
        return None

    def _discover_via_playwright(self) -> list[str]:
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
                        "[%s] Municode search for %r failed: %s", self.slug, term, exc
                    )
        finally:
            page.close()
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
        page.goto(self.base_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state(
                "networkidle", timeout=self.settings.selector_timeout_ms
            )
        except PlaywrightTimeoutError:
            pass

        box = self._find_search_box(page)
        if box is None:
            return []
        try:
            box.click()
            box.fill(term)
            box.press("Enter")
        except PlaywrightError as exc:
            logger.debug("[%s] search box interaction failed: %s", self.slug, exc)
            return []

        try:
            page.wait_for_load_state(
                "networkidle", timeout=self.settings.selector_timeout_ms
            )
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1500)
        return self._harvest_links(page)

    def _harvest_links(self, page: Page) -> list[str]:
        found: list[str] = []
        origin = f"{urlparse(self.base_url).scheme}://{urlparse(self.base_url).netloc}"
        for anchor in page.query_selector_all("a[href]"):
            href = anchor.get_attribute("href")
            if not href or "nodeid=" not in href.lower():
                continue
            try:
                text = (anchor.inner_text() or "").strip()
            except PlaywrightError:
                text = ""
            absolute = urljoin(origin + "/", href)
            if self.link_is_relevant(text, absolute) or self._matches_hint(
                absolute, text
            ):
                found.append(absolute)
        return found

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    def fetch(self, url: str, wait_selector: str | None = None) -> str:
        # Wait for the chunk region to hydrate before capturing HTML.
        return super().fetch(url, wait_selector or ".chunk-content-wrapper, .chunks")

    def parse_section(self, url: str, html: str) -> ScrapedSection | None:
        soup = self.soup(html)
        text, _ = self.select_content(soup)
        heading = self.find_heading(soup)
        nums = self.parse_numbering(heading, text)

        # Prefer the node id's embedded chapter/section (e.g. TIT20ZO_CH20.30...).
        node_ids = _NODE_ID_RE.search(url)
        if node_ids:
            self._augment_from_node_id(node_ids.group(1), nums)

        return ScrapedSection(
            section_url=url,
            raw_text=text,
            title_number=nums["title_number"],
            chapter_number=nums["chapter_number"],
            section_number=nums["section_number"],
        )

    @staticmethod
    def _augment_from_node_id(node_id: str, nums: dict[str, str | None]) -> None:
        # Municode node ids encode numbering: TIT20ZO_CH20.30REZODI_20.30.460...
        m_title = re.search(r"TIT([0-9]+[A-Za-z]?)", node_id)
        if m_title and not nums.get("title_number"):
            nums["title_number"] = m_title.group(1)
        m_chapter = re.search(r"CH([0-9]+(?:\.[0-9]+)?)", node_id)
        if m_chapter and not nums.get("chapter_number"):
            nums["chapter_number"] = m_chapter.group(1)
        m_section = re.search(r"_([0-9]+(?:\.[0-9]+){1,3})", node_id)
        if m_section and not nums.get("section_number"):
            nums["section_number"] = m_section.group(1)
