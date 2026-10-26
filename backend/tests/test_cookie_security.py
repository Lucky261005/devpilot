"""Secure session cookies are mandatory outside development."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, check_environment, get_settings
from tests.conftest import make_client, signed_up

KEY = "x" * 44  # any non-empty value satisfies the secret-key check; not a real key


def test_development_allows_insecure_cookies():
    s = check_environment(Settings(env="development", cookie_secure=False))
    assert s.cookie_secure is False


@pytest.mark.parametrize("env", ["production", "staging"])
def test_other_environments_refuse_insecure_cookies(env):
    with pytest.raises(RuntimeError, match="DEVPILOT_COOKIE_SECURE must be true"):
        check_environment(Settings(env=env, secret_key=KEY, cookie_secure=False))


def test_other_environments_accept_secure_cookies():
    assert check_environment(Settings(env="production", secret_key=KEY, cookie_secure=True)).cookie_secure


def test_api_startup_fails_with_insecure_production_settings(monkeypatch):
    from app.main import app

    monkeypatch.setenv("DEVPILOT_ENV", "production")
    monkeypatch.setenv("DEVPILOT_SECRET_KEY", KEY)
    monkeypatch.setenv("DEVPILOT_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="DEVPILOT_COOKIE_SECURE"), TestClient(app):
            pass  # entering the client runs the lifespan (startup)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_session_cookie_attributes(settings, monkeypatch):
    signed_up("cookie-attrs@example.com", "long-enough-pw")
    c = make_client()
    r = c.post("/api/auth/login", json={"email": "cookie-attrs@example.com", "password": "long-enough-pw"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert "secure" not in cookie.replace("httponly", "")  # development default

    monkeypatch.setattr(settings, "cookie_secure", True)
    r = c.post("/api/auth/login", json={"email": "cookie-attrs@example.com", "password": "long-enough-pw"})
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie


# --- the documented docker compose setup (static: the containers are not started here) ---------

ROOT = Path(__file__).resolve().parents[2]


def _env_example() -> dict[str, str]:
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines if line.startswith("DEVPILOT_"))


def _compose_backend_environment() -> dict[str, str]:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = compose.split("environment: &backend_env")[1].split("volumes:")[0]
    pairs = re.findall(r"^\s+(DEVPILOT_[A-Z_]+):\s*(\"[^\"]*\"|\S+)", block, re.M)
    return {k: v.strip('"') for k, v in pairs}


def _settings_from(env: dict[str, str]) -> Settings:
    fields = {k.removeprefix("DEVPILOT_").lower(): v for k, v in env.items()}
    return Settings(**{k: v for k, v in fields.items() if k in Settings.model_fields and v != ""})


def test_documented_compose_setup_passes_the_startup_check():
    # Step 1 copies .env.example to the root .env; step 2 sets the secret key; Compose's
    # `environment:` block then overrides .env for the backend and worker containers.
    env = {**_env_example(), "DEVPILOT_SECRET_KEY": KEY, **_compose_backend_environment()}
    s = _settings_from(env)
    assert s.env == "production" and s.cookie_secure is True
    assert check_environment(s) is s


def test_compose_forces_secure_cookies_wherever_it_forces_production():
    compose_env = _compose_backend_environment()
    assert compose_env["DEVPILOT_ENV"] == "production" and compose_env["DEVPILOT_COOKIE_SECURE"] == "true"
    without = {**_env_example(), "DEVPILOT_SECRET_KEY": KEY, **compose_env, "DEVPILOT_COOKIE_SECURE": "false"}
    with pytest.raises(RuntimeError, match="DEVPILOT_COOKIE_SECURE must be true"):
        check_environment(_settings_from(without))


def test_env_example_alone_is_a_working_development_config():
    s = _settings_from({**_env_example()})  # backend/.env copied from the example, no Docker
    assert s.env == "development" and s.cookie_secure is False
    assert check_environment(s) is s
