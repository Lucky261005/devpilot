"""Forwarded-header trust: only nginx may set the client IP used by the login/register throttle.

These are unit tests: the API runs in-process behind uvicorn's own ProxyHeadersMiddleware,
configured like docker-compose.yml. The real Compose network is not exercised here.
"""

import ipaddress
import re
from pathlib import Path

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
NGINX_IP = re.search(r"ipv4_address:\s*([\d.]+)", COMPOSE).group(1)  # type: ignore[union-attr]
PW = {"password": "wrong-password-1"}


def _client(peer: str) -> TestClient:
    from app.main import app

    c = TestClient(ProxyHeadersMiddleware(app, trusted_hosts=NGINX_IP), client=(peer, 40000))
    c.headers["x-devpilot-csrf"] = "1"
    return c


def _attempts(c: TestClient, n: int, spoof: bool) -> list[int]:
    return [
        # A different email each time, so only the per-IP limit is in play (not the per-account one).
        c.post(
            "/api/auth/login",
            json={"email": f"ip-test-{i}@example.com", **PW},
            headers={"x-forwarded-for": f"10.9.8.{i}"} if spoof else {},
        ).status_code
        for i in range(n)
    ]


def test_untrusted_peer_cannot_dodge_the_throttle_with_x_forwarded_for():
    codes = _attempts(_client("203.0.113.7"), 11, spoof=True)  # a new fake IP on every attempt
    assert codes[:10] == [401] * 10 and codes[10] == 429  # still counted as one client


def test_nginx_forwards_real_client_ips():
    nginx = _client(NGINX_IP)
    assert _attempts(nginx, 11, spoof=True) == [401] * 11  # 11 different real clients, none throttled
    same = [
        nginx.post(
            "/api/auth/login",
            json={"email": f"one-client-{i}@example.com", **PW},
            headers={"x-forwarded-for": "198.51.100.4"},
        )
        for i in range(11)
    ]
    assert same[-1].status_code == 429  # one real client is still throttled through the proxy


def test_deployment_trusts_only_nginx():
    trusted = re.findall(r"FORWARDED_ALLOW_IPS:\s*(\S+)", COMPOSE)
    assert trusted and set(trusted) == {NGINX_IP}
    subnet = ipaddress.ip_network(re.search(r"subnet:\s*(\S+)", COMPOSE).group(1))  # type: ignore[union-attr]
    assert ipaddress.ip_address(NGINX_IP) in subnet
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "--forwarded-allow-ips=*" not in dockerfile and '"*"' not in COMPOSE
    # The API container publishes no port: only nginx can reach it.
    backend_block = COMPOSE.split("  backend:")[1].split("\n  worker:")[0]
    assert "ports:" not in backend_block


# --- F3: plain HTTP only on the host's loopback; remote users go through HTTPS on the host -----

NGINX_CONF = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")


def test_web_ui_is_published_on_loopback_only():
    ports = re.findall(r"ports:\s*\[([^\]]*)\]", COMPOSE)
    assert ports == ['"127.0.0.1:8080:80"']  # never 0.0.0.0, which would expose plain HTTP


def test_nginx_believes_forwarded_ips_only_from_the_host_gateway():
    gateway = re.search(r"gateway:\s*([\d.]+)", COMPOSE).group(1)  # type: ignore[union-attr]
    subnet = ipaddress.ip_network(re.search(r"subnet:\s*(\S+)", COMPOSE).group(1))  # type: ignore[union-attr]
    assert ipaddress.ip_address(gateway) in subnet and gateway != NGINX_IP
    assert re.findall(r"set_real_ip_from\s+([^;]+);", NGINX_CONF) == [gateway]  # one address, no ranges
    assert "real_ip_header X-Forwarded-For;" in NGINX_CONF
    assert "real_ip_recursive off;" in NGINX_CONF  # only the hop the host proxy added counts


def test_public_origin_defaults_to_localhost_and_cookies_stay_secure():
    assert "DEVPILOT_FRONTEND_ORIGIN: ${DEVPILOT_PUBLIC_ORIGIN:-http://localhost:8080}" in COMPOSE
    assert 'DEVPILOT_COOKIE_SECURE: "true"' in COMPOSE and "DEVPILOT_ENV: production" in COMPOSE


def test_services_start_in_order_on_a_fresh_database():
    # The backend container runs `alembic upgrade head` before uvicorn; on a fresh database a
    # worker started earlier crashed on the missing review_jobs table.
    backend = COMPOSE.split("\n  backend:")[1].split("\n  worker:")[0]
    worker = COMPOSE.split("\n  worker:")[1].split("\n  frontend:")[0]
    assert "healthcheck:" in backend and "/api/health" in backend
    assert re.search(r"backend: \{ condition: service_healthy \}", worker)
    db = COMPOSE.split("\n  db:")[1].split("\n  backend:")[0]
    assert "pg_isready -h 127.0.0.1" in db  # TCP, not the socket the init server also answers on
    assert "alembic upgrade head && uvicorn" in (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
