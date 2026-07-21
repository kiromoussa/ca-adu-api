import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { priceIdForTier, tierForPriceId } from "@/lib/stripe";

const original = { ...process.env };

beforeEach(() => {
  process.env.STRIPE_PRICE_STARTER = "price_starter_123";
  process.env.STRIPE_PRICE_PRO = "price_pro_456";
});

afterEach(() => {
  process.env = { ...original };
});

describe("priceIdForTier", () => {
  it("maps tiers to configured price ids", () => {
    expect(priceIdForTier("starter")).toBe("price_starter_123");
    expect(priceIdForTier("pro")).toBe("price_pro_456");
  });
});

describe("tierForPriceId", () => {
  it("reverse-maps a price id to its tier", () => {
    expect(tierForPriceId("price_starter_123")).toBe("starter");
    expect(tierForPriceId("price_pro_456")).toBe("pro");
  });

  it("returns null for unknown or empty price ids", () => {
    expect(tierForPriceId("price_unknown")).toBeNull();
    expect(tierForPriceId(null)).toBeNull();
    expect(tierForPriceId(undefined)).toBeNull();
  });
});
