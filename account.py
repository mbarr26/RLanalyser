"""Accounts: sign up, sign in, sign out, and ask the server what the user has paid for.

Talks to a Supabase project over HTTPS with `urllib` (same style as updater.py): its Auth API for the
account and three small edge functions for Stripe (create-checkout, create-portal, delete-account). The
app only ever holds the public anon key; card details and the Stripe secret key never touch this PC.

The session (access + refresh token) is kept in the Windows Credential Manager through `keyring`, never in
config.json. If no secure store is available the session just lasts until the app closes. Tokens are never
logged or put in an error message. No UI here.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import service
from version import APP_VERSION

TIMEOUT = 20
USER_AGENT = f"RLAnalyser/{APP_VERSION}"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
REFRESH_MARGIN = timedelta(seconds=60)
MIN_PASSWORD = 8
KEYRING_SERVICE, KEYRING_USER = "RLAnalyser", "session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class AccountError(Exception):
    """Something the user should be told about. `code` lets the page react (e.g. show the verify screen)."""

    def __init__(self, message, code="error"):
        super().__init__(message)
        self.code = code


# what Supabase's error codes / messages mean to a person
FRIENDLY = {
    "invalid_credentials": "Wrong email or password.",
    "email_not_confirmed": "Please confirm your email first. We sent you a link when you signed up.",
    "user_already_exists": "There is already an account with that email. Try signing in.",
    "weak_password": "That password is too easy to guess. Use at least 8 characters with a mix of letters and numbers.",
    "over_request_rate_limit": "Too many attempts. Please wait a minute and try again.",
    "over_email_send_rate_limit": "We've sent a few emails already. Please wait a few minutes before asking for another.",
    "signup_disabled": "New accounts are switched off right now.",
    "validation_failed": "That doesn't look right. Check the email and password.",
}


def validate_credentials(email, password, check_strength=True):
    """Errors to show before we even ask the server (a list of messages, empty when fine)."""
    problems = []
    if not EMAIL_RE.match((email or "").strip()):
        problems.append("Enter a valid email address.")
    if check_strength:
        if len(password or "") < MIN_PASSWORD:
            problems.append(f"Use at least {MIN_PASSWORD} characters for your password.")
    elif not password:
        problems.append("Enter your password.")
    return problems


def password_hint(password):
    """A short strength hint for the sign-up form: ("weak" | "ok" | "strong", text)."""
    password = password or ""
    kinds = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
    if len(password) < MIN_PASSWORD:
        return "weak", f"At least {MIN_PASSWORD} characters"
    if len(password) >= 12 and kinds >= 3:
        return "strong", "Strong"
    if kinds >= 2:
        return "ok", "Good. Longer is stronger"
    return "weak", "Add numbers or capital letters"


# ---------- where the session is kept ----------

class KeyringStore:
    """The Windows Credential Manager. Falls back to memory (until the app closes) if it can't be used."""

    def __init__(self):
        self._memory = None

    def load(self):
        try:
            import keyring
            raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
            return json.loads(raw) if raw else self._memory
        except Exception:
            return self._memory

    def save(self, session):
        self._memory = session
        try:
            import keyring
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, json.dumps(session))
        except Exception:
            pass

    def clear(self):
        self._memory = None
        try:
            import keyring
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass


class MemoryStore:
    def __init__(self, session=None):
        self.session = session

    def load(self):
        return self.session

    def save(self, session):
        self.session = session

    def clear(self):
        self.session = None


# ---------- the client ----------

