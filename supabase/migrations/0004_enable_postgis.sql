-- ADU Atlas pivot: enable PostGIS (and related) for spatial parcels, zoning
-- districts, and overlays. Safe/idempotent; the full 16-table schema follows in
-- 0005. Supabase provisions these extensions into the `extensions` schema.
create extension if not exists postgis;
create extension if not exists postgis_topology;
create extension if not exists pg_trgm;      -- address / text fuzzy lookup
create extension if not exists "uuid-ossp";
