"""GET /api/reviews/recent: the dashboard's newest reviews across the caller's own repositories."""

from tests.conftest import _counter, make_client, signed_up
from tests.test_api import _import_sample


def _user_with_reviews(sample_zip, n: int):
    c = signed_up(f"recent{next(_counter)}@example.com", "correct-horse-9")
    repo = _import_sample(c, sample_zip)
    ids = [c.post(f"/api/repositories/{repo['id']}/reviews", json={"kind": "full"}).json()["id"] for _ in range(n)]
    return c, repo, ids


def test_newest_first_with_repository_name_and_no_error_text(sample_zip):
    c, repo, ids = _user_with_reviews(sample_zip, 3)
    rows = c.get("/api/reviews/recent").json()
    assert [r["id"] for r in rows] == ids[::-1]
    assert {r["repository_name"] for r in rows} == {repo["name"]}
    assert {"status", "stage", "created_at", "finished_at", "severity_counts"} <= rows[0].keys()
    assert "error" not in rows[0] and "stats" not in rows[0]


def test_limit_is_bounded(sample_zip):
    c, _, ids = _user_with_reviews(sample_zip, 3)
    assert [r["id"] for r in c.get("/api/reviews/recent?limit=2").json()] == ids[:0:-1]
    assert c.get("/api/reviews/recent?limit=0").status_code == 422
    assert c.get("/api/reviews/recent?limit=21").status_code == 422


def test_empty_for_a_new_user():
    c = signed_up(f"recent{next(_counter)}@example.com", "correct-horse-9")
    assert c.get("/api/reviews/recent").json() == []


def test_requires_sign_in():
    assert make_client().get("/api/reviews/recent").status_code == 401


def test_other_users_reviews_are_not_listed(sample_zip):
    _user_with_reviews(sample_zip, 2)
    b, _, b_ids = _user_with_reviews(sample_zip, 1)
    assert [r["id"] for r in b.get("/api/reviews/recent?limit=20").json()] == b_ids
