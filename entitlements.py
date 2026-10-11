"""What a user may do: the one place that turns "who they are and what they pay" into allowed features.

Pure logic, no network and no UI. `account.py` fetches the entitlement from the server and caches it in
config.json; `rl_analyser.py` asks `can()` before every paid action; the page asks `describe()` what to show.

An entitlement is a small dict the server reports and the app caches:
    {"email": str, "status": "active" | "trialing" | "past_due" | "canceled" | "none",
     "period_end": ISO time the paid month runs to (or None), "checked_at": ISO time we last heard from the server}

Lapse rules (nothing a user saved is ever deleted, a lapsed account just goes back to Free):
  - If the server can't be reached, Pro keeps working for OFFLINE_GRACE after the last good check.
  - "past_due" (Stripe is still retrying the card) keeps Pro for PAST_DUE_GRACE after the period ended.
  - A paid month that has run out is allowed RENEWAL_SLACK for the renewal to reach us.

This is a local app, so these checks can be bypassed by someone who edits the code. They are there to make
paying the easy path, not to be DRM.
"""

import os
from datetime import datetime, timedelta

OFFLINE_GRACE = timedelta(days=7)
PAST_DUE_GRACE = timedelta(days=3)
RENEWAL_SLACK = timedelta(hours=48)
STALE_AFTER = timedelta(hours=24)       # after this long without a check the page shows "offline" (still Pro)
RECHECK_EVERY = timedelta(hours=6)

FREE, PRO = "free", "pro"
FREE_HISTORY_GAMES = 10                 # the progress pages show only the latest this-many games on Free

# feature -> the plan it needs
FEATURES = {
    "coach": PRO,         # AI report and chat
    "goals": PRO,         # weekly goals and training advice
    "benchmarks": PRO,    # rank percentiles
    "share": PRO,         # share cards
    "clips": PRO,         # replay video clips
    "history": PRO,       # progress beyond the latest FREE_HISTORY_GAMES games
}

FEATURE_NAMES = {
    "coach": "The AI coach", "goals": "Weekly goals", "benchmarks": "Rank benchmarks",
    "share": "Share cards", "clips": "Replay clips", "history": "Your full history",
}

PAID_STATUSES = {"active", "trialing"}


def _time(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def describe(entitlement, now=None):
    """Where the account stands: {plan, reason, daysLeft, ...} for the page and for `can`.

    reason is one of "forced" (RLA_FORCE_PLAN, for testing), "paid", "offline" (Pro on the grace period),
    "past_due" (card failing, still Pro for a few days), "lapsed" (was paid, now over), "free".
    """
    forced = os.environ.get("RLA_FORCE_PLAN", "").lower()
    if forced in (FREE, PRO):
        return {"plan": forced, "reason": "forced", "daysLeft": None}

    now = now or datetime.now()
    ent = entitlement or {}
    status = ent.get("status") or "none"
    checked = _time(ent.get("checked_at"))
    period_end = _time(ent.get("period_end"))

    if status not in PAID_STATUSES and status != "past_due":
        return {"plan": FREE, "reason": "lapsed" if status == "canceled" else "free", "daysLeft": None}

    # we only trust what the server said for OFFLINE_GRACE
    if checked is None or now - checked > OFFLINE_GRACE:
        return {"plan": FREE, "reason": "lapsed", "daysLeft": None}
    left = (checked + OFFLINE_GRACE - now).total_seconds() / 86400

    if status == "past_due":
        if period_end is None or now > period_end + PAST_DUE_GRACE:
            return {"plan": FREE, "reason": "lapsed", "daysLeft": None}
        return {"plan": PRO, "reason": "past_due", "daysLeft": max(0.0, (period_end + PAST_DUE_GRACE - now).total_seconds() / 86400)}

    if period_end is not None and now > period_end + RENEWAL_SLACK:
        return {"plan": FREE, "reason": "lapsed", "daysLeft": None}
    if now - checked > STALE_AFTER:
        return {"plan": PRO, "reason": "offline", "daysLeft": max(0.0, left)}
    return {"plan": PRO, "reason": "paid", "daysLeft": None}


def plan_now(entitlement, now=None):
    return describe(entitlement, now)["plan"]


def can(feature, entitlement, now=None):
    """Whether the account may use a feature. An unknown feature name is a bug, so it raises."""
    needed = FEATURES[feature]
    return needed == FREE or plan_now(entitlement, now) == PRO


def locked_payload(feature):
    """What the Api returns instead of data when a feature needs Pro. The page shows the upgrade dialog."""
    return {"locked": feature, "name": FEATURE_NAMES.get(feature, feature)}


def history_limit(entitlement, now=None):
    """How many of the latest games the progress pages may show (None = all of them)."""
    return None if can("history", entitlement, now) else FREE_HISTORY_GAMES


def needs_recheck(entitlement, now=None):
    checked = _time((entitlement or {}).get("checked_at"))
    return checked is None or (now or datetime.now()) - checked > RECHECK_EVERY
