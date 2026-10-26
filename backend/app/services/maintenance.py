"""Housekeeping that is safe to run at any time, from the worker loop or `python -m app.cli`."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import LOGIN_FAILURE_WINDOW
from app.models import ImportEvent, IpRateEvent, LoginAttempt, ReviewQuotaEvent, UserSession, utcnow

SESSION_BATCH = 500  # rows per transaction: keeps each write short so sign-ins are never blocked long
ATTEMPT_BATCH = 500
IP_EVENT_BATCH = 500
IMPORT_EVENT_BATCH = 500
REVIEW_QUOTA_BATCH = 500


def delete_expired_sessions(db: Session, now: datetime | None = None, batch_size: int = SESSION_BATCH) -> int:
    """Delete sessions whose expires_at is strictly before `now`, in small committed batches.

    Touches only the sessions table. A session that is still valid is never selected, and running
    this again is harmless. Returns the number of rows deleted."""
    now = now or utcnow()
    total = 0
    while True:
        ids = db.scalars(select(UserSession.id).where(UserSession.expires_at < now).limit(batch_size)).all()
        if not ids:
            return total
        total += db.query(UserSession).filter(UserSession.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def delete_expired_login_attempts(db: Session, now: datetime | None = None, batch_size: int = ATTEMPT_BATCH) -> int:
    """Delete sign-in attempt records older than the throttle window, for every account.

    Uses the same cutoff as the throttle (api/auth.py): attempts at or before now - window no longer
    count, attempts after it do and are never touched. Small committed batches; harmless to repeat."""
    cutoff = (now or utcnow()) - LOGIN_FAILURE_WINDOW
    total = 0
    while True:
        ids = db.scalars(select(LoginAttempt.id).where(LoginAttempt.created_at <= cutoff).limit(batch_size)).all()
        if not ids:
            return total
        total += db.query(LoginAttempt).filter(LoginAttempt.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def delete_expired_ip_events(db: Session, now: datetime | None = None, batch_size: int = IP_EVENT_BATCH) -> int:
    """Delete per-IP rate-limit records whose window has passed (expires_at at or before `now`).

    Records still inside their window are never selected, so the limit is unaffected. Small committed
    batches; harmless to repeat."""
    now = now or utcnow()
    total = 0
    while True:
        ids = db.scalars(select(IpRateEvent.id).where(IpRateEvent.expires_at <= now).limit(batch_size)).all()
        if not ids:
            return total
        total += db.query(IpRateEvent).filter(IpRateEvent.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def delete_expired_import_events(db: Session, now: datetime | None = None, batch_size: int = IMPORT_EVENT_BATCH) -> int:
    """Delete import-quota records whose window has passed (expires_at at or before `now`). Records
    still inside their window are never selected. Small committed batches; harmless to repeat."""
    now = now or utcnow()
    total = 0
    while True:
        ids = db.scalars(select(ImportEvent.id).where(ImportEvent.expires_at <= now).limit(batch_size)).all()
        if not ids:
            return total
        total += db.query(ImportEvent).filter(ImportEvent.id.in_(ids)).delete(synchronize_session=False)
        db.commit()


def delete_expired_review_quota_events(
    db: Session, now: datetime | None = None, batch_size: int = REVIEW_QUOTA_BATCH
) -> int:
    """Delete per-user review-quota records whose hour has passed (expires_at at or before `now`).
    Records still inside their window are never selected. Small committed batches; harmless to repeat."""
    now = now or utcnow()
    total = 0
    while True:
        ids = db.scalars(select(ReviewQuotaEvent.id).where(ReviewQuotaEvent.expires_at <= now).limit(batch_size)).all()
        if not ids:
            return total
        total += db.query(ReviewQuotaEvent).filter(ReviewQuotaEvent.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
