# San Jose - Data Sources and ADU Rules

Status: verified (parcel + zoning envelope queries returned features for a real
San Jose residential address on 2026-07-21).

Jurisdiction slug (proposed): `san_jose`

Test point used for all curl checks below:
- Address: 1401 Bird Ave, San Jose, CA 95125 (Willow Glen, single-family)
- lon/lat (WGS84): `-121.890869924534, 37.306841933604`
- Envelope (~120 m, `xmin,ymin,xmax,ymax`): `-121.89223,37.30576,-121.88951,37.30792`

All three primary layers live on the City of San Jose's official ArcGIS Server
(`geo.sanjoseca.gov`). It is fast (<1s per envelope query), returns clean
GeoJSON with `inSR/outSR=4326`, and valid SSL (no `verify=False` needed, unlike
LA ZIMAS). This is the authoritative City GIS - preferred over any third-party
aggregator.

---

## 1. Parcels (APN + geometry)

- Service: `PLN/PLN_Geocortex_Public_PRD` MapServer, layer id **49** ("Parcels")
- Geometry: `esriGeometryPolygon`
- APN field: **`APN`** (esriFieldTypeString). Also `PARCELID`, `LOTNUM`.
- NOTE: this layer has NO situs/address field. `situs_address` must be left
  null on cache (nullable in `parcels`), or joined from the county service (see
  section 4). APN + geometry (the must-haves for the on-demand resolver) are
  both present.

Exact /query URL:
```
https://geo.sanjoseca.gov/server/rest/services/PLN/PLN_Geocortex_Public_PRD/MapServer/49/query
```

Verified curl (returned **77** parcel features, polygon geometry):
```
curl -s "https://geo.sanjoseca.gov/server/rest/services/PLN/PLN_Geocortex_Public_PRD/MapServer/49/query?geometry=-121.89223,37.30576,-121.88951,37.30792&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"
```
Sample properties: `{"OBJECTID":13856,"PARCELID":"83893","APN":"42902075","LOTNUM":null,"ENTERPRISEID":"DPW-PARC-0000083893"}`

Resolver note: `_prop(props, "APN", ...)` already matches this field. No situs,
so `_prop(props, "SitusFullAddress", ...)` returns None -> stored as null.

---

## 2. Zoning (zone_code polygons)

- Service: `PLN/PLN_Geocortex_Public_PRD` MapServer, layer id **128**
  ("Zoning District")
- Geometry: `esriGeometryPolygon`
- Zone-code field: **`ZONING`** (full zone code, e.g. `R-1-8`) and
  **`ZONINGABBREV`** (same value in the samples). Use `ZONING` as `zone_code`.
- Other fields: `REZONINGFILE`, `PDUSE`, `PDDENSITY`, `DEVELOPEDASPD`,
  `APPROVALDATE`, `FACILITYID`.
- (Layer 269 "Zoning" is a group layer with no geometry - do not use. Layer 129
  "Zonings (Since 2000)" is historical.)

Exact /query URL:
```
https://geo.sanjoseca.gov/server/rest/services/PLN/PLN_Geocortex_Public_PRD/MapServer/128/query
```

