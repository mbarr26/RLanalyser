-- RL Analyser: the one table the app reads. Run this once in the Supabase SQL editor.
--
-- The desktop app can only READ its own row (row-level security). Nothing on the user's PC can write to it:
-- the Stripe webhook function writes it with the service-role key, which never leaves the server.

create table if not exists public.subscriptions (
  user_id                uuid primary key references auth.users (id) on delete cascade,
  stripe_customer_id     text unique,
  stripe_subscription_id text,
  -- Stripe's own words: active, trialing, past_due, canceled, unpaid, incomplete ... or 'none' before they pay.
  -- The app treats active/trialing as Pro, past_due as Pro for a few more days, everything else as Free.
  status                 text not null default 'none',
  current_period_end     timestamptz,
  updated_at             timestamptz not null default now()
);

alter table public.subscriptions enable row level security;

drop policy if exists "read own subscription" on public.subscriptions;
create policy "read own subscription"
  on public.subscriptions for select
  using (auth.uid() = user_id);

-- Deliberately no insert / update / delete policies: only the service role (which bypasses RLS) can write.
