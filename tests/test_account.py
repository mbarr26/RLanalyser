import json
import threading
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import account
from account import Account, AccountError, MemoryStore

NOW = datetime(2026, 10, 12, 12, 0)


class FakeServer:
    """A tiny local stand-in for Supabase: routes are {(method, path-prefix): (status, body)}."""

    def __init__(self):
        self.routes, self.requests = {}, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else None
                outer.requests.append({"method": self.command, "path": self.path, "body": body,
                                       "auth": self.headers.get("Authorization"), "apikey": self.headers.get("apikey")})
                for (method, prefix), reply in outer.routes.items():
                    if method == self.command and self.path.startswith(prefix):
                        status, payload = reply
                        raw = json.dumps(payload).encode()
                        self.send_response(status)
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                        return
                self.send_response(404)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            do_GET = do_POST = _handle

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    try:
        s.close()
    except Exception:
        pass


def make(server, session=None, now=NOW):
    return Account(server.url, "anon-key", MemoryStore(session), now=lambda: now)


def tokens(access="A1", refresh="R1", email="a@b.co"):
    return {"access_token": access, "refresh_token": refresh, "expires_in": 3600, "user": {"email": email}}


def session(expires_in=timedelta(hours=1), access="A1"):
    return {"access_token": access, "refresh_token": "R1", "expires_at": (NOW + expires_in).isoformat(),
            "email": "a@b.co"}


# ---- validation ----

def test_validate_credentials():
    assert account.validate_credentials("a@b.co", "longenough") == []
    assert "valid email" in account.validate_credentials("nope", "longenough")[0]
    assert "at least 8" in account.validate_credentials("a@b.co", "short")[0]
    assert account.validate_credentials("a@b.co", "x", check_strength=False) == []
    assert "Enter your password" in account.validate_credentials("a@b.co", "", check_strength=False)[0]


@pytest.mark.parametrize("password,level", [("abc", "weak"), ("abcdefgh", "weak"), ("Abcdefg1", "ok"),
                                            ("Abcdefghij12!", "strong")])
def test_password_hint(password, level):
    assert account.password_hint(password)[0] == level


# ---- sign up / in / out ----

def test_sign_in_stores_session_and_sends_the_public_key(server):
    server.routes[("POST", "/auth/v1/token?grant_type=password")] = (200, tokens())
    acc = make(server)
    assert acc.sign_in(" a@b.co ", "pw") == {"email": "a@b.co"}
    assert acc.signed_in() and acc.session()["access_token"] == "A1"
    req = server.requests[0]
    assert req["body"] == {"email": "a@b.co", "password": "pw"}
    assert req["apikey"] == "anon-key" and req["auth"] == "Bearer anon-key"


def test_sign_in_wrong_password_is_friendly(server):
    server.routes[("POST", "/auth/v1/token")] = (400, {"error_code": "invalid_credentials", "msg": "Invalid login credentials"})
    acc = make(server)
    with pytest.raises(AccountError) as e:
        acc.sign_in("a@b.co", "bad")
    assert e.value.code == "invalid_credentials" and "Wrong email or password" in str(e.value)
    assert not acc.signed_in()


def test_unconfirmed_email_has_its_own_code(server):
    server.routes[("POST", "/auth/v1/token")] = (400, {"error_code": "email_not_confirmed", "msg": "Email not confirmed"})
    with pytest.raises(AccountError) as e:
        make(server).sign_in("a@b.co", "pw")
    assert e.value.code == "email_not_confirmed"


def test_sign_up_needs_confirmation_by_default(server):
    server.routes[("POST", "/auth/v1/signup")] = (200, {"user": {"email": "a@b.co"}})
    acc = make(server)
    assert acc.sign_up("a@b.co", "longenough1") == {"needs_confirmation": True, "email": "a@b.co"}
    assert not acc.signed_in()


def test_sign_up_signs_in_when_confirmation_is_off(server):
    server.routes[("POST", "/auth/v1/signup")] = (200, tokens())
    acc = make(server)
    assert acc.sign_up("a@b.co", "longenough1")["needs_confirmation"] is False
    assert acc.signed_in()


def test_sign_up_existing_email_and_weak_password(server):
    server.routes[("POST", "/auth/v1/signup")] = (422, {"msg": "User already registered"})
    with pytest.raises(AccountError) as e:
        make(server).sign_up("a@b.co", "longenough1")
    assert e.value.code == "user_already_exists"
    server.routes[("POST", "/auth/v1/signup")] = (422, {"error_code": "weak_password", "msg": "x"})
    with pytest.raises(AccountError) as e:
        make(server).sign_up("a@b.co", "longenough1")
    assert e.value.code == "weak_password"


def test_sign_up_validates_before_calling_the_server(server):
    with pytest.raises(AccountError):
        make(server).sign_up("bad", "short")
    assert server.requests == []


