"""Pull-request review scope: pinned head commit, changed-file edge cases, a moving head, and
isolation between users. Uses the mocked GitHub API from test_api.py (acme/shop, PR #7, base
"b"*40, head "c"*40, one changed file inventory/pricing.py)."""

import httpx

from app.integrations import github
from tests.test_api import GH_CALLS, GH_OVERRIDES, _run_worker, github_mock  # noqa: F401 (fixture)

FILES = "/repos/acme/shop/pulls/7/files"
BASE, HEAD = "b" * 40, "c" * 40


def _open_pr(client) -> int:
    rid = client.post("/api/repositories/github", json={"full_name": "acme/shop"}).json()["id"]
    assert client.get(f"/api/repositories/{rid}/pulls/7").status_code == 200
    return rid


def _review(client, rid, settings, gh) -> dict:
    job = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "pull_request", "pr_number": 7}).json()
    _run_worker(settings, github_factory=gh.GitHubClient)
    return client.get(f"/api/reviews/{job['id']}").json()


def test_snapshot_is_downloaded_at_the_head_commit_not_the_base(client, github_mock, settings):  # noqa: F811
    review = _review(client, _open_pr(client), settings, github_mock)
    assert review["status"] == "completed", review["error"]
    assert (review["stats"]["base_sha"], review["stats"]["head_sha"]) == (BASE, HEAD)
    assert f"/repos/acme/shop/zipball/{HEAD}" in GH_CALLS
    assert f"/repos/acme/shop/zipball/{BASE}" not in GH_CALLS
    assert review["stats"]["pr_files_truncated"] is False


def test_removed_renamed_binary_and_patchless_files(client, github_mock, settings):  # noqa: F811
    GH_OVERRIDES[FILES] = httpx.Response(
        200,
        json=[
            {"filename": "inventory/old.py", "status": "removed", "additions": 0, "deletions": 1,
             "patch": "@@ -1 +0,0 @@\n-x = 1"},
            {"filename": "inventory/store.py", "previous_filename": "inventory/shop.py", "status": "renamed",
             "additions": 0, "deletions": 0},
            {"filename": "inventory/pricing.py", "status": "modified", "additions": 900, "deletions": 0},
            {"filename": "docs/logo.png", "status": "added", "additions": 0, "deletions": 0},
        ],
    )  # fmt: skip
    rid = _open_pr(client)
    review = _review(client, rid, settings, github_mock)
    assert review["status"] == "completed", review["error"]
    changed = {f["path"]: f["status"] for f in client.get(f"/api/reviews/{review['id']}/changed-files").json()}
    assert changed == {
        "inventory/old.py": "removed",
        "inventory/store.py": "renamed",
        "inventory/pricing.py": "modified",
        "docs/logo.png": "added",
    }
    # Only the two Python files present at head are reviewed; the removed file and the image are not.
    assert review["stats"]["files_reviewed"] == 2
    # A pure rename changes no lines, and pricing.py came without a patch: no findings can be
    # scoped to changed lines, and the patchless file is reported instead of dropped silently.
    assert client.get(f"/api/reviews/{review['id']}/findings").json() == []
    assert review["stats"]["files_without_patch"] == ["inventory/pricing.py"]


def test_empty_pull_request_completes_with_nothing_reviewed(client, github_mock, settings):  # noqa: F811
    GH_OVERRIDES[FILES] = httpx.Response(200, json=[])
    review = _review(client, _open_pr(client), settings, github_mock)
    assert review["status"] == "completed", review["error"]
    assert review["stats"]["files_reviewed"] == 0 and review["stats"]["files_without_patch"] == []


def test_a_push_during_preparation_fails_the_review_instead_of_mixing_commits(
    client,
    github_mock,  # noqa: F811
    settings,
    monkeypatch,
):
    rid = _open_pr(client)
    real_pull = github.GitHubClient.pull
    heads = iter([HEAD, "d" * 40])  # first read at the start of the job, second after the file list

    def moving_pull(self, full_name, number):
        return {**real_pull(self, full_name, number), "head_sha": next(heads)}

    monkeypatch.setattr(github.GitHubClient, "pull", moving_pull)
    review = _review(client, rid, settings, github_mock)
    assert review["status"] == "failed" and "new commits" in review["error"]
    assert not any("/zipball/" + "d" * 40 in c for c in GH_CALLS)


def test_another_user_cannot_open_review_or_read_a_pull_request_review(
    client,
    other_client,
    github_mock,  # noqa: F811
    settings,
):
    rid = _open_pr(client)
    review = _review(client, rid, settings, github_mock)
    rv = review["id"]
    assert other_client.get(f"/api/repositories/{rid}/pulls/7").status_code == 404
    body = {"kind": "pull_request", "pr_number": 7}
    assert other_client.post(f"/api/repositories/{rid}/reviews", json=body).status_code == 404
    for path in ("", "/findings", "/changed-files", "/test-suggestions"):
        assert other_client.get(f"/api/reviews/{rv}{path}").status_code == 404, path
    assert all(r["id"] != rv for r in other_client.get("/api/reviews/recent?limit=20").json())
