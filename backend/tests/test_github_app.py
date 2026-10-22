"""GitHub App integration: authorization, branches, token lifecycle, failures (mocked HTTP).

These are deterministic; tests/test_github_live.py covers the real API when configured."""

from datetime import timedelta

import httpx
import pytest

from app.core.db import SessionLocal
from app.core.security import decrypt_secret, encrypt_secret
from app.integrations import github
from app.models import GitHubAccount, User, utcnow
from app.services import github_tokens
from tests.test_api import GH_CALLS, GH_OVERRIDES, github_mock  # noqa: F401 (fixture)


def _account(email: str) -> GitHubAccount | None:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=email).one()
        return db.query(GitHubAccount).filter_by(user_id=user.id).one_or_none()


# --- repository and branch selection --------------------------------------------------------


def test_lists_only_granted_repositories_and_their_branches(client, github_mock):  # noqa: F811
    repos = client.get("/api/github/repos").json()
    assert [r["full_name"] for r in repos] == ["acme/shop"] and repos[0]["private"] is True
    body = client.get("/api/github/repos/acme/shop/branches").json()
    assert body["default_branch"] == "main"
    assert [(b["name"], b["sha"]) for b in body["branches"]] == [("main", "a" * 40), ("feat/x", "d" * 40)]
    assert client.get("/api/github/repos/acme/public/branches").status_code == 404


def test_import_selected_branch_records_its_commit(client, github_mock):  # noqa: F811
    r = client.post("/api/repositories/github", json={"full_name": "ACME/shop", "branch": "feat/x"})
    assert r.status_code == 201, r.text
    repo = r.json()
    assert repo["source_ref"] == "acme/shop"  # canonical name from GitHub, not the request
    assert (repo["source_branch"], repo["source_sha"]) == ("feat/x", "d" * 40)
    assert repo["name"] == "acme-shop@feat-x" and repo["index_status"] == "ready"
    assert f"/repos/acme/shop/zipball/{'d' * 40}" in GH_CALLS


def test_other_user_cannot_use_someone_elses_connection(client, other_client, github_mock):  # noqa: F811
    for method, url, body in [
        ("get", "/api/github/repos", None),
        ("get", "/api/github/repos/acme/shop/branches", None),
        ("post", "/api/repositories/github", {"full_name": "acme/shop"}),
    ]:
        r = getattr(other_client, method)(url, **({"json": body} if body else {}))
        assert r.status_code == 400 and "Connect a GitHub account" in r.json()["detail"], url
    assert other_client.get("/api/github/status").json()["connected"] is False


# --- failures --------------------------------------------------------------------------------


def test_revoked_token_disconnects_and_asks_to_reconnect(client, github_mock):  # noqa: F811
    GH_OVERRIDES["/user/installations"] = httpx.Response(401, json={"message": "Bad credentials"})
    r = client.get("/api/github/repos")
    assert r.status_code == 401 and "Connect GitHub again" in r.json()["detail"]
    assert client.get("/api/github/status").json()["connected"] is False


def test_rate_limit_is_reported_not_retried_forever(client, github_mock):  # noqa: F811
    GH_OVERRIDES["/user/installations"] = httpx.Response(
        403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"},
        json={"message": "API rate limit"},
    )
    r = client.get("/api/github/repos")
    assert r.status_code == 429 and "rate limit" in r.json()["detail"]
    assert client.get("/api/github/status").json()["connected"] is True  # a limit is not a revocation


def test_oauth_callback_declined_and_success(client, monkeypatch, settings):
    start = client.get("/api/github/oauth/start", follow_redirects=False)
    state = httpx.URL(start.headers["location"]).params["state"]
    assert "scope=" not in start.headers["location"]  # GitHub Apps take permissions from the App
    r = client.get(
        "/api/github/oauth/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False
    )
    assert r.status_code == 307 and r.headers["location"].endswith("/settings?github=declined")

    start = client.get("/api/github/oauth/start", follow_redirects=False)
    state = httpx.URL(start.headers["location"]).params["state"]
    monkeypatch.setattr(
        github,
        "_token_request",
        lambda s, data, transport=None: {
            "access_token": "ghu_new",
            "refresh_token": "ghr_new",
            "expires_in": 28800,
            "refresh_token_expires_in": 15897600,
        },
    )
    monkeypatch.setattr(github.GitHubClient, "user", lambda self: {"login": "octo"})
    r = client.get("/api/github/oauth/callback", params={"state": state, "code": "abc"}, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].endswith("/settings?github=connected")
    acct = _account(client.email)
    assert acct is not None and acct.github_login == "octo"
    assert decrypt_secret(acct.encrypted_token) == "ghu_new" and acct.encrypted_token != "ghu_new"
    assert decrypt_secret(acct.encrypted_refresh_token) == "ghr_new"
    assert acct.token_expires_at is not None


