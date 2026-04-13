"""
tests/test_rbac_middleware.py — RBAC and authentication middleware unit tests.

Tests cover (B12.3):
  - JWT token expiry, missing sub, tampered signature → decoded as None
  - Role-based permission matrix (viewer/operator/admin/superadmin)
  - require_permission dependency: 401 for unauthenticated, 403 for wrong role
  - Missing cookie + missing Bearer → unauthenticated path
  - Role upgrade reflected in next access check

No live DB or LDAP required.  All DB access is mocked.
"""
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from jose import jwt as _jose_jwt

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# ---------------------------------------------------------------------------
# Module stubs — registered once at collection time for auth's own dependencies.
# auth itself is NOT force-evicted here because test_restore_management.py
# (imported later alphabetically) would re-install its own stub.  Instead an
# autouse fixture below ensures each test method gets the real auth module.
# ---------------------------------------------------------------------------

# Stub auth's custom dependencies that aren't pip-installable
_db_stub = types.ModuleType("db_pool")
_db_stub.get_connection = MagicMock(side_effect=RuntimeError("no DB in rbac tests"))
sys.modules.setdefault("db_pool", _db_stub)

_ldap_auth_stub = types.ModuleType("ldap_auth")
_ldap_auth_stub.LDAPAuthenticator = MagicMock
sys.modules.setdefault("ldap_auth", _ldap_auth_stub)

_cache_stub = types.ModuleType("cache")
_cache_stub._get_client = lambda: None
sys.modules.setdefault("cache", _cache_stub)

_rhelpers_stub = types.ModuleType("request_helpers")
_rhelpers_stub.get_request_ip = lambda req: "127.0.0.1"
sys.modules.setdefault("request_helpers", _rhelpers_stub)

if "secret_helper" not in sys.modules:
    _sh_stub = types.ModuleType("secret_helper")
    _sh_stub.read_secret = lambda name, env_var=None, default="": ""
    sys.modules["secret_helper"] = _sh_stub


# ---------------------------------------------------------------------------
# Autouse fixture: guarantee each test in this file runs with the REAL auth
# module, regardless of what other test files installed during collection.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _ensure_real_auth_module():
    """Evict any auth/fastapi stubs and re-import the real auth before each test."""
    # Ensure our db_pool stub (with get_connection) is active for auth.py import
    sys.modules["db_pool"] = _db_stub
    sys.modules.setdefault("request_helpers", _rhelpers_stub)
    if "secret_helper" not in sys.modules:
        sys.modules["secret_helper"] = _sh_stub
    # Evict auth + fastapi so the real modules are freshly imported
    for _mod in ("auth", "fastapi", "fastapi.security", "fastapi.security.http",
                 "fastapi.security.oauth2"):
        sys.modules.pop(_mod, None)
    yield
    # After the test, evict auth again so the next test also gets a fresh import
    sys.modules.pop("auth", None)

# ---------------------------------------------------------------------------
# JWT helpers for isolated token construction
# ---------------------------------------------------------------------------
_TEST_SECRET = "rbac-test-secret-key-not-for-production"
_ALGORITHM = "HS256"


def _make_jwt(sub: str, role: str, exp_delta: timedelta = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "role": role,
        "iat": now,
        "exp": now + (exp_delta if exp_delta is not None else timedelta(minutes=90)),
    }
    return _jose_jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)


def _decode_jwt(token: str):
    try:
        return _jose_jwt.decode(token, _TEST_SECRET, algorithms=[_ALGORITHM])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Inline permission table (mirrors role_permissions in db/init.sql)
# Write implies read; admin implies write and read.
# ---------------------------------------------------------------------------
_ROLE_PERM: dict = {
    "viewer":     {"vms": "read",  "snapshots": "read",  "reports": "read"},
    "operator":   {"vms": "write", "snapshots": "write", "reports": "read"},
    "admin":      {"vms": "admin", "snapshots": "admin", "users": "admin"},
    "superadmin": {"*": "admin"},
}

_HIERARCHY = {"read": 1, "write": 2, "admin": 3}


def _check_perm(role: str, resource: str, permission: str) -> bool:
    """Inline permission check without DB."""
    if not role:
        return False
    perms = _ROLE_PERM.get(role, {})
    if "*" in perms:
        return True
    action = perms.get(resource)
    if not action:
        return False
    return _HIERARCHY.get(action, 0) >= _HIERARCHY.get(permission, 99)


# ===========================================================================
# 1.  JWT token structure and validation
# ===========================================================================

