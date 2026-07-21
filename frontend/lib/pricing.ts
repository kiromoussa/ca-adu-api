// Pricing tiers (ca-adu-build-spec.md section 4). Single source of truth for the
// landing page and the dashboard billing panel.

export interface PricingTier {
  id: "free" | "starter" | "pro" | "enterprise";
  name: string;
  price: string;
  cadence: string;
  tagline: string;
  features: string[];
  monthlyLookups: number | null;
  cta: string;
  highlighted: boolean;
  checkoutTier?: "starter" | "pro";
}

export const OVERAGE_RATE = "$0.02 / lookup";

export const PRICING_TIERS: PricingTier[] = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    cadence: "forever",
    tagline: "Kick the tires on a single city.",
    monthlyLookups: 50,
    features: [
      "50 lookups / month",
      "1 city",
      "State-law-validated fields",
      "Full OpenAPI access"
    ],
    cta: "Start free",
    highlighted: false
  },
  {
    id: "starter",
    name: "Starter",
    price: "$19",
    cadence: "/ month",
    tagline: "All 8 cities for production apps.",
    monthlyLookups: 1000,
    features: [
      "1,000 lookups / month",
      "All 8 California cities",
      "Compliance-flag endpoint",
      `Overage ${OVERAGE_RATE}, no cliff`
    ],
    cta: "Choose Starter",
    highlighted: true,
    checkoutTier: "starter"
  },
  {
    id: "pro",
    name: "Pro",
    price: "$49",
    cadence: "/ month",
    tagline: "High volume plus change alerts.",
    monthlyLookups: 10000,
    features: [
      "10,000 lookups / month",
      "All 8 California cities",
      "Webhook alerts on ordinance changes",
      `Overage ${OVERAGE_RATE}, no cliff`
    ],
    cta: "Choose Pro",
    highlighted: false,
    checkoutTier: "pro"
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "Custom",
    cadence: "",
    tagline: "Bulk data and white-label reports.",
    monthlyLookups: null,
    features: [
      "Custom volume",
      "Bulk CSV export",
      "White-label reports",
      "Priority support and SLA"
    ],
    cta: "Contact sales",
    highlighted: false
  }
];

// Monthly quota per tier, mirroring increment_api_usage() in the schema.
export const TIER_QUOTAS: Record<PricingTier["id"], number | null> = {
  free: 50,
  starter: 1000,
  pro: 10000,
  enterprise: null
};
