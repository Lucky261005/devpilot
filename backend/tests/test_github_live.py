"""Live GitHub App integration test. Skipped unless explicitly configured.

Use a dedicated test GitHub account and a disposable repository, never a personal token:

    DEVPILOT_TEST_GITHUB_TOKEN           a GitHub App user token (ghu_...) for the test account
    DEVPILOT_TEST_GITHUB_REPO            owner/name of a small PRIVATE repo the App is installed on
    DEVPILOT_TEST_GITHUB_UNGRANTED_REPO  owner/name of a public repo the App is NOT installed on

    uv run pytest -m live_github tests/test_github_live.py

The token is stored only in the throwaway test database (encrypted) and never printed."""

import os

import pytest

from app.core.db import SessionLocal
from app.core.security import encrypt_secret
from app.models import GitHubAccount, User

TOKEN = os.environ.get("DEVPILOT_TEST_GITHUB_TOKEN", "")
REPO = os.environ.get("DEVPILOT_TEST_GITHUB_REPO", "")
UNGRANTED = os.environ.get("DEVPILOT_TEST_GITHUB_UNGRANTED_REPO", "")

pytestmark = [
    pytest.mark.live_github,
    pytest.mark.skipif(not (TOKEN and REPO and UNGRANTED), reason="live GitHub test not configured"),
]


def _connect(client, token: str) -> None:
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        db.query(GitHubAccount).filter_by(user_id=user.id).delete()
        db.add(GitHubAccount(user_id=user.id, github_login="live-test", encrypted_token=encrypt_secret(token)))
        db.commit()


def test_read_only_import_end_to_end(client):
    _connect(client, TOKEN)
    repos = {r["full_name"].lower(): r for r in client.get("/api/github/repos").json()}
    assert REPO.lower() in repos, "the App must be installed on the test repository"
    assert repos[REPO.lower()]["private"] is True, "use a private repository to prove private access"
    assert UNGRANTED.lower() not in repos

    owner, name = REPO.split("/")
    body = client.get(f"/api/github/repos/{owner}/{name}/branches").json()
    head = {b["name"]: b["sha"] for b in body["branches"]}[body["default_branch"]]

    r = client.post("/api/repositories/github", json={"full_name": REPO})
    assert r.status_code == 201, r.text
    repo = r.json()
    assert repo["index_status"] == "ready", repo["index_error"]
    assert (repo["source_branch"], repo["source_sha"]) == (body["default_branch"], head)
    assert repo["file_count"] > 0

    r = client.post("/api/repositories/github", json={"full_name": UNGRANTED})
    assert r.status_code == 404


def test_invalid_token_is_treated_as_revoked(client):
    _connect(client, "ghu_" + "0" * 36)
    assert client.get("/api/github/repos").status_code == 401
    assert client.get("/api/github/status").json()["connected"] is False
