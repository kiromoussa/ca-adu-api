# ADU Atlas API - Product Spec (authoritative)

Self-serve, developer-facing California parcel feasibility API for ADUs, JADUs,
and SB 9 preliminary analysis. NOT a municipal-code scraper. The paid product is
a fast, deterministic, source-cited, address-level preliminary feasibility result
a PropTech/architect/RE/lender workflow or AI agent can call programmatically.

Core promise: "Send an address and proposed ADU project. Receive a source-cited,
timestamped preliminary feasibility result: parcel/zoning context, ADU/JADU/SB 9
rules, setback/height/size constraints, hazard/overlay flags, assumptions,
confidence, and official-source citations."

Coverage: Los Angeles City first, fully working. Architecture supports San Diego,
San Jose, San Francisco, Sacramento, Irvine, Long Beach, Oakland. A city is
`production` only after its sources + rules are ingested, tested, and verified.

Project types: detached_adu, attached_adu, garage_conversion, jadu, sb9_duplex,
sb9_urban_lot_split.

Distribution: RapidAPI first; public OpenAPI docs / portal second. Self-serve only.

## NON-NEGOTIABLE TRUST / LEGAL

1. Every substantive result field carries provenance: source_url, source_title,
   source_section or source_layer, retrieved_at, last_verified_at,
   confidence (high|medium|low), data_status (current|stale|needs_review|unavailable).
2. Never say "permit approved", "legal to build", "guaranteed", or a final yes/no.
   Use feasibility_status: likely_feasible | likely_constrained |
   needs_professional_review | insufficient_data.
3. Every response includes the disclaimer verbatim:
   "This is preliminary informational zoning and GIS analysis, not legal,
   architectural, surveying, engineering, title, environmental, or permit advice.
   Verify all results with the applicable jurisdiction and qualified
   professionals before making decisions or spending money."
4. Preserve raw source snapshots + hashes for every scraped code section and GIS
   layer metadata. Never overwrite history (immutable source_snapshots).
5. State-law baseline validation is explicit. Local data more restrictive than
   current state law -> compliance_flag needs_review /
   possibly_more_restrictive_than_state_baseline; preserve local source; do not
   infer the local rule is invalid.
6. NO LLM at API request time for core legal/geospatial determinations. Request
   path = versioned structured rules + deterministic calculations + source-linked
   data. LLMs only offline for extraction candidates/summaries/QA; human/source
   validation still required.

## STATE-LAW BASELINES (seed state_rule_baselines, California, with citations)

- max_height_detached_standard_ft: floor 16 (AB 2221)
- max_height_near_transit_ft: floor 18 (AB 2221/SB 897)
- max_height_multifamily_lot_ft: floor 18 (AB 2221)
- max_height_attached_ft: ceiling 25 or zone limit whichever lower (AB 2221)
- side_rear_setback_min_ft: ceiling 4 (AB 2221)
- front_setback_restriction: cannot block ADU <800 sqft (AB 2221)
- owner_occupancy_required_adu: must be false (Gov Code 66315/66323)
- owner_occupancy_required_jadu: conditional on shared sanitation (Gov 66333(b))
- jadu_allowed: true, 1 per SFD lot (Gov 66333)
- jadu_separate_sale_allowed: false (Gov 66333(c)(1))
- parking_required: false near transit/historic/etc (SB 897)
- demolition_permit_concurrent: true (SB 897)
- permit_review_days: <=60 (SB 897/AB 2221)
- fire_sprinkler_trigger: false (SB 897)
- impact_fee_exempt_sqft_threshold: 750 (AB68/SB13)
- max_size_sqft_1br: >=850 ; max_size_sqft_2br: >=1000 ; max_size_sqft_general_cap: up to 1200
- nonconforming_zoning_denial_allowed: false (SB 897)
- pre_2018_unpermitted_adu_amnesty: true (SB 897)
- sb9_duplex_ministerial: true in SF zones/urbanized (SB 9, Gov 65852.21)
- sb9_lot_split_min_lot_sqft: 1200 ; sb9_lot_split_ratio: 0.4 (60/40) ; sb9_one_split_per_owner: true (SB 9)

## DATA SOURCES (track exact endpoint/layer + license notes in source_registry)

Municipal code: LA American Legal LAMC
https://codelibrary.amlegal.com/codes/los_angeles/latest/lamc/0-0-0-422835 ;
San Diego American Legal + docs.sandiego.gov ; San Jose Municode Title 20 ;
SF American Legal Planning Code ; Sacramento American Legal Title 17 ; Irvine
Municode Title 5 ; Long Beach Municode Title 21 ; Oakland Municode Planning Code.

LA City GIS: ZIMAS ArcGIS REST
https://zimas.lacity.org/arcgis/rest/services/zma/zimas/MapServer
(Do NOT use unincorporated LA County zoning as a substitute for LA City.)

State validation: HCD ADU Handbook https://www.hcd.ca.gov/building-standards/adu/handbook ;
HCD ADU landing https://www.hcd.ca.gov/building-standards/adu ; HCD ordinance review letters.

