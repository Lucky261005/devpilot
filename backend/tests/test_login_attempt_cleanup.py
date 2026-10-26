"""Expired sign-in attempt records are removed for every account, never the ones still counted."""

import logging
from datetime import timedelta

import app.workers.queue as queue
from app.api.auth import LOGIN_FAILURE_WINDOW
from app.core.db import SessionLocal
from app.core.security import account_key
from app.models import LoginAttempt, UserSession, utcnow
from app.services.maintenance import delete_expired_login_attempts
from tests.conftest import make_client, signed_up


def _add(created_ats, key: str = "k" * 64) -> list[int]:
    with SessionLocal() as db:
        rows = [LoginAttempt(account_key=key, created_at=t) for t in created_ats]
        db.add_all(rows)
        db.commit()
        return [r.id for r in rows]


def _alive(ids: list[int]) -> set[int]:
    with SessionLocal() as db:
        return {r.id for r in db.query(LoginAttempt).filter(LoginAttempt.id.in_(ids))}


def test_only_attempts_outside_the_window_are_deleted():
    now = utcnow()
    expired = _add([now - timedelta(days=30), now - timedelta(hours=1), now - LOGIN_FAILURE_WINDOW])
    recent = _add([now - LOGIN_FAILURE_WINDOW + timedelta(seconds=1), now - timedelta(minutes=1), now])
    with SessionLocal() as db:
        assert delete_expired_login_attempts(db, now=now) == 3
    assert _alive(expired) == set() and _alive(recent) == set(recent)


def test_accounts_never_retried_are_cleaned_up():
    old = utcnow() - timedelta(days=30)
    ids = _add([old], key="a" * 64) + _add([old], key="b" * 64) + _add([old], key="c" * 64)
    with SessionLocal() as db:
        delete_expired_login_attempts(db)
    assert _alive(ids) == set()


def test_cleanup_does_not_weaken_the_throttle():
    signed_up("still-locked@example.com", "the-right-password")
    c = make_client()
    for _ in range(5):
        c.post("/api/auth/login", json={"email": "still-locked@example.com", "password": "a-wrong-password"})
    with SessionLocal() as db:
        assert delete_expired_login_attempts(db) == 0  # all five are inside the window
    r = c.post("/api/auth/login", json={"email": "still-locked@example.com", "password": "the-right-password"})
    assert r.status_code == 429


def test_batches_and_repeats():
    now = utcnow()
    ids = _add([now - timedelta(hours=2, minutes=i) for i in range(7)])
    with SessionLocal() as db:
        assert delete_expired_login_attempts(db, now=now, batch_size=2) == 7
        assert delete_expired_login_attempts(db, now=now) == 0
        assert delete_expired_login_attempts(db, now=now) == 0
    assert _alive(ids) == set()


def test_other_tables_are_untouched():
    signed_up("keeps-session@example.com", "the-right-password")
    with SessionLocal() as db:
        sessions = db.query(UserSession).count()
    _add([utcnow() - timedelta(days=1)])
    with SessionLocal() as db:
        delete_expired_login_attempts(db)
        assert db.query(UserSession).count() == sessions


def _capture(monkeypatch) -> list[logging.LogRecord]:
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger("app.workers.queue")
    logger.addHandler(handler)
    monkeypatch.setattr(logger, "disabled", False)  # the test session's Alembic run disables loggers
    monkeypatch.setattr(logger, "level", logging.INFO)
    return records


def test_worker_runs_it_and_logs_only_counts(settings, monkeypatch):
    ids = _add([utcnow() - timedelta(hours=3)], key=account_key("private.person@example.com"))
    records = _capture(monkeypatch)
    queue.Worker(SessionLocal, settings).maybe_cleanup()
    assert _alive(ids) == set()
    text = " ".join(r.getMessage() for r in records)
    assert "expired sign-in attempt records" in text
    assert "private" not in text and account_key("private.person@example.com") not in text


def test_worker_failure_is_logged_safely_and_does_not_skip_session_cleanup(settings, monkeypatch):
    key = account_key("victim@example.com")

    def boom(db):
        raise RuntimeError(f"UPDATE login_attempts ... [parameters: ('{key}',)]")

    monkeypatch.setattr(queue, "delete_expired_login_attempts", boom)
    sessions_cleaned = []
    monkeypatch.setattr(queue, "delete_expired_sessions", lambda db: sessions_cleaned.append(1) or 0)
    records = _capture(monkeypatch)
    queue.Worker(SessionLocal, settings).maybe_cleanup()  # must not raise
    failures = [r for r in records if "sign-in attempt cleanup failed" in r.getMessage()]
    assert len(failures) == 1 and failures[0].levelno == logging.ERROR
    assert "RuntimeError" in failures[0].getMessage() and failures[0].exc_info is None
    assert key not in " ".join(r.getMessage() for r in records) and "victim" not in " ".join(
        r.getMessage() for r in records
    )
    assert sessions_cleaned == [1]
