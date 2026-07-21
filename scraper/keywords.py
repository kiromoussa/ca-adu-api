"""ADU keyword list and per-city chapter hints.

Sourced from ca-adu-build-spec.md section 1 and the "CA ADU & Zoning Code Data
Sourcing Report" section 2. The keyword phrases feed the site-internal search on
both publishers; the per-city chapter hints are used both to rank/keep search
results and as a deterministic fallback when the search UI drifts.
"""

from __future__ import annotations

# Ordered most specific -> least specific. The first phrase is the canonical one
# to type into each publisher's full-text search box (both index the literal
# phrase, per the sourcing report).
SEARCH_PHRASES: list[str] = [
    "accessory dwelling unit",
    "junior accessory dwelling unit",
    "ADU",
    "JADU",
]

# Substrings that, if present in a section heading or link text, mark it as an
# ADU / zoning section worth keeping. Lower-cased comparison.
ADU_KEYWORDS: list[str] = [
    "accessory dwelling unit",
    "junior accessory dwelling",
    "accessory dwelling",
    " adu",
    "adu ",
    "(adu)",
    "jadu",
    "in-law unit",  # San Francisco's historical term
    "second unit",
    "residential zoning district",
    "residential zone",
]


# Per-city hints. Keyed by the city slug used in the `cities` table.
#   search_terms  extra phrases to search in addition to SEARCH_PHRASES
#   chapters      chapter/section number fragments expected in headings/URLs
#   hint_urls     deterministic fallback URLs (used only if search discovery
#                 finds nothing). ALP hint URLs are code-root nodes; Municode
#                 hint URLs carry a ?nodeId= fragment.
CITY_HINTS: dict[str, dict] = {
    # ----- American Legal Publishing (ALP) -----
    "los_angeles": {
        "search_terms": ["12.22", "accessory dwelling unit"],
        "chapters": ["12.22", "12.24"],
        "titles": ["12"],
        "hint_urls": [
            # SEC. 12.22 (contains the ADU/JADU provisions, 12.22 A.33).
            "https://codelibrary.amlegal.com/codes/los_angeles/latest/lapz/0-0-0-6561",
        ],
    },
    "san_diego": {
        "search_terms": [
            "accessory dwelling unit",
            "junior accessory dwelling unit",
            "Chapter 14 Article 1 Division 3",
        ],
        "chapters": ["14", "141", "142"],
        "titles": ["14", "13"],
        "hint_urls": [
            "https://codelibrary.amlegal.com/codes/san_diego/latest",
        ],
    },
    "san_francisco": {
        "search_terms": ["accessory dwelling unit", "in-law unit", "207"],
        "chapters": ["207", "102"],
        "titles": ["2"],
        "hint_urls": [
            # SEC. 207.2 (state-mandated ADU program) and 207.1 (local ADU program).
            "https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-19964",
            "https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-19955",
        ],
    },
    "sacramento": {
        "search_terms": ["accessory dwelling unit", "Title 17", "17.108"],
        "chapters": ["17.108", "17.228", "17.812"],
        "titles": ["17"],
        "hint_urls": [
            # 17.228.105 Accessory dwelling units and junior accessory dwelling units.
            "https://codelibrary.amlegal.com/codes/sacramentoca/latest/sacramento_ca/0-0-0-36106",
        ],
    },
    # ----- Municode -----
    "san_jose": {
        "search_terms": [
            "Part 4.5 Accessory Dwelling Units",
            "accessory dwelling unit",
            "20.30.46",
        ],
        "chapters": [
            "20.30.460",
            "20.30.470",
            "20.30.480",
            "20.30.490",
            "20.30.495",
            "20.30",
        ],
        "titles": ["20"],
        "hint_urls": [],
    },
    "irvine": {
        "search_terms": ["accessory dwelling unit", "Title 5 zoning"],
        "chapters": ["5"],
        "titles": ["5"],
        "hint_urls": [],
    },
    "long_beach": {
        "search_terms": ["accessory dwelling unit", "Title 21", "21.41"],
        "chapters": ["21.41", "21.45", "21.52"],
        "titles": ["21"],
        "hint_urls": [],
    },
    "oakland": {
        "search_terms": [
            "accessory dwelling unit",
            "Chapter 17.103",
            "residential zoning regulations",
        ],
        "chapters": ["17.103", "17.09", "17.10"],
        "titles": ["17"],
        "hint_urls": [],
    },
}


def hints_for(slug: str) -> dict:
    """Return the hint block for a city slug, or a safe empty default."""
    return CITY_HINTS.get(
        slug,
        {"search_terms": [], "chapters": [], "titles": [], "hint_urls": []},
    )


def search_terms_for(slug: str) -> list[str]:
    """Ordered, de-duplicated search terms for a city (hints first)."""
    terms: list[str] = []
    for term in list(hints_for(slug).get("search_terms", [])) + SEARCH_PHRASES:
        if term and term not in terms:
            terms.append(term)
    return terms


def text_matches_adu(text: str | None) -> bool:
    """True if the text looks like an ADU / relevant zoning heading."""
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in ADU_KEYWORDS)
