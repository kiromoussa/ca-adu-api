# Architecture

This document is retired. It described the pre-pivot "CA ADU Zoning API" (a
weekly scraper plus LLM extraction pipeline feeding tiered, Stripe-billed REST
endpoints for 8 cities). That product has been superseded.

The current product is a deterministic address-level ADU feasibility API. For the
authoritative architecture see:

- `docs/adr/0001-architecture.md` - the current architecture decision record.
- `docs/PRODUCT_SPEC.md` - the product spec.
- `docs/DEPLOYMENT_STATUS.md` - live deployment status and runbook.

Code layout for the current system: `services/` (core feasibility engine and
API), `ingestion/` (source data loaders), `portal/` (frontend), and
`supabase/migrations/` (schema).
