"""On-demand resolver tests (mocked fetcher + in-memory DB seam, no network/DB).

These exercise the ingestion-lite request-path resolver: the parallel fetch, the
idempotent caching SQL (ON CONFLICT for parcels, NOT EXISTS dedup for zoning /
overlays), the ONDEMAND_ENABLED gate, the Los Angeles v1 scope gate, and honest
degradation when a source fails.
"""

from __future__ import annotations

import math

from services.core.ondemand import (
    JURISDICTION_LAYERS,
    FLOOD_LAYER,
    PARCEL_LAYER,
    ZONING_LAYER,
    JurisdictionLayers,
    LayerConfig,
    OnDemandResolver,
    arcgis_query_params,
    bbox_envelope,
    feature_key,
    get_jurisdiction_layers,
)
from services.core.repository import GeoPoint


LA_POINT = GeoPoint(lon=-118.27, lat=34.03)


# ---- Fakes ----------------------------------------------------------------
class FakeDB:
    """Records execute() calls and returns canned rows for the provenance SQL."""

    def __init__(self, slug: str = "los_angeles"):
        self.slug = slug
        self.executed: list[str] = []
        self.queries: list[str] = []
        self._reg = 0

    def _norm(self, sql: str) -> str:
        return " ".join(sql.split())

    def rows(self, sql, params=()):
        self.queries.append(self._norm(sql))
        return []

    def row(self, sql, params=()):
        s = self._norm(sql)
        self.queries.append(s)
        if "select slug from jurisdictions" in s:
            return {"slug": self.slug} if self.slug is not None else None
        if "insert into source_registry" in s:
            self._reg += 1
            return {"id": f"00000000-0000-0000-0000-0000000000{self._reg:02d}"}
        if "select id::text from source_registry" in s:
            return None
        if "insert into source_snapshots" in s:
            return {"id": "00000000-0000-0000-0000-0000000000ff"}
        if "coalesce(max(version)" in s:
            return {"v": 1}
        if "select id::text from source_snapshots" in s:
            return None
        return None

    def execute(self, sql, params=()):
        self.executed.append(self._norm(sql))


def make_fetch(features_by_fragment):
    calls: list[str] = []

    def fetch(url, params, *, verify, timeout):
        calls.append(url)
        for frag, feats in features_by_fragment.items():
            if frag in url:
                return 200, b'{"features":[]}', feats
        return 200, b'{"features":[]}', []

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def _parcel_feature():
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
        "properties": {"APN": "5123-014-007", "SitusFullAddress": "123 MAIN ST"},
    }


def _zoning_feature():
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]},
        "properties": {"ZONE_CLASS": "R1", "ZONE_CMPLT": "R1-1"},
    }


def _flood_feature(zone="X"):
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 3], [3, 3], [3, 0], [0, 0]]]},
        "properties": {"FLD_ZONE": zone, "OBJECTID": 7},
    }


def _all_features(flood_zone="X"):
    return {
        "LACounty_Parcel": [_parcel_feature()],
        "zma/zimas": [_zoning_feature()],
        "NFHL": [_flood_feature(flood_zone)],
    }


# ---- Pure helpers ---------------------------------------------------------
def test_bbox_envelope_is_centered_and_sized():
    xmin, ymin, xmax, ymax = bbox_envelope(LA_POINT, 120.0)
    assert xmin < LA_POINT.lon < xmax
    assert ymin < LA_POINT.lat < ymax
    assert math.isclose((ymax - ymin) / 2.0, 120.0 / 111320.0, rel_tol=1e-9)


def test_arcgis_query_params_shape():
    p = arcgis_query_params(LA_POINT, 120.0)
    assert p["f"] == "geojson"
    assert p["inSR"] == "4326" and p["outSR"] == "4326"
    assert p["geometryType"] == "esriGeometryEnvelope"


def test_feature_key_is_stable_and_geometry_sensitive():
    f = _parcel_feature()
    assert feature_key(f, "5123-014-007") == feature_key(f, "5123-014-007")
    other = _parcel_feature()
    other["geometry"]["coordinates"][0][0] = [9, 9]
    assert feature_key(f, "x") != feature_key(other, "x")


