"""A pretend account service: sign-up, sign-in, a pretend Stripe checkout and billing portal. NOT real.

It speaks just enough of Supabase's API for account.py (sign up, sign in, refresh, reset, the subscriptions table
and the Stripe functions), so the whole accounts flow can be tried without any online service. Two uses:

  * Demo build (`release.ps1 -Demo`, or `RLA_DEMO=1` from source): the app starts it on this PC in the background
    (see rl_analyser.py) and shows a DEMO badge. Accounts are saved to demo-accounts.json so a demo sign-in survives
    a restart, like a real one. Nothing goes online and nobody is charged. Anyone can "pay" for Pro on its pretend
    page, so a demo build must never be given to the public.
  * dev_tools/fake_service.py: the same thing as a stand-alone command, in memory, for testing.

Passwords are stored as salted hashes. The service listens on 127.0.0.1 only.
"""

import hashlib
import html
import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

HASH_ROUNDS = 50_000


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), HASH_ROUNDS).hex()


def _error(status, code, msg):
    return status, {"error_code": code, "msg": msg}


class DemoService:
    def __init__(self, persist=None, confirm_email=False, log=None):
        self.persist = Path(persist) if persist else None
        self.confirm_email = confirm_email
        self.log = log or (lambda *args: None)
        self.users, self.tokens, self.refresh, self.subs = {}, {}, {}, {}
        self.httpd = None
        self.port = None
        self._load()

    # ---------- saved state ----------

    def _load(self):
        if not self.persist:
            return
        try:
            data = json.loads(self.persist.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.users, self.tokens = data.get("users", {}), data.get("tokens", {})
        self.refresh, self.subs = data.get("refresh", {}), data.get("subs", {})

    def _save(self):
        if not self.persist:
            return
        try:
            self.persist.write_text(json.dumps({"users": self.users, "tokens": self.tokens,
                                                "refresh": self.refresh, "subs": self.subs}), encoding="utf-8")
        except OSError:
            pass                      # a demo that can't save just forgets its accounts next time

    # ---------- the account logic (called by the HTTP handler) ----------

    def issue(self, email):
        access, refresh = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        self.tokens[access], self.refresh[refresh] = email, email
        self._save()
        return {"access_token": access, "refresh_token": refresh, "expires_in": 3600, "token_type": "bearer",
                "user": {"id": self.users[email]["id"], "email": email, "email_confirmed_at": "2026-01-01T00:00:00Z"}}

    def sign_up(self, email, password):
        if email in self.users:
            return _error(422, "user_already_exists", "User already registered")
        if len(password or "") < 8:
            return _error(422, "weak_password", "Password should be at least 8 characters")
        salt = secrets.token_hex(8)
        self.users[email] = {"salt": salt, "hash": _hash(password, salt), "confirmed": not self.confirm_email,
                             "id": secrets.token_hex(8)}
        if self.confirm_email:
            self._save()
            self.log(f"confirm with http://127.0.0.1:{self.port}/fake/confirm?email={email}")
            return 200, {"user": {"email": email}}
        return 200, self.issue(email)

    def sign_in(self, email, password):
        user = self.users.get(email)
        if not user or user["hash"] != _hash(password or "", user["salt"]):
            return _error(400, "invalid_credentials", "Invalid login credentials")
        if not user["confirmed"]:
            return _error(400, "email_not_confirmed", "Email not confirmed")
        return 200, self.issue(email)

    def refresh_token(self, token):
        who = self.refresh.pop(token, None)
        if not who or who not in self.users:
            return _error(400, "refresh_token_not_found", "Invalid Refresh Token")
        return 200, self.issue(who)

    def set_subscription(self, email, status="active", days=30):
        self.subs[email] = {"status": status,
                            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}
        self._save()
        self.log(f"{email}: {self.subs[email]}")
        return self.subs[email]

    def delete_user(self, email):
        self.users.pop(email, None)
        self.subs.pop(email, None)
        for table in (self.tokens, self.refresh):
            for key in [k for k, v in table.items() if v == email]:
                table.pop(key)
        self._save()

    # ---------- the HTTP side ----------

    def start(self, port=0):
        """Listen on 127.0.0.1 (port 0 = any free port) in a background thread. Returns the port."""
        svc = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                svc.log(self.command, self.path, "->", args[1] if len(args) > 1 else "")

            def reply(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def page(self, title, body, email):
                """A small HTML page standing in for Stripe's. `email` is URL-encoded for the buttons' requests."""
                raw = (
                    "<!doctype html><meta charset='utf-8'><title>" + title + "</title>"
                    "<body style='font-family:Segoe UI,sans-serif;background:#0d0d11;color:#f4f4f7;max-width:480px;margin:12vh auto;padding:0 20px'>"
                    "<h2>" + title + "</h2>" + body +
                    "<p id='msg' style='color:#a78bfa;font-weight:600'></p>"
                    "<p style='color:#868695;font-size:13px'>A pretend page from RL Analyser's demo mode, not Stripe. No money moves.</p>"
                    "<script>async function act(q){await fetch('/fake/pay?email=" + email + "&'+q);"
                    "document.getElementById('msg').textContent='Done. Switch back to RL Analyser: it updates by itself within a few seconds.';}"
                    "</script></body>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def user(self):
                return svc.tokens.get((self.headers.get("Authorization") or "").removeprefix("Bearer "))

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
                    if not email:                   # like Supabase: an unknown or expired token is a 401
                        return self.reply(401, {"code": "PGRST301", "message": "JWT expired"})
                    row = svc.subs.get(email)
                    return self.reply(200, [row] if row and row["status"] != "none" else [])
                if url.path == "/fake/confirm":
                    if q.get("email") in svc.users:
                        svc.users[q["email"]]["confirmed"] = True
                        svc._save()
                    return self.reply(200, {"confirmed": q.get("email")})
                if url.path in ("/fake/checkout", "/fake/portal"):
                    who, encoded = html.escape(q.get("email", "")), quote(q.get("email", ""))
                    if url.path == "/fake/checkout":
                        return self.page("Pretend checkout", f"<p>RL Analyser Pro, $15.99 / month, for <b>{who}</b>.</p>"
                                         "<button style='font-size:16px;padding:10px 22px' onclick=\"act('status=active')\">Pay $15.99 (pretend)</button>",
                                         encoded)
                    return self.page("Pretend billing portal", f"<p>Billing for <b>{who}</b>.</p><p>"
                                     "<button onclick=\"act('status=active&days=30')\">Subscription is fine</button> "
                                     "<button onclick=\"act('status=past_due&days=-1')\">Make the card fail</button> "
                                     "<button onclick=\"act('status=canceled&days=-1')\">Cancel subscription</button></p>", encoded)
                if url.path == "/fake/pay":
                    try:
                        days = int(q.get("days", 30))
                    except ValueError:
                        days = 30
                    return self.reply(200, svc.set_subscription(q.get("email", ""), q.get("status", "active"), days))
                self.reply(404, {})

            def do_POST(self):
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                data = self.body()
                email = (data.get("email") or "").strip().lower()

                if url.path == "/auth/v1/signup":
                    return self.reply(*svc.sign_up(email, data.get("password")))
                if url.path == "/auth/v1/token" and q.get("grant_type") == "password":
                    return self.reply(*svc.sign_in(email, data.get("password")))
                if url.path == "/auth/v1/token" and q.get("grant_type") == "refresh_token":
                    return self.reply(*svc.refresh_token(data.get("refresh_token")))
                if url.path in ("/auth/v1/recover", "/auth/v1/resend"):
                    svc.log(f"(pretend email sent to {email})")
                    return self.reply(200, {})
                if url.path == "/auth/v1/logout":
                    return self.reply(200, {})

                who = self.user()
                if url.path.startswith("/functions/v1/"):
                    if not who:
                        return self.reply(401, {"message": "not signed in"})
                    name = url.path.rsplit("/", 1)[-1]
                    base = f"http://127.0.0.1:{svc.port}"
                    if name == "create-checkout":
                        return self.reply(200, {"url": f"{base}/fake/checkout?email={quote(who)}"})
                    if name == "create-portal":
                        return self.reply(200, {"url": f"{base}/fake/portal?email={quote(who)}"})
                    if name == "delete-account":
                        svc.delete_user(who)
                        return self.reply(200, {})
                self.reply(404, {})

        self.httpd = HTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
