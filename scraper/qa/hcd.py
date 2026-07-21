"""HCD data sources for the QA cross-check.

Two feeds are consumed:

1. Housing Element Annual Progress Report (APR) CSV, published on the CA Open
   Data Portal (data.ca.gov). This is a bulk CSV, not a live JSON API, so we
   download it and filter to our 8 target jurisdictions. It carries ADU permit
   counts per jurisdiction/year - used as a coarse activity signal and to
   confirm a jurisdiction is actually permitting ADUs.

2. HCD ADU/JADU ordinance review letters. HCD periodically publishes
   jurisdiction-specific PDFs flagging where a local ordinance deviates from
   state law. There is no API; we track the known letter URLs and treat any
   published letter for one of our cities as a "known discrepancy" signal that
   should be reconciled against our scraped adu_rules data.

Nothing here writes to the database - callers pass the parsed findings to
crosscheck.py.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_APR_DATASET_PAGE = (
    "https://data.ca.gov/dataset/"
    "housing-element-annual-progress-report-apr-data-by-jurisdiction-and-year"
)

# CKAN datastore is fronted by a package_show API on data.ca.gov. When the
# direct CSV resource URL is known it can be set via HCD_APR_CSV_URL; otherwise
# we resolve the newest CSV resource from the dataset's CKAN metadata.
CKAN_PACKAGE_SHOW = (
    "https://data.ca.gov/api/3/action/package_show"
    "?id=housing-element-annual-progress-report-apr-data-by-jurisdiction-and-year"
)

# Known HCD ADU ordinance review letters (jurisdiction -> letter URL). These are
# HCD's own findings of non-compliance and are the highest-value QA ground truth.
# Extend as HCD publishes more. Keyed by our city slug.
ORDINANCE_REVIEW_LETTERS: dict[str, str] = {
    "irvine": (
        "https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/"
        "ordinance-review-letters/irvine-adu-findings-010725.pdf"
    ),
    "san_jose": (
        "https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/"
        "ordinance-review-letters/san-jose-adu-ta-12102025.pdf"
    ),
}

# Jurisdiction name as it appears in the APR CSV -> our city slug.
APR_JURISDICTION_TO_SLUG: dict[str, str] = {
    "los angeles": "los_angeles",
    "san diego": "san_diego",
    "san francisco": "san_francisco",
    "sacramento": "sacramento",
    "san jose": "san_jose",
    "san josé": "san_jose",
    "irvine": "irvine",
    "long beach": "long_beach",
    "oakland": "oakland",
}


@dataclass(frozen=True)
class AprRecord:
    """One APR row reduced to the fields we care about."""

    slug: str
    jurisdiction: str
    year: str | None
    adu_permits: float | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class OrdinanceLetter:
    """A published HCD ordinance review letter for one of our cities."""

    slug: str
    url: str
    available: bool


def _http_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "ca-adu-zoning-api-qa/0.1 (+https://github.com/ca-adu-api)"},
    )


def resolve_apr_csv_url(client: httpx.Client | None = None) -> str | None:
    """Find the newest CSV resource URL for the APR dataset.

    Honors HCD_APR_CSV_URL if set. Otherwise queries the CKAN package_show API
    and returns the most recently modified CSV resource. Returns None if it
    cannot be resolved.
    """
    override = os.environ.get("HCD_APR_CSV_URL")
    if override:
        return override

    owns_client = client is None
    client = client or _http_client()
    try:
        resp = client.get(CKAN_PACKAGE_SHOW)
        resp.raise_for_status()
        payload = resp.json()
        resources = (payload.get("result") or {}).get("resources") or []
        csvs = [r for r in resources if str(r.get("format", "")).lower() == "csv" and r.get("url")]
        if not csvs:
            logger.warning("No CSV resource found in APR dataset metadata.")
            return None
        csvs.sort(key=lambda r: r.get("last_modified") or r.get("created") or "", reverse=True)
        return csvs[0]["url"]
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Could not resolve APR CSV url via CKAN: %s", exc)
        return None
    finally:
        if owns_client:
            client.close()


def _find_column(fieldnames: list[str], *candidates: str) -> str | None:
    """Case/space-insensitive column matcher over the CSV header."""
    norm = {name.strip().lower(): name for name in fieldnames}
    for cand in candidates:
        key = cand.strip().lower()
        if key in norm:
            return norm[key]
    # loose contains match as a fallback
    for cand in candidates:
        key = cand.strip().lower()
        for low, orig in norm.items():
            if key in low:
                return orig
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_apr_records(client: httpx.Client | None = None) -> list[AprRecord]:
    """Download and parse the APR CSV, filtered to our 8 target jurisdictions.

    Aggregates ADU permit counts per jurisdiction across all years/columns that
    look ADU-related. Returns [] on any fetch/parse failure (the cross-check
    degrades gracefully to letter-only signals).
    """
    owns_client = client is None
    client = client or _http_client()
    try:
        url = resolve_apr_csv_url(client)
        if not url:
            return []
        resp = client.get(url)
        resp.raise_for_status()
        text = resp.content.decode("utf-8-sig", errors="replace")

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            return []

        juris_col = _find_column(reader.fieldnames, "jurisdiction", "jurisdiction name", "city")
        year_col = _find_column(reader.fieldnames, "year", "reporting year", "reporting_calendar_year")
        adu_col = _find_column(
            reader.fieldnames,
            "adu",
            "accessory dwelling unit",
            "adu_permitted",
            "adus permitted",
            "total adus",
        )
        if not juris_col:
            logger.warning("APR CSV missing a jurisdiction column; columns=%s", reader.fieldnames)
            return []

        records: list[AprRecord] = []
        for row in reader:
            juris_raw = (row.get(juris_col) or "").strip()
            slug = APR_JURISDICTION_TO_SLUG.get(juris_raw.lower())
            if not slug:
                continue
            records.append(
                AprRecord(
                    slug=slug,
                    jurisdiction=juris_raw,
                    year=(row.get(year_col) if year_col else None),
                    adu_permits=(_to_float(row.get(adu_col)) if adu_col else None),
                    raw=row,
                )
            )
        logger.info("Parsed %d APR rows for target jurisdictions.", len(records))
        return records
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Could not fetch/parse APR CSV: %s", exc)
        return []
    finally:
        if owns_client:
            client.close()


def check_ordinance_letters(client: httpx.Client | None = None) -> list[OrdinanceLetter]:
    """HEAD each known ordinance review letter to confirm it is published.

    A reachable letter for a city is a strong "HCD has findings against this
    jurisdiction" signal for the cross-check.
    """
    owns_client = client is None
    client = client or _http_client()
    results: list[OrdinanceLetter] = []
    try:
        for slug, url in ORDINANCE_REVIEW_LETTERS.items():
            available = False
            try:
                resp = client.head(url)
                available = resp.status_code < 400
                if not available:  # some servers reject HEAD; retry with GET range
                    resp = client.get(url, headers={"Range": "bytes=0-1024"})
                    available = resp.status_code < 400
            except Exception as exc:  # pragma: no cover - network dependent
                logger.warning("Ordinance letter check failed for %s: %s", slug, exc)
            results.append(OrdinanceLetter(slug=slug, url=url, available=available))
        return results
    finally:
        if owns_client:
            client.close()