# --- token lifecycle -------------------------------------------------------------------------


@pytest.fixture
def expiring_account(client):
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        acct = GitHubAccount(
            user_id=user.id,
            github_login="dev",
            encrypted_token=encrypt_secret("ghu_old"),
            encrypted_refresh_token=encrypt_secret("ghr_old"),
            token_expires_at=utcnow() + timedelta(minutes=1),  # inside the renewal window
            refresh_expires_at=utcnow() + timedelta(days=30),
        )
        db.add(acct)
        db.commit()
        return acct.id


def test_expiring_token_is_renewed_and_refresh_token_rotated(db, settings, expiring_account, monkeypatch):
    seen = {}

    def fake(s, data, transport=None):
        seen.update(data)
        return {"access_token": "ghu_fresh", "refresh_token": "ghr_rotated", "expires_in": 28800}

    monkeypatch.setattr(github, "_token_request", fake)
    acct = db.get(GitHubAccount, expiring_account)
    assert github_tokens.access_token(db, acct, settings) == "ghu_fresh"
    assert seen == {"grant_type": "refresh_token", "refresh_token": "ghr_old"}
    db.expire_all()
    acct = db.get(GitHubAccount, expiring_account)
    assert decrypt_secret(acct.encrypted_refresh_token) == "ghr_rotated"
    assert github_tokens.access_token(db, acct, settings) == "ghu_fresh"  # valid now: no second refresh


def test_rejected_refresh_removes_the_connection(db, settings, expiring_account, monkeypatch):
    def fake(s, data, transport=None):
        raise github.GitHubError("GitHub did not issue a token (bad_refresh_token).", 401)

    monkeypatch.setattr(github, "_token_request", fake)
    with pytest.raises(github.GitHubError) as e:
        github_tokens.access_token(db, db.get(GitHubAccount, expiring_account), settings)
    assert e.value.status == 401
    assert db.get(GitHubAccount, expiring_account) is None


def test_unreachable_github_keeps_the_connection(db, settings, expiring_account, monkeypatch):
    def fake(s, data, transport=None):
        raise github.GitHubError("Could not reach GitHub. Try again.", 503)

    monkeypatch.setattr(github, "_token_request", fake)
    with pytest.raises(github.GitHubError):
        github_tokens.access_token(db, db.get(GitHubAccount, expiring_account), settings)
    assert db.get(GitHubAccount, expiring_account) is not None


def test_expired_refresh_token_removes_the_connection(db, settings, expiring_account):
    acct = db.get(GitHubAccount, expiring_account)
    acct.refresh_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(github.GitHubError):
        github_tokens.access_token(db, acct, settings)
    assert db.get(GitHubAccount, expiring_account) is None


# --- client behaviour ------------------------------------------------------------------------


def _client(settings, handler) -> github.GitHubClient:
    c = github.GitHubClient("t", settings, transport=httpx.MockTransport(handler))
    c.sleep = lambda s: None
    return c


def test_pagination_follows_pages_and_is_bounded(settings):
    def handler(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json=[{"n": page}] * (100 if page < 3 else 7))

    assert len(_client(settings, handler).pages("/x")) == 207

    always_full = _client(settings, lambda r: httpx.Response(200, json=[{}] * 100))
    assert len(always_full.pages("/x")) == 100 * github.MAX_PAGES


def test_retries_transient_failures_then_gives_up(settings):
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(502) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    assert _client(settings, flaky).get("/x").json() == {"ok": True} and len(calls) == 3

    def down(request):
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(github.GitHubError) as e:
        _client(settings, down).get("/x")
    assert e.value.status == 503


def test_short_secondary_rate_limit_is_waited_out(settings):
    waits, calls = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(403, headers={"retry-after": "2"}, json={"message": "secondary rate limit"})
        return httpx.Response(200, json=[])

    c = _client(settings, handler)
    c.sleep = waits.append
    assert c.get("/x").json() == [] and waits == [2]


def test_branch_names_are_validated():
    for bad in ["../x", "-x", "a b", "x/", "/x", "a" * 201]:
        with pytest.raises(github.GitHubError):
            github.validate_branch(bad)
    assert github.validate_branch("feat/x-1.2") == "feat/x-1.2"
