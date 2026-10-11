# The account server (Supabase + Stripe)

This folder is the **online half** of RL Analyser's accounts. The desktop app never talks to Stripe directly:

```
 desktop app ──(email + password)──▶  Supabase Auth        (accounts, email confirmation, password reset)
     │
     ├──(your sign-in token)────────▶  create-checkout  ──▶  Stripe Checkout   (the payment page, in the browser)
     ├──(your sign-in token)────────▶  create-portal    ──▶  Stripe Portal      (update card / cancel / invoices)
     ├──(your sign-in token)────────▶  delete-account                            (cancel + delete)
     └──(reads its own row)─────────▶  subscriptions table  ◀── stripe-webhook ◀── Stripe (paid / failed / ended)
```

What's stored online: the user's **email**, a password **hash** (Supabase), and their **subscription status**.
Replays and stats never leave their PC. Card details only ever touch Stripe.

You'll need free accounts at [supabase.com](https://supabase.com) and [stripe.com](https://stripe.com).
**Do everything below in Stripe's *test mode* first** (the toggle at the top of the Stripe dashboard), and only repeat
with live keys when the "Going live" checklist at the bottom is done.

## 1. Supabase project

1. Create a project (any region near your users). Note two things from **Project settings → API**:
   the **Project URL** and the **anon public** key. These two go into the app (step 5). The **service_role** key is
   a secret: it never goes in the app or in git.
2. **SQL editor** → paste `supabase/migrations/20261011000000_subscriptions.sql` → Run. (Or `supabase db push`.)
3. **Authentication → Providers → Email**: keep it on, turn **Confirm email** ON, set minimum password length to **8**.
4. **Authentication → URL configuration**: set **Site URL** to your website (or any page that says "Email confirmed,
   go back to RL Analyser"), so the confirmation link has somewhere to land.
5. **Authentication → SMTP settings**: Supabase's built-in email sender is limited to a couple of emails an hour.
   Before real users, connect a sender (Resend, Postmark, Brevo...) so confirmation and reset emails always arrive.
6. **Authentication → Rate limits** and **Attack protection** (CAPTCHA) are worth switching on before launch.

## 2. Stripe product

1. **Product catalogue → Add product**: "RL Analyser Pro", **recurring**, **monthly**, **$15.99**. Copy the **Price ID**
   (starts `price_`). You can change the price later by adding a new price and updating the secret below.
2. **Settings → Billing → Customer portal**: switch it on and allow *update payment method*, *cancel subscription*
   and *invoice history*. Add your Terms and Privacy links.
3. **Settings → Billing → Subscriptions and emails**: turn on the emails you want (receipts, failed-payment reminders)
   and set the **retry schedule** for failed cards (Smart Retries is fine). The app gives a card that is failing
   a further 3 days of Pro after the month ends, so keep retries within about a week.
4. Copy your **Secret key** (`sk_test_...`) from **Developers → API keys**.

## 3. Deploy the functions

Install the [Supabase CLI](https://supabase.com/docs/guides/cli), then from this `server/` folder:

```
supabase login
supabase link --project-ref <your project reference>
supabase secrets set STRIPE_SECRET_KEY=sk_test_... STRIPE_PRICE_ID=price_... ^
  CHECKOUT_SUCCESS_URL=https://yoursite.example/thanks CHECKOUT_CANCEL_URL=https://yoursite.example/cancelled ^
  PORTAL_RETURN_URL=https://yoursite.example/thanks
supabase functions deploy create-checkout create-portal delete-account stripe-webhook
```

(`^` is Windows' line continuation; put it all on one line if you prefer.) The success, cancel and return pages are
just pages that tell the user to switch back to the app, which unlocks by itself within seconds. A single static
page is enough for all three.

## 4. The Stripe webhook

1. **Developers → Webhooks → Add endpoint**:
   `https://<your project reference>.supabase.co/functions/v1/stripe-webhook`
2. Select these events: `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`, `invoice.paid`, `invoice.payment_failed`.
3. Copy the endpoint's **Signing secret** (`whsec_...`) and run
   `supabase secrets set STRIPE_WEBHOOK_SECRET=whsec_...`

Nothing is trusted from the webhook until its signature checks out, and it is the only thing that can write to the
`subscriptions` table.

## 5. Point the app at it

Put the two public values from step 1 in `service.py` (or, for a quick test, set the `RLA_SUPABASE_URL` and
`RLA_SUPABASE_KEY` environment variables), and fill in `TERMS_URL`, `PRIVACY_URL` and `SUPPORT_EMAIL`. Until
`SUPABASE_URL` is set the app has no accounts and nothing is locked, so **don't release a build with it empty**.

## 6. Test it (Stripe test mode)

| Try this | Expect |
|---|---|
| Create an account in the app | "Check your email" screen; the link confirms it; signing in works |
| Press **Upgrade**, pay with card `4242 4242 4242 4242`, any future date, any CVC | The app shows "You're Pro" within seconds, no restart |
| Account menu → **Manage subscription** | Stripe's portal opens |
| Cancel in the portal | Still Pro until the month ends, then back to Free with a "subscription ended" banner |
| Card `4000 0000 0000 0341` (fails when charged) | After the first renewal attempt fails, a "payment didn't go through" banner |
| Pull the network cable while Pro | Stays Pro for 7 days with an "offline" banner |
| Account menu → **Delete my account** | Subscription cancelled in Stripe, the account is gone |

You can try the whole app flow **without** Supabase or Stripe using `python dev_tools/fake_service.py` (see its header).

## Going live checklist

- [ ] Terms of Service and Privacy Policy published (what you store: email, password hash, subscription status; Stripe
      keeps payment records; replays stay on the PC; how to delete the account).
- [ ] Stripe account activated (business details, bank account) and **tax** set up (Stripe Tax or your own VAT/sales-tax
      handling). A reseller like Paddle or Lemon Squeezy can do this for you if that is a worry.
- [ ] Swap to **live** keys: new `STRIPE_SECRET_KEY`, a live Price ID, and a live webhook endpoint with its own signing secret.
- [ ] Custom email sender connected in Supabase.
- [ ] A refund / cancellation policy written down (Stripe's portal cancels at the end of the period).
- [ ] `service.py` filled in, a release built, and the installer code-signed if you can (see the main README).

## Cost

Supabase and Stripe both have free starting tiers. Stripe takes about 2.9% + 30c per payment (more for some cards
and countries); that is the main running cost at first.
