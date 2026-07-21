"""GIS ingestion subpackage.

Source-specific ingesters plus the ``run`` dispatch entrypoint. Each ingester
exposes ``ingest(ctx: GisContext)`` returning an :class:`IngestResult` (or a
list of them for LA, which covers both zoning and parcels).
"""

from .common import (
    GisContext,
    GISDatabase,
    IngestResult,
    Settings,
    content_hash,
)

__all__ = [
    "GisContext",
    "GISDatabase",
    "IngestResult",
    "Settings",
    "content_hash",
]
