import Link from "next/link";

import RapidApiCta from "@/components/RapidApiCta";
import Disclaimer from "@/components/Disclaimer";
import { loadJurisdictionsConfig } from "@/lib/server-config";
import { FEASIBILITY_STATUSES } from "@/lib/constants";

const REQUEST = `POST /v1/feasibility
{
  "address": "509 N Avenue 50, Los Angeles, CA 90042",
  "project_type": "detached_adu",
  "target_sqft": 800,
  "proposed_height_ft": 16
}`;

const RESPONSE = `200 OK
{
  "feasibility_status": "likely_feasible",
  "jurisdiction": "los_angeles",
  "parcel":   { "apn": "5469-011-014", "zone": "RD1.5" },
  "constraints": {
    "side_rear_setback_min_ft": {
      "value": 4, "source_title": "AB 2221",
      "data_status": "current", "confidence": "high"
    }
  },
  "disclaimer": "Preliminary informational analysis ..."
}`;

const TRUST = [
  {
    tag: "no_llm_on_request",
    title: "Deterministic answers",
    body: "Every response comes from versioned rules, PostGIS spatial joins, and source-linked data. Language models run only offline to draft rule candidates for human review.",
  },
  {
    tag: "provenance",
    title: "A citation on every field",
    body: "source_url, source_title, section or layer, retrieved_at, last_verified_at, confidence, and data_status travel with every value the API asserts.",
  },
  {
    tag: "no_false_certainty",
    title: "Honest verdicts",
    body: "Never approved, legal, or a bare yes or no. Results resolve to likely_feasible, likely_constrained, needs_professional_review, or insufficient_data.",
  },
  {
    tag: "state_baseline",
    title: "State law as ground truth",
    body: "Local values are checked against current California law (AB 2221, SB 897, SB 9). Anything more restrictive is flagged for review, and the local source is preserved.",
  },
  {
    tag: "immutable_snapshots",
    title: "History is never overwritten",
    body: "Every scraped code section and GIS layer fetch is content-hashed and stored as an immutable, versioned snapshot, so any result can be traced to its source.",
  },
  {
    tag: "coverage_honesty",
    title: "No claimed coverage",
    body: "A city returns a billable result only after its sources and rules are ingested, tested, and verified. GET /v1/jurisdictions is the live source of truth.",
  },
];

const PLATE_ROWS = [
  { k: "Zone", v: "RD1.5", src: "ZIMAS" },
  { k: "Max height, detached", v: "16 ft", src: "LAMC 12.22" },
  { k: "Side / rear setback", v: "4 ft", src: "AB 2221" },
  { k: "Owner occupancy", v: "not required", src: "Gov 66323" },
  { k: "Flood overlay", v: "Zone X", src: "FEMA" },
];

const PHASES = [
  {
    label: "Today - live",
    dot: "bg-ok",
    text: "text-ok",
    sub: "Shipping in Los Angeles.",
    items: ["detached ADU", "attached ADU", "garage conversion", "JADU", "SB 9 duplex", "SB 9 lot split"],
  },
  {
    label: "Tomorrow",
    dot: "bg-accent",
    text: "text-accent-deep",
    sub: "The rest of the development stack.",
    items: ["permits", "zoning", "environmental", "historic districts", "coastal", "utilities"],
  },
  {
    label: "Eventually",
    dot: "bg-faint",
    text: "text-muted",
    sub: "The feasibility layer for property.",
    items: ["any address", "any project", "any constraint", "statewide", "nationwide"],
  },
];

