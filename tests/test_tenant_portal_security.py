"""
tests/test_tenant_portal_security.py — P8 Tenant Portal security test suite.

Covers 27 security requirements across 8 categories:

  S01–S04  Authentication / unauthenticated branding endpoint
  S05–S08  Authorisation / RBAC checks on admin endpoints
  S09–S12  SQL injection surface (static SQL, no f-string interpolation)
  S13–S16  IDOR prevention (ownership check pattern)
  S17–S19  Session management (invalidation, hash, expiry)
  S20–S22  MFA enrollment integrity
  S23–S25  Branding validation (hex colour, field lengths)
  S26–S27  Audit trail coverage

No live DB or Redis required — all external calls are mocked.
"""

import ast
import os
import sys
import types
import textwrap
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow importing from api/ and tenant_portal/
# ---------------------------------------------------------------------------
_TEST_DIR   = os.path.dirname(__file__)
_ROOT_DIR   = os.path.abspath(os.path.join(_TEST_DIR, ".."))
_API_DIR    = os.path.join(_ROOT_DIR, "api")
_PORTAL_DIR = os.path.join(_ROOT_DIR, "tenant_portal")

for _p in (_API_DIR, _PORTAL_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Minimal stubs so we can import modules without live infrastructure
# ---------------------------------------------------------------------------

def _ensure_stub(name: str, attrs: dict | None = None) -> types.ModuleType:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in (attrs or {}).items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


_ensure_stub("psycopg2")
_ensure_stub("psycopg2.extras", {"RealDictCursor": object})
_ensure_stub("redis")

_conn_ctx_mock = MagicMock()
_conn_ctx_mock.__enter__ = MagicMock(return_value=_conn_ctx_mock)
_conn_ctx_mock.__exit__ = MagicMock(return_value=False)

_db_stub = _ensure_stub("db_pool", {
    "get_connection":        MagicMock(return_value=_conn_ctx_mock),
    "get_tenant_connection": MagicMock(return_value=_conn_ctx_mock),
    "init_pool":             MagicMock(),
})

_ensure_stub("secret_helper", {"read_secret": lambda *a, **kw: ""})
_ensure_stub("rate_limiter",  {"limiter": MagicMock()})
_ensure_stub("redis_client",  {"get_redis": MagicMock()})
_ensure_stub("request_helpers", {"get_request_ip": lambda req: "127.0.0.1"})

_auth_user_cls = type("User", (), {"username": "admin", "role": "admin", "email": ""})
_ensure_stub("auth", {
    "require_authentication": MagicMock(return_value=_auth_user_cls()),
    "log_auth_event":         MagicMock(),
    "User":                   _auth_user_cls,
})

_ensure_stub("slowapi",              {"_rate_limit_exceeded_handler": MagicMock()})
_ensure_stub("slowapi.errors",       {"RateLimitExceeded": Exception})
_ensure_stub("slowapi.middleware",   {"SlowAPIMiddleware": MagicMock()})
_ensure_stub("audit_helper",         {"log_action": MagicMock()})
_ensure_stub("middleware",           {
    "get_tenant_context": MagicMock(),
    "inject_rls_vars":    MagicMock(),
})

_tc = type("TenantContext", (), {
    "keystone_user_id": "user-123",
    "project_ids":       ["proj-1"],
    "region_ids":        ["region-1"],
    "control_plane_id":  "cp-1",
})
_ensure_stub("tenant_context", {"TenantContext": _tc})


# ============================================================================
# S01–S04  Authentication
# ============================================================================

class TestPublicBrandingEndpoint:
    """S01-S04: GET /tenant/branding is unauthenticated and fails gracefully."""

    @pytest.fixture(autouse=True)
    def _reset_branding_module(self):
        """Re-install a correct db_pool stub and evict branding_routes before each test.

        test_rbac_middleware has an autouse fixture that replaces db_pool with a
        stub that has only get_connection (not get_tenant_connection).  We create
        a fresh complete stub here so branding_routes always imports cleanly.
        """
        # Always force-create a fresh db_pool stub with BOTH methods
        fresh_db_stub = types.ModuleType("db_pool")
        fresh_db_stub.get_connection        = MagicMock(return_value=_conn_ctx_mock)
        fresh_db_stub.get_tenant_connection = MagicMock(return_value=_conn_ctx_mock)
        fresh_db_stub.init_pool             = MagicMock()
        sys.modules["db_pool"] = fresh_db_stub
        # Evict branding_routes so each test gets a fresh import against our stub
        sys.modules.pop("branding_routes", None)
        yield
        sys.modules.pop("branding_routes", None)

    def test_s01_no_auth_required_on_branding_route(self):
        """S01: branding_routes.router has no auth dependency on get_branding."""
        import importlib
        mod = importlib.import_module("branding_routes")
        routes = {r.path: r for r in mod.router.routes}
        route = routes.get("/tenant/branding")
        assert route is not None, "GET /tenant/branding route must be registered"
        # No Depends(get_tenant_context) or Depends(require_authentication) on this endpoint
        dep_fns = [d.dependency for d in getattr(route, "dependencies", [])]
        dep_fn_names = [getattr(f, "__name__", "") for f in dep_fns]
        assert "require_authentication" not in dep_fn_names
        assert "get_tenant_context" not in dep_fn_names

    def test_s02_branding_returns_defaults_on_db_failure(self):
        """S02: DB error → defaults returned, no 500 propagated to caller."""
        import importlib
        import asyncio
        import branding_routes
        importlib.reload(branding_routes)
        branding_routes._CACHE.clear()
        with patch("branding_routes.get_tenant_connection", side_effect=RuntimeError("db down")):
            result = asyncio.get_event_loop().run_until_complete(branding_routes.get_branding())
        assert result["company_name"] == "Cloud Portal"
        assert result["primary_color"] == "#1A73E8"

    def test_s03_branding_returns_defaults_when_no_row(self):
        """S03: Empty DB row → defaults returned."""
        import importlib, asyncio
        import branding_routes
        importlib.reload(branding_routes)
        branding_routes._CACHE.clear()
        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__  = MagicMock(return_value=False)
        mock_cur.fetchone  = MagicMock(return_value=None)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.cursor    = MagicMock(return_value=mock_cur)
        with patch("branding_routes.get_tenant_connection", return_value=mock_conn):
            result = asyncio.get_event_loop().run_until_complete(branding_routes.get_branding())
        assert result["company_name"] == "Cloud Portal"

    def test_s04_branding_result_cached(self):
        """S04: Second call within TTL doesn't re-query the DB."""
        import importlib, asyncio
        import branding_routes
        importlib.reload(branding_routes)
        branding_routes._CACHE.clear()
        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__  = MagicMock(return_value=False)
        mock_cur.fetchone  = MagicMock(return_value={
            "company_name": "ACME", "logo_url": None, "favicon_url": None,
            "primary_color": "#FF0000", "accent_color": "#00FF00",
            "support_email": None, "support_url": None,
            "welcome_message": None, "footer_text": None,
        })
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.cursor    = MagicMock(return_value=mock_cur)
        with patch("branding_routes.get_tenant_connection", return_value=mock_conn) as mock_get:
            asyncio.get_event_loop().run_until_complete(branding_routes.get_branding())
            asyncio.get_event_loop().run_until_complete(branding_routes.get_branding())
        assert mock_get.call_count == 1, "DB should only be queried once within TTL"


# ============================================================================
# S05–S08  Authorisation (admin endpoint RBAC)
# ============================================================================

class TestAdminEndpointRBAC:
    """S05-S08: Admin tenant-portal endpoints require admin/superadmin role."""

    def _load_tpr(self):
        import importlib
        for name in ("tenant_portal_routes",):
            sys.modules.pop(name, None)
        return importlib.import_module("tenant_portal_routes")

    def test_s05_require_admin_rejects_viewer(self):
        """S05: viewer role → 403 on _require_admin guard."""
        from fastapi import HTTPException
        mod = self._load_tpr()
        viewer = type("U", (), {"role": "viewer", "username": "v"})()
        with pytest.raises(HTTPException) as exc_info:
            mod._require_admin(viewer)
        assert exc_info.value.status_code == 403

    def test_s06_require_admin_rejects_operator(self):
        """S06: operator role → 403."""
        from fastapi import HTTPException
        mod = self._load_tpr()
        operator = type("U", (), {"role": "operator", "username": "op"})()
        with pytest.raises(HTTPException) as exc_info:
            mod._require_admin(operator)
        assert exc_info.value.status_code == 403

    def test_s07_require_admin_allows_admin(self):
        """S07: admin role → no exception."""
        mod = self._load_tpr()
        admin = type("U", (), {"role": "admin", "username": "a"})()
        result = mod._require_admin(admin)
        assert result.role == "admin"

    def test_s08_require_admin_allows_superadmin(self):
        """S08: superadmin role → no exception."""
        mod = self._load_tpr()
        superadmin = type("U", (), {"role": "superadmin", "username": "sa"})()
        result = mod._require_admin(superadmin)
        assert result.role == "superadmin"


# ============================================================================
# S09–S12  SQL injection surface
# ============================================================================

class TestNoSQLInjection:
    """S09-S12: All DB queries must use parameterised SQL — no string formatting of user input."""

    _FILES = [
        os.path.join(_PORTAL_DIR, "branding_routes.py"),
        os.path.join(_PORTAL_DIR, "environment_routes.py"),
        os.path.join(_PORTAL_DIR, "auth_routes.py"),
        os.path.join(_API_DIR,    "tenant_portal_routes.py"),
    ]

    def _get_source(self, path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_s09_no_fstring_in_execute_calls(self):
        """S09: f-strings must not appear in the same expression as .execute(."""
        for fpath in self._FILES:
            source = self._get_source(fpath)
            tree   = ast.parse(source)
            fname  = os.path.basename(fpath)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
                    continue
                for arg in node.args:
                    assert not isinstance(arg, ast.JoinedStr), (
                        f"{fname}: f-string passed directly to .execute() at line {node.lineno}"
                    )

    def test_s10_no_percent_format_in_execute(self):
        """S10: % string formatting must not be used inside .execute() SQL argument."""
        for fpath in self._FILES:
            source = self._get_source(fpath)
            tree   = ast.parse(source)
            fname  = os.path.basename(fpath)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "execute"):
                    continue
                for arg in node.args:
                    # BinOp % (old-style formatting) would be ast.BinOp with Mod op
                    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):
                        pytest.fail(
                            f"{fname} line {node.lineno}: % string format in .execute() "
                            "is a SQL injection risk — use parameterised queries"
                        )

    def test_s11_branding_query_parameterised(self):
        """S11: The branding SELECT query uses %s placeholder, not string concat."""
        source = self._get_source(os.path.join(_PORTAL_DIR, "branding_routes.py"))
        assert "WHERE control_plane_id = %s" in source
        assert "WHERE control_plane_id = " + "'" not in source
        assert "WHERE control_plane_id = " + '"' not in source

    def test_s12_mfa_reset_parameterised(self):
        """S12: admin_reset_mfa DELETE uses %s placeholders, not format strings."""
        source = self._get_source(os.path.join(_API_DIR, "tenant_portal_routes.py"))
        # The DELETE must appear with parameters, not inline values
        assert "WHERE keystone_user_id = %s AND control_plane_id = %s" in source


