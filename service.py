"""Where the account service lives and what the subscription costs. Constants only.

Fill these in once the Supabase project and Stripe product exist (see server/README.md). The anon key is
*meant* to be public (it can only do what the database's row-level security allows), so it is safe to ship.
NEVER put a Stripe secret key or the Supabase service-role key in this file: those live only in the
server's function settings.

While SUPABASE_URL is empty the app has no accounts to talk to, so it skips the sign-in page and behaves as
before (everything unlocked). Don't release with it empty.
"""

import os

from paths import bundled

# e.g. "https://abcdefgh.supabase.co"; env vars let a test run point at a fake server
SUPABASE_URL = os.environ.get("RLA_SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("RLA_SUPABASE_KEY", "")

PRICE_TEXT = "$15.99 / month"
PLAN_NAME = "RL Analyser Pro"

# Shown on the landing page and required by Stripe before going live
TERMS_URL = ""
PRIVACY_URL = ""
SUPPORT_EMAIL = ""


# Demo mode: the app runs a pretend account service (demo_service.py) on this PC and shows a DEMO badge, so the whole
# accounts flow can be tried before the real Supabase and Stripe exist. It is switched on by a file named demo.flag
# next to the app (only `release.ps1 -Demo` builds put one there) or by RLA_DEMO=1 when running from source.
# A demo build lets anyone "pay" for Pro on its pretend page, so it must never be given to the public.
DEMO = bool(os.environ.get("RLA_DEMO")) or bundled("demo.flag").is_file()
DEMO_ACTIVE = False     # True once start_demo() has started the pretend service


def configured():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def start_demo(persist_path):
    """Start the pretend account service and point the app at it. Does nothing unless this is a demo build
    that has no real service configured. Returns the DemoService (or None)."""
    global SUPABASE_URL, SUPABASE_ANON_KEY, DEMO_ACTIVE
    if not DEMO or configured():
        return None
    import demo_service
    svc = demo_service.DemoService(persist_path)
    SUPABASE_URL = f"http://127.0.0.1:{svc.start()}"
    SUPABASE_ANON_KEY = "demo"
    DEMO_ACTIVE = True
    return svc
