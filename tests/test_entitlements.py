from datetime import datetime, timedelta

import pytest

import entitlements as ent

NOW = datetime(2026, 10, 12, 12, 0)


def paid(checked_ago=timedelta(hours=1), period_in=timedelta(days=20), status="active"):
    return {"email": "a@b.c", "status": status, "checked_at": (NOW - checked_ago).isoformat(),
            "period_end": (NOW + period_in).isoformat()}


@pytest.fixture(autouse=True)
def no_force(monkeypatch):
    monkeypatch.delenv("RLA_FORCE_PLAN", raising=False)


def test_paid_and_fresh_is_pro():
    d = ent.describe(paid(), NOW)
    assert d["plan"] == "pro" and d["reason"] == "paid"


def test_trialing_counts_as_paid():
    assert ent.plan_now(paid(status="trialing"), NOW) == "pro"


def test_no_account_or_no_subscription_is_free():
    assert ent.plan_now(None, NOW) == "free"
    assert ent.plan_now({"status": "none"}, NOW) == "free"
    assert ent.describe({"status": "none"}, NOW)["reason"] == "free"


def test_canceled_is_lapsed_free():
    d = ent.describe(paid(status="canceled"), NOW)
    assert d == {"plan": "free", "reason": "lapsed", "daysLeft": None}


def test_offline_keeps_pro_for_seven_days_then_drops():
    two_days = ent.describe(paid(checked_ago=timedelta(days=2)), NOW)
    assert two_days["plan"] == "pro" and two_days["reason"] == "offline"
    assert 4.9 < two_days["daysLeft"] < 5.1
    assert ent.plan_now(paid(checked_ago=timedelta(days=6, hours=23)), NOW) == "pro"
    assert ent.plan_now(paid(checked_ago=timedelta(days=7, minutes=1)), NOW) == "free"


def test_never_checked_is_not_trusted():
    e = paid()
    e["checked_at"] = None
    assert ent.plan_now(e, NOW) == "free"


def test_period_that_ran_out_gets_renewal_slack():
    inside = paid(period_in=-timedelta(hours=47))
    outside = paid(period_in=-timedelta(hours=49))
    assert ent.plan_now(inside, NOW) == "pro"
    assert ent.plan_now(outside, NOW) == "free"


def test_past_due_is_pro_for_three_days_after_the_period():
    d = ent.describe(paid(status="past_due", period_in=-timedelta(days=1)), NOW)
    assert d["plan"] == "pro" and d["reason"] == "past_due" and 1.9 < d["daysLeft"] < 2.1
    assert ent.plan_now(paid(status="past_due", period_in=-timedelta(days=3, minutes=1)), NOW) == "free"
    assert ent.plan_now({**paid(status="past_due"), "period_end": None}, NOW) == "free"


def test_past_due_still_bounded_by_offline_grace():
    assert ent.plan_now(paid(status="past_due", period_in=-timedelta(hours=1),
                             checked_ago=timedelta(days=8)), NOW) == "free"


def test_bad_timestamps_do_not_crash():
    assert ent.plan_now({"status": "active", "checked_at": "nonsense", "period_end": "x"}, NOW) == "free"


def test_can_gates_every_paid_feature():
    free, pro = {"status": "none"}, paid()
    for feature in ent.FEATURES:
        assert ent.can(feature, free, NOW) is False
        assert ent.can(feature, pro, NOW) is True


def test_unknown_feature_raises():
    with pytest.raises(KeyError):
        ent.can("teleport", None, NOW)


def test_history_limit():
    assert ent.history_limit({"status": "none"}, NOW) == ent.FREE_HISTORY_GAMES == 10
    assert ent.history_limit(paid(), NOW) is None


def test_locked_payload_names_the_feature():
    assert ent.locked_payload("coach") == {"locked": "coach", "name": "The AI coach"}


def test_needs_recheck_after_six_hours():
    assert ent.needs_recheck(None, NOW)
    assert not ent.needs_recheck(paid(checked_ago=timedelta(hours=5)), NOW)
    assert ent.needs_recheck(paid(checked_ago=timedelta(hours=7)), NOW)


def test_forced_plan_for_local_testing(monkeypatch):
    monkeypatch.setenv("RLA_FORCE_PLAN", "pro")
    assert ent.describe(None, NOW) == {"plan": "pro", "reason": "forced", "daysLeft": None}
    monkeypatch.setenv("RLA_FORCE_PLAN", "free")
    assert ent.plan_now(paid(), NOW) == "free"
