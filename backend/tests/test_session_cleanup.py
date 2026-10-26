"""Expired-session cleanup: what it deletes, what it keeps, and when the worker runs it."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select

import app.workers.queue as queue
from app.core.db import SessionLocal
from app.core.security import hash_token
from app.models import (
    AuditEvent,
    LoginAttempt,
    Repository,
    ReviewAdmission,
    ReviewJob,
    User,
    UserSession,
    utcnow,
)
from app.services.maintenance import delete_expired_sessions
from tests.conftest import _counter, signed_up


def _add_sessions(user_id: int, offsets: list[timedelta]) -> list[int]:
    with SessionLocal() as db:
        rows = [
            UserSession(user_id=user_id, token_hash=hash_token(f"t-{next(_counter)}"), expires_at=utcnow() + off)
            for off in offsets
        ]
        db.add_all(rows)
        db.commit()
        return [r.id for r in rows]


def _alive(ids: list[int]) -> set[int]:
    with SessionLocal() as db:
        return set(db.scalars(select(UserSession.id).where(UserSession.id.in_(ids))))


@pytest.fixture
def user_id():
    c = signed_up(f"sess{next(_counter)}@example.com", "correct-horse-7")
    with SessionLocal() as db:
        return db.query(User.id).filter_by(email=c.email).scalar()


def test_deletes_only_expired_sessions(user_id):
    expired = _add_sessions(user_id, [timedelta(days=-8), timedelta(hours=-1), timedelta(seconds=-1)])
    valid = _add_sessions(user_id, [timedelta(seconds=30), timedelta(days=6)])
    with SessionLocal() as db:
        deleted = delete_expired_sessions(db)
    assert deleted >= 3  # other tests may have left expired rows of their own
    assert _alive(expired) == set() and _alive(valid) == set(valid)


def test_repeated_cleanup_is_harmless(user_id):
    _add_sessions(user_id, [timedelta(minutes=-5)])
    valid = _add_sessions(user_id, [timedelta(days=1)])
    with SessionLocal() as db:
        delete_expired_sessions(db)
        assert delete_expired_sessions(db) == 0 and delete_expired_sessions(db) == 0
    assert _alive(valid) == set(valid)


def test_works_in_small_batches(user_id):
    with SessionLocal() as db:
        delete_expired_sessions(db)  # start from a clean slate
    expired = _add_sessions(user_id, [timedelta(minutes=-i) for i in range(1, 8)])
    with SessionLocal() as db:
        assert delete_expired_sessions(db, batch_size=2) == 7
    assert _alive(expired) == set()


def test_unrelated_data_is_untouched(user_id):
    with SessionLocal() as db:
        db.add_all([LoginAttempt(account_key="a" * 64, created_at=utcnow()), ReviewAdmission(created_at=utcnow())])
        db.commit()

    def counts():
        with SessionLocal() as db:
            return [
                db.scalar(select(func.count()).select_from(m))
                for m in (User, Repository, ReviewJob, AuditEvent, LoginAttempt, ReviewAdmission)
            ]

    before = counts()
    _add_sessions(user_id, [timedelta(days=-1)])
    with SessionLocal() as db:
        delete_expired_sessions(db)
    assert counts() == before


def test_signed_in_client_keeps_working_after_cleanup():
    c = signed_up(f"active{next(_counter)}@example.com", "correct-horse-8")
    with SessionLocal() as db:
        delete_expired_sessions(db)
    assert c.get("/api/auth/me").status_code == 200


def test_worker_runs_cleanup_when_due_and_survives_failures(settings, monkeypatch, user_id):
    w = queue.Worker(SessionLocal, settings)
    expired = _add_sessions(user_id, [timedelta(hours=-2)])
    w.maybe_cleanup()  # due at start
    assert _alive(expired) == set()

    later = _add_sessions(user_id, [timedelta(hours=-2)])
    w.maybe_cleanup()  # not due again for an hour
    assert _alive(later) == set(later)

    def boom(db):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(queue, "delete_expired_sessions", boom)
    w.next_cleanup = 0
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    # The app's logging setup replaces root handlers, so listen on the worker's own logger.
    logger = logging.getLogger("app.workers.queue")
    logger.addHandler(handler)
    # The test session's Alembic run (fileConfig) disables existing loggers; production runs
    # migrations in a separate process, so re-enable it here.
    monkeypatch.setattr(logger, "disabled", False)
    try:
        w.maybe_cleanup()  # must not raise
    finally:
        logger.removeHandler(handler)
    text = " ".join(r.getMessage() for r in records)
    assert "expired-session cleanup failed" in text and records[0].levelno == logging.ERROR
    assert "token" not in text.lower()
