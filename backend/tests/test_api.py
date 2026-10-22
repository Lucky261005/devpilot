"""Integration tests through the HTTP API with a real database, real analyzers, and a replayed
LLM response in place of the network call."""

import httpx
import pytest

from app.ai.provider import StaticReplayProvider
from app.core.db import SessionLocal
from app.core.security import encrypt_secret
from app.models import GitHubAccount, ReviewJob, User
from app.workers.queue import claim_next, recover_stale_jobs, run_once
from tests.conftest import SAMPLE, make_client, zip_dir


def _import_sample(client, sample_zip, name="inventory"):
    with open(sample_zip, "rb") as f:
        r = client.post(
            "/api/repositories/archive", data={"name": name}, files={"file": ("sample.zip", f, "application/zip")}
        )
    assert r.status_code == 201, r.text
    return r.json()


def _run_worker(settings, **kw):
    assert run_once(SessionLocal, settings, **kw)


def test_auth_flow_and_session_cookie():
    c = make_client()
    assert c.get("/api/auth/me").status_code == 401
    r = c.post("/api/auth/register", json={"email": "Flow@Example.com", "password": "long-enough-pw"})
    assert r.status_code == 201 and r.json()["email"] == "flow@example.com"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").status_code == 200
    assert (
        c.post("/api/auth/register", json={"email": "flow@example.com", "password": "long-enough-pw"}).status_code
        == 409
    )
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/auth/me").status_code == 401
    assert (
        c.post("/api/auth/login", json={"email": "flow@example.com", "password": "wrong-password"}).status_code == 401
    )
    assert (
        c.post("/api/auth/login", json={"email": "flow@example.com", "password": "long-enough-pw"}).status_code == 200
    )


def test_short_password_and_bad_email_rejected():
    c = make_client()
    assert c.post("/api/auth/register", json={"email": "x@example.com", "password": "short"}).status_code == 422
    assert c.post("/api/auth/register", json={"email": "nope", "password": "long-enough-pw"}).status_code == 422


def test_csrf_header_required_for_mutations(client):
    del client.headers["x-devpilot-csrf"]
    assert client.post("/api/auth/logout").status_code == 403


def test_oversized_request_rejected(client, settings):
    r = client.post(
        "/api/repositories/archive",
        headers={"content-length": str(settings.max_upload_bytes + 2_000_000)},
        content=b"x",
    )
    assert r.status_code == 413


def test_import_index_search_and_file_view(client, sample_zip):
    repo = _import_sample(client, sample_zip)
    assert repo["index_status"] == "ready" and repo["file_count"] >= 5
    rid = repo["id"]
    r = client.get(f"/api/repositories/{rid}/search", params={"q": "apply_discount", "mode": "identifier"})
    hits = r.json()["results"]
    assert hits and hits[0]["path"] == "inventory/pricing.py" and hits[0]["line"] == 4
    r = client.get(f"/api/repositories/{rid}/search", params={"q": "shell=True"})
    assert "inventory/store.py" in {h["path"] for h in r.json()["results"]}
    f = client.get(f"/api/repositories/{rid}/file", params={"path": "inventory/pricing.py"}).json()
    assert f["language"] == "python" and f["content"].splitlines()[3].startswith("def apply_discount")
    assert client.get(f"/api/repositories/{rid}/file", params={"path": "../../etc/passwd"}).status_code == 404


def test_malformed_archive_is_recorded_as_failed(client, tmp_path):
    bad = tmp_path / "bad.zip"
    import zipfile

    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.py", "x")
    with open(bad, "rb") as f:
        r = client.post("/api/repositories/archive", data={"name": "bad"}, files={"file": ("bad.zip", f)})
    assert r.status_code == 201
    assert r.json()["index_status"] == "failed" and "unsafe path" in r.json()["index_error"]


