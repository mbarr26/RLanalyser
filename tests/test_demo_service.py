import pytest

import service
from account import Account, AccountError, MemoryStore
from demo_service import DemoService


@pytest.fixture
def demo(tmp_path):
    svc = DemoService(tmp_path / "demo-accounts.json")
    svc.start()
    yield svc
    svc.stop()


def client(svc, session=None):
    return Account(f"http://127.0.0.1:{svc.port}", "demo", MemoryStore(session))


def test_full_account_flow_against_the_demo_service(demo):
    acc = client(demo)
    assert acc.sign_up("me@example.com", "Sup3rSecret!")["needs_confirmation"] is False
    assert acc.fetch_entitlement()["status"] == "none"
    demo.set_subscription("me@example.com")
    assert acc.fetch_entitlement()["status"] == "active"
    assert acc.checkout_url().startswith(f"http://127.0.0.1:{demo.port}/fake/checkout")
    assert acc.portal_url().endswith("me%40example.com")


def test_wrong_password_and_duplicate_signup(demo):
    acc = client(demo)
    acc.sign_up("me@example.com", "Sup3rSecret!")
    with pytest.raises(AccountError) as e:
        client(demo).sign_in("me@example.com", "not-it-at-all")
    assert e.value.code == "invalid_credentials"
    with pytest.raises(AccountError) as e:
        client(demo).sign_up("me@example.com", "Sup3rSecret!")
    assert e.value.code == "user_already_exists"


def test_accounts_and_sessions_survive_a_restart(tmp_path):
    path = tmp_path / "demo-accounts.json"
    first = DemoService(path)
    first.start()
    acc = client(first)
    acc.sign_up("me@example.com", "Sup3rSecret!")
    first.set_subscription("me@example.com")
    session = acc.session()
    first.stop()

    second = DemoService(path)
    second.start()
    try:
        assert client(second).sign_in("me@example.com", "Sup3rSecret!")["email"] == "me@example.com"
        # the sign-in saved before the restart still works, like a real one
        assert client(second, session).fetch_entitlement()["status"] == "active"
    finally:
        second.stop()


def test_passwords_are_not_stored_in_plain_text(tmp_path):
    path = tmp_path / "demo-accounts.json"
    svc = DemoService(path)
    svc.start()
    try:
        client(svc).sign_up("me@example.com", "Sup3rSecret!")
    finally:
        svc.stop()
    assert "Sup3rSecret!" not in path.read_text()


def test_delete_account_removes_everything(demo):
    acc = client(demo)
    acc.sign_up("me@example.com", "Sup3rSecret!")
    acc.delete_account()
    with pytest.raises(AccountError):
        client(demo).sign_in("me@example.com", "Sup3rSecret!")


def test_unknown_token_is_a_401_so_the_app_signs_out(demo):
    stale = {"access_token": "nope", "refresh_token": "nope", "expires_at": "2999-01-01T00:00:00", "email": "x@y.zz"}
    with pytest.raises(AccountError) as e:
        client(demo, stale).fetch_entitlement()
    assert e.value.code == "session_expired"


# ---- the demo switch in service.py ----

@pytest.fixture
def clean_service(monkeypatch):
    monkeypatch.setattr(service, "SUPABASE_URL", "")
    monkeypatch.setattr(service, "SUPABASE_ANON_KEY", "")
    monkeypatch.setattr(service, "DEMO_ACTIVE", False)


def test_start_demo_points_the_app_at_the_pretend_service(clean_service, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "DEMO", True)
    svc = service.start_demo(tmp_path / "d.json")
    try:
        assert svc is not None and service.DEMO_ACTIVE and service.configured()
        assert service.SUPABASE_URL == f"http://127.0.0.1:{svc.port}"
    finally:
        svc.stop()


def test_a_normal_build_never_starts_the_pretend_service(clean_service, monkeypatch, tmp_path):
    monkeypatch.setattr(service, "DEMO", False)
    assert service.start_demo(tmp_path / "d.json") is None
    assert not service.DEMO_ACTIVE and not service.configured()


def test_a_real_service_always_wins_over_demo(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "DEMO", True)
    monkeypatch.setattr(service, "SUPABASE_URL", "https://real.supabase.co")
    monkeypatch.setattr(service, "SUPABASE_ANON_KEY", "k")
    monkeypatch.setattr(service, "DEMO_ACTIVE", False)
    assert service.start_demo(tmp_path / "d.json") is None and not service.DEMO_ACTIVE


def test_account_follows_the_app_service_settings(clean_service, monkeypatch):
    acc = Account(store=MemoryStore())
    assert acc.base == ""
    monkeypatch.setattr(service, "SUPABASE_URL", "https://x.supabase.co/")
    assert acc.base == "https://x.supabase.co"
