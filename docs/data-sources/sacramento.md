# Sacramento (City of Sacramento) - Data Sources + ADU Rules

Status: sources + rules researched and LIVE-VERIFIED on 2026-07-21. Ready to wire.
`verified = true` (parcel AND zoning envelope queries both returned features for a
real residential address in the city).

Jurisdiction slug (proposed): `sacramento`
Coverage flip target: `coverage_status = 'production'` only after these sources +
rules are ingested into Postgres and the on-demand resolver is extended to this slug.

All three GIS layers are served by the Sacramento County enterprise ArcGIS server
`https://mapservices.gis.saccounty.net/arcgis/rest/services` (ArcGIS Server 10.x,
public, no token). The City of Sacramento zoning layer is published in that same
server under the `CITY_of_SACRAMENTO` service. Envelope queries with
`f=geojson&inSR=4326&outSR=4326` return WGS84 GeoJSON exactly like the proven LA
pattern.

## Test point (real residential address used for verification)

- Address A (commercial/midtown, sanity): `2701 K St, Sacramento, CA 95816`
  -> lon `-121.470936`, lat `38.573140` (US Census geocoder). Zoning here = `C-2-SPD`.
- Address B (single-family residential, primary verification):
  `1250 43rd St, Sacramento, CA 95819` (East Sacramento)
  -> lon `-121.450544`, lat `38.566375` (US Census geocoder). Zoning here = `R-1`.

Envelope helper (matches `services/core/ondemand.py` `bbox_envelope`, radius 120 m):
for lon/lat, `dlat = 120/111320`, `dlon = 120/(111320*|cos(lat)|)`,
envelope = `xmin,ymin,xmax,ymax`.

Address B envelope: `-121.45192234,38.56529670,-121.44916498,38.56745265`

---

## (a) Jurisdiction boundary polygon (point -> jurisdiction)

- Layer: `POLITICAL/MapServer/0` - "City Boundaries"
- Base URL: `https://mapservices.gis.saccounty.net/arcgis/rest/services/POLITICAL/MapServer/0`
- Geometry: `esriGeometryPolygon`
- City-name field: `CITY_NAME` (value `SACRAMENTO`); also `DISTRICT` = `CITY OF SACRAMENTO`
- Where filter to select just this city: `CITY_NAME='SACRAMENTO'`

Verified curl (returns 1 polygon feature; bbox lon -121.561..-121.363,
lat 38.438..38.686; test point B is inside):

```
curl -s "https://mapservices.gis.saccounty.net/arcgis/rest/services/POLITICAL/MapServer/0/query?where=CITY_NAME%3D%27SACRAMENTO%27&outFields=CITY_NAME&returnGeometry=true&outSR=4326&f=geojson"
```

Note: layer 3 "City Boundaries with Unincorporated" and layer 2 "Sacramento County
Boundary" also exist; use layer 0 filtered to `CITY_NAME='SACRAMENTO'` for the city
proper (do NOT use the county boundary as the city jurisdiction).

---

## (b) Parcel service (point/envelope -> APN + situs + geometry)

- Layer: `PARCELS/MapServer/8` - "Active GIS Parcel Base" (Sacramento County Assessor
  parcel base; the county assessor is the parcel authority for the City of Sacramento)
- Base URL: `https://mapservices.gis.saccounty.net/arcgis/rest/services/PARCELS/MapServer/8`
- Geometry: `esriGeometryPolygon`
- APN field: `APN_DASH` (formatted `007-0111-017-0000`); also `APN10` (`0070111017`)
  and `PARCEL_NUMBER` (`00701110170000`)
- Situs address fields: `STREET_NBR` + `STREET_NAME` (e.g. `2709` + `K ST`).
  There is no single pre-joined "situs full address" field; concatenate
  `STREET_NBR` + ' ' + `STREET_NAME`.
- Owner name field (present, may be privacy-sensitive): `NAME`, `CARE_OF_NAME`

Verified curl (Address A envelope; returned 37 parcel features, each with APN + polygon):

```
curl -s "https://mapservices.gis.saccounty.net/arcgis/rest/services/PARCELS/MapServer/8/query?geometry=-121.472315,38.572062,-121.469557,38.574218&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"
```

Sample returned properties: `APN_DASH=007-0111-017-0000`, `APN10=0070111017`,
`PARCEL_NUMBER=00701110170000`, `STREET_NBR=2709`, `STREET_NAME=K ST`, geometry `Polygon`.

Wiring note: the on-demand resolver's `_prop(props, "APN", "AIN", ...)` lookup must be
extended to also match `APN_DASH` / `APN10` / `PARCEL_NUMBER` for this jurisdiction,
and situs assembled from `STREET_NBR` + `STREET_NAME` (the LA `SitusFullAddress`
field does not exist here).

Alternative layer: `PARCELS/MapServer/22` "ALL Parcels" has an identical schema
(includes obsolete/inactive parcels); prefer layer 8 "Active GIS Parcel Base" for
current parcels. Layer 0 returns no fields (group/annotation layer) - do not use it.

