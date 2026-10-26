import hashlib
import math
from datetime import UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analyzers.base import SEVERITIES
from app.api.deps import current_user, owned_repo, owned_review
from app.api.repositories import read_snapshot_file
from app.core.config import Settings, get_settings
from app.core.db import get_db, serialize
from app.models import (
    AuditEvent,
    ChangedFile,
    Finding,
    FindingFeedback,
    PullRequest,
    Repository,
    ReviewAdmission,
    ReviewJob,
    ReviewQuotaEvent,
    TestSuggestion,
    User,
    utcnow,
)
from app.schemas import (
    ChangedFileOut,
    FeedbackIn,
    FileContent,
    FindingOut,
    RecentReviewOut,
    ReviewIn,
    ReviewOut,
    TestSuggestionOut,
)
from app.services.review import review_root

router = APIRouter(tags=["reviews"])


def _review_out(db: Session, job: ReviewJob) -> ReviewOut:
    counts = dict(
        db.execute(
            select(Finding.severity, func.count()).where(Finding.review_id == job.id).group_by(Finding.severity)
        ).all()
    )
    out = ReviewOut.model_validate(job)
    out.severity_counts = counts
    if job.pull_request_id:
        pr = db.get(PullRequest, job.pull_request_id)
        if pr:
            out.pr_number, out.pr_title = pr.number, pr.title
    return out


GLOBAL_WINDOW = timedelta(hours=1)


USER_WINDOW = timedelta(hours=1)


def _admit_user_review(db: Session, user: User, limit: int) -> ReviewQuotaEvent:
    """Admit one review under the user's hourly quota and record it, or raise 429. Same lock, count,
    insert rule as the import quota (api/repositories.py `_check_quota`): reviews for one user are
    serialized across API processes, so at most `limit` are admitted per rolling hour. A refused
    request leaves no record."""
    serialize(db, hashlib.sha256(f"review:{user.id}".encode()).hexdigest())
    now = utcnow()
    mine = ReviewQuotaEvent.user_id == user.id
    db.query(ReviewQuotaEvent).filter(mine, ReviewQuotaEvent.expires_at <= now).delete()
    if db.query(func.count(ReviewQuotaEvent.id)).filter(mine, ReviewQuotaEvent.expires_at > now).scalar() >= limit:
        db.commit()  # keeps the expired-row cleanup, releases the lock
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Review limit reached. Try again later.")
    event = ReviewQuotaEvent(user_id=user.id, expires_at=now + USER_WINDOW)
    db.add(event)
    db.commit()
    return event


def _admit_review(db: Session, cap: int) -> None:
    """Admit one review job under the installation-wide cap, or raise 429.

    The admission is recorded and committed before counting, so every request counts all
    admissions committed before it: on both SQLite (one writer at a time) and PostgreSQL (READ
    COMMITTED; each COUNT sees everything committed before it starts), at most `cap` reviews are
    admitted per rolling hour. Requests racing at the boundary may be refused early, never
    admitted late. A refused request removes its own record, so refusals use no capacity."""
    now = utcnow()
    cutoff = now - GLOBAL_WINDOW
    db.query(ReviewAdmission).filter(ReviewAdmission.created_at <= cutoff).delete()
    admission = ReviewAdmission(created_at=now)
    db.add(admission)
    db.commit()
    in_window = db.query(ReviewAdmission.created_at).filter(ReviewAdmission.created_at > cutoff)
    if in_window.count() > cap:
        db.delete(admission)
        db.commit()
        # Nothing else in the window only when cap is 0 (rejected by Settings, ge=1): retry in a full window.
        oldest = min((c for (c,) in in_window.all()), default=now)
        oldest = oldest if oldest.tzinfo else oldest.replace(tzinfo=UTC)
        retry = max(1, math.ceil((oldest + GLOBAL_WINDOW - now).total_seconds()))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "This server has reached its hourly review limit. Try again later.",
            headers={"Retry-After": str(retry)},
        )


