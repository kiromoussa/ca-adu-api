import Link from "next/link";
import { PRICING_TIERS } from "@/lib/pricing";

const CITIES = [
  "Los Angeles",
  "San Diego",
  "San Francisco",
  "Sacramento",
  "San Jose",
  "Irvine",
  "Long Beach",
  "Oakland"
];

const ENDPOINTS = [
  {
    method: "GET",
    path: "/v1/adu-rules?city=los_angeles&zone=R1",
    blurb: "Structured, state-law-validated ADU rules for a city and zone district."
  },
  {
    method: "GET",
    path: "/v1/cities",
    blurb: "The 8 covered California cities, publishers, and last-scraped timestamps."
  },
  {
    method: "GET",
    path: "/v1/compliance-flags?city=oakland",
    blurb: "Per-field compliance flags: compliant, more_restrictive, or needs_review."
  }
];

const DIFFERENTIATORS = [
  {
    title: "Narrow",
    body: "California ADU and housing-density zoning only. We go deep on the codes that actually block or permit a build."
  },
  {
    title: "State-law-validated",
    body: "Every numeric and boolean field is checked against AB 2221, SB 897, SB 9, and Gov. Code 66310-66342 floors and ceilings."
  },
  {
    title: "Cheap and flat",
    body: "Plans start at $0 and top out at $49/mo. Overage is a flat $0.02 per lookup - no cliff pricing."
  }
];

function ExampleResponse() {
  const json = `{
  "city": "los_angeles",
  "zone_district": "R1",
  "max_height_detached_standard_ft": 16,
  "side_rear_setback_min_ft": 4,
  "front_setback_restriction": false,
  "owner_occupancy_required_adu": false,
  "jadu_allowed": true,
  "parking_required": false,
  "permit_review_days": 60,
  "compliance_flag": "compliant"
}`;
  return (
    <pre className="overflow-x-auto rounded-lg border border-surface-border bg-ink p-4 text-xs leading-relaxed text-slate-100">
      <code>{json}</code>
    </pre>
  );
}

export default function HomePage() {
  return (
    <div>
      {/* Hero */}
      <section className="border-b border-surface-border bg-white">
        <div className="mx-auto grid max-w-6xl gap-10 px-6 py-16 lg:grid-cols-2 lg:items-center">
          <div>
            <span className="inline-block rounded-full border border-surface-border bg-surface-muted px-3 py-1 text-xs font-medium text-ink-soft">
              8 California cities - validated against state law
            </span>
            <h1 className="mt-4 text-4xl font-bold tracking-tight text-ink sm:text-5xl">
              ADU zoning rules as clean, verifiable JSON.
            </h1>
            <p className="mt-4 max-w-xl text-lg text-ink-soft">
              A developer API that maps accessory dwelling unit and housing-density
              zoning codes for the biggest California cities into structured,
              state-law-validated fields. Query a city and zone, get the rules that
              decide whether a build is allowed.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link
                href="/dashboard"
                className="rounded-md bg-brand px-5 py-2.5 font-medium text-white hover:bg-brand-dark no-underline"
              >
                Get an API key
              </Link>
              <Link
                href="/docs"
                className="rounded-md border border-surface-border bg-white px-5 py-2.5 font-medium text-ink hover:bg-surface-muted no-underline"
              >
                Read the docs
              </Link>
            </div>
          </div>
          <ExampleResponse />
        </div>
      </section>

      {/* Differentiators */}
      <section className="mx-auto max-w-6xl px-6 py-14">
        <div className="grid gap-6 md:grid-cols-3">
          {DIFFERENTIATORS.map((d) => (
            <div key={d.title} className="rounded-xl border border-surface-border bg-white p-6">
              <h3 className="text-lg font-semibold text-ink">{d.title}</h3>
              <p className="mt-2 text-sm text-ink-soft">{d.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Endpoints */}
      <section className="border-y border-surface-border bg-white">
        <div className="mx-auto max-w-6xl px-6 py-14">
          <h2 className="text-2xl font-bold text-ink">Three endpoints, everything you need</h2>
          <p className="mt-2 text-ink-soft">
            REST over HTTPS, JSON responses, API-key auth with per-tier monthly quotas.
          </p>
          <div className="mt-6 space-y-3">
            {ENDPOINTS.map((e) => (
              <div
                key={e.path}
                className="flex flex-col gap-2 rounded-lg border border-surface-border p-4 sm:flex-row sm:items-center sm:gap-4"
              >
                <span className="inline-flex w-fit items-center rounded bg-brand/10 px-2 py-0.5 font-mono text-xs font-semibold text-brand-dark">
                  {e.method}
                </span>
                <code className="font-mono text-sm text-ink">{e.path}</code>
                <span className="text-sm text-ink-soft sm:ml-auto sm:text-right">{e.blurb}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Coverage */}
      <section className="mx-auto max-w-6xl px-6 py-14">
        <h2 className="text-2xl font-bold text-ink">Coverage</h2>
        <p className="mt-2 text-ink-soft">
          Sourced from the official municipal code publishers and refreshed on a
          weekly scrape, then cross-checked against HCD findings.
        </p>
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {CITIES.map((c) => (
            <div
              key={c}
              className="rounded-lg border border-surface-border bg-white px-4 py-3 text-sm font-medium text-ink"
            >
              {c}
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="border-t border-surface-border bg-white">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-bold tracking-tight text-ink">Simple, flat pricing</h2>
            <p className="mt-2 text-ink-soft">
              Start free. Upgrade for all 8 cities and change alerts. Overage is a
              flat $0.02 per lookup with no pricing cliff.
            </p>
          </div>
          <div className="mt-8 grid gap-6 lg:grid-cols-4">
            {PRICING_TIERS.map((tier) => (
              <div
                key={tier.id}
                className={`flex flex-col rounded-xl border p-6 ${
                  tier.highlighted
                    ? "border-brand ring-1 ring-brand"
                    : "border-surface-border"
                }`}
              >
                {tier.highlighted ? (
                  <span className="mb-3 w-fit rounded-full bg-brand px-2.5 py-0.5 text-xs font-semibold text-white">
                    Most popular
                  </span>
                ) : null}
                <h3 className="text-lg font-semibold text-ink">{tier.name}</h3>
                <div className="mt-2 flex items-baseline gap-1">
                  <span className="text-3xl font-bold text-ink">{tier.price}</span>
                  {tier.cadence ? (
                    <span className="text-sm text-ink-soft">{tier.cadence}</span>
                  ) : null}
                </div>
                <p className="mt-2 text-sm text-ink-soft">{tier.tagline}</p>
                <ul className="mt-4 flex-1 space-y-2 text-sm text-ink">
                  {tier.features.map((f) => (
                    <li key={f} className="flex items-start gap-2">
                      <span aria-hidden className="mt-1 text-brand">
                        -
                      </span>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                {tier.id === "enterprise" ? (
                  <a
                    href="mailto:sales@ca-adu-api.dev?subject=Enterprise%20plan"
                    className="mt-6 rounded-md border border-surface-border bg-white px-4 py-2 text-center font-medium text-ink hover:bg-surface-muted no-underline"
                  >
                    {tier.cta}
                  </a>
                ) : (
                  <Link
                    href="/dashboard"
                    className={`mt-6 rounded-md px-4 py-2 text-center font-medium no-underline ${
                      tier.highlighted
                        ? "bg-brand text-white hover:bg-brand-dark"
                        : "border border-surface-border bg-white text-ink hover:bg-surface-muted"
                    }`}
                  >
                    {tier.cta}
                  </Link>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
