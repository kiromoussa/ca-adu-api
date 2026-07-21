import type { Metadata } from "next";

import RapidApiCta from "@/components/RapidApiCta";
import { loadPlansConfig, PLAN_ORDER } from "@/lib/server-config";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Atlas Property Feasibility API plans and quotas, sourced directly from config/plans.yaml.",
};

const FEATURE_LABELS: Record<string, string> = {
  feasibility_analysis: "Address-level feasibility analysis",
  jurisdiction_rules: "Jurisdiction and zone rule lookups",
  changelog: "Changelog access",
  shareable_analysis_token: "Shareable analysis links",
  priority_support: "Priority support",
};

export default function PricingPage() {
  const config = loadPlansConfig();
  const { billable_unit, dedupe } = config.billing;

  return (
    <div className="mx-auto max-w-content px-6 py-16">
      <p className="eyebrow">On RapidAPI &middot; self-serve, hard caps</p>
      <h1 className="mt-3 text-3xl font-bold tracking-tightest sm:text-4xl">
        Pay per completed analysis.
      </h1>
      <p className="mt-4 max-w-measure leading-relaxed text-muted">
        Plans and quotas below are read directly from the same configuration
        the API rate limiter enforces. No paid overages in v1: once a plan hits
        its monthly quota, the API returns 429 quota_exceeded until the next
        cycle.
      </p>

      <div className="mt-6 max-w-measure rounded-card border border-line bg-surface p-5">
        <p className="font-mono text-[13px] font-semibold text-ink">
          Billable unit: {billable_unit.name}
        </p>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">
          {billable_unit.description}
        </p>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          Identical requests from the same customer within {dedupe.window_hours}{" "}
          hours are served from cache and not billed again. Errors,
          quota-exceeded responses, and unsupported-jurisdiction requests are
          never metered.
        </p>
      </div>

      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PLAN_ORDER.map((key) => {
          const plan = config.plans[key];
          if (!plan) return null;
          const featured = key === "PRO";
          return (
            <div
              key={key}
              className={`flex flex-col rounded-card border bg-surface p-6 ${
                featured ? "border-accent shadow-[0_0_0_1px_rgb(var(--accent))]" : "border-line"
              }`}
            >
              <p className="font-mono text-[12px] uppercase tracking-[0.1em] text-muted">
                {plan.display_name}
              </p>
              <p className="mt-2 flex items-baseline gap-1">
                <span className="text-3xl font-bold tracking-tightest">
                  ${plan.price_usd}
                </span>
                <span className="text-sm text-faint">/ {plan.billing_period}</span>
              </p>
              <p className="mt-1 font-mono text-[13px] text-accent-deep">
                {plan.monthly_quota} / month{plan.hard_cap ? " (cap)" : ""}
              </p>
              <p className="mt-3 text-sm leading-relaxed text-muted">
                {plan.description}
              </p>

              <ul className="mt-5 flex-1 space-y-2 text-sm">
                {Object.entries(plan.features).map(([featureKey, enabled]) => (
                  <li
                    key={featureKey}
                    className={enabled ? "text-ink/80" : "text-faint line-through"}
                  >
                    <span className="font-mono text-accent-deep">
                      {enabled ? "+ " : "- "}
                    </span>
                    {FEATURE_LABELS[featureKey] ?? featureKey}
                  </li>
                ))}
              </ul>

              <div className="mt-6">
                <RapidApiCta
                  label={plan.price_usd === 0 ? "Start free" : "Subscribe"}
                  variant={featured ? "primary" : "secondary"}
                  className="w-full"
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
