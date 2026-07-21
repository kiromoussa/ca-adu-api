# ADU Atlas API - RapidAPI pricing copy

Source of truth: `config/plans.yaml`. If that file changes, update this
document to match; do not let the two drift. All prices are USD, billed
monthly, no annual plans in v1.

## Billable unit (exact wording, use verbatim in the "Pricing" tab intro)

```
Billable unit: one completed address-level feasibility analysis - one
address combined with one project_type that resolves to a terminal
feasibility_status (likely_feasible, likely_constrained,
needs_professional_review, or insufficient_data).

Only successful, completed analyses are metered. Errors and
unsupported-coverage responses are never billed: authentication failures,
validation errors, quota-exceeded responses, rate-limited responses,
unsupported-coverage responses (jurisdiction not yet production), and
server errors all return without consuming a unit of your plan.

Same-customer requests with identical inputs (address, project_type, and
optional fields) within 24 hours are served from cache and are not billed a
second time. You may also supply an Idempotency-Key header to safely retry a
request without risk of double-billing; a repeated key with an identical
body returns the stored result, and a repeated key with a different body is
rejected with a 409 rather than silently billed twice.

There are no paid overages in v1. Once a plan reaches its monthly quota,
requests return 429 (quota_exceeded) until the next calendar-month reset or
until you upgrade.
```

## Plan tiers

### BASIC - Free

- **Price:** $0 / month
- **Monthly quota:** 3 completed feasibility analyses (hard cap, no overage)
- **Rate limit:** 10 requests/minute
- **Includes:** feasibility analysis, jurisdiction rules lookup, changelog
- **Does not include:** shareable public analysis links, priority support

```
Free tier for evaluation. 3 completed feasibility analyses per month, hard
capped at 3 with no overage path. Full read access to jurisdiction coverage,
rules, and changelog endpoints (these are never billed). Ideal for trying
the API against a handful of real addresses before committing to a paid
plan.
```

### PRO - $25/month

- **Price:** $25 / month
- **Monthly quota:** 50 completed feasibility analyses (hard cap, no overage)
- **Rate limit:** 30 requests/minute
- **Includes:** feasibility analysis, jurisdiction rules lookup, changelog,
  shareable public analysis links
- **Does not include:** priority support

```
50 completed feasibility analyses per month for individual developers and
small teams building a first ADU/JADU/SB 9 feature. Adds shareable public
analysis links (mint a token and share a read-only result with a client or
homeowner with no API key required). No overages in v1: additional requests
past 50/month return 429 until your next billing cycle.
```

### ULTRA - $75/month

- **Price:** $75 / month
- **Monthly quota:** 250 completed feasibility analyses (hard cap, no overage)
- **Rate limit:** 60 requests/minute
- **Includes:** feasibility analysis, jurisdiction rules lookup, changelog,
  shareable public analysis links, priority support

```
250 completed feasibility analyses per month for growing PropTech, real
estate, and lending workflows running feasibility checks across a pipeline
of properties. Includes priority support (target: 1 business day response).
No overages in v1.
```

### MEGA - $150/month

- **Price:** $150 / month
- **Monthly quota:** 750 completed feasibility analyses (hard cap, no overage)
- **Rate limit:** 120 requests/minute
- **Includes:** feasibility analysis, jurisdiction rules lookup, changelog,
  shareable public analysis links, priority support

```
750 completed feasibility analyses per month for high-volume integrations
and platforms embedding feasibility checks into their own product. No
overages in v1; contact support@aduatlas.example.com for custom volume
above 750/month before your workflow hits the monthly cap.
```

## Comparison table (for the Hub pricing grid)

| | BASIC | PRO | ULTRA | MEGA |
|---|---|---|---|---|
| Price/month | $0 | $25 | $75 | $150 |
| Completed analyses/month | 3 | 50 | 250 | 750 |
| Overages | None | None | None | None |
| Rate limit | 10/min | 30/min | 60/min | 120/min |
| Jurisdiction rules + changelog | Included | Included | Included | Included |
| Shareable public analysis link | No | Yes | Yes | Yes |
| Priority support | No | No | Yes | Yes |

## Metering and quota behavior (for the "How it's billed" field)

```
Quota resets on the 1st of each calendar month at 00:00 UTC. RapidAPI
gateway quota headers are the primary source of truth; ADU Atlas also
tracks usage internally as a fallback so quota is enforced even if a gateway
header is momentarily unavailable. A short-window burst limiter also
applies on top of the monthly quota on every plan (see rate limit above) to
protect against accidental request loops; a burst-limited response is not
billed either.
```
