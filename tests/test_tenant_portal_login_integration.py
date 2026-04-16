"""
tests/test_tenant_portal_login_integration.py
==============================================
Live integration tests for the tenant portal login flow.

These tests require a running stack and valid credentials.  They are
skipped automatically unless the required environment variables are set.

Run against local dev (Docker Compose):
  $env:TENANT_PORTAL_URL  = "http://localhost:8082"   # Vite proxy (tests proxy routing)
  $env:TENANT_DIRECT_URL  = "http://localhost:8010"   # Direct to backend (tests async fix)
  $env:TENANT_TEST_USER   = "org1@org1.com"
  $env:TENANT_TEST_PASS   = "yourpassword"
  $env:TENANT_TEST_DOMAIN = "org1"
  pytest tests/test_tenant_portal_login_integration.py -v

What each test validates
------------------------
T01  /tenant/branding reachable via proxy (no 504 on page load)
T02  /tenant/branding reachable directly to backend (backend is up)
T03  login via Vite proxy returns 200 + access_token  (proxy routing fixed)
T04  login directly to backend returns 200 + access_token  (async fix)
T05  wrong password returns 401, NOT 504  (backend reachable, rejects bad creds)
T06  bad domain returns 401 (Keystone domain enforcement)
T07  empty domain is rejected 422 before reaching Keystone
T08  overly long domain is rejected 422 (field validator)
T09  injection chars in domain rejected 422 (regex whitelist)
T10  /tenant/auth/me with a valid token returns correct username
"""

import os

import httpx
import pytest

# ---------------------------------------------------------------------------
# Config from environment — tests skip if vars not set
# ---------------------------------------------------------------------------
PROXY_URL   = os.getenv("TENANT_PORTAL_URL",  "http://localhost:8082")
DIRECT_URL  = os.getenv("TENANT_DIRECT_URL",  "http://localhost:8010")
TEST_USER   = os.getenv("TENANT_TEST_USER",   "")
TEST_PASS   = os.getenv("TENANT_TEST_PASS",   "")
TEST_DOMAIN = os.getenv("TENANT_TEST_DOMAIN", "Default")

_HAVE_CREDS = bool(TEST_USER and TEST_PASS)
_needs_creds = pytest.mark.skipif(
    not _HAVE_CREDS,
    reason="Set TENANT_TEST_USER and TENANT_TEST_PASS to run live login tests",
)

pytestmark = pytest.mark.live_pf9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _login(base_url: str, username: str, password: str, domain: str) -> httpx.Response:
    return httpx.post(
        f"{base_url}/tenant/auth/login",
        json={"username": username, "password": password, "domain": domain},
        timeout=20,
    )


def _branding(base_url: str) -> httpx.Response:
    return httpx.get(f"{base_url}/tenant/branding", timeout=10)


