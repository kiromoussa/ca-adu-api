"""PostGIS-backed implementation of :class:`FeasibilityRepository`.

Uses psycopg 3 (sync) against ``SUPABASE_DB_URL`` (the pooled Supabase Postgres
connection string, authenticated with the service role). All spatial predicates
run server-side in PostGIS:

- parcel matching uses ``ST_Contains`` first, then ``ST_DWithin`` on the
  geography type with a documented tolerance (meters) as the fallback;
- the zoning join and overlay intersection use ``ST_Intersects``;
- the envelope inward buffer is computed in California Albers (EPSG:3310, an
  equal-area meter CRS) so ``ST_Area`` after a negative ``ST_Buffer`` is metric
  and accurate for parcel-scale polygons.

psycopg is imported lazily so the pure core and its unit tests do not require the
driver to be installed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .repository import (
    Baseline,
    BufferedArea,
    GeoPoint,
    JurisdictionMatch,
    OverlayResult,
    ParcelMatch,
    RuleAttr,
    SourceRef,
    ZoneMatch,
    ZoningResult,
    ZoningRuleSet,
)
from .spatial import DEFAULT_PARCEL_TOLERANCE_M

# Overlay types we actively expect for LA v1 (statewide/federal sources).
_EXPECTED_OVERLAY_TYPES = ("flood", "fire")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresRepository:
    """Concrete repository over a psycopg connection pool."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8):
        if not dsn:
            raise ValueError("A Postgres DSN (SUPABASE_DB_URL) is required.")
        self._dsn = dsn
        self._pool = None  # lazy
        self._min_size = min_size
        self._max_size = max_size

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def _get_pool(self):
        if self._pool is None:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(
                self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                kwargs={"autocommit": True},
                open=True,
            )
        return self._pool

    def _rows(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        from psycopg.rows import dict_row

        with self._get_pool().connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return []
                return list(cur.fetchall())

    def _row(self, sql: str, params: tuple = ()) -> Optional[dict[str, Any]]:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self._get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Source-ref helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _source_from_row(
        row: dict[str, Any],
        *,
        default_title: str,
        confidence: Optional[str] = None,
    ) -> SourceRef:
        return SourceRef(
            source_url=row.get("source_url") or "urn:aduatlas:unknown-source",
            source_title=row.get("source_title") or default_title,
            source_section=row.get("source_section"),
            source_layer=row.get("source_layer"),
            retrieved_at=row.get("retrieved_at"),
            last_verified_at=row.get("last_verified_at"),
            confidence=confidence or row.get("confidence") or "medium",
            data_status=row.get("data_status") or "current",
        )

    # ------------------------------------------------------------------
    # Step A: address -> jurisdiction
    # ------------------------------------------------------------------
    def find_jurisdiction_for_point(self, point: GeoPoint) -> Optional[JurisdictionMatch]:
        row = self._row(
            """
            select id::text, slug, name, coverage_status, supported_project_types,
                   last_source_refresh_at
              from jurisdictions
             where boundary is not null
               and ST_Contains(boundary, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
             order by jurisdiction_type = 'city' desc
             limit 1
            """,
            (point.lon, point.lat),
        )
        if row is None:
            return None
        return self._jurisdiction_match(row, matched_confidence="high")

    def get_jurisdiction_by_slug(self, slug: str) -> Optional[JurisdictionMatch]:
        row = self._row(
            """
            select id::text, slug, name, coverage_status, supported_project_types,
                   last_source_refresh_at
              from jurisdictions
             where slug = %s
            """,
            (slug,),
        )
        if row is None:
            return None
        return self._jurisdiction_match(row, matched_confidence="medium")

    def _jurisdiction_match(self, row: dict[str, Any], matched_confidence: str) -> JurisdictionMatch:
        slug = row["slug"]
        source = SourceRef(
            source_url=f"https://api.aduatlas.example.com/v1/jurisdictions/{slug}",
            source_title=f"ADU Atlas jurisdiction boundary ({row['name']})",
            source_layer="jurisdictions.boundary",
            retrieved_at=row.get("last_source_refresh_at") or _now(),
            last_verified_at=row.get("last_source_refresh_at"),
            confidence=matched_confidence,
            data_status="current",
        )
        return JurisdictionMatch(
            id=row["id"],
            slug=slug,
            name=row["name"],
            display_name=row["name"],
            coverage_status=row["coverage_status"],
            matched_confidence=matched_confidence,
            source=source,
            supported_project_types=tuple(row.get("supported_project_types") or ()),
        )

    def list_jurisdictions(self) -> list[dict[str, Any]]:
        return self._rows(
            """
            select slug, name, name as display_name, state_code as state, county,
                   coverage_status, supported_project_types,
                   source_update_date, last_source_refresh_at
              from jurisdictions
             order by
               (coverage_status = 'production') desc,
               (coverage_status = 'ingesting') desc,
               name asc
            """
        )

    # ------------------------------------------------------------------
    # Step B: parcel lookup (ST_Contains, then ST_DWithin tolerance)
    # ------------------------------------------------------------------
    def find_parcel_for_point(
        self, jurisdiction_id: str, point: GeoPoint, tolerance_m: float = DEFAULT_PARCEL_TOLERANCE_M
    ) -> ParcelMatch:
        pt = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
        # 1) exact containment
        row = self._row(
            f"""
            select id::text, apn, area_sqft,
                   ST_X(centroid) as clon, ST_Y(centroid) as clat,
                   source_url, source_layer, confidence, data_status,
                   retrieved_at, last_verified_at
              from parcels
             where jurisdiction_id = %s
               and geom is not null
               and ST_Contains(geom, {pt})
             limit 1
            """,
            (jurisdiction_id, point.lon, point.lat),
        )
        method = "st_contains"
        if row is None:
            # 2) tolerance fallback (documented): nearest parcel within tolerance
            row = self._row(
                f"""
                select id::text, apn, area_sqft,
                       ST_X(centroid) as clon, ST_Y(centroid) as clat,
                       source_url, source_layer, confidence, data_status,
                       retrieved_at, last_verified_at
                  from parcels
                 where jurisdiction_id = %s
                   and geom is not null
                   and ST_DWithin(geom::geography, {pt}::geography, %s)
                 order by ST_Distance(geom::geography, {pt}::geography) asc
                 limit 1
                """,
                (jurisdiction_id, point.lon, point.lat, tolerance_m, point.lon, point.lat),
            )
            method = "st_intersects"
        if row is None:
            return ParcelMatch(matched=False, match_tolerance_m=tolerance_m)

        source = self._source_from_row(row, default_title="Parcel GIS layer")
        centroid = None
        if row.get("clon") is not None and row.get("clat") is not None:
            centroid = GeoPoint(lon=float(row["clon"]), lat=float(row["clat"]))
        return ParcelMatch(
            matched=True,
            id=row["id"],
            apn=row.get("apn"),
            lot_size_sqft=float(row["area_sqft"]) if row.get("area_sqft") is not None else None,
            centroid=centroid,
            match_method=method,
            match_tolerance_m=(0.0 if method == "st_contains" else tolerance_m),
            source=source,
        )

    # ------------------------------------------------------------------
    # Step C: zoning lookup (spatial join; cross-zone ambiguity)
    # ------------------------------------------------------------------
    def find_zoning_for_parcel(
        self, jurisdiction_id: str, parcel_id: Optional[str], point: GeoPoint
    ) -> ZoningResult:
        if parcel_id is not None:
            rows = self._rows(
                """
                select zd.zone_code, zd.zone_name, zd.zone_category,
                       zd.source_url, zd.source_layer, zd.confidence, zd.data_status,
                       zd.retrieved_at, zd.last_verified_at
                  from zoning_districts zd
                  join parcels p on p.id = %s
                 where zd.jurisdiction_id = %s
                   and zd.geom is not null
                   and ST_Intersects(zd.geom, p.geom)
                 order by ST_Area(ST_Intersection(zd.geom, p.geom)) desc
                """,
                (parcel_id, jurisdiction_id),
            )
        else:
            rows = self._rows(
                """
                select zone_code, zone_name, zone_category,
                       source_url, source_layer, confidence, data_status,
                       retrieved_at, last_verified_at
                  from zoning_districts
                 where jurisdiction_id = %s
                   and geom is not null
                   and ST_Contains(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                """,
                (jurisdiction_id, point.lon, point.lat),
            )
        zones: list[ZoneMatch] = []
        for r in rows:
            zones.append(
                ZoneMatch(
                    zone_code=r["zone_code"],
                    zone_name=r.get("zone_name"),
                    zone_category=r.get("zone_category"),
                    general_plan=None,
                    source=self._source_from_row(r, default_title="Zoning districts GIS layer"),
                )
            )
        return ZoningResult(zones=zones)

    # ------------------------------------------------------------------
    # Step D: overlay lookup (hit / no_hit / source_unavailable)
    # ------------------------------------------------------------------
    def find_overlays_for_parcel(
        self, jurisdiction_id: Optional[str], parcel_id: Optional[str], point: GeoPoint
    ) -> list[OverlayResult]:
        # Which overlay types have any features loaded at all (=> "available").
        avail_rows = self._rows("select distinct overlay_type from overlay_features")
        available = {r["overlay_type"] for r in avail_rows}

        # Intersecting features for this parcel/point.
        if parcel_id is not None:
            hit_rows = self._rows(
                """
                select ov.overlay_type, ov.name, ov.designation, ov.raw_feature_id,
                       ov.raw_value, ov.source_url, ov.source_layer, ov.confidence,
                       ov.data_status, ov.retrieved_at, ov.last_verified_at
                  from overlay_features ov
                  join parcels p on p.id = %s
                 where ov.geom is not null
                   and ST_Intersects(ov.geom, p.geom)
                """,
                (parcel_id,),
            )
        else:
            hit_rows = self._rows(
                """
                select overlay_type, name, designation, raw_feature_id, raw_value,
                       source_url, source_layer, confidence, data_status,
                       retrieved_at, last_verified_at
                  from overlay_features
                 where geom is not null
                   and ST_Intersects(geom, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
                """,
                (point.lon, point.lat),
            )

        results: list[OverlayResult] = []
        hit_types: set[str] = set()
        for r in hit_rows:
            ot = r["overlay_type"]
            hit_types.add(ot)
            raw = {
                "raw_feature_id": r.get("raw_feature_id"),
                "designation": r.get("designation"),
                "name": r.get("name"),
            }
            if isinstance(r.get("raw_value"), dict):
                raw.update(r["raw_value"])
            results.append(
                OverlayResult(
                    overlay_type=ot,
                    status="hit",
                    raw_values=raw,
                    description=r.get("designation") or r.get("name"),
                    source=self._source_from_row(r, default_title=f"{ot} overlay GIS layer"),
                )
            )

        # For every expected overlay type with no hit, distinguish no_hit from
        # source_unavailable based on whether the layer is loaded at all.
        for ot in _EXPECTED_OVERLAY_TYPES:
            if ot in hit_types:
                continue
            if ot in available:
                results.append(OverlayResult(overlay_type=ot, status="no_hit", source=None))
            else:
                results.append(
                    OverlayResult(
                        overlay_type=ot,
                        status="source_unavailable",
                        description="Overlay layer has not been ingested; presence "
                        "could not be determined.",
                        source=None,
                    )
                )
        return results

    # ------------------------------------------------------------------
    # Step E: rules
    # ------------------------------------------------------------------
    def get_zoning_rule(
        self, jurisdiction_id: str, zone_code: str, project_type: str
    ) -> Optional[ZoningRuleSet]:
        rule = self._row(
            """
            select id::text, zone_code, zone_name, project_type, version, review_status
              from zoning_rules
             where jurisdiction_id = %s
               and upper(zone_code) = upper(%s)
               and project_type = %s
               and is_current = true
             order by version desc
             limit 1
            """,
            (jurisdiction_id, zone_code, project_type),
        )
        if rule is None:
            return None
        attrs_rows = self._rows(
            """
            select field_name, value_json, value_numeric, unit, operator,
                   state_baseline_id::text as state_baseline_id, compliance_flag,
                   source_url, source_title, source_section, source_layer,
                   retrieved_at, last_verified_at, confidence, data_status
              from rule_attributes
             where zoning_rule_id = %s
             order by field_name
            """,
            (rule["id"],),
        )
        attributes: list[RuleAttr] = []
        for a in attrs_rows:
            value = a.get("value_json")
            if a.get("value_numeric") is not None:
                value = float(a["value_numeric"])
            attributes.append(
                RuleAttr(
                    field_name=a["field_name"],
                    value=value,
                    unit=a.get("unit"),
                    operator=a.get("operator"),
                    state_baseline_id=a.get("state_baseline_id"),
                    source=self._source_from_row(a, default_title="Local zoning ordinance"),
                )
            )
        return ZoningRuleSet(
            zone_code=rule["zone_code"],
            zone_name=rule.get("zone_name"),
            project_type=rule["project_type"],
            version=rule.get("version"),
            review_status=rule.get("review_status") or "pending",
            attributes=attributes,
        )

    def get_state_baselines(self, project_type: str) -> list[Baseline]:
        rows = self._rows(
            """
            select field_name, operator, baseline_value_json, unit, applies_to,
                   legal_citation, source_url, source_title, effective_from,
                   last_verified_at, confidence, data_status
              from state_rule_baselines
             where (cardinality(applies_to) = 0 or %s = any(applies_to))
               and (effective_to is null or effective_to > now())
             order by field_name
            """,
            (project_type,),
        )
        out: list[Baseline] = []
        for r in rows:
            out.append(
                Baseline(
                    field_name=r["field_name"],
                    operator=r["operator"],
                    baseline_value=r["baseline_value_json"],
                    unit=r.get("unit"),
                    applies_to=tuple(r.get("applies_to") or ()),
                    legal_citation=r["legal_citation"],
                    source_url=r["source_url"],
                    source_title=r.get("source_title"),
                    effective_from=str(r["effective_from"]) if r.get("effective_from") else None,
                    last_verified_at=r.get("last_verified_at"),
                    confidence=r.get("confidence") or "high",
                    data_status=r.get("data_status") or "current",
                )
            )
        return out

    # ------------------------------------------------------------------
    # Step F: envelope inward buffer (EPSG:3310 equal-area meters)
    # ------------------------------------------------------------------
    def compute_inward_buffer_area(self, parcel_id: str, inset_m: float) -> BufferedArea:
        row = self._row(
            """
            select ST_Area(ST_Buffer(ST_Transform(geom, 3310), %s)) as area_sqm,
                   source_url, source_layer, confidence, data_status,
                   retrieved_at, last_verified_at
              from parcels
             where id = %s
               and geom is not null
            """,
            (-abs(inset_m), parcel_id),
        )
        if row is None or row.get("area_sqm") is None:
            return BufferedArea(available=False, inset_m=inset_m)
        area = float(row["area_sqm"])
        if area <= 0.0:
            return BufferedArea(available=False, inset_m=inset_m)
        return BufferedArea(
            available=True,
            buffered_area_sqm=area,
            orientation_known=False,
            inset_m=inset_m,
            source=self._source_from_row(row, default_title="Parcel GIS layer"),
        )

    # ------------------------------------------------------------------
    # Cache + idempotency + persistence
    # ------------------------------------------------------------------
    def find_cached_analysis(self, request_fingerprint: str, within_hours: int) -> Optional[dict[str, Any]]:
        return self._row(
            """
            select pa.id::text, pa.feasibility_status, pa.coverage_status,
                   pa.result_json, j.slug as jurisdiction_slug
              from property_analyses pa
              left join jurisdictions j on j.id = pa.jurisdiction_id
             where pa.request_fingerprint = %s
               and pa.feasibility_status is not null
               and pa.created_at > now() - make_interval(hours => %s)
             order by pa.created_at desc
             limit 1
            """,
            (request_fingerprint, within_hours),
        )

    def find_by_idempotency_key(self, consumer_id: Optional[str], idempotency_key: str) -> Optional[dict[str, Any]]:
        return self._row(
            """
            select id::text, request_fingerprint, feasibility_status, result_json
              from property_analyses
             where idempotency_key = %s
               and coalesce(consumer_id, '') = coalesce(%s, '')
             order by created_at desc
             limit 1
            """,
            (idempotency_key, consumer_id),
        )

    def insert_analysis(self, record: dict[str, Any]) -> str:
        from psycopg.types.json import Jsonb

        lon = record.get("geocode_lon")
        lat = record.get("geocode_lat")
        geocode_sql = "ST_SetSRID(ST_MakePoint(%(geocode_lon)s, %(geocode_lat)s), 4326)" if lon is not None and lat is not None else "NULL"
        params = dict(record)
        params.setdefault("share_token", None)
        params["options"] = Jsonb(record.get("options") or {})
        params["result_json"] = Jsonb(record.get("result_json") or {})
        row = self._row(
            f"""
            insert into property_analyses
              (id, request_fingerprint, idempotency_key, share_token, consumer_id,
               provider, plan, input_address, normalized_address, geocode,
               project_type, target_sqft, bedrooms, proposed_height_ft,
               existing_structure, options, jurisdiction_id, parcel_id,
               coverage_status, feasibility_status, score, analysis_version,
               result_json, disclaimer, billable, billed, cache_hit)
            values
              (coalesce(%(id)s::uuid, gen_random_uuid()), %(request_fingerprint)s,
               %(idempotency_key)s, %(share_token)s, %(consumer_id)s, %(provider)s,
               %(plan)s, %(input_address)s, %(normalized_address)s, {geocode_sql},
               %(project_type)s, %(target_sqft)s, %(bedrooms)s, %(proposed_height_ft)s,
               %(existing_structure)s, %(options)s, %(jurisdiction_id)s::uuid,
               %(parcel_id)s::uuid, %(coverage_status)s, %(feasibility_status)s,
               %(score)s, %(analysis_version)s, %(result_json)s, %(disclaimer)s,
               %(billable)s, %(billed)s, %(cache_hit)s)
            returning id::text
            """,
            params,  # type: ignore[arg-type]
        )
        return row["id"] if row else record.get("id")

    def insert_findings(self, analysis_id: str, findings: list[dict[str, Any]]) -> None:
        from psycopg.types.json import Jsonb

        if not findings:
            return
        with self._get_pool().connection() as conn:
            with conn.cursor() as cur:
                for f in findings:
                    cur.execute(
                        """
                        insert into analysis_findings
                          (property_analysis_id, finding_type, project_path,
                           field_name, title, detail, value_json, feasibility_status,
                           compliance_flag, source_url, source_title, source_section,
                           source_layer, retrieved_at, last_verified_at, confidence,
                           data_status, sort_order)
                        values
                          (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s)
                        """,
                        (
                            analysis_id,
                            f.get("finding_type"),
                            f.get("project_path"),
                            f.get("field_name"),
                            f.get("title"),
                            f.get("detail"),
                            Jsonb(f.get("value_json")),
                            f.get("feasibility_status"),
                            f.get("compliance_flag"),
                            f.get("source_url"),
                            f.get("source_title"),
                            f.get("source_section"),
                            f.get("source_layer"),
                            f.get("retrieved_at"),
                            f.get("last_verified_at"),
                            f.get("confidence"),
                            f.get("data_status"),
                            f.get("sort_order", 0),
                        ),
                    )

    def get_analysis(self, analysis_id: str) -> Optional[dict[str, Any]]:
        return self._row(
            """
            select id::text, consumer_id, share_token, feasibility_status, result_json
              from property_analyses
             where id = %s::uuid
            """,
            (analysis_id,),
        )

    def get_analysis_by_share_token(self, token: str) -> Optional[dict[str, Any]]:
        return self._row(
            """
            select id::text, consumer_id, share_token, feasibility_status, result_json
              from property_analyses
             where share_token = %s
            """,
            (token,),
        )

    # ------------------------------------------------------------------
    # Metadata endpoints
    # ------------------------------------------------------------------
    def get_jurisdiction_rules(
        self, slug: str, zone: Optional[str], project_type: Optional[str]
    ) -> Optional[dict[str, Any]]:
        j = self._row(
            """
            select id::text, slug, name, state_code, county, coverage_status,
                   supported_project_types, source_update_date, last_source_refresh_at
              from jurisdictions where slug = %s
            """,
            (slug,),
        )
        if j is None:
            return None
        clauses = ["zr.jurisdiction_id = %s", "zr.is_current = true"]
        params: list[Any] = [j["id"]]
        if zone:
            clauses.append("upper(zr.zone_code) = upper(%s)")
            params.append(zone)
        if project_type:
            clauses.append("zr.project_type = %s")
            params.append(project_type)
        where = " and ".join(clauses)
        rules = self._rows(
            f"""
            select zr.id::text, zr.zone_code, zr.zone_name, zr.project_type,
                   zr.version, zr.effective_from
              from zoning_rules zr
             where {where}
             order by zr.zone_code, zr.project_type, zr.version desc
            """,
            tuple(params),
        )
        zones: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for r in rules:
            attrs = self._rows(
                """
                select field_name, value_json, value_numeric, unit,
                       state_baseline_id::text as state_baseline_id, compliance_flag,
                       source_url, source_title, source_section, source_layer,
                       retrieved_at, last_verified_at, confidence, data_status
                  from rule_attributes
                 where zoning_rule_id = %s
                 order by field_name
                """,
                (r["id"],),
            )
            zones.append(
                {
                    "zone_code": r["zone_code"],
                    "zone_name": r.get("zone_name"),
                    "project_type": r["project_type"],
                    "attributes": attrs,
                }
            )
        return {"jurisdiction": j, "zones": zones, "citations": citations}

    def get_changelog(self, jurisdiction: Optional[str], limit: int) -> list[dict[str, Any]]:
        if jurisdiction:
            return self._rows(
                """
                select ce.id::text, j.slug as jurisdiction_slug, ce.entry_type,
                       ce.title, ce.summary, ce.version, ce.source_url, ce.published_at
                  from changelog_entries ce
                  left join jurisdictions j on j.id = ce.jurisdiction_id
                 where j.slug = %s
                 order by ce.published_at desc
                 limit %s
                """,
                (jurisdiction, limit),
            )
        return self._rows(
            """
            select ce.id::text, j.slug as jurisdiction_slug, ce.entry_type,
                   ce.title, ce.summary, ce.version, ce.source_url, ce.published_at
              from changelog_entries ce
              left join jurisdictions j on j.id = ce.jurisdiction_id
             order by ce.published_at desc
             limit %s
            """,
            (limit,),
        )

    def get_source_freshness(self) -> list[dict[str, Any]]:
        return self._rows(
            """
            select coalesce(layer_name, name) as key, name,
                   case
                     when last_retrieved_at is null then 'unavailable'
                     when last_retrieved_at < now() - interval '90 days' then 'stale'
                     else 'current'
                   end as data_status,
                   last_retrieved_at as last_refreshed_at
              from source_registry
             where active = true
             order by name
            """
        )

    # ------------------------------------------------------------------
    # Metering
    # ------------------------------------------------------------------
    def record_usage_event(self, event: dict[str, Any]) -> None:
        self._execute(
            """
            insert into api_usage_events
              (consumer_id, provider, plan, endpoint, method, project_type,
               jurisdiction_slug, analysis_id, request_fingerprint, status_code,
               billable, billed, cache_hit, response_time_ms)
            values
              (%s, %s, %s, %s, %s, %s, %s, %s::uuid, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.get("consumer_id"),
                event.get("provider", "direct"),
                event.get("plan"),
                event.get("endpoint"),
                event.get("method"),
                event.get("project_type"),
                event.get("jurisdiction_slug"),
                event.get("analysis_id"),
                event.get("request_fingerprint"),
                event.get("status_code"),
                event.get("billable", False),
                event.get("billed", False),
                event.get("cache_hit", False),
                event.get("response_time_ms"),
            ),
        )

    def count_billable_this_month(self, consumer_id: str) -> int:
        row = self._row(
            """
            select count(*) as n
              from api_usage_events
             where consumer_id = %s
               and billable = true
               and created_at >= date_trunc('month', now() at time zone 'utc')
            """,
            (consumer_id,),
        )
        return int(row["n"]) if row else 0

    def count_requests_last_minute(self, consumer_id: str) -> int:
        row = self._row(
            """
            select count(*) as n
              from api_usage_events
             where consumer_id = %s
               and created_at > now() - interval '1 minute'
            """,
            (consumer_id,),
        )
        return int(row["n"]) if row else 0