def test_zimas_uses_verify_false():
    assert ZONING_LAYER.verify_ssl is False
    assert PARCEL_LAYER.verify_ssl is True and FLOOD_LAYER.verify_ssl is True


# ---- Resolver behavior ----------------------------------------------------
def test_disabled_resolver_is_a_noop():
    db = FakeDB()
    fetch = make_fetch(_all_features())
    r = OnDemandResolver(db, enabled=False, fetch=fetch)
    out = r.hydrate_point("jid-1", LA_POINT)
    assert out["fetched"] is False
    assert fetch.calls == []
    assert db.executed == []


def test_out_of_scope_jurisdiction_is_skipped():
    db = FakeDB(slug="san_diego")
    fetch = make_fetch(_all_features())
    r = OnDemandResolver(db, enabled=True, fetch=fetch)
    out = r.hydrate_point("jid-1", LA_POINT)
    assert out["fetched"] is False
    assert fetch.calls == []


def test_hydrate_point_fetches_all_three_in_parallel_and_caches():
    db = FakeDB(slug="los_angeles")
    fetch = make_fetch(_all_features())
    r = OnDemandResolver(db, enabled=True, fetch=fetch)
    out = r.hydrate_point("00000000-0000-0000-0000-0000000000aa", LA_POINT)

    # All three official layers were queried.
    assert len(fetch.calls) == 3
    assert any("LACounty_Parcel" in u for u in fetch.calls)
    assert any("zma/zimas" in u for u in fetch.calls)
    assert any("NFHL" in u for u in fetch.calls)

    # One row cached per layer.
    assert out["parcel"] == 1 and out["zoning"] == 1 and out["flood"] == 1

    # Idempotent caching SQL: ON CONFLICT for parcels, NOT EXISTS dedup elsewhere.
    parcel_sql = next(s for s in db.executed if "insert into parcels" in s)
    assert "on conflict (jurisdiction_id, apn) do nothing" in parcel_sql
    assert "st_multi(st_makevalid(st_setsrid(st_geomfromgeojson" in parcel_sql.lower()

    zoning_sql = next(s for s in db.executed if "insert into zoning_districts" in s)
    assert "not exists" in zoning_sql and "ondemand_key" in zoning_sql

    overlay_sql = next(s for s in db.executed if "insert into overlay_features" in s)
    assert "not exists" in overlay_sql and "ondemand_key" in overlay_sql
    # Generic overlay geom is not forced to MultiPolygon.
    assert "st_multi(" not in overlay_sql.lower()


def test_memo_prevents_refetch_within_ttl():
    db = FakeDB()
    fetch = make_fetch(_all_features())
    r = OnDemandResolver(db, enabled=True, fetch=fetch)
    r.hydrate_point("jid-1", LA_POINT)
    # Second call for the same point should be memoized (no new fetches).
    r.hydrate_point("jid-1", LA_POINT)
    assert len(fetch.calls) == 3
    # The zoning safety net is also memoized after hydrate_point.
    assert r.hydrate_zoning("jid-1", LA_POINT) == 0


def test_failed_fetch_degrades_without_caching():
    db = FakeDB()

    def boom(url, params, *, verify, timeout):
        raise RuntimeError("network down")

    r = OnDemandResolver(db, enabled=True, fetch=boom)
    out = r.hydrate_point("jid-1", LA_POINT)
    # It attempted (fetched=True) but cached nothing and did not raise.
    assert out["fetched"] is True
    assert out["parcel"] == 0 and out["zoning"] == 0 and out["flood"] == 0
    assert not any("insert into parcels" in s for s in db.executed)


def test_empty_feature_set_is_a_clean_no_hit():
    db = FakeDB()
    fetch = make_fetch({})  # every layer returns zero features
    r = OnDemandResolver(db, enabled=True, fetch=fetch)
    out = r.hydrate_point("jid-1", LA_POINT)
    assert out["fetched"] is True
    assert out["parcel"] == 0 and out["zoning"] == 0 and out["flood"] == 0


