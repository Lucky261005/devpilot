"""Administrator commands, run on the server (not reachable over HTTP).

python -m app.cli cleanup
python -m app.cli create-user --email you@example.com          # prompts for the password
printf '%s' "$PW" | python -m app.cli create-user --email you@example.com --password-stdin
"""

import argparse
import getpass
import shutil
import sys
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import AuditEvent, ReviewJob, User, utcnow
from app.schemas import Credentials
from app.services.maintenance import (
    delete_expired_import_events,
    delete_expired_ip_events,
    delete_expired_login_attempts,
    delete_expired_review_quota_events,
    delete_expired_sessions,
)


def cleanup() -> None:
    """Retention: delete per-review source snapshots older than the retention period, expired
    sessions, sign-in attempt records outside the throttle window, per-IP rate records outside
    their 60 s window and import and review quota records outside their hour. Findings (with their short
    evidence excerpts) are kept until the repository is deleted."""
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
        db.commit()
        expired = delete_expired_sessions(db)
        attempts = delete_expired_login_attempts(db)
        ip_events = delete_expired_ip_events(db)
        imports = delete_expired_import_events(db)
        reviews = delete_expired_review_quota_events(db)
    print(
        f"removed {removed} review snapshots, {expired} expired sessions, {attempts} expired sign-in attempts, "
        f"{ip_events} expired per-IP rate records, {imports} expired import quota records, "
        f"{reviews} expired review quota records"
    )


class CommandError(Exception):
    pass


def create_user(email: str, password: str) -> str:
    """Create an account directly, whatever DEVPILOT_REGISTRATION says. For the server operator:
    this is how a fresh installation gets its first account when public registration is off.

    Same validation (email format, 10 to 256 character password) and hashing as sign-up."""
    try:
        creds = Credentials(email=email, password=password)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise CommandError(f"Invalid account details: {problems}") from None
    email = creds.email.lower()
    with SessionLocal() as db:
        if db.query(User).filter_by(email=email).first():
            raise CommandError(f"An account with {email} already exists; nothing was changed.")
        user = User(email=email, password_hash=hash_password(creds.password))
        db.add(user)
        db.flush()
        db.add(AuditEvent(user_id=user.id, action="user.create_cli"))
        db.commit()
    return email


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.read().rstrip("\r\n")
    first = getpass.getpass("Password (10+ characters): ")
    if first != getpass.getpass("Repeat password: "):
        raise CommandError("Passwords do not match; nothing was changed.")
    return first


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("cleanup", help="delete expired review snapshots and sessions")
    cu = sub.add_parser("create-user", help="create an account (works in every registration mode)")
    cu.add_argument("--email", required=True)
    cu.add_argument("--password-stdin", action="store_true", help="read the password from stdin, not a prompt")
    args = p.parse_args(argv)
    if args.command == "cleanup":
        cleanup()
        return 0
    try:
        email = create_user(args.email, _read_password(args.password_stdin))
    except CommandError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Created account {email}. Sign in at the web UI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
