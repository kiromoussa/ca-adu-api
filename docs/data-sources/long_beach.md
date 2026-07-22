# Long Beach - Data Sources and ADU Rules

Status: RESEARCHED + LIVE-VERIFIED (parcel, zoning, and city-boundary envelope
queries all returned real features around a real residential address on
2026-07-21). Ready for wiring; flip `coverage_status='production'` only after
rules are ingested into the DB.

Jurisdiction slug (proposed): `long_beach`

Verification address: 356 Coronado Ave, Long Beach, CA 90814 (Belmont Heights,
residential). Census-geocoded to lon=-118.153426425736, lat=33.770213571348.

Envelope used in all curl tests below (~120 m box, `xmin,ymin,xmax,ymax`, WGS84):

    -118.154706,33.769134,-118.152146,33.771294

All services accept the proven envelope shape:
`/query?geometry=xmin,ymin,xmax,ymax&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&f=geojson`.

Long Beach is in LA County. Parcels come from the LA County Assessor public GIS
(has APN + a single-field situs, preferred), with the City's own Assessor_Parcels
layer as an APN-only fallback. Zoning and the city boundary come from the official
City of Long Beach ArcGIS Online org (`services6.arcgis.com/yCArG7wGXGyWLqav`,
"City of Long Beach, CA", owner `arcgis_clb`). All endpoints returned clean
GeoJSON with valid SSL (no `verify=False` needed, unlike LA ZIMAS) and responded
in under ~1s.

---

## 1. Parcels (APN + situs + geometry) -- VERIFIED

Primary: LA County Assessor public parcel cache (county serves all of Long Beach;
has both APN and a single composed situs string, matching the LA-style
`SitusFullAddress` field the resolver already knows).

- Layer base: `https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0`
- Layer name / id: `LACounty_Parcel` / **0**
- Query URL:
  `https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query`
- APN field: **`APN`** (dashed, e.g. `7257-012-017`). Also **`AIN`** (10-digit,
  no dashes, e.g. `7257012017`) - the county's canonical id and the format the
  City parcel layer + `LACO_URL` use.
- Situs field: **`SitusFullAddress`** (single composed string, e.g.
  `387 OBISPO AVE LONG BEACH CA 90814`). Also split fields `SitusHouseNo`,
  `SitusStreet`, `SitusCity`, `SitusZIP`, and `SitusCity`/`TaxRateCity`
  ("LONG BEACH" for city-limits filtering). Rich extras: `UseType`,
  `UseDescription`, `Units1`, `YearBuilt1`, `SQFTmain1`.
- Geometry: `esriGeometryPolygon` (returned as GeoJSON Polygon).

Live test (HTTP 200, 146 features):

    curl -s "https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query?geometry=-118.154706,33.769134,-118.152146,33.771294&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Sample returned features (APN | SitusFullAddress | UseType):
- 7257-012-017 | 387 OBISPO AVE LONG BEACH CA 90814 | Residential
- (146 parcels intersected the box; polygon geometry confirmed via `f=geojson`)

Resolver note: `_prop(props, "APN", ...)` matches `APN`; `_prop(props,
"SitusFullAddress", ...)` matches `SitusFullAddress` (same field name as the LA
City parcel layer), so situs is populated with no resolver change.

Fallback (City of Long Beach parcels, APN only, no situs):

- Query URL:
  `https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Assessor_Parcels/FeatureServer/0/query`
- APN field: **`APN`** (10-digit no-dash string, e.g. `7257014049`); also `APNI`
  (integer), `STACKEDAPN`, `MUNICIPALITY` (`CLB`), and `LACO_URL` (a
  ready-made assessor-detail link). NO situs/address field on this layer.
- Live test (HTTP 200, 151 features):

      curl -s "https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Assessor_Parcels/FeatureServer/0/query?geometry=-118.154706,33.769134,-118.152146,33.771294&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Prefer the LA County layer for the on-demand resolver (APN + situs both present).
Use the City layer only if the County service is ever unavailable; join situs from
County by AIN if needed.

---

## 2. Zoning (zone_code polygons) -- VERIFIED

Official City of Long Beach zoning (Title 21 zoning districts).

- Layer base: `https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Zoning/FeatureServer/0`
- Layer name / id: `Zoning` / **0**
- Query URL:
  `https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Zoning/FeatureServer/0/query`
- Zone code field: **`ZONING_SYMBOL`** (e.g. `R-2-A`, `CNR`). Other fields:
  `GENERAL_CLASS` / `SPECIFIC_CLASS` (numeric class codes), `OVERLAY`,
  `PD_SUBAREA`, `SP_DISTRICT`, `ORD_NO`, `RECORD_DATE`.
- Geometry: `esriGeometryPolygon`.

Live test (HTTP 200, 2 features around the point):

    curl -s "https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Zoning/FeatureServer/0/query?geometry=-118.154706,33.769134,-118.152146,33.771294&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Zone codes returned: `R-2-A` (the parcel's zone, two-family residential) and
