import { describe, expect, it } from "vitest";
import { PRICING_TIERS, TIER_QUOTAS } from "@/lib/pricing";

describe("pricing tiers", () => {
  it("exposes the four spec tiers in order", () => {
    expect(PRICING_TIERS.map((t) => t.id)).toEqual([
      "free",
      "starter",
      "pro",
      "enterprise"
    ]);
  });

  it("matches the quota floors enforced by increment_api_usage()", () => {
    expect(TIER_QUOTAS.free).toBe(50);
    expect(TIER_QUOTAS.starter).toBe(1000);
    expect(TIER_QUOTAS.pro).toBe(10000);
    expect(TIER_QUOTAS.enterprise).toBeNull();
  });

  it("only offers self-serve checkout for starter and pro", () => {
    const checkoutable = PRICING_TIERS.filter((t) => t.checkoutTier).map(
      (t) => t.checkoutTier
    );
    expect(checkoutable).toEqual(["starter", "pro"]);
  });

  it("prices the paid tiers per the spec", () => {
    expect(PRICING_TIERS.find((t) => t.id === "starter")?.price).toBe("$19");
    expect(PRICING_TIERS.find((t) => t.id === "pro")?.price).toBe("$49");
  });
});
