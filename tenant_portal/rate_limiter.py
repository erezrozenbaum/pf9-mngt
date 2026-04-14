"""rate_limiter.py — Shared SlowAPI limiter for the tenant portal."""

from slowapi import Limiter

from request_helpers import get_request_ip

limiter = Limiter(key_func=get_request_ip)