`CNR` (neighborhood commercial). Confirms the zone-code field name and polygon
geometry.

Resolver note: the on-demand resolver's `_cache_zoning` reads LA fields
(`ZONE_CLASS`/`ZONE_CMPLT`). For Long Beach it must read **`ZONING_SYMBOL`**.
This is a layer-config change at wiring time.

Useful ADU overlay/conditional layers in the same org (for later overlay ingest;
several ADU rules key off these):
- Parking Impacted Areas: `.../Parking_Impacted_Areas/FeatureServer/0`
- Parking Exempt Areas: `.../Parking_Exempt_Areas/FeatureServer/0`
- Coastal Zone: `.../Coastal_Zone/FeatureServer/0`
- Historic Districts: `.../HistoricDistricts/FeatureServer/0`
- Special Setback Areas: `.../Special_Setback_Areas/FeatureServer/0`
(all under `https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/`)

---

## 3. City boundary polygon (point -> jurisdiction) -- VERIFIED

Official City of Long Beach city-limits polygon.

- Query URL:
  `https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/City_of_Long_Beach_City_Boundary_Official/FeatureServer/0/query`
- Layer name / id: `City Boundary Official` / **0**
- City name field: **`CITYNAME`** (value `LONG BEACH`); also `CITYCODE` = `CLB`.
- Where filter: **`CITYNAME='LONG BEACH'`** (layer holds a single feature, so
  `where=1=1` also works).

Live test (HTTP 200, 1 feature, single Polygon, `Shape__Area` ~3.08e8 sq m
~= 40 sq mi land area, consistent with Long Beach):

    curl -s "https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/City_of_Long_Beach_City_Boundary_Official/FeatureServer/0/query?where=CITYNAME%3D%27LONG%20BEACH%27&outFields=CITYNAME,CITYCODE&returnGeometry=true&outSR=4326&f=geojson"

(There is also a `City_Of_Long_Beach_City_Boundary` layer in the org; prefer the
`..._Official` layer above.)

---

## 4. ADU / JADU ordinance and rule values

Citation and current status: The legacy Long Beach zoning ADU section was
**LBMC Title 21, Section 21.51.276** ("Accessory Dwelling Units"). Per the City's
current ADU program page, **that section no longer applies and the City is
administering California state ADU law directly** (Gov. Code sections 66310 to
66342, formerly 65852.2 / 65852.22) until a new local ordinance is adopted. The
task brief cited "21.52.206"; the operative Long Beach zoning section is
**21.51.276** (now superseded), so the rule values below are anchored primarily on
current state law plus the City's operative planning/building documents. Flag on
ingest that the local codified section is in transition.

