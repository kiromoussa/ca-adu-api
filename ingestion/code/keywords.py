"""ADU search phrases + per-jurisdiction chapter hints for code discovery.

Feeds the site-internal / API full-text search on both publishers and provides
a deterministic fallback (known chapter URLs) when a publisher's search drifts.
Keyed by the jurisdiction slug used in config/jurisdictions.yaml.
"""

from __future__ import annotations

# Ordered most specific -> least specific. Both publishers index the literal
# phrase, so the canonical phrase is typed first.
SEARCH_PHRASES: list[str] = [
    "accessory dwelling unit",
    "junior accessory dwelling unit",
    "ADU",
    "JADU",
]

# Substrings that, in a heading or link text, mark a section worth keeping.
ADU_KEYWORDS: list[str] = [
    "accessory dwelling unit",
    "junior accessory dwelling",
    "accessory dwelling",
    " adu",
    "adu ",
    "(adu)",
    "jadu",
    "in-law unit",     # San Francisco's historical term
    "second unit",
    "residential zoning district",
    "residential zone",
    "urban lot split",
    "two-unit",         # SB 9 duplex phrasing
]

# Per-jurisdiction hints.
#   search_terms  extra phrases searched in addition to SEARCH_PHRASES
#   chapters      chapter/section fragments expected in headings/URLs
#   hint_urls     deterministic fallback section URLs (ALP: render-doc doc nodes;
#                 Municode: URLs carrying ?nodeId=)
JURISDICTION_HINTS: dict[str, dict] = {
    # ----- American Legal Publishing -----
    "los_angeles": {
        "search_terms": ["12.22", "accessory dwelling unit", "SB 9", "urban lot split"],
        "chapters": ["12.22", "12.24", "12.03"],
        "titles": ["12"],
        "hint_urls": [
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
            "https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-19964",
            "https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-19955",
        ],
    },
    "sacramento": {
        "search_terms": ["accessory dwelling unit", "Title 17", "17.228"],
        "chapters": ["17.108", "17.228", "17.812"],
        "titles": ["17"],
        "hint_urls": [
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
            "20.30.460", "20.30.470", "20.30.480", "20.30.490", "20.30.495", "20.30",
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
    """Return the hint block for a jurisdiction slug, or a safe empty default."""
    return JURISDICTION_HINTS.get(
        slug, {"search_terms": [], "chapters": [], "titles": [], "hint_urls": []}
    )


def search_terms_for(slug: str) -> list[str]:
    """Ordered, de-duplicated search terms for a jurisdiction (hints first)."""
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


if __name__ == "__main__":  # offline self-check
    assert text_matches_adu("Accessory Dwelling Units")
    assert not text_matches_adu("Parking garages")
    assert search_terms_for("los_angeles")[0] == "12.22"
    print("keywords OK")
