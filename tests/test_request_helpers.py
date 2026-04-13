"""
tests/test_request_helpers.py — Unit tests for api/request_helpers.py
"""
import os
import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# Evict any stub registered by an earlier test file (e.g. test_rbac_middleware.py
# registers a minimal request_helpers stub so auth.py can be imported).
sys.modules.pop("request_helpers", None)

from request_helpers import get_request_ip  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — build minimal fake Request objects
# ---------------------------------------------------------------------------
def _make_request(x_real_ip=None, client_host=None):
    """Build a minimal mock Request with the given header and client host."""
    headers = {}
    if x_real_ip is not None:
        headers["X-Real-IP"] = x_real_ip
    req = MagicMock()
    req.headers.get = lambda key, default=None: headers.get(key, default)
    req.client = MagicMock()
    req.client.host = client_host
    return req


def _make_request_no_client(x_real_ip=None):
    """Request with no client attribute (e.g. test-client edge case)."""
    req = _make_request(x_real_ip=x_real_ip, client_host=None)
    req.client = None
    return req


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestGetRequestIp:
    def test_x_real_ip_header_takes_priority(self):
        req = _make_request(x_real_ip="10.0.0.1", client_host="192.168.1.1")
        assert get_request_ip(req) == "10.0.0.1"

    def test_falls_back_to_client_host_when_header_absent(self):
        req = _make_request(x_real_ip=None, client_host="192.168.1.50")
        assert get_request_ip(req) == "192.168.1.50"

    def test_falls_back_to_loopback_when_no_client_and_no_header(self):
        req = _make_request_no_client()
        assert get_request_ip(req) == "127.0.0.1"

    def test_falls_back_to_loopback_when_header_empty_and_no_client(self):
        req = _make_request_no_client(x_real_ip="")
        # empty string is falsy — should still produce default
        assert get_request_ip(req) == "127.0.0.1"

    def test_x_real_ip_beats_client_host_ipv6(self):
        req = _make_request(x_real_ip="2001:db8::1", client_host="::1")
        assert get_request_ip(req) == "2001:db8::1"

    def test_returns_string(self):
        req = _make_request(x_real_ip="1.2.3.4")
        result = get_request_ip(req)
        assert isinstance(result, str)
