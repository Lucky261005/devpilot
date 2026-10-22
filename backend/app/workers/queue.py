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
    def __init__(self, session_factory: sessionmaker, settings: Settings, poll_s: float = 1.0):
        super().__init__(daemon=True, name="review-worker")
        self.session_factory, self.settings, self.poll_s = session_factory, settings, poll_s
        self.stop_event = threading.Event()

    def run(self) -> None:
        with self.session_factory() as db:
            if n := recover_stale_jobs(db, self.settings):
                log.warning("marked %s stale jobs as failed", n)
        while not self.stop_event.is_set():
            try:
                if not run_once(self.session_factory, self.settings):
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