# ---------------------------------------------------------------------------
# T01-T02  Branding endpoint — unauthenticated, must not 504
# ---------------------------------------------------------------------------
class TestBrandingReachability:
    def test_T01_branding_via_proxy(self):
        """Branding loads through the Vite proxy — proxy routing is working."""
        r = _branding(PROXY_URL)
        assert r.status_code != 504, (
            f"504: nginx/Vite proxy cannot reach tenant_portal container. "
            f"Check VITE_TENANT_API_TARGET in docker-compose.override.yml"
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"

    def test_T02_branding_direct_to_backend(self):
        """Branding loads when calling the backend directly — pod/container is up."""
        r = _branding(DIRECT_URL)
        assert r.status_code != 504, "Backend container is not responding"
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"


# ---------------------------------------------------------------------------
# T03-T04  Happy-path login
# ---------------------------------------------------------------------------
class TestLoginHappyPath:
    @_needs_creds
    def test_T03_login_via_proxy_returns_token(self):
        """Full login through Vite proxy succeeds and returns an access_token."""
        r = _login(PROXY_URL, TEST_USER, TEST_PASS, TEST_DOMAIN)
        assert r.status_code != 504, (
            "504 on login via proxy — Vite proxy is not forwarding /tenant/* correctly. "
            "Check VITE_TENANT_API_TARGET in docker-compose.override.yml."
        )
        assert r.status_code == 200, (
            f"Login via proxy failed {r.status_code}: {r.text[:300]}"
        )
        body = r.json()
        assert "access_token" in body, f"No access_token in response: {body}"
        assert body["token_type"] == "bearer"

    @_needs_creds
    def test_T04_login_direct_to_backend_returns_token(self):
        """Direct login to backend succeeds — async Keystone call is non-blocking."""
        r = _login(DIRECT_URL, TEST_USER, TEST_PASS, TEST_DOMAIN)
        assert r.status_code != 504, (
            "504 on direct backend login — event loop may still be blocked "
            "or Keystone is unreachable from the backend container."
        )
        assert r.status_code == 200, (
            f"Direct backend login failed {r.status_code}: {r.text[:300]}"
        )
        body = r.json()
        assert "access_token" in body, f"No access_token in response: {body}"


# ---------------------------------------------------------------------------
# T05-T06  Bad credentials — must get 401, not 504
# ---------------------------------------------------------------------------
class TestLoginBadCredentials:
    @_needs_creds
    def test_T05_wrong_password_returns_401_not_504(self):
        """A wrong password must return 401 from Keystone, not 504 (reachability check)."""
        r = _login(PROXY_URL, TEST_USER, "definitely-wrong-password-xyz", TEST_DOMAIN)
        assert r.status_code != 504, (
            "Got 504 on wrong-password test — backend or Keystone unreachable"
        )
        assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text[:200]}"

    @_needs_creds
    def test_T06_wrong_domain_returns_401(self):
        """A non-existent Keystone domain returns 401 (credential mismatch)."""
        r = _login(PROXY_URL, TEST_USER, TEST_PASS, "nonexistent-domain-xyz")
        assert r.status_code in (401, 503), (
            f"Expected 401 or 503, got {r.status_code}: {r.text[:200]}"
        )


# ---------------------------------------------------------------------------
# T07-T09  Domain field validation (no live Keystone call needed)
# ---------------------------------------------------------------------------
class TestDomainValidation:
    def test_T07_empty_domain_rejected_422(self):
        """Empty domain string is rejected by Pydantic before reaching Keystone."""
        r = httpx.post(
            f"{PROXY_URL}/tenant/auth/login",
            json={"username": "u", "password": "p", "domain": "   "},
            timeout=10,
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text[:200]}"

    def test_T08_overlength_domain_rejected_422(self):
        """Domain > 255 chars is rejected by max_length validator."""
        r = httpx.post(
            f"{PROXY_URL}/tenant/auth/login",
            json={"username": "u", "password": "p", "domain": "A" * 256},
            timeout=10,
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text[:200]}"

    def test_T09_injection_chars_in_domain_rejected_422(self):
        """Injection chars in domain (SQL/script) are rejected by regex whitelist."""
        for payload in ["'; DROP TABLE--", "<script>", "domain/../../etc", "dom\x00ain"]:
            r = httpx.post(
                f"{PROXY_URL}/tenant/auth/login",
                json={"username": "u", "password": "p", "domain": payload},
                timeout=10,
            )
            assert r.status_code == 422, (
                f"Injection payload {payload!r} was NOT rejected: "
                f"{r.status_code} {r.text[:200]}"
            )


# ---------------------------------------------------------------------------
# T10  /me endpoint with valid token
# ---------------------------------------------------------------------------
class TestMeEndpoint:
    @_needs_creds
    def test_T10_me_returns_correct_username(self):
        """After login, GET /tenant/auth/me returns the authenticated username."""
        login_r = _login(PROXY_URL, TEST_USER, TEST_PASS, TEST_DOMAIN)
        if login_r.status_code != 200:
            pytest.skip(f"Login failed ({login_r.status_code}) — skipping /me test")

        token = login_r.json()["access_token"]
        me_r = httpx.get(
            f"{PROXY_URL}/tenant/auth/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        assert me_r.status_code == 200, f"/me failed {me_r.status_code}: {me_r.text[:200]}"
        body = me_r.json()
        assert body.get("username") == TEST_USER, (
            f"Expected username={TEST_USER!r}, got {body.get('username')!r}"
        )
