# San Diego data sources (City of San Diego)

Status: RESEARCHED + LIVE-VERIFIED (parcel and zoning queries both returned real
features around a real residential address). Ready for wiring; flip
coverage_status='production' only after rules are ingested into the DB.

Verification address: 4653 Cape May Ave, San Diego, CA 92107 (Ocean Beach,
residential). Census-geocoded to lon=-117.242912, lat=32.745644.

Envelope used in all curl tests below (~120 m box, xmin,ymin,xmax,ymax, WGS84):

    -117.244194,32.744566,-117.241630,32.746722

All services accept the proven envelope shape:
`/query?geometry=xmin,ymin,xmax,ymax&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&f=geojson`.

---

## 1. Parcels (APN + situs + geometry) -- VERIFIED

Official City of San Diego regional/assessor parcels (County Assessor data served
by the City geocoder merged service).

- Layer base: `https://webmaps.sandiego.gov/arcgis/rest/services/GeocoderMerged/MapServer/1`
- Layer name / id: `PARCELS_ALL` / **1**
- Query URL:
  `https://webmaps.sandiego.gov/arcgis/rest/services/GeocoderMerged/MapServer/1/query`
- APN field: **`APN`** (10-digit string; also `APN_8`, and integer `PARCELID`)
- Situs fields: `SITUS_ADDRESS` (number, integer), `SITUS_PRE_DIR`, `SITUS_STREET`,
  `SITUS_SUFFIX`, `SITUS_POST_DIR`, `SITUS_JURIS`. Also useful: `OWN_NAME1`,
  `ACREAGE`, `ASR_TOTAL`, `UNITQTY`.
- Geometry: `esriGeometryPolygon` (returned as GeoJSON Polygon).

Live test (HTTP 200, 111 features):

    curl -s "https://webmaps.sandiego.gov/arcgis/rest/services/GeocoderMerged/MapServer/1/query?geometry=-117.244194,32.744566,-117.241630,32.746722&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Sample returned features:
- APN=4485221700  SITUS=4603 BRIGHTON AVE
- APN=4485221800  SITUS=4609 BRIGHTON AVE
- APN=4485221900  SITUS=4617 BRIGHTON AVE

Note: situs is split across `SITUS_ADDRESS` + `SITUS_STREET` + `SITUS_SUFFIX`, so
compose a normalized address on ingest (the LA parcel layer had a single
`SitusFullAddress`; SD does not).

Alternate (county) parcel source if the City service is ever down:
`https://gis-public.sandiegocounty.gov/arcgis/rest/services/sdep_warehouse/PARCELS_ALL/MapServer`
and SanGIS regional warehouse. Prefer the City webmaps service (matches City zoning coverage).

---

## 2. Zoning (zone code polygons) -- VERIFIED

Official City of San Diego Development Services Department (DSD) Official Zoning Map.

- Layer base: `https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0`
- Layer name / id: `Official Zoning Map` / **0**
- Query URL:
  `https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0/query`
- Zone code field: **`ZONE_NAME`** (e.g. `RM-1-1`, `RS-1-7`). Other fields:
  `ORDNUM` (adopting ordinance), `IMP_DATE`.
- Geometry: `esriGeometryPolygon`.

Live test (HTTP 200, 1 feature):

    curl -s "https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0/query?geometry=-117.244194,32.744566,-117.241630,32.746722&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Returned: `ZONE_NAME = RM-1-1` (Residential Multiple-unit). Confirms the zone-code
field name and polygon geometry.

Overlay zones (fire/coastal/parking-impact, which SDMC 141.0302 keys several rules
off of) are in a separate service, useful for later overlay ingest:
`https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Overlay/MapServer`.

---

## 3. City boundary polygon (point -> jurisdiction) -- VERIFIED

SanGIS regional Municipality Boundary layer (all incorporated cities in the county).

- Query URL:
  `https://gis.sangis.org/maps/rest/services/Public/Basemap/MapServer/5016/query`
- Layer name / id: `Municipality Boundary` / **5016**
- City name field: **`name`**
- Where filter to select just the City of San Diego: **`name='SAN DIEGO'`**

Live test (returned San Diego multipolygon parts):

    curl -s "https://gis.sangis.org/maps/rest/services/Public/Basemap/MapServer/5016/query?where=name%3D%27SAN%20DIEGO%27&outFields=name&returnGeometry=true&outSR=4326&f=geojson"

---

## 4. ADU / JADU ordinance and rule values

Citation: San Diego Municipal Code (SDMC) Chapter 14, Article 1, Division 3,
**Section 141.0302** "Accessory Dwelling Units (ADUs) and Junior Accessory Dwelling
Units (JADUs)". Code edition footer: (3-2026) -- reflects the August 2025 ADU
regulation update (ordinances O-21836, O-21989). ADUs/JADUs are a limited use
decided by **Process One** (ministerial).

- Source URL (official PDF):
  `https://docs.sandiego.gov/municode/MuniCodeChapter14/Ch14Art01Division03.pdf`
- Summary bulletin: DSD Information Bulletin 400,
  `https://www.sandiego.gov/development-services/forms-publications/information-bulletins/400`

