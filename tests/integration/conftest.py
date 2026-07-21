"""Integration-test harness: real PostGIS, real migrations, real FastAPI app.

Unlike ``services/tests`` (pure unit tests over in-memory fakes), this suite
exercises the whole request path against a live Postgres/PostGIS database:

  1. applies every ``supabase/migrations/*.sql`` in order (exactly like
     ``make migrate``) plus ``supabase/seed_baselines.sql``,
  2. seeds a tiny Los Angeles fixture (one parcel polygon, one R1 zoning
     district, two overlay features, one verified zoning_rule + attribute, and
     the California state baselines), and
  3. drives ``POST /v1/feasibility`` and friends through FastAPI's TestClient,
     with the network-dependent geocoder replaced by a deterministic static one.

Safety and CI behavior:

  - The suite is destructive (it resets the ``public`` schema on the target
    database), so it only runs against ``ADU_TEST_DB_URL`` (default: the
    isolated, ephemeral PostGIS in ``tests/integration/docker-compose.yml`` on
    port 54330). It NEVER touches ``SUPABASE_DB_URL``.
  - If psycopg is not installed, the ``psql`` client is missing, or the test
    database is unreachable, every test SKIPS with an explanatory message. So a
    plain ``pytest`` run in a CI job that has not stood up the database passes
    (as skips) instead of failing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_MIGRATIONS_DIR = _REPO_ROOT / "supabase" / "migrations"
_SEED_BASELINES = _REPO_ROOT / "supabase" / "seed_baselines.sql"

DEFAULT_TEST_DB_URL = "postgresql://postgres:postgres@localhost:54330/postgres"

# Points inside the seeded LA parcel and inside the seeded (planned) Oakland
# boundary. The static geocoder maps request addresses onto these. Several LA
# addresses map to the same in-parcel point so different tests can use distinct
# request fingerprints (and thus not collide on the 24h dedupe cache).
LA_LON, LA_LAT = -118.2500, 34.0500
LA_ADDRESS = "1234 S Main St, Los Angeles, CA 90015"
LA_ADDRESS_BILLABLE = "1 First St, Los Angeles, CA 90012"
LA_ADDRESS_DEDUPE = "777 Spring St, Los Angeles, CA 90014"
OAKLAND_ADDRESS = "500 14th St, Oakland, CA 94612"
OAKLAND_LON, OAKLAND_LAT = -122.2500, 37.8000

# Direct API key used by the tests. Any non-empty string works (it is
# sha256-hashed server-side into an opaque consumer id); no gateway needed.
TEST_API_KEY = "adu-atlas-integration-test-key"


def _resolve_dsn() -> str:
    return os.environ.get("ADU_TEST_DB_URL", DEFAULT_TEST_DB_URL)


def _psql_bin() -> str | None:
    return shutil.which("psql")


def _run_psql(dsn: str, *, file: Path | None = None, sql: str | None = None) -> None:
    """Apply a SQL file or string with ON_ERROR_STOP, raising on any error."""
    cmd = [_psql_bin() or "psql", dsn, "-v", "ON_ERROR_STOP=1", "-q"]
    if file is not None:
        cmd += ["-f", str(file)]
    if sql is not None:
        cmd += ["-c", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"psql failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        )


# Reset the target database to a clean slate, then create the Supabase auth
# roles the migrations' RLS policies reference. A vanilla PostGIS container does
# not have anon/authenticated/service_role, and 0002/0006 do
# ``create policy ... to service_role``, which errors without them.
_RESET_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role;
  END IF;
END
$$;
DROP SCHEMA IF EXISTS public CASCADE;
DROP SCHEMA IF EXISTS topology CASCADE;
CREATE SCHEMA public;
GRANT ALL ON SCHEMA public TO public;
"""


@pytest.fixture(scope="session")
def db_dsn() -> str:
    """The test database DSN, or SKIP the whole suite if it is unusable."""
    if _psql_bin() is None:
        pytest.skip(
            "psql client not found on PATH; integration tests apply migrations "
            "with psql (see tests/integration/docker-compose.yml)."
        )
    try:
        import psycopg
    except Exception:  # pragma: no cover - dependency guard
        pytest.skip("psycopg is not installed; install services/requirements.txt.")

    dsn = _resolve_dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("select 1")
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(
            "Test PostGIS is not reachable at "
            f"{dsn!r} ({exc}). Start it with: docker compose -f "
            "tests/integration/docker-compose.yml up -d"
        )
    return dsn


