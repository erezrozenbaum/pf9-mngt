"""
tests/test_backup_worker.py — Unit tests for backup_worker/main.py

No live DB, NFS, or subprocess calls required.  Psycopg2 is mocked.
"""
import datetime
import os
import sys
import types
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Path setup — backup_worker/ lives outside api/
# ---------------------------------------------------------------------------
_BW_DIR = os.path.join(os.path.dirname(__file__), "..", "backup_worker")
if _BW_DIR not in sys.path:
    sys.path.insert(0, _BW_DIR)

# Stub psycopg2 before importing the module
_psycopg2_stub = types.ModuleType("psycopg2")
_psycopg2_stub.connect = MagicMock(side_effect=RuntimeError("no DB in tests"))
_psycopg2_extras_stub = types.ModuleType("psycopg2.extras")
_psycopg2_extras_stub.RealDictCursor = MagicMock
sys.modules.setdefault("psycopg2", _psycopg2_stub)
sys.modules["psycopg2.extras"] = _psycopg2_extras_stub

import main as _bw  # noqa: E402  (backup_worker/main.py)


# ---------------------------------------------------------------------------
# Tests: _read_secret
# ---------------------------------------------------------------------------
class TestReadSecret:
    def test_returns_env_var_when_no_secret_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TEST_BW_SECRET", "env-value")
        result = _bw._read_secret("nonexistent_secret", env_var="TEST_BW_SECRET")
        assert result == "env-value"

    def test_returns_default_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("TEST_BW_SECRET", raising=False)
        result = _bw._read_secret("nonexistent_secret", env_var="TEST_BW_SECRET",
                                  default="fallback")
        assert result == "fallback"

    def test_returns_empty_string_as_default_default(self, monkeypatch):
        monkeypatch.delenv("TEST_BW_SECRET", raising=False)
        result = _bw._read_secret("nonexistent_secret", env_var="TEST_BW_SECRET")
        assert result == ""

    def test_reads_secret_file_when_present(self, tmp_path, monkeypatch):
        secret_file = tmp_path / "my_secret"
        secret_file.write_text("  file-secret-value  \n")
        # Override the secrets search path by patching os.path.isfile and open
        real_isfile = os.path.isfile
        def _fake_isfile(path):
            if "my_secret" in path and "run" in path:
                return True
            return real_isfile(path)
        real_open = open
        def _fake_open(path, *a, **kw):
            if "my_secret" in path and "run" in path:
                return real_open(str(secret_file), *a, **kw)
            return real_open(path, *a, **kw)
        monkeypatch.setattr(os.path, "isfile", _fake_isfile)
        monkeypatch.setenv("TEST_BW_SECRET", "env-value-should-be-ignored")
        with patch("builtins.open", side_effect=_fake_open):
            result = _bw._read_secret("my_secret", env_var="TEST_BW_SECRET")
        assert result == "file-secret-value"


# ---------------------------------------------------------------------------
# Tests: _ALLOWED_JOB_FIELDS and _update_job allowlist
# ---------------------------------------------------------------------------
class TestUpdateJobAllowlist:
    def test_allowed_fields_frozenset_is_defined(self):
        assert hasattr(_bw, "_ALLOWED_JOB_FIELDS")
        assert isinstance(_bw._ALLOWED_JOB_FIELDS, frozenset)

    def test_allowed_fields_contains_expected_entries(self):
        expected = {"status", "started_at", "completed_at", "file_name",
                    "file_path", "file_size_bytes", "duration_seconds",
                    "error_message", "notes"}
        assert expected.issubset(_bw._ALLOWED_JOB_FIELDS)

    def test_update_job_raises_on_unknown_field(self):
        fake_conn = MagicMock()
        with pytest.raises(ValueError, match="unknown field"):
            _bw._update_job(fake_conn, 1, status="running",
                            injected_column="DROP TABLE backup_history")

    def test_update_job_raises_on_multiple_unknown_fields(self):
        fake_conn = MagicMock()
        with pytest.raises(ValueError, match="unknown field"):
            _bw._update_job(fake_conn, 1, bad_field="x", another_bad="y")

    def test_update_job_succeeds_with_known_fields(self):
        fake_conn = MagicMock()
        fake_cur = MagicMock()
        fake_conn.cursor.return_value.__enter__ = lambda s: fake_cur
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        # Should not raise
        _bw._update_job(fake_conn, 42, status="completed",
                        duration_seconds=12.5)
        fake_cur.execute.assert_called_once()
        fake_conn.commit.assert_called_once()

    def test_update_job_sql_uses_placeholders_not_f_string_values(self):
        """Verify parameterised SQL — values must not appear in the SQL string."""
        fake_conn = MagicMock()
        fake_cur = MagicMock()
        fake_conn.cursor.return_value.__enter__ = lambda s: fake_cur
        fake_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        _bw._update_job(fake_conn, 99, status="malicious'; DROP TABLE backup_history;--",
                        error_message="test")
        sql_arg = fake_cur.execute.call_args[0][0]
        params = fake_cur.execute.call_args[0][1]
        assert "malicious" not in sql_arg                            # value is not in SQL
        assert any("malicious" in str(p) for p in params)           # value is in params


# ---------------------------------------------------------------------------
# Tests: _check_storage_health
# ---------------------------------------------------------------------------
class TestCheckStorageHealth:
    def test_returns_true_when_backup_path_writable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_bw, "BACKUP_PATH", str(tmp_path))
        assert _bw._check_storage_health() is True

    def test_cleans_up_probe_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_bw, "BACKUP_PATH", str(tmp_path))
        _bw._check_storage_health()
        probe = tmp_path / ".backup_worker_probe"
        assert not probe.exists()

    def test_returns_false_when_path_not_writable(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_bw, "BACKUP_PATH", str(tmp_path))
        # Make the directory read-only
        original_open = open
        def _fail_open(path, *a, **kw):
            if ".backup_worker_probe" in str(path):
                raise PermissionError("read-only filesystem")
            return original_open(path, *a, **kw)
        with patch("builtins.open", side_effect=_fail_open):
            assert _bw._check_storage_health() is False

    def test_ldap_admin_password_not_via_plain_os_getenv(self):
        """LDAP_ADMIN_PASSWORD must be fetched via _read_secret, not os.getenv."""
        import inspect
        src = inspect.getsource(_bw)
        assert '_read_secret("ldap_admin_password"' in src
        # raw os.getenv("LDAP_ADMIN_PASSWORD") must NOT appear
        assert 'os.getenv("LDAP_ADMIN_PASSWORD"' not in src


# ---------------------------------------------------------------------------
# Tests: _touch_alive (liveness probe)
# ---------------------------------------------------------------------------
class TestTouchAlive:
    def test_writes_heartbeat_file(self, tmp_path, monkeypatch):
        probe_path = str(tmp_path / "alive")
        monkeypatch.setattr(_bw, "_ALIVE_FILE", probe_path)
        _bw._touch_alive()
        assert os.path.isfile(probe_path)

    def test_does_not_raise_on_write_failure(self, monkeypatch):
        monkeypatch.setattr(_bw, "_ALIVE_FILE", "/nonexistent_dir/alive")
        # Should not raise
        _bw._touch_alive()
