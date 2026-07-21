import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createServiceClient } from "@/lib/supabase/service";
import { getStripe, priceIdForTier } from "@/lib/stripe";
import { getSiteUrl } from "@/lib/env";

export const runtime = "nodejs";

// Creates a Stripe Checkout Session for a Starter or Pro subscription.
export async function POST(request: NextRequest) {
  let tier: "starter" | "pro";
  try {
    const body = (await request.json()) as { tier?: string };
    if (body.tier !== "starter" && body.tier !== "pro") {
      return NextResponse.json({ error: "Invalid tier." }, { status: 400 });
    }
    tier = body.tier;
  } catch {
    return NextResponse.json({ error: "Invalid request body." }, { status: 400 });
  }

  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Not authenticated." }, { status: 401 });
  }

  const priceId = priceIdForTier(tier);
  if (!priceId) {
    return NextResponse.json(
      { error: `No Stripe price configured for tier '${tier}'.` },
      { status: 500 }
    );
  }

  const stripe = getStripe();
  const siteUrl = getSiteUrl();

  // Reuse an existing Stripe customer for this user if we have one on file.
  const service = createServiceClient();
  const { data: existing } = await service
    .from("api_keys")
    .select("stripe_customer_id")
    .eq("user_id", user.id)
    .not("stripe_customer_id", "is", null)
    .limit(1)
    .maybeSingle();

  const existingCustomerId = existing?.stripe_customer_id ?? undefined;

  try {
    const session = await stripe.checkout.sessions.create({
      mode: "subscription",
      line_items: [{ price: priceId, quantity: 1 }],
      client_reference_id: user.id,
      customer: existingCustomerId,
      customer_email: existingCustomerId ? undefined : user.email ?? undefined,
      metadata: { user_id: user.id, tier },
      subscription_data: {
        metadata: { user_id: user.id, tier }
      },
      success_url: `${siteUrl}/dashboard?checkout=success`,
      cancel_url: `${siteUrl}/dashboard?checkout=cancelled`
    });

    return NextResponse.json({ url: session.url });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Stripe error.";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