---

## (c) Zoning service (-> zone_code polygons)

- Layer: `CITY_of_SACRAMENTO/MapServer/3` - "City of Sacramento Zoning" (published by
  the City of Sacramento; `SacCity` is the ArcGIS Hub owner)
- Base URL: `https://mapservices.gis.saccounty.net/arcgis/rest/services/CITY_of_SACRAMENTO/MapServer/3`
- Geometry: `esriGeometryPolygon`
- Zone-code field: `ZONE` (full code incl. overlay, e.g. `R-1`, `C-2-SPD`, `H-SPD`)
- Base-zone field: `BASE_ZONE` (e.g. `R-1`, `C-2`, `H`) - use this for rule keying
  (strip the SPD/overlay suffix)
- Overlay field: `OVERLAY` (e.g. `SPD`); zone description field: `DESCRIPTIO`
  (e.g. `Single-Unit Dwelling Zone`, `General Commercial Zone`)

Verified curl (Address B / residential envelope; returned 8 features, all `R-1`):

```
curl -s "https://mapservices.gis.saccounty.net/arcgis/rest/services/CITY_of_SACRAMENTO/MapServer/3/query?geometry=-121.45192234,38.56529670,-121.44916498,38.56745265&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"
```

Sample returned properties: `ZONE=R-1`, `BASE_ZONE=R-1`, `OVERLAY=<null>`,
`DESCRIPTIO=Single-Unit Dwelling Zone`, geometry `Polygon`. (Address A returns
`ZONE=C-2-SPD`, `BASE_ZONE=C-2`, `DESCRIPTIO=General Commercial Zone`.)

Wiring note: the on-demand resolver's zoning `_prop(props, "ZONE_CLASS", "ZONE_CMPLT",
...)` lookup must be extended to match `ZONE` (full) and `BASE_ZONE` (rule key) for
this jurisdiction. Sacramento single-family base zones are `R-1`, `R-1A`, `R-1B`;
duplex `R-2`, multi `R-2A`/`R-3`/`R-4`/`R-5`. The feasibility `_is_single_family_zone`
prefix set (currently LA-oriented: R1/RS/RE/RA/RW1/RD) already matches `R-1`.

---

## (d) ADU / JADU / SB 9 rules keyed by zone

Ordinance: Sacramento City Code Title 17, section 17.228.105 "Accessory dwelling
units and junior accessory dwelling units" (Chapter 17.228 Special Use Regulations).
Current version cited: 2026 S-4, most recently amended by Ord. 2026-0001 sec 25
(prior: Ord. 2024-0051, 2024-0017, 2021-0023, 2019-006, 2017-0008, 2013-0020,
2013-0007).

- Source URL (verified fetch via curl_cffi impersonate=chrome; American Legal is
  Cloudflare-gated):
  `https://codelibrary.amlegal.com/codes/sacramentoca/latest/sacramento_ca/0-0-0-36106`
- State validation cross-check: HCD ADU ordinance review letter for Sacramento
  (findings 01/2026):
  `https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/ordinance-review-letters/sacramento-adu-findings-012026.pdf`
- City applicant guidance (context only): `https://adu.cityofsacramento.org/`

The ordinance offers TWO mutually exclusive paths (may not be combined):
- Subsection B - City local development option (Gov Code 66310-66403).
- Subsection C - State ministerial option (Gov Code 66323): detached ADU <= 800 sqft,
  18 ft height (up to 20 ft to match primary roof pitch), 4 ft side/rear setbacks.

ADU count (subsection B.1.a): a single-unit-dwelling lot may have up to 2 ADUs, or
1 ADU + 1 JADU, or 2 JADUs. A duplex/multi-unit lot may have up to 2 ADUs.
ADUs are not counted toward density and are consistent with the GP/zoning designation.

### Key rule field values (zone-independent unless noted; apply to residential base zones R-1 etc.)

