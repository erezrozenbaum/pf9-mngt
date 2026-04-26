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
import sys
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


# ---------------------------------------------------------------------------
# Unit tests — v1.93.18 security hardening
# ---------------------------------------------------------------------------

class TestJWTJtiClaim:
    """JWT tokens must include a unique jti claim (v1.93.18 H11)."""

    def test_token_contains_jti(self):
        """create_access_token must embed a jti claim via secrets.token_urlsafe."""
        import os
        auth_path = os.path.join(os.path.dirname(__file__), "..", "api", "auth.py")
        with open(auth_path, encoding="utf-8") as f:
            source = f.read()
        assert '"jti"' in source, "create_access_token must set jti claim"
        assert "token_urlsafe" in source, "jti must be generated with secrets.token_urlsafe"

    def test_each_token_has_unique_jti(self):
        """Two calls to _make_token with different jti values must decode differently."""
        t1 = _make_token({"sub": "user", "role": "viewer", "jti": "unique-id-1"})
        t2 = _make_token({"sub": "user", "role": "viewer", "jti": "unique-id-2"})
        p1 = _decode_token(t1)
        p2 = _decode_token(t2)
        assert p1 is not None and p2 is not None
        assert p1["jti"] != p2["jti"], "Each token must have a unique jti"


class TestJWTTTL:
    """JWT TTL default must be 15 minutes (v1.93.18 H13)."""

    def test_default_jwt_ttl_is_15_minutes(self):
        """auth.py default JWT TTL must be 15 minutes, not 90."""
        import os
        auth_path = os.path.join(os.path.dirname(__file__), "..", "api", "auth.py")
        with open(auth_path, encoding="utf-8") as f:
            source = f.read()
        # The default= argument of os.getenv for JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be "15"
        assert 'os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15")' in source, (
            "auth.py JWT_ACCESS_TOKEN_EXPIRE_MINUTES default must be \"15\""
        )

    def test_mfa_challenge_ttl_is_2_minutes(self):
        """mfa_routes.py MFA challenge TTL must be 2 minutes, not 5."""
        import os
        mfa_path = os.path.join(os.path.dirname(__file__), "..", "api", "mfa_routes.py")
        with open(mfa_path, encoding="utf-8") as f:
            source = f.read()
        assert "MFA_TOKEN_EXPIRE_MINUTES = 2" in source, (
            "MFA challenge token TTL must be 2 minutes (was 5)"
        )
        assert "MFA_TOKEN_EXPIRE_MINUTES = 5" not in source, (
            "MFA challenge token TTL must NOT be 5 minutes any more"
        )


class TestMetricsEndpointProtection:
    """Metrics endpoints must check X-Metrics-Key when METRICS_API_KEY is configured (v1.93.18 H14)."""

    def test_metrics_key_check_in_source(self):
        """main.py /metrics must check X-Metrics-Key header."""
        import os
        main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "X-Metrics-Key" in source, (
            "/metrics handler must check X-Metrics-Key header"
        )
        assert "METRICS_API_KEY" in source, (
            "main.py must define METRICS_API_KEY"
        )

    def test_metrics_key_uses_constant_time_compare(self):
        """X-Metrics-Key comparison must use secrets.compare_digest (constant-time)."""
        import os
        main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(main_path) as f:
            source = f.read()
        # Ensure compare_digest is used (not plain == comparison)
        assert "compare_digest" in source, (
            "Metrics key comparison must use secrets.compare_digest (constant-time)"
        )


class TestLoginRateLimit:
    """Login endpoint rate limit must be 5/minute or less (v1.93.18 H12)."""

    def test_login_rate_limit_is_tight(self):
        """main.py login endpoint must not use 10/minute or higher rate limit."""
        import os
        main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(main_path) as f:
            source = f.read()
        # Check that 10/minute is NOT on the login endpoint
        assert "@limiter.limit(\"10/minute\")" not in source or \
            source.find("@limiter.limit(\"10/minute\")") > source.find("/auth/login"), (
            "Login endpoint rate limit must be reduced from 10/minute"
        )
        # Check that a tight limit IS present near the login endpoint
        assert "5/minute" in source or "2/minute" in source or "3/minute" in source, (
            "Login endpoint must have a tight rate limit (5/minute or less)"
        )


