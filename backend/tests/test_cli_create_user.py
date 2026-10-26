"""First-account setup for a fresh installation: the operator-only `create-user` command."""

import io

import pytest

from app import cli
from app.core.db import SessionLocal
from app.models import AuditEvent, User
from tests.conftest import _counter, make_client

PW = "first-owner-password"


def _email() -> str:
    return f"owner{next(_counter)}@example.com"


def _run(monkeypatch, capsys, args: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = cli.main(args)
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def registration(settings, monkeypatch):
    def set_mode(mode: str, invite_code: str = "") -> None:
        monkeypatch.setattr(settings, "registration", mode)
        monkeypatch.setattr(settings, "invite_code", invite_code)

    return set_mode


@pytest.mark.parametrize("mode", ["invite", "closed"])
def test_operator_creates_the_first_account_while_public_registration_is_off(registration, monkeypatch, capsys, mode):
    registration(mode)  # invite with no code configured: nobody can register over HTTP
    email = _email()
    assert make_client().post("/api/auth/register", json={"email": email, "password": PW}).status_code == 403

    code, out, err = _run(monkeypatch, capsys, ["create-user", "--email", email.upper(), "--password-stdin"], PW + "\n")
    assert code == 0 and f"Created account {email}" in out and err == ""
    assert PW not in out + err  # the password is never echoed
    c = make_client()
    assert c.post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200
    assert c.get("/api/auth/me").json()["email"] == email


def test_existing_account_is_never_overwritten(monkeypatch, capsys):
    email = _email()
    _run(monkeypatch, capsys, ["create-user", "--email", email, "--password-stdin"], PW)
    code, out, err = _run(
        monkeypatch, capsys, ["create-user", "--email", email, "--password-stdin"], "another-password-1"
    )
    assert code == 1 and "already exists" in err and "nothing was changed" in err
    assert make_client().post("/api/auth/login", json={"email": email, "password": PW}).status_code == 200


@pytest.mark.parametrize(
    ("email", "password"), [("not-an-email", PW), ("ok@example.com", "short"), ("ok@example.com", "")]
)
def test_invalid_details_are_rejected_without_creating_anything(monkeypatch, capsys, email, password):
    with SessionLocal() as db:
        users = db.query(User).count()
    code, _, err = _run(monkeypatch, capsys, ["create-user", "--email", email, "--password-stdin"], password)
    assert code == 1 and "Invalid account details" in err
    with SessionLocal() as db:
        assert db.query(User).count() == users


def test_prompted_passwords_must_match(monkeypatch, capsys):
    answers = iter(["first-owner-password", "different-password"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    email = _email()
    code, _, err = _run(monkeypatch, capsys, ["create-user", "--email", email])
    assert code == 1 and "do not match" in err
    with SessionLocal() as db:
        assert db.query(User).filter_by(email=email).count() == 0


def test_creation_is_audited_without_secrets(monkeypatch, capsys):
    email = _email()
    _run(monkeypatch, capsys, ["create-user", "--email", email, "--password-stdin"], PW)
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        events = [(e.action, e.detail) for e in db.query(AuditEvent).filter_by(user_id=user.id)]
    assert events and events[0][0] == "user.create_cli" and PW not in repr(events)


def test_not_reachable_over_http_and_registration_policies_unchanged(registration):
    c = make_client()
    for path in ["/api/cli/create-user", "/api/auth/create-user", "/api/admin/users"]:
        assert c.post(path, json={"email": _email(), "password": PW}).status_code in (404, 405)
    registration("invite", "")
    assert c.post("/api/auth/register", json={"email": _email(), "password": PW, "invite_code": ""}).status_code == 403
    registration("invite", "the-code")
    assert (
        c.post("/api/auth/register", json={"email": _email(), "password": PW, "invite_code": "the-code"}).status_code
        == 202
    )
    registration("open")
    assert c.post("/api/auth/register", json={"email": _email(), "password": PW}).status_code == 202
