import { NextResponse, type NextRequest } from "next/server";
import type Stripe from "stripe";
import type { ApiTier } from "@/lib/database.types";
import { createServiceClient } from "@/lib/supabase/service";
import { getStripe, tierForPriceId } from "@/lib/stripe";
import { getStripeWebhookSecret } from "@/lib/env";

export const runtime = "nodejs";
// Stripe needs the raw, unparsed request body to verify the signature.
export const dynamic = "force-dynamic";

// Apply a tier change to every api_key belonging to a user, and persist the
// Stripe identifiers so future events can be reconciled by customer id.
async function applyTierToUser(params: {
  userId: string | null;
  customerId: string | null;
  subscriptionId: string | null;
  tier: ApiTier;
}): Promise<void> {
  const { userId, customerId, subscriptionId, tier } = params;
  const service = createServiceClient();

  const update: {
    tier: ApiTier;
    stripe_customer_id?: string | null;
    stripe_subscription_id?: string | null;
  } = { tier };

  if (customerId !== null) update.stripe_customer_id = customerId;
  if (subscriptionId !== null || tier === "free") {
    update.stripe_subscription_id = subscriptionId;
  }

  // Prefer matching by user id; fall back to the Stripe customer id.
  if (userId) {
    await service.from("api_keys").update(update).eq("user_id", userId);
  } else if (customerId) {
    await service.from("api_keys").update(update).eq("stripe_customer_id", customerId);
  }
}

function priceIdFromSubscription(subscription: Stripe.Subscription): string | null {
  return subscription.items.data[0]?.price?.id ?? null;
}

export async function POST(request: NextRequest) {
  const signature = request.headers.get("stripe-signature");
  if (!signature) {
    return NextResponse.json({ error: "Missing stripe-signature header." }, { status: 400 });
  }

  const rawBody = await request.text();
  const stripe = getStripe();

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(rawBody, signature, getStripeWebhookSecret());
  } catch (err) {
    const message = err instanceof Error ? err.message : "Invalid signature.";
    return NextResponse.json({ error: `Webhook verification failed: ${message}` }, { status: 400 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object as Stripe.Checkout.Session;
        const userId =
          session.metadata?.user_id ?? session.client_reference_id ?? null;
        const customerId =
          typeof session.customer === "string" ? session.customer : null;
        const subscriptionId =
          typeof session.subscription === "string" ? session.subscription : null;

        // Resolve tier from session metadata, else from the subscription's price.
        let tier: ApiTier | null =
          (session.metadata?.tier as ApiTier | undefined) ?? null;
        if (!tier && subscriptionId) {
          const subscription = await stripe.subscriptions.retrieve(subscriptionId);
          tier = tierForPriceId(priceIdFromSubscription(subscription));
        }

        await applyTierToUser({
          userId,
          customerId,
          subscriptionId,
          tier: tier ?? "free"
        });
        break;
      }

      case "customer.subscription.created":
      case "customer.subscription.updated": {
        const subscription = event.data.object as Stripe.Subscription;
        const userId = subscription.metadata?.user_id ?? null;
        const customerId =
          typeof subscription.customer === "string" ? subscription.customer : null;
        const activeStatuses = ["active", "trialing", "past_due"];
        const tier = activeStatuses.includes(subscription.status)
          ? tierForPriceId(priceIdFromSubscription(subscription)) ?? "free"
          : "free";

        await applyTierToUser({
          userId,
          customerId,
          subscriptionId: subscription.id,
          tier
        });
        break;
      }

      case "customer.subscription.deleted": {
        const subscription = event.data.object as Stripe.Subscription;
        const userId = subscription.metadata?.user_id ?? null;
        const customerId =
          typeof subscription.customer === "string" ? subscription.customer : null;

        await applyTierToUser({
          userId,
          customerId,
          subscriptionId: null,
          tier: "free"
        });
        break;
      }

      default:
        // Unhandled event types are acknowledged so Stripe does not retry.
        break;
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Handler error.";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}
