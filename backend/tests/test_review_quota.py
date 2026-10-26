"""Database-backed per-user review quota: DEVPILOT_REVIEWS_PER_HOUR (30) reviews per user per rolling
hour, applied alongside the installation-wide cap (test_global_review_cap.py)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

import app.api.reviews as reviews
import app.workers.queue as queue
from app.core.db import SessionLocal
from app.models import ReviewAdmission, ReviewQuotaEvent, utcnow
from app.services.maintenance import delete_expired_review_quota_events
from tests.conftest import _counter, make_client, signed_up
from tests.test_api import _import_sample

LIMIT = 4  # small per-user limit so each test stays quick; the code path is the same as for 30


@pytest.fixture(autouse=True)
def limit(settings, monkeypatch):
    monkeypatch.setattr(settings, "reviews_per_hour", LIMIT)


def _user_with_repo(sample_zip):
    c = signed_up(f"rq{next(_counter)}@example.com", "correct-horse-9")
    return c, _import_sample(c, sample_zip)["id"]


def _review(c, rid) -> int:
    return c.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"}).status_code


def _count(model) -> int:
    with SessionLocal() as db:
        return db.query(model).count()


def test_default_is_thirty_per_hour():
    from app.core.config import Settings

    assert Settings.model_fields["reviews_per_hour"].default == 30 and reviews.USER_WINDOW == timedelta(hours=1)


def test_up_to_the_limit_is_admitted_and_the_next_is_refused(sample_zip):
    c, rid = _user_with_repo(sample_zip)
    assert [_review(c, rid) for _ in range(LIMIT + 2)] == [202] * LIMIT + [429, 429]
    r = c.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"})
    assert r.json()["detail"] == "Review limit reached. Try again later."
    assert _count(ReviewQuotaEvent) == LIMIT  # refused requests left nothing behind


def test_quota_is_per_user(sample_zip):
    (a, ra), (b, rb) = _user_with_repo(sample_zip), _user_with_repo(sample_zip)
    [_review(a, ra) for _ in range(LIMIT)]
    assert _review(a, ra) == 429 and _review(b, rb) == 202


def test_window_boundary(sample_zip, monkeypatch):
    t0 = utcnow()
    monkeypatch.setattr(reviews, "utcnow", lambda: t0)
    c, rid = _user_with_repo(sample_zip)
    [_review(c, rid) for _ in range(LIMIT)]
    monkeypatch.setattr(reviews, "utcnow", lambda: t0 + reviews.USER_WINDOW - timedelta(milliseconds=1))
    assert _review(c, rid) == 429
    monkeypatch.setattr(reviews, "utcnow", lambda: t0 + reviews.USER_WINDOW)
    assert _review(c, rid) == 202
    assert _count(ReviewQuotaEvent) == 1  # this user's expired records were removed on the way


def test_survives_a_restart(sample_zip):
    c, rid = _user_with_repo(sample_zip)
    [_review(c, rid) for _ in range(LIMIT)]
    restarted = make_client()  # nothing in process memory carries over
    restarted.cookies = c.cookies
    assert _review(restarted, rid) == 429


def test_concurrent_reviews_admit_exactly_the_quota(sample_zip, settings, monkeypatch):
    """Runs on SQLite by default; set DEVPILOT_TEST_DATABASE_URL to run it on PostgreSQL."""
    monkeypatch.setattr(settings, "reviews_per_hour", 10)
    base, rid = _user_with_repo(sample_zip)

    def attempt(_):
        c = make_client()
        c.cookies = base.cookies
        return _review(c, rid)

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(attempt, range(20)))
    assert codes.count(202) == 10 and codes.count(429) == 10  # never more, never fewer
    assert _count(ReviewQuotaEvent) == 10


# --- interaction with the installation-wide cap -----------------------------------------------


def test_global_cap_refusal_gives_the_users_slot_back(sample_zip, settings, monkeypatch):
    (other, orid), (c, rid) = _user_with_repo(sample_zip), _user_with_repo(sample_zip)
    monkeypatch.setattr(settings, "reviews_global_per_hour", 1)
    assert _review(other, orid) == 202  # fills the installation cap
    assert _review(c, rid) == 429  # refused by the installation cap
    assert _count(ReviewQuotaEvent) == 1 and _count(ReviewAdmission) == 1  # only the other user's
    monkeypatch.setattr(settings, "reviews_global_per_hour", 60)
    assert [_review(c, rid) for _ in range(LIMIT + 1)] == [202] * LIMIT + [429]  # full quota still there


def test_user_quota_refusal_uses_no_global_capacity(sample_zip):
    c, rid = _user_with_repo(sample_zip)
    [_review(c, rid) for _ in range(LIMIT)]
    assert _review(c, rid) == 429
    assert _count(ReviewAdmission) == LIMIT


def test_both_limits_apply_independently(sample_zip, settings, monkeypatch):
    monkeypatch.setattr(settings, "reviews_global_per_hour", LIMIT + 1)
    (a, ra), (b, rb) = _user_with_repo(sample_zip), _user_with_repo(sample_zip)
    assert [_review(a, ra) for _ in range(LIMIT + 1)] == [202] * LIMIT + [429]  # per-user limit
    assert [_review(b, rb) for _ in range(2)] == [202, 429]  # installation cap, b's own quota untouched
    assert _count(ReviewAdmission) == LIMIT + 1


# --- cleanup ---------------------------------------------------------------------------------


def test_cleanup_removes_only_expired_records_in_batches_and_the_quota_still_holds(sample_zip, monkeypatch):
    t0 = utcnow()
    monkeypatch.setattr(reviews, "utcnow", lambda: t0)
    c, rid = _user_with_repo(sample_zip)
    [_review(c, rid) for _ in range(LIMIT)]
    later = t0 + reviews.USER_WINDOW
    with SessionLocal() as db:
        assert delete_expired_review_quota_events(db, now=later - timedelta(seconds=1)) == 0
        assert delete_expired_review_quota_events(db, now=later, batch_size=3) == LIMIT
    monkeypatch.setattr(reviews, "utcnow", lambda: later)
    assert [_review(c, rid) for _ in range(LIMIT + 1)] == [202] * LIMIT + [429]


def test_worker_cleans_up_even_if_earlier_cleanups_fail(sample_zip, settings, monkeypatch):
    c, rid = _user_with_repo(sample_zip)
    _review(c, rid)
    with SessionLocal() as db:
        db.query(ReviewQuotaEvent).update({ReviewQuotaEvent.expires_at: utcnow() - timedelta(minutes=1)})
        db.commit()

    def boom(db):
        raise RuntimeError("earlier cleanup failed")

    for name in (
        "delete_expired_sessions",
        "delete_expired_login_attempts",
        "delete_expired_ip_events",
        "delete_expired_import_events",
    ):
        monkeypatch.setattr(queue, name, boom)
    queue.Worker(SessionLocal, settings).maybe_cleanup()  # must not raise
    assert _count(ReviewQuotaEvent) == 0
