"""Text + HTML helpers shared by the code fetchers and the ingest orchestrator.

Pure, dependency-light (beautifulsoup4 only). No network, no DB, no LLM.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup


def soup(html: str) -> BeautifulSoup:
    """Parse HTML, preferring lxml, falling back to the stdlib parser."""
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # lxml not installed -> stdlib parser
        return BeautifulSoup(html, "html.parser")


def clean_text(node: Any) -> str:
    """Collapse a BeautifulSoup node to trimmed, newline-separated text."""
    if node is None:
        return ""
    text = node.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()


def normalize_text(text: str | None) -> str:
    """Whitespace-normalized form used for hashing / change detection."""
    return re.sub(r"\s+", " ", text or "").strip()


def content_hash(text: str | None) -> str:
    """SHA-256 of the normalized text (stable across incidental whitespace)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    """SHA-256 of a raw byte payload (used for immutable source snapshots)."""
    return hashlib.sha256(payload).hexdigest()


def find_heading(document: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    """Return the first non-empty heading matched by the candidate selectors."""
    for selector in selectors:
        node = document.select_one(selector)
        if node:
            text = clean_text(node)
            if text:
                return text.splitlines()[0][:300]
    return None


def parse_numbering(heading: str | None, text: str) -> dict[str, str | None]:
    """Best-effort extraction of title / chapter / section numbers.

    Handles dotted municipal-code numbering (12.22, 20.30.460, 17.228.105) and
    explicit "Title N" / "Chapter N" / "Sec. N" phrasing found in headings.
    """
    result: dict[str, str | None] = {
        "title_number": None,
        "chapter_number": None,
        "section_number": None,
    }
    haystack = heading or (text or "")[:400]
    if not haystack:
        return result

    m_title = re.search(r"\bTitle\s+(\d+[A-Za-z]?)", haystack, re.I)
    if m_title:
        result["title_number"] = m_title.group(1)

    m_chapter = re.search(r"\bChapter\s+([\d.]+[A-Za-z]?)", haystack, re.I)
    if m_chapter:
        result["chapter_number"] = m_chapter.group(1).rstrip(".")

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


def section_label(
    title_number: str | None,
    chapter_number: str | None,
    section_number: str | None,
    fallback: str = "",
) -> str:
    """Human-readable label like '12 / 12.22 / 12.22 A.33' for provenance."""
    parts = [p for p in (title_number, chapter_number, section_number) if p]
    return " / ".join(parts) if parts else fallback


if __name__ == "__main__":  # offline self-check
    assert normalize_text("  a\n b  ") == "a b"
    assert content_hash("a b") == content_hash("a  b\n")
    nums = parse_numbering("Sec. 12.22 A.33 Accessory Dwelling Units", "")
    assert nums["section_number"] == "12.22", nums
    assert section_label("12", "12.22", "12.22") == "12 / 12.22 / 12.22"
    print("normalize OK")
