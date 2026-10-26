"""GitHub disconnect: local credentials go first, then the GitHub grant is revoked if GitHub agrees."""

from datetime import timedelta

import httpx
import pytest

from app.core.db import SessionLocal
from app.core.security import encrypt_secret
from app.integrations import github
from app.models import AuditEvent, GitHubAccount, User, utcnow
from tests.conftest import make_client


def _connect(client, *, expires_in=timedelta(hours=8), refresh="ghr_refresh") -> None:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        db.query(GitHubAccount).filter_by(user_id=user.id).delete()
        db.add(
            GitHubAccount(
                user_id=user.id,
                github_login="octo",
                encrypted_token=encrypt_secret("ghu_access"),
                encrypted_refresh_token=encrypt_secret(refresh) if refresh else None,
                token_expires_at=utcnow() + expires_in,
                refresh_expires_at=utcnow() + timedelta(days=180),
            )
        )
        db.commit()


def _stored(client) -> bool:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        return db.query(GitHubAccount).filter_by(user_id=user.id).count() > 0


@pytest.fixture
def revocations(monkeypatch):
    """Records tokens sent to GitHub's revoke endpoint; set `.result` to choose GitHub's answer."""

    class Calls(list):
        result = True

    calls = Calls()

    def fake_revoke(settings, token, transport=None):
        calls.append(token)
        return calls.result

    monkeypatch.setattr(github, "revoke_grant", fake_revoke)
    return calls


def test_disconnect_deletes_local_tokens_and_reports_confirmed_revocation(client, revocations):
    _connect(client)
    r = client.delete("/api/github/account")
    body = r.json()
    assert r.status_code == 200 and body["local_credentials_deleted"] and body["github_grant_revoked"]
    assert "GitHub confirmed" in body["detail"]
    assert revocations == ["ghu_access"]
    assert not _stored(client)  # access and refresh tokens are gone with the row
    assert client.get("/api/github/status").json()["connected"] is False
    r = client.get("/api/github/repos")
    assert r.status_code == 400 and "Connect a GitHub account" in r.json()["detail"]


def test_github_failure_still_deletes_local_tokens(client, revocations):
    _connect(client)
    revocations.result = False  # what revoke_grant returns for any non-204 answer or network error
    body = client.delete("/api/github/account").json()
    assert body["local_credentials_deleted"] is True and body["github_grant_revoked"] is False
    assert "did not confirm" in body["detail"] and "github.com/settings/apps/authorizations" in body["detail"]
    assert not _stored(client)


def test_repeated_disconnect_is_safe(client, revocations):
    _connect(client)
    client.delete("/api/github/account")
    r = client.delete("/api/github/account")
    assert r.status_code == 200
    assert r.json() == {
        "local_credentials_deleted": False,
        "github_grant_revoked": False,
        "detail": "No GitHub account is connected.",
    }
    assert len(revocations) == 1  # GitHub is not called again


def test_disconnect_only_affects_the_caller(client, other_client, revocations):
    _connect(client)
    r = other_client.delete("/api/github/account")
    assert r.json()["local_credentials_deleted"] is False
    assert _stored(client) and revocations == []
    assert make_client().delete("/api/github/account").status_code == 401  # not signed in


def test_expired_access_token_is_refreshed_once_for_revocation_but_not_stored(client, revocations, monkeypatch):
    _connect(client, expires_in=timedelta(hours=-1))
    monkeypatch.setattr(
        github,
        "_token_request",
        lambda s, data, transport=None: {"access_token": "ghu_fresh", "refresh_token": "ghr_new"},
    )
    body = client.delete("/api/github/account").json()
    assert revocations == ["ghu_fresh"] and body["github_grant_revoked"] is True
    assert not _stored(client)  # the fresh tokens were used once and never saved


def test_audit_records_disconnect_and_revocation_result(client, revocations):
    _connect(client)
    revocations.result = False
    client.delete("/api/github/account")
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        events = [(e.action, e.detail) for e in db.query(AuditEvent).filter_by(user_id=user.id).order_by(AuditEvent.id)]
    assert ("github.disconnect", None) in events or ("github.disconnect", {}) in events
    assert ("github.grant_revoke", {"revoked": False}) in events
    assert "ghu_access" not in repr(events)


# --- the revoke call itself ---------------------------------------------------------------


def _revoke_with(settings, handler) -> bool:
    return github.revoke_grant(settings, "ghu_token", transport=httpx.MockTransport(handler))


def test_revoke_grant_uses_the_documented_endpoint(settings):
    seen = {}

    def handler(request):
        seen.update(
            method=request.method, path=request.url.path, auth=request.headers["authorization"], body=request.content
        )
        return httpx.Response(204)

    assert _revoke_with(settings, handler) is True
    assert seen["method"] == "DELETE" and seen["path"] == f"/applications/{settings.github_client_id}/grant"
    assert seen["auth"].startswith("Basic ")  # App client id + secret, never the user's token
    assert b'"access_token":"ghu_token"' in seen["body"].replace(b" ", b"")


@pytest.mark.parametrize("status", [404, 422, 500])
def test_revoke_grant_only_reports_success_on_204(settings, status):
    assert _revoke_with(settings, lambda r: httpx.Response(status)) is False


def test_revoke_grant_network_error_is_not_success(settings):
    def down(request):
        raise httpx.ConnectError("no route", request=request)

    assert _revoke_with(settings, down) is False
