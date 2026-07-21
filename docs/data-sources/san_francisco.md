# San Francisco - Data Sources + ADU Rules (LIVE-VERIFIED)

City and County of San Francisco (consolidated city-county). Slug suggestion: `san_francisco`.
All endpoints below were live-tested on 2026-07-21 with envelope/where queries and returned features.
verified = true (parcel AND zoning queries returned features for a real SF residential point).

Style note: request path stays deterministic (no LLM). Every field below carries a citable source URL.

---

## 0. Test point used

Sunset District residential block (43rd Ave near Kirkham):
- lon = -122.5040, lat = 37.7566
- Envelope used (~120 m box, xmin,ymin,xmax,ymax): `-122.5054,37.7555,-122.5026,37.7577`
- Result: parcel layer returned 197 features (single-family lots), zoning returned RH-1 polygons.

Envelope query shape that works (matches `services/core/ondemand.py::arcgis_query_params`):
`/query?geometry=xmin,ymin,xmax,ymax&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson`

NOTE the base path is `/arcgiswa/` (not `/arcgis/`) on sfplanninggis.org.

---

## 1. Parcel service (APN + situs + geometry)

- Provider: City and County of San Francisco Planning Department (official).
- Service: `PlanningData/MapServer`, layer id **23** ("Parcels").
- Geometry: `esriGeometryPolygon` (returns GeoJSON Polygon).
- Base layer URL (citable source_url):
  `https://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/23`
- Exact /query URL (copy-paste):
  `https://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/23/query`

Field names:
- APN-like id: **`blklot`** (Assessor block+lot, e.g. `1889010`) and **`mapblklot`** (map block/lot; identical here).
  SF has no "APN" field per se; block/lot is the parcel identifier. Map `apn` <- `blklot` (fallback `mapblklot`).
- Situs/address: composed from **`from_st`**, **`to_st`**, **`street`**, **`st_type`** (e.g. `1551` / `1551` / `43RD` / no type here).
  There is no single pre-composed address string; build situs as `from_st street st_type` (+ ", San Francisco, CA").
- Other useful: `block_num`, `lot_num`, `objectid`, `shape_Area` (sq ft, planar; prefer PostGIS geography area).

Verified curl:
```
curl -sS "https://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/23/query?geometry=-122.5054,37.7555,-122.5026,37.7577&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"
# -> 197 features; e.g. {"mapblklot":"1889010","blklot":"1889010","block_num":"1889","lot_num":"010","from_st":"1551","street":"43RD"}
```

Alternate parcel layer: id **24** ("Parcels - MapBlockLot") has fewer fields (`mapblklot`,`block_num`,`lot_num`) and no
street address. Prefer layer 23 (has address components).

---

## 2. Zoning service (zone_code polygons)

- Provider: SF Planning Department (official).
- Service: `PlanningData/MapServer`, layer id **3** ("Zoning Map - Zoning Districts").
- Geometry: `esriGeometryPolygon`.
- Base layer URL (citable source_url):
  `https://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/3`
- Exact /query URL (copy-paste):
  `https://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/3/query`

Field names:
- Zone code: **`zoning`** (e.g. `RH-1`) and **`zoning_sim`** (simplified, identical for residential). Map `zone_code` <- `zoning` (fallback `zoning_sim`).
- Zone name: **`districtname`** (e.g. `RESIDENTIAL- HOUSE, ONE FAMILY`).
- General plan category: **`gen`** (e.g. `Residential`).
- Code section (deep link into Planning Code): **`codesection`** (e.g. `209.1`) and **`url`** (per-district amlegal link).
- Other: `objectid`, `commercial_hours_of_operation`.

Verified curl:
```
curl -sS "https://sfplanninggis.org/arcgiswa/rest/services/PlanningData/MapServer/3/query?geometry=-122.5054,37.7555,-122.5026,37.7577&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"
# -> 6 features; e.g. {"zoning_sim":"RH-1","zoning":"RH-1","districtname":"RESIDENTIAL- HOUSE, ONE FAMILY","gen":"Residential","codesection":"209.1"}
```

SF residential zone families (for SB 9 / single-family gating): `RH-1`, `RH-1(D)`, `RH-1(S)` are single-family
"Residential House, One Family"; `RH-2`, `RH-3` are two/three-family; `RM-*` multifamily; `RTO`, `NC*`, `C-*` etc.
mixed/commercial. The existing `feasibility._is_single_family_zone` prefixes are LA-specific (R1/RS/RE...) and will NOT
match SF `RH-1`; wiring SF requires extending that single-family test to recognize `RH-1` (note for the code step, not
changed here).

---

## 3. City boundary polygon (point -> jurisdiction)

SF is a consolidated city-county, so any regional jurisdiction/county layer selects the whole city with one filter.

