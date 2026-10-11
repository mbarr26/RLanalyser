// POST /functions/v1/create-checkout  (needs the user's sign-in token)
// Returns {url}: a Stripe-hosted payment page for RL Analyser Pro. The app opens it in the browser.

import { admin, json, stripe, userFrom } from "../_shared/common.ts";

Deno.serve(async (req) => {
  const user = await userFrom(req);
  if (!user) return json({ message: "Please sign in." }, 401);
  if (!user.email_confirmed_at) return json({ message: "Confirm your email first." }, 403);

  const { data: row } = await admin
    .from("subscriptions").select("stripe_customer_id,status").eq("user_id", user.id).maybeSingle();

  // Already paying (or the card is being retried): send them to manage it instead of charging twice
  if (row && ["active", "trialing", "past_due"].includes(row.status) && row.stripe_customer_id) {
    const portal = await stripe.billingPortal.sessions.create({
      customer: row.stripe_customer_id, return_url: Deno.env.get("PORTAL_RETURN_URL")!,
    });
    return json({ url: portal.url });
  }

  let customer = row?.stripe_customer_id;
  if (!customer) {
    const created = await stripe.customers.create({ email: user.email!, metadata: { user_id: user.id } });
    customer = created.id;
    await admin.from("subscriptions").upsert({ user_id: user.id, stripe_customer_id: customer });
  }

  const session = await stripe.checkout.sessions.create({
    mode: "subscription",
    customer,
    client_reference_id: user.id,
    line_items: [{ price: Deno.env.get("STRIPE_PRICE_ID")!, quantity: 1 }],
    allow_promotion_codes: true,            // lets you hand out free-month codes (e.g. to friends)
    subscription_data: { metadata: { user_id: user.id } },
    success_url: Deno.env.get("CHECKOUT_SUCCESS_URL")!,
    cancel_url: Deno.env.get("CHECKOUT_CANCEL_URL")!,
  });
  return json({ url: session.url });
});
