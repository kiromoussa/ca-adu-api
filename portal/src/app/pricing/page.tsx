import type { Metadata } from "next";

import RapidApiCta from "@/components/RapidApiCta";
import { loadPlansConfig, PLAN_ORDER } from "@/lib/server-config";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "ADU Atlas API plans and quotas, sourced directly from config/plans.yaml.",
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
      <h1 className="text-3xl font-semibold tracking-tight">Pricing</h1>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-ink/70 dark:text-ink-dark/70">
        Plans and quotas below are read directly from the same configuration
        file the API's rate limiter enforces. There are no paid overages in
        v1: once a plan reaches its monthly quota, the API returns 429
        quota_exceeded until the next billing cycle.
      </p>

      <div className="mt-6 rounded-lg border border-ink/10 bg-ink/[0.02] p-5 text-sm leading-relaxed text-ink/70 dark:border-white/10 dark:bg-white/[0.03] dark:text-ink-dark/70">
        <p className="font-medium text-ink dark:text-ink-dark">
          Billable unit: {billable_unit.name}
        </p>
        <p className="mt-1">{billable_unit.description}</p>
        <p className="mt-3">
          Identical requests from the same customer within{" "}
          {dedupe.window_hours} hours are served from cache and are not
          billed again. Errors, quota-exceeded responses, and requests
          against an unsupported jurisdiction are never metered.
        </p>
      </div>

      <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {PLAN_ORDER.map((key) => {
          const plan = config.plans[key];
          if (!plan) return null;
          return (
            <div
              key={key}
              className="flex flex-col rounded-lg border border-ink/10 p-6 dark:border-white/10"
            >
              <h2 className="text-lg font-semibold">{plan.display_name}</h2>
              <p className="mt-2 flex items-baseline gap-1">
                <span className="text-3xl font-semibold tracking-tight">
                  ${plan.price_usd}
                </span>
                <span className="text-sm text-ink/50 dark:text-ink-dark/50">
                  / {plan.billing_period}
                </span>
              </p>
              <p className="mt-3 text-sm leading-relaxed text-ink/65 dark:text-ink-dark/65">
                {plan.description}
              </p>

              <div className="mt-4 space-y-1 text-sm text-ink/70 dark:text-ink-dark/70">
                <p>
                  <span className="font-medium">{plan.monthly_quota}</span>{" "}
                  completed analyses / month
                  {plan.hard_cap ? " (hard cap)" : ""}
                </p>
                <p>{plan.rate_limit_per_minute} requests / minute burst limit</p>
                <p>
                  Overages: {plan.overages_allowed ? "allowed" : "not available in v1"}
                </p>
              </div>

              <ul className="mt-5 flex-1 space-y-2 text-sm">
                {Object.entries(plan.features).map(([featureKey, enabled]) => (
                  <li
                    key={featureKey}
                    className={
                      enabled
                        ? "text-ink/80 dark:text-ink-dark/80"
                        : "text-ink/30 line-through dark:text-ink-dark/30"
                    }
                  >
                    {enabled ? "+ " : "- "}
                    {FEATURE_LABELS[featureKey] ?? featureKey}
                  </li>
                ))}
              </ul>

              <div className="mt-6">
                <RapidApiCta
                  label={plan.price_usd === 0 ? "Start free on RapidAPI" : "Subscribe on RapidAPI"}
                  variant={key === "PRO" ? "primary" : "secondary"}
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
