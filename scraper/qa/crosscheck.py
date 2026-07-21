"""Cross-reference HCD findings against our scraped adu_rules data.

Discrepancy logic
-----------------
- If HCD has published an ordinance review letter for a city (findings of
  non-compliance) but every adu_rules row we hold for that city is flagged
  'compliant', that is a discrepancy: we are likely missing a non-compliance
  HCD already identified. Severity: warning.

- If our data flags a city 'more_restrictive'/'needs_review' but the APR shows
  the jurisdiction is actively permitting ADUs, that is informational context,
  not necessarily a conflict; recorded as info.

- If the APR dataset reports zero ADU permits for a city over the reporting
  window while our data says fully 'compliant', flag info (possible stale or
  overly optimistic extraction) for a human to eyeball.

Each discrepancy becomes a qa_alerts row (see alerts.py). This module is pure
logic over already-fetched inputs so it is unit-testable without the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .hcd import AprRecord, OrdinanceLetter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Discrepancy:
    slug: str
    source: str  # 'hcd_ordinance_letter' | 'hcd_apr'
    field: str | None
    scraped_value: str | None
    hcd_finding: str
    severity: str  # 'info' | 'warning' | 'critical'


def _city_flag_summary(rules_rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count compliance_flag values for one city's adu_rules rows."""
    summary = {"compliant": 0, "more_restrictive": 0, "needs_review": 0}
    for row in rules_rows:
        flag = row.get("compliance_flag")
        if flag in summary:
            summary[flag] += 1
    return summary


def cross_check(
    *,
    rules_by_slug: dict[str, list[dict[str, Any]]],
    apr_records: list[AprRecord],
    ordinance_letters: list[OrdinanceLetter],
) -> list[Discrepancy]:
    """Return the list of discrepancies found across all cities.

    Args:
        rules_by_slug: adu_rules rows grouped by city slug (from Supabase).
        apr_records: parsed APR rows (may be empty if the feed was unavailable).
        ordinance_letters: availability of known HCD review letters.
    """
    discrepancies: list[Discrepancy] = []

    letters_by_slug = {letter.slug: letter for letter in ordinance_letters}

    # ADU permit totals per city from APR (sum across years).
    apr_totals: dict[str, float] = {}
    apr_seen: set[str] = set()
    for rec in apr_records:
        apr_seen.add(rec.slug)
        if rec.adu_permits is not None:
            apr_totals[rec.slug] = apr_totals.get(rec.slug, 0.0) + rec.adu_permits

    for slug, rules_rows in rules_by_slug.items():
        summary = _city_flag_summary(rules_rows)
        total_rows = sum(summary.values())
        all_compliant = total_rows > 0 and summary["more_restrictive"] == 0 and summary["needs_review"] == 0

        # 1. HCD letter exists but our data shows nothing wrong.
        letter = letters_by_slug.get(slug)
        if letter and letter.available and all_compliant:
            discrepancies.append(
                Discrepancy(
                    slug=slug,
                    source="hcd_ordinance_letter",
                    field=None,
                    scraped_value="all rows compliant",
                    hcd_finding=(
                        "HCD has published an ADU ordinance review letter for this "
                        f"jurisdiction ({letter.url}) indicating findings, but our "
                        "adu_rules data flags no non-compliance."
                    ),
                    severity="warning",
                )
            )

        # 2. APR shows zero permitting activity but we call it fully compliant.
        if slug in apr_seen and all_compliant:
            total_permits = apr_totals.get(slug, 0.0)
            if total_permits <= 0:
                discrepancies.append(
                    Discrepancy(
                        slug=slug,
                        source="hcd_apr",
                        field="adu_permits",
                        scraped_value="all rows compliant",
                        hcd_finding=(
                            "APR dataset reports zero ADU permits for this jurisdiction "
                            "over the reporting window; verify the ordinance is actually "
                            "permissive and extraction is not overly optimistic."
                        ),
                        severity="info",
                    )
                )

        # 3. We flag issues; note the APR activity context for the reviewer.
        if summary["more_restrictive"] > 0:
            discrepancies.append(
                Discrepancy(
                    slug=slug,
                    source="hcd_apr",
                    field="compliance_flag",
                    scraped_value=f"{summary['more_restrictive']} zone(s) more_restrictive",
                    hcd_finding=(
                        "Our data flags one or more zones as more restrictive than the "
                        f"state baseline. APR permits on record: {apr_totals.get(slug, 0.0):.0f}. "
                        "Confirm against the current adopted ordinance."
                    ),
                    severity="info",
                )
            )

    logger.info("Cross-check produced %d discrepancies.", len(discrepancies))
    return discrepancies
