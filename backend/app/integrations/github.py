"""GitHub REST client and OAuth helpers.

SSRF: users never supply URLs. They supply "owner/name" and PR numbers, which are validated
and placed into fixed API paths. Redirects are followed only to GitHub-owned hosts."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from app.core.config import Settings

FULL_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
ALLOWED_HOSTS = {"api.github.com", "codeload.github.com", "github.com"}


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def validate_full_name(full_name: str) -> str:
    if not FULL_NAME_RE.match(full_name) or ".." in full_name:
        raise GitHubError("Repository must look like 'owner/name'.", 400)
    return full_name


class GitHubClient:
    def __init__(self, token: str, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.http = httpx.Client(
            base_url=settings.github_api_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "DevPilot",
            },
            timeout=30.0,
            transport=transport,
            follow_redirects=False,
        )

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code == 401:
            raise GitHubError("GitHub rejected the stored token. Reconnect your account.", 401)
        if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
            raise GitHubError(
                f"GitHub API rate limit reached; resets at epoch {r.headers.get('x-ratelimit-reset')}.",
                429,
            )
        if r.status_code in (403, 404):
            raise GitHubError("Not found, or your GitHub token has no access to it.", 404)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API error {r.status_code}.", 502)
        return r

    def get(self, path: str, **params) -> httpx.Response:
        return self._check(self.http.get(path, params=params or None))

    def user(self) -> dict:
        return self.get("/user").json()

    def list_repos(self) -> list[dict]:
        r = self.get("/user/repos", per_page=100, sort="updated")
        return [
            {
                "full_name": x["full_name"],
                "private": x["private"],
                "default_branch": x["default_branch"],
                "updated_at": x["updated_at"],
            }
            for x in r.json()
        ]

    def repo(self, full_name: str) -> dict:
        return self.get(f"/repos/{validate_full_name(full_name)}").json()

    def list_pulls(self, full_name: str, state: str = "open") -> list[dict]:
        if state not in ("open", "closed", "all"):
            state = "open"
        r = self.get(f"/repos/{validate_full_name(full_name)}/pulls", state=state, per_page=50)
        return [_pr_summary(p) for p in r.json()]

    def pull(self, full_name: str, number: int) -> dict:
        return _pr_summary(self.get(f"/repos/{validate_full_name(full_name)}/pulls/{int(number)}").json())

    def pull_files(self, full_name: str, number: int, max_files: int = 300) -> list[dict]:
        files: list[dict] = []
        page = 1
        while len(files) < max_files:
            r = self.get(
                f"/repos/{validate_full_name(full_name)}/pulls/{int(number)}/files",
                per_page=100,
                page=page,
            )
            batch = r.json()
            files += batch
            if len(batch) < 100:
                break
            page += 1
        return [
            {
                "path": f["filename"],
                "status": f["status"],
                "additions": f["additions"],
                "deletions": f["deletions"],
                "patch": f.get("patch"),
                "previous_path": f.get("previous_filename"),
            }
            for f in files[:max_files]
        ]

    def download_zipball(self, full_name: str, ref: str, dest: Path) -> None:
        if not re.match(r"^[A-Za-z0-9._/-]{1,200}$", ref):
            raise GitHubError("Invalid ref.", 400)
        r = self.http.get(f"/repos/{validate_full_name(full_name)}/zipball/{ref}")
        hops = 0
        while r.status_code in (301, 302, 307, 308) and hops < 3:
            location = r.headers.get("location", "")
            if urlparse(location).hostname not in ALLOWED_HOSTS or urlparse(location).scheme != "https":
                raise GitHubError("Unexpected redirect while downloading the repository.", 502)
            # The signed codeload URL carries its own credentials; don't forward ours.
            r = httpx.get(location, timeout=60.0, follow_redirects=False)
            hops += 1
        self._check(r)
        if len(r.content) > self.settings.max_upload_bytes:
            raise GitHubError("Repository archive exceeds the maximum size.", 413)
        dest.write_bytes(r.content)


def _pr_summary(p: dict) -> dict:
    return {
        "number": p["number"],
        "title": p["title"],
        "state": p["state"],
        "author": (p.get("user") or {}).get("login", ""),
        "url": p["html_url"],
        "base_sha": p["base"]["sha"],
        "head_sha": p["head"]["sha"],
        "base_ref": p["base"]["ref"],
        "head_ref": p["head"]["ref"],
        "updated_at": p.get("updated_at"),
        "draft": p.get("draft", False),
        "additions": p.get("additions"),
        "deletions": p.get("deletions"),
        "changed_files": p.get("changed_files"),
    }


def authorize_url(settings: Settings, state: str, redirect_uri: str) -> str:
    q = {
        "client_id": settings.github_client_id,
        "state": state,
        "redirect_uri": redirect_uri,
        "scope": settings.github_oauth_scopes,
        "allow_signup": "false",
    }
    return "https://github.com/login/oauth/authorize?" + urlencode(q)


def exchange_code(
    settings: Settings, code: str, redirect_uri: str, transport: httpx.BaseTransport | None = None
) -> tuple[str, str]:
    with httpx.Client(timeout=20.0, transport=transport) as c:
        r = c.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
    data = r.json() if r.status_code == 200 else {}
    token = data.get("access_token")
    if not token:
        raise GitHubError("GitHub did not issue a token (the code may have expired).", 400)
    return token, data.get("scope", "")