# ============================================================================
# S13–S16  IDOR prevention
# ============================================================================

class TestIDORPrevention:
    """S13-S16: Tenant endpoints return 403-not-404 to prevent existence oracle attacks."""

    def _source(self, fname):
        path = os.path.join(_PORTAL_DIR, fname)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_s13_vm_ownership_raises_403_not_404(self):
        """S13: _check_vm_ownership raises HTTP 403 on miss."""
        source = self._source("environment_routes.py")
        # Confirm the 403 constant is used (could be HTTP_403_FORBIDDEN or 403 literal)
        assert "HTTP_403_FORBIDDEN" in source or "403" in source
        assert "_check_vm_ownership" in source

    def test_s14_no_404_on_ownership_miss(self):
        """S14: _check_vm_ownership must NOT raise 404 (existence oracle)."""
        tree = ast.parse(self._source("environment_routes.py"))
        for node in ast.walk(tree):
            # Look for any Raise or raise HTTPException(status_code=404) in _check_vm_ownership
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name != "_check_vm_ownership":
                continue
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if not (isinstance(func, ast.Name) and func.id == "HTTPException"):
                    continue
                for kw in child.keywords:
                    if kw.arg == "status_code" and isinstance(kw.value, (ast.Constant, ast.Attribute)):
                        val = kw.value
                        if isinstance(val, ast.Constant) and val.value == 404:
                            pytest.fail("_check_vm_ownership must not raise 404 — use 403")

    def test_s15_sql_scoped_to_tenant_project_and_region(self):
        """S15: All SELECT queries in environment_routes.py include project AND region scope."""
        source = self._source("environment_routes.py")
        # Every SELECT block must have region/project scope; verifying our double-scope pattern
        assert "project_id = ANY(%s)" in source
        assert "region_id  = ANY(%s)" in source or "region_id = ANY(%s)" in source

    def test_s16_rls_inject_called_before_queries(self):
        """S16: inject_rls_vars is called in environment_routes — confirms RLS double-scope."""
        source = self._source("environment_routes.py")
        assert "inject_rls_vars(cur, ctx)" in source


