"""Database-backed job queue. `review_jobs` is the queue: no Redis needed at this scale.

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL, so several workers can run
safely. SQLite ignores the lock clause; run a single worker there (the default)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.integrations.github import GitHubError
from app.models import ReviewJob, utcnow
from app.services.ingestion import IngestionError
from app.services.maintenance import (
    delete_expired_import_events,
    delete_expired_ip_events,
    delete_expired_login_attempts,
    delete_expired_review_quota_events,
    delete_expired_sessions,
)
from app.services.review import run_review

log = logging.getLogger(__name__)


def recover_stale_jobs(db: Session, settings: Settings) -> int:
    """Jobs left 'running' by a crashed worker (or past the timeout) are marked failed."""
    cutoff = utcnow() - timedelta(seconds=settings.job_timeout_s)
    res = db.execute(
        update(ReviewJob)
        .where(ReviewJob.status == "running", ReviewJob.started_at < cutoff)
        .values(
            status="failed", error="Job did not finish in time (worker stopped or timed out).", finished_at=utcnow()
        )
    )
    db.commit()
    return getattr(res, "rowcount", 0) or 0


def claim_next(db: Session) -> ReviewJob | None:
    job = db.scalars(
        select(ReviewJob)
        .where(ReviewJob.status == "queued")
        .order_by(ReviewJob.created_at, ReviewJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        db.rollback()
        return None
    job.status, job.started_at, job.stage = "running", utcnow(), "starting"
    db.commit()
    return job


def process_job(db: Session, job: ReviewJob, settings: Settings, **kwargs) -> None:
    def set_stage(stage: str) -> None:
        job.stage = stage
        db.commit()

    try:
        run_review(db, job, settings, set_stage=set_stage, **kwargs)
        job.status = "completed"
    except (IngestionError, GitHubError) as e:  # expected, user-facing failures
        db.rollback()
        job.status, job.error = "failed", str(e)
    except Exception as e:  # noqa: BLE001 - any failure must be recorded, not lost
        db.rollback()
        log.exception("review job %s failed", job.id)
        job.status = "failed"
        job.error = f"Internal error during '{job.stage}' ({type(e).__name__}). See server logs."
    job.finished_at = utcnow()
    job.stage = None
    db.commit()


def run_once(session_factory: sessionmaker, settings: Settings, **kwargs) -> bool:
    with session_factory() as db:
        job = claim_next(db)
        if job is None:
            return False
        log.info("processing review job %s", job.id)
        process_job(db, job, settings, **kwargs)
        return True


class Worker(threading.Thread):
    # Expired-session cleanup runs when the queue is idle, at most this often (and at start).
    CLEANUP_EVERY_S = 3600.0

    def __init__(self, session_factory: sessionmaker, settings: Settings, poll_s: float = 1.0):
        super().__init__(daemon=True, name="review-worker")
        self.session_factory, self.settings, self.poll_s = session_factory, settings, poll_s
        self.stop_event = threading.Event()
        self.next_cleanup = 0.0  # monotonic time; 0 = due now

    def maybe_cleanup(self) -> None:
        """Delete expired sessions, sign-in attempts, per-IP rate records and import and review quota
        records if due. Never raises: a failure is logged and retried later; one task failing does not skip the
        others."""
        if time.monotonic() < self.next_cleanup:
            return
        self.next_cleanup = time.monotonic() + self.CLEANUP_EVERY_S
        try:
            with self.session_factory() as db:
                if n := delete_expired_sessions(db):
                    log.info("deleted %s expired sessions", n)
        except Exception:  # noqa: BLE001 - housekeeping must not stop review processing
            log.exception("expired-session cleanup failed; will retry in %ss", int(self.CLEANUP_EVERY_S))
        try:
            with self.session_factory() as db:
                if n := delete_expired_login_attempts(db):
                    log.info("deleted %s expired sign-in attempt records", n)
        except Exception as e:  # noqa: BLE001
            # Error type only: database errors can quote query parameters, and this table is keyed by
            # account identifiers.
            log.error(
                "expired sign-in attempt cleanup failed (%s); will retry in %ss",
                type(e).__name__,
                int(self.CLEANUP_EVERY_S),
            )
        try:
            with self.session_factory() as db:
                if n := delete_expired_ip_events(db):
                    log.info("deleted %s expired per-IP rate records", n)
        except Exception as e:  # noqa: BLE001
            # Error type only, for the same reason: rows are keyed by (hashed) client addresses.
            log.error(
                "expired per-IP rate record cleanup failed (%s); will retry in %ss",
                type(e).__name__,
                int(self.CLEANUP_EVERY_S),
            )
        try:
            with self.session_factory() as db:
                if n := delete_expired_import_events(db):
                    log.info("deleted %s expired import quota records", n)
        except Exception as e:  # noqa: BLE001
            log.error(
                "expired import quota record cleanup failed (%s); will retry in %ss",
                type(e).__name__,
                int(self.CLEANUP_EVERY_S),
            )
        try:
            with self.session_factory() as db:
                if n := delete_expired_review_quota_events(db):
                    log.info("deleted %s expired review quota records", n)
        except Exception as e:  # noqa: BLE001
            log.error(
                "expired review quota record cleanup failed (%s); will retry in %ss",
                type(e).__name__,
                int(self.CLEANUP_EVERY_S),
            )

    def run(self) -> None:
        with self.session_factory() as db:
            if n := recover_stale_jobs(db, self.settings):
                log.warning("marked %s stale jobs as failed", n)
        while not self.stop_event.is_set():
            try:
                if not run_once(self.session_factory, self.settings):
                    self.maybe_cleanup()  # only between jobs, never while one is running
                    self.stop_event.wait(self.poll_s)
            except Exception:  # noqa: BLE001 - keep the worker alive on DB hiccups
                log.exception("worker loop error")
                time.sleep(self.poll_s)


if __name__ == "__main__":  # standalone worker: python -m app.workers.queue
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.core.logging import configure_logging

    configure_logging()
    w = Worker(SessionLocal, get_settings())
    w.run()
