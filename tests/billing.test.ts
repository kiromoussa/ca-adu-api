// Integration tests for the Stripe billing webhook
// (frontend/app/api/stripe/webhook/route.ts).
//
// Asserts the webhook upgrades api_keys.tier when Stripe reports a paid
// subscription, on both checkout.session.completed and customer.subscription.*
// events. Stripe (signature verification + subscription lookup) and the Supabase
// service client are mocked, so there is no network, no real Stripe, and no real
// database. The webhook secret and price->tier map are also stubbed.

import { describe, it, expect, beforeEach, vi } from "vitest";

// Shared, hoisted spies/state so the vi.mock factories (hoisted above imports)
// can reach them.
const h = vi.hoisted(() => ({
  updateCalls: [] as Array<{ table: string; payload: Record<string, unknown>; col: string; val: unknown }>,
  constructEvent: vi.fn(),
  subscriptionsRetrieve: vi.fn(),
}));

vi.mock("@/lib/supabase/service", () => ({
  createServiceClient: () => ({
    from: (table: string) => ({
      update: (payload: Record<string, unknown>) => ({
        eq: (col: string, val: unknown) => {
          h.updateCalls.push({ table, payload, col, val });
          return Promise.resolve({ error: null });
        },
      }),
    }),
  }),
}));

vi.mock("@/lib/stripe", () => ({
  getStripe: () => ({
    webhooks: { constructEvent: h.constructEvent },
    subscriptions: { retrieve: h.subscriptionsRetrieve },
  }),
  tierForPriceId: (priceId: string | null | undefined) =>
    priceId === "price_starter" ? "starter" : priceId === "price_pro" ? "pro" : null,
}));

vi.mock("@/lib/env", () => ({
  getStripeWebhookSecret: () => "whsec_test",
}));

import { POST } from "@/app/api/stripe/webhook/route";

function webhookRequest(rawBody: string, signature: string | null) {
  return {
    headers: { get: (name: string) => (name === "stripe-signature" ? signature : null) },
    text: async () => rawBody,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  } as any;
}

function lastUpdate() {
  return h.updateCalls[h.updateCalls.length - 1];
}

beforeEach(() => {
  h.updateCalls.length = 0;
  h.constructEvent.mockReset();
  h.subscriptionsRetrieve.mockReset();
});

describe("stripe webhook", () => {
  it("rejects a request with no stripe-signature header (400)", async () => {
    const res = await POST(webhookRequest("{}", null));
    expect(res.status).toBe(400);
    expect(h.updateCalls).toHaveLength(0);
  });

  it("rejects a request whose signature fails verification (400)", async () => {
    h.constructEvent.mockImplementation(() => {
      throw new Error("no signatures found matching the expected signature");
    });
    const res = await POST(webhookRequest("{}", "bad-sig"));
    expect(res.status).toBe(400);
    expect(h.updateCalls).toHaveLength(0);
  });

  it("upgrades tier on checkout.session.completed using session metadata", async () => {
    h.constructEvent.mockReturnValue({
      type: "checkout.session.completed",
      data: {
        object: {
          metadata: { user_id: "user-1", tier: "pro" },
          customer: "cus_1",
          subscription: "sub_1",
        },
      },
    });

    const res = await POST(webhookRequest("{}", "sig"));

    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ received: true });

    const call = lastUpdate();
    expect(call.table).toBe("api_keys");
    expect(call.payload.tier).toBe("pro");
    expect(call.payload.stripe_customer_id).toBe("cus_1");
    expect(call.payload.stripe_subscription_id).toBe("sub_1");
    expect(call.col).toBe("user_id");
    expect(call.val).toBe("user-1");
  });

  it("resolves tier from the subscription price when session metadata omits it", async () => {
    h.constructEvent.mockReturnValue({
      type: "checkout.session.completed",
      data: {
        object: {
          metadata: { user_id: "user-2" },
          customer: "cus_2",
          subscription: "sub_2",
        },
      },
    });
    h.subscriptionsRetrieve.mockResolvedValue({
      items: { data: [{ price: { id: "price_starter" } }] },
    });

    const res = await POST(webhookRequest("{}", "sig"));

    expect(res.status).toBe(200);
    expect(h.subscriptionsRetrieve).toHaveBeenCalledWith("sub_2");
    const call = lastUpdate();
    expect(call.payload.tier).toBe("starter");
    expect(call.val).toBe("user-2");
  });

  it("upgrades tier on customer.subscription.updated when active", async () => {
    h.constructEvent.mockReturnValue({
      type: "customer.subscription.updated",
      data: {
        object: {
          id: "sub_3",
          status: "active",
          customer: "cus_3",
          metadata: { user_id: "user-3" },
          items: { data: [{ price: { id: "price_pro" } }] },
        },
      },
    });

    const res = await POST(webhookRequest("{}", "sig"));

    expect(res.status).toBe(200);
    const call = lastUpdate();
    expect(call.payload.tier).toBe("pro");
    expect(call.payload.stripe_subscription_id).toBe("sub_3");
    expect(call.col).toBe("user_id");
    expect(call.val).toBe("user-3");
  });

  it("downgrades to free on customer.subscription.updated when canceled", async () => {
    h.constructEvent.mockReturnValue({
      type: "customer.subscription.updated",
      data: {
        object: {
          id: "sub_4",
          status: "canceled",
          customer: "cus_4",
          metadata: { user_id: "user-4" },
          items: { data: [{ price: { id: "price_pro" } }] },
        },
      },
    });

    const res = await POST(webhookRequest("{}", "sig"));

    expect(res.status).toBe(200);
    expect(lastUpdate().payload.tier).toBe("free");
  });

  it("matches by stripe_customer_id when no user id is present", async () => {
    h.constructEvent.mockReturnValue({
      type: "customer.subscription.updated",
      data: {
        object: {
          id: "sub_5",
          status: "active",
          customer: "cus_5",
          metadata: {},
          items: { data: [{ price: { id: "price_starter" } }] },
        },
      },
    });

    const res = await POST(webhookRequest("{}", "sig"));

    expect(res.status).toBe(200);
    const call = lastUpdate();
    expect(call.payload.tier).toBe("starter");
    expect(call.col).toBe("stripe_customer_id");
    expect(call.val).toBe("cus_5");
  });
});