def test_sign_out_clears_even_when_offline(server):
    acc = make(server, session())
    server.close()                       # the server is gone
    acc.sign_out()
    assert not acc.signed_in()


def test_sign_out_tells_the_server(server):
    server.routes[("POST", "/auth/v1/logout")] = (204, {})
    acc = make(server, session())
    acc.sign_out()
    assert server.requests[0]["path"] == "/auth/v1/logout" and server.requests[0]["auth"] == "Bearer A1"


def test_reset_password_and_resend(server):
    server.routes[("POST", "/auth/v1/recover")] = (200, {})
    server.routes[("POST", "/auth/v1/resend")] = (200, {})
    acc = make(server)
    acc.reset_password("a@b.co")
    acc.resend_confirmation("a@b.co")
    assert [r["path"] for r in server.requests] == ["/auth/v1/recover", "/auth/v1/resend"]
    with pytest.raises(AccountError):
        acc.reset_password("nonsense")


# ---- tokens ----

def test_fresh_token_is_used_as_is(server):
    assert make(server, session()).token() == "A1"
    assert server.requests == []


def test_expiring_token_is_refreshed(server):
    server.routes[("POST", "/auth/v1/token?grant_type=refresh_token")] = (200, tokens("A2", "R2"))
    acc = make(server, session(expires_in=timedelta(seconds=10)))
    assert acc.token() == "A2"
    assert server.requests[0]["body"] == {"refresh_token": "R1"}
    assert acc.session()["refresh_token"] == "R2" and acc.email() == "a@b.co"


def test_refused_refresh_ends_the_session(server):
    server.routes[("POST", "/auth/v1/token")] = (400, {"error_code": "refresh_token_not_found", "msg": "bad"})
    acc = make(server, session(expires_in=-timedelta(minutes=1)))
    with pytest.raises(AccountError) as e:
        acc.token()
    assert e.value.code == "session_expired" and not acc.signed_in()


def test_offline_refresh_keeps_the_session(server):
    acc = make(server, session(expires_in=-timedelta(minutes=1)))
    server.close()
    with pytest.raises(AccountError) as e:
        acc.token()
    assert e.value.code == "offline" and acc.signed_in()


def test_no_session_means_please_sign_in(server):
    with pytest.raises(AccountError) as e:
        make(server).token()
    assert e.value.code == "session_expired"


# ---- subscription ----

def test_fetch_entitlement_reads_the_subscription_row(server):
    server.routes[("GET", "/rest/v1/subscriptions")] = (200, [{"status": "active", "current_period_end": "2026-11-01T00:00:00+00:00"}])
    ent = make(server, session()).fetch_entitlement()
    assert ent == {"email": "a@b.co", "status": "active", "period_end": "2026-11-01T00:00:00+00:00",
                   "checked_at": NOW.isoformat()}
    assert server.requests[0]["auth"] == "Bearer A1"


def test_fetch_entitlement_without_a_subscription(server):
    server.routes[("GET", "/rest/v1/subscriptions")] = (200, [])
    assert make(server, session()).fetch_entitlement()["status"] == "none"


def test_checkout_and_portal_urls(server):
    server.routes[("POST", "/functions/v1/create-checkout")] = (200, {"url": "https://checkout.stripe.com/c/pay/x"})
    server.routes[("POST", "/functions/v1/create-portal")] = (200, {"url": "https://billing.stripe.com/p/y"})
    acc = make(server, session())
    assert acc.checkout_url().startswith("https://checkout.stripe.com/")
    assert acc.portal_url().startswith("https://billing.stripe.com/")


def test_non_https_payment_url_is_refused(server):
    server.routes[("POST", "/functions/v1/create-checkout")] = (200, {"url": "http://evil.example/pay"})
    with pytest.raises(AccountError):
        make(server, session()).checkout_url()


def test_delete_account_forgets_the_session(server):
    server.routes[("POST", "/functions/v1/delete-account")] = (200, {})
    acc = make(server, session())
    acc.delete_account()
    assert not acc.signed_in()


# ---- safety ----

def test_remote_http_is_refused():
    acc = Account("http://example.com", "k", MemoryStore())
    with pytest.raises(AccountError) as e:
        acc.sign_in("a@b.co", "pw")
    assert e.value.code == "config"


def test_unconfigured_service_says_so():
    with pytest.raises(AccountError) as e:
        Account("", "", MemoryStore()).sign_in("a@b.co", "pw")
    assert e.value.code == "config"


def test_server_error_message_has_no_tokens(server):
    server.routes[("POST", "/auth/v1/token")] = (500, {"msg": "boom A1 R1"})
    with pytest.raises(AccountError) as e:
        make(server, session()).sign_in("a@b.co", "pw")
    assert e.value.code == "server" and "A1" not in str(e.value)
