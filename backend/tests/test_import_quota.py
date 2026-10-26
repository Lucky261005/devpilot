"""Database-backed per-user repository import quota: 20 admitted imports per user per rolling hour."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import app.api.repositories as repositories
import app.workers.queue as queue
from app.core.db import SessionLocal
from app.models import ImportEvent, utcnow
from app.services.maintenance import delete_expired_import_events
from tests.conftest import _counter, make_client, signed_up

PW = "long-enough-pw"


def _user():
    return signed_up(f"imp{next(_counter)}@example.com", PW)


def _import(c) -> int:
    # Quota is checked before anything else, so a request that then fails (here: local import is not
    # allowed) still uses a slot, exactly like a real import.
    return c.post("/api/repositories/local", json={"path": "/nowhere", "name": "x"}).status_code


def _rows() -> list[ImportEvent]:
    with SessionLocal() as db:
        return db.query(ImportEvent).all()


def test_twenty_imports_are_admitted_and_the_twenty_first_is_refused():
    c = _user()
    codes = [_import(c) for _ in range(22)]
    assert 429 not in codes[:20] and codes[20:] == [429, 429]
    assert len(_rows()) == 20  # refused requests left nothing behind


def test_quota_is_per_user():
    a, b = _user(), _user()
    [_import(a) for _ in range(20)]
    assert _import(a) == 429
    assert _import(b) != 429


def test_window_boundary(monkeypatch):
    t0 = utcnow()
    monkeypatch.setattr(repositories, "utcnow", lambda: t0)
    c = _user()
    [_import(c) for _ in range(20)]
    monkeypatch.setattr(repositories, "utcnow", lambda: t0 + repositories.IMPORT_WINDOW - timedelta(milliseconds=1))
    assert _import(c) == 429
    monkeypatch.setattr(repositories, "utcnow", lambda: t0 + repositories.IMPORT_WINDOW)
    assert _import(c) != 429
    assert len(_rows()) == 1  # this user's expired records were removed on the way


def test_survives_a_restart():
    c = _user()
    [_import(c) for _ in range(20)]
    restarted = make_client()  # nothing in process memory carries over
    restarted.cookies = c.cookies
    assert _import(restarted) == 429


def test_only_the_user_id_and_expiry_are_stored():
    c = _user()
    _import(c)
    assert set(ImportEvent.__table__.columns.keys()) == {"id", "user_id", "expires_at"}
    assert len(_rows()) == 1


def test_concurrent_imports_admit_exactly_the_quota():
    """Runs on SQLite by default; set DEVPILOT_TEST_DATABASE_URL to run it on PostgreSQL."""
    base = _user()

    def attempt(_):
        c = make_client()
        c.cookies = base.cookies
        return _import(c)

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(attempt, range(26)))
    assert len(codes) - codes.count(429) == repositories.IMPORT_LIMIT  # never more, never fewer
    assert len(_rows()) == repositories.IMPORT_LIMIT


# --- cleanup ---------------------------------------------------------------------------------


def test_cleanup_removes_only_expired_records_in_batches_and_the_quota_still_holds(monkeypatch):
    t0 = utcnow()
    monkeypatch.setattr(repositories, "utcnow", lambda: t0)
    c = _user()
    [_import(c) for _ in range(20)]
    later = t0 + repositories.IMPORT_WINDOW
    with SessionLocal() as db:
        assert delete_expired_import_events(db, now=later - timedelta(seconds=1)) == 0  # all still active
        assert delete_expired_import_events(db, now=later, batch_size=3) == 20
    monkeypatch.setattr(repositories, "utcnow", lambda: later)
    codes = [_import(c) for _ in range(21)]
    assert 429 not in codes[:20] and codes[20] == 429


def test_worker_cleans_up_even_if_earlier_cleanups_fail(settings, monkeypatch):
    c = _user()
    _import(c)
    with SessionLocal() as db:
        db.query(ImportEvent).update({ImportEvent.expires_at: utcnow() - timedelta(minutes=1)})
        db.commit()

    def boom(db):
        raise RuntimeError("earlier cleanup failed")

    for name in ("delete_expired_sessions", "delete_expired_login_attempts", "delete_expired_ip_events"):
        monkeypatch.setattr(queue, name, boom)
    queue.Worker(SessionLocal, settings).maybe_cleanup()  # must not raise
    assert _rows() == []
