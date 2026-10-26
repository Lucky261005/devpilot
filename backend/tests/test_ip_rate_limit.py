"""Database-backed per-IP limit on sign-in and registration: 10 accepted requests per 60 s window."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient

import app.api.auth as auth
import app.workers.queue as queue
from app.core.db import SessionLocal
from app.core.security import ip_key
from app.models import IpRateEvent, utcnow
from app.services.maintenance import delete_expired_ip_events
from tests.conftest import _counter

BAD = {"password": "a-wrong-password"}


def _client(ip: str = "203.0.113.7") -> TestClient:
    from app.main import app

    c = TestClient(app, client=(ip, 40000))
    c.headers["x-devpilot-csrf"] = "1"
    return c


def _login(c) -> int:
    # A new email every time, so the per-account throttle never interferes.
    return c.post("/api/auth/login", json={"email": f"ip{next(_counter)}@example.com", **BAD}).status_code


def _rows(scope: str | None = None) -> list[IpRateEvent]:
    with SessionLocal() as db:
        q = db.query(IpRateEvent)
        return q.filter_by(scope=scope).all() if scope else q.all()


def test_eleventh_request_is_refused_and_refusals_use_no_slot():
    c = _client()
    codes = [_login(c) for _ in range(13)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429] * 3
    assert len(_rows("login")) == 10  # the three refused requests left nothing behind


def test_window_boundary(monkeypatch):
    t0 = utcnow()
    monkeypatch.setattr(auth, "utcnow", lambda: t0)
    c = _client()
    assert [_login(c) for _ in range(10)] == [401] * 10
    monkeypatch.setattr(auth, "utcnow", lambda: t0 + timedelta(seconds=59, microseconds=999_000))
    assert _login(c) == 429  # still inside the 60 s window
    monkeypatch.setattr(auth, "utcnow", lambda: t0 + auth.IP_WINDOW)
    assert _login(c) == 401  # exactly 60 s later the first ten no longer count
    assert len(_rows("login")) == 1  # this client's expired records were removed on the way


def test_sign_in_and_registration_are_counted_separately_per_ip():
    c = _client()
    [_login(c) for _ in range(10)]
    assert _login(c) == 429
    r = c.post("/api/auth/register", json={"email": f"sep{next(_counter)}@example.com", "password": "long-enough-pw"})
    assert r.status_code == 202  # registration has its own 10
    assert _login(_client("198.51.100.20")) == 401  # another address has its own 10


def test_survives_a_restart():
    c = _client()
    [_login(c) for _ in range(10)]
    restarted = _client()  # a new client and app instance: nothing in process memory carries over
    assert _login(restarted) == 429


def test_only_a_keyed_hash_of_the_ip_is_stored():
    _login(_client("203.0.113.99"))
    rows = _rows("login")
    assert len(rows) == 1 and rows[0].ip_key == ip_key("203.0.113.99") and len(rows[0].ip_key) == 64
    assert all("203.0.113.99" not in str(v) for v in (rows[0].scope, rows[0].ip_key, rows[0].expires_at))


def test_concurrent_requests_never_exceed_the_limit():
    """Runs on SQLite by default; set DEVPILOT_TEST_DATABASE_URL to run it on PostgreSQL."""

    def attempt(_):
        return _login(_client())

    with ThreadPoolExecutor(max_workers=16) as pool:
        codes = list(pool.map(attempt, range(16)))
    assert codes.count(401) == auth.IP_LIMIT and set(codes) == {401, 429}  # never more, never fewer
    assert len(_rows("login")) == codes.count(401)


# --- cleanup ---------------------------------------------------------------------------------


def _add(expires_ats) -> list[int]:
    with SessionLocal() as db:
        rows = [IpRateEvent(scope="login", ip_key="k" * 64, expires_at=t) for t in expires_ats]
        db.add_all(rows)
        db.commit()
        return [r.id for r in rows]


def _alive(ids):
    with SessionLocal() as db:
        return {r.id for r in db.query(IpRateEvent).filter(IpRateEvent.id.in_(ids))}


def test_cleanup_removes_only_records_outside_the_window():
    now = utcnow()
    expired = _add([now - timedelta(hours=1), now - timedelta(seconds=1), now])
    active = _add([now + timedelta(seconds=1), now + timedelta(seconds=59)])
    with SessionLocal() as db:
        assert delete_expired_ip_events(db, now=now) == 3
        assert delete_expired_ip_events(db, now=now) == 0  # harmless to repeat
    assert _alive(expired) == set() and _alive(active) == set(active)


def test_cleanup_works_in_batches():
    now = utcnow()
    ids = _add([now - timedelta(minutes=i + 1) for i in range(7)])
    with SessionLocal() as db:
        assert delete_expired_ip_events(db, now=now, batch_size=2) == 7
    assert _alive(ids) == set()


def _capture(monkeypatch) -> list[logging.LogRecord]:
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    logger = logging.getLogger("app.workers.queue")
    logger.addHandler(handler)
    monkeypatch.setattr(logger, "disabled", False)  # the test session's Alembic run disables loggers
    monkeypatch.setattr(logger, "level", logging.INFO)
    return records


def test_worker_cleans_up_and_failures_are_logged_without_addresses(settings, monkeypatch):
    ids = _add([utcnow() - timedelta(minutes=5)])
    records = _capture(monkeypatch)
    queue.Worker(SessionLocal, settings).maybe_cleanup()
    assert _alive(ids) == set()
    assert any("per-IP rate records" in r.getMessage() for r in records)

    def boom(db):
        raise RuntimeError("DELETE ... [parameters: ('203.0.113.7',)]")

    monkeypatch.setattr(queue, "delete_expired_ip_events", boom)
    records.clear()
    queue.Worker(SessionLocal, settings).maybe_cleanup()  # must not raise
    failures = [r for r in records if "per-IP rate record cleanup failed" in r.getMessage()]
    assert len(failures) == 1 and failures[0].exc_info is None and "RuntimeError" in failures[0].getMessage()
    assert "203.0.113.7" not in " ".join(r.getMessage() for r in records)


def test_limit_still_holds_after_cleanup(monkeypatch):
    t0 = utcnow()
    monkeypatch.setattr(auth, "utcnow", lambda: t0)
    c = _client()
    assert [_login(c) for _ in range(10)] == [401] * 10
    later = t0 + auth.IP_WINDOW
    with SessionLocal() as db:
        assert delete_expired_ip_events(db, now=later) == 10
    monkeypatch.setattr(auth, "utcnow", lambda: later)
    assert [_login(c) for _ in range(11)] == [401] * 10 + [429]  # a fresh window of exactly ten
    with SessionLocal() as db:
        assert delete_expired_ip_events(db, now=later) == 0  # the active ten are kept
    assert _login(c) == 429


def test_ip_cleanup_runs_when_earlier_cleanups_fail(settings, monkeypatch):
    ids = _add([utcnow() - timedelta(minutes=5)])

    def boom(db):
        raise RuntimeError("earlier cleanup failed")

    monkeypatch.setattr(queue, "delete_expired_sessions", boom)
    monkeypatch.setattr(queue, "delete_expired_login_attempts", boom)
    records = _capture(monkeypatch)
    queue.Worker(SessionLocal, settings).maybe_cleanup()  # must not raise
    assert _alive(ids) == set()
    text = " ".join(r.getMessage() for r in records)
    assert "expired-session cleanup failed" in text and "sign-in attempt cleanup failed" in text
    assert "deleted 1 expired per-IP rate records" in text