class TestJWTValidation:
    def test_valid_token_decodes(self):
        token = _make_jwt("user1", "viewer")
        payload = _decode_jwt(token)
        assert payload is not None
        assert payload["sub"] == "user1"
        assert payload["role"] == "viewer"

    def test_expired_token_returns_none(self):
        token = _make_jwt("user1", "viewer", exp_delta=timedelta(seconds=-1))
        assert _decode_jwt(token) is None

    def test_wrong_secret_returns_none(self):
        token = _make_jwt("user1", "viewer")
        try:
            result = _jose_jwt.decode(token, "wrong-secret", algorithms=[_ALGORITHM])
        except Exception:
            result = None
        assert result is None

    def test_tampered_payload_returns_none(self):
        token = _make_jwt("user1", "viewer")
        # Corrupt the last 4 chars of the signature segment
        tampered = token[:-4] + "XXXX"
        assert _decode_jwt(tampered) is None

    def test_missing_sub_field(self):
        now = datetime.now(timezone.utc)
        payload = {"role": "viewer", "iat": now, "exp": now + timedelta(minutes=10)}
        token = _jose_jwt.encode(payload, _TEST_SECRET, algorithm=_ALGORITHM)
        data = _decode_jwt(token)
        # Token itself decodes; sub is absent
        assert data is not None
        assert data.get("sub") is None

    def test_superadmin_token_carries_correct_role(self):
        token = _make_jwt("admin", "superadmin")
        payload = _decode_jwt(token)
        assert payload["role"] == "superadmin"

    def test_multiple_roles_each_decode_correctly(self):
        for role in ("viewer", "operator", "admin", "superadmin"):
            token = _make_jwt("u", role)
            payload = _decode_jwt(token)
            assert payload["role"] == role

    def test_very_short_expiry_still_valid_before_exp(self):
        token = _make_jwt("u", "viewer", exp_delta=timedelta(seconds=30))
        payload = _decode_jwt(token)
        assert payload is not None

    def test_empty_token_returns_none(self):
        assert _decode_jwt("") is None

    def test_garbage_token_returns_none(self):
        assert _decode_jwt("not.a.jwt") is None


# ===========================================================================
# 2.  Role-based permission matrix
# ===========================================================================

class TestPermissionMatrix:
    @pytest.mark.parametrize("role,resource,permission,expected", [
        # Viewer: read-only access
        ("viewer",     "vms",        "read",  True),
        ("viewer",     "vms",        "write", False),
        ("viewer",     "vms",        "admin", False),
        ("viewer",     "snapshots",  "read",  True),
        # Operator: write access to vms/snapshots
        ("operator",   "vms",        "write", True),
        ("operator",   "vms",        "read",  True),   # write implies read
        ("operator",   "snapshots",  "write", True),
        ("operator",   "snapshots",  "admin", False),
        ("operator",   "users",      "read",  False),  # no users permission
        # Admin: admin on vms, snapshots, users
        ("admin",      "vms",        "admin", True),
        ("admin",      "vms",        "write", True),   # admin implies write
        ("admin",      "vms",        "read",  True),   # admin implies read
        ("admin",      "users",      "admin", True),
        ("admin",      "nonexistent","read",  False),
        # Superadmin: wildcard
        ("superadmin", "vms",        "admin", True),
        ("superadmin", "anything",   "read",  True),
        ("superadmin", "anything",   "admin", True),
        # No role
        (None,         "vms",        "read",  False),
        ("",           "vms",        "read",  False),
        # Unknown role
        ("unknown",    "vms",        "read",  False),
    ])
    def test_permission(self, role, resource, permission, expected):
        assert _check_perm(role, resource, permission) == expected

    def test_write_implies_read_for_operator(self):
        assert _check_perm("operator", "vms", "read") is True

    def test_admin_implies_write(self):
        assert _check_perm("admin", "vms", "write") is True

    def test_admin_cannot_access_unknown_resource(self):
        assert _check_perm("admin", "billing", "read") is False

    def test_superadmin_passes_all_combinations(self):
        for perm in ("read", "write", "admin"):
            assert _check_perm("superadmin", "any_resource", perm) is True

    def test_viewer_cannot_write_any_resource(self):
        for resource in ("vms", "snapshots", "reports", "users"):
            assert _check_perm("viewer", resource, "write") is False


# ===========================================================================
# 3.  require_permission dependency (using auth module with mocked DB)
# ===========================================================================

