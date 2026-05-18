"""
tests/test_circuit_breaker_status.py — Unit tests for RegionCircuitBreaker.get_status()

Tests run without Redis or any real network access.
All Redis calls are patched out via the local-fallback path.

Run with:  pytest tests/test_circuit_breaker_status.py -v
"""
import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Minimal stubs so pf9_control.py can be imported without its full deps
# ---------------------------------------------------------------------------

# Ensure real `requests` is registered in sys.modules before any stub setup so
# integration tests that run later (e.g. test_health.py) still get the real module.
import requests as _real_requests  # noqa: F401 — side-effect: registers real module

# cache stub
cache_stub = types.ModuleType("cache")
cache_stub.cached = lambda ttl=60, key_prefix="": (lambda fn: fn)
cache_stub._get_client = lambda: None          # no Redis
sys.modules.setdefault("cache", cache_stub)

# secret_helper stub — returns "test-password" so any test that runs after and
# expects this value from a setdefault stub (e.g. test_cluster_registry.py) still passes.
# Circuit breaker code never calls read_secret, so the value is irrelevant here.
secret_helper_stub = types.ModuleType("secret_helper")
secret_helper_stub.read_secret = lambda name, env_var=None, default="": "test-password"
sys.modules.setdefault("secret_helper", secret_helper_stub)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from pf9_control import RegionCircuitBreaker, _get_circuit_breaker  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build a CB whose Redis access is always mocked to "None" (local mode)
# ---------------------------------------------------------------------------

def _make_cb(region_id: str = "test-region") -> RegionCircuitBreaker:
    """Return a fresh RegionCircuitBreaker that uses in-process local fallback only."""
    cb = RegionCircuitBreaker(region_id)
    return cb


class TestGetStatusClosed(unittest.TestCase):

    def test_returns_closed_state(self):
        cb = _make_cb()
        status = cb.get_status()
        self.assertEqual(status["state"], "closed")

    def test_failure_count_zero(self):
        cb = _make_cb()
        status = cb.get_status()
        self.assertEqual(status["failure_count"], 0)

    def test_open_for_seconds_remaining_none_when_closed(self):
        cb = _make_cb()
        status = cb.get_status()
        self.assertIsNone(status["open_for_seconds_remaining"])

    def test_keys_present(self):
        cb = _make_cb()
        status = cb.get_status()
        self.assertIn("state", status)
        self.assertIn("failure_count", status)
        self.assertIn("open_for_seconds_remaining", status)


class TestGetStatusOpen(unittest.TestCase):

    def _open_circuit(self, cb: RegionCircuitBreaker) -> None:
        """Force the circuit open by recording failures up to threshold."""
        for _ in range(cb.FAILURE_THRESHOLD):
            cb.record_failure()

    def test_state_open_after_threshold_failures(self):
        cb = _make_cb("open-test")
        self._open_circuit(cb)
        status = cb.get_status()
        self.assertEqual(status["state"], "open")

    def test_failure_count_at_threshold(self):
        cb = _make_cb("open-count-test")
        self._open_circuit(cb)
        status = cb.get_status()
        self.assertGreaterEqual(status["failure_count"], cb.FAILURE_THRESHOLD)

    def test_remaining_seconds_positive_when_open(self):
        cb = _make_cb("open-remaining-test")
        self._open_circuit(cb)
        status = cb.get_status()
        self.assertIsNotNone(status["open_for_seconds_remaining"])
        self.assertGreater(status["open_for_seconds_remaining"], 0)

    def test_remaining_seconds_not_exceed_recovery_timeout(self):
        cb = _make_cb("open-cap-test")
        self._open_circuit(cb)
        status = cb.get_status()
        self.assertLessEqual(
            status["open_for_seconds_remaining"],
            RegionCircuitBreaker.RECOVERY_TIMEOUT,
        )


class TestGetStatusAfterSuccess(unittest.TestCase):

    def test_closed_after_success_resets_failure_count(self):
        cb = _make_cb("reset-test")
        # Record some failures (below threshold)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        status = cb.get_status()
        self.assertEqual(status["state"], "closed")
        self.assertEqual(status["failure_count"], 0)

    def test_remaining_none_after_reset(self):
        cb = _make_cb("reset-remaining-test")
        cb.record_failure()
        cb.record_success()
        status = cb.get_status()
        self.assertIsNone(status["open_for_seconds_remaining"])


class TestGetCircuitBreakerRegistry(unittest.TestCase):

    def test_same_region_returns_same_instance(self):
        cb1 = _get_circuit_breaker("region-singleton")
        cb2 = _get_circuit_breaker("region-singleton")
        self.assertIs(cb1, cb2)

    def test_different_regions_return_different_instances(self):
        cb_a = _get_circuit_breaker("region-alpha-unique")
        cb_b = _get_circuit_breaker("region-beta-unique")
        self.assertIsNot(cb_a, cb_b)

    def test_get_status_callable_via_registry(self):
        cb = _get_circuit_breaker("registry-status-test")
        status = cb.get_status()
        self.assertIn("state", status)


if __name__ == "__main__":
    unittest.main()