def _apply_migrations(dsn: str) -> None:
    _run_psql(dsn, sql=_RESET_SQL)
    files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError(f"no migrations found under {_MIGRATIONS_DIR}")
    for f in files:
        _run_psql(dsn, file=f)
    _run_psql(dsn, file=_SEED_BASELINES)


def _seed_la_fixture(dsn: str) -> dict[str, Any]:
    """Seed a minimal, self-consistent LA fixture; return the ids created."""
    import psycopg
    from psycopg.rows import dict_row

    zimas = "https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer"
    lamc = "https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-422835"
    fhsz = "https://data.ca.gov/dataset/fire-hazard-severity-zone-viewer1"

    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as conn:
        # LA -> production, with a boundary that contains the geocoded point.
        la = conn.execute(
            """
            update jurisdictions
               set coverage_status = 'production',
                   boundary = ST_Multi(ST_MakeEnvelope(-118.70, 33.90,
                                                       -118.10, 34.40, 4326)),
                   centroid = ST_SetSRID(ST_MakePoint(-118.25, 34.05), 4326),
                   source_update_date = current_date,
                   last_source_refresh_at = now()
             where slug = 'los_angeles'
            returning id::text
            """
        ).fetchone()
        la_id = la["id"]

        # Oakland stays 'planned' (seeded by seed_baselines) but gets a boundary
        # so the unsupported-coverage path can resolve a jurisdiction.
        conn.execute(
            """
            update jurisdictions
               set boundary = ST_Multi(ST_MakeEnvelope(-122.35, 37.70,
                                                       -122.15, 37.90, 4326))
             where slug = 'oakland'
            """
        )

        # One parcel polygon that contains the geocoded point.
        parcel = conn.execute(
            """
            insert into parcels
              (jurisdiction_id, apn, situs_address, normalized_address,
               geom, centroid, area_sqft, source_url, source_layer,
               confidence, data_status, retrieved_at, last_verified_at)
            values
              (%(jid)s::uuid, '5123-014-007', '1234 S Main St',
               '1234 S MAIN ST',
               ST_Multi(ST_MakeEnvelope(-118.2510, 34.0490,
                                        -118.2490, 34.0510, 4326)),
               ST_SetSRID(ST_MakePoint(-118.2500, 34.0500), 4326),
               6500, %(zimas)s, 'parcels', 'high', 'current', now(), now())
            returning id::text
            """,
            {"jid": la_id, "zimas": zimas},
        ).fetchone()

        # One R1 zoning district that covers the parcel.
        conn.execute(
            """
            insert into zoning_districts
              (jurisdiction_id, zone_code, zone_name, zone_category, geom,
               source_url, source_layer, confidence, data_status,
               retrieved_at, last_verified_at)
            values
              (%(jid)s::uuid, 'R1', 'One-Family Residential', 'residential',
               ST_Multi(ST_MakeEnvelope(-118.2600, 34.0400,
                                        -118.2400, 34.0600, 4326)),
               %(zimas)s, 'zoning', 'high', 'current', now(), now())
            """,
            {"jid": la_id, "zimas": zimas},
        )

        # Overlay features: a non-hazard HPOZ/historic hit that intersects the
        # parcel (exercises overlay provenance), and a fire layer placed away
        # from the parcel so it is 'available' but a no_hit for this parcel.
        # (Flood is never loaded, so it must report 'source_unavailable'.)
        conn.execute(
            """
            insert into overlay_features
              (jurisdiction_id, overlay_type, name, designation, geom,
               raw_feature_id, raw_value, source_url, source_layer,
               confidence, data_status, retrieved_at, last_verified_at)
            values
              (%(jid)s::uuid, 'historic', 'Example HPOZ', 'Contributing',
               ST_Multi(ST_MakeEnvelope(-118.2600, 34.0400,
                                        -118.2400, 34.0600, 4326)),
               'H-42', '{"district": "Example HPOZ"}'::jsonb,
               %(zimas)s, 'historic', 'high', 'current', now(), now()),
              (%(jid)s::uuid, 'fire', 'FHSZ', 'Moderate',
               ST_Multi(ST_MakeEnvelope(-118.3100, 34.0900,
                                        -118.3000, 34.1000, 4326)),
               'F-1', '{}'::jsonb,
               %(fhsz)s, 'fire', 'high', 'current', now(), now())
            """,
            {"jid": la_id, "zimas": zimas, "fhsz": fhsz},
        )

        # One verified local zoning rule for (LA, R1, detached_adu) with one
        # provenance-carrying attribute that matches the state baseline.
        rule = conn.execute(
            """
            insert into zoning_rules
              (jurisdiction_id, zone_code, zone_name, project_type, version,
               is_current, effective_from, review_status, compliance_flag,
               confidence, data_status, retrieved_at, last_verified_at)
            values
              (%(jid)s::uuid, 'R1', 'One-Family Residential', 'detached_adu',
               1, true, current_date, 'verified', 'matches_state_baseline',
               'high', 'current', now(), now())
            returning id::text
            """,
            {"jid": la_id},
        ).fetchone()

        conn.execute(
            """
            insert into rule_attributes
              (zoning_rule_id, field_name, value_json, value_numeric, unit,
               operator, compliance_flag, source_url, source_title,
               source_section, source_layer, retrieved_at, last_verified_at,
               confidence, data_status)
            values
              (%(rid)s::uuid, 'max_height_detached_standard_ft', '16'::jsonb,
               16, 'ft', 'floor', 'matches_state_baseline', %(lamc)s,
               'LAMC 12.22 A.33', 'LAMC 12.22 A.33', 'lamc', now(), now(),
               'high', 'current')
            """,
            {"rid": rule["id"], "lamc": lamc},
        )

        # One active source so GET /v1/health reports freshness.
        conn.execute(
            """
            insert into source_registry
              (jurisdiction_id, source_type, provider, name, url, layer_name,
               active, last_retrieved_at)
            values
              (%(jid)s::uuid, 'gis_zoning', 'arcgis', 'LA ZIMAS zoning',
               %(zimas)s, 'zoning', true, now())
            """,
            {"jid": la_id, "zimas": zimas},
        )

        # One changelog entry so GET /v1/changelog returns a mapped row.
        conn.execute(
            """
            insert into changelog_entries
              (jurisdiction_id, entry_type, title, summary, published_at)
            values
              (%(jid)s::uuid, 'coverage', 'Los Angeles is now production',
               'LA City coverage promoted to production.', now())
            """,
            {"jid": la_id},
        )

    return {"la_id": la_id, "parcel_id": parcel["id"], "rule_id": rule["id"]}