class Account:
    def __init__(self, base_url=None, anon_key=None, store=None, now=datetime.now):
        self._base, self._key = base_url, anon_key     # None = read the app's service settings each time
        self.store = store or KeyringStore()
        self.now = now

    # --- plumbing ---

    @property
    def base(self):
        return (self._base if self._base is not None else service.SUPABASE_URL).rstrip("/")

    @base.setter
    def base(self, value):
        self._base = value

    @property
    def key(self):
        return self._key if self._key is not None else service.SUPABASE_ANON_KEY

    def _check_url(self, url):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https" or (parsed.scheme == "http" and (parsed.hostname or "") in LOCAL_HOSTS):
            return
        raise AccountError("The account service address must start with https://.", "config")

    def _request(self, method, path, body=None, token=None):
        if not self.base:
            raise AccountError("Accounts aren't set up in this build yet.", "config")
        url = self.base + path
        self._check_url(url)
        headers = {"apikey": self.key, "User-Agent": USER_AGENT, "Content-Type": "application/json",
                   "Authorization": f"Bearer {token or self.key}"}
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise self._http_error(e) from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise AccountError("Can't reach the server. Check your internet connection and try again.", "offline") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise AccountError("The server sent something we couldn't read. Please try again.", "bad_response") from None

    @staticmethod
    def _http_error(e):
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        code = str(payload.get("error_code") or payload.get("code") or "")
        text = str(payload.get("msg") or payload.get("message") or payload.get("error_description") or "")
        if not code and "already registered" in text.lower():
            code = "user_already_exists"
        if not code and "not confirmed" in text.lower():
            code = "email_not_confirmed"
        if not code and "invalid login" in text.lower():
            code = "invalid_credentials"
        if e.code == 429 and not code:
            code = "over_request_rate_limit"
        if code in FRIENDLY:
            return AccountError(FRIENDLY[code], code)
        if e.code in (401, 403):
            return AccountError("Your sign-in has expired. Please sign in again.", "session_expired")
        if e.code >= 500:
            return AccountError("The account server is having a problem. Please try again in a moment.", "server")
        return AccountError(text or f"The server refused that ({e.code}).", code or "error")

    # --- session ---

    def session(self):
        return self.store.load()

    def email(self):
        return (self.session() or {}).get("email")

    def signed_in(self):
        return bool(self.session())

    def _save(self, token_response, email=None):
        user = token_response.get("user") or {}
        expires_in = int(token_response.get("expires_in") or 3600)
        self.store.save({
            "access_token": token_response["access_token"], "refresh_token": token_response["refresh_token"],
            "expires_at": (self.now() + timedelta(seconds=expires_in)).isoformat(),
            "email": user.get("email") or email or (self.session() or {}).get("email"),
        })

    def token(self):
        """A valid access token, refreshed first if it's about to expire. Raises session_expired if it can't be."""
        s = self.session()
        if not s:
            raise AccountError("Please sign in.", "session_expired")
        if datetime.fromisoformat(s["expires_at"]) - self.now() > REFRESH_MARGIN:
            return s["access_token"]
        try:
            resp = self._request("POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": s["refresh_token"]})
        except AccountError as e:
            if e.code in ("offline", "server"):
                raise
            self.store.clear()          # the refresh token was refused: the sign-in is over
            raise AccountError("Your sign-in has expired. Please sign in again.", "session_expired") from None
        self._save(resp, s.get("email"))
        return self.session()["access_token"]

    # --- account actions ---

    def sign_up(self, email, password):
        """Create an account. Returns {"needs_confirmation": True} when an email link must be clicked first."""
        problems = validate_credentials(email, password)
        if problems:
            raise AccountError(" ".join(problems), "validation_failed")
        email = email.strip()
        resp = self._request("POST", "/auth/v1/signup", {"email": email, "password": password})
        if resp.get("access_token"):           # the project doesn't require email confirmation
            self._save(resp, email)
            return {"needs_confirmation": False, "email": email}
        return {"needs_confirmation": True, "email": email}

    def sign_in(self, email, password):
        problems = validate_credentials(email, password, check_strength=False)
        if problems:
            raise AccountError(" ".join(problems), "validation_failed")
        resp = self._request("POST", "/auth/v1/token?grant_type=password",
                             {"email": email.strip(), "password": password})
        self._save(resp, email.strip())
        return {"email": self.email()}

    def forget(self):
        """Drop the session on this PC only (the server already says it is no good)."""
        self.store.clear()

    def sign_out(self):
        """Forget the session here, and tell the server (best effort: being offline mustn't block signing out)."""
        s = self.session()
        self.store.clear()
        if s:
            try:
                self._request("POST", "/auth/v1/logout", {}, token=s["access_token"])
            except AccountError:
                pass

    def reset_password(self, email):
        if validate_credentials(email, "x" * MIN_PASSWORD):
            raise AccountError("Enter the email address of your account.", "validation_failed")
        self._request("POST", "/auth/v1/recover", {"email": email.strip()})

    def resend_confirmation(self, email):
        self._request("POST", "/auth/v1/resend", {"type": "signup", "email": email.strip()})

    # --- subscription ---

    def fetch_entitlement(self):
        """What the user has paid for, as entitlements.py expects it."""
        token = self.token()
        rows = self._request("GET", "/rest/v1/subscriptions?select=status,current_period_end&limit=1", token=token)
        row = rows[0] if isinstance(rows, list) and rows else {}
        return {"email": self.email(), "status": row.get("status") or "none",
                "period_end": row.get("current_period_end"), "checked_at": self.now().isoformat()}

    def checkout_url(self):
        return self._function("create-checkout")

    def portal_url(self):
        return self._function("create-portal")

    def delete_account(self):
        """Ask the server to cancel the subscription and delete the account, then forget the session here."""
        self._function("delete-account", expect_url=False)
        self.store.clear()

    def _function(self, name, expect_url=True):
        resp = self._request("POST", f"/functions/v1/{name}", {}, token=self.token())
        if not expect_url:
            return resp
        url = resp.get("url")
        parsed = urllib.parse.urlparse(url or "")
        # Payment pages must be https. The one exception is the pretend service on this PC (dev_tools/fake_service.py),
        # whose pages are local http: allowed only when the account service itself is local.
        local_test = parsed.scheme == "http" and (parsed.hostname or "") in LOCAL_HOSTS             and (urllib.parse.urlparse(self.base).hostname or "") in LOCAL_HOSTS
        if not url or (parsed.scheme != "https" and not local_test):
            raise AccountError("The payment page couldn't be opened. Please try again.", "bad_response")
        return url
