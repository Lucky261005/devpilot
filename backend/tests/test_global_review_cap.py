"""Installation-wide cap on new review jobs per rolling hour (database-backed)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

import app.api.reviews as reviews
from app.core.db import SessionLocal
from app.models import ReviewAdmission, ReviewJob, utcnow
from tests.conftest import _counter, make_client, signed_up
from tests.test_api import _import_sample, _run_worker


def _user_with_repo(sample_zip):
    c = signed_up(f"cap{next(_counter)}@example.com", "correct-horse-9")
    return c, _import_sample(c, sample_zip)["id"]


def _review(c, rid):
    return c.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"})


def _jobs() -> int:
    with SessionLocal() as db:
        return db.query(ReviewJob).count()


def _admissions() -> int:
    with SessionLocal() as db:
        return db.query(ReviewAdmission).count()


@pytest.fixture
def cap(settings, monkeypatch):
    def set_cap(n: int) -> None:
        monkeypatch.setattr(settings, "reviews_global_per_hour", n)

    return set_cap


def test_default_cap_is_60_and_the_61st_is_refused(settings, sample_zip):
    assert settings.reviews_global_per_hour == 60
    before = _jobs()
    users = [_user_with_repo(sample_zip) for _ in range(3)]  # 3 x 20 stays under the per-user 30
    codes = [_review(c, rid).status_code for c, rid in users for _ in range(20)]
    assert codes == [202] * 60
    fourth, rid = _user_with_repo(sample_zip)
    r = _review(fourth, rid)
    assert r.status_code == 429 and "hourly review limit" in r.json()["detail"]
    assert 1 <= int(r.headers["retry-after"]) <= 3600
    assert _jobs() - before == 60 and _admissions() == 60


def test_all_users_share_one_cap(cap, sample_zip):
    cap(3)
    (a, ra), (b, rb) = _user_with_repo(sample_zip), _user_with_repo(sample_zip)
    assert [_review(a, ra).status_code, _review(a, ra).status_code, _review(b, rb).status_code] == [202] * 3
    assert _review(b, rb).status_code == 429  # B's first review hit the cap A mostly used


def test_per_user_quota_still_applies(settings, monkeypatch, sample_zip):
    monkeypatch.setattr(settings, "reviews_per_hour", 2)
    c, rid = _user_with_repo(sample_zip)
    assert [_review(c, rid).status_code for _ in range(2)] == [202, 202]
    r = _review(c, rid)
    assert r.status_code == 429 and r.json()["detail"] == "Review limit reached. Try again later."
    assert _admissions() == 2  # the per-user refusal used no global capacity


def test_refused_requests_create_no_jobs(cap, sample_zip):
    cap(2)
    c, rid = _user_with_repo(sample_zip)
    _review(c, rid), _review(c, rid)
    jobs = _jobs()
    assert [_review(c, rid).status_code for _ in range(3)] == [429] * 3
    assert _jobs() == jobs and _admissions() == 2


def test_deleting_a_repository_does_not_free_capacity(cap, sample_zip):
    cap(2)
    c, rid = _user_with_repo(sample_zip)
    _review(c, rid), _review(c, rid)
    assert c.delete(f"/api/repositories/{rid}").status_code == 204  # cascades its review jobs
    c2, rid2 = _user_with_repo(sample_zip)
    assert _review(c2, rid2).status_code == 429


def test_window_rolls_after_an_hour(cap, monkeypatch, sample_zip):
    cap(2)
    c, rid = _user_with_repo(sample_zip)
    _review(c, rid), _review(c, rid)
    assert _review(c, rid).status_code == 429
    later = utcnow() + timedelta(hours=1, seconds=1)
    monkeypatch.setattr(reviews, "utcnow", lambda: later)
    assert _review(c, rid).status_code == 202
    assert _admissions() == 1  # expired admissions are removed


def test_concurrent_requests_never_exceed_the_cap(cap, sample_zip):
    """SQLite: one writer at a time. The same commit-then-count rule holds on PostgreSQL under
    READ COMMITTED, but that path is not exercised here (no PostgreSQL in this environment)."""
    cap(5)
    owner, rid = _user_with_repo(sample_zip)
    jobs = _jobs()

    def attempt(_):
        c = make_client()
        c.cookies = owner.cookies
        return _review(c, rid).status_code

    with ThreadPoolExecutor(max_workers=12) as pool:
        codes = list(pool.map(attempt, range(12)))
    assert codes.count(202) <= 5 and set(codes) <= {202, 429}
    assert _jobs() - jobs == codes.count(202) and _admissions() == codes.count(202)


def test_admitted_jobs_are_queued_and_processed_as_before(cap, settings, sample_zip):
    cap(1)
    c, rid = _user_with_repo(sample_zip)
    r = _review(c, rid)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    _run_worker(settings)
    assert c.get(f"/api/reviews/{r.json()['id']}").json()["status"] == "completed"


def test_zero_cap_refuses_cleanly_instead_of_crashing(cap, sample_zip):
    c, rid = _user_with_repo(sample_zip)
    cap(0)
    jobs_before = _jobs()
    r = _review(c, rid)
    assert r.status_code == 429 and r.headers["Retry-After"] == str(int(reviews.GLOBAL_WINDOW.total_seconds()))
    assert _jobs() == jobs_before and _admissions() == 0


def test_settings_reject_a_zero_cap():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(reviews_global_per_hour=0)
