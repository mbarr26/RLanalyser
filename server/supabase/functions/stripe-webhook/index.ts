// POST /functions/v1/stripe-webhook   (deploy with --no-verify-jwt: Stripe calls it, not a signed-in user)
// Stripe tells us when someone pays, a renewal fails, or a subscription ends. We check the signature, then copy
// the subscription's state into the `subscriptions` table that the desktop app reads.

import { stripe, syncSubscription } from "../_shared/common.ts";

Deno.serve(async (req) => {
  const signature = req.headers.get("stripe-signature");
  if (!signature) return new Response("missing signature", { status: 400 });

  let event;
  try {
    // The raw body is needed for the signature check, so read it as text and don't parse it first
    event = await stripe.webhooks.constructEventAsync(
      await req.text(), signature, Deno.env.get("STRIPE_WEBHOOK_SECRET")!,
    );
  } catch (e) {
    console.error("bad signature", e);
    return new Response("bad signature", { status: 400 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed": {
        const session = event.data.object;
        if (session.subscription) {
          const id = typeof session.subscription === "string" ? session.subscription : session.subscription.id;
          await syncSubscription(await stripe.subscriptions.retrieve(id));
        }
        break;
      }
      case "customer.subscription.created":
      case "customer.subscription.updated":
      case "customer.subscription.deleted":
        await syncSubscription(event.data.object);
        break;
      case "invoice.paid":
      case "invoice.payment_failed": {
        const invoice = event.data.object;
        if (invoice.subscription) {
          const id = typeof invoice.subscription === "string" ? invoice.subscription : invoice.subscription.id;
          await syncSubscription(await stripe.subscriptions.retrieve(id));
        }
        break;
      }
      default:
        break;                       // events we don't care about are acknowledged and ignored
    }
  } catch (e) {
    console.error("webhook handling failed", event.type, e);
    return new Response("handler error", { status: 500 });      // Stripe will retry
  }
  return new Response("ok", { status: 200 });
});
