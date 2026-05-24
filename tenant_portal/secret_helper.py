"""
tenant_portal/secret_helper.py — Backward-compatible re-export.

The implementation lives in shared/secret_helper.py (single source of truth).
Existing code that does `from secret_helper import read_secret`
continues to work without modification.

DO NOT add logic here — edit shared/secret_helper.py instead.
"""

from shared.secret_helper import read_secret  # noqa: F401
