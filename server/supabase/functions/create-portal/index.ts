// POST /functions/v1/create-portal  (needs the user's sign-in token)
// Returns {url}: Stripe's customer portal, where they update their card, cancel, or download invoices.

import { admin, json, stripe, userFrom } from "../_shared/common.ts";

Deno.serve(async (req) => {
  const user = await userFrom(req);
  if (!user) return json({ message: "Please sign in." }, 401);

  const { data: row } = await admin
    .from("subscriptions").select("stripe_customer_id").eq("user_id", user.id).maybeSingle();
  if (!row?.stripe_customer_id) return json({ message: "There's no subscription to manage yet." }, 404);

  const portal = await stripe.billingPortal.sessions.create({
    customer: row.stripe_customer_id, return_url: Deno.env.get("PORTAL_RETURN_URL")!,
  });
  return json({ url: portal.url });
});
