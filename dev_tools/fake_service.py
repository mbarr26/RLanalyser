"""A pretend account service for trying the sign-in and upgrade flow on your own PC. Developer tool, not shipped.

    python dev_tools/fake_service.py                    # then, in another window:
    set RLA_SUPABASE_URL=http://127.0.0.1:8765
    set RLA_SUPABASE_KEY=anything
    python rl_analyser.py

It speaks just enough of Supabase's API for account.py (sign up, sign in, refresh, reset, the subscriptions
table and the three Stripe functions) and keeps everything in memory, so restarting it forgets all accounts.
No real emails are sent and no real payments are taken.

    --confirm-email   new accounts must be confirmed first:   http://127.0.0.1:8765/fake/confirm?email=you@example.com
    Pretend to pay:   http://127.0.0.1:8765/fake/pay?email=you@example.com                (becomes Pro for 30 days)
    Other states:     /fake/pay?email=...&status=past_due   |   canceled   |   none
    Fast-forward:     /fake/pay?email=...&days=-5       (period ended 5 days ago)
"""

import argparse
import json
import secrets
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

USERS = {}      # email -> {"password", "confirmed", "id"}
TOKENS = {}     # access token -> email
REFRESH = {}    # refresh token -> email
SUBS = {}       # email -> {"status", "current_period_end"}
OPTIONS = {"confirm": False}


def issue(email):
    access, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    TOKENS[access], REFRESH[refresh] = email, email
    return {"access_token": access, "refresh_token": refresh, "expires_in": 3600, "token_type": "bearer",
            "user": {"id": USERS[email]["id"], "email": email, "email_confirmed_at": "2026-01-01T00:00:00Z"}}


def error(status, code, msg):
    return status, {"error_code": code, "msg": msg}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("  ", self.command, self.path, "->", args[1] if len(args) > 1 else "")

    def reply(self, status, body):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def user(self):
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        return TOKENS.get(token)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}") if length else {}
        except ValueError:
            return {}

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/rest/v1/subscriptions":
            email = self.user()
            if not email:                       # like Supabase: an unknown or expired token is a 401
                return self.reply(401, {"code": "PGRST301", "message": "JWT expired"})
            row = SUBS.get(email)
            return self.reply(200, [row] if row and row["status"] != "none" else [])
        if url.path == "/fake/confirm":
            if q.get("email") in USERS:
                USERS[q["email"]]["confirmed"] = True
            return self.reply(200, {"confirmed": q.get("email")})
        if url.path == "/fake/pay":
            email = q.get("email", "")
            days = int(q.get("days", 30))
            SUBS[email] = {"status": q.get("status", "active"),
                           "current_period_end": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}
            print(f"   >>> {email}: {SUBS[email]}")
            return self.reply(200, SUBS[email])
        self.reply(404, {})

    def do_POST(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        data = self.body()
        email = (data.get("email") or "").strip().lower()

        if url.path == "/auth/v1/signup":
            if email in USERS:
                return self.reply(*error(422, "user_already_exists", "User already registered"))
            if len(data.get("password") or "") < 8:
                return self.reply(*error(422, "weak_password", "Password should be at least 8 characters"))
            USERS[email] = {"password": data["password"], "confirmed": not OPTIONS["confirm"], "id": secrets.token_hex(8)}
            if OPTIONS["confirm"]:
                print(f"   >>> confirm with http://127.0.0.1:{self.server.server_port}/fake/confirm?email={email}")
                return self.reply(200, {"user": {"email": email}})
            return self.reply(200, issue(email))

        if url.path == "/auth/v1/token" and q.get("grant_type") == "password":
            user = USERS.get(email)
            if not user or user["password"] != data.get("password"):
                return self.reply(*error(400, "invalid_credentials", "Invalid login credentials"))
            if not user["confirmed"]:
                return self.reply(*error(400, "email_not_confirmed", "Email not confirmed"))
            return self.reply(200, issue(email))

        if url.path == "/auth/v1/token" and q.get("grant_type") == "refresh_token":
            who = REFRESH.pop(data.get("refresh_token"), None)
            if not who or who not in USERS:
                return self.reply(*error(400, "refresh_token_not_found", "Invalid Refresh Token"))
            return self.reply(200, issue(who))

        if url.path in ("/auth/v1/recover", "/auth/v1/resend"):
            print(f"   >>> (pretend email sent to {email})")
            return self.reply(200, {})
        if url.path == "/auth/v1/logout":
            return self.reply(200, {})

        who = self.user()
        if url.path.startswith("/functions/v1/"):
            if not who:
                return self.reply(401, {"message": "not signed in"})
            name = url.path.rsplit("/", 1)[-1]
            if name == "create-checkout":
                print(f"   >>> checkout opened for {who}. To pay: /fake/pay?email={who}")
                return self.reply(200, {"url": f"https://checkout.stripe.com/c/pay/fake_{USERS[who]['id']}"})
            if name == "create-portal":
                return self.reply(200, {"url": "https://billing.stripe.com/p/session/fake"})
            if name == "delete-account":
                USERS.pop(who, None)
                SUBS.pop(who, None)
                return self.reply(200, {})
        self.reply(404, {})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--confirm-email", action="store_true")
    args = ap.parse_args()
    OPTIONS["confirm"] = args.confirm_email
    print(f"Fake account service on http://127.0.0.1:{args.port}  (email confirmation {'ON' if args.confirm_email else 'off'})")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