def test_other_users_cannot_see_or_touch_repository(client, other_client, sample_zip):
    rid = _import_sample(client, sample_zip)["id"]
    for method, url in [
        ("get", f"/api/repositories/{rid}"),
        ("get", f"/api/repositories/{rid}/search?q=x"),
        ("get", f"/api/repositories/{rid}/file?path=README.md"),
        ("delete", f"/api/repositories/{rid}"),
        ("patch", f"/api/repositories/{rid}"),
    ]:
        kwargs = {"json": {"ai_review_allowed": True}} if method == "patch" else {}
        assert getattr(other_client, method)(url, **kwargs).status_code == 404, url
    assert other_client.get("/api/repositories").json() == []
    r = other_client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"})
    assert r.status_code == 404


def test_full_review_static_only(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    r = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    _run_worker(settings)
    review = client.get(f"/api/reviews/{r.json()['id']}").json()
    assert review["status"] == "completed", review["error"]
    findings = client.get(f"/api/reviews/{review['id']}/findings").json()
    rules = {f["rule_id"] for f in findings}
    assert {"E722", "B602"} <= rules  # bare except (ruff) and shell=True (bandit)
    assert all(f["source"] == "static" for f in findings)
    b602 = next(f for f in findings if f["rule_id"] == "B602")
    assert b602["path"] == "inventory/store.py" and "shell=True" in b602["evidence"]
    assert review["stats"]["ai"]["status"] == "not_requested"
    assert review["stats"]["analyzers"]["ruff"]["status"] == "ok"
    # filters
    sec = client.get(f"/api/reviews/{review['id']}/findings", params={"category": "security"}).json()
    assert sec and all(f["category"] == "security" for f in sec)
    # deterministic test suggestions for functions not referenced by tests
    tests = client.get(f"/api/reviews/{review['id']}/test-suggestions").json()
    assert "inventory/pricing.py::apply_discount" in {t["target"] for t in tests}
    # history
    assert [h["id"] for h in client.get(f"/api/repositories/{rid}/reviews").json()] == [review["id"]]


def test_ai_review_requires_consent(client, sample_zip):
    rid = _import_sample(client, sample_zip)["id"]
    r = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full", "use_ai": True})
    assert r.status_code == 400 and "Enable AI review" in r.json()["detail"]


AI_PAYLOAD = {
    "summary": "Pricing has a boundary bug.",
    "findings": [
        {
            "title": "Bulk discount excludes exactly 100 units",
            "description": "Docstring says 100 or more.",
            "severity": "medium",
            "category": "logic",
            "path": "inventory/pricing.py",
            "start_line": 6,
            "end_line": 6,
            "evidence": "if quantity > BULK_THRESHOLD:",
            "reasoning": "> vs >=",
            "suggested_fix": "Use >=.",
            "suggested_test": "assert apply_discount(1, 100) == 90",
            "confidence": "high",
        },
        {
            "title": "Invented issue",
            "description": "x",
            "severity": "high",
            "category": "bug",
            "path": "inventory/pricing.py",
            "start_line": 6,
            "end_line": 6,
            "evidence": "this code does not exist",
            "reasoning": "x",
            "suggested_fix": "x",
            "suggested_test": "x",
            "confidence": "low",
        },
        {
            "title": "Shell injection",
            "description": "dup of bandit",
            "severity": "high",
            "category": "security",
            "path": "inventory/store.py",
            "start_line": 26,
            "end_line": 26,
            "evidence": 'return subprocess.call("generate-report " + name, shell=True)',
            "reasoning": "x",
            "suggested_fix": "x",
            "suggested_test": "x",
            "confidence": "high",
        },
    ],
    "test_suggestions": [
        {
            "target": "apply_discount",
            "path": "inventory/pricing.py",
            "start_line": 4,
            "rationale": "boundary",
            "test_code": "def test_x():\n    assert True\n",
        }
    ],
}


def test_full_review_with_ai_validates_and_dedupes(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    assert client.patch(f"/api/repositories/{rid}", json={"ai_review_allowed": True}).json()["ai_review_allowed"]
    review_id = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full", "use_ai": True}).json()["id"]
    provider = StaticReplayProvider(AI_PAYLOAD, model="replay-model")
    _run_worker(settings, provider_factory=lambda s: provider)
    review = client.get(f"/api/reviews/{review_id}").json()
    assert review["status"] == "completed"
    ai = review["stats"]["ai"]
    assert ai["status"] == "completed" and ai["returned"] == 3 and ai["accepted"] == 2
    assert ai["rejected"] == [{"title": "Invented issue", "reason": "evidence_mismatch"}]
    findings = client.get(f"/api/reviews/{review_id}/findings", params={"source": "ai"}).json()
    assert [f["title"] for f in findings] == ["Bulk discount excludes exactly 100 units"]  # shell dup dropped
    assert findings[0]["analyzer"] == "llm:replay-model" and findings[0]["confidence"] == "high"
    # The prompt kept repository content inside the untrusted block.
    system, user = provider.calls[0]
    assert "untrusted" in system and "<repository_content>" in user and "B602" in user
    # feedback is recorded with analyzer/version and can be changed
    fid = findings[0]["id"]
    assert client.put(f"/api/findings/{fid}/feedback", json={"verdict": "useful"}).status_code == 204
    assert client.put(f"/api/findings/{fid}/feedback", json={"verdict": "incorrect"}).status_code == 204
    again = client.get(f"/api/reviews/{review_id}/findings", params={"source": "ai"}).json()
    assert again[0]["my_feedback"] == "incorrect"
    assert client.get("/api/feedback/summary").json() == {"llm:replay-model": {"incorrect": 1}}
    assert client.put(f"/api/findings/{fid}/feedback", json={"verdict": "meh"}).status_code == 422
    ts = client.get(f"/api/reviews/{review_id}/test-suggestions").json()
    assert {"ai", "static"} == {t["source"] for t in ts}


def test_ai_failure_keeps_static_results(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    client.patch(f"/api/repositories/{rid}", json={"ai_review_allowed": True})
    review_id = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full", "use_ai": True}).json()["id"]
    _run_worker(settings, provider_factory=lambda s: StaticReplayProvider('{"not": "valid"}'))
    review = client.get(f"/api/reviews/{review_id}").json()
    assert review["status"] == "completed"
    assert review["stats"]["ai"]["status"] == "failed"
    assert "schema validation" in review["stats"]["ai"]["reason"]
    assert client.get(f"/api/reviews/{review_id}/findings").json()  # static still present


def test_ai_unconfigured_is_skipped_not_failed(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    client.patch(f"/api/repositories/{rid}", json={"ai_review_allowed": True})
    review_id = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full", "use_ai": True}).json()["id"]
    _run_worker(settings)  # real get_provider: no API key in tests
    ai = client.get(f"/api/reviews/{review_id}").json()["stats"]["ai"]
    assert ai["status"] == "skipped" and "ANTHROPIC_API_KEY" in ai["reason"]


def test_local_diff_review_reports_only_changed_lines(client, local_git_repo, settings):
    r = client.post("/api/repositories/local", json={"name": "local", "path": str(local_git_repo)})
    assert r.status_code == 201 and r.json()["index_status"] == "ready", r.text
    rid = r.json()["id"]
    job = client.post(
        f"/api/repositories/{rid}/reviews", json={"kind": "diff", "base_ref": "HEAD~1", "head_ref": "HEAD"}
    ).json()
    _run_worker(settings)
    review = client.get(f"/api/reviews/{job['id']}").json()
    assert review["status"] == "completed", review["error"]
    files = client.get(f"/api/reviews/{job['id']}/changed-files").json()
    assert [f["path"] for f in files] == ["pkg/util.py"] and "+def run(cmd):" in files[0]["patch"]
    findings = client.get(f"/api/reviews/{job['id']}/findings").json()
    assert {"E722", "B602"} <= {f["rule_id"] for f in findings}
    src = client.get(f"/api/reviews/{job['id']}/file", params={"path": "pkg/util.py"}).json()
    assert "def run" in src["content"]


def test_local_import_outside_allowed_root_rejected(client, tmp_path):
    r = client.post("/api/repositories/local", json={"name": "x", "path": str(tmp_path)})
    assert r.status_code == 400 and "outside" in r.json()["detail"]


def test_bad_ref_fails_job_with_clear_error(client, local_git_repo, settings):
    rid = client.post("/api/repositories/local", json={"name": "l2", "path": str(local_git_repo)}).json()["id"]
    job = client.post(
        f"/api/repositories/{rid}/reviews", json={"kind": "diff", "base_ref": "--upload-pack=evil", "head_ref": "HEAD"}
    ).json()
    _run_worker(settings)
    review = client.get(f"/api/reviews/{job['id']}").json()
    assert review["status"] == "failed" and "Invalid Git ref" in review["error"]


def test_review_rate_limit(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    codes = [
        client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"}).status_code
        for _ in range(settings.reviews_per_hour + 1)
    ]
    assert codes[-1] == 429 and codes[0] == 202


def test_delete_repository_cascades(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"})
    _run_worker(settings)
    assert client.delete(f"/api/repositories/{rid}").status_code == 204
    assert client.get(f"/api/repositories/{rid}").status_code == 404
    with SessionLocal() as db:
        assert db.query(ReviewJob).filter_by(repository_id=rid).count() == 0
    assert not (settings.data_dir / "snapshots" / str(rid)).exists()


def test_worker_recovers_stale_and_records_internal_errors(client, sample_zip, settings):
    rid = _import_sample(client, sample_zip)["id"]
    jid = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"}).json()["id"]

    class Boom:
        name, languages = "boom", ("python",)

        def version(self):
            return "0"

        def run(self, root, files):
            raise RuntimeError("secret internal detail")

    _run_worker(settings, analyzers=[Boom()])
    review = client.get(f"/api/reviews/{jid}").json()
    assert review["status"] == "failed" and "secret internal detail" not in review["error"]
    assert "static_analysis" in review["error"]

    jid2 = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "full"}).json()["id"]
    with SessionLocal() as db:
        job = claim_next(db)
        assert job.id == jid2 and job.status == "running"
        from datetime import timedelta

        job.started_at = job.started_at - timedelta(seconds=settings.job_timeout_s + 5)
        db.commit()
        assert recover_stale_jobs(db, settings) == 1
    assert client.get(f"/api/reviews/{jid2}").json()["status"] == "failed"


# --- GitHub (mocked HTTP transport; no network) -------------------------------------------


def _gh_transport(zip_bytes: bytes):
    pr = {
        "number": 7,
        "title": "Add pricing",
        "state": "open",
        "user": {"login": "dev"},
        "html_url": "https://github.com/acme/shop/pull/7",
        "base": {"sha": "b" * 40, "ref": "main"},
        "head": {"sha": "c" * 40, "ref": "feat"},
        "updated_at": "2026-10-01T00:00:00Z",
    }
    patch = '@@ -1,3 +1,8 @@\n BULK_THRESHOLD = 100\n \n \n+def apply_discount(price, quantity):\n+    """Orders of 100 units or more get 10% off."""\n+    if quantity > BULK_THRESHOLD:\n+        return round(price * quantity * 0.9, 2)\n+    return round(price * quantity, 2)\n'

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer gho_testtoken"
        p = request.url.path
        if p == "/repos/acme/shop":
            return httpx.Response(200, json={"full_name": "acme/shop", "default_branch": "main"})
        if p.startswith("/repos/acme/shop/zipball/"):
            return httpx.Response(200, content=zip_bytes)
        if p == "/repos/acme/shop/pulls":
            return httpx.Response(200, json=[pr])
        if p == "/repos/acme/shop/pulls/7":
            return httpx.Response(200, json=pr)
        if p == "/repos/acme/shop/pulls/7/files":
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "inventory/pricing.py",
                        "status": "modified",
                        "additions": 5,
                        "deletions": 0,
                        "patch": patch,
                    }
                ],
            )
        if p == "/repos/acme/private":
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(500)

    return httpx.MockTransport(handler)


@pytest.fixture
def github_mock(client, monkeypatch, tmp_path):
    zip_bytes = zip_dir(SAMPLE, tmp_path / "gh.zip", prefix="acme-shop-ccc/").read_bytes()
    transport = _gh_transport(zip_bytes)
    import app.integrations.github as gh

    real_init = gh.GitHubClient.__init__
    monkeypatch.setattr(
        gh.GitHubClient,
        "__init__",
        lambda self, token, settings, transport_=None: real_init(self, token, settings, transport),
    )
    with SessionLocal() as db:
        user = db.query(User).filter_by(email=client.email).one()
        db.add(GitHubAccount(user_id=user.id, github_login="dev", encrypted_token=encrypt_secret("gho_testtoken")))
        db.commit()
    return gh


def test_github_import_pulls_and_pr_review(client, github_mock, settings):
    assert client.get("/api/github/status").json()["connected"] is True
    r = client.post("/api/repositories/github", json={"full_name": "acme/shop"})
    assert r.status_code == 201 and r.json()["index_status"] == "ready", r.text
    rid = r.json()["id"]
    pulls = client.get(f"/api/repositories/{rid}/pulls").json()
    assert pulls[0]["number"] == 7
    detail = client.get(f"/api/repositories/{rid}/pulls/7").json()
    assert detail["files"][0]["path"] == "inventory/pricing.py"
    job = client.post(f"/api/repositories/{rid}/reviews", json={"kind": "pull_request", "pr_number": 7}).json()
    _run_worker(settings, github_factory=github_mock.GitHubClient)
    review = client.get(f"/api/reviews/{job['id']}").json()
    assert review["status"] == "completed", review["error"]
    assert review["pr_number"] == 7 and review["stats"]["head_sha"] == "c" * 40
    # Only pricing.py changed, so store.py's static findings are excluded.
    assert all(f["path"] == "inventory/pricing.py" for f in client.get(f"/api/reviews/{job['id']}/findings").json())
    tests = client.get(f"/api/reviews/{job['id']}/test-suggestions").json()
    assert [t["target"] for t in tests] == ["inventory/pricing.py::apply_discount"]


def test_github_errors_and_input_validation(client, github_mock):
    assert client.post("/api/repositories/github", json={"full_name": "acme/private"}).status_code == 404
    for bad in ["https://evil.example/x", "acme/../etc", "a/b/c", "127.0.0.1/x y"]:
        assert client.post("/api/repositories/github", json={"full_name": bad}).status_code == 400, bad


def test_github_requires_connection(client):
    assert client.post("/api/repositories/github", json={"full_name": "acme/shop"}).status_code == 400


def test_oauth_state_is_validated(client):
    r = client.get("/api/github/oauth/start", follow_redirects=False)
    assert r.status_code == 307 and "state=" in r.headers["location"]
    assert "client_id=test-client" in r.headers["location"]
    r = client.get("/api/github/oauth/callback", params={"code": "x", "state": "forged"}, follow_redirects=False)
    assert r.status_code == 400 and "state" in r.json()["detail"]


def test_chunked_upload_without_length_rejected(client):
    r = client.post(
        "/api/repositories/archive", content=iter([b"x"]), headers={"content-type": "multipart/form-data; boundary=x"}
    )
    assert r.status_code == 411


def test_unexpected_indexing_error_marks_repo_failed(client, sample_zip, monkeypatch):
    import app.api.repositories as repos

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(repos, "index_snapshot", boom)
    from fastapi.testclient import TestClient

    from app.main import app

    raw = TestClient(app, raise_server_exceptions=False)
    raw.cookies = client.cookies
    raw.headers["x-devpilot-csrf"] = "1"
    with open(sample_zip, "rb") as f:
        r = raw.post("/api/repositories/archive", data={"name": "boom"}, files={"file": ("s.zip", f)})
    assert r.status_code == 500 and "disk full" not in r.text
    repo = next(x for x in client.get("/api/repositories").json() if x["name"] == "boom")
    assert repo["index_status"] == "failed"
