"""
tests/test_cluster_registry.py — Unit tests for ClusterRegistry and MultiClusterQuery.

These tests run WITHOUT a live DB or live PF9 — all DB / Pf9Client calls are mocked.
Run with:  pytest tests/test_cluster_registry.py -v
"""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ---------------------------------------------------------------------------
# Minimal stubs for modules that pull in heavy dependencies (psycopg2, requests)
# ---------------------------------------------------------------------------

# Stub db_pool
db_pool_stub = types.ModuleType("db_pool")
def _fake_get_connection():
    raise RuntimeError("DB not available in unit tests")
db_pool_stub.get_connection = _fake_get_connection
sys.modules.setdefault("db_pool", db_pool_stub)

# Stub secret_helper
secret_helper_stub = types.ModuleType("secret_helper")
secret_helper_stub.read_secret = lambda name, env_var=None, default="": "test-password"
sys.modules.setdefault("secret_helper", secret_helper_stub)

# Stub cache
cache_stub = types.ModuleType("cache")
cache_stub.cached = lambda ttl=60, key_prefix="": (lambda fn: fn)
sys.modules.setdefault("cache", cache_stub)

# Stub requests so Pf9Client.__init__ doesn't need the real package
requests_stub = types.ModuleType("requests")
requests_stub.Session = MagicMock
sys.modules.setdefault("requests", requests_stub)

# Stub fastapi (HTTPException only)
fastapi_stub = types.ModuleType("fastapi")
class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
fastapi_stub.HTTPException = _HTTPException
fastapi_stub.Query = lambda *a, **kw: None
fastapi_stub.Depends = lambda fn: None
sys.modules.setdefault("fastapi", fastapi_stub)

# Stub psycopg2.extras (RealDictCursor)
psycopg2_stub = sys.modules.get("psycopg2", types.ModuleType("psycopg2"))
psycopg2_extras_stub = types.ModuleType("psycopg2.extras")
psycopg2_extras_stub.RealDictCursor = MagicMock
sys.modules.setdefault("psycopg2", psycopg2_stub)
sys.modules["psycopg2.extras"] = psycopg2_extras_stub

