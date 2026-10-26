"""Registration policy (open / invite / closed) and the generic duplicate-email response."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.db import SessionLocal
from app.models import User, UserSession
from tests.conftest import make_client, signed_up

PW = "long-enough-pw"


def _register(c, email: str, **extra):
    return c.post("/api/auth/register", json={"email": email, "password": PW, **extra})


def _account_exists(email: str) -> bool:
    with SessionLocal() as db:
        return db.query(User).filter_by(email=email).first() is not None


def _session_count() -> int:
    with SessionLocal() as db:
        return db.query(UserSession).count()


@pytest.fixture
def mode(settings, monkeypatch):
    def set_mode(value: str, invite_code: str = "") -> None:
        monkeypatch.setattr(settings, "registration", value)
        monkeypatch.setattr(settings, "invite_code", invite_code)

    return set_mode


def test_open_registration_needs_no_invite_code(mode):
    mode("open")
    c = make_client()
    r = _register(c, "open@example.com")
    assert r.status_code == 202 and _account_exists("open@example.com")
    assert c.post("/api/auth/login", json={"email": "open@example.com", "password": PW}).status_code == 200


def test_invite_registration_with_the_right_code(mode):
    mode("invite", "s3cret-invite")
    r = _register(make_client(), "invited@example.com", invite_code="s3cret-invite")
    assert r.status_code == 202 and _account_exists("invited@example.com")


@pytest.mark.parametrize("supplied", [None, "", "wrong-code", "s3cret-invit", "s3cret-invite-x"])
def test_invite_registration_rejects_missing_or_wrong_codes(mode, supplied):
    mode("invite", "s3cret-invite")
    sessions = _session_count()
    extra = {} if supplied is None else {"invite_code": supplied}
    r = _register(make_client(), "uninvited@example.com", **extra)
    assert r.status_code == 403 and "invite code" in r.json()["detail"]
    assert not _account_exists("uninvited@example.com") and _session_count() == sessions


@pytest.mark.parametrize("supplied", [None, ""])
def test_invite_mode_without_a_configured_code_fails_closed(mode, supplied):
    mode("invite", "")
    extra = {} if supplied is None else {"invite_code": supplied}
    r = _register(make_client(), "nocode@example.com", **extra)
    assert r.status_code == 403 and "no invite code" in r.json()["detail"]
    assert not _account_exists("nocode@example.com")


def test_closed_registration_creates_nothing(mode):
    mode("closed", "even-with-a-code")
    sessions = _session_count()
    c = make_client()
    r = _register(c, "closed@example.com", invite_code="even-with-a-code")
    assert r.status_code == 403 and r.json()["detail"] == "Registration is closed on this server."
    assert "set-cookie" not in r.headers
    assert not _account_exists("closed@example.com") and _session_count() == sessions


@pytest.mark.parametrize("value", ["invite", "closed"])
def test_existing_accounts_can_still_sign_in(mode, value):
    c = signed_up(f"existing-{value}@example.com", PW)  # created while registration was open
    assert c.post("/api/auth/logout").status_code == 204
    mode(value, "some-code")
    r = c.post("/api/auth/login", json={"email": f"existing-{value}@example.com", "password": PW})
    assert r.status_code == 200 and c.get("/api/auth/me").status_code == 200


def test_duplicate_email_gets_the_same_answer_as_a_new_one(mode):
    mode("open")
    c = make_client()
    new = _register(c, "dup@example.com")
    again = c.post("/api/auth/register", json={"email": "DUP@example.com", "password": "another-password"})
    assert (new.status_code, new.json()) == (again.status_code, again.json())
    assert "set-cookie" not in again.headers
    # The original account is untouched: its password still works, the new one does not.
    assert c.post("/api/auth/login", json={"email": "dup@example.com", "password": PW}).status_code == 200
    assert (
        c.post("/api/auth/login", json={"email": "dup@example.com", "password": "another-password"}).status_code == 401
    )


def test_public_settings_show_the_mode_but_never_the_code(mode):
    mode("invite", "top-secret-invite")
    r = make_client().get("/api/settings")
    assert r.json()["registration"] == "invite"
    assert "top-secret-invite" not in r.text and "invite_code" not in r.text


def test_defaults_depend_on_the_environment():
    assert Settings(env="development", registration=None).registration_mode == "open"
    assert Settings(env="production", registration=None).registration_mode == "invite"
    assert Settings(env="staging", registration="").registration_mode == "invite"
    assert Settings(env="production", registration=" Closed ").registration_mode == "closed"


@pytest.mark.parametrize("bad", ["yes", "public", "invite-only", "1"])
def test_invalid_registration_setting_is_rejected(bad):
    with pytest.raises(ValidationError):
        Settings(registration=bad)
