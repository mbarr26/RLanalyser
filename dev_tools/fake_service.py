"""A pretend account service for trying the sign-in and upgrade flow on your own PC. Developer tool, not shipped.

    python dev_tools/fake_service.py                    # then, in another window:
    set RLA_SUPABASE_URL=http://127.0.0.1:8765
    set RLA_SUPABASE_KEY=anything
    python rl_analyser.py

This is demo_service.py (see its header) run on its own, in memory: restarting it forgets all accounts. For the
simplest way to try the flow, set RLA_DEMO=1 (or double-click try_accounts.bat): the app then runs the same service
inside itself. No real emails are sent and no real payments are taken.

    --confirm-email   new accounts must be confirmed first:   http://127.0.0.1:8765/fake/confirm?email=you@example.com
    Pretend to pay:   http://127.0.0.1:8765/fake/pay?email=you@example.com                (becomes Pro for 30 days)
    Other states:     /fake/pay?email=...&status=past_due   |   canceled   |   none
    Fast-forward:     /fake/pay?email=...&days=-5       (period ended 5 days ago)
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo_service import DemoService  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--confirm-email", action="store_true")
    args = ap.parse_args()
    service = DemoService(confirm_email=args.confirm_email, log=lambda *a: print("  ", *a, flush=True))
    port = service.start(args.port)
    print(f"Fake account service on http://127.0.0.1:{port}  (email confirmation {'ON' if args.confirm_email else 'off'})", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        service.stop()


if __name__ == "__main__":
    main()
