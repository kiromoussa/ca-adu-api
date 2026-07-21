import type { Metadata } from "next";

import CoverageBadge from "@/components/Badge";
import { loadJurisdictionsConfig, sourceRegistryByKey } from "@/lib/server-config";
import {
  COVERAGE_STATUS_DESCRIPTIONS,
  PROJECT_TYPE_LABELS,
} from "@/lib/constants";

export const metadata: Metadata = {
  title: "Coverage",
  description:
    "Live jurisdiction coverage for Atlas Property Feasibility API, sourced directly from config/jurisdictions.yaml.",
};

export default function CoveragePage() {
  const { jurisdictions } = loadJurisdictionsConfig();
  const sources = sourceRegistryByKey();

  const statusOrder = ["production", "ingesting", "planned"] as const;
  const sorted = [...jurisdictions].sort(
    (a, b) => statusOrder.indexOf(a.coverage_status) - statusOrder.indexOf(b.coverage_status)
  );

  return (
    <div className="mx-auto max-w-content px-6 py-16">
      <p className="eyebrow">Coverage</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tightest sm:text-4xl">
        Los Angeles is live. The rest are honest.
      </h1>
      <p className="mt-4 max-w-measure leading-relaxed text-muted">
        Coverage is generated directly from the jurisdiction registry that
        drives the API. A jurisdiction reaches
        <span className="mx-1.5 inline-block align-middle">
          <CoverageBadge status="production" />
        </span>
        only after its municipal-code source, GIS parcel and zoning layers, and
        rule set are ingested, tested, and verified. We do not claim coverage
        ahead of that verification.
      </p>

      <div className="mt-8 grid gap-3 sm:grid-cols-3">
        {statusOrder.map((status) => (
          <div key={status} className="rounded-card border border-line bg-surface p-4">
            <CoverageBadge status={status} />
            <p className="mt-2.5 text-xs leading-relaxed text-muted">
              {COVERAGE_STATUS_DESCRIPTIONS[status]}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-12 space-y-4">
        {sorted.map((j) => (
          <div key={j.slug} className="rounded-card border border-line bg-surface p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold tracking-tightest">
                  {j.display_name}
                </h2>
                <p className="font-mono text-[11px] uppercase tracking-[0.06em] text-faint">
                  {j.county} County, {j.state}
                </p>
              </div>
              <CoverageBadge status={j.coverage_status} />
            </div>

            <p className="mt-4 max-w-measure text-sm leading-relaxed text-muted">
              {j.notes}
            </p>

            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              <div>
                <p className="eyebrow">Project types</p>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {j.supported_project_types.map((type) => (
                    <span
                      key={type}
                      className="rounded-full border border-line bg-surface-2 px-2.5 py-1 font-mono text-[12px] text-muted"
                    >
                      {PROJECT_TYPE_LABELS[type] ?? type}
                    </span>
                  ))}
                </div>
              </div>
              <div>
                <p className="eyebrow">Sources</p>
                <ul className="mt-2.5 space-y-1.5">
                  {j.source_keys.map((key) => {
                    const source = sources.get(key);
                    return (
                      <li key={key} className="text-xs text-muted">
                        {source ? (
                          <a
                            href={source.base_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="cursor-pointer text-accent-deep underline decoration-line-strong underline-offset-2 hover:decoration-accent"
                          >
                            {source.name}
                          </a>
                        ) : (
                          key
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>

            <a
              href={j.official_code_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-5 inline-block cursor-pointer font-mono text-xs font-semibold text-accent-deep underline decoration-line-strong underline-offset-4 hover:decoration-accent"
            >
              Official municipal code -&gt;
            </a>
          </div>
        ))}
      </div>
    </div>
  );
}
