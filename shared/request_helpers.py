"""
shared/request_helpers.py — HTTP request utilities shared by all pf9-mngt services.

Single source of truth for request introspection helpers.

Usage:
    from shared.request_helpers import get_request_ip
"""

from fastapi import Request


def get_request_ip(request: Request) -> str:
    """
    Return the real client IP address for the given request.

    Priority:
      1. X-Real-IP header (set by nginx to $remote_addr — cannot be spoofed
         by the client because nginx overwrites it unconditionally).
      2. TCP peer address (request.client.host) — used in development / direct
         connections where nginx is not in front.
      3. "127.0.0.1" — safe fallback when neither source is available.
    """
    return (
        request.headers.get("X-Real-IP")
        or (request.client.host if request.client else "127.0.0.1")
    )