export default function HomePage() {
  const { jurisdictions } = loadJurisdictionsConfig();
  const counts = jurisdictions.reduce(
    (acc, j) => {
      acc[j.coverage_status] = (acc[j.coverage_status] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <div>
      {/* Hero */}
      <section className="mx-auto max-w-content px-6 pb-16 pt-16 sm:pt-24">
        <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <p className="eyebrow">Property feasibility, as an API</p>
            <h1 className="mt-4 text-4xl font-bold tracking-tightest sm:text-6xl">
              The API for property feasibility.
            </h1>
            <p className="mt-6 max-w-[42ch] text-lg leading-relaxed text-muted">
              Starting with California ADUs. Expanding to every permit, zoning
              rule, and development constraint. One call, one source-cited
              answer.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <RapidApiCta />
              <Link
                href="/docs"
                className="inline-flex cursor-pointer items-center rounded-card border border-line-strong px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:border-accent hover:text-accent-deep"
              >
                Read the docs
              </Link>
            </div>
            <div className="mt-7 flex flex-wrap gap-x-7 gap-y-2 font-mono text-xs text-faint">
              <span>
                <span className="text-muted">Deterministic.</span> No LLM on the request path.
              </span>
              <span>
                <span className="text-muted">Cited.</span> Every field, every time.
              </span>
            </div>
          </div>

          {/* Feasibility plate */}
          <div className="overflow-hidden rounded-card border border-line bg-surface shadow-sm">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <span className="font-mono text-[13px] text-muted">
                <span className="text-ink">POST</span> /v1/feasibility
              </span>
              <span className="h-2 w-2 rounded-full bg-accent ring-4 ring-[var(--accent-wash)]" />
            </div>
            <div
              className="relative aspect-[16/10] bg-surface-2"
              style={{
                backgroundImage:
                  "linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px)",
                backgroundSize: "22px 22px, 22px 22px",
              }}
            >
              <span className="absolute left-3 top-2.5 font-mono text-[10.5px] text-faint">
                34.1090 N, 118.2045 W
              </span>
              <span className="absolute right-3 top-2.5 font-mono text-[10.5px] text-faint">
                APN 5469-011-014
              </span>
              <svg viewBox="0 0 400 250" className="absolute inset-0 h-full w-full" aria-hidden="true">
                <polygon points="70,42 330,58 320,206 82,196" fill="none" stroke="rgb(var(--line-strong))" strokeWidth="2" />
                <polygon points="104,76 296,90 288,180 114,170" fill="var(--accent-wash)" stroke="rgb(var(--accent))" strokeWidth="2" />
                <rect x="198" y="112" width="78" height="52" rx="2" fill="rgb(var(--accent) / 0.28)" stroke="rgb(var(--accent-deep))" strokeWidth="1.5" />
                <text x="212" y="143" fill="rgb(var(--muted))" fontFamily="ui-monospace, monospace" fontSize="11">ADU 800 sf</text>
              </svg>
              <span className="absolute bottom-3 left-3 inline-flex items-center gap-2 rounded-full border border-ok/40 bg-surface px-3 py-1.5 font-mono text-[12.5px] font-semibold text-ok">
                <span className="h-1.5 w-1.5 rounded-full bg-ok" /> likely_feasible
              </span>
            </div>
            <div>
              {PLATE_ROWS.map((r, i) => (
                <div
                  key={r.k}
                  className={`flex items-baseline justify-between gap-3 px-4 py-2.5 ${i > 0 ? "border-t border-line" : ""}`}
                >
                  <span className="text-[13.5px] text-muted">{r.k}</span>
                  <span className="font-mono text-[13.5px] font-semibold">
                    {r.v}
                    <span className="ml-2 rounded border border-line-strong px-1.5 py-px font-mono text-[10px] font-normal text-accent-deep">
                      {r.src}
                    </span>
                  </span>
                </div>
              ))}
            </div>
            <p className="border-t border-line px-4 py-2.5 text-[11px] leading-snug text-faint">
              Preliminary informational analysis, not legal, architectural, or
              permit advice. retrieved_at 2026-07-21 &middot; confidence: medium
            </p>
          </div>
        </div>
      </section>

      {/* Request / response */}
      <Section id="call" eyebrow="One request, one billable result" title="What you send, and what you get back.">
        <p className="mb-8 max-w-measure text-muted">
          A billable unit is one completed analysis: one address plus one
          project type. Errors and unsupported-coverage responses are never
          billed.
        </p>
        <div className="grid gap-5 md:grid-cols-2">
          <CodeCard label="Request" verb="POST /v1/feasibility" body={REQUEST} />
          <CodeCard label="Response" verb="200 OK" body={RESPONSE} />
        </div>
        <div className="mt-7 flex flex-wrap gap-2.5">
          {FEASIBILITY_STATUSES.map((s) => (
            <span
              key={s.value}
              className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-surface px-3 py-1.5 font-mono text-[12.5px] font-semibold"
            >
              <span
                className={`h-2 w-2 rounded-full ${
                  s.value === "likely_feasible"
                    ? "bg-ok"
                    : s.value === "likely_constrained"
                      ? "bg-warn"
                      : s.value === "needs_professional_review"
                        ? "bg-review"
                        : "bg-faint"
                }`}
              />
              {s.value}
            </span>
          ))}
        </div>
      </Section>

      {/* Trust */}
      <Section
        eyebrow="Why the number is defensible"
        title="Built to be cited, not just consumed."
      >
        <p className="mb-10 max-w-measure text-muted">
          Feasibility drives real money and permits. Every design choice favors
          traceability over confident guessing.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {TRUST.map((c) => (
            <div key={c.tag} className="rounded-card border border-line bg-surface p-6">
              <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-accent-deep">
                {c.tag}
              </p>
              <h3 className="mt-3 text-lg font-semibold tracking-tightest">{c.title}</h3>
              <p className="mt-2 text-[14.5px] leading-relaxed text-muted">{c.body}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* Vision / roadmap */}
      <Section
        eyebrow="The wedge"
        title="Small enough to ship. Big enough to be infrastructure."
      >
        <p className="mb-10 max-w-[64ch] text-muted">
          ADUs are the beachhead, not the ceiling. The same primitive, resolving
          an address and a project into a cited, deterministic feasibility read,
          generalizes to every question a builder, lender, or agent needs
          answered about a piece of land.
        </p>
        <div className="mb-11 text-center">
          <code className="font-mono text-2xl font-semibold tracking-tightest sm:text-3xl">
            <span className="text-accent-deep">feasibility</span>
            <span className="text-muted">(address, project)</span>
          </code>
          <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-faint">
            one function &middot; eventually, for anything you can build
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {PHASES.map((p) => (
            <div key={p.label} className="rounded-card border border-line bg-surface p-6">
              <div className={`flex items-center gap-2 font-mono text-xs font-semibold uppercase tracking-[0.09em] ${p.text}`}>
                <span className={`h-2 w-2 rounded-full ${p.dot}`} />
                {p.label}
              </div>
              <p className="mt-3 text-sm text-faint">{p.sub}</p>
              <ul className="mt-4 flex flex-wrap gap-2">
                {p.items.map((it) => (
                  <li
                    key={it}
                    className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-mono text-[12.5px] text-muted"
                  >
                    {it}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Section>

      {/* Coverage */}
      <Section eyebrow="Coverage" title="Los Angeles is live. The rest are honest.">
        <div className="flex flex-col items-start justify-between gap-6 sm:flex-row sm:items-end">
          <p className="max-w-measure text-muted">
            A jurisdiction is marked live only after its source registry, GIS
            layers, and rule set are ingested, tested, and verified. Right now{" "}
            <span className="font-mono text-ink">{counts.production ?? 0}</span>{" "}
            live,{" "}
            <span className="font-mono text-ink">{counts.ingesting ?? 0}</span>{" "}
            in ingestion,{" "}
            <span className="font-mono text-ink">{counts.planned ?? 0}</span>{" "}
            planned. Requests against a planned jurisdiction return
            unsupported_coverage and are never billed.
          </p>
          <Link
            href="/coverage"
            className="inline-flex cursor-pointer whitespace-nowrap items-center rounded-card border border-line-strong px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:border-accent hover:text-accent-deep"
          >
            View full coverage
          </Link>
        </div>
      </Section>

      {/* Disclaimer + CTA */}
      <section className="border-t border-line">
        <div className="mx-auto max-w-content px-6 py-16">
          <Disclaimer />
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <RapidApiCta />
            <Link
              href="/pricing"
              className="cursor-pointer text-sm font-semibold text-accent-deep underline decoration-line-strong underline-offset-4 hover:decoration-accent"
            >
              See pricing
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}

function Section({
  id,
  eyebrow,
  title,
  children,
}: {
  id?: string;
  eyebrow: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="border-t border-line">
      <div className="mx-auto max-w-content px-6 py-16 sm:py-20">
        <p className="eyebrow">{eyebrow}</p>
        <h2 className="mt-3 max-w-[22ch] text-3xl font-bold tracking-tightest sm:text-4xl">
          {title}
        </h2>
        <div className="mt-8">{children}</div>
      </div>
    </section>
  );
}

function CodeCard({ label, verb, body }: { label: string; verb: string; body: string }) {
  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface-2 shadow-sm">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="font-mono text-xs uppercase tracking-[0.06em] text-muted">
          {label}
        </span>
        <span className="rounded bg-[var(--accent-wash)] px-2 py-0.5 font-mono text-[11px] font-bold text-accent-deep">
          {verb}
        </span>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-[12.7px] leading-relaxed text-ink">
        {body}
      </pre>
    </div>
  );
}