# Now we can safely import pf9_control and cluster_registry
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from pf9_control import Pf9Client  # noqa: E402 — after stubs
from cluster_registry import (     # noqa: E402
    ClusterRegistry,
    MultiClusterQuery,
    get_registry,
    merge_flat,
    merge_aggregate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(region_id: str = "default:region-one") -> Pf9Client:
    """Build a minimal Pf9Client without hitting env vars."""
    return Pf9Client(
        auth_url="https://pf9.test/keystone/v3",
        username="svc",
        password="pw",
        region_name="region-one",
        region_id=region_id,
    )


def _make_registry_with_clients(*region_ids) -> ClusterRegistry:
    """Return a pre-populated ClusterRegistry (bypasses DB)."""
    reg = ClusterRegistry()
    for rid in region_ids:
        client = _make_client(rid)
        reg._regions[rid] = client
        reg._region_configs[rid] = {
            "is_default": rid == region_ids[0],
            "priority": 100,
            "region_id": rid,
            "control_plane_id": "default",
            "region_name": rid.split(":")[-1],
            "display_name": rid,
        }
        if "default" not in reg._control_planes:
            reg._control_planes["default"] = client
    reg._initialized = True
    return reg


# ---------------------------------------------------------------------------
# ClusterRegistry unit tests
# ---------------------------------------------------------------------------

class TestClusterRegistryAccessors(unittest.TestCase):

    def test_get_default_region_returns_first_is_default(self):
        reg = _make_registry_with_clients("r1", "r2")
        # r1 is is_default=True
        client = reg.get_default_region()
        self.assertEqual(client.region_id, "r1")

    def test_get_region_known(self):
        reg = _make_registry_with_clients("r1", "r2")
        client = reg.get_region("r2")
        self.assertEqual(client.region_id, "r2")

    def test_get_region_unknown_raises_404(self):
        reg = _make_registry_with_clients("r1")
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            reg.get_region("does-not-exist")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_all_enabled_regions_count(self):
        reg = _make_registry_with_clients("r1", "r2", "r3")
        self.assertEqual(len(reg.get_all_enabled_regions()), 3)

    def test_get_default_region_fallback_when_no_is_default(self):
        reg = ClusterRegistry()
        client = _make_client("r1")
        reg._regions["r1"] = client
        reg._region_configs["r1"] = {"is_default": False, "priority": 100}
        reg._initialized = True
        # No region marked is_default → falls back to first dict entry
        result = reg.get_default_region()
        self.assertEqual(result.region_id, "r1")

    def test_get_control_plane_known(self):
        reg = _make_registry_with_clients("r1")
        cp = reg.get_control_plane("default")
        self.assertIsNotNone(cp)

    def test_get_default_control_plane(self):
        reg = _make_registry_with_clients("r1")
        cp = reg.get_default_control_plane()
        self.assertIsNotNone(cp)


class TestClusterRegistryBootstrap(unittest.TestCase):

    def test_bootstrap_from_env_fallback(self):
        """If DB load returns nothing, env-var bootstrap should create a 'default' client."""
        reg = ClusterRegistry()
        fake_client = _make_client("default")
        with patch.object(reg, "_load_from_db"):          # no-op DB load
            with patch("cluster_registry.Pf9Client.from_env", return_value=fake_client):
                reg.initialize()
        self.assertIn("default", reg._regions)
        self.assertTrue(reg._initialized)

    def test_resolve_password_env_prefix(self):
        reg = ClusterRegistry()
        row = {"password_enc": "env:abc123", "control_plane_id": "default"}
        pw = reg._resolve_password(row)
        self.assertEqual(pw, "test-password")  # from stub

    def test_resolve_password_non_env_falls_back(self):
        reg = ClusterRegistry()
        row = {"password_enc": "ENCRYPTED_BLOB", "control_plane_id": "default"}
        pw = reg._resolve_password(row)
        # Phase 4 path hits warning + falls back to env-var stub value
        self.assertEqual(pw, "test-password")

    def test_shutdown_closes_sessions(self):
        reg = _make_registry_with_clients("r1")
        # Verify session.close() is called without error
        for client in reg._regions.values():
            client.session = MagicMock()
        reg.shutdown()
        for client in reg._regions.values():
            client.session.close.assert_called_once()

    def test_reload_reinitializes(self):
        reg = _make_registry_with_clients("r1")
        self.assertTrue(reg._initialized)
        with patch.object(reg, "_load_from_db"):  # keep test hermetic
            reg.reload()
        # After reload, bootstrapped from env because _load_from_db is no-op
        self.assertTrue(reg._initialized)


class TestClusterRegistryDbLoad(unittest.TestCase):

    def test_load_from_db_populates_registry(self):
        """Test that _load_from_db correctly maps DB rows to Pf9Client instances."""
        fake_rows = [
            {
                "region_id": "default:region-one",
                "region_name": "region-one",
                "display_name": "Default Region",
                "is_default": True,
                "priority": 100,
                "latency_threshold_ms": 2000,
                "control_plane_id": "default",
                "auth_url": "https://pf9.test/keystone/v3",
                "username": "svc",
                "password_enc": "env:abc",
                "user_domain": "Default",
                "project_name": "service",
                "project_domain": "Default",
            }
        ]
        reg = ClusterRegistry()

        # Patch get_connection context manager to yield fake rows
        fake_cur = MagicMock()
        fake_cur.__enter__ = lambda s: s
        fake_cur.__exit__ = MagicMock(return_value=False)
        fake_cur.fetchall.return_value = fake_rows

        fake_conn = MagicMock()
        fake_conn.__enter__ = lambda s: s
        fake_conn.__exit__ = MagicMock(return_value=False)
        fake_conn.cursor.return_value = fake_cur

        import contextlib
        @contextlib.contextmanager
        def fake_get_connection():
            yield fake_conn

        with patch("cluster_registry.get_connection", fake_get_connection):
            reg._load_from_db()

        self.assertIn("default:region-one", reg._regions)
        self.assertIn("default", reg._control_planes)
        self.assertEqual(reg._regions["default:region-one"].region_id, "default:region-one")


# ---------------------------------------------------------------------------
# merge functions
# ---------------------------------------------------------------------------

class TestMergeFunctions(unittest.TestCase):

    def test_merge_flat(self):
        results = [
            {"region_id": "r1", "data": [{"id": "vm1"}, {"id": "vm2"}]},
            {"region_id": "r2", "data": [{"id": "vm3"}]},
        ]
        flat = merge_flat(results)
        self.assertEqual(len(flat), 3)
        self.assertEqual(flat[0]["_region_id"], "r1")
        self.assertEqual(flat[2]["_region_id"], "r2")

    def test_merge_aggregate(self):
        results = [
            {"region_id": "r1", "data": {"count": 10}},
            {"region_id": "r2", "data": {"count": 5}},
        ]
        agg = merge_aggregate(results, key="count")
        self.assertEqual(agg["total"], 15)
        self.assertEqual(agg["by_region"]["r1"], 10)


# ---------------------------------------------------------------------------
# MultiClusterQuery unit tests
# ---------------------------------------------------------------------------

class TestMultiClusterQuery(unittest.TestCase):

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_gather_all_success(self):
        """All regions succeed — results list has one entry per region."""
        reg = _make_registry_with_clients("r1", "r2")
        # Patch list_servers on each client
        for rid, client in reg._regions.items():
            client.list_servers = lambda: [{"id": rid + "-vm1"}]

        q = MultiClusterQuery(reg)
        result = self._run(q.gather("list_servers"))
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(len(result["errors"]), 0)

    def test_gather_partial_failure(self):
        """One region fails — errors list is populated, results list has the success."""
        reg = _make_registry_with_clients("r1", "r2")
        reg._regions["r1"].list_servers = lambda: [{"id": "vm1"}]
        reg._regions["r2"].list_servers = MagicMock(side_effect=RuntimeError("unreachable"))

        q = MultiClusterQuery(reg)
        result = self._run(q.gather("list_servers"))
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("unreachable", result["errors"][0]["error"])

    def test_gather_timeout_becomes_error(self):
        """A region that never responds within timeout goes to errors, not results."""
        import time
        reg = _make_registry_with_clients("r1")

        def _slow():
            time.sleep(60)  # will be cut off by wait_for
        reg._regions["r1"].list_servers = _slow

        # Use a very short timeout for the test
        with patch.dict(os.environ, {"REGION_REQUEST_TIMEOUT_SEC": "1"}):
            q = MultiClusterQuery(reg)
            result = self._run(q.gather("list_servers"))

        self.assertEqual(len(result["results"]), 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_gather_and_merge_applies_merge_fn(self):
        reg = _make_registry_with_clients("r1")
        reg._regions["r1"].list_servers = lambda: [{"id": "vm1"}]
        q = MultiClusterQuery(reg)
        result = self._run(q.gather_and_merge("list_servers", merge_flat))
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["_region_id"], "r1")

    def test_specific_region_ids_filter(self):
        """When region_ids is provided, only those regions are queried."""
        reg = _make_registry_with_clients("r1", "r2", "r3")
        for rid, client in reg._regions.items():
            client.list_servers = lambda: []

        q = MultiClusterQuery(reg, region_ids=["r2"])
        self.assertEqual(len(q.regions), 1)
        self.assertEqual(q.regions[0].region_id, "r2")


# ---------------------------------------------------------------------------
# get_client() backward-compat shim
# ---------------------------------------------------------------------------

class TestGetClientShim(unittest.TestCase):

    def test_get_client_returns_pf9client_instance(self):
        """get_client() must return a Pf9Client regardless of whether registry is live."""
        from pf9_control import get_client
        fake_client = _make_client("default:region-one")
        fake_registry = _make_registry_with_clients("default:region-one")

        import cluster_registry as _cr
        original = _cr._registry
        try:
            _cr._registry = fake_registry
            result = get_client()
            self.assertIsInstance(result, Pf9Client)
        finally:
            _cr._registry = original

    def test_get_client_fallback_when_registry_raises(self):
        """If the registry raises, get_client() falls back to env-var singleton."""
        from pf9_control import get_client
        import pf9_control as _pc
        # Clear any cached singleton
        original = _pc._client
        _pc._client = None
        try:
            fake_from_env = _make_client("default")
            with patch("pf9_control.Pf9Client.from_env", return_value=fake_from_env):
                # Make cluster_registry.get_registry raise
                import cluster_registry as _cr
                original_reg = _cr._registry
                _cr._registry = None  # force a fresh init attempt
                with patch("cluster_registry.ClusterRegistry.initialize",
                           side_effect=RuntimeError("no db")):
                    result = get_client()
            self.assertIsInstance(result, Pf9Client)
        finally:
            _pc._client = original


if __name__ == "__main__":
    unittest.main()
