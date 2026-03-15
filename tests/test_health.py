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
        r = requests.get(f"{api}/metrics", verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 200

    def test_metrics_unauthenticated(self, api):
        """Public /metrics endpoint must not require auth (prometheus / monitoring scrape)."""
        r = requests.get(f"{api}/metrics", headers={}, verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 200


class TestProtectedEndpointRequiresAuth:
    def test_api_metrics_requires_auth(self, api):
        """Authenticated /api/metrics must reject unauthenticated requests."""
        r = requests.get(f"{api}/api/metrics", verify=VERIFY_SSL, timeout=5)
        assert r.status_code == 401

    def test_arbitrary_api_route_requires_auth(self, api):
        """/api/tenants must require a Bearer token."""
        r = requests.get(f"{api}/api/tenants", verify=VERIFY_SSL, timeout=5)
        assert r.status_code in (401, 403)
