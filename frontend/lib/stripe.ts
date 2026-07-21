import "server-only";

import Stripe from "stripe";
import type { ApiTier } from "@/lib/database.types";
import { getStripeSecretKey } from "@/lib/env";

// Single Stripe instance for server code. apiVersion is intentionally omitted so
// the account's pinned default is used, avoiding type drift across SDK bumps.
export function getStripe(): Stripe {
  return new Stripe(getStripeSecretKey());
}

// Map a paid tier to its configured Stripe price id.
export function priceIdForTier(tier: "starter" | "pro"): string | undefined {
  if (tier === "starter") return process.env.STRIPE_PRICE_STARTER;
  return process.env.STRIPE_PRICE_PRO;
}

// Reverse lookup used by the webhook: given a Stripe price id, return the tier.
export function tierForPriceId(priceId: string | null | undefined): ApiTier | null {
  if (!priceId) return null;
  if (priceId === process.env.STRIPE_PRICE_STARTER) return "starter";
  if (priceId === process.env.STRIPE_PRICE_PRO) return "pro";
  return null;
}