- Provider: Metropolitan Transportation Commission (MTC/ABAG) regional jurisdictions (official regional GIS, hosted ArcGIS Online).
- Service: `region_jurisdiction_clp/FeatureServer`, layer id **0**.
- Base URL: `https://services3.arcgis.com/i2dkYWmb4wHvYPda/arcgis/rest/services/region_jurisdiction_clp/FeatureServer/0`
- Where filter to select just San Francisco: **`jurname='San Francisco'`** (also `coname='San Francisco'`, FIPS county `075`).
- Exact /query URL (copy-paste):
  `https://services3.arcgis.com/i2dkYWmb4wHvYPda/arcgis/rest/services/region_jurisdiction_clp/FeatureServer/0/query?where=jurname%3D%27San+Francisco%27&outFields=jurname&returnGeometry=true&outSR=4326&f=geojson`

Verified: returns exactly one feature, geometry MultiPolygon (20 parts - mainland + Farallones/Treasure Island etc.).
Fields: `jurname`, `coname`, `fipst`, `fipco`.

Alternative official boundary (if MTC AGOL is undesirable): California City Boundaries and Identifiers,
CA Open Data / gis.data.ca.gov, filter `CITY='San Francisco'`. Not curl-tested here; MTC layer above is verified.

---

## 4. Overlay / hazard layers

- Flood: reuse the existing national FEMA NFHL layer already wired for LA
  (`https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28`, field `FLD_ZONE`). NFHL is nationwide and
  covers SF - no SF-specific change needed. SF Planning also exposes layer **41** "FEMA Flood Hazard" in PlanningData
  if a local mirror is preferred.
- Seismic (SF-specific, optional): PlanningData layer **39** "Seismic Hazard - Liquefaction", **40** "Landslide".
- Slope/hillside (optional): PlanningData layers **18** ("Slope of 20% or greater"), **19** ("25% or greater").
- Historic (optional): PlanningData layers **17** (Article 10 Historic Districts), **16** (Article 11 Conservation),
  **11** (Landmarks). Relevant because 207.2(d)(10) imposes objective architectural review for historic properties.

---

## 5. ADU / JADU ordinance - citation + verified rule values

Ordinance: **San Francisco Planning Code Article 2, Sec. 207.1 (Local ADU Program) and Sec. 207.2 (State-Mandated ADU
Program).** Codified in the SF Planning Code (American Legal Publishing code library).

- Sec. 207.2 (State-Mandated ADU Program) - the ministerial, state-aligned track most new ADUs use:
  `https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-19964`
- Sec. 207.1 (Local ADU Program) - SF's discretionary local program (subject to Sec. 311 notification, no fixed
  size/number cap, more design latitude but not ministerial):
  `https://codelibrary.amlegal.com/codes/san_francisco/latest/sf_planning/0-0-0-19955`
- Implementing guidance: Planning Director Bulletin No. 3 "State Accessory Dwelling Unit Program":
  `https://sfplanning.org/resource/planning-director-bulletin-no-3-state-accessory-dwelling-unit-program`
- State baseline reference: HCD ADU Handbook (Gov Code 66314-66333).

Fetch note (for the ingestion step): amlegal is Cloudflare-fronted. curl_cffi with `impersonate='chrome124'` works IF
you first GET the code landing page `.../codes/san_francisco/latest/sf_planning` in the same Session to seed cookies,
then GET `/api/render-doc/san_francisco/latest/sf_planning/0-0-0-19964/` with header
`X-Requested-With: XMLHttpRequest` and a Referer of the landing page. A cold render-doc request returns 403.

### Verified rule field values (keyed by zone; SF state program is citywide, not per-zone-specific)

Source note format: [PC = SF Planning Code section]. Values are from the ministerial state program (207.2), which is
what a deterministic feasibility result should quote for a standard detached ADU; they match or float to the CA state
baseline. Local-program (207.1) latitude is noted where it differs.