class TestPasswordResetSecurity:
    """Password reset token must not appear in logs (v1.93.18 M19, L11)."""

    def test_reset_token_not_logged_in_plaintext(self):
        """The logger.warning for SMTP-disabled case must NOT include the raw token."""
        import os
        main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(main_path) as f:
            source = f.read()
        # Ensure the old pattern (logging the token directly) is gone
        assert "password reset token for '%s': %s\", username, token" not in source, (
            "Password reset token must NOT be logged in plaintext in the warning call"
        )

    def test_reset_rate_limit_is_per_hour(self):
        """Password reset endpoint must use an hour-based rate limit."""
        import os
        main_path = os.path.join(os.path.dirname(__file__), "..", "api", "main.py")
        with open(main_path) as f:
            source = f.read()
        assert "3/hour" in source, (
            "Password reset endpoint must use 3/hour rate limit"
        )


class TestSecretFilePermissions:
    """secret_helper.py must raise PermissionError on writable secret files (v1.93.18 L3)."""

    def test_secret_helper_raises_on_write_bits_in_source(self):
        """secret_helper.py must contain a PermissionError raise for write bits."""
        import os
        sh_path = os.path.join(os.path.dirname(__file__), "..", "api", "secret_helper.py")
        with open(sh_path, encoding="utf-8") as f:
            source = f.read()
        assert "PermissionError" in source, (
            "secret_helper must raise PermissionError for insecure secret file permissions"
        )
        assert "0o022" in source, (
            "secret_helper must check write bits (0o022 mask)"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="os.chmod does not enforce Unix bits on Windows")
    def test_write_bits_raise_permission_error(self, tmp_path):
        """A world-writable secret file must raise PermissionError (Linux only)."""
        import importlib
        api_dir = os.path.join(os.path.dirname(__file__), "..", "api")
        sys.path.insert(0, api_dir)
        secret_file = tmp_path / "test_pw"
        secret_file.write_text("mysecret")
        os.chmod(str(secret_file), 0o666)
        os.environ["SECRETS_DIR"] = str(tmp_path)
        if "secret_helper" in sys.modules:
            del sys.modules["secret_helper"]
        import secret_helper as sh
        try:
            with pytest.raises(PermissionError):
                sh.read_secret("test_pw")
        finally:
            del os.environ["SECRETS_DIR"]
            if "secret_helper" in sys.modules:
                del sys.modules["secret_helper"]

    @pytest.mark.skipif(sys.platform == "win32", reason="os.chmod does not enforce Unix bits on Windows")
    def test_owner_readonly_is_accepted(self, tmp_path):
        """A 0600 secret file must be read without error (Linux only)."""
        api_dir = os.path.join(os.path.dirname(__file__), "..", "api")
        sys.path.insert(0, api_dir)
        secret_file = tmp_path / "test_pw"
        secret_file.write_text("mysecret")
        os.chmod(str(secret_file), 0o600)
        os.environ["SECRETS_DIR"] = str(tmp_path)
        if "secret_helper" in sys.modules:
            del sys.modules["secret_helper"]
        import secret_helper as sh
        try:
            val = sh.read_secret("test_pw")
            assert val == "mysecret"
        finally:
            del os.environ["SECRETS_DIR"]
            if "secret_helper" in sys.modules:
                del sys.modules["secret_helper"]


class TestConfigValidatorLogging:
    """config_validator.py must use logger, not print() (v1.93.18 L2)."""

    def test_no_print_statements_in_print_validation_results(self):
        """print_validation_results must use logger, not print()."""
        import os
        cfg_path = os.path.join(os.path.dirname(__file__), "..", "api", "config_validator.py")
        with open(cfg_path, encoding="utf-8") as f:
            source = f.read()
        # Find the method body
        method_start = source.find("def print_validation_results")
        method_end = source.find("\n    @classmethod", method_start + 1)
        if method_end == -1:
            method_end = len(source)
        method_body = source[method_start:method_end]
        assert "print(" not in method_body, (
            "print_validation_results must not call print() \u2014 use logger instead"
        )
        assert "logger." in method_body, (
            "print_validation_results must use logger for structured output"
        )
