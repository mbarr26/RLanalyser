"""Where the account service lives and what the subscription costs. Constants only.

Fill these in once the Supabase project and Stripe product exist (see server/README.md). The anon key is
*meant* to be public (it can only do what the database's row-level security allows), so it is safe to ship.
NEVER put a Stripe secret key or the Supabase service-role key in this file: those live only in the
server's function settings.

While SUPABASE_URL is empty the app has no accounts to talk to, so it skips the sign-in page and behaves as
before (everything unlocked). Don't release with it empty.
"""

import os

# e.g. "https://abcdefgh.supabase.co"; env vars let a test run point at a fake server
SUPABASE_URL = os.environ.get("RLA_SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("RLA_SUPABASE_KEY", "")

PRICE_TEXT = "$15.99 / month"
PLAN_NAME = "RL Analyser Pro"

# Shown on the landing page and required by Stripe before going live
TERMS_URL = ""
PRIVACY_URL = ""
SUPPORT_EMAIL = ""


def configured():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)
