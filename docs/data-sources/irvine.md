# Irvine data sources (City of Irvine)

Status: RESEARCHED + LIVE-VERIFIED (parcel and zoning envelope queries both returned
real features around a real residential address on 2026-07-21). Ready for wiring; flip
coverage_status='production' only after rules are ingested into the DB.

Jurisdiction slug (proposed): `irvine`

Verification address: 14 Foxhill, Irvine, CA 92604 (Woodbridge / Planning Area 11,
single-family). Census-geocoded (Public_AR_Current) to lon=-117.791522532196,
lat=33.690594625669.

Envelope used in all curl tests below (~230 m box, xmin,ymin,xmax,ymax, WGS84):

    -117.792803,33.689515,-117.790243,33.691675

All three primary layers live on the City of Irvine's official ArcGIS Server
(`gis.cityofirvine.org`, ArcGIS 10.91) in ONE MapServer service, `OnlineParcel`.
This is the authoritative City GIS (it backs the public Online Parcel Search at
gis.cityofirvine.org/onlineparcel/), preferred over any third-party aggregator. Valid
SSL, no `verify=False` needed (unlike LA ZIMAS). Parcel query ~1.7s, zoning ~0.3s.

All layers accept the proven envelope shape:
`/query?geometry=xmin,ymin,xmax,ymax&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&f=geojson`.

Service root: `https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer`

---

## 1. Parcels (APN + geometry) -- VERIFIED

Official City of Irvine parcel (Land) layer. Includes APN, PIN, tract/lot, and
Planning Area number.

- Layer base: `https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/4`
- Layer name / id: `Parcel` / **4**
- Query URL:
  `https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/4/query`
- APN field: **`APN`** (esriFieldTypeInteger, e.g. `45121312`). Note: stored as an
  8-digit integer with NO dashes; normalize to Orange County dashed form
  `451-213-12` (book-page-parcel) on ingest.
