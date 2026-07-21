"""ADU Atlas ingestion package.

Namespace package for the GIS / ArcGIS ingestion workers. Sub-packages:

- ``ingestion.arcgis``  robust ArcGIS REST client (metadata, query, pagination,
  retries, rate limiting, ETag / Last-Modified caching).
- ``ingestion.gis``     source-specific ingesters (LA ZIMAS parcels + zoning,
  FEMA flood, CAL FIRE fire, CA statewide zoning bootstrap) plus the dispatch
  entrypoint ``ingestion.gis.run``.

Nothing here touches the API request path. Ingestion is offline / scheduled and
writes immutable, content-hashed ``source_snapshots`` plus ``ingest_runs`` rows.
"""

__all__ = ["arcgis", "gis"]
