"""ADU Atlas - municipal-code ingestion + OFFLINE rule extraction + QA.

This package is OFFLINE ONLY. It scrapes municipal code, snapshots the raw
bytes immutably, writes zoning_sections, produces LLM extraction CANDIDATES
(zoning_rules + rule_attributes, never auto-verified), and queues state-baseline
conflicts into qa_issues.

It MUST NEVER be imported by the API request path (services/api, services/core).
The request path is deterministic (versioned rules + PostGIS + source-linked
data) and does not run any LLM. As a tripwire, importing this package while the
request-path marker env var is set raises immediately.
"""

from __future__ import annotations

import os

if os.environ.get("ADU_ATLAS_REQUEST_PATH") in {"1", "true", "yes", "on"}:
    raise RuntimeError(
        "ingestion.code is OFFLINE-only and must not be imported on the API "
        "request path (ADU_ATLAS_REQUEST_PATH is set). The request path uses "
        "deterministic rules + PostGIS only, never LLM extraction."
    )

__all__ = ["__version__"]
__version__ = "0.1.0"