Rule field values (each with the subsection it comes from; where the local numeric
is not fixed, the CA state baseline is used and flagged):

- **max_height_detached_standard_ft** = 16 (state floor; local flag needs_review).
  SDMC 141.0302(b)(8) does NOT set a flat detached numeric cap: detached ADUs on
  single-dwelling lots are limited to two stories (b)(8)(A) and must comply with the
  overall max structure height of the underlying base + overlay zone (b)(8)(C). The
  16 ft value is the state-guaranteed minimum and the threshold that switches the
  setback tier (b)(9)(C) vs (b)(9)(D); actual allowed height can be the base-zone max
  (commonly 24-30 ft). Store 16 as the guaranteed standard, resolve the true cap from
  the parcel's base zone at analysis time.
- **side_rear_setback_min_ft** = 0 (local), state baseline ceiling 4. SDMC
  141.0302(b)(9)(C)(i): ADU structures <=16 ft outside a High/Very High Fire Hazard
  Severity Zone have NO minimum interior side/rear setback. (b)(9)(D): ADUs >16 ft
  outside a fire zone also 0 ft unless the side/rear line abuts residential, then 4 ft
  or base-zone min whichever is less. Within a High/VHFHSZ: 4 ft (b)(9)(C)(ii),
  (b)(9)(D)(ii). Street side yard: 4 ft or base-zone min whichever is less (b)(9)(B).
  Front: per base zone (b)(9)(A). Use 4 ft as the conservative default for the
  feasibility envelope; 0 ft is permissible for the common small-detached case.
- **owner_occupancy_required_adu** = false. SDMC 141.0302(b)(11): "The record owner
  is not required to live on the same premises of an ADU." (matches state Gov 66315.)
- **owner_occupancy_required_jadu** = true. SDMC 141.0302(c)(1)(E)-(F): record owner
  must reside in the single dwelling unit or the JADU and record a deed-restriction
  agreement. (matches state Gov 66333(b).)
- **jadu_allowed** = true. SDMC 141.0302(c)(1): one JADU per single-dwelling premises,
  within existing/proposed SDU or attached garage; 150-500 sq ft (c)(4); may not be
  sold separately (c)(1)(D); requires efficiency kitchen (c)(6).
- **parking_required** = false (general). SDMC 141.0302(b)(10)(A): no on-street or
  off-street parking required for ADUs, EXCEPT (b)(10)(B) one off-street space when the
  premises is both in the Beach Impact Area of the Parking Impact Overlay Zone AND
  outside a transit priority area (with several exemptions, e.g. ADU <=500 sq ft,
  historical district). Treat as false with a Beach-Impact-Area conditional flag.
- **permit_review_days** = 60 (CA state baseline; local numeric not stated). SDMC
  141.0302 processes ADUs as ministerial Process One; the code text does not state a
  day count, so default to the state-mandated 60-day ministerial review (Gov 66317 /
  SB 897). Flag as state-baseline-derived.
- **max_size_sqft_general_cap** = 1200. SDMC 141.0302(b)(7)(B): gross floor area of an
  attached or detached ADU shall not exceed 1,200 sq ft; minimum 150 sq ft (b)(7)(A);
  conversions of existing space have no max (b)(7)(C)-(E). State 800 sq ft exemption
  from FAR/coverage/front-setback/open-space is honored at (b)(4).
- **fire_sprinkler_trigger** = false (conditional). SDMC 141.0302(b)(6)(A): ADU/JADU
  not required to have automatic fire sprinklers if not required for the primary
  dwelling; (b)(6)(C) construction of a detached ADU does not trigger sprinklers in
  the existing primary dwelling. Required only if the primary dwelling is sprinklered
  (b)(6)(B). (matches state SB 897 baseline.)

Additional notes for the rule engine:
- Max number of ADUs: up to 8 detached ADUs may be permitted on qualifying multi-unit
  premises (b)(2)(B); count limits at (b)(2)(A).
- ADU minimum rental term 31 days; JADUs no rental-term limit (a)(8).
- ADU Home Density Bonus for affordable units exists at 141.0302(d) (out of v1 scope).
- Coastal Overlay Zone imposes extra regulations (a)(7); flag when the parcel is in the
  Coastal Overlay.

---

## Wiring cheat-sheet (copy-paste field map)

| Layer   | query_url | id | key field(s) |
|---------|-----------|----|--------------|
| Parcel  | https://webmaps.sandiego.gov/arcgis/rest/services/GeocoderMerged/MapServer/1/query | 1 | APN; SITUS_ADDRESS+SITUS_STREET+SITUS_SUFFIX |
| Zoning  | https://webmaps.sandiego.gov/arcgis/rest/services/DSD/Zoning_Base/MapServer/0/query | 0 | ZONE_NAME |
| Boundary| https://gis.sangis.org/maps/rest/services/Public/Basemap/MapServer/5016/query | 5016 | name (where name='SAN DIEGO') |

All three respond to `f=geojson`, `inSR=4326`, `outSR=4326`,
`geometryType=esriGeometryEnvelope`. Parcel + zoning support `outFields=*`. No SSL
workaround needed (unlike LA ZIMAS); standard cert chains validate. Both City
webmaps services responded in under ~1s in testing.
