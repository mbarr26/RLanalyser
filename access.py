"""The app's view of "who is signed in and what may they do": glues account.py, entitlements.py and config.json.

`rl_analyser.py` creates one `Access` and asks it before every paid action; the page asks `state()` what to
show. Everything returns plain dicts so it can go straight to the page. No UI and no webview here, so it is
unit-tested (tests/test_access.py).

The cached entitlement lives in config.json under "entitlement" (email, status, dates: no tokens; those stay
in the Windows Credential Manager, see account.py). It is only trusted if its email is the signed-in one.
"""

import webbrowser
from datetime import datetime

import entitlements
import service
from account import Account, AccountError


def _problem(e):
    return {"error": str(e), "code": e.code}


class Access:
    def __init__(self, account=None, load_config=None, save_config=None, open_url=None, now=datetime.now):
        self.account = account or Account()
        self._load, self._save = load_config, save_config
        self.open_url = open_url or webbrowser.open
        self.now = now

    # ---------- what the user may do ----------

    def configured(self):
        return service.configured()

    def entitlement(self):
        """The cached entitlement, but only for whoever is signed in now (never another user's)."""
        ent = (self._load() or {}).get("entitlement")
        mine = (self.account.email() or "").lower()
        if not ent or not mine or (ent.get("email") or "").lower() != mine:
            return None
        return ent

    def plan_state(self):
        state = entitlements.describe(self.entitlement(), self.now())
        if state["reason"] == "forced" or self.configured():
            return state
        # No account service in this build yet: nobody can sign in, so don't lock anything
        return {"plan": entitlements.PRO, "reason": "unconfigured", "daysLeft": None}

    def allowed(self, feature):
        return entitlements.FEATURES[feature] == entitlements.FREE or self.plan_state()["plan"] == entitlements.PRO

    def locked(self, feature):
        return entitlements.locked_payload(feature)

    def history_limit(self):
        return None if self.allowed("history") else entitlements.FREE_HISTORY_GAMES

    def needs_sign_in(self):
        return self.configured() and not self.account.signed_in()

    def needs_recheck(self):
        return self.account.signed_in() and entitlements.needs_recheck(self.entitlement(), self.now())

    # ---------- what the page shows ----------

    def state(self):
        plan = self.plan_state()
        ent = self.entitlement() or {}
        return {
            "configured": self.configured(), "demo": service.DEMO_ACTIVE, "needsSignIn": self.needs_sign_in(),
            "signedIn": self.account.signed_in(), "email": self.account.email(),
            "plan": plan["plan"], "reason": plan["reason"], "daysLeft": plan["daysLeft"],
            "status": ent.get("status") or "none", "periodEnd": ent.get("period_end"),
            "price": service.PRICE_TEXT, "planName": service.PLAN_NAME,
            "terms": service.TERMS_URL, "privacy": service.PRIVACY_URL, "support": service.SUPPORT_EMAIL,
            "freeHistory": entitlements.FREE_HISTORY_GAMES,
            "features": {f: self.allowed(f) for f in entitlements.FEATURES},
            "featureNames": entitlements.FEATURE_NAMES,
        }

    # ---------- actions (each returns the new state, or {"error", "code"}) ----------

    def _store(self, ent):
        config = dict(self._load() or {})
        if ent is None:
            config.pop("entitlement", None)
        else:
            config["entitlement"] = ent
        self._save(config)

    def refresh(self):
        """Ask the server what the user has paid for. Being offline keeps the cached answer (and its grace period)."""
        if not self.account.signed_in():
            return self.state()
        try:
            self._store(self.account.fetch_entitlement())
        except AccountError as e:
            if e.code == "session_expired":
                # the server no longer accepts this sign-in (password changed, account deleted, signed out elsewhere)
                self.account.forget()
                self._store(None)
            if e.code not in ("offline", "server"):
                out = self.state()
                out["error"], out["code"] = str(e), e.code
                return out
        return self.state()

    def sign_in(self, email, password):
        try:
            self.account.sign_in(email, password)
        except AccountError as e:
            return _problem(e)
        return self.refresh()

    def sign_up(self, email, password):
        try:
            result = self.account.sign_up(email, password)
        except AccountError as e:
            return _problem(e)
        if not result["needs_confirmation"]:
            return {**self.refresh(), "needsConfirmation": False, "email": result["email"]}
        return {"needsConfirmation": True, "email": result["email"]}

    def sign_out(self):
        self.account.sign_out()
        self._store(None)
        return self.state()

    def reset_password(self, email):
        try:
            self.account.reset_password(email)
        except AccountError as e:
            return _problem(e)
        return {"sent": True}

    def resend_confirmation(self, email):
        try:
            self.account.resend_confirmation(email)
        except AccountError as e:
            return _problem(e)
        return {"sent": True}

    def open_checkout(self):
        return self._open(self.account.checkout_url)

    def open_portal(self):
        return self._open(self.account.portal_url)

    def _open(self, get_url):
        try:
            url = get_url()
        except AccountError as e:
            return _problem(e)
        self.open_url(url)
        return {"opened": True}

    def delete_account(self):
        try:
            self.account.delete_account()
        except AccountError as e:
            return _problem(e)
        self._store(None)
        return self.state()
