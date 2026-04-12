"""Shared SlowAPI rate-limiter instance.

Imported by api/main.py and any router module that needs request-rate limiting.
The key function delegates to get_request_ip (X-Real-IP preferred, set by nginx
to $remote_addr) so clients cannot spoof their rate-limit bucket via headers.
"""
from slowapi import Limiter
from request_helpers import get_request_ip

limiter = Limiter(key_func=get_request_ip)
