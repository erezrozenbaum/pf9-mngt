"""
tests/test_container_alerts.py — Container Alert Settings tests.

Integration tests require a live stack + superadmin credentials:
  TEST_API_URL=http://localhost:8000 \\
  TEST_SUPERADMIN_USER=superadmin \\
  TEST_SUPERADMIN_PASSWORD=<password> \\
  TEST_ADMIN_USER=admin \\
  TEST_ADMIN_PASSWORD=<password> \\
  pytest tests/test_container_alerts.py -v

Unit tests for the container watchdog logic run without a live stack.
"""

import os
import json
import time
import types
import unittest.mock as mock

import pytest
import requests

API_URL = os.getenv("TEST_API_URL", "http://localhost:8000")
SUPERADMIN_USER = os.getenv("TEST_SUPERADMIN_USER", "")
SUPERADMIN_PASS = os.getenv("TEST_SUPERADMIN_PASSWORD", "")
ADMIN_USER = os.getenv("TEST_ADMIN_USER", "")
ADMIN_PASS = os.getenv("TEST_ADMIN_PASSWORD", "")
VERIFY_SSL = os.getenv("TEST_VERIFY_SSL", "false").lower() != "false"


def _login(username, password):
    r = requests.post(
        f"{API_URL}/auth/login",
        json={"username": username, "password": password},
        verify=VERIFY_SSL,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unit tests — watchdog health evaluation (no live stack needed)
# ---------------------------------------------------------------------------

class TestWatchdogHealthEvaluation:
    """Unit tests for _is_unhealthy() helper in container_watchdog."""

    def _load_fn(self):
        """Import _is_unhealthy without triggering docker or network calls."""
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "container_watchdog",
            pathlib.Path(__file__).parent.parent / "monitoring" / "container_watchdog.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._is_unhealthy

    def test_exited_nonzero_is_unhealthy(self):
        fn = self._load_fn()
        c = {"State": "exited", "Status": "Exited (1) 2 minutes ago"}
        reason = fn(c)
        assert reason is not None
        assert "1" in reason

    def test_exited_zero_is_healthy(self):
        fn = self._load_fn()
        c = {"State": "exited", "Status": "Exited (0) 5 seconds ago"}
        assert fn(c) is None

    def test_running_healthy_is_healthy(self):
        fn = self._load_fn()
        c = {"State": "running", "Status": "Up 3 hours"}
        assert fn(c) is None

    def test_unhealthy_status_string(self):
        fn = self._load_fn()
        c = {"State": "running", "Status": "Up 12 minutes (unhealthy)"}
        reason = fn(c)
        assert reason is not None
        assert "unhealthy" in reason.lower()

    def test_exited_137_is_unhealthy(self):
        """Exit code 137 = OOM kill — should trigger an alert."""
        fn = self._load_fn()
        c = {"State": "exited", "Status": "Exited (137) 1 second ago"}
        reason = fn(c)
        assert reason is not None
        assert "137" in reason

    def test_paused_container_is_healthy(self):
        """Paused is not exited — no alert expected."""
        fn = self._load_fn()
        c = {"State": "paused", "Status": "Up 10 minutes (Paused)"}
        assert fn(c) is None


class TestWatchdogCooldown:
    """Verify per-container cooldown prevents alert storms."""

    def test_cooldown_suppresses_repeat_alerts(self):
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "container_watchdog",
            pathlib.Path(__file__).parent.parent / "monitoring" / "container_watchdog.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        alerts_sent = []

        def fake_send(to, subject, body):
            alerts_sent.append(subject)

        containers = [
            {"Names": ["/pf9_api"], "State": "exited", "Status": "Exited (1) 1s ago", "Image": "pf9_api:latest"},
        ]

        with mock.patch.object(mod, "_docker_get", return_value=containers), \
             mock.patch.object(mod, "_fetch_alert_email", return_value="ops@example.com"), \
             mock.patch.object(mod, "_send_alert", side_effect=fake_send), \
             mock.patch("time.sleep", side_effect=StopIteration):

            try:
                mod._run_watchdog()
            except StopIteration:
                pass

        assert len(alerts_sent) == 1
        assert "unhealthy" in alerts_sent[0].lower() or "pf9_api" in alerts_sent[0]


class TestWatchdogRecovery:
    """Verify recovery notification is sent when container comes back healthy."""

    def test_recovery_alert_sent(self):
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "container_watchdog",
            pathlib.Path(__file__).parent.parent / "monitoring" / "container_watchdog.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        alerts_sent = []
        call_count = [0]
        # First poll: container is unhealthy; second poll: container is healthy
        unhealthy = [{"Names": ["/pf9_api"], "State": "exited", "Status": "Exited (1) 1s ago", "Image": "test"}]
        healthy   = [{"Names": ["/pf9_api"], "State": "running", "Status": "Up 3 seconds", "Image": "test"}]

        def fake_docker_get(_path):
            call_count[0] += 1
            return unhealthy if call_count[0] == 1 else healthy

        with mock.patch.object(mod, "_docker_get", side_effect=fake_docker_get), \
             mock.patch.object(mod, "_fetch_alert_email", return_value="ops@example.com"), \
             mock.patch.object(mod, "_send_alert", side_effect=lambda t, s, b: alerts_sent.append(s)), \
             mock.patch("time.sleep", side_effect=[None, StopIteration]):

            try:
                mod._run_watchdog()
            except StopIteration:
                pass

        assert len(alerts_sent) == 2
        subjects = " ".join(alerts_sent).lower()
        assert "unhealthy" in subjects or "alert" in subjects
        assert "recovery" in subjects


class TestWatchdogMissingSocket:
    """Watchdog must exit cleanly when Docker socket is absent (Windows dev mode)."""

    def test_exits_on_missing_socket(self):
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            "container_watchdog",
            pathlib.Path(__file__).parent.parent / "monitoring" / "container_watchdog.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with mock.patch.object(mod, "_docker_get", side_effect=FileNotFoundError("no socket")):
            # Should return without raising, not loop forever
            mod._run_watchdog()  # expected to return early


# ---------------------------------------------------------------------------
# Integration tests — API endpoints (live stack required)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not SUPERADMIN_USER, reason="TEST_SUPERADMIN_USER not set")
class TestContainerAlertAPI:
    """Integration tests against a running pf9_api instance."""

    @pytest.fixture(scope="class")
    def superadmin_token(self):
        return _login(SUPERADMIN_USER, SUPERADMIN_PASS)

    @pytest.fixture(scope="class")
    def admin_token(self):
        if not ADMIN_USER:
            pytest.skip("TEST_ADMIN_USER not set")
        return _login(ADMIN_USER, ADMIN_PASS)

    def test_get_returns_value(self, superadmin_token):
        r = requests.get(f"{API_URL}/settings/container-alert", verify=VERIFY_SSL, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "value" in data
        assert isinstance(data["value"], str)

    def test_get_is_unauthenticated(self):
        """Public endpoint — no auth token required."""
        r = requests.get(f"{API_URL}/settings/container-alert", verify=VERIFY_SSL, timeout=10)
        assert r.status_code == 200

    def test_put_requires_auth(self):
        r = requests.put(
            f"{API_URL}/admin/settings/container-alert",
            json={"value": "test@example.com"},
            verify=VERIFY_SSL, timeout=10,
        )
        assert r.status_code in (401, 403)

    def test_put_requires_superadmin(self, admin_token):
        r = requests.put(
            f"{API_URL}/admin/settings/container-alert",
            json={"value": "test@example.com"},
            headers=_auth(admin_token),
            verify=VERIFY_SSL, timeout=10,
        )
        assert r.status_code == 403

    def test_put_and_get_roundtrip(self, superadmin_token):
        test_email = "container-alerts-test@example.com"
        r = requests.put(
            f"{API_URL}/admin/settings/container-alert",
            json={"value": test_email},
            headers=_auth(superadmin_token),
            verify=VERIFY_SSL, timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["value"] == test_email

        r2 = requests.get(f"{API_URL}/settings/container-alert", verify=VERIFY_SSL, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["value"] == test_email

    def test_put_rejects_invalid_email(self, superadmin_token):
        r = requests.put(
            f"{API_URL}/admin/settings/container-alert",
            json={"value": "not-an-email"},
            headers=_auth(superadmin_token),
            verify=VERIFY_SSL, timeout=10,
        )
        assert r.status_code == 400

    def test_put_blank_email_disables_alerts(self, superadmin_token):
        r = requests.put(
            f"{API_URL}/admin/settings/container-alert",
            json={"value": ""},
            headers=_auth(superadmin_token),
            verify=VERIFY_SSL, timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["value"] == ""