# ---- Multi-jurisdiction layer resolution ----------------------------------
def test_la_layers_are_registered_and_unknown_city_is_unconfigured():
    la = get_jurisdiction_layers("los_angeles")
    assert la is not None
    assert la.parcel is PARCEL_LAYER
    assert la.zoning is ZONING_LAYER
    assert FLOOD_LAYER in la.overlays
    # An un-onboarded city has no configured layers (coverage honesty).
    assert get_jurisdiction_layers("san_diego") is None
    assert get_jurisdiction_layers(None) is None


# A second, fictional jurisdiction with DIFFERENT services + attribute names,
# proving a city is added by config alone (distinct URLs + field mappings), with
# zero change to the resolver logic.
TESTVILLE = JurisdictionLayers(
    slug="testville",
    parcel=LayerConfig(
        name="Testville parcels",
        query_url="https://gis.testville.example/parcels/MapServer/0/query",
        provider="arcgis", source_type="gis_parcel", layer_name="tv_parcels/0",
        apn_fields=("PARCEL_NO",),           # different from LA's APN/AIN
        situs_fields=("ADDR",),
    ),
    zoning=LayerConfig(
        name="Testville zoning",
        query_url="https://gis.testville.example/zoning/MapServer/3/query",
        provider="arcgis", source_type="gis_zoning", layer_name="tv_zoning/3",
        zone_code_fields=("ZONING_CODE",),   # different from LA's ZONE_CLASS
        zone_name_fields=("ZONING_DESC",),
    ),
    overlays=(FLOOD_LAYER,),                  # federal flood reused
)


def _register_testville():
    JURISDICTION_LAYERS["testville"] = TESTVILLE


def _unregister_testville():
    JURISDICTION_LAYERS.pop("testville", None)


def test_second_city_hydrates_from_its_own_layers_and_field_names():
    _register_testville()
    try:
        db = FakeDB(slug="testville")
        fetch = make_fetch({
            "gis.testville.example/parcels": [{
                "type": "Feature",
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
                "properties": {"PARCEL_NO": "TV-001", "ADDR": "1 TEST WAY"},
            }],
            "gis.testville.example/zoning": [{
                "type": "Feature",
                "geometry": {"type": "Polygon",
                             "coordinates": [[[0, 0], [0, 2], [2, 2], [2, 0], [0, 0]]]},
                "properties": {"ZONING_CODE": "RS-1", "ZONING_DESC": "Single Family"},
            }],
            "NFHL": [_flood_feature("X")],
        })
        r = OnDemandResolver(db, enabled=True, fetch=fetch)
        out = r.hydrate_point("jid-tv", GeoPoint(lon=-117.0, lat=33.0))

        # Queried Testville's own services, NOT the LA ones.
        assert any("gis.testville.example/parcels" in u for u in fetch.calls)
        assert any("gis.testville.example/zoning" in u for u in fetch.calls)
        assert not any("LACounty_Parcel" in u for u in fetch.calls)
        assert not any("zimas" in u for u in fetch.calls)

        # Rows cached => the per-city field-name overrides extracted values.
        assert out["parcel"] == 1 and out["zoning"] == 1 and out["flood"] == 1
        parcel_sql = next(s for s in db.executed if "insert into parcels" in s)
        assert "on conflict (jurisdiction_id, apn) do nothing" in parcel_sql
    finally:
        _unregister_testville()


def test_unconfigured_jurisdiction_fetches_nothing():
    db = FakeDB(slug="nowhere_ca")  # not in the registry
    fetch = make_fetch(_all_features())
    r = OnDemandResolver(db, enabled=True, fetch=fetch)
    out = r.hydrate_point("jid-x", LA_POINT)
    assert out["fetched"] is False
    assert fetch.calls == []
    assert r.hydrate_zoning("jid-x", LA_POINT) == 0
    assert r.hydrate_overlays("jid-x", LA_POINT) == 0
