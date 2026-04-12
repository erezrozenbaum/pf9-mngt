"""
tests/test_restore_management.py — Unit tests for api/restore_management.py

Tests the parts that don't require a live OpenStack or DB.
Heavy imports are stubbed so the module loads in isolation.
"""
import base64
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stubs — must precede the import
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# Stub psycopg2
_psycopg2_stub = types.ModuleType("psycopg2")
_psycopg2_stub.connect = MagicMock(side_effect=RuntimeError("no DB in tests"))
_psycopg2_extras_stub = types.ModuleType("psycopg2.extras")
_psycopg2_extras_stub.RealDictCursor = MagicMock
_psycopg2_extras_stub.Json = MagicMock
sys.modules.setdefault("psycopg2", _psycopg2_stub)
sys.modules["psycopg2.extras"] = _psycopg2_extras_stub

# Stub requests (http_requests in restore_management)
_requests_stub = types.ModuleType("requests")
_requests_stub.get = MagicMock(side_effect=RuntimeError("no HTTP in tests"))
_requests_stub.post = MagicMock(side_effect=RuntimeError("no HTTP in tests"))
_requests_stub.exceptions = types.SimpleNamespace(
    RequestException=Exception,
    ConnectionError=Exception,
    Timeout=Exception,
)
sys.modules.setdefault("requests", _requests_stub)

# Stub fastapi
_fastapi_stub = types.ModuleType("fastapi")
class _FakeHTTPException(Exception):
    def __init__(self, status_code=500, detail=""):
        self.status_code = status_code
        self.detail = detail
_fastapi_stub.HTTPException = _FakeHTTPException
_fastapi_stub.Depends = lambda fn: fn
_fastapi_stub.APIRouter = MagicMock(return_value=MagicMock())
_fastapi_stub.Request = MagicMock
_fastapi_stub.status = types.SimpleNamespace(HTTP_404_NOT_FOUND=404, HTTP_400_BAD_REQUEST=400)
sys.modules.setdefault("fastapi", _fastapi_stub)

# Stub pydantic
_pydantic_stub = types.ModuleType("pydantic")
class _BaseModel:
    pass
_pydantic_stub.BaseModel = _BaseModel
_pydantic_stub.Field = lambda *a, **kw: None
sys.modules.setdefault("pydantic", _pydantic_stub)

# Stub auth — force-set to override any stub installed by an earlier test module
# (test_cluster_routes.py registers an incomplete auth stub via setdefault)
_auth_stub = types.ModuleType("auth")
_auth_stub.require_permission = MagicMock()
_auth_stub.get_current_user = MagicMock()
_auth_stub.User = MagicMock
_auth_stub.require_authentication = MagicMock()
_auth_stub.has_permission = MagicMock(return_value=True)
_auth_stub.log_auth_event = MagicMock()
sys.modules["auth"] = _auth_stub

# Stub db_pool
_db_pool_stub = types.ModuleType("db_pool")
_db_pool_stub.get_connection = MagicMock(side_effect=RuntimeError("no DB in tests"))
sys.modules.setdefault("db_pool", _db_pool_stub)

# Import module under test
import restore_management as _rm  # noqa: E402


# ---------------------------------------------------------------------------
# Tests: read_secret is used for PF9_PASSWORD
# ---------------------------------------------------------------------------
class TestPf9PasswordUsesReadSecret:
    def test_pf9_password_sourced_from_env_via_read_secret(self, monkeypatch):
        """PF9_PASSWORD must be fetched via read_secret(), not os.getenv() directly."""
        monkeypatch.setenv("PF9_PASSWORD", "my-test-openstack-password")
        # Re-import with the env var set to verify read_secret works
        import importlib
        monkeypatch.delenv("PF9_PASSWORD", raising=False)
        monkeypatch.setenv("PF9_PASSWORD", "env-password")
        # The module-level PF9_PASSWORD was already set at import time.
        # This test verifies the module uses read_secret (not os.getenv) by
        # checking that the secret_helper.read_secret function is called.
        # We inspect the source to confirm read_secret is used:
        import inspect
        src = inspect.getsource(_rm)
        assert "read_secret" in src
        assert 'os.getenv("PF9_PASSWORD"' not in src
        assert 'os.getenv(\'PF9_PASSWORD\'' not in src


# ---------------------------------------------------------------------------
# Tests: _resolve_service_user_password
# ---------------------------------------------------------------------------
class TestResolveServiceUserPassword:
    def test_returns_plaintext_when_set(self, monkeypatch):
        monkeypatch.setenv("SNAPSHOT_SERVICE_USER_PASSWORD", "plaintext-pw")
        monkeypatch.delenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED", raising=False)
        result = _rm._resolve_service_user_password()
        assert result == "plaintext-pw"

    def test_returns_empty_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("SNAPSHOT_SERVICE_USER_PASSWORD", raising=False)
        monkeypatch.delenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED", raising=False)
        monkeypatch.delenv("SNAPSHOT_PASSWORD_KEY", raising=False)
        result = _rm._resolve_service_user_password()
        assert result == ""

    def test_decrypts_fernet_when_encrypted_and_key_set(self, monkeypatch):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        f = Fernet(key)
        plaintext = "decrypted-service-pw"
        encrypted = f.encrypt(plaintext.encode()).decode()
        monkeypatch.delenv("SNAPSHOT_SERVICE_USER_PASSWORD", raising=False)
        monkeypatch.setenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED", encrypted)
        monkeypatch.setenv("SNAPSHOT_PASSWORD_KEY", key.decode())
        result = _rm._resolve_service_user_password()
        assert result == plaintext

    def test_returns_empty_on_invalid_encryption(self, monkeypatch):
        monkeypatch.delenv("SNAPSHOT_SERVICE_USER_PASSWORD", raising=False)
        monkeypatch.setenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED", "bad-ciphertext")
        monkeypatch.setenv("SNAPSHOT_PASSWORD_KEY", "bad-key")
        result = _rm._resolve_service_user_password()
        assert result == ""

    def test_plaintext_takes_priority_over_encrypted(self, monkeypatch):
        """Plaintext env var should win even if encrypted vars are also set."""
        monkeypatch.setenv("SNAPSHOT_SERVICE_USER_PASSWORD", "wins")
        monkeypatch.setenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED", "some-blob")
        monkeypatch.setenv("SNAPSHOT_PASSWORD_KEY", "some-key")
        result = _rm._resolve_service_user_password()
        assert result == "wins"
