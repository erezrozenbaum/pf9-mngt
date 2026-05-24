"""
tenant_portal/request_helpers.py — Backward-compatible re-export.

The implementation lives in shared/request_helpers.py (single source of truth).
Existing code that does `from request_helpers import get_request_ip`
continues to work without modification.

DO NOT add logic here — edit shared/request_helpers.py instead.
"""

from shared.request_helpers import get_request_ip  # noqa: F401
