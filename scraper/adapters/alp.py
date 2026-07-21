"""American Legal Publishing adapter (codelibrary.amlegal.com).

Covers Los Angeles, San Diego, San Francisco, Sacramento. ALP serves an Angular
single-page app fronted by a Cloudflare bot check that blocks both plain HTTP
clients and headless Playwright. The reliable path is ALP's own JSON API,
reached with curl_cffi impersonating a real Chrome TLS/JA3 fingerprint (which
clears Cloudflare):

  - Discovery: POST-less GET to /api/search/?s=<ctx>&offset=&limit=, where <ctx>
    is base64(zlib(json({"query": term}))). Results carry client_slug, code_slug
    and doc_id, which we filter to this city and turn into section URLs.
  - Content: /api/render-doc/{client}/{version}/{code}/{doc_id}/ returns JSON with
    an "html" field holding the full server-rendered section text.

This adapter therefore overrides the base Playwright fetch() with an API fetch;
the base run()/parse orchestration is otherwise unchanged.
"""

from __future__ import annotations

import base64
import json
import logging
import zlib
from urllib.parse import urlparse

from ..base import BaseScraper, ScrapedSection
from ..keywords import hints_for, search_terms_for

logger = logging.getLogger(__name__)

_ALP_HOST = "codelibrary.amlegal.com"
_ALP_BASE = f"https://{_ALP_HOST}"


def _search_ctx(query: str) -> str:
    """Build the ALP search 's' parameter: base64(zlib(json({"query": ...})))."""
    payload = json.dumps({"query": query}).encode("utf-8")
    return base64.b64encode(zlib.compress(payload)).decode("ascii")


class ALPScraper(BaseScraper):
    publisher = "alp"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._city_path, self._code_segment = self._parse_base_url(self.base_url)
        self._session = None  # lazy curl_cffi session

    # ------------------------------------------------------------------
    # curl_cffi session (Cloudflare bypass via TLS impersonation)
    # ------------------------------------------------------------------
    def _client(self):
        if self._session is None:
            from curl_cffi import requests as cr

            self._session = cr.Session(impersonate="chrome124")
        return self._session

    @staticmethod
    def _parse_base_url(base_url: str) -> tuple[str, str | None]:
        """Return (client_slug, code_slug) from .../codes/{client}/latest/{code}/..."""
        parts = [p for p in urlparse(base_url).path.split("/") if p]
        client = code = None
        if "codes" in parts:
            i = parts.index("codes")
            client = parts[i + 1] if len(parts) > i + 1 else None
        if "latest" in parts:
            li = parts.index("latest")
            if len(parts) > li + 1:
                code = parts[li + 1]
        return client or "", code

    @staticmethod
    def _section_url(client: str, code: str, doc_id: str, version: str = "latest") -> str:
        return f"{_ALP_BASE}/codes/{client}/{version}/{code}/{doc_id}"

    @staticmethod
    def _render_doc_api(url: str) -> str | None:
        """Map a section URL to its render-doc API URL."""
        parts = [p for p in urlparse(url).path.split("/") if p]
        # /codes/{client}/{version}/{code}/{doc_id}
        if len(parts) < 5 or parts[0] != "codes":
            return None
        client, version, code, doc_id = parts[1], parts[2], parts[3], parts[4]
        return f"{_ALP_BASE}/api/render-doc/{client}/{version}/{code}/{doc_id}/"

    # ------------------------------------------------------------------
    # discovery via the search API
    # ------------------------------------------------------------------
    def discover_sections(self) -> list[str]:
        urls: list[str] = []
        client = self._client()
        for term in search_terms_for(self.slug)[:3]:
            self._rate_limit()
            try:
                resp = client.get(
                    f"{_ALP_BASE}/api/search/",
                    params={"s": _search_ctx(term), "offset": 0, "limit": 40},
                    headers={"Accept": "application/json"},
                    timeout=self.settings.nav_timeout_ms / 1000,
                )
                if resp.status_code != 200:
                    logger.warning("[%s] ALP search %r -> HTTP %s", self.slug, term, resp.status_code)
                    continue
                results = resp.json().get("results", [])
            except Exception as exc:  # noqa: BLE001 - degrade to hints
                logger.warning("[%s] ALP search %r failed: %s", self.slug, term, exc)
                continue

            for r in results:
                if r.get("client_slug") != self._city_path:
                    continue  # scope to this city (search is global)
                if r.get("is_minute"):
                    continue
                code = r.get("code_slug")
                doc_id = r.get("doc_id")
                version = r.get("version") or "latest"
                if code and doc_id:
                    urls.append(self._section_url(self._city_path, code, doc_id, version))

        # Deterministic fallback so a drifted API still yields something.
        urls.extend(hints_for(self.slug).get("hint_urls", []))
        if self.base_url:
            urls.append(self.base_url)
        return urls

    # ------------------------------------------------------------------
    # content fetch via render-doc API (overrides base Playwright fetch)
    # ------------------------------------------------------------------
    def fetch(self, url: str, wait_selector: str | None = None) -> str:
        """Return the section's HTML via ALP's render-doc API (Cloudflare-safe)."""
        self._rate_limit()
        api = self._render_doc_api(url)
        client = self._client()
        if api is None:
            # Non-section URL (e.g. code root): fetch the page HTML directly.
            resp = client.get(url, timeout=self.settings.nav_timeout_ms / 1000)
            return resp.text

        resp = client.get(
            api,
            headers={"Accept": "application/json"},
            timeout=self.settings.nav_timeout_ms / 1000,
        )
        resp.raise_for_status()
        data = resp.json()
        html = data.get("html") or ""
        title = data.get("title") or ""
        # Wrap so parse_section's heading selectors can find the title.
        if title:
            html = f"<h1>{title}</h1>\n{html}"
        if self.settings.save_snapshots:
            self._snapshot(url, html)
        return html

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    def parse_section(self, url: str, html: str) -> ScrapedSection | None:
        soup = self.soup(html)
        # render-doc html is already just the section body; take all of its text.
        text = self.clean_text(soup)
        if len(text) < 50:
            return None
        heading = self.find_heading(soup)
        nums = self.parse_numbering(heading, text)
        return ScrapedSection(
            section_url=url,
            raw_text=text,
            title_number=nums["title_number"],
            chapter_number=nums["chapter_number"],
            section_number=nums["section_number"],
        )