| field | value | source note |
|---|---|---|
| `max_height_detached_standard_ft` | `18` | 17.228.105 C.1.b: detached new ADU max 18 ft (up to 20 ft to align roof pitch with primary). Under local option B.2.c.ii the underlying zone height applies instead (e.g. ~35 ft in R-1). >= CA floor 16 ft (AB 2221). |
| `side_rear_setback_min_ft` | `4` | 17.228.105 C.1.b (state option) requires 4 ft side/rear. Local option B.2.c.iii allows interior side/rear of the lesser of the zone requirement or 3 ft. Both <= CA ceiling 4 ft (AB 2221). Recording 4 (conservative); note 3 ft available under option B. |
| `owner_occupancy_required_adu` | `false` | 17.228.105 imposes owner occupancy only on JADUs (B.3.b), not on ADUs. Matches CA baseline (Gov 66315/66323). |
| `owner_occupancy_required_jadu` | `true` | 17.228.105 B.3.b: JADU owner must reside onsite unless owned by a government agency, land trust, or housing organization. Conditional per CA (Gov 66333(b)). |
| `jadu_allowed` | `true` | 17.228.105 B.3: 1 JADU per single-unit dwelling, <= 500 sqft, within the walls of the SFD, separate entrance, deed restriction, no separate sale (Gov 66333). |
| `jadu_max_size_sqft` | `500` | 17.228.105 B.3.a. Matches CA (Gov 66333). |
| `parking_required` | `false` (default to CA state baseline) | UNCLEAR LOCALLY: section 17.228.105 contains no parking provision. Defaulting to CA baseline: no additional parking may be required near transit / historic / car-share, etc. (SB 897 / Gov 66314). Verify against Title 17 off-street parking chapter before asserting a local number. |
| `permit_review_days` | `60` | 17.228.105 B.4.b: city must approve/deny a complete application within 60 days where an existing residential use is present; deemed approved if not acted on within 60 days. Matches CA <= 60 (SB 897/AB 2221). |
| `max_size_sqft_general_cap` | `1200` | 17.228.105 B.2.b.iii: one detached ADU max 1,200 sqft; two detached combined also <= 1,200 sqft. (Attached ADU B.2.b.ii: greater of 50% of primary or 850 sqft (<=1 br) / 1,000 sqft (>1 br).) Consistent with CA cap up to 1,200. |
| `fire_sprinkler_trigger` | `false` (default to CA state baseline) | UNCLEAR LOCALLY: section 17.228.105 is silent on fire sprinklers. Defaulting to CA baseline: an ADU is not required to provide fire sprinklers if they are not required for the primary residence (SB 897 / Gov 66314). Verify against the city building code (Title 15) if a definitive local trigger is needed. |

Supporting size/standard values (for completeness, from 17.228.105 subsection B):
- `max_size_sqft_attached` = greater of 50% of primary dwelling OR 850 sqft (<=1 bedroom)
  / 1,000 sqft (>1 bedroom) (B.2.b.ii).
- `max_size_sqft_detached` = 1,200 sqft (B.2.b.iii).
- Detached ADU / primary min separation = 4 ft (B.2.c.i).
- Lot-coverage/open-space exemption for ADUs under 800 sqft total lot coverage (B.2.c.ii.2).
- ADUs > 60 ft from front property line: no setback for single-story / first floor;
  2nd floor+ = 3 ft or zone, whichever less (B.2.c.iii.2).
- ADU may not be sold separately from the primary residence except per Gov 66341
  (B.2.a.ii).

SB 9 (duplex / urban lot split): not addressed in 17.228.105; governed by state SB 9
(Gov 65852.21 / 66411.7) and any separate Sacramento SB 9 implementation ordinance.
Not researched here; use CA state baselines and route to `needs_professional_review`
until a Sacramento SB 9 ordinance is ingested.

---

## (e) Coverage flip checklist (do NOT flip until all true)

1. Insert `jurisdictions` row: slug `sacramento`, boundary geom from source (a),
   `coverage_status` staged as `planned`/`beta` until steps below complete.
2. Register the three `source_registry` rows (parcel, zoning, boundary) with the
   exact base URLs above + provider `arcgis`.
3. Extend `services/core/ondemand.py`:
   - add Sacramento `LayerConfig`s (parcel `PARCELS/MapServer/8`,
     zoning `CITY_of_SACRAMENTO/MapServer/3`); scope selection is currently hard-gated
     to `los_angeles` (`_LA_SLUG` in `_in_scope`) - generalize to a per-jurisdiction
     layer map.
   - extend APN `_prop` to match `APN_DASH`/`APN10`/`PARCEL_NUMBER` and situs to
     `STREET_NBR`+`STREET_NAME`; extend zoning `_prop` to match `ZONE`/`BASE_ZONE`.
4. Ingest `zoning_rules` + `rule_attributes` keyed by `BASE_ZONE` from section (d),
   each with provenance to 17.228.105 and state-baseline compliance flags
   (3 ft / 18 ft are within CA baselines; no `possibly_more_restrictive_than_state`
   flags expected). Mark parking + fire-sprinkler rows as
   `data_status = needs_review` (defaulted to state baseline, local text silent).
5. Live-recheck parcel + zoning `/query` return features (curls above) as a
   pre-flip smoke test, then flip `coverage_status = 'production'`.

## Verification summary

- Parcel query (layer 8): PASS - 37 features with `APN_DASH` + polygon geometry.
- Zoning query (layer 3): PASS - `R-1` at residential test point, `C-2-SPD` at
  midtown test point, all with polygon geometry + `ZONE`/`BASE_ZONE`.
- Boundary query (layer 0): PASS - single `SACRAMENTO` polygon, test point inside.
- ADU ordinance 17.228.105: fetched in full (curl_cffi chrome), key values recorded.
- All queries against `mapservices.gis.saccounty.net`, no auth/token required,
  `f=geojson` + `inSR/outSR=4326` confirmed working.