- Other fields: `PIN` (City parcel id), `TRACT`, `LOT`, `PA` (Planning Area number,
  drives Irvine's master-plan zoning), `ACRES`, `SHAPE.STArea()`.
- Geometry: `esriGeometryPolygon` (returned as GeoJSON Polygon).
- IMPORTANT: this layer has NO situs/address field (`NAME`/`LABEL` are null for
  residential parcels). Leave `situs_address` null on cache, or join from the Orange
  County parcel service in section 4 (which carries `SITE_ADDRESS`).

Live test (HTTP 200, **62** parcel features):

    curl -s "https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/4/query?geometry=-117.792803,33.689515,-117.790243,33.691675&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Sample returned features (the test address block, Tract 8690):
- APN=45121312 (451-213-12)  TRACT=8690 LOT=41 PA=11
- APN=45121311 (451-213-11)  TRACT=8690 LOT=42 PA=11
- APN=45121310 (451-213-10)  TRACT=8690 LOT=43 PA=11

Resolver note: `_prop(props, "APN", ...)` matches this field directly (cast int ->
string, zero-pad to 8, then optionally dash). No situs -> `SitusFullAddress` lookup
returns None -> stored as null (same handling as San Jose layer 49).

---

## 2. Zoning (zone code polygons) -- VERIFIED

Official City of Irvine Zoning layer. Irvine uses MASTER-PLAN / PLANNING-AREA zoning:
the "zone code" is a numeric master-plan designation (e.g. `2.2`), not a conventional
alphanumeric code like `R-1`. Each polygon carries a plain-language description and a
direct Municode section link.

- Layer base: `https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/7`
- Layer name / id: `Zoning` / **7**
- Query URL:
  `https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/7/query`
- Zone code field: **`ZONING`** (master-plan code string, e.g. `2.2`, `1.5`, `6.1`).
  Use `ZONING` as `zone_code`.
- Other fields: **`DESCRIPTION`** (e.g. `Low Density Residential`, `Recreation`,
  `Institutional`), **`PLANAREA`** / `PA_NO` (Planning Area number, joins to parcel
  `PA`), `WEBCODE` (top-level category integer, e.g. 2 = residential family), `LABEL`,
  `URL` (per-zone Municode citation link), `GEOCODE`.
- Geometry: `esriGeometryPolygon`.

Live test (HTTP 200, **6** zoning polygons around the test point):

    curl -s "https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/7/query?geometry=-117.792803,33.689515,-117.790243,33.691675&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=true&f=geojson"

Zone codes returned: `2.2` (Low Density Residential -- the test parcel's zone), `1.5`
(Recreation), `6.1` (Institutional). Confirms the master-plan zone-code field name and
polygon geometry. The `2.2` polygon carries
`URL=https://library.municode.com/ca/irvine/codes/zoning?nodeId=ZOOR_DIV3GEDESTLAUSRE_CH3-37ZODILAUSREDEST_S3-37-132.2LODERE`.

Resolver note: the LA-scoped `_cache_zoning` reads `ZONE_CLASS/ZONE_CMPLT`; for Irvine
it must read `ZONING` (code) and `DESCRIPTION` (name). ADU rules key off the master-plan
family, i.e. any residential `ZONING` (categories 2.x low/medium/high density
residential, and mixed-use / PD areas that permit single-family), not off `R-1`-style
codes. Store `PLANAREA` too -- Irvine standards can vary by Planning Area.

---

## 3. City boundary polygon (point -> jurisdiction) -- VERIFIED

The `OnlineParcel` service is single-jurisdiction (City of Irvine only), so its City
Boundary layer holds exactly ONE polygon = the Irvine city limits. No name filter is
needed; select with `where=1=1`.

- Layer base: `https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/0`
- Layer name / id: `City Boundary` / **0**
- Where filter: **`1=1`** (single-feature layer; there is no city-name field to match on)
- Fields: `CITYBNDRY`, `OBJECTID`, `SHAPE.STArea()`.
- Geometry: `esriGeometryPolygon`.

Live test (HTTP 200, **1** feature; `SHAPE.STArea()` ~= 1.839e9 sq ft ~= 65.9 sq mi,
matching Irvine's ~66 sq mi):

    curl -s "https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&f=geojson"

If a multi-city county boundary layer is preferred for consistency with the other
jurisdictions, the Orange County boundaries service can be substituted later; the City
single-feature layer above is authoritative and sufficient for point-in-polygon.

---

## 4. Optional situs source (Orange County parcels) -- VERIFIED

The City parcel layer (section 1) has APN + geometry but NO address. Orange County's
official public GIS (`ocgis.com`, OC Public Works) serves a parcel layer with a site
address plus a dashed APN, and responds to the same envelope query. Use it only to
enrich `situs_address`; keep the City layer as the authoritative parcel/geometry source.

- Layer base: `https://www.ocgis.com/arcpub/rest/services/Map_Layers/Parcels/MapServer/0`
- Query URL:
  `https://www.ocgis.com/arcpub/rest/services/Map_Layers/Parcels/MapServer/0/query`
- Fields: **`SITE_ADDRESS`** (e.g. `47 FOXHILL IRVINE`), **`ASSESSMENT_NO`** (dashed
  APN, e.g. `451-241-13`), `YEAR_BUILT`, `NBR_BEDROOMS`.

Live test (HTTP 200, **58** features; f=json):

    curl -s "https://www.ocgis.com/arcpub/rest/services/Map_Layers/Parcels/MapServer/0/query?geometry=-117.792803,33.689515,-117.790243,33.691675&geometryType=esriGeometryEnvelope&inSR=4326&outSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false&f=json"

Join key: City `APN` int `45124113` <-> County `ASSESSMENT_NO` `451-241-13`
(strip dashes to match, or add dashes to the City value).

---

## 5. ADU / JADU ordinance and rule values

Citation: **City of Irvine Zoning Ordinance, Division 2 (Additional Standards for Uses),
Chapter 3-26 "Accessory Dwelling Units"** (ADU Ordinance No. 18-05, adopted 04/24/2018).
Section map (from the HCD review letter, which quotes each subsection verbatim):
3-26-1 Definitions; 3-26-3 Residential Zoning applicability; 3-26-4 Review Timelines;
3-26-5 Zoning / Objective / Setback / Size / Height standards; 3-26-7 misc.

- Municode (zoning code root): `https://library.municode.com/ca/irvine/codes/zoning`
- HCD findings letter (2025-01-07), non-compliance review of Ord. 18-05 under Gov Code
  66310-66342: `https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/ordinance-review-letters/irvine-adu-findings-010725.pdf`
- HCD technical-assistance letter (2025-03-27):
  `https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/ordinance-review-letters/irvine-adu-ta-032725.pdf`

CRITICAL COMPLIANCE STATUS (drives the values below): HCD reviewed Ordinance 18-05 and
found it NON-COMPLIANT with State ADU/JADU Law on ~12 points. Per HCD's March 2025
technical-assistance letter, "the City has not amended Ordinance No. 18-05 and ... instead
intend[s] to use State ADU Law." Therefore the enforceable Irvine standards ARE the CA
state baselines (Gov Code 66310-66342 / former 65852.2, .22, .26); the local numeric
caps in Chapter 3-26 that are more restrictive have been superseded. Each value below is
the controlling state baseline, annotated with the specific Chapter 3-26 subsection it
replaces. This is not "inventing" a local value -- it is the state floor the City is on
record as applying directly.

Rule field values (controlling value + superseded local subsection + state citation):

- **max_height_detached_standard_ft** = 16. State floor, Gov 66321(b)(4)(A): a detached
  ADU on a single-/multi-family lot must be allowed at least 16 ft (18 ft if within 1/2
  mile of major transit or on a multistory multifamily lot, Gov 66321(b)(4)(B)-(C), plus
  up to 2 ft extra for matching roof pitch). SUPERSEDES local Irvine ZO 3-26-5 6.f., which
  capped detached ADUs at one story and 15.5 ft -- HCD flagged this as non-compliant.
  Store 16 as the guaranteed standard; the true cap can be higher (up to the base
  Planning-Area height for attached / above-garage ADUs, Gov 66321(b)(4)(D)).
- **side_rear_setback_min_ft** = 4. State ceiling, Gov 66314(d)(7): no more than a 4 ft
  side/rear setback may be required for new-construction ADUs; 0 ft for conversions /
  same-footprint rebuilds; and no setback that would block an 800 sq ft ADU
  (Gov 66321(b)(3)). SUPERSEDES local ZO 3-26-5 5. / 6.e., which required a 5 ft
  side/rear setback and the underlying-zone setbacks -- HCD flagged the >4 ft requirement
  as non-compliant. Use 4 ft for the feasibility envelope.
- **owner_occupancy_required_adu** = false. Gov 66315: for an ADU on a lot with a
  proposed/existing single-family dwelling, no owner-occupancy or deed-restriction
  requirement is permitted (only a >=30-day minimum rental term may be imposed).
  SUPERSEDES local ZO 3-26-4 3. / 3-26-5, which required the applicant to be an
  owner-occupant and recorded deed restrictions -- HCD flagged both as prohibited.
- **owner_occupancy_required_jadu** = true. Gov 66333(b): the owner must reside in either
  the primary dwelling or the JADU (government agencies, land trusts, and qualified
  housing orgs exempt). State baseline; Irvine has no compliant local variation.
- **jadu_allowed** = true. Gov 66323(a): the City must ministerially approve one ADU AND
  one JADU per lot with a proposed/existing single-family dwelling. HCD found Ord. 18-05
  must be revised to allow the full ADU+JADU unit mix (and JADUs in townhomes, which the
  City had wrongly disallowed). JADU: within the walls of the existing dwelling, 150-500
  sq ft (Gov 66333).
- **parking_required** = false (general). Gov 66314(d): no parking may be required for an
  ADU that is within 1/2 mile walking distance of transit, part of the existing primary
  dwelling/accessory structure, in an architecturally/historically significant district,
  when on-street permits are not offered to the ADU, or within one block of a car-share.
  Where none of these apply, up to 1 space (per ADU or per bedroom) may be required; local
  ZO 3-26-5 3.b caps required parking at 1 space per bedroom. Treat as false with a
  "not-near-transit -> up to 1 space" conditional flag.
- **permit_review_days** = 60. Gov 66317(a): the permitting agency must approve or deny a
  complete ADU/JADU application within 60 days (ministerial), else deemed approved.
  SUPERSEDES local ZO 3-26-4, which stated 120 days -- HCD flagged the 120-day timeline as
  non-compliant.
- **max_size_sqft_general_cap** = 1200. Gov 66314(d)(5): a detached ADU may not be capped
  below 1,200 sq ft; attached ADUs at 50% of the primary dwelling (Gov 66314(d)(4)); and
  an 800 sq ft ADU must always be allowed regardless of FAR/coverage/lot-size limits
  (Gov 66321(b)(3)). SUPERSEDES local ZO 3-26-5 6.d.2, which limited ADUs to 50% of the
  primary's livable area or a smaller lot-size table -- HCD flagged this as non-compliant.
- **fire_sprinkler_trigger** = false. Gov 66314(d)(12): an ADU is not required to have
  sprinklers if the primary dwelling is not required to, AND construction of the ADU does
  not trigger a sprinkler requirement in the existing primary dwelling. Local ZO 3-26-5
  had the first half but lacked the "does not trigger in the primary" clause -- HCD
  required it added. Effective value: false / not-triggered.

State-baseline reconciliation: every value above is the CA state floor/ceiling, adopted
because Irvine's Chapter 3-26 numerics were found non-compliant and the City applies State
ADU Law directly (per HCD). None are MORE restrictive than the PRODUCT_SPEC CA baselines
(heights >= floors, setback == 4 ft ceiling, review <= 60 days, no ADU owner-occupancy,
sprinklers not triggered, size cap up to 1,200). Nothing was invented; where the local
value diverged it was superseded by the cited Gov Code section, and where the local value
was simply absent (JADU owner-occupancy) the state baseline was used.

Additional notes for the rule engine:
- Irvine ADU standards are administered through the Planning Area master plans; store the
  parcel `PA` / zoning `PLANAREA` so Planning-Area-specific development standards can be
  layered in later.
- ADUs are permitted on any lot zoned to allow single-family or multifamily residential
  use (Gov 66314; HCD required Irvine to stop limiting to single-family). Key on the
  residential `ZONING` families (2.x) plus mixed-use / PD areas allowing dwellings.
- Re-verify Chapter 3-26 text if/when Irvine finally amends Ord. 18-05; until then the
  state-baseline mapping above is the correct enforceable rule set.

---

## Wiring cheat-sheet (copy-paste field map)

| Layer    | query_url | id | key field(s) |
|----------|-----------|----|--------------|
| Parcel   | https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/4/query | 4 | APN (int, 8-digit -> dash to 451-213-12); PA; no situs |
| Zoning   | https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/7/query | 7 | ZONING (master-plan code, e.g. 2.2); DESCRIPTION; PLANAREA |
| Boundary | https://gis.cityofirvine.org/arcgis/rest/services/OnlineParcel/MapServer/0/query | 0 | single feature (where 1=1) |
| Situs (OC, optional) | https://www.ocgis.com/arcpub/rest/services/Map_Layers/Parcels/MapServer/0/query | 0 | SITE_ADDRESS; ASSESSMENT_NO (dashed APN) |

All City layers respond to `f=geojson`, `inSR=4326`, `outSR=4326`,
`geometryType=esriGeometryEnvelope`, and `outFields=*`. verify_ssl: true for all
`gis.cityofirvine.org` and `www.ocgis.com` layers; default timeout is fine (parcel ~1.7s,
zoning ~0.3s). Flip `coverage_status='production'` only after the section-5 rules are
ingested + verified.

Sources:
- City parcel/zoning/boundary services: gis.cityofirvine.org OnlineParcel MapServer (verified via curl, 2026-07-21)
- OC County parcels: www.ocgis.com Map_Layers/Parcels (verified via curl, 2026-07-21)
- Irvine ZO Chapter 3-26 sections + controlling Gov Code: HCD findings letter 2025-01-07 and technical-assistance letter 2025-03-27 (URLs above)
- Municode Irvine zoning code: https://library.municode.com/ca/irvine/codes/zoning
