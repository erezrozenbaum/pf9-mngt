"""
tests/test_health.py — Health endpoint smoke tests.

Run against a live stack:
  TEST_API_URL=http://localhost:8000 pytest tests/test_health.py -v

The API_URL defaults to http://localhost:8000 (dev stack direct).
For the prod stack (nginx on 443): TEST_API_URL=https://localhost pytest ...
"""

import os
import pytest
import requests
from pathlib import Path

# Load .env from repo root so METRICS_API_KEY etc. are available when running
# pytest directly on the host (not inside Docker).
try:
    from dotenv import load_dotenv
    _root = Path(__file__).parent.parent
    _env_file = _root / ".env"
    _env_ci = _root / ".env.ci"
    if _env_file.exists():
        load_dotenv(_env_file, override=True)
    elif _env_ci.exists():
        # CI: .env is gitignored; fall back to .env.ci which the stack was started with
        load_dotenv(_env_ci, override=True)
except ImportError:
    pass  # python-dotenv not installed — rely on shell env

API_URL = os.getenv("TEST_API_URL", "http://localhost:8000")
# Allow self-signed cert in prod TLS tests
VERIFY_SSL = os.getenv("TEST_VERIFY_SSL", "false").lower() != "false"


@pytest.fixture(scope="session")
def api():
    """Base URL for all requests in this session."""
    return API_URL.rstrip("/")


class TestHealthEndpoint:
    def test_health_returns_200(self, api):
        r = requests.get(f"{api}/health", verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 200

    def test_health_body_has_status_ok(self, api):
        r = requests.get(f"{api}/health", verify=VERIFY_SSL, timeout=5)
        body = r.json()
        assert body.get("status") == "ok"

    def test_health_body_has_timestamp(self, api):
        r = requests.get(f"{api}/health", verify=VERIFY_SSL, timeout=5)
        body = r.json()
        assert "timestamp" in body

    def test_health_is_unauthenticated(self, api):
        """Health endpoint must be reachable without a token (used by Docker healthcheck)."""
        r = requests.get(
            f"{api}/health",
            headers={},   # explicitly no Authorization header
            verify=VERIFY_SSL,
            timeout=5,
        )
        assert r.status_code == 200

    def test_health_content_type_json(self, api):
        r = requests.get(f"{api}/health", verify=VERIFY_SSL, timeout=5)
        assert "application/json" in r.headers.get("content-type", "")


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, api):
        """GET /metrics with valid X-Metrics-Key must return 200.
        If METRICS_API_KEY is not set, the endpoint is open and 200 is expected without a key.
        """
        key = os.getenv("METRICS_API_KEY", "")
        headers = {"X-Metrics-Key": key} if key else {}
        r = requests.get(f"{api}/metrics", headers=headers, verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 200

    def test_metrics_requires_key_when_configured(self, api, api_server_available):
        """When METRICS_API_KEY is set, /metrics without the header must return 401."""
        if not api_server_available:
            pytest.skip("API server not reachable — skipping live enforcement test")
        key = os.getenv("METRICS_API_KEY", "")
        if not key:
            pytest.skip("METRICS_API_KEY not configured — endpoint is open, skip enforcement test")
        r = requests.get(f"{api}/metrics", headers={}, verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 401


class TestProtectedEndpointRequiresAuth:
    def test_api_metrics_requires_auth(self, api, api_server_available):
        """Authenticated /api/metrics must reject unauthenticated requests."""
        if not api_server_available:
            pytest.skip("API server not reachable — skipping live auth test")
        r = requests.get(f"{api}/api/metrics", verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 401

    def test_arbitrary_api_route_requires_auth(self, api, api_server_available):
        """/api/tenants must require a Bearer token."""
        if not api_server_available:
            pytest.skip("API server not reachable — skipping live auth test")
        r = requests.get(f"{api}/api/tenants", verify=VERIFY_SSL, timeout=5)
        assert r.status_code in (401, 403)
