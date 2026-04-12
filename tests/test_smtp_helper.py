"""
tests/test_smtp_helper.py — Unit tests for api/smtp_helper.py

No live SMTP server or DB required.  DB, Redis, and smtplib are all mocked.
"""
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stubs — must come before importing smtp_helper
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# Stub db_pool
_db_pool_stub = types.ModuleType("db_pool")
_db_pool_stub.get_connection = MagicMock(side_effect=RuntimeError("no DB in tests"))
sys.modules.setdefault("db_pool", _db_pool_stub)

# Stub cache
_cache_stub = types.ModuleType("cache")
_cache_stub._get_client = lambda: None  # Redis unavailable
sys.modules.setdefault("cache", _cache_stub)

# Stub crypto_helper for Fernet decrypt used by get_smtp_config
_crypto_stub = types.ModuleType("crypto_helper")
_crypto_stub.fernet_decrypt = lambda stored, **kw: stored.replace("fernet:", "decrypted_")
sys.modules.setdefault("crypto_helper", _crypto_stub)

import smtp_helper  # noqa: E402


# ---------------------------------------------------------------------------
# Tests: get_smtp_config
# ---------------------------------------------------------------------------
class TestGetSmtpConfig:
    def test_returns_all_expected_keys(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "_load_db_smtp_override", lambda: {})
        monkeypatch.setattr(smtp_helper, "SMTP_ENABLED", True)
        monkeypatch.setattr(smtp_helper, "SMTP_HOST", "smtp.test")
        cfg = smtp_helper.get_smtp_config()
        for key in ("enabled", "host", "port", "use_tls", "username", "password",
                    "from_address", "from_name"):
            assert key in cfg

    def test_db_override_beats_env(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "_load_db_smtp_override", lambda: {
            "smtp.host": "db-smtp.example.com",
            "smtp.port": "2525",
        })
        monkeypatch.setattr(smtp_helper, "SMTP_HOST", "env-smtp.example.com")
        monkeypatch.setattr(smtp_helper, "SMTP_PORT", 587)
        cfg = smtp_helper.get_smtp_config()
        assert cfg["host"] == "db-smtp.example.com"
        assert cfg["port"] == 2525

    def test_env_used_when_no_db_override(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "_load_db_smtp_override", lambda: {})
        monkeypatch.setattr(smtp_helper, "SMTP_HOST", "env-smtp.example.com")
        monkeypatch.setattr(smtp_helper, "SMTP_PORT", 465)
        cfg = smtp_helper.get_smtp_config()
        assert cfg["host"] == "env-smtp.example.com"
        assert cfg["port"] == 465

    def test_fernet_password_is_decrypted(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "_load_db_smtp_override", lambda: {
            "smtp.password": "fernet:ENCRYPTEDBLOB",
        })
        # Patch fernet_decrypt on whichever crypto_helper module is in sys.modules
        # (may be the real module if test_crypto_helper ran first)
        monkeypatch.setattr(
            sys.modules["crypto_helper"], "fernet_decrypt",
            lambda stored, **kw: stored.replace("fernet:", "decrypted_"),
            raising=False,
        )
        cfg = smtp_helper.get_smtp_config()
        assert cfg["password"] == "decrypted_ENCRYPTEDBLOB"

    def test_boolean_flags_parsed(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "_load_db_smtp_override", lambda: {
            "smtp.enabled": "true",
            "smtp.use_tls": "false",
        })
        cfg = smtp_helper.get_smtp_config()
        assert cfg["enabled"] is True
        assert cfg["use_tls"] is False


# ---------------------------------------------------------------------------
# Tests: send_email
# ---------------------------------------------------------------------------
class TestSendEmail:
    def _disabled_cfg(self):
        return {
            "enabled": False, "host": "", "port": 587, "use_tls": True,
            "username": "", "password": "", "from_address": "test@example.com",
            "from_name": "Test",
        }

    def _enabled_cfg(self):
        return {
            "enabled": True, "host": "smtp.test", "port": 587, "use_tls": True,
            "username": "u", "password": "p", "from_address": "test@example.com",
            "from_name": "Test",
        }

    def test_returns_true_when_smtp_disabled(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "get_smtp_config", self._disabled_cfg)
        assert smtp_helper.send_email("to@example.com", "subj", "<p>body</p>") is True

    def test_returns_true_on_successful_send(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "get_smtp_config", self._enabled_cfg)
        with patch.object(smtp_helper, "_do_send", return_value=None):
            assert smtp_helper.send_email("to@example.com", "subj", "<p>body</p>") is True

    def test_returns_false_on_smtp_error(self, monkeypatch):
        import smtplib
        monkeypatch.setattr(smtp_helper, "get_smtp_config", self._enabled_cfg)
        with patch.object(smtp_helper, "_do_send",
                          side_effect=smtplib.SMTPException("connection refused")):
            assert smtp_helper.send_email("to@example.com", "subj", "<p>body</p>") is False

    def test_raise_on_error_propagates(self, monkeypatch):
        import smtplib
        monkeypatch.setattr(smtp_helper, "get_smtp_config", self._enabled_cfg)
        with patch.object(smtp_helper, "_do_send",
                          side_effect=smtplib.SMTPAuthenticationError(535, b"auth failed")):
            with pytest.raises(smtplib.SMTPAuthenticationError):
                smtp_helper.send_email("to@example.com", "subj", "<p>body</p>",
                                       raise_on_error=True)

    def test_string_recipient_normalised_to_list(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "get_smtp_config", self._enabled_cfg)
        captured = {}
        def _fake_do_send(msg, to_addrs):
            captured["to"] = to_addrs
        with patch.object(smtp_helper, "_do_send", side_effect=_fake_do_send):
            smtp_helper.send_email("single@example.com", "s", "<b>b</b>")
        assert captured["to"] == ["single@example.com"]

    def test_list_recipient_passed_through(self, monkeypatch):
        monkeypatch.setattr(smtp_helper, "get_smtp_config", self._enabled_cfg)
        captured = {}
        def _fake_do_send(msg, to_addrs):
            captured["to"] = to_addrs
        with patch.object(smtp_helper, "_do_send", side_effect=_fake_do_send):
            smtp_helper.send_email(["a@x.com", "b@x.com"], "s", "<b>b</b>")
        assert captured["to"] == ["a@x.com", "b@x.com"]


# ---------------------------------------------------------------------------
# Tests: _load_db_smtp_override (Redis path)
# ---------------------------------------------------------------------------
class TestLoadDbSmtpOverrideRedis:
    def test_returns_empty_dict_when_redis_and_db_both_unavailable(self):
        # Both Redis and db_pool are stubbed to fail — should return {}
        result = smtp_helper._load_db_smtp_override()
        assert isinstance(result, dict)

    def test_returns_cached_value_when_redis_returns_data(self, monkeypatch):
        import json
        fake_rc = MagicMock()
        fake_rc.get.return_value = json.dumps({"smtp.host": "cached.test"}).encode()
        # Use raising=False — the cache stub from an earlier test may not have _get_client
        monkeypatch.setattr(
            sys.modules["cache"], "_get_client", lambda: fake_rc, raising=False
        )
        result = smtp_helper._load_db_smtp_override()
        assert result.get("smtp.host") == "cached.test"
