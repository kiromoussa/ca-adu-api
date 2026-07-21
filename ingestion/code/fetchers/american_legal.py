"""American Legal Publishing fetcher (codelibrary.amlegal.com).

Covers Los Angeles (v1), and - once ingested - San Diego, San Francisco,
Sacramento. American Legal serves an Angular SPA behind a Cloudflare bot check
that blocks plain HTTP clients and headless Playwright alike. The reliable path
is American Legal's own JSON API, reached with curl_cffi impersonating a real
Chrome TLS/JA3 fingerprint (which clears Cloudflare):

  - Discovery: GET /api/search/?s=<ctx>&offset=&limit=, where <ctx> is
    base64(zlib(json({"query": term}))). Results carry client_slug, code_slug
    and doc_id; filter to this jurisdiction and turn them into section URLs.
  - Content: GET /api/render-doc/{client}/{version}/{code}/{doc_id}/ returns
    JSON with an "html" field holding the server-rendered section text.

curl_cffi and requests are imported lazily so environments that only need the
Municode path (or run offline self-checks) do not require curl_cffi installed.
"""

from __future__ import annotations

import base64
import json
import logging
import zlib
from urllib.parse import urlparse

from keywords import hints_for, search_terms_for
from normalize import (
    clean_text,
    find_heading,
    parse_numbering,
    section_label,
    soup,
)

from .base import BaseCodeFetcher, FetchedSection

logger = logging.getLogger(__name__)

_ALP_HOST = "codelibrary.amlegal.com"
_ALP_BASE = f"https://{_ALP_HOST}"


def _search_ctx(query: str) -> str:
    """Build the American Legal search 's' param: base64(zlib(json({'query':...})))."""
    payload = json.dumps({"query": query}).encode("utf-8")
    return base64.b64encode(zlib.compress(payload)).decode("ascii")


class AmericanLegalFetcher(BaseCodeFetcher):
    publisher = "american_legal"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._client_slug, self._code_slug = self._parse_base_url(self.base_url)
        self._session = None

    # ------------------------------------------------------------------
    def _client(self):
        if self._session is None:
            from curl_cffi import requests as cr  # lazy import

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
        """Map a section URL to its render-doc API URL, or None if not a section."""
        parts = [p for p in urlparse(url).path.split("/") if p]
        # /codes/{client}/{version}/{code}/{doc_id}
        if len(parts) < 5 or parts[0] != "codes":
            return None
        client, version, code, doc_id = parts[1], parts[2], parts[3], parts[4]
        return f"{_ALP_BASE}/api/render-doc/{client}/{version}/{code}/{doc_id}/"

    # ------------------------------------------------------------------
    def discover_sections(self) -> list[str]:
        urls: list[str] = []
        client = self._client()
        timeout = self.settings.nav_timeout_ms / 1000
        for term in search_terms_for(self.slug)[:4]:
            self._rate_limit()
            try:
                resp = client.get(
                    f"{_ALP_BASE}/api/search/",
                    params={"s": _search_ctx(term), "offset": 0, "limit": 40},
                    headers={"Accept": "application/json"},
                    timeout=timeout,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "[%s] ALP search %r -> HTTP %s", self.slug, term, resp.status_code
                    )
                    continue
                results = resp.json().get("results", [])
            except Exception as exc:  # degrade to hints
                logger.warning("[%s] ALP search %r failed: %s", self.slug, term, exc)
                continue

            for r in results:
                if r.get("client_slug") != self._client_slug:
                    continue  # search is global; scope to this jurisdiction
                if r.get("is_minute"):
                    continue
                code = r.get("code_slug")
                doc_id = r.get("doc_id")
                version = r.get("version") or "latest"
                if code and doc_id:
                    urls.append(self._section_url(self._client_slug, code, doc_id, version))

        # Deterministic fallback so a drifted API still yields something.
        urls.extend(hints_for(self.slug).get("hint_urls", []))
        if self.base_url:
            urls.append(self.base_url)
        return urls

    # ------------------------------------------------------------------
    def fetch_section(self, url: str) -> FetchedSection | None:
        self._rate_limit()
        client = self._client()
        timeout = self.settings.nav_timeout_ms / 1000
        api = self._render_doc_api(url)

        if api is None:
            # Non-section URL (e.g. code root): fetch page HTML directly.
            resp = client.get(url, timeout=timeout)
            html = resp.text or ""
            title = None
        else:
            resp = client.get(api, headers={"Accept": "application/json"}, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            html = data.get("html") or ""
            title = data.get("title") or None
            if title:
                html = f"<h1>{title}</h1>\n{html}"

        document = soup(html)
        text = clean_text(document)
        if len(text) < 50:
            return None
        heading = title or find_heading(document, self.heading_selectors)
        nums = parse_numbering(heading, text)
        label = section_label(
            nums["title_number"], nums["chapter_number"], nums["section_number"], heading or ""
        )
        etag = resp.headers.get("ETag") if hasattr(resp, "headers") else None
        last_modified = resp.headers.get("Last-Modified") if hasattr(resp, "headers") else None

        return FetchedSection(
            section_url=url,
            raw_bytes=html.encode("utf-8"),
            text=text,
            content_type="text/html",
            http_status=getattr(resp, "status_code", None),
            etag=etag,
            last_modified=last_modified,
            title=heading,
            code_title=self.source.get("code_title") or _default_code_title(self.slug),
            title_number=nums["title_number"],
            chapter_number=nums["chapter_number"],
            section_number=nums["section_number"],
            section_label=label,
        )


def _default_code_title(slug: str) -> str | None:
    return {
        "los_angeles": "LAMC",
        "san_diego": "San Diego Municipal Code",
        "san_francisco": "SF Planning Code",
        "sacramento": "Sacramento City Code Title 17",
    }.get(slug)
