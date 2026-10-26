"""Per-account sign-in throttle: 5 failed attempts per account per rolling 15 minutes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import app.api.auth as auth
from app.core.db import SessionLocal
from app.core.security import account_key
from app.models import IpRateEvent, LoginAttempt, utcnow
from tests.conftest import make_client, signed_up

PW = "the-right-password"
BAD = "a-wrong-password"


def _clear_ip_limit() -> None:
    with SessionLocal() as db:
        db.query(IpRateEvent).delete()
        db.commit()


def _login(c, email: str, password: str):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def _fail(c, email: str, n: int) -> list[int]:
    return [_login(c, email, BAD).status_code for _ in range(n)]


def test_sixth_attempt_is_refused_even_with_the_right_password():
    signed_up("lock@example.com", PW)
    c = make_client()
    assert _fail(c, "lock@example.com", 5) == [401] * 5
    r = _login(c, "lock@example.com", PW)
    assert r.status_code == 429 and r.json()["detail"] == auth.THROTTLED


def test_equivalent_emails_share_one_counter():
    signed_up("mixed@example.com", PW)
    c = make_client()
    for variant in [
        "mixed@example.com",
        "MIXED@example.com",
        "Mixed@Example.COM",
        "mIxEd@example.com",
        "MIXED@EXAMPLE.COM",
    ]:
        assert _login(c, variant, BAD).status_code == 401
    assert _login(c, "mixed@example.com", PW).status_code == 429
    assert account_key(" Mixed@Example.COM ") == account_key("mixed@example.com")


def test_unknown_account_gets_the_same_responses():
    signed_up("real@example.com", PW)
    real, ghost = make_client(), make_client()
    real_codes = [_login(real, "real@example.com", BAD) for _ in range(6)]
    _clear_ip_limit()  # test clients share one IP; keep the per-IP limit out of this comparison
    ghost_codes = [_login(ghost, "ghost@example.com", BAD) for _ in range(6)]
    assert [(r.status_code, r.json()["detail"]) for r in real_codes] == [
        (r.status_code, r.json()["detail"]) for r in ghost_codes
    ]  # request_id differs per request by design
    assert real_codes[-1].status_code == 429


def test_window_expires_after_15_minutes(monkeypatch):
    signed_up("expiry@example.com", PW)
    c = make_client()
    _fail(c, "expiry@example.com", 5)
    assert _login(c, "expiry@example.com", PW).status_code == 429
    later = utcnow() + timedelta(minutes=15, seconds=1)
    monkeypatch.setattr(auth, "utcnow", lambda: later)
    assert _login(c, "expiry@example.com", PW).status_code == 200


def test_success_clears_earlier_failures():
    signed_up("clears@example.com", PW)
    c = make_client()
    assert _fail(c, "clears@example.com", 4) == [401] * 4
    assert _login(c, "clears@example.com", PW).status_code == 200
    _clear_ip_limit()  # test clients share one IP; this test is about the per-account counter
    assert _fail(c, "clears@example.com", 5) == [401] * 5  # a fresh budget after the success
    assert _login(c, "clears@example.com", BAD).status_code == 429


def test_refused_attempts_do_not_extend_the_lockout(monkeypatch):
    c = make_client()
    _fail(c, "noextend@example.com", 5)
    for _ in range(3):
        assert _login(c, "noextend@example.com", BAD).status_code == 429
    with SessionLocal() as db:
        assert db.query(LoginAttempt).filter_by(account_key=account_key("noextend@example.com")).count() == 5


def test_per_ip_throttle_still_applies():
    c = make_client()  # 10 attempts per IP per minute, each for a different account
    codes = [_login(c, f"ip{i}@example.com", BAD).status_code for i in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_concurrent_attempts_check_the_password_at_most_five_times():
    signed_up("race@example.com", PW)

    def attempt(_):
        return _login(make_client(), "race@example.com", BAD).status_code

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(attempt, range(10)))
    assert codes.count(401) == auth.LOGIN_FAILURE_LIMIT and set(codes) == {401, 429}  # never more, never fewer
    assert _login(make_client(), "race@example.com", PW).status_code == 429  # still locked


def test_records_hold_no_email_or_password():
    c = make_client()
    _fail(c, "Private.Person@example.com", 2)
    with SessionLocal() as db:
        rows = db.query(LoginAttempt).all()
    assert len(rows) == 2
    for row in rows:
        assert len(row.account_key) == 64 and int(row.account_key, 16) >= 0
        assert "private" not in row.account_key.lower() and BAD not in row.account_key
    assert {r.account_key for r in rows} == {account_key("private.person@example.com")}