@pytest.fixture(scope="session")
def seeded_db(db_dsn: str) -> dict[str, Any]:
    """Apply migrations + baselines, then seed the LA fixture. Session-scoped."""
    _apply_migrations(db_dsn)
    return _seed_la_fixture(db_dsn)


@pytest.fixture(scope="session")
def client(db_dsn: str, seeded_db: dict[str, Any]):
    """A FastAPI TestClient wired to the test DB and a static geocoder."""
    from fastapi.testclient import TestClient

    from services.api import main as api_main
    from services.api import settings as api_settings
    from services.core.db import PostgresRepository
    from services.core.geocode import StaticGeocoder
    from services.core.repository import GeoPoint

    # Make the health endpoint's `settings.has_db` true against the test DB
    # without ever pointing production settings at it elsewhere.
    os.environ["SUPABASE_DB_URL"] = db_dsn
    api_settings.get_settings.cache_clear()

    repo = PostgresRepository(db_dsn)
    la_point = GeoPoint(lon=LA_LON, lat=LA_LAT)
    geocoder = StaticGeocoder(
        {
            LA_ADDRESS: la_point,
            LA_ADDRESS_BILLABLE: la_point,
            LA_ADDRESS_DEDUPE: la_point,
            OAKLAND_ADDRESS: GeoPoint(lon=OAKLAND_LON, lat=OAKLAND_LAT),
        }
    )

    # main.py calls get_repository()/get_geocoder() directly (not via Depends),
    # so we rebind the names in the module namespace.
    original_repo = api_main.get_repository
    original_geo = api_main.get_geocoder
    api_main.get_repository = lambda: repo
    api_main.get_geocoder = lambda: geocoder

    test_client = TestClient(api_main.app)
    try:
        yield test_client
    finally:
        api_main.get_repository = original_repo
        api_main.get_geocoder = original_geo
        repo.close()


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Direct-key credentials (no RapidAPI gateway required)."""
    return {"X-API-Key": TEST_API_KEY}


@pytest.fixture()
def addresses() -> dict[str, str]:
    """Named request addresses the static geocoder knows how to resolve."""
    return {
        "la": LA_ADDRESS,
        "la_billable": LA_ADDRESS_BILLABLE,
        "la_dedupe": LA_ADDRESS_DEDUPE,
        "oakland": OAKLAND_ADDRESS,
    }
