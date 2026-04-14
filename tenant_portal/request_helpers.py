"""request_helpers.py — Shared HTTP request utilities for the tenant portal."""

from fastapi import Request


def get_request_ip(request: Request) -> str:
    """
    Return the real client IP (X-Real-IP set by nginx, or TCP peer, or fallback).
    """
    return (
        request.headers.get("X-Real-IP")
        or (request.client.host if request.client else "127.0.0.1")
    )
