"""
api/crypto_helper.py — Shared Fernet encrypt/decrypt for secrets at rest.

Storage convention:  "fernet:<url-safe-base64-ciphertext>"

Key derivation
--------------
  key = base64url(SHA-256(raw_secret_bytes))

The raw secret is read from a named Docker secret file (or env var fallback).
Callers pass the secret_name so different keys can be used for different
domains (e.g. ldap_sync_key vs jwt_secret), limiting blast radius if one key
is rotated independently.

Usage
-----
    from crypto_helper import fernet_encrypt, fernet_decrypt

    enc = fernet_encrypt("s3cr3t!", secret_name="ldap_sync_key",
                         env_var="LDAP_SYNC_KEY")
    # stores as:  "fernet:gAAAAA..."

    plain = fernet_decrypt("fernet:gAAAAA...", secret_name="ldap_sync_key",
                           env_var="LDAP_SYNC_KEY", context="config_id=42")
    # returns:  "s3cr3t!"

Exceptions
----------
- Returns "" (empty string) on decryption failure — never raises, to avoid
  crashing callers in auth hot paths.  Errors are always logged.
- fernet_encrypt raises RuntimeError if the key secret is unavailable.
"""

import base64
import hashlib
import logging
import os

from secret_helper import read_secret

logger = logging.getLogger("pf9.crypto_helper")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _derive_key(secret_name: str, env_var: str) -> bytes:
    """
    Derive a 32-byte Fernet-compatible key from a named secret.

    Key = base64url(SHA-256(secret.encode("utf-8")))

    Raises RuntimeError if neither the secret file nor the env var is set.
    """
    raw = read_secret(secret_name, env_var=env_var)
    if not raw:
        raise RuntimeError(
            f"crypto_helper: secret '{secret_name}' / env var '{env_var}' is not set. "
            "Cannot derive encryption key."
        )
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fernet_encrypt(
    plaintext: str,
    *,
    secret_name: str,
    env_var: str,
) -> str:
    """
    Encrypt *plaintext* and return a "fernet:<ciphertext>" string.

    Parameters
    ----------
    plaintext   : value to encrypt
    secret_name : Docker secret name (file under /run/secrets/)
    env_var     : environment-variable fallback name

    Returns
    -------
    str — "fernet:<url-safe-base64-ciphertext>"

    Raises
    ------
    RuntimeError  — key secret is unavailable
    """
    from cryptography.fernet import Fernet

    key = _derive_key(secret_name, env_var)
    ciphertext = Fernet(key).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return f"fernet:{ciphertext}"


def fernet_decrypt(
    stored: str,
    *,
    secret_name: str,
    env_var: str,
    context: str = "",
) -> str:
    """
    Decrypt a "fernet:<ciphertext>" string and return the plaintext.

    Parameters
    ----------
    stored      : the full stored string, including "fernet:" prefix
    secret_name : Docker secret name
    env_var     : environment-variable fallback name
    context     : optional string added to error log messages (e.g. "config_id=42")

    Returns
    -------
    str — decrypted plaintext, or "" on any failure (errors are logged).
    """
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        logger.error(
            "crypto_helper: 'cryptography' package not installed. "
            "Install it with:  pip install cryptography"
        )
        return ""

    if not stored.startswith("fernet:"):
        logger.error(
            "crypto_helper: stored value does not have 'fernet:' prefix%s",
            f" ({context})" if context else "",
        )
        return ""

    blob = stored[7:]  # strip "fernet:"
    try:
        key = _derive_key(secret_name, env_var)
        return Fernet(key).decrypt(blob.encode("ascii")).decode("utf-8")
    except RuntimeError as exc:
        logger.error("crypto_helper: key unavailable%s: %s",
                     f" ({context})" if context else "", exc)
        return ""
    except InvalidToken:
        logger.error(
            "crypto_helper: decryption failed — token is invalid or key has changed%s. "
            "Re-encrypt the value if the secret was rotated.",
            f" ({context})" if context else "",
        )
        return ""
    except Exception as exc:
        logger.error("crypto_helper: unexpected decryption error%s: %s",
                     f" ({context})" if context else "", exc)
        return ""