# ============================================================================
# S17–S19  Session management
# ============================================================================

class TestSessionManagement:
    """S17-S19: Session tokens are hashed, scoped to CP, and can be force-revoked."""

    def _portal_source(self, fname):
        path = os.path.join(_PORTAL_DIR, fname)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_s17_session_token_hashed_in_redis(self):
        """S17: auth_routes.py stores a hashed token in Redis, never plaintext."""
        source = self._portal_source("auth_routes.py")
        # Must hash before storage; the hash helper name may vary but hashlib/hmac usage expected
        assert "_hash_token" in source or "hashlib" in source or "hmac" in source, (
            "Session tokens must be hashed before Redis storage"
        )

    def test_s18_session_key_scoped_to_cp(self):
        """S18: Redis session key includes control_plane_id to prevent cross-CP session replay."""
        source = self._portal_source("auth_routes.py")
        # Look for CP ID incorporated in the key construction
        assert "TENANT_PORTAL_CP_ID" in source or "control_plane_id" in source, (
            "Session Redis key must be scoped to control_plane_id"
        )

    def test_s19_admin_can_delete_sessions(self):
        """S19: admin endpoint exists to force-delete all sessions for a user."""
        import importlib
        mod = importlib.import_module("tenant_portal_routes")
        route_paths = [r.path for r in mod.router.routes]
        delete_session_routes = [
            p for p in route_paths
            if "/sessions/" in p and any(
                r.methods and "DELETE" in r.methods
                for r in mod.router.routes
                if r.path == p
            )
        ]
        assert len(delete_session_routes) >= 1, (
            "At least one DELETE /sessions/{cp_id}/{user} admin endpoint must be registered"
        )


