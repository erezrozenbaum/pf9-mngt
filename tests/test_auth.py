"""
tests/test_auth.py — Authentication module tests.

Run against a live stack with valid credentials:
  TEST_API_URL=http://localhost:8000 \
  TEST_ADMIN_EMAIL=admin \
  TEST_ADMIN_PASSWORD=<password> \
  pytest tests/test_auth.py -v

All tests are read-only (no mutations to users or roles).

Unit tests for token/JWT logic require no live stack and run in isolation.
"""

import os
import time
import hmac
import hashlib
from datetime import timedelta

import pytest
import requests

API_URL = os.getenv("TEST_API_URL", "http://localhost:8000")
ADMIN_USER = os.getenv("TEST_ADMIN_EMAIL", "")
ADMIN_PASS = os.getenv("TEST_ADMIN_PASSWORD", "")
VERIFY_SSL = os.getenv("TEST_VERIFY_SSL", "false").lower() != "false"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login(api, username, password):
    return requests.post(
        f"{api}/auth/login",
        json={"username": username, "password": password},
        verify=VERIFY_SSL,
        timeout=10,
    )


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests — JWT helpers (no live stack needed)
# ---------------------------------------------------------------------------

# JWT config mirrored from auth.py defaults — tests use a stable test key
import secrets as _secrets
from jose import jwt as _jose_jwt
from jose import JWTError

_TEST_SECRET = "test-secret-key-for-unit-tests-only"
_ALGORITHM = "HS256"


def _make_token(payload: dict, expires_delta=None) -> str:
    from datetime import datetime, timezone
    import copy
    data = copy.copy(payload)
    if expires_delta is None:
        expires_delta = timedelta(minutes=60)
    now = datetime.now(timezone.utc)
    data["exp"] = now + expires_delta
    data["iat"] = now
    return _jose_jwt.encode(data, _TEST_SECRET, algorithm=_ALGORITHM)


def _decode_token(token: str):
    try:
        return _jose_jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM])
    except JWTError:
        return None


class TestJWTHelpers:
    """Pure unit tests — JWT logic verified without importing the full auth module."""

    def test_valid_token_decodes_correctly(self):
        token = _make_token({"sub": "testuser", "role": "viewer"})
        payload = _decode_token(token)
        assert payload is not None
        assert payload["sub"] == "testuser"
        assert payload["role"] == "viewer"

    def test_expired_token_returns_none(self):
        token = _make_token({"sub": "testuser", "role": "viewer"}, expires_delta=timedelta(seconds=-1))
        assert _decode_token(token) is None

    def test_tampered_signature_returns_none(self):
        token = _make_token({"sub": "testuser", "role": "viewer"})
        tampered = token[:-4] + "XXXX"
        assert _decode_token(tampered) is None

    def test_wrong_secret_returns_none(self):
        token = _make_token({"sub": "testuser", "role": "viewer"})
        try:
            result = _jose_jwt.decode(token, "wrong-secret", algorithms=[_ALGORITHM])
        except JWTError:
            result = None
        assert result is None

    def test_default_admin_timing_safe(self):
        """auth.py must use hmac.compare_digest for the default admin password check."""
        import os
        auth_path = os.path.join(os.path.dirname(__file__), "..", "api", "auth.py")
        with open(auth_path) as f:
            source = f.read()
        assert "hmac.compare_digest" in source, (
            "Default admin password comparison must use hmac.compare_digest (constant-time), "
            "not plain == operator"
        )
        # Also verify the plain == pattern is NOT used for this specific comparison
        # (check that no 'password == DEFAULT_ADMIN_PASSWORD' pattern exists)
        assert "password == DEFAULT_ADMIN_PASSWORD" not in source
        assert "DEFAULT_ADMIN_PASSWORD == password" not in source


# ---------------------------------------------------------------------------
# Integration tests — require live stack + credentials
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not ADMIN_USER or not ADMIN_PASS,
    reason="Set TEST_ADMIN_EMAIL and TEST_ADMIN_PASSWORD to run live auth tests",
)
class TestLoginEndpoint:
    @pytest.fixture(scope="class")
    def api(self):
        return API_URL.rstrip("/")

    def test_login_success(self, api):
        r = login(api, ADMIN_USER, ADMIN_PASS)
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body.get("token_type") == "bearer"
        assert body.get("expires_in", 0) > 0

    def test_login_returns_user_info(self, api):
        r = login(api, ADMIN_USER, ADMIN_PASS)
        body = r.json()
        user = body.get("user", {})
        assert user.get("username") == ADMIN_USER
        assert user.get("role") in (
            "viewer", "operator", "admin", "superadmin", "technical"
        )

    def test_login_wrong_password_returns_401(self, api):
        r = login(api, ADMIN_USER, "definitely_wrong_" + ADMIN_PASS)
        assert r.status_code == 401

    def test_login_unknown_user_returns_401(self, api):
        r = login(api, "no_such_user_xyzzy", "wrongpass")
        assert r.status_code == 401

    def test_login_empty_password_returns_401(self, api):
        r = login(api, ADMIN_USER, "")
        assert r.status_code == 401

    def test_token_grants_access_to_protected_route(self, api):
        r = login(api, ADMIN_USER, ADMIN_PASS)
        token = r.json()["access_token"]
        r2 = requests.get(
            f"{api}/api/tenants",
            headers=auth_headers(token),
            verify=VERIFY_SSL,
            timeout=10,
        )
        assert r2.status_code == 200

    def test_missing_token_rejected(self, api):
        r = requests.get(f"{api}/api/tenants", verify=VERIFY_SSL, timeout=5)
        assert r.status_code in (401, 403)

    def test_invalid_token_rejected(self, api):
        r = requests.get(
            f"{api}/api/tenants",
            headers=auth_headers("not.a.real.token"),
            verify=VERIFY_SSL,
            timeout=5,
        )
        assert r.status_code in (401, 403)


@pytest.mark.skipif(
    not ADMIN_USER or not ADMIN_PASS,
    reason="Set TEST_ADMIN_EMAIL and TEST_ADMIN_PASSWORD to run live auth tests",
)
class TestLogoutAndRevocation:
    """Verify that tokens are actually invalidated after logout."""

    @pytest.fixture(scope="class")
    def api(self):
        return API_URL.rstrip("/")

    def test_logout_invalidates_token(self, api):
        # 1. Login
        r = login(api, ADMIN_USER, ADMIN_PASS)
        assert r.status_code == 200
        token = r.json()["access_token"]

        # 2. Confirm token works before logout
        r2 = requests.get(
            f"{api}/api/tenants",
            headers=auth_headers(token),
            verify=VERIFY_SSL,
            timeout=5,
        )
        assert r2.status_code == 200, "Token should work before logout"

        # 3. Logout
        r3 = requests.post(
            f"{api}/auth/logout",
            headers=auth_headers(token),
            verify=VERIFY_SSL,
            timeout=5,
        )
        assert r3.status_code == 200

        # 4. Confirm token is now rejected
        r4 = requests.get(
            f"{api}/api/tenants",
            headers=auth_headers(token),
            verify=VERIFY_SSL,
            timeout=5,
        )
        assert r4.status_code in (401, 403), (
            "Token must be rejected after logout (session revocation)"
        )
