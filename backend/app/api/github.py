import hmac
import secrets

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_repo
from app.api.repositories import github_client_for, github_error
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.integrations.github import GitHubClient, GitHubError, authorize_url, exchange_code, validate_full_name
from app.models import AuditEvent, GitHubAccount, PullRequest, User, utcnow
from app.services import github_tokens

router = APIRouter(tags=["github"])
STATE_COOKIE = "devpilot_gh_state"


def _redirect_uri(request: Request) -> str:
    return str(request.url_for("github_callback"))


@router.get("/api/github/status")
def github_status(
    db: Session = Depends(get_db), user: User = Depends(current_user), settings: Settings = Depends(get_settings)
):
    acct = db.query(GitHubAccount).filter_by(user_id=user.id).one_or_none()
    return {
        "configured": settings.github_configured,
        "connected": acct is not None,
        "login": acct.github_login if acct else None,
        "scopes": acct.scopes if acct else None,
        "install_url": f"https://github.com/apps/{settings.github_app_slug}/installations/new"
        if settings.github_app_slug
        else None,
    }


@router.get("/api/github/oauth/start")
def oauth_start(request: Request, user: User = Depends(current_user), settings: Settings = Depends(get_settings)):
    if not settings.github_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GitHub OAuth is not configured on this server.")
    state = secrets.token_urlsafe(24)
    resp = RedirectResponse(authorize_url(settings, state, _redirect_uri(request)))
    resp.set_cookie(
        STATE_COOKIE,
        f"{user.id}:{state}",
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/github",
    )
    return resp


@router.get("/api/github/oauth/callback", name="github_callback")
def oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    cookie_state: str | None = Cookie(default=None, alias=STATE_COOKIE),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    expected = f"{user.id}:{state}"
    if not cookie_state or not state or not hmac.compare_digest(cookie_state, expected):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth state mismatch. Start the connection again.")
    if error or not code:  # the user declined, or GitHub returned an error instead of a code
        resp = RedirectResponse(settings.frontend_origin + "/settings?github=declined")
        resp.delete_cookie(STATE_COOKIE, path="/api/github")
        return resp
    try:
        tokens = exchange_code(settings, code, _redirect_uri(request), utcnow())
        login = GitHubClient(tokens.access_token, settings).user()["login"]
    except GitHubError as e:
        raise HTTPException(e.status, str(e)) from e
    acct = db.query(GitHubAccount).filter_by(user_id=user.id).one_or_none() or GitHubAccount(user_id=user.id)
    acct.github_login, acct.scopes = login, ""
    github_tokens.store(acct, tokens)
    db.add(acct)
    db.add(AuditEvent(user_id=user.id, action="github.connect", detail={"login": login}))
    db.commit()
    resp = RedirectResponse(settings.frontend_origin + "/settings?github=connected")
    resp.delete_cookie(STATE_COOKIE, path="/api/github")
    return resp


REVOKE_HELP = "https://github.com/settings/apps/authorizations"


@router.delete("/api/github/account")
def disconnect(
    db: Session = Depends(get_db), user: User = Depends(current_user), settings: Settings = Depends(get_settings)
):
    acct = db.query(GitHubAccount).filter_by(user_id=user.id).one_or_none()
    if acct is None:
        return {
            "local_credentials_deleted": False,
            "github_grant_revoked": False,
            "detail": "No GitHub account is connected.",
        }
    revoked = github_tokens.disconnect(db, acct, settings)
    detail = (
        "Disconnected. DevPilot deleted its GitHub tokens and GitHub confirmed the authorization was revoked."
        if revoked
        else "Disconnected. DevPilot deleted its GitHub tokens, but GitHub did not confirm revoking the "
        f"authorization. Revoke DevPilot at {REVOKE_HELP} to be sure."
    )
    return {"local_credentials_deleted": True, "github_grant_revoked": revoked, "detail": detail}


@router.get("/api/github/repos")
def github_repos(
    db: Session = Depends(get_db), user: User = Depends(current_user), settings: Settings = Depends(get_settings)
):
    try:
        return github_client_for(db, user, settings).list_repos()
    except GitHubError as e:
        raise github_error(db, user, e) from e


@router.get("/api/github/repos/{owner}/{name}/branches")
def github_branches(
    owner: str,
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    try:
        gh = github_client_for(db, user, settings)
        meta = gh.authorized_repo(validate_full_name(f"{owner}/{name}"))
        return {"default_branch": meta["default_branch"], "branches": gh.branches(meta["full_name"])}
    except GitHubError as e:
        raise github_error(db, user, e) from e


@router.get("/api/repositories/{repo_id}/pulls")
def list_pulls(
    repo_id: int,
    state: str = "open",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    repo = owned_repo(repo_id, db, user)
    if repo.source_type != "github":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only GitHub repositories have pull requests.")
    try:
        return github_client_for(db, user, settings).list_pulls(repo.source_ref, state)
    except GitHubError as e:
        raise github_error(db, user, e) from e


@router.get("/api/repositories/{repo_id}/pulls/{number}")
def get_pull(
    repo_id: int,
    number: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    repo = owned_repo(repo_id, db, user)
    if repo.source_type != "github":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only GitHub repositories have pull requests.")
    try:
        gh = github_client_for(db, user, settings)
        meta = gh.pull(repo.source_ref, number)
        files = gh.pull_files(repo.source_ref, number)
    except GitHubError as e:
        raise github_error(db, user, e) from e
    pr = db.query(PullRequest).filter_by(repository_id=repo.id, number=number).one_or_none()
    if pr is None:
        pr = PullRequest(repository_id=repo.id, number=number)
        db.add(pr)
    pr.title, pr.author, pr.url = meta["title"][:1000], meta["author"], meta["url"]
    pr.base_sha, pr.head_sha = meta["base_sha"], meta["head_sha"]
    db.commit()
    return {**meta, "files": files}