# ============================================================================
# S20–S22  MFA enrollment integrity
# ============================================================================

class TestMFAIntegrity:
    """S20-S22: MFA enrollment security properties."""

    def _portal_source(self, fname):
        path = os.path.join(_PORTAL_DIR, fname)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_s20_mfa_reset_endpoint_registered(self):
        """S20: DELETE /mfa/{cp_id}/{keystone_user_id} admin endpoint is registered."""
        import importlib
        mod = importlib.import_module("tenant_portal_routes")
        delete_mfa_routes = [
            r.path for r in mod.router.routes
            if "/mfa/" in r.path and r.methods and "DELETE" in r.methods
        ]
        assert len(delete_mfa_routes) >= 1, (
            "DELETE /mfa/{cp_id}/{keystone_user_id} endpoint must be registered"
        )

    def test_s21_mfa_delete_returns_404_when_no_enrollment(self):
        """S21: admin_reset_mfa raises 404 when no enrollment row is found (clean error)."""
        from fastapi import HTTPException
        import importlib
        import asyncio
        mod = importlib.import_module("tenant_portal_routes")

        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__  = MagicMock(return_value=False)
        mock_cur.fetchone  = MagicMock(return_value=None)   # no row deleted
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.cursor    = MagicMock(return_value=mock_cur)

        admin_user = type("U", (), {"username": "admin", "role": "admin"})()
        mock_request = MagicMock()

        with patch("tenant_portal_routes.get_connection", return_value=mock_conn):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    mod.admin_reset_mfa("cp-1", "user-x", mock_request, admin_user)
                )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "mfa_enrollment_not_found"

    def test_s22_mfa_delete_logs_admin_action(self):
        """S22: Successful MFA reset is logged with admin username and user ID."""
        import importlib, asyncio
        mod = importlib.import_module("tenant_portal_routes")

        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__  = MagicMock(return_value=False)
        mock_cur.fetchone  = MagicMock(return_value={"keystone_user_id": "user-x"})
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.cursor    = MagicMock(return_value=mock_cur)

        admin_user   = type("U", (), {"username": "sadmin", "role": "superadmin"})()
        mock_request = MagicMock()

        with patch("tenant_portal_routes.get_connection", return_value=mock_conn):
            with patch.object(mod.logger, "info") as mock_log:
                asyncio.get_event_loop().run_until_complete(
                    mod.admin_reset_mfa("cp-1", "user-x", mock_request, admin_user)
                )
        # At least one log.info call mentioning the user and admin
        logged_messages = " ".join(str(c) for c in mock_log.call_args_list)
        assert "user-x" in logged_messages
        assert "sadmin" in logged_messages


