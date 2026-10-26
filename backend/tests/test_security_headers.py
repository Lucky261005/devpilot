"""Security headers on API responses, nginx's web-app policy, and docs access by environment."""

import re
from pathlib import Path

import pytest

from app.main import API_CSP
from tests.conftest import make_client

NGINX = (Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf").read_text(encoding="utf-8")
DOCS = ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]


def _assert_api_headers(r) -> None:
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == API_CSP


@pytest.mark.parametrize("path", ["/api/health", "/api/settings", "/api/auth/me", "/api/does-not-exist"])
def test_api_responses_carry_security_headers(path):
    r = make_client().get(path)
    _assert_api_headers(r)
    assert "strict-transport-security" not in r.headers  # development is plain HTTP


def test_early_rejections_carry_them_too():
    c = make_client()
    del c.headers["x-devpilot-csrf"]
    r = c.post("/api/auth/logout")
    assert r.status_code == 403
    _assert_api_headers(r)


def test_development_serves_interactive_docs():
    c = make_client()
    for path in ["/docs", "/redoc", "/openapi.json"]:
        r = c.get(path)
        assert r.status_code == 200, path
        assert "content-security-policy" not in r.headers  # Swagger UI loads its own assets


@pytest.fixture
def production(settings, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    return settings


@pytest.mark.parametrize("path", DOCS)
def test_production_hides_docs_and_schema(production, path):
    r = make_client().get(path)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert r.headers["x-content-type-options"] == "nosniff"


def test_production_api_keeps_working(production):
    r = make_client().get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    _assert_api_headers(r)


def test_hsts_only_outside_development_and_only_when_configured(settings, monkeypatch):
    monkeypatch.setattr(settings, "hsts_seconds", 31536000)
    assert "strict-transport-security" not in make_client().get("/api/health").headers  # development
    monkeypatch.setattr(settings, "env", "production")
    assert make_client().get("/api/health").headers["strict-transport-security"] == "max-age=31536000"
    monkeypatch.setattr(settings, "hsts_seconds", 0)
    assert "strict-transport-security" not in make_client().get("/api/health").headers


def test_nginx_web_app_policy():
    csp = re.search(r'add_header Content-Security-Policy "([^"]+)" always;', NGINX).group(1)  # type: ignore[union-attr]
    directives = dict(d.strip().split(" ", 1) for d in csp.split(";"))
    assert directives["script-src"] == "'self'"  # no inline or eval
    assert directives["style-src"] == "'self'" and directives["style-src-attr"] == "'unsafe-inline'"
    assert directives["frame-ancestors"] == "'none'" and directives["object-src"] == "'none'"
    assert "unsafe-eval" not in csp
    assert 'add_header X-Content-Type-Options "nosniff" always;' in NGINX
    assert "Referrer-Policy" in NGINX and 'X-Frame-Options "DENY"' in NGINX
    # Headers sit in the web-app location only, so API responses keep the backend's own policy.
    api_block = NGINX.split("location /api/")[1].split("}")[0]
    assert "add_header" not in api_block
    assert "Strict-Transport-Security" not in NGINX  # no TLS in this container
