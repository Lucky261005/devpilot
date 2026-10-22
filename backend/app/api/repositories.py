import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_repo
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.ratelimit import limiter
from app.integrations.github import GitHubClient, GitHubError, validate_full_name
from app.models import AuditEvent, GitHubAccount, Repository, User
from app.schemas import FileContent, GitHubRepoIn, LocalRepoIn, RepositoryOut, RepositoryPatch
from app.services import github_tokens, ingestion
from app.services.indexing import index_snapshot, list_paths, search

router = APIRouter(prefix="/api/repositories", tags=["repositories"])


def _check_quota(user: User, settings: Settings) -> None:
    if not limiter.allow(("ingest", user.id), limit=20, window_s=3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Import limit reached. Try again later.")


def _new_repo(db: Session, user: User, name: str, source_type: str, ref: str) -> Repository:
    if db.query(Repository).filter_by(owner_id=user.id, name=name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a repository with this name.")
    repo = Repository(owner_id=user.id, name=name, source_type=source_type, source_ref=ref, index_status="indexing")
    db.add(repo)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id, action="repository.create", detail={"repository_id": repo.id, "source_type": source_type}
        )
    )
    db.commit()
    return repo


def _index_or_fail(db: Session, repo: Repository, fill, settings: Settings) -> Repository:
    """Run `fill(snapshot_dir)` then index; on rejection, keep the row with a visible error."""
    root = ingestion.new_snapshot_dir(settings, repo.id, "current")
    try:
        fill(root)
        index_snapshot(db, repo, root, settings)
    except (ingestion.IngestionError, GitHubError, ValueError) as e:
        db.rollback()
        shutil.rmtree(root, ignore_errors=True)
        repo.index_status, repo.index_error = "failed", str(e)
        db.commit()
    except Exception:
        db.rollback()
        shutil.rmtree(root, ignore_errors=True)
        repo.index_status, repo.index_error = "failed", "Internal error while indexing. See server logs."
        db.commit()
        raise
    return repo