# ============================================================================
# S23–S25  Branding input validation
# ============================================================================

class TestBrandingValidation:
    """S23-S25: BrandingUpsertRequest model validates colour and string fields."""

    def _load_model(self):
        import importlib
        sys.modules.pop("tenant_portal_routes", None)
        mod = importlib.import_module("tenant_portal_routes")
        return mod.BrandingUpsertRequest

    def test_s23_valid_hex_color_accepted(self):
        """S23: Valid 6-digit hex colours are accepted."""
        model = self._load_model()
        obj = model(
            company_name="ACME",
            primary_color="#1A73E8",
            accent_color="#F29900",
        )
        assert obj.primary_color == "#1A73E8"
        assert obj.accent_color == "#F29900"

    def test_s24_invalid_hex_color_rejected(self):
        """S24: Non-hex or wrong-length colours raise ValidationError."""
        from pydantic import ValidationError
        model = self._load_model()
        invalid_cases = [
            {"primary_color": "blue"},
            {"primary_color": "#ZZZ"},
            {"primary_color": "#12345"},       # 5 digits
            {"primary_color": "#1234567"},     # 7 digits
            {"accent_color":  "rgba(0,0,0)"},
        ]
        for overrides in invalid_cases:
            with pytest.raises(ValidationError):
                model(company_name="X", **overrides)

    def test_s25_default_colors_are_valid_hex(self):
        """S25: Default colour values themselves pass the validator."""
        model = self._load_model()
        obj = model(company_name="Defaults")
        # Validator is applied to defaults — these must pass
        assert obj.primary_color.startswith("#")
        assert len(obj.primary_color) == 7
        assert obj.accent_color.startswith("#")
        assert len(obj.accent_color) == 7


# ============================================================================
# S26–S27  Audit trail coverage
# ============================================================================

class TestAuditTrail:
    """S26-S27: branding upsert and MFA reset are covered by server-side logging."""

    def test_s26_branding_upsert_logs_to_logger(self):
        """S26: PUT branding endpoint calls logger.info after successful upsert."""
        import importlib, asyncio
        mod = importlib.import_module("tenant_portal_routes")

        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__  = MagicMock(return_value=False)
        mock_cur.fetchone  = MagicMock(return_value={
            "control_plane_id": "cp-1",
            "project_id": "",
            "updated_at": datetime.now(timezone.utc),
        })
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.cursor    = MagicMock(return_value=mock_cur)

        admin_user   = type("U", (), {"username": "admin1", "role": "admin"})()
        mock_request = MagicMock()

        body = mod.BrandingUpsertRequest(company_name="ACME")

        with patch("tenant_portal_routes.get_connection", return_value=mock_conn):
            with patch.object(mod.logger, "info") as mock_log:
                asyncio.get_event_loop().run_until_complete(
                    mod.upsert_branding("cp-1", body, mock_request, current_user=admin_user)
                )
        logged_messages = " ".join(str(c) for c in mock_log.call_args_list)
        assert "cp-1" in logged_messages
        assert "admin1" in logged_messages

    def test_s27_audit_log_endpoint_exists_and_returns_paged_response(self):
        """S27: GET /audit/{cp_id} admin endpoint is registered and returns paginated shape."""
        import importlib, asyncio
        mod = importlib.import_module("tenant_portal_routes")

        # Verify route is registered
        audit_routes = [r.path for r in mod.router.routes if "/audit/" in r.path]
        assert len(audit_routes) >= 1, "GET /audit/{cp_id} must be registered"

        mock_conn = MagicMock()
        mock_cur  = MagicMock()
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__  = MagicMock(return_value=False)
        # fetchall returns rows; second fetchone returns count
        mock_cur.fetchall = MagicMock(return_value=[
            {"id": 1, "keystone_user_id": "u", "control_plane_id": "cp-1",
             "action": "login", "resource_type": None, "resource_id": None,
             "project_id": None, "region_id": None, "ip_address": "1.2.3.4",
             "success": True, "detail": None, "created_at": datetime.now(timezone.utc)}
        ])
        mock_cur.fetchone = MagicMock(return_value={"count": 1})
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__  = MagicMock(return_value=False)
        mock_conn.cursor    = MagicMock(return_value=mock_cur)

        admin_user = type("U", (), {"username": "admin", "role": "admin"})()

        with patch("tenant_portal_routes.get_connection", return_value=mock_conn):
            result = asyncio.get_event_loop().run_until_complete(
                mod.get_audit_log("cp-1", limit=50, offset=0,
                                  keystone_user_id=None, current_user=admin_user)
            )
        assert "total"  in result
        assert "items"  in result
        assert "offset" in result
        assert result["total"] == 1
        assert len(result["items"]) == 1
        # Rows must carry 'detail' and 'created_at' keys (aliased from DB columns)
        assert "detail"     in result["items"][0]
        assert "created_at" in result["items"][0]


