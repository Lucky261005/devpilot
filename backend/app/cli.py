"""Maintenance commands.  python -m app.cli cleanup"""

import argparse
import shutil
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.models import ReviewJob, UserSession, utcnow


def cleanup() -> None:
    """Retention: delete per-review source snapshots and expired sessions. Findings (with
    their short evidence excerpts) are kept until the repository is deleted."""
    settings = get_settings()
    cutoff = utcnow() - timedelta(days=settings.retention_days)
    removed = 0
    with SessionLocal() as db:
        jobs = db.scalars(select(ReviewJob).where(ReviewJob.kind != "full", ReviewJob.finished_at < cutoff)).all()
        for job in jobs:
            path = settings.data_dir / "snapshots" / str(job.repository_id) / f"review-{job.id}"
            if path.exists():
                shutil.rmtree(path)
                removed += 1
        expired = db.query(UserSession).filter(UserSession.expires_at < utcnow()).delete()
        db.commit()
    print(f"removed {removed} review snapshots, {expired} expired sessions")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["cleanup"])
    args = p.parse_args()
    cleanup()
