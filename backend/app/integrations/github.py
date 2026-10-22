"""GitHub REST client and GitHub App user-authorization helpers.

DevPilot is a GitHub App. Users authorize it with the web flow and get a user-to-server token,
which can only reach repositories that are both visible to the user and covered by an
installation of the App. Those tokens expire (about 8 h) and are renewed with a rotating refresh
token (services/github_tokens.py). All access is read-only (the App requests Contents: read,
Metadata: read, Pull requests: read).

SSRF: users never supply URLs. They supply "owner/name", branch names and PR numbers, which are
validated and placed into fixed API paths. Redirects are followed only to GitHub-owned hosts."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import httpx

from app.core.config import Settings

FULL_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
MAX_PAGES = 10  # 100 items per page; enough for a personal account, bounded for safety
OAUTH_EXCHANGE_URL = "https://github.com/login/oauth/access_token"
ALLOWED_HOSTS = {"api.github.com", "codeload.github.com", "github.com"}


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def validate_full_name(full_name: str) -> str:
    if not FULL_NAME_RE.match(full_name) or ".." in full_name:
        raise GitHubError("Repository must look like 'owner/name'.", 400)
    return full_name


def validate_branch(branch: str) -> str:
    if not BRANCH_RE.match(branch) or ".." in branch or branch.startswith(("/", "-")) or branch.endswith("/"):
        raise GitHubError("Invalid branch name.", 400)
    return branch


class GitHubClient:
    def __init__(self, token: str, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.sleep = time.sleep  # replaced in tests
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
        if r.status_code == 429 or (r.status_code == 403 and _rate_limited(r)):
            reset = r.headers.get("x-ratelimit-reset", "")
            when = f" Resets at {datetime.fromtimestamp(int(reset)).isoformat(timespec='minutes')}." if reset else ""
            raise GitHubError(f"GitHub API rate limit reached.{when} Try again later.", 429)
        if r.status_code in (403, 404):
            raise GitHubError("Not found, or your GitHub token has no access to it.", 404)
        if r.status_code >= 400:
            raise GitHubError(f"GitHub API error {r.status_code}.", 502)
        return r

    def get(self, path: str, **params) -> httpx.Response:
        """GET with up to two retries for network errors, 5xx, and short Retry-After waits."""
        for attempt in range(3):
            last = attempt == 2
            try:
                r = self.http.get(path, params=params or None)
            except httpx.TransportError as e:
                if last:
                    raise GitHubError("Could not reach GitHub. Try again.", 503) from e
                self.sleep(0.5 * 2**attempt)
                continue
            if r.status_code in (502, 503, 504) and not last:
                self.sleep(0.5 * 2**attempt)
                continue
            retry_after = r.headers.get("retry-after", "")
            if r.status_code in (403, 429) and retry_after.isdigit() and int(retry_after) <= 5 and not last:
                self.sleep(int(retry_after))  # short secondary rate limit
                continue
            return self._check(r)
        raise AssertionError("unreachable")

    def pages(self, path: str, key: str | None = None, **params) -> list[dict]:
        """All items of a paginated list endpoint, up to MAX_PAGES pages of 100."""
        items: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            body = self.get(path, per_page=100, page=page, **params).json()
            batch = body[key] if key else body
            items += batch
            if len(batch) < 100:
                break
        return items

    def user(self) -> dict:
        return self.get("/user").json()

    def list_repos(self) -> list[dict]:
        """Repositories this user granted DevPilot through an App installation."""
        repos: dict[str, dict] = {}
        for inst in self.pages("/user/installations", key="installations"):
            for x in self.pages(f"/user/installations/{int(inst['id'])}/repositories", key="repositories"):
                repos[x["full_name"].lower()] = {
                    "full_name": x["full_name"],
                    "private": x["private"],
                    "default_branch": x["default_branch"],
                    "updated_at": x.get("updated_at"),
                }
        return sorted(repos.values(), key=lambda r: r["updated_at"] or "", reverse=True)

    def authorized_repo(self, full_name: str) -> dict:
        """The repository's metadata, only if it is in this user's installation grants.

        The name from the browser is never trusted on its own: a public repository is readable
        with any token, so membership in the grant list is checked explicitly."""
        wanted = validate_full_name(full_name).lower()
        for r in self.list_repos():
            if r["full_name"].lower() == wanted:
                return r
        raise GitHubError(
            "DevPilot has no access to this repository. Install the GitHub App on it, then try again.", 404
        )

    def branches(self, full_name: str) -> list[dict]:
        return [
            {"name": b["name"], "sha": b["commit"]["sha"], "protected": b.get("protected", False)}
            for b in self.pages(f"/repos/{validate_full_name(full_name)}/branches")
        ]

    def branch_sha(self, full_name: str, branch: str) -> str:
        path = f"/repos/{validate_full_name(full_name)}/branches/{quote(validate_branch(branch), safe='')}"
        sha = self.get(path).json()["commit"]["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise GitHubError("GitHub returned an unexpected commit id.", 502)
        return sha

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


def _rate_limited(r: httpx.Response) -> bool:
    if r.headers.get("x-ratelimit-remaining") == "0":
        return True
    try:
        return "rate limit" in r.json().get("message", "").lower()
    except ValueError:
        return False


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
    # GitHub Apps take permissions from the App's settings, so there is no "scope" parameter.
    q = {"client_id": settings.github_client_id, "state": state, "redirect_uri": redirect_uri, "allow_signup": "false"}
    return "https://github.com/login/oauth/authorize?" + urlencode(q)


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None  # None when the App has token expiry turned off
    refresh_expires_at: datetime | None


def _token_request(settings: Settings, data: dict, transport: httpx.BaseTransport | None = None) -> dict:
    payload = {"client_id": settings.github_client_id, "client_secret": settings.github_client_secret, **data}
    try:
        with httpx.Client(timeout=20.0, transport=transport) as c:
            r = c.post(OAUTH_EXCHANGE_URL, data=payload, headers={"Accept": "application/json"})
    except httpx.TransportError as e:
        raise GitHubError("Could not reach GitHub. Try again.", 503) from e
    body = r.json() if r.status_code == 200 else {}
    # GitHub reports failures as 200 with an "error" field (bad_verification_code, bad_refresh_token).
    if not body.get("access_token"):
        raise GitHubError(f"GitHub did not issue a token ({body.get('error', r.status_code)}).", 401)
    return body


def _token_set(body: dict, now: datetime) -> TokenSet:
    def at(seconds: object) -> datetime | None:
        return now + timedelta(seconds=int(str(seconds))) if seconds else None

    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=at(body.get("expires_in")),
        refresh_expires_at=at(body.get("refresh_token_expires_in")),
    )


def exchange_code(
    settings: Settings, code: str, redirect_uri: str, now: datetime, transport: httpx.BaseTransport | None = None
) -> TokenSet:
    return _token_set(_token_request(settings, {"code": code, "redirect_uri": redirect_uri}, transport), now)


def refresh_tokens(
    settings: Settings, refresh_token: str, now: datetime, transport: httpx.BaseTransport | None = None
) -> TokenSet:
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    return _token_set(_token_request(settings, data, transport), now)