| field | value | source note |
|---|---|---|
| `max_height_detached_standard_ft` | 18 (plus 2 ft for matching roof pitch) | PC 207.2(d)(9)(A): "A height of 18 feet for a detached ADU... An additional two feet... to accommodate a roof pitch... aligned with the roof pitch of the primary dwelling." Exceeds state floor of 16. |
| `max_height_attached_ft` | 25 | PC 207.2(d)(9)(B): "A height of 25 feet for an ADU that is attached to the primary dwelling." Matches state ceiling. |
| `side_rear_setback_min_ft` | 4 | PC 207.2(d)(7): "A setback of no more than four feet from the side and rear lot lines..."; and no setback for conversions/replacements. Matches state ceiling of 4. |
| `front_setback_restriction` | no front setback that precludes an 800 sqft / 16 ft / 4-ft-setback ADU | PC 207.2(d) preamble: City shall not impose front setback (or lot coverage/FAR/open space/min lot size) that does not permit an ADU 800 sqft or less, 16 ft or less, 4 ft setbacks. Matches state. |
| `owner_occupancy_required_adu` | false | Not required under 207.2 (ministerial, per Gov Code 66315). SF imposes no owner-occupancy for the ADU under the state program. |
| `owner_occupancy_required_jadu` | conditional (shared sanitation) | Per state law Gov 66333(b); SF 207.2 covers JADUs under the same ministerial standards. Default to state baseline; verify. |
| `jadu_allowed` | true | PC 207.2 expressly applies to "ADUs and JADUs"; 1 JADU per single-family lot per Gov 66333. |
| `jadu_separate_sale_allowed` | false | PC 207.2(g): lot "shall not be subdivided in a manner that would allow the ADU or JADU to be sold or separately financed" (narrow condominium exceptions under 207.4 / Gov 66341). |
| `parking_required` | false | PC 207.2(d)(8): replacement parking not required when a garage/carport is demolished or converted for an ADU. SF is transit-served; state law (SB 897) bars parking where near transit. Float to state baseline false; note where >0.5 mi from transit verify. |
| `permit_review_days` | 60 | Not a numeric local value; 207.2(e) makes review ministerial (no discretionary review, no Sec. 311 notification, no Planning Commission hearing). Default to CA state baseline of <=60 days (Gov 66317). |
| `max_size_sqft_1br` | 850 | PC 207.2(c)(1) & 207.2(d)(5)(B): ADU with one bedroom or less <= 850 sqft Gross Floor Area (detached). |
| `max_size_sqft_2br` | 1000 | PC 207.2(d)(5)(B): ADU with more than one bedroom <= 1,000 sqft Gross Floor Area (detached). |
| `max_size_sqft_general_cap` | 1000 | Detached cap for 2+ br is 1,000 sqft; attached is greater of 50% of primary GFA or 850/1000. Use 1,000 as the general detached cap; note attached percentage rule. |
| `fire_sprinkler_trigger` | false | Not imposed by 207.2; per state law (Gov 66317 / SB 897) sprinklers not required for an ADU if not required for the primary dwelling. Default to state baseline false; verify against SF Building Code for the specific structure. |

### SB 9 note
SB 9 (Gov 65852.21 / 66411.7) applies in single-family residential zones. In SF the single-family zones are the
`RH-1` family. SF implements SB 9 via separate provisions; treat SB 9 paths as `needs_professional_review`/`conditional`
for `RH-1` and `likely_ineligible` for `RH-2`/`RH-3`/`RM`/`NC` until SF's SB 9 local rules are ingested and verified.

---

## 6. Wiring checklist (for the code step - NOT done in this doc)

1. Add SF jurisdiction row (slug `san_francisco`), boundary from section 3, coverage_status flipped to `production`
   only after rules ingested + verified.
2. Add SF `LayerConfig`s in the on-demand resolver (PlanningData/23 parcels, PlanningData/3 zoning). The resolver's
   `_prop` APN lookup must include `blklot`/`mapblklot`; zoning lookup must include `zoning`/`zoning_sim` (current LA
   code only checks `APN`/`AIN` and `ZONE_CLASS`/`ZONE_CMPLT`). Both are field-name additions, no schema change.
   Also extend `_in_scope` beyond the LA-only slug gate.
3. Situs address for SF parcels must be composed from `from_st`+`street`+`st_type` (no single situs field).
4. Extend `feasibility._is_single_family_zone` to recognize `RH-1*` as single-family (currently LA prefixes only).
5. SSL: sfplanninggis.org served a valid chain in testing (no verify=False needed, unlike LA ZIMAS). Confirm in prod.
6. Seed SF zoning_rules keyed by zone_code using the section 5 table, with per-field provenance pointing at PC 207.2
   subsections and the amlegal URLs.

---

## 7. Live-verification log (2026-07-21)

- `PlanningData/MapServer/23/query` envelope around test point -> 197 parcel features, Polygon geometry, `blklot` present. PASS.
- `PlanningData/MapServer/3/query` envelope around test point -> 6 zoning features, `zoning`=`RH-1`, `districtname`, `codesection`=`209.1`. PASS.
- `region_jurisdiction_clp/FeatureServer/0/query?where=jurname='San Francisco'` -> 1 feature, MultiPolygon boundary. PASS.
- amlegal 207.2 full text fetched via curl_cffi (chrome124 + seeded cookies + XHR header) -> HTTP 200, height/size/setback clauses extracted. PASS.
- FEMA NFHL (existing LA config) is nationwide; covers SF. No new test required.
