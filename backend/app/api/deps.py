from datetime import UTC

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import hash_token
from app.models import Repository, ReviewJob, User, UserSession, utcnow

SESSION_COOKIE = "devpilot_session"


def current_user(db: Session = Depends(get_db), token: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in.")
    sess = db.query(UserSession).filter_by(token_hash=hash_token(token)).one_or_none()
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Sign in again.")
    expires = sess.expires_at if sess.expires_at.tzinfo else sess.expires_at.replace(tzinfo=UTC)
    if expires < utcnow():
        db.delete(sess)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Sign in again.")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Sign in again.")
    return user


def owned_repo(repo_id: int, db: Session, user: User) -> Repository:
    """Resource-level authorization: 404 (not 403) so other users' IDs are not disclosed."""
    repo = db.get(Repository, repo_id)
    if repo is None or repo.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found.")
    return repo


def owned_review(review_id: int, db: Session, user: User) -> ReviewJob:
    job = db.get(ReviewJob, review_id)
    if job is None or job.repository.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found.")
    return job