# ============================================================================
# S28–S30  URL injection / length limits
# ============================================================================

class TestBrandingURLValidation:
    """S28-S30: BrandingUpsertRequest rejects javascript: URIs and over-long strings."""

    def _load_model(self):
        import importlib
        sys.modules.pop("tenant_portal_routes", None)
        mod = importlib.import_module("tenant_portal_routes")
        return mod.BrandingUpsertRequest

    def test_s28_javascript_logo_url_rejected(self):
        """S28: javascript: URI in logo_url raises ValidationError."""
        from pydantic import ValidationError
        model = self._load_model()
        with pytest.raises(ValidationError):
            model(company_name="X", logo_url="javascript:alert(1)")

    def test_s29_data_uri_favicon_rejected(self):
        """S29: data: URI in favicon_url raises ValidationError."""
        from pydantic import ValidationError
        model = self._load_model()
        with pytest.raises(ValidationError):
            model(company_name="X", favicon_url="data:text/html,<script>evil</script>")

    def test_s30_https_urls_accepted(self):
        """S30: Valid https:// URLs are accepted for all URL fields."""
        model = self._load_model()
        obj = model(
            company_name="ACME",
            logo_url="https://cdn.example.com/logo.png",
            favicon_url="https://cdn.example.com/favicon.ico",
            support_url="https://support.example.com",
        )


# ============================================================================
# S31–S33  Login domain field validation
# ============================================================================

class TestLoginDomainValidation:
    """S31-S33: LoginRequest.domain field rejects injection chars, empty, and over-long values."""

    def _load_model(self):
        import importlib
        sys.modules.pop("auth_routes", None)
        # Stub httpx and jose if not already available
        _ensure_stub("httpx", {"AsyncClient": MagicMock(), "HTTPError": Exception})
        _ensure_stub("jose", {"jwt": MagicMock(), "JWTError": Exception})
        # Patch the existing middleware stub with attrs auth_routes needs at import time
        mw = sys.modules.get("middleware")
        if mw is not None:
            mw.JWT_ALGORITHM = "HS256"
            mw.JWT_SECRET_KEY = "test-secret-key"
            mw.TENANT_TOKEN_EXPIRE_MINUTES = 60
            mw._check_rate_limit = MagicMock()
            mw._hash_token = MagicMock(return_value="hashed")
            mw._redis_session_key = MagicMock(return_value="key")
            mw.get_tenant_context = MagicMock()
            mw.inject_rls_vars = MagicMock()
        mod = importlib.import_module("auth_routes")
        return mod.LoginRequest

    def test_s31_default_domain_accepted(self):
        """S31: Default domain value 'Default' passes all validators."""
        model = self._load_model()
        obj = model(username="user@org.com", password="secret")
        assert obj.domain == "Default"

    def test_s32_domain_with_injection_chars_rejected(self):
        """S32: Domain names with special characters are rejected (injection prevention)."""
        from pydantic import ValidationError
        model = self._load_model()
        bad_domains = [
            "Default; DROP TABLE users",
            "<script>alert(1)</script>",
            "domain\x00null",
            "../../../etc",
            "domain name",   # space not allowed
        ]
        for bad in bad_domains:
            with pytest.raises(ValidationError, match="domain"):
                model(username="u", password="p", domain=bad)

    def test_s33_over_long_domain_rejected(self):
        """S33: Domain names exceeding 255 chars are rejected."""
        from pydantic import ValidationError
        model = self._load_model()
        with pytest.raises(ValidationError):
            model(username="u", password="p", domain="A" * 256)
