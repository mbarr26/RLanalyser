from datetime import datetime, timedelta

import pytest

import access
import entitlements
import service
from account import AccountError

NOW = datetime(2026, 10, 12, 12, 0)


class StubAccount:
    """Stands in for account.Account (its HTTP behaviour is tested in test_account.py)."""

    def __init__(self, email=None):
        self._email = email
        self.entitlement = {"email": email, "status": "none", "period_end": None, "checked_at": NOW.isoformat()}
        self.fail = None
        self.calls = []

    def email(self):
        return self._email

    def signed_in(self):
        return self._email is not None

    def _maybe_fail(self):
        if self.fail:
            raise AccountError(self.fail[1], self.fail[0])

    def sign_in(self, email, password):
        self.calls.append("sign_in")
        self._maybe_fail()
        self._email = email
        self.entitlement["email"] = email

    def sign_up(self, email, password):
        self._maybe_fail()
        return {"needs_confirmation": True, "email": email}

    def sign_out(self):
        self._email = None

    def fetch_entitlement(self):
        self._maybe_fail()
        return dict(self.entitlement, email=self._email)

    def checkout_url(self):
        self._maybe_fail()
        return "https://checkout.stripe.com/x"

    portal_url = checkout_url

    def delete_account(self):
        self._maybe_fail()
        self._email = None

    def reset_password(self, email):
        self._maybe_fail()

    resend_confirmation = reset_password


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(service, "SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(service, "SUPABASE_ANON_KEY", "k")
    monkeypatch.delenv("RLA_FORCE_PLAN", raising=False)


def make(email=None, config=None):
    store = {"config": config or {}}
    opened = []
    acc = StubAccount(email)
    a = access.Access(acc, lambda: dict(store["config"]), lambda c: store.update(config=c),
                      open_url=opened.append, now=lambda: NOW)
    return a, acc, store, opened


def pro_entitlement(email="me@x.co", checked_ago=timedelta(minutes=5)):
    return {"email": email, "status": "active", "period_end": (NOW + timedelta(days=20)).isoformat(),
            "checked_at": (NOW - checked_ago).isoformat()}


def test_signed_out_user_must_sign_in():
    a, *_ = make()
    assert a.needs_sign_in() and a.state()["needsSignIn"] and not a.allowed("coach")


def test_free_user_gets_free_features_only():
    a, *_ = make("me@x.co")
    s = a.state()
    assert s["plan"] == "free" and not s["needsSignIn"]
    assert s["features"]["coach"] is False and a.history_limit() == 10


def test_pro_user_gets_everything():
    a, *_ = make("me@x.co", {"entitlement": pro_entitlement()})
    assert a.state()["plan"] == "pro" and all(a.state()["features"].values()) and a.history_limit() is None


def test_another_users_cached_pro_is_ignored():
    a, *_ = make("me@x.co", {"entitlement": pro_entitlement(email="someone-else@x.co")})
    assert a.plan_state()["plan"] == "free"


def test_unconfigured_build_locks_nothing_and_needs_no_sign_in(monkeypatch):
    monkeypatch.setattr(service, "SUPABASE_URL", "")
    a, *_ = make()
    assert not a.needs_sign_in() and a.plan_state()["reason"] == "unconfigured" and a.allowed("coach")


def test_forced_free_plan_works_even_when_unconfigured(monkeypatch):
    monkeypatch.setattr(service, "SUPABASE_URL", "")
    monkeypatch.setenv("RLA_FORCE_PLAN", "free")
    a, *_ = make()
    assert not a.allowed("coach") and a.history_limit() == 10


def test_sign_in_stores_the_entitlement():
    a, acc, store, _ = make()
    acc.entitlement["status"] = "active"
    acc.entitlement["period_end"] = (NOW + timedelta(days=5)).isoformat()
    state = a.sign_in("me@x.co", "pw")
    assert state["plan"] == "pro" and state["email"] == "me@x.co"
    assert store["config"]["entitlement"]["status"] == "active"


def test_sign_in_error_is_passed_on():
    a, acc, *_ = make()
    acc.fail = ("invalid_credentials", "Wrong email or password.")
    assert a.sign_in("me@x.co", "bad") == {"error": "Wrong email or password.", "code": "invalid_credentials"}


def test_offline_refresh_keeps_the_cached_entitlement():
    a, acc, store, _ = make("me@x.co", {"entitlement": pro_entitlement(checked_ago=timedelta(days=2))})
    acc.fail = ("offline", "Can't reach the server.")
    state = a.refresh()
    assert "error" not in state and state["plan"] == "pro" and state["reason"] == "offline"


def test_expired_session_is_reported_on_refresh():
    a, acc, *_ = make("me@x.co")
    acc.fail = ("session_expired", "Please sign in again.")
    assert a.refresh()["code"] == "session_expired"


def test_sign_out_clears_everything():
    a, acc, store, _ = make("me@x.co", {"entitlement": pro_entitlement(), "replay_dir": "C:/r"})
    state = a.sign_out()
    assert state["needsSignIn"] and "entitlement" not in store["config"] and store["config"]["replay_dir"] == "C:/r"


def test_sign_up_needs_confirmation():
    a, *_ = make()
    assert a.sign_up("new@x.co", "longenough1") == {"needsConfirmation": True, "email": "new@x.co"}


def test_checkout_and_portal_open_the_browser():
    a, acc, _, opened = make("me@x.co")
    assert a.open_checkout() == {"opened": True} and a.open_portal() == {"opened": True}
    assert opened == ["https://checkout.stripe.com/x"] * 2


def test_checkout_error_does_not_open_anything():
    a, acc, _, opened = make("me@x.co")
    acc.fail = ("offline", "Can't reach the server.")
    assert a.open_checkout()["code"] == "offline" and opened == []


def test_delete_account_forgets_entitlement():
    a, acc, store, _ = make("me@x.co", {"entitlement": pro_entitlement()})
    assert a.delete_account()["needsSignIn"] and "entitlement" not in store["config"]


def test_needs_recheck():
    assert make("me@x.co")[0].needs_recheck()
    assert not make("me@x.co", {"entitlement": pro_entitlement()})[0].needs_recheck()
    assert not make()[0].needs_recheck()
