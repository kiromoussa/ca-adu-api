"""Municipal-code fetchers, dispatched by publisher.

american_legal -> AmericanLegalFetcher (curl_cffi + render-doc API)
municode       -> MunicodeFetcher      (Playwright render of nodeId pages)
"""

from __future__ import annotations

from typing import Any

from .american_legal import AmericanLegalFetcher
from .base import BaseCodeFetcher, FetchedSection, SelectorDriftError
from .municode import MunicodeFetcher

__all__ = [
    "AmericanLegalFetcher",
    "MunicodeFetcher",
    "BaseCodeFetcher",
    "FetchedSection",
    "SelectorDriftError",
    "fetcher_for",
]

_BY_PUBLISHER: dict[str, type[BaseCodeFetcher]] = {
    "american_legal": AmericanLegalFetcher,
    "municode": MunicodeFetcher,
}


def fetcher_for(publisher: str) -> type[BaseCodeFetcher] | None:
    """Return the fetcher class for a publisher type, or None if unknown."""
    return _BY_PUBLISHER.get(publisher)
