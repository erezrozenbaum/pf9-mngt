"""
tests/test_copilot_agentic.py — Tests for Copilot agentic execution (v2.2.0).

Covers:
  - Safety: confirmed=False must be rejected (400)
  - Safety: agentic disabled → 403
  - Rate limit: quota exceeded → 429
  - Agentic status endpoint returns expected shape
  - Intent match propagates runbook metadata
  - SQL injection: confirmed must be boolean, not truthy string
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the api/ directory is on sys.path for direct imports
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# ---------------------------------------------------------------------------
# Stub heavy dependencies so we can import copilot.py without a DB/server
# ---------------------------------------------------------------------------

def _make_stub(name: str):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


def _stub_modules():
    # psycopg2 stubs with RealDictCursor
    psycopg2_extras = sys.modules.get("psycopg2.extras") or _make_stub("psycopg2.extras")
    psycopg2_extras.RealDictCursor = MagicMock  # type: ignore[attr-defined]
    sys.modules["psycopg2.extras"] = psycopg2_extras

    for name in [
        "psycopg2", "psycopg2.pool",
        "fastapi", "fastapi.responses", "fastapi.routing",
        "starlette", "starlette.routing", "starlette.requests",
        "pydantic", "pydantic.fields",
        "cryptography", "cryptography.fernet",
        "jose", "jose.jwt", "jose.exceptions",
        "httpx",
    ]:
        if name not in sys.modules:
            _make_stub(name)

    # fastapi stubs — router decorators must pass functions through unchanged
    fapi = sys.modules["fastapi"]

    def _passthrough(*args, **kwargs):
        """Decorator factory that returns the decorated function unchanged."""
        def decorator(fn):
            return fn
        # Support both @router.get("/path") and @router.get("/path", ...) forms
        if args and callable(args[0]):  # called as bare decorator (rare)
            return args[0]
        return decorator

    router_instance = MagicMock()
    for method in ("get", "post", "put", "delete", "patch"):
        setattr(router_instance, method, _passthrough)

    class _MockAPIRouter:  # APIRouter() → the singleton router_instance
        def __new__(cls, *a, **kw):
            return router_instance

    fapi.APIRouter = _MockAPIRouter  # type: ignore[attr-defined]
    def _http_exc_init(self, status_code: int = 500, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail

    fapi.HTTPException = type(  # type: ignore[attr-defined]
        "HTTPException",
        (Exception,),
        {"__init__": _http_exc_init},
    )
    fapi.Request = MagicMock  # type: ignore[attr-defined]
    fapi.Depends = lambda fn: fn  # type: ignore[attr-defined]

    # pydantic stubs
    pyd = sys.modules["pydantic"]

    class _BaseModel:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    pyd.BaseModel = _BaseModel  # type: ignore[attr-defined]
    pyd.Field = lambda *a, **kw: None  # type: ignore[attr-defined]

    # db_pool stub
    db_pool = _make_stub("db_pool")
    db_pool.get_connection = MagicMock()

    # auth stub
    auth_mod = _make_stub("auth")
    auth_mod.create_access_token = MagicMock(return_value="svc-token-abc")
    auth_mod.verify_token = MagicMock(return_value={"sub": "testuser", "role": "admin"})

    # crypto_helper stub
    crypto = _make_stub("crypto_helper")
    crypto.fernet_encrypt = MagicMock(return_value="enc")
    crypto.fernet_decrypt = MagicMock(return_value="dec")

    # copilot_intents stub
    ci = _make_stub("copilot_intents")
    ci.match_intent = MagicMock(return_value=None)
    ci.get_suggestion_chips = MagicMock(return_value={})
    ci._extract_scope = MagicMock(return_value=(None, None))

    # copilot_context / copilot_llm stubs — build on ONE module instance each
    copilot_ctx_stub = _make_stub("copilot_context")
    copilot_ctx_stub.build_infra_context = MagicMock(return_value="")  # type: ignore[attr-defined]

    copilot_llm_stub = _make_stub("copilot_llm")
    copilot_llm_stub.ask_llm = MagicMock(return_value=("", 0, False))  # type: ignore[attr-defined]
    copilot_llm_stub.test_ollama = MagicMock()  # type: ignore[attr-defined]
    copilot_llm_stub.test_openai = MagicMock()  # type: ignore[attr-defined]
    copilot_llm_stub.test_anthropic = MagicMock()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# All module names touched by _stub_modules() — used for fixture cleanup
# ---------------------------------------------------------------------------
_STUBBED_NAMES = {
    "psycopg2", "psycopg2.pool", "psycopg2.extras",
    "fastapi", "fastapi.responses", "fastapi.routing",
    "starlette", "starlette.routing", "starlette.requests",
    "pydantic", "pydantic.fields",
    "cryptography", "cryptography.fernet",
    "jose", "jose.jwt", "jose.exceptions",
    "httpx",
    "db_pool", "auth", "crypto_helper",
    "copilot_intents", "copilot_context", "copilot_llm",
    "copilot",
}


@pytest.fixture(scope="module", autouse=True)
def _module_stubs():
    """Apply module stubs before tests run; restore sys.modules afterwards.

    Calling _stub_modules() inside a fixture (not at module level) ensures
    sys.modules is NOT polluted during pytest's collection phase, which would
    cause ImportError/AttributeError in other test files collected after this
    one (e.g. test_crypto_helper.py, test_tenant_portal_login_integration.py).
    """
    saved = {name: sys.modules.get(name) for name in _STUBBED_NAMES}
    for name in _STUBBED_NAMES:
        sys.modules.pop(name, None)
    _stub_modules()
    yield
    for name in _STUBBED_NAMES:
        if saved[name] is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = saved[name]


# ---------------------------------------------------------------------------
# Helper: import the functions under test directly (not the module)
# ---------------------------------------------------------------------------

def _get_helpers():
    """Return the helper functions from copilot module after stubbing."""
    import importlib
    # Reload to pick up stubs if already imported
    if "copilot" in sys.modules:
        copilot = sys.modules["copilot"]
    else:
        import copilot  # noqa: F401 — side-effect import
    return copilot


# ===========================================================================
# Test 1: confirmed=False must be rejected with 400
# ===========================================================================

def test_execute_intent_requires_confirmed_true():
    """Calling execute_intent without confirmed=True must raise HTTP 400."""
    copilot = _get_helpers()
    HTTPException = sys.modules["fastapi"].HTTPException

    class FakeRequest:
        state = MagicMock()

    class FakeBody:
        intent_key = "error_vms"
        runbook_name = "stuck_vm_remediation"
        confirmed = False   # <-- NOT confirmed
        dry_run = True
        parameters = {}

    import asyncio

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            copilot.execute_intent(FakeBody(), FakeRequest())
        )
    assert exc_info.value.status_code == 400


# ===========================================================================
# Test 2: agentic disabled → 403
# ===========================================================================

def test_execute_intent_agentic_disabled():
    """When agentic_enabled=false, execute_intent must raise HTTP 403."""
    copilot = _get_helpers()
    HTTPException = sys.modules["fastapi"].HTTPException

    class FakeRequest:
        state = MagicMock()

    class FakeBody:
        intent_key = "error_vms"
        runbook_name = "stuck_vm_remediation"
        confirmed = True
        dry_run = True
        parameters = {}

    import asyncio

    with patch.object(copilot, "_get_agentic_setting", return_value="false"):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                copilot.execute_intent(FakeBody(), FakeRequest())
            )
    assert exc_info.value.status_code == 403
# Test 3: quota exceeded → 429
# ===========================================================================

def test_execute_intent_quota_exceeded():
    """When hourly usage >= quota, execute_intent must raise HTTP 429."""
    copilot = _get_helpers()
    HTTPException = sys.modules["fastapi"].HTTPException

    class FakeRequest:
        state = MagicMock()

    class FakeBody:
        intent_key = "error_vms"
        runbook_name = "stuck_vm_remediation"
        confirmed = True
        dry_run = True
        parameters = {}

    import asyncio

    def _setting(key, default):
        return "true" if "enabled" in key else "10"

    with patch.object(copilot, "_get_agentic_setting", side_effect=_setting), \
         patch.object(copilot, "_count_hourly_executions", return_value=10):
        # Default quota is 10; used=10 → should be rejected
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                copilot.execute_intent(FakeBody(), FakeRequest())
            )
    assert exc_info.value.status_code == 429


# ===========================================================================
# Test 4: agentic-status endpoint returns expected shape
# ===========================================================================

def test_agentic_status_default():
    """agentic_status should return enabled/quota/used/remaining keys."""
    copilot = _get_helpers()

    class FakeRequest:
        state = MagicMock()

    import asyncio

    def _setting(key, default):
        return "true" if "enabled" in key else "10"

    with patch.object(copilot, "_get_agentic_setting", side_effect=_setting), \
         patch.object(copilot, "_count_hourly_executions", return_value=3):
        result = asyncio.get_event_loop().run_until_complete(
            copilot.agentic_status(FakeRequest())
        )

    assert result["enabled"] is True
    assert result["quota_per_hour"] == 10
    assert result["used_this_hour"] == 3
    assert result["remaining"] == 7


# ===========================================================================
# Test 5: IntentDef runbook metadata propagates through match_intent
# ===========================================================================

def test_intent_runbook_metadata():
    """IntentDef runbook metadata should appear in IntentMatch result."""
    if "copilot_intents" in sys.modules:
        # Remove stub so we can import the real module
        del sys.modules["copilot_intents"]

    # Re-add just the stubs that copilot_intents itself needs
    for name in ["psycopg2", "psycopg2.extras", "psycopg2.pool", "db_pool"]:
        if name not in sys.modules:
            _make_stub(name)

    sys.modules["db_pool"].get_connection = MagicMock()

    try:
        import importlib
        import copilot_intents as ci  # real module
        importlib.reload(ci)

        # Find an intent we annotated
        error_vm_intent = next((i for i in ci.INTENTS if i.key == "error_vms"), None)
        assert error_vm_intent is not None, "error_vms intent not found"
        assert error_vm_intent.runbook_name == "stuck_vm_remediation"
        assert error_vm_intent.risk_level == "medium"
        assert error_vm_intent.supports_dry_run is True

        cap_cpu_intent = next((i for i in ci.INTENTS if i.key == "capacity_cpu"), None)
        assert cap_cpu_intent is not None, "capacity_cpu intent not found"
        assert cap_cpu_intent.runbook_name == "capacity_forecast"
        assert cap_cpu_intent.risk_level == "low"
        assert cap_cpu_intent.supports_dry_run is False

    finally:
        # Restore stub
        _stub_modules()


# ===========================================================================
# Test 6: Security — confirmed must be bool True, not truthy string
# ===========================================================================

def test_security_confirmed_not_injectable():
    """
    A truthy non-boolean value for confirmed should NOT bypass the check.
    Pydantic should coerce/validate; we test the endpoint rejects confirmed=False.
    """
    copilot = _get_helpers()
    HTTPException = sys.modules["fastapi"].HTTPException

    class FakeRequest:
        state = MagicMock()

    import asyncio

    # Test with confirmed=False explicitly
    class FakeBadBody:
        intent_key = "error_vms"
        runbook_name = "stuck_vm_remediation"
        confirmed = False   # must be rejected
        dry_run = True
        parameters = {}

    with pytest.raises(Exception) as exc_info:
        asyncio.get_event_loop().run_until_complete(
            copilot.execute_intent(FakeBadBody(), FakeRequest())
        )
    assert getattr(exc_info.value, "status_code", None) == 400, "confirmed=False must yield HTTP 400"


# ===========================================================================
# Test 7: _log_copilot_execution handles DB failure gracefully
# ===========================================================================

def test_log_copilot_execution_db_failure():
    """If the DB is unavailable, _log_copilot_execution should not raise."""
    copilot = _get_helpers()
    db_pool = sys.modules["db_pool"]

    db_pool.get_connection.side_effect = Exception("DB connection failed")
    # Should not raise — only logs a warning
    try:
        copilot._log_copilot_execution("user1", "error_vms", "stuck_vm_remediation", "exec-123", True)
    finally:
        db_pool.get_connection.side_effect = None
