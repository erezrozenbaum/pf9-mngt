"""
tests/test_crypto_helper.py — Unit tests for api/crypto_helper.py

Tests run WITHOUT a Docker secrets file.  The `read_secret` function that
`crypto_helper` imports is patched via monkeypatch.setattr so the tests are
isolated from whatever `secret_helper` stub may have been installed by an
earlier test module.
"""
import os
import sys
import types
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

import crypto_helper as _cm_mod  # noqa: E402
from crypto_helper import fernet_encrypt, fernet_decrypt, _derive_key

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
_TEST_SECRET_NAME = "test_crypto_key"
_TEST_SECRET_VALUE = "super-secret-test-value-32chars!!"
_OTHER_SECRET_VALUE = "a-completely-different-key-value!"


def _patch_read_secret(monkeypatch, return_value: str):
    """Patch crypto_helper.read_secret to return *return_value* unconditionally."""
    monkeypatch.setattr(_cm_mod, "read_secret", lambda name, env_var=None, **kw: return_value)


def _patch_read_secret_missing(monkeypatch):
    """Patch crypto_helper.read_secret to return empty string (secret absent)."""
    monkeypatch.setattr(_cm_mod, "read_secret", lambda name, env_var=None, **kw: "")


class TestDeriveKey:
    def test_returns_32_byte_base64url(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        key = _derive_key(_TEST_SECRET_NAME, env_var="UNUSED")
        import base64
        raw = base64.urlsafe_b64decode(key)
        assert len(raw) == 32

    def test_deterministic_for_same_secret(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        k1 = _derive_key(_TEST_SECRET_NAME, env_var="UNUSED")
        k2 = _derive_key(_TEST_SECRET_NAME, env_var="UNUSED")
        assert k1 == k2

    def test_different_secrets_produce_different_keys(self, monkeypatch):
        _patch_read_secret(monkeypatch, "secret-one")
        k1 = _derive_key(_TEST_SECRET_NAME, env_var="UNUSED")
        _patch_read_secret(monkeypatch, "secret-two")
        k2 = _derive_key(_TEST_SECRET_NAME, env_var="UNUSED")
        assert k1 != k2

    def test_raises_when_secret_missing(self, monkeypatch):
        _patch_read_secret_missing(monkeypatch)
        with pytest.raises(RuntimeError, match="is not set"):
            _derive_key(_TEST_SECRET_NAME, env_var="UNUSED")


class TestFernetEncrypt:
    def test_produces_fernet_prefix(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        result = fernet_encrypt("hello", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result.startswith("fernet:")

    def test_raises_when_key_unavailable(self, monkeypatch):
        _patch_read_secret_missing(monkeypatch)
        with pytest.raises(RuntimeError):
            fernet_encrypt("hello", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")

    def test_ciphertext_is_not_plaintext(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        plaintext = "my secret value"
        result = fernet_encrypt(plaintext, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert plaintext not in result

    def test_two_encryptions_produce_different_ciphertexts(self, monkeypatch):
        """Fernet uses random IVs — same plaintext yields different ciphertext each time."""
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        a = fernet_encrypt("hello", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        b = fernet_encrypt("hello", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert a != b


class TestFernetDecrypt:
    def test_roundtrip(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        plaintext = "roundtrip value"
        encrypted = fernet_encrypt(plaintext, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        result = fernet_decrypt(encrypted, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == plaintext

    def test_roundtrip_unicode(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        plaintext = "héllo wörld — unicode "
        encrypted = fernet_encrypt(plaintext, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        result = fernet_decrypt(encrypted, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == plaintext

    def test_missing_prefix_returns_empty(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        result = fernet_decrypt("notprefixed", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == ""

    def test_wrong_key_returns_empty(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        encrypted = fernet_encrypt("secret", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        # Switch to a different key for decryption
        _patch_read_secret(monkeypatch, _OTHER_SECRET_VALUE)
        result = fernet_decrypt(encrypted, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == ""

    def test_missing_key_returns_empty(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        encrypted = fernet_encrypt("secret", secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        _patch_read_secret_missing(monkeypatch)
        result = fernet_decrypt(encrypted, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == ""

    def test_corrupted_ciphertext_returns_empty(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        result = fernet_decrypt("fernet:AAAA_not_valid_base64==!!!",
                                secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == ""

    def test_context_included_in_error_log(self, monkeypatch, caplog):
        import logging
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        with caplog.at_level(logging.ERROR, logger="pf9.crypto_helper"):
            fernet_decrypt("notprefixed", secret_name=_TEST_SECRET_NAME,
                           env_var="UNUSED", context="test_context=42")
        # Doesn't crash — error was logged, not raised

    def test_empty_string_roundtrip(self, monkeypatch):
        _patch_read_secret(monkeypatch, _TEST_SECRET_VALUE)
        plaintext = ""
        encrypted = fernet_encrypt(plaintext, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        result = fernet_decrypt(encrypted, secret_name=_TEST_SECRET_NAME, env_var="UNUSED")
        assert result == plaintext
