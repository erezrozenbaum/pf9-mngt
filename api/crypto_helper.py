"""
api/crypto_helper.py — Backward-compatible re-export.

The implementation lives in shared/crypto_helper.py (single source of truth).
Existing code that does `from crypto_helper import fernet_encrypt, fernet_decrypt`
continues to work without modification.

DO NOT add logic here — edit shared/crypto_helper.py instead.
"""

from shared.crypto_helper import (  # noqa: F401
    fernet_encrypt,
    fernet_decrypt,
    _derive_key,
)
