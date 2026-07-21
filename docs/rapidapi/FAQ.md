# ADU Atlas API - FAQ (RapidAPI listing)

Copy each question/answer pair into the RapidAPI "FAQ" section as a separate
entry.

---

**What does this API return - a final legal answer on whether I can build an
ADU?**

No. ADU Atlas returns a preliminary informational zoning and GIS analysis,
not legal, architectural, surveying, engineering, title, environmental, or
permit advice. The response never says "approved", "legal to build", or
"guaranteed". It returns a `feasibility_status` of `likely_feasible`,
`likely_constrained`, `needs_professional_review`, or `insufficient_data`,
and every response carries this disclaimer verbatim: "This is preliminary
informational zoning and GIS analysis, not legal, architectural, surveying,
engineering, title, environmental, or permit advice. Verify all results with
the applicable jurisdiction and qualified professionals before making
decisions or spending money." Always verify with the applicable jurisdiction
and a qualified professional before spending money.

---

**Which cities are actually supported right now?**

Los Angeles City is the v1 target and the only jurisdiction that returns a
billable feasibility result today. San Diego, San Jose, San Francisco,
Sacramento, Irvine, Long Beach, and Oakland are registered so you can build
against them, but calls for those cities return `unsupported_coverage`
(HTTP 422, not billed) until each city's source registry, GIS layers, and
rule set are ingested, tested, and marked production-ready. Call
`GET /jurisdictions` at request time to check live coverage status -
do not hardcode which cities are supported.

---

**Does this API use an LLM to answer my request?**

No. The request path (everything behind `POST /feasibility` and the GET
endpoints) is fully deterministic: versioned structured rules, PostGIS
spatial joins, and source-linked data only. Large language models are used
only offline, to generate extraction candidates from municipal code text and
to flag items for human/source QA before they are ever published as a
verified rule. No LLM output reaches your response unverified.

---

**What exactly counts as a billable request?**

A billable unit is one completed address-level feasibility analysis: one
address plus one project_type that resolves to a terminal
`feasibility_status`. Authentication errors, validation errors (400),
unsupported-coverage responses (422), quota-exceeded and rate-limited
responses (429), and server errors (5xx) are never billed. If you call the
same address and project_type again within 24 hours, you get the cached
result and are not billed again. See the Pricing tab for full detail.

---

**How do I avoid being double-charged if my client retries a request?**

Send an `Idempotency-Key` header (any string, up to 255 characters) on your
`POST /feasibility` call. A repeated key with an identical request body
returns the original stored result at no additional cost. A repeated key
with a different request body returns `409 idempotency_key_conflict` and is
not billed.

---

**What does every response include for sourcing / trust?**

Every substantive field in a feasibility response carries provenance:
`source_url`, `source_title`, `source_section` (municipal code) or
`source_layer` (GIS service), `retrieved_at`, `last_verified_at`,
`confidence` (`high`/`medium`/`low`), and `data_status`
(`current`/`stale`/`needs_review`/`unavailable`). A top-level `sources`
array lists every distinct source used. Local zoning values are also
compared against the current California state-law baseline (AB 2221,
SB 897, SB 9) and flagged with a `compliance_flag` if the local rule is more
restrictive than state law - the local source is always preserved, never
silently overridden.

---

**What is the "approximate conceptual envelope" and can I trust its exact
square footage?**

It is an approximate buildable-area estimate computed by buffering the
parcel polygon inward by the applicable setbacks in PostGIS, available for
Los Angeles in v1 only. Set `"options": {"include_envelope": true}` in your
request to receive it - it is not computed by default. It is explicitly
labeled `"approximate conceptual envelope"` and is not a survey. If the
parcel's front/side/rear orientation cannot be determined from GIS data,
the envelope is downgraded with a `limitations` entry rather than reporting
false precision. It never asserts easements, slopes, utilities, trees, HOA
covenants, or title facts.

---

**What request/response fields do I need at minimum?**

`address` (a normal mailing address string) and `project_type` (one of
`detached_adu`, `attached_adu`, `garage_conversion`, `jadu`, `sb9_duplex`,
`sb9_urban_lot_split`). Everything else - `target_sqft`, `bedrooms`,
`proposed_height_ft`, `existing_structure`, `options` - is optional and
sharpens the result when supplied. See `openapi/examples/` for full
copy-paste requests in curl, TypeScript, Python, and JavaScript.

---

**Can I share a result with someone who does not have an API key?**

Yes, on Pro, Ultra, and Mega plans. A completed analysis can carry a
`share_token`; anyone with `GET /analyses/{analysis_id}?token=<token>`
can retrieve the read-only result with no API credentials. This lookup is
never billed.

---

**How fresh is the underlying zoning and GIS data?**

Check `GET /health` for non-sensitive freshness per source, and
`GET /jurisdictions/{slug}/rules` for the rule-set version history for a
specific jurisdiction. Each result also carries `freshness.data_as_of`, the
newest `last_verified_at` timestamp across the sources actually used for
that analysis. `GET /changelog` is the public, per-city update history.

---

**What happens if you get a rule wrong?**

Report it through support with the `analysis_id` (or the jurisdiction slug
and zone) and the source you believe is authoritative. Verified corrections
are published and appear in `GET /changelog` with
`change_type: correction`. Raw source snapshots are immutable and versioned,
so every past analysis result remains reproducible even after a correction.