Verified curl (returned **11** zoning polygons around the test point):
```
curl -s "https://geo.sanjoseca.gov/server/rest/services/PLN/PLN_Geocortex_Public_PRD/MapServer/128/query?geometry=-121.89223,37.30576,-121.88951,37.30792&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"
```
Zone codes returned: `R-1-8` (single-family, the parcel's zone), `CN`, `A(PD)`.

Resolver note: `_cache_zoning` currently reads `ZONE_CLASS/ZONE_CMPLT` (LA
fields). For San Jose it must read `ZONING` / `ZONINGABBREV`. This is a
layer-config change when wiring San Jose (the on-demand resolver is LA-scoped
today).

---

## 3. City boundary polygon (point -> jurisdiction)

- Service: `OPN/OPN_OpenDataService` MapServer, layer id **372** ("Incorporated")
- Geometry: `esriGeometryPolygon` (returns MultiPolygon in GeoJSON)
- Where filter to select San Jose: **`INCORPORATED='San Jose'`**
- Verified: 1 feature, `INCORPAREA=180.73` sq mi (matches San Jose's ~180 sq mi).

Exact /query URL + filter:
```
https://geo.sanjoseca.gov/server/rest/services/OPN/OPN_OpenDataService/MapServer/372/query?where=INCORPORATED='San Jose'&outFields=INCORPORATED&returnGeometry=true&outSR=4326&f=geojson
```

Do NOT use PLN layer 329 ("City Boundary"): it is an inverse mask polygon
(single feature `NAME='Not San Jose', INSIDESJ='No'`), not the city limits.

---

## 4. Optional situs source (Santa Clara County parcels)

If a situs/address string is wanted on the parcel row, the county parcel
FeatureServer has `apn` + `situs_hous`/`situs_stre`/`situs_city` + geometry and
also responds fast:
```
https://services8.arcgis.com/fpjs8A5Vtkshblnd/arcgis/rest/services/Santa_Clara_County_Parcels/FeatureServer/0/query
```
CAUTION: `fpjs8A5Vtkshblnd` is a third-party ArcGIS Online org that hosts parcel
layers for many unrelated CA cities (Apple Valley, Arcadia, ...), i.e. a data
aggregator, not the official County GIS. Treat provenance accordingly; prefer
the City layer 49 as the authoritative parcel source and use this only to
enrich situs if needed. (The official County server `webgis.sccgov.org` was
tested and timed out repeatedly - not viable on the deterministic request path.)

---

## 5. ADU / JADU rules

Ordinance: **San Jose Municipal Code Title 20 (Zoning), Chapter 20.30, Part 4.5
- Accessory Dwelling Units; principal section SJMC 20.30.460** ("Accessory
dwelling units - single-family dwelling lot"), with JADU / definitions in Title
20 Part 2.75 (SJMC 20.80). Keyed by `zone_code` (ADUs permitted in R-1, R-2,
R-M, and PD districts that allow single-family uses).

Citation URLs:
- Municode: https://library.municode.com/ca/san_jose/codes/code_of_ordinances?nodeId=TIT20ZO_CH20.30REZODI
- City ADU program / ordinance updates: https://www.sanjoseca.gov/business/development-services-permit-center/accessory-dwelling-units-adus/adu-ordinance-updates

Key rule field values (local value + one-line source note; CA state baseline
used where the local value is unclear, per PRODUCT_SPEC baselines):

| field | value | source note |
|---|---|---|
| `max_height_detached_standard_ft` | 18 | San Jose: single-story detached ADU max 18 ft; two-story detached up to 24 ft. 18 ft aligns with the AB 2221 near-transit floor. Use 18 as the standard-detached cap; 24 as the two-story allowance. |
| `side_rear_setback_min_ft` | 4 | CA state baseline (AB 2221): city must allow 4 ft side/rear. San Jose grants a state-mandated 4 ft; some City guidance allows 3 ft for a single-story detached ADU (less restrictive) and requires 4 ft for two-story / >40% lot coverage. Value ambiguous locally -> default to state baseline 4 ft. |
| `owner_occupancy_required_adu` | false | San Jose does not require owner-occupancy for ADUs; consistent with Gov Code 66315 (AB 976 made no-owner-occupancy permanent from 2025). |
| `owner_occupancy_required_jadu` | true | Owner-occupancy of the primary residence required for a JADU (govt agencies / land trusts / qualified housing orgs exempt); consistent with Gov 66333(b). |
| `jadu_allowed` | true | JADU permitted, 1 per single-family lot, created within the walls of the existing dwelling (SJMC / Gov 66333). |
| `parking_required` | false | 0 spaces required when within 1/2 mi walking distance of transit and other SB 897 exemptions (VTA bus, Light Rail, Caltrain corridors). Broadly exempt; default false per SB 897. Outside an exemption, up to 1 space may apply - flag as conditional at rule-merge time. |
| `permit_review_days` | 60 | Ministerial 60-day shot clock with auto-approval if missed (AB 2221 / SB 897). |
| `max_size_sqft_general_cap` | 1200 | San Jose: 1,200 sq ft max on lots >= 9,000 sq ft; 1,000 sq ft on lots < 9,000 sq ft; 800 sq ft for duplex/multifamily ADUs. General cap = 1,200. |
| `fire_sprinkler_trigger` | false | ADU not required to have sprinklers if the primary dwelling is not (SB 897). San Jose local note: if ADU > 500 sq ft AND combined floor area with main unit exceeds 3,600 sq ft, whole-property sprinklers can be triggered - condition, not a blanket ADU requirement. |

State-baseline reconciliation: none of the above are MORE restrictive than the
CA baselines in PRODUCT_SPEC (heights >= floors, setback == 4 ft ceiling,
review <= 60 days, no owner-occupancy, sprinklers off, size cap up to 1,200).
Where local specifics were unclear (side/rear setback, parking outside
exemptions) the CA state baseline was used rather than inventing a local value.

---

## 6. Wiring checklist (copy-paste targets)

- Parcel LayerConfig -> query_url layer 49 above; APN field `APN`; no situs.
- Zoning LayerConfig -> query_url layer 128 above; zone_code from `ZONING`
  (name from `ZONINGABBREV`); update `_cache_zoning` `_prop(...)` to include
  `ZONING`/`ZONINGABBREV`.
- Boundary -> OPN layer 372, `where=INCORPORATED='San Jose'`.
- verify_ssl: true for all `geo.sanjoseca.gov` layers; default timeout is fine.
- Seed zoning_rules keyed by zone_code (R-1, R-1-8, R-2, R-M, PD single-family)
  with the section-5 values; attach provenance (SJMC 20.30.460 URL) per field.
- Flip `coverage_status='production'` only after rules are ingested + verified.

Sources:
- City parcel/zoning/boundary services: geo.sanjoseca.gov ArcGIS (verified via curl, 2026-07-21)
- SJMC 20.30.460 / Chapter 20.30: https://library.municode.com/ca/san_jose/codes/code_of_ordinances?nodeId=TIT20ZO_CH20.30REZODI
- City ADU program: https://www.sanjoseca.gov/business/development-services-permit-center/accessory-dwelling-units-adus
