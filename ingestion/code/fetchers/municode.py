"""Municode fetcher (library.municode.com / api.municode.com).

Covers San Jose, Irvine, Long Beach, Oakland (all coverage_status='planned'
until ingested + tested). Municode serves a single-page app whose node URLs are:

    https://library.municode.com/ca/{city}/codes/{code}?nodeId=TIT20ZO_CH20.30...

Discovery has two paths:
  1. Primary: the reverse-engineered JSON API at api.municode.com - resolve the
     client, pick the product matching the code path, full-text search for ADU
     terms, collect node ids. Fast, no SPA driving.
  2. Fallback: drive the site search box with Playwright and harvest ?nodeId=
     result links, plus the per-jurisdiction chapter hints.

Section content is always extracted from the rendered DOM (the SPA hydrates the
node's chunks into the content region), robust regardless of how the node id was
found. Playwright and httpx are imported lazily.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from keywords import hints_for, search_terms_for
from normalize import clean_text, find_heading, parse_numbering, section_label, soup

from .base import BaseCodeFetcher, FetchedSection, SelectorDriftError

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

_MIN_CONTENT_CHARS = 200


class MunicodeApiClient:
    """Best-effort client for api.municode.com. Failures return empty results."""

    BASE = "https://api.municode.com"

    def __init__(self, user_agent: str, timeout_seconds: float = 30.0) -> None:
        import httpx  # lazy

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
        except Exception:  # pragma: no cover
            pass

    @staticmethod
    def _get_ci(obj: dict, *names: str) -> Any:
        lowered = {k.lower(): v for k, v in obj.items()} if isinstance(obj, dict) else {}
        for name in names:
            if name.lower() in lowered:
                return lowered[name.lower()]
        return None

    def get_client(self, client_name: str, state_abbr: str = "CA") -> dict | None:
        import httpx

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
        import httpx

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
        import httpx

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


class MunicodeFetcher(BaseCodeFetcher):
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
        self._pw = None
        self._browser = None

    @staticmethod
    def _parse_code_path(base_url: str) -> str:
        parts = [p for p in urlparse(base_url).path.split("/") if p]
        return parts[-1] if parts else ""

    def _node_url(self, node_id: str) -> str:
        base = self.base_url.split("?")[0]
        return f"{base}?nodeId={quote_plus(node_id)}"

    def _matches_hint(self, url: str, text: str | None) -> bool:
        hay = f"{url} {text or ''}".lower()
        return any(ch.lower() in hay for ch in hints_for(self.slug).get("chapters", []))

    # ------------------------------------------------------------------
    # browser lifecycle (lazy)
    # ------------------------------------------------------------------
    def _ensure_browser(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright  # lazy

            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=self.settings.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            logger.info("[%s] launched Chromium", self.slug)
        return self._browser

    def close(self) -> None:
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:  # pragma: no cover
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:  # pragma: no cover
            pass
        self._browser = None
        self._pw = None

    def run(self):
        try:
            yield from super().run()
        finally:
            self.close()

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
        try:
            api = MunicodeApiClient(user_agent=self.settings.user_agent)
        except Exception as exc:  # httpx not available -> fall back to Playwright
            logger.debug("[%s] municode api client unavailable: %s", self.slug, exc)
            return []
        try:
            client = api.get_client(self.jurisdiction.get("name", ""), "CA")
            if not client:
                return []
            client_id = api._get_ci(client, "ClientID", "ClientId", "Id")
            if client_id is None:
                return []
            product_id = self._resolve_product_id(api, int(client_id))
            node_ids: list[str] = []
            for term in search_terms_for(self.slug)[:3]:
                self._rate_limit()
                node_ids.extend(api.search_node_ids(int(client_id), term, product_id))
            seen: set[str] = set()
            ordered = [n for n in node_ids if not (n in seen or seen.add(n))]
            logger.info("[%s] API discovery found %d node id(s)", self.slug, len(ordered))
            return ordered
        except Exception as exc:
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
            token = self._code_path.split("_")[0].lower()
            if token and token in name.lower().replace(" ", ""):
                pid = api._get_ci(product, "ProductId", "ProductID", "Id")
                if pid is not None:
                    return int(pid)
        return None

    def _discover_via_playwright(self) -> list[str]:
        from playwright.sync_api import Error as PlaywrightError

        urls: list[str] = []
        browser = self._ensure_browser()
        page = browser.new_page(user_agent=self.settings.user_agent)
        page.set_default_timeout(self.settings.nav_timeout_ms)
        try:
            for term in search_terms_for(self.slug)[:3]:
                self._rate_limit()
                try:
                    urls.extend(self._search(page, term))
                except PlaywrightError as exc:
                    logger.warning("[%s] Municode search %r failed: %s", self.slug, term, exc)
        finally:
            page.close()
        return urls

    def _find_search_box(self, page):
        from playwright.sync_api import Error as PlaywrightError

        for selector in _SEARCH_BOX_SELECTORS:
            locator = page.locator(selector).first
            try:
                if locator.count() > 0 and locator.is_visible():
                    return locator
            except PlaywrightError:
                continue
        return None

    def _search(self, page, term: str) -> list[str]:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        page.goto(self.base_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=self.settings.selector_timeout_ms)
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
            page.wait_for_load_state("networkidle", timeout=self.settings.selector_timeout_ms)
        except PlaywrightTimeoutError:
            pass
        page.wait_for_timeout(1500)
        return self._harvest_links(page)

    def _harvest_links(self, page) -> list[str]:
        from playwright.sync_api import Error as PlaywrightError

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
            from keywords import text_matches_adu

            if text_matches_adu(text) or text_matches_adu(absolute) or self._matches_hint(
                absolute, text
            ):
                found.append(absolute)
        return found

    # ------------------------------------------------------------------
    # content
    # ------------------------------------------------------------------
    def _render(self, url: str) -> tuple[str, int | None]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        browser = self._ensure_browser()
        page = browser.new_page(user_agent=self.settings.user_agent)
        try:
            page.set_default_timeout(self.settings.nav_timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=self.settings.selector_timeout_ms)
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_selector(
                    ".chunk-content-wrapper, .chunks",
                    timeout=self.settings.selector_timeout_ms,
                )
            except PlaywrightTimeoutError:
                logger.debug("[%s] chunk region not found on %s", self.slug, url)
            return page.content(), None
        finally:
            page.close()

    def _select_content(self, document) -> str:
        best = ""
        tried: list[str] = []
        for selector in self.content_selectors:
            tried.append(selector)
            for node in document.select(selector):
                text = clean_text(node)
                if len(text) > len(best):
                    best = text
            if len(best) >= _MIN_CONTENT_CHARS:
                break
        if len(best) < _MIN_CONTENT_CHARS:
            raise SelectorDriftError(
                f"[{self.slug}] no content container >= {_MIN_CONTENT_CHARS} chars "
                f"matched {tried}. Municode DOM likely changed."
            )
        return best

    def fetch_section(self, url: str) -> FetchedSection | None:
        self._rate_limit()
        html, status = self._render(url)
        document = soup(html)
        text = self._select_content(document)
        heading = find_heading(document, self.heading_selectors)
        nums = parse_numbering(heading, text)

        m = _NODE_ID_RE.search(url)
        if m:
            self._augment_from_node_id(m.group(1), nums)

        label = section_label(
            nums["title_number"], nums["chapter_number"], nums["section_number"], heading or ""
        )
        return FetchedSection(
            section_url=url,
            raw_bytes=html.encode("utf-8"),
            text=text,
            content_type="text/html",
            http_status=status,
            title=heading,
            code_title=self.source.get("code_title"),
            title_number=nums["title_number"],
            chapter_number=nums["chapter_number"],
            section_number=nums["section_number"],
            section_label=label,
        )

    @staticmethod
    def _augment_from_node_id(node_id: str, nums: dict[str, str | None]) -> None:
        m_title = re.search(r"TIT([0-9]+[A-Za-z]?)", node_id)
        if m_title and not nums.get("title_number"):
            nums["title_number"] = m_title.group(1)
        m_chapter = re.search(r"CH([0-9]+(?:\.[0-9]+)?)", node_id)
        if m_chapter and not nums.get("chapter_number"):
            nums["chapter_number"] = m_chapter.group(1)
        m_section = re.search(r"_([0-9]+(?:\.[0-9]+){1,3})", node_id)
        if m_section and not nums.get("section_number"):
            nums["section_number"] = m_section.group(1)