Risk layers: FEMA NFHL https://www.fema.gov/flood-maps/national-flood-hazard-layer ;
CAL FIRE/OSFM FHSZ https://data.ca.gov/dataset/fire-hazard-severity-zone-viewer1 ;
CA statewide zoning (bootstrap only, local wins)
https://lab.data.ca.gov/dataset/california-statewide-zoning-north .

ArcGIS REST client must support: service metadata ?f=pjson, /layers?f=pjson,
/query?where=...&outFields=*&returnGeometry=true&f=geojson, pagination, retries,
rate limits, caching, ETag/Last-Modified, source metadata persistence.
For code publishers reuse the proven approach: American Legal via curl_cffi
(impersonate chrome) + /api/render-doc/{client}/{version}/{code}/{docid}/ (bypasses
Cloudflare); Municode via Playwright render.

## DATABASE (Supabase Postgres + PostGIS; UUID PKs, timestamps, RLS, FKs, checks, indexes)

16 tables (exact fields in the user's spec; implement all): jurisdictions,
source_registry, source_snapshots (immutable/versioned), zoning_sections,
state_rule_baselines, zoning_rules, rule_attributes (per-field provenance),
parcels (geom MultiPolygon 4326 + centroid Point 4326), zoning_districts (geom),
overlay_features (geom Geometry 4326; overlay_type flood|fire|historic|coastal|
hillside|environmental|hpoz|other), property_analyses, analysis_findings,
ingest_runs, qa_issues, api_usage_events (privacy-minimized), changelog_entries.
GIST indexes on all geometry columns; B-tree on lookup paths (apn, slug, zone_code,
project_type, request_fingerprint). Never expose service role key in frontend.

## SPATIAL / FEASIBILITY (deterministic + tested)

A. address -> jurisdiction (normalize, geocode to point, boundary test; insufficient_data if unsure)
B. parcel lookup (ST_Contains/ST_Intersects, documented tolerance; APN+geom+source+date; never approximate as exact)
C. zoning lookup (spatial join parcel/centroid to zoning district; capture cross-zone ambiguity; zone code/name + layer source + timestamp)
D. overlay lookup (intersect flood/fire/historic/coastal/hillside; preserve raw ids/values; distinguish "no hit" from "source unavailable")
E. rule engine (select jurisdiction+zone+project_type; merge state baseline + local WITHOUT overwriting provenance; condition-by-condition explanation + source links)
F. preliminary envelope (LA V1 only, after parcel/zoning reliable; setback buffers via PostGIS, correct m<->ft; label "approximate conceptual envelope"; if front/side/rear orientation unknown -> limitation/needs_review, no fake precision; never claim easements/slopes/utilities/trees/HOA/title/survey unless authoritative data integrated)

## API (OpenAPI 3.1 first; keep implementation aligned). Base /v1

- POST /feasibility  {address*, project_type*(enum), target_sqft?, bedrooms?, proposed_height_ft?, existing_structure?, options?}
  -> analysis_id, request summary, coverage/jurisdiction, parcel context (only fields found),
     zoning context, feasibility_status, score (only if explainable else omit), eligible paths
     (ADU/JADU/SB9 with status), development constraints (height/size/setbacks/parking/owner
     occupancy/permit timeline/fees), overlay findings, approximate envelope (only where supported),
     assumptions, limitations, sources+per-field provenance, freshness/analysis version, disclaimer.
  Idempotency-Key header supported on POST.
- GET /jurisdictions -> coverage status, supported project types, source update date
- GET /jurisdictions/{slug}/rules -> citywide/zone rules, citations, version history
- GET /analyses/{analysis_id} -> authenticated if private; else public shareable-token route
- GET /changelog -> public update history by city
- GET /health -> uptime + non-sensitive source freshness

Strict JSON schemas (Pydantic), consistent error envelope, idempotency, request
limits/timeouts/retries, API versioning, no raw internal errors, fast responses
(cache + queued enrichment). Publish curl/TS/Python/JS examples.

## RAPIDAPI

Handle X-RapidAPI-Key / X-RapidAPI-Host; verify via expected gateway pattern (not
obscurity). Billable unit = one completed address-level feasibility analysis (one
address + one project_type). Meter only successful completed analyses (not errors
or unsupported-coverage). Plan-aware quotas from gateway when available + fallback
internal limiter. Same-customer identical inputs within 24h = cache hit, not
double-billed. Plans config-driven in config/plans.yaml:
- BASIC free 3/mo hard cap ; PRO $25 50/mo ; ULTRA $75 250/mo ; MEGA $150 750/mo.
- No paid overages in v1. Produce a RapidAPI listing package (title, descriptions,
  categories, tags, FAQs, pricing copy, endpoint docs, response examples, logo
  requirements, support policy).

## STYLE
No emojis. No em dashes (use a hyphen). cursor: pointer on portal buttons/links.