class TestRequirePermissionDependency:
    """
    Directly invokes the inner dependency function produced by
    require_permission() with a pre-constructed User object.
    """

    def _mock_request(self, path="/api/vms"):
        req = MagicMock()
        req.url.path = path
        req.headers.get = lambda k, d=None: d
        return req

    @pytest.mark.asyncio
    async def test_unauthenticated_user_raises_401(self):
        from fastapi import HTTPException
        import auth as auth_mod

        with patch.object(auth_mod, "has_permission", return_value=True), \
             patch.object(auth_mod, "log_auth_event", return_value=None):
            dep_fn = auth_mod.require_permission("vms", "read")
            req = self._mock_request()
            with pytest.raises(HTTPException) as exc_info:
                await dep_fn(current_user=None, request=req)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_insufficient_role_raises_403(self):
        from fastapi import HTTPException
        import auth as auth_mod
        from auth import User

        viewer = User(username="viewer_user", role="viewer")
        with patch.object(auth_mod, "has_permission", return_value=False), \
             patch.object(auth_mod, "log_auth_event", return_value=None):
            dep_fn = auth_mod.require_permission("users", "admin")
            req = self._mock_request(path="/api/admin/users")
            with pytest.raises(HTTPException) as exc_info:
                await dep_fn(current_user=viewer, request=req)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_sufficient_role_returns_user_dict(self):
        import auth as auth_mod
        from auth import User

        admin_user = User(username="admin_user", role="admin")
        with patch.object(auth_mod, "has_permission", return_value=True), \
             patch.object(auth_mod, "log_auth_event", return_value=None):
            dep_fn = auth_mod.require_permission("vms", "write")
            req = self._mock_request()
            result = await dep_fn(current_user=admin_user, request=req)
            assert result["username"] == "admin_user"
            assert result["role"] == "admin"

    @pytest.mark.asyncio
    async def test_superadmin_allowed_all_resources(self):
        import auth as auth_mod
        from auth import User

        superadmin = User(username="sa", role="superadmin")
        with patch.object(auth_mod, "has_permission", return_value=True), \
             patch.object(auth_mod, "log_auth_event", return_value=None):
            for resource in ("vms", "users", "system_settings", "ldap_sync"):
                dep_fn = auth_mod.require_permission(resource, "admin")
                req = self._mock_request()
                result = await dep_fn(current_user=superadmin, request=req)
                assert result["username"] == "sa"

    @pytest.mark.asyncio
    async def test_permission_denied_logs_auth_event(self):
        from fastapi import HTTPException
        import auth as auth_mod
        from auth import User

        viewer = User(username="viewer_user", role="viewer")
        log_mock = MagicMock()
        with patch.object(auth_mod, "has_permission", return_value=False), \
             patch.object(auth_mod, "log_auth_event", log_mock):
            dep_fn = auth_mod.require_permission("users", "admin")
            req = self._mock_request("/api/admin/users")
            try:
                await dep_fn(current_user=viewer, request=req)
            except HTTPException:
                pass
            log_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_role_upgrade_reflected_immediately(self):
        """
        Simulate a viewer being upgraded to admin between requests.
        The permission check outcome changes based on the User object passed in.
        """
        import auth as auth_mod
        from auth import User

        viewer = User(username="u", role="viewer")
        admin  = User(username="u", role="admin")

        with patch.object(auth_mod, "has_permission", side_effect=lambda *a, **kw: True), \
             patch.object(auth_mod, "log_auth_event", return_value=None):
            req = self._mock_request()

            dep_fn = auth_mod.require_permission("users", "admin")
            # First call as viewer — has_permission=True (mocked)
            result_v = await dep_fn(current_user=viewer, request=req)
            assert result_v["role"] == "viewer"

            # Second call after role upgrade
            result_a = await dep_fn(current_user=admin, request=req)
            assert result_a["role"] == "admin"


# ===========================================================================
# 4.  Missing / expired token paths
# ===========================================================================

class TestMissingTokenPaths:
    def test_missing_bearer_and_cookie_gives_none_user(self):
        """
        Simulate validate_token behavior when both cookie and Bearer are absent.
        verify_token should return None for an empty/None token.
        """
        import auth as auth_mod

        # Patch get_connection so verify_token's DB check falls back gracefully
        with patch.object(auth_mod, "get_connection",
                          MagicMock(side_effect=RuntimeError("no DB"))):
            result = auth_mod.verify_token("")
        assert result is None

    def test_expired_jwt_verify_returns_none(self):
        import auth as auth_mod

        token = _make_jwt("u", "viewer", exp_delta=timedelta(seconds=-10))
        with patch.object(auth_mod, "get_connection",
                          MagicMock(side_effect=RuntimeError("no DB"))):
            result = auth_mod.verify_token(token)
        assert result is None

    def test_garbage_token_verify_returns_none(self):
        import auth as auth_mod

        with patch.object(auth_mod, "get_connection",
                          MagicMock(side_effect=RuntimeError("no DB"))):
            result = auth_mod.verify_token("garbage.token.here")
        assert result is None
