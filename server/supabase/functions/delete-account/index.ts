// POST /functions/v1/delete-account  (needs the user's sign-in token)
// Cancels their subscription straight away (no more charges) and deletes the account. The row in
// `subscriptions` goes with it (on delete cascade). Stripe keeps its own invoice records, as the law requires.

import { admin, json, stripe, userFrom } from "../_shared/common.ts";

Deno.serve(async (req) => {
  const user = await userFrom(req);
  if (!user) return json({ message: "Please sign in." }, 401);

  const { data: row } = await admin
    .from("subscriptions").select("stripe_subscription_id,status").eq("user_id", user.id).maybeSingle();

  if (row?.stripe_subscription_id && ["active", "trialing", "past_due", "unpaid"].includes(row.status)) {
    try {
      await stripe.subscriptions.cancel(row.stripe_subscription_id);
    } catch (e) {
      // If we can't stop the billing, don't delete the account: they'd keep being charged with nowhere to cancel
      console.error("could not cancel subscription", e);
      return json({ message: "We couldn't cancel your subscription, so your account was not deleted. Please try again." }, 502);
    }
  }

  const { error } = await admin.auth.admin.deleteUser(user.id);
  if (error) return json({ message: "We couldn't delete your account. Please try again." }, 500);
  return json({ deleted: true });
});
