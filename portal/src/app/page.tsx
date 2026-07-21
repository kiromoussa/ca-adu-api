import Link from "next/link";

import RapidApiCta from "@/components/RapidApiCta";
import Disclaimer from "@/components/Disclaimer";
import { loadJurisdictionsConfig } from "@/lib/server-config";
import { FEASIBILITY_STATUSES, PROJECT_TYPE_LABELS } from "@/lib/constants";

export default function HomePage() {
  const { jurisdictions, project_types } = loadJurisdictionsConfig();

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
      <section className="mx-auto max-w-content px-6 pb-16 pt-20 sm:pt-28">
        <p className="text-sm font-medium uppercase tracking-wide text-ink/50 dark:text-ink-dark/50">
          Developer API - California ADU / JADU / SB 9
        </p>
        <h1 className="mt-4 max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          Address-level ADU feasibility, source-cited and deterministic.
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink/70 dark:text-ink-dark/70">
          Send an address and a proposed ADU project. Receive a source-cited,
          timestamped preliminary feasibility result: parcel and zoning
          context, ADU/JADU/SB 9 rules, setback/height/size constraints,
          hazard and overlay flags, assumptions, confidence, and
          official-source citations - built for a PropTech, architecture,
          real estate, or lending workflow, or an AI agent, to call
          programmatically.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-4">
          <RapidApiCta />
          <Link
            href="/docs"
            className="cursor-pointer text-sm font-medium text-ink underline decoration-ink/30 underline-offset-4 hover:decoration-ink dark:text-ink-dark dark:decoration-white/30 dark:hover:decoration-white"
          >
            Read the API docs
          </Link>
        </div>
      </section>

      {/* What you get */}
      <section className="border-t border-ink/10 dark:border-white/10">
        <div className="mx-auto max-w-content px-6 py-16">
          <h2 className="text-2xl font-semibold tracking-tight">
            What a feasibility request returns
          </h2>
          <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                title: "Parcel and zoning context",
                body: "APN, geometry source, zone code and name, spatial-join method, and the layer and timestamp behind them.",
              },
              {
                title: "Eligible paths",
                body: "Detached ADU, attached ADU, garage conversion, JADU, SB 9 duplex, and SB 9 urban lot split, each with its own status.",
              },
              {
                title: "Development constraints",
                body: "Height, size, setback, parking, owner-occupancy, permit timeline, and impact-fee constraints, condition by condition.",
              },
              {
                title: "Overlay findings",
                body: "Flood, fire, historic, coastal, hillside, and environmental overlay hits, distinguishing no-hit from source-unavailable.",
              },
              {
                title: "Approximate envelope",
                body: "A labeled conceptual buildable envelope where parcel and zoning data support it - never presented as a survey.",
              },
              {
                title: "Assumptions, limitations, and sources",
                body: "Every substantive field carries source_url, source_title, source_section or layer, retrieved_at, last_verified_at, confidence, and data_status.",
              },
            ].map((item) => (
              <div
                key={item.title}
                className="rounded-lg border border-ink/10 p-6 dark:border-white/10"
              >
                <h3 className="text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink/65 dark:text-ink-dark/65">
                  {item.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* No LLM on the request path */}
      <section className="border-t border-ink/10 dark:border-white/10">
        <div className="mx-auto max-w-content px-6 py-16">
          <div className="grid gap-10 lg:grid-cols-2">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Deterministic rules, not a language model
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
                The request path never calls a language model. Every
                feasibility result comes from versioned zoning rules, state-law
                baselines, and PostGIS spatial joins against official parcel,
                zoning, and hazard-overlay geometry. Large language models are
                used only offline, to propose extraction candidates from
                municipal code and to run QA, and every candidate still
                requires source and human validation before it is marked
                verified.
              </p>
              <p className="mt-4 text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
                We never report a final "approved," "legal," or "guaranteed"
                answer. Every result carries one of four explicit
                <code className="mx-1 rounded bg-ink/5 px-1.5 py-0.5 text-xs dark:bg-white/10">
                  feasibility_status
                </code>
                values.
              </p>
              <ul className="mt-6 space-y-3">
                {FEASIBILITY_STATUSES.map((status) => (
                  <li key={status.value} className="text-sm">
                    <code className="rounded bg-ink/5 px-1.5 py-0.5 text-xs font-medium dark:bg-white/10">
                      {status.value}
                    </code>
                    <span className="ml-2 text-ink/65 dark:text-ink-dark/65">
                      {status.description}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                State-law floor, always documented
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
                Every determination is checked against the current California
                state-law baseline (AB 2221, SB 897, SB 9, AB 68/SB 13, Gov.
                Code 66310-66342 and related sections). When a local rule is
                more restrictive than the state baseline, the result is
                flagged
                <code className="mx-1 rounded bg-ink/5 px-1.5 py-0.5 text-xs dark:bg-white/10">
                  possibly_more_restrictive_than_state_baseline
                </code>
                with a
                <code className="mx-1 rounded bg-ink/5 px-1.5 py-0.5 text-xs dark:bg-white/10">
                  needs_review
                </code>
                compliance flag - the local source is always preserved, never
                silently overridden.
              </p>
              <p className="mt-4 text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
                Raw source snapshots (municipal code sections and GIS layer
                metadata) are content-hashed and immutable. History is never
                overwritten, so every result can be traced back to the exact
                source text or layer state it was derived from.
              </p>
              <p className="mt-4 text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
                Supported project types:
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {project_types.map((type) => (
                  <span
                    key={type}
                    className="rounded-full border border-ink/10 px-3 py-1 text-xs text-ink/70 dark:border-white/15 dark:text-ink-dark/70"
                  >
                    {PROJECT_TYPE_LABELS[type] ?? type}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Coverage teaser */}
      <section className="border-t border-ink/10 dark:border-white/10">
        <div className="mx-auto max-w-content px-6 py-16">
          <div className="flex flex-col items-start justify-between gap-6 sm:flex-row sm:items-center">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">Coverage</h2>
              <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
                A jurisdiction is only marked live after its source registry,
                GIS layers, and rule set are ingested, tested, and verified.
                Right now {counts.production ?? 0} jurisdiction(s) are live,{" "}
                {counts.ingesting ?? 0} are in active ingestion, and{" "}
                {counts.planned ?? 0} are planned. Requests against a planned
                jurisdiction return unsupported_coverage and are never
                billed.
              </p>
            </div>
            <Link
              href="/coverage"
              className="cursor-pointer whitespace-nowrap rounded-md border border-ink/15 px-5 py-2.5 text-sm font-medium text-ink hover:bg-ink/5 dark:border-white/20 dark:text-ink-dark dark:hover:bg-white/10"
            >
              View full coverage
            </Link>
          </div>
        </div>
      </section>

      {/* Disclaimer */}
      <section className="border-t border-ink/10 dark:border-white/10">
        <div className="mx-auto max-w-content px-6 py-16">
          <Disclaimer />
          <div className="mt-8 flex flex-wrap gap-4">
            <RapidApiCta />
            <Link
              href="/pricing"
              className="cursor-pointer text-sm font-medium text-ink underline decoration-ink/30 underline-offset-4 hover:decoration-ink dark:text-ink-dark dark:decoration-white/30 dark:hover:decoration-white"
            >
              See pricing
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