@router.get("", response_model=list[RepositoryOut])
def list_repositories(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.scalars(
        select(Repository).where(Repository.owner_id == user.id).order_by(Repository.created_at.desc())
    ).all()


@router.post("/archive", response_model=RepositoryOut, status_code=201)
def import_archive(
    file: UploadFile,
    name: str = Form(min_length=1, max_length=100, pattern=r"^[\w.\- ]+$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    _check_quota(user, settings)
    with tempfile.TemporaryDirectory() as tmp:
        zpath = Path(tmp) / "upload.zip"
        size = 0
        with open(zpath, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Upload exceeds the maximum archive size."
                    )
                out.write(chunk)
        repo = _new_repo(db, user, name, "archive", (file.filename or "upload.zip")[:200])
        return _index_or_fail(
            db, repo, lambda root: ingestion.safe_extract_zip(zpath, root, settings, strip_top=True), settings
        )


@router.post("/local", response_model=RepositoryOut, status_code=201)
def import_local(
    body: LocalRepoIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    _check_quota(user, settings)
    try:
        path = ingestion.validate_local_path(body.path, settings)
    except ingestion.IngestionError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    repo = _new_repo(db, user, body.name, "local", str(path))

    def fill(root: Path) -> None:
        ingestion.export_git_tree(path, ingestion.resolve_ref(path, "HEAD"), root, settings)

    return _index_or_fail(db, repo, fill, settings)


def github_client_for(db: Session, user: User, settings: Settings) -> GitHubClient:
    """A client acting as this user. Raises GitHubError when the stored authorization is gone."""
    account = db.query(GitHubAccount).filter_by(user_id=user.id).one_or_none()
    if account is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Connect a GitHub account first.")
    return GitHubClient(github_tokens.access_token(db, account, settings), settings)


def github_error(db: Session, user: User, e: GitHubError) -> HTTPException:
    """Map a GitHub failure to an HTTP error; a rejected token also ends the stored connection."""
    if e.status == 401:
        account = db.query(GitHubAccount).filter_by(user_id=user.id).one_or_none()
        if account is not None:
            github_tokens.forget(db, account, "token_rejected")
        return HTTPException(
            status.HTTP_401_UNAUTHORIZED, "GitHub access was revoked or expired. Connect GitHub again."
        )
    return HTTPException(e.status, str(e))


@router.post("/github", response_model=RepositoryOut, status_code=201)
def import_github(
    body: GitHubRepoIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    _check_quota(user, settings)
    try:
        validate_full_name(body.full_name)
        gh = github_client_for(db, user, settings)
        # Authorization check before anything is stored: the repository must be in this user's
        # App installation grants. Its canonical name comes from GitHub, not from the request.
        meta = gh.authorized_repo(body.full_name)
        full_name, branch = meta["full_name"], body.branch or meta["default_branch"]
        sha = gh.branch_sha(full_name, branch)  # pin the import to one commit
    except GitHubError as e:
        raise github_error(db, user, e) from e
    name = full_name.replace("/", "-") + ("" if branch == meta["default_branch"] else "@" + branch.replace("/", "-"))
    repo = _new_repo(db, user, name, "github", full_name)
    repo.source_branch, repo.source_sha = branch, sha
    db.commit()

    def fill(root: Path) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / "repo.zip"
            gh.download_zipball(full_name, sha, z)
            ingestion.safe_extract_zip(z, root, settings, strip_top=True)

    return _index_or_fail(db, repo, fill, settings)


@router.get("/{repo_id}", response_model=RepositoryOut)
def get_repository(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return owned_repo(repo_id, db, user)


@router.patch("/{repo_id}", response_model=RepositoryOut)
def update_repository(
    repo_id: int, body: RepositoryPatch, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    repo = owned_repo(repo_id, db, user)
    if body.ai_review_allowed is not None:
        repo.ai_review_allowed = body.ai_review_allowed
        db.add(
            AuditEvent(
                user_id=user.id,
                action="repository.ai_consent",
                detail={"repository_id": repo.id, "allowed": body.ai_review_allowed},
            )
        )
    db.commit()
    return repo


@router.delete("/{repo_id}", status_code=204)
def delete_repository(
    repo_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    repo = owned_repo(repo_id, db, user)
    db.add(AuditEvent(user_id=user.id, action="repository.delete", detail={"repository_id": repo.id}))
    db.delete(repo)
    db.commit()
    shutil.rmtree(settings.data_dir / "snapshots" / str(repo_id), ignore_errors=True)


@router.get("/{repo_id}/files", response_model=list[str])
def files(repo_id: int, prefix: str = "", db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_repo(repo_id, db, user)
    return list_paths(db, repo_id, prefix)


def read_snapshot_file(root: Path | None, path: str, settings: Settings) -> FileContent:
    if root is None or not root.exists():
        raise HTTPException(status.HTTP_410_GONE, "Source snapshot is no longer available.")
    try:
        target = (root / path).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.")
    except (OSError, ValueError) as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found.") from e
    if target.stat().st_size > settings.max_file_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large to display.")
    text = target.read_text(encoding="utf-8", errors="replace")
    return FileContent(
        path=path,
        language=ingestion.LANGUAGES.get(target.suffix.lower(), "text"),
        content=text,
        line_count=len(text.splitlines()),
    )


@router.get("/{repo_id}/file", response_model=FileContent)
def file_content(
    repo_id: int,
    path: str = Query(max_length=1024),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    repo = owned_repo(repo_id, db, user)
    return read_snapshot_file(Path(repo.snapshot_dir) if repo.snapshot_dir else None, path, settings)


@router.get("/{repo_id}/search")
def search_code(
    repo_id: int,
    q: str = Query(min_length=1, max_length=200),
    mode: str = Query(default="text", pattern="^(text|identifier)$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_repo(repo_id, db, user)
    return {"query": q, "mode": mode, "results": search(db, repo_id, q, mode)}


@router.get("/{repo_id}/stats")
def repo_stats(repo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from app.models import CodeChunk

    owned_repo(repo_id, db, user)
    rows = db.execute(
        select(CodeChunk.language, func.count(func.distinct(CodeChunk.path)))
        .where(CodeChunk.repository_id == repo_id)
        .group_by(CodeChunk.language)
    ).all()
    return {"languages": {lang: n for lang, n in rows}}
