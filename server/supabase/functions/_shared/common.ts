// Shared by the four edge functions. Runs on Supabase (Deno), never on the user's PC.
//
// Secrets (supabase secrets set ...): STRIPE_SECRET_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET,
// CHECKOUT_SUCCESS_URL, CHECKOUT_CANCEL_URL, PORTAL_RETURN_URL. SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
// are provided to every function automatically.

import Stripe from "https://esm.sh/stripe@16?target=denonext";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

export const stripe = new Stripe(Deno.env.get("STRIPE_SECRET_KEY")!, {
  apiVersion: "2024-06-20",
  httpClient: Stripe.createFetchHttpClient(),
});

// The service-role client bypasses row-level security. Only ever used here, on the server.
export const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** The signed-in user behind the request's bearer token, or null. */
export async function userFrom(req: Request) {
  const token = (req.headers.get("Authorization") ?? "").replace(/^Bearer\s+/i, "");
  if (!token) return null;
  const { data, error } = await admin.auth.getUser(token);
  return error ? null : data.user;
}

/** Copy a Stripe subscription into our table. Every webhook event ends up here. */
export async function syncSubscription(sub: Stripe.Subscription) {
  const customer = typeof sub.customer === "string" ? sub.customer : sub.customer.id;
  let userId = (sub.metadata?.user_id as string | undefined) ?? null;
  if (!userId) {
    const { data } = await admin.from("subscriptions").select("user_id").eq("stripe_customer_id", customer).maybeSingle();
    userId = data?.user_id ?? null;
  }
  if (!userId) {
    console.error("subscription without a known user", sub.id);
    return;
  }
  const { error } = await admin.from("subscriptions").upsert({
    user_id: userId,
    stripe_customer_id: customer,
    stripe_subscription_id: sub.id,
    status: sub.status,
    current_period_end: new Date(sub.current_period_end * 1000).toISOString(),
    updated_at: new Date().toISOString(),
  });
  if (error) throw error;
}