- Source URLs:
  - City ADU program (states "applies state ADU law directly; LBMC 21.51.276 no
    longer applies"): `https://www.longbeach.gov/lbcd/adus/`
  - City Building & Safety FAQ-001, "Accessory Dwelling Units and Two-Unit
    Residential Developments (SB 9)" (Eff 07-20-2023, Rev 8-21-24), official City
    PDF downloaded and parsed during verification:
    `https://www.longbeach.gov/globalassets/lbcd/media-library/documents/planning/adus-and-sb9/faq-001`
  - City Planning "Summary of Accessory Dwelling Unit Zoning Regulations"
    (referenced by the ADU page; the Feb-2025 globalassets URL returned 404 on
    2026-07-21 - re-pull from the ADU page link at ingest time):
    `https://www.longbeach.gov/lbcd/adus/`
  - CA state ADU law (Gov. Code 66310-66342): the substantive baseline the City
    applies directly.

Rule field values (local value + one-line source note; CA state baseline used and
flagged where the local value is unclear or the City defers to state law):

| field | value | source note |
|---|---|---|
| `max_height_detached_standard_ft` | 16 | State floor the City applies (Gov. Code 66321(a)(1)(A)): detached ADU allowed to at least 16 ft. City summary: 16 ft base, +2 ft to match roof pitch; increases to **18 ft** when within 1/2 mi of transit, on a multifamily lot, or built with a new primary dwelling (Gov. Code 66321(a)(1)(B)-(C)). Store 16 as the standard detached cap; treat 18 as the near-transit/multifamily allowance. |
| `side_rear_setback_min_ft` | 4 | Gov. Code 66321(a)(1)(D): city may require no more than 4 ft side/rear. City FAQ-001 A2 confirms "Zoning Regulations require a four-foot side and rear yard setback." 0 ft for conversions of existing structures / existing-footprint replacements (Gov. Code 66323). |
| `owner_occupancy_required_adu` | false | Not required for ADUs (Gov. Code 66317; AB 976 made the no-owner-occupancy rule permanent from 2025). City ADU page: owner-occupancy not required for a standard ADU. |
| `owner_occupancy_required_jadu` | true | Owner must occupy the primary dwelling or the JADU (Gov. Code 66333(b)). City nuance (AB 1154, eff 1/1/2026, reflected on the City ADU page): owner-occupancy required only where the JADU shares a bathroom with the primary dwelling. Store true; carry the shared-bathroom conditional as a note. |
| `jadu_allowed` | true | Gov. Code 66333: one JADU per single-family lot, <=500 sq ft, created within the existing single-family dwelling or an attached garage; efficiency kitchen required; may not be sold separately. City page: 1 ADU + 1 JADU per lot allowed. |
| `parking_required` | false | Gov. Code 66314: no parking may be required when the ADU is within 1/2 mi walking distance of transit, is a conversion of existing space, is in a historic district, or other state exemptions. Outside an exemption, up to 1 space per ADU (or per bedroom, whichever is less) may apply - treat as false with a conditional flag keyed to the Parking Impacted / Parking Exempt overlay layers in section 2. JADU: no parking (Gov. Code 66333). |
| `permit_review_days` | 60 | Ministerial 60-day shot clock with deemed-approval if the City misses it (Gov. Code 66317). City ADU page: "60 days; often 30-45 in practice." |
| `max_size_sqft_general_cap` | 1200 | Gov. Code 66323: general cap 1,200 sq ft (detached; attached the lesser of 1,200 sq ft or 50% of the primary dwelling). State-guaranteed minimums that override local standards: 850 sq ft (studio/1-bedroom) and 1,000 sq ft (2+ bedrooms). JADU capped at 500 sq ft. Store 1,200 as the general cap. |
| `fire_sprinkler_trigger` | false | Gov. Code 66324: an ADU does not require sprinklers if they are not required for the primary dwelling. City FAQ-001 A21-A24 confirm: ADU (new detached, garage conversion, or addition) requires sprinklers only when the existing dwelling has or is required to have them. Note: newly constructed SB 9 principal units/duplexes DO require NFPA-13D sprinklers (FAQ-001 A19-A20) - that is an SB 9 rule, not an ADU rule. |

State-baseline reconciliation: none of the above are MORE restrictive than the CA
baselines (height >= 16 ft floor, setback == 4 ft ceiling, review <= 60 days, no
ADU owner-occupancy, sprinklers off unless primary is sprinklered, size cap up to
1,200). Where the local codified numeric is in transition (Long Beach applies
state law directly), the state value is used and flagged rather than inventing a
local figure.

Additional notes for the rule engine:
- ADUs allowed in all zones permitting single-family detached housing EXCEPT
  R-3-T and R-4-M, and prohibited in a PUD (per the legacy 21.31.360(B)); confirm
  against the adopted local ordinance once published.
- Coastal Overlay (Coastal Zone layer) may impose additional review; flag when the
  parcel intersects it.

---

## 5. Wiring cheat-sheet (copy-paste field map)

| Layer   | query_url | id | key field(s) |
|---------|-----------|----|--------------|
| Parcel (primary) | https://public.gis.lacounty.gov/public/rest/services/LACounty_Cache/LACounty_Parcel/MapServer/0/query | 0 | APN (or AIN); SitusFullAddress |
| Parcel (fallback) | https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Assessor_Parcels/FeatureServer/0/query | 0 | APN (10-digit, no situs) |
| Zoning  | https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/Zoning/FeatureServer/0/query | 0 | ZONING_SYMBOL |
| Boundary| https://services6.arcgis.com/yCArG7wGXGyWLqav/arcgis/rest/services/City_of_Long_Beach_City_Boundary_Official/FeatureServer/0/query | 0 | CITYNAME (where CITYNAME='LONG BEACH') |

- All four respond to `f=geojson`, `inSR=4326`, `outSR=4326`,
  `geometryType=esriGeometryEnvelope`; parcel + zoning support `outFields=*`.
- `verify_ssl`: true for all endpoints; standard cert chains validate.
- Zoning resolver: update `_cache_zoning` `_prop(...)` to read `ZONING_SYMBOL`.
- Seed `zoning_rules` keyed by `zone_code` (R-1, R-1-N, R-2-A, R-2-N, R-3, R-4,
  etc.) with the section-4 values; attach provenance (state Gov. Code sections +
  City ADU page / FAQ-001) per field.
- Flip `coverage_status='production'` only after rules are ingested + verified.

Sources:
- LA County parcel service: public.gis.lacounty.gov ArcGIS (verified via curl, 2026-07-21)
- City zoning / boundary / parcel services: services6.arcgis.com/yCArG7wGXGyWLqav, org "City of Long Beach, CA" (verified via curl, 2026-07-21)
- City ADU program: https://www.longbeach.gov/lbcd/adus/
- City FAQ-001 (ADU + SB 9): https://www.longbeach.gov/globalassets/lbcd/media-library/documents/planning/adus-and-sb9/faq-001
- CA state ADU law: Gov. Code 66310-66342
