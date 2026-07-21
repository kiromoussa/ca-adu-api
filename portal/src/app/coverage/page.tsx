import type { Metadata } from "next";

import CoverageBadge from "@/components/Badge";
import { loadJurisdictionsConfig, sourceRegistryByKey } from "@/lib/server-config";
import {
  COVERAGE_STATUS_DESCRIPTIONS,
  COVERAGE_STATUS_LABELS,
  PROJECT_TYPE_LABELS,
} from "@/lib/constants";

export const metadata: Metadata = {
  title: "Coverage",
  description:
    "Live jurisdiction coverage for the ADU Atlas API, sourced directly from config/jurisdictions.yaml.",
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
      <h1 className="text-3xl font-semibold tracking-tight">Coverage</h1>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
        Coverage status is generated directly from the jurisdiction registry
        that drives the API. A jurisdiction only reaches
        <span className="mx-1">
          <CoverageBadge status="production" />
        </span>
        after its municipal-code source, GIS parcel and zoning layers, and
        rule set are ingested, tested, and verified. We do not claim coverage
        for a jurisdiction ahead of that verification.
      </p>

      <div className="mt-8 grid gap-3 sm:grid-cols-3">
        {statusOrder.map((status) => (
          <div
            key={status}
            className="rounded-lg border border-ink/10 p-4 dark:border-white/10"
          >
            <CoverageBadge status={status} />
            <p className="mt-2 text-xs leading-relaxed text-ink/60 dark:text-ink-dark/60">
              {COVERAGE_STATUS_DESCRIPTIONS[status]}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-12 space-y-6">
        {sorted.map((jurisdiction) => (
          <div
            key={jurisdiction.slug}
            className="rounded-lg border border-ink/10 p-6 dark:border-white/10"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">
                  {jurisdiction.display_name}
                </h2>
                <p className="text-xs text-ink/50 dark:text-ink-dark/50">
                  {jurisdiction.county} County, {jurisdiction.state}
                </p>
              </div>
              <CoverageBadge status={jurisdiction.coverage_status} />
            </div>

            <p className="mt-4 text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
              {jurisdiction.notes}
            </p>

            <div className="mt-4">
              <p className="text-xs font-medium uppercase tracking-wide text-ink/40 dark:text-ink-dark/40">
                Supported project types
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {jurisdiction.supported_project_types.map((type) => (
                  <span
                    key={type}
                    className="rounded-full border border-ink/10 px-3 py-1 text-xs text-ink/70 dark:border-white/15 dark:text-ink-dark/70"
                  >
                    {PROJECT_TYPE_LABELS[type] ?? type}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-4">
              <p className="text-xs font-medium uppercase tracking-wide text-ink/40 dark:text-ink-dark/40">
                Sources
              </p>
              <ul className="mt-2 space-y-1">
                {jurisdiction.source_keys.map((key) => {
                  const source = sources.get(key);
                  return (
                    <li key={key} className="text-xs text-ink/60 dark:text-ink-dark/60">
                      {source ? (
                        <a
                          href={source.base_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="cursor-pointer underline decoration-ink/20 underline-offset-2 hover:decoration-ink dark:decoration-white/20 dark:hover:decoration-white"
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

            <a
              href={jurisdiction.official_code_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-4 inline-block cursor-pointer text-xs font-medium text-ink underline decoration-ink/30 underline-offset-4 hover:decoration-ink dark:text-ink-dark dark:decoration-white/30 dark:hover:decoration-white"
            >
              Official municipal code -&gt;
            </a>
          </div>
        ))}
      </div>

      <p className="mt-12 text-xs text-ink/40 dark:text-ink-dark/40">
        Coverage status values: {COVERAGE_STATUS_LABELS.production} (production),{" "}
        {COVERAGE_STATUS_LABELS.ingesting} (ingesting),{" "}
        {COVERAGE_STATUS_LABELS.planned} (planned).
      </p>
    </div>
  );
}
