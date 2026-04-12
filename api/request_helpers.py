"""
api/request_helpers.py — Shared HTTP request utilities.

Exported
--------
get_request_ip(request) -> str
    Return the real client IP, preferring X-Real-IP (set by nginx to
    $remote_addr, not client-spoofable) over the TCP peer address.
    Used by both the rate limiter and audit logging.
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
