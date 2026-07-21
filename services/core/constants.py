"""Version stamps and the verbatim legal disclaimer.

The disclaimer string here MUST match the ``const`` in
``openapi/openapi.yaml`` (FeasibilityResponse.disclaimer) exactly. It is emitted
verbatim in every feasibility response. Do not paraphrase it.
"""

from __future__ import annotations

# Semantic version of the deterministic analysis engine (services.core). Bump on
# any change that can alter a feasibility result for identical inputs.
ANALYSIS_VERSION = "1.0.0"

# Version of the local rule set shape the engine reads. Individual jurisdiction
# rule versions live on ``zoning_rules.version``; this is the engine contract.
RULES_VERSION = "1.0.0"

# Version tag for the seeded California state-law baselines (seed_baselines.sql).
STATE_BASELINE_VERSION = "2024.01"

# The exact disclaimer, emitted verbatim in every feasibility response. Kept as a
# single normalized-whitespace string so it is byte-identical everywhere.
DISCLAIMER = (
    "This is preliminary informational zoning and GIS analysis, not legal, "
    "architectural, surveying, engineering, title, environmental, or permit "
    "advice. Verify all results with the applicable jurisdiction and qualified "
    "professionals before making decisions or spending money."
)

# Terminal feasibility statuses. Never an approval or a legal yes/no.
FEASIBILITY_STATUSES = (
    "likely_feasible",
    "likely_constrained",
    "needs_professional_review",
    "insufficient_data",
)

# Per-path eligibility statuses.
PATH_STATUSES = (
    "likely_eligible",
    "likely_ineligible",
    "conditional",
    "needs_professional_review",
    "insufficient_data",
)

# Project types accepted by the API (mirrors the OpenAPI ProjectType enum and the
# CHECK constraints in migration 0005).
PROJECT_TYPES = (
    "detached_adu",
    "attached_adu",
    "garage_conversion",
    "jadu",
    "sb9_duplex",
    "sb9_urban_lot_split",
)

# The SB 9 project types (single-family-zone gated).
SB9_PROJECT_TYPES = ("sb9_duplex", "sb9_urban_lot_split")

# DB-level compliance flags (migration 0005 CHECK on rule_attributes /
# zoning_rules) mapped to the API-level ComplianceFlag enum.
#   DB: matches_state_baseline | possibly_more_restrictive_than_state_baseline |
#       needs_review | not_applicable
#   API: compliant | needs_review | possibly_more_restrictive_than_state_baseline
DB_COMPLIANCE_MATCHES = "matches_state_baseline"
DB_COMPLIANCE_MORE_RESTRICTIVE = "possibly_more_restrictive_than_state_baseline"
DB_COMPLIANCE_NEEDS_REVIEW = "needs_review"
DB_COMPLIANCE_NOT_APPLICABLE = "not_applicable"


def db_compliance_to_api(flag: str | None) -> str | None:
    """Map a DB compliance flag to the API ComplianceFlag enum (or ``None``).

    ``not_applicable`` and unknown values map to ``None`` so the field is simply
    omitted from the sourced-value wrapper rather than asserting a comparison
    that was never made.
    """
    if flag == DB_COMPLIANCE_MATCHES:
        return "compliant"
    if flag == DB_COMPLIANCE_MORE_RESTRICTIVE:
        return "possibly_more_restrictive_than_state_baseline"
    if flag == DB_COMPLIANCE_NEEDS_REVIEW:
        return "needs_review"
    return None
