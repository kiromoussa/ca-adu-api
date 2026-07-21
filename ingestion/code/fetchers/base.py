"""Base class + shared data type for municipal-code fetchers.

A fetcher turns one jurisdiction's official code source into a stream of
FetchedSection objects (raw bytes for the immutable snapshot + cleaned text +
numbering). It performs discovery, polite rate limiting, retries, and parsing;
it does NOT touch the database (the ingest orchestrator owns snapshots + writes).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from normalize import content_hash as _content_hash
from normalize import normalize_text

logger = logging.getLogger(__name__)

_MIN_CONTENT_CHARS = 50


class SelectorDriftError(RuntimeError):
    """Raised when no candidate selector matches - publisher DOM likely changed."""


@dataclass
class FetchedSection:
    """One municipal-code section captured from a publisher."""

    section_url: str
    raw_bytes: bytes                       # exact captured payload for snapshotting
    text: str                              # cleaned, human-readable section text
    content_type: str = "text/html"
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    title: str | None = None
    code_title: str | None = None          # e.g. LAMC, Planning Code
    title_number: str | None = None
    chapter_number: str | None = None
    section_number: str | None = None
    section_label: str | None = None
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def content_hash(self) -> str:
        """SHA-256 over the normalized text (change detection for zoning_sections)."""
        return _content_hash(self.text)

    @property
    def normalized_text(self) -> str:
        return normalize_text(self.text)


class BaseCodeFetcher(ABC):
    """Shared fetch machinery. One instance per jurisdiction per run."""

    publisher: str = "base"
    code_title: str | None = None

    content_selectors: tuple[str, ...] = ("main", "[role='main']", "article", "body")
    heading_selectors: tuple[str, ...] = ("h1", "h2", "header h1", ".title")

    def __init__(
        self,
        jurisdiction: dict[str, Any],
        source: dict[str, Any],
        settings: Any,
    ) -> None:
        self.jurisdiction = jurisdiction
        self.slug = jurisdiction.get("slug", "unknown")
        self.source = source
        self.base_url = str(source.get("base_url") or "")
        self.settings = settings
        self._last_request_ts = 0.0

    # ------------------------------------------------------------------
    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        wait = self.settings.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    # ------------------------------------------------------------------
    @abstractmethod
    def discover_sections(self) -> list[str]:
        """Return candidate section URLs for this jurisdiction."""

    @abstractmethod
    def fetch_section(self, url: str) -> FetchedSection | None:
        """Fetch + parse one section URL into a FetchedSection (or None)."""

    # ------------------------------------------------------------------
    def run(self) -> Iterator[FetchedSection]:
        """Discover -> fetch -> yield each parsed section. Resilient per-URL."""
        try:
            urls = self.discover_sections()
        except Exception as exc:  # discovery failure is fatal for this source
            logger.error("[%s] discovery failed: %s", self.slug, exc)
            return

        seen: set[str] = set()
        ordered: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                ordered.append(url)
        ordered = ordered[: self.settings.max_sections_per_jurisdiction]
        logger.info("[%s] discovered %d candidate section(s)", self.slug, len(ordered))

        for url in ordered:
            try:
                section = self.fetch_section(url)
            except SelectorDriftError as exc:
                logger.error("[%s] selector drift at %s: %s", self.slug, url, exc)
                continue
            except Exception as exc:  # keep the run alive across one bad section
                logger.error("[%s] fetch/parse failed at %s: %s", self.slug, url, exc)
                continue
            if section is None or len(section.text.strip()) < _MIN_CONTENT_CHARS:
                logger.debug("[%s] no usable content at %s", self.slug, url)
                continue
            yield section