@router.post("/api/repositories/{repo_id}/reviews", response_model=ReviewOut, status_code=202)
def create_review(
    repo_id: int,
    body: ReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    repo = owned_repo(repo_id, db, user)
    if repo.index_status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Repository is not indexed.")
    if body.kind == "diff" and repo.source_type != "local":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ref-to-ref reviews need a local Git repository.")
    if body.kind == "pull_request" and (repo.source_type != "github" or not body.pr_number):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pull request reviews need a GitHub repository and pr_number.")
    if body.use_ai and not repo.ai_review_allowed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enable AI review for this repository before requesting it.")
    pr_id = None
    if body.kind == "pull_request":
        pr = db.query(PullRequest).filter_by(repository_id=repo.id, number=body.pr_number).one_or_none()
        if pr is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Open the pull request before reviewing it.")
        pr_id = pr.id
    quota = _admit_user_review(db, user, settings.reviews_per_hour)
    try:
        _admit_review(db, settings.reviews_global_per_hour)  # last check: nothing after it can refuse
    except HTTPException:
        db.delete(quota)  # refused by the installation cap: give the user's slot back
        db.commit()
        raise
    job = ReviewJob(
        repository_id=repo.id,
        kind=body.kind,
        base_ref=body.base_ref,
        head_ref=body.head_ref,
        pull_request_id=pr_id,
        use_ai=body.use_ai,
        stats={},
    )
    db.add(job)
    db.flush()
    db.add(
        AuditEvent(
            user_id=user.id,
            action="review.create",
            detail={"review_id": job.id, "kind": body.kind, "use_ai": body.use_ai},
        )
    )
    db.commit()
    return _review_out(db, job)


@router.get("/api/repositories/{repo_id}/reviews", response_model=list[ReviewOut])
def list_reviews(
    repo_id: int,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_repo(repo_id, db, user)
    jobs = db.scalars(
        select(ReviewJob)
        .where(ReviewJob.repository_id == repo_id)
        .order_by(ReviewJob.created_at.desc(), ReviewJob.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_review_out(db, j) for j in jobs]


# Declared before /api/reviews/{review_id} so "recent" is not parsed as an id.
@router.get("/api/reviews/recent", response_model=list[RecentReviewOut])
def recent_reviews(
    limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    rows = db.execute(
        select(ReviewJob, Repository.name)
        .join(Repository, ReviewJob.repository_id == Repository.id)
        .where(Repository.owner_id == user.id)
        .order_by(ReviewJob.created_at.desc(), ReviewJob.id.desc())
        .limit(limit)
    ).all()
    fields = set(RecentReviewOut.model_fields) - {"repository_name"}
    return [
        RecentReviewOut(**_review_out(db, job).model_dump(include=fields), repository_name=name) for job, name in rows
    ]


@router.get("/api/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _review_out(db, owned_review(review_id, db, user))


@router.get("/api/reviews/{review_id}/findings", response_model=list[FindingOut])
def list_findings(
    review_id: int,
    severity: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    source: list[str] = Query(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    owned_review(review_id, db, user)
    stmt = select(Finding).where(Finding.review_id == review_id)
    if severity:
        stmt = stmt.where(Finding.severity.in_(severity))
    if category:
        stmt = stmt.where(Finding.category.in_(category))
    if source:
        stmt = stmt.where(Finding.source.in_(source))
    findings = sorted(db.scalars(stmt).all(), key=lambda f: (SEVERITIES.index(f.severity), f.path, f.start_line))
    mine = dict(
        db.execute(
            select(FindingFeedback.finding_id, FindingFeedback.verdict).where(
                FindingFeedback.review_id == review_id, FindingFeedback.user_id == user.id
            )
        ).all()
    )
    out = []
    for f in findings:
        o = FindingOut.model_validate(f)
        o.my_feedback = mine.get(f.id)
        out.append(o)
    return out


@router.get("/api/reviews/{review_id}/changed-files", response_model=list[ChangedFileOut])
def changed_files(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_review(review_id, db, user)
    return db.scalars(select(ChangedFile).where(ChangedFile.review_id == review_id).order_by(ChangedFile.path)).all()


@router.get("/api/reviews/{review_id}/test-suggestions", response_model=list[TestSuggestionOut])
def test_suggestions(review_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_review(review_id, db, user)
    return db.scalars(
        select(TestSuggestion)
        .where(TestSuggestion.review_id == review_id)
        .order_by(TestSuggestion.source, TestSuggestion.path)
    ).all()


@router.get("/api/reviews/{review_id}/file", response_model=FileContent)
def review_file(
    review_id: int,
    path: str = Query(max_length=1024),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
):
    job = owned_review(review_id, db, user)
    return read_snapshot_file(review_root(settings, job, job.repository), path, settings)


@router.put("/api/findings/{finding_id}/feedback", status_code=204)
def give_feedback(finding_id: int, body: FeedbackIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    f = db.get(Finding, finding_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found.")
    job = owned_review(f.review_id, db, user)
    fb = db.query(FindingFeedback).filter_by(finding_id=f.id, user_id=user.id).one_or_none()
    if fb is None:
        fb = FindingFeedback(
            finding_id=f.id,
            user_id=user.id,
            repository_id=job.repository_id,
            review_id=job.id,
            analyzer=f.analyzer,
            analyzer_version=f.analyzer_version,
            verdict=body.verdict,
        )
        db.add(fb)
    fb.verdict, fb.comment = body.verdict, body.comment
    db.commit()


@router.get("/api/feedback/summary")
def feedback_summary(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Feedback counts per analyzer for the current user's repositories."""
    rows = db.execute(
        select(FindingFeedback.analyzer, FindingFeedback.verdict, func.count())
        .where(FindingFeedback.user_id == user.id)
        .group_by(FindingFeedback.analyzer, FindingFeedback.verdict)
    ).all()
    out: dict[str, dict[str, int]] = {}
    for analyzer, verdict, n in rows:
        out.setdefault(analyzer, {})[verdict] = n
    return out
