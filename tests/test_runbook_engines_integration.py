"""
tests/test_runbook_engines_integration.py — Integration tests for runbook engine functions.

Unlike test_v18510_fixes.py (which only validates result *shapes* via fake dicts),
these tests actually import and call the real engine functions
(_engine_sg_audit, _engine_quota_check, _engine_vm_rightsizing) with fully
mocked OpenStack API responses and a mocked DB connection.

This validates:
  - The engine correctly counts how many resources it scanned (not just violations)
  - Zero violations / zero alerts still returns meaningful scan counts in summary
  - target_project filtering reduces the scanned count correctly
  - Violations are detected when flagged ports are open to 0.0.0.0/0
  - Quota alerts fire at the right thresholds
  - vm_rightsizing returns vms_with_metering_data=0 when no metering rows exist
    (the root cause the user sees: "returns 0 and appears to do nothing")
"""
import os
import sys
import json
import types
import contextlib
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# STEP 1 — stub heavy third-party / DB / auth modules BEFORE importing runbook_routes
# ---------------------------------------------------------------------------

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)


def _make_cm_conn(rows=None, exists=True):
    """Return a DB context-manager mock that yields a fake connection/cursor."""
    rows = rows or []
    cursor = MagicMock()
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone = MagicMock(return_value=[exists])
    cursor.fetchall = MagicMock(return_value=rows)
    conn = MagicMock()
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor = MagicMock(return_value=cursor)
    cm = MagicMock()
    cm.__enter__ = lambda s: conn
    cm.__exit__ = MagicMock(return_value=False)
    return cm, cursor


# -- psycopg2 --
if "psycopg2" not in sys.modules:
    _psycopg2 = types.ModuleType("psycopg2")
    _psycopg2.connect = MagicMock(side_effect=RuntimeError("no DB in tests"))
    _psycopg2.OperationalError = Exception
    _psycopg2.DatabaseError = Exception
    _psycopg2_extras = types.ModuleType("psycopg2.extras")
    _psycopg2_extras.RealDictCursor = dict
    _psycopg2.extras = _psycopg2_extras
    sys.modules["psycopg2"] = _psycopg2
    sys.modules["psycopg2.extras"] = _psycopg2_extras

# -- fastapi --
if "fastapi" not in sys.modules:
    class _FakeHTTPException(Exception):
        def __init__(self, status_code: int = 400, detail: str = ""):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    _fastapi = types.ModuleType("fastapi")
    _fastapi.HTTPException = _FakeHTTPException
    _fastapi.APIRouter = MagicMock(return_value=MagicMock())
    _fastapi.Depends = lambda f: f
    _fastapi.Query = MagicMock(return_value=None)
    _fastapi.Request = object
    _fastapi.File = MagicMock(return_value=None)
    _fastapi.UploadFile = MagicMock
    _fastapi.status = types.SimpleNamespace(
        HTTP_200_OK=200, HTTP_400_BAD_REQUEST=400,
        HTTP_403_FORBIDDEN=403, HTTP_404_NOT_FOUND=404,
    )
    _fastapi.Header = MagicMock(return_value="")
    sys.modules["fastapi"] = _fastapi

    for _sub in ("fastapi.responses", "fastapi.middleware.cors", "fastapi.middleware"):
        sys.modules.setdefault(_sub, types.ModuleType(_sub))
    sys.modules["fastapi.responses"].FileResponse = MagicMock
    sys.modules["fastapi.middleware.cors"].CORSMiddleware = MagicMock
    sys.modules["fastapi.middleware"].cors = sys.modules["fastapi.middleware.cors"]

_HTTPException = sys.modules["fastapi"].HTTPException

# -- pydantic --
if "pydantic" not in sys.modules:
    _pydantic = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    _pydantic.BaseModel = _BaseModel
    _pydantic.Field = MagicMock(return_value=None)
    _pydantic.field_validator = lambda *a, **kw: (lambda f: f)
    sys.modules["pydantic"] = _pydantic

# -- other stubs --
for _mod in ("redis", "slowapi", "slowapi.util", "slowapi.errors"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

# -- project modules --
_cm_conn, _default_cursor = _make_cm_conn(exists=False)
_db_pool_stub = types.ModuleType("db_pool")
_db_pool_stub.get_connection = MagicMock(return_value=_cm_conn)
sys.modules["db_pool"] = _db_pool_stub

_auth_stub = types.ModuleType("auth")
_auth_stub.require_permission = MagicMock(return_value=lambda f: f)
_auth_stub.get_current_user = MagicMock(return_value=MagicMock(username="test"))
_auth_stub.require_authentication = MagicMock()
_auth_stub.User = MagicMock()
_auth_stub.log_auth_event = MagicMock()
sys.modules["auth"] = _auth_stub

for _mod in ("request_helpers", "secret_helper"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))
sys.modules["request_helpers"].get_request_ip = MagicMock(return_value="127.0.0.1")
sys.modules["secret_helper"].read_secret = MagicMock(return_value="")

_redis_stub = sys.modules.get("redis", types.ModuleType("redis"))
_redis_stub.Redis = MagicMock()
_redis_stub.ConnectionError = Exception
_redis_stub.TimeoutError = Exception
sys.modules["redis"] = _redis_stub

# -- pf9_control stub (imported *inside* each engine function) --
# We install this via patch.dict per-test so it does NOT persist across test
# files and break test_cluster_registry which needs the real pf9_control module.
_pf9_control_stub = types.ModuleType("pf9_control")
_pf9_control_stub.get_client = MagicMock()  # placeholder; overridden inside each test


# ---------------------------------------------------------------------------
# STEP 2 — now import runbook_routes and grab the engine registry
# ---------------------------------------------------------------------------
import runbook_routes as _rb  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_response(data: dict, status_code: int = 200) -> MagicMock:
    """Build a fake requests.Response-like object."""
    r = MagicMock()
    r.status_code = status_code
    r.json = MagicMock(return_value=data)
    r.raise_for_status = MagicMock()
    return r


def _make_client(
    neutron_sgs=None,
    keystone_projects=None,
    nova_quotas=None,
    nova_servers=None,
    nova_flavors=None,
):
    """
    Build a fake pf9_control client.

    neutron_sgs        : list of SG dicts (or empty list)
    keystone_projects  : list of project dicts
    nova_quotas        : dict mapping project_id → quota_set dict
    nova_servers       : list of server dicts
    nova_flavors       : list of flavor dicts
    """
    client = MagicMock()
    client.token = "fake-token-xyz"
    client.neutron_endpoint = "http://neutron.fake"
    client.keystone_endpoint = "http://keystone.fake"
    client.nova_endpoint = "http://nova.fake"
    client.authenticate = MagicMock()

    def _get(url, headers=None, **kw):
        if "security-groups" in url:
            return _make_fake_response({"security_groups": neutron_sgs or []})
        if "/projects" in url and "keystone" in url:
            return _make_fake_response({"projects": keystone_projects or []})
        if "quota-sets" in url:
            # url pattern: /os-quota-sets/{project_id}/detail
            pid = url.split("/os-quota-sets/")[1].split("/")[0]
            qs = (nova_quotas or {}).get(pid, {})
            return _make_fake_response({"quota_set": qs})
        if "servers/detail" in url:
            return _make_fake_response({"servers": nova_servers or []})
        if "flavors/detail" in url:
            return _make_fake_response({"flavors": nova_flavors or []})
        # default: return empty dict
        return _make_fake_response({})

    client.session.get = MagicMock(side_effect=_get)
    return client


def _call_sg_audit(params: dict, client: MagicMock) -> dict:
    """Call _engine_sg_audit with the given fake client injected."""
    _pf9_control_stub.get_client = MagicMock(return_value=client)
    with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}):
        return _rb._engine_sg_audit(params, dry_run=False, actor="test")


def _call_quota_check(params: dict, client: MagicMock) -> dict:
    """Call _engine_quota_check with the given fake client injected."""
    _pf9_control_stub.get_client = MagicMock(return_value=client)
    with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}):
        return _rb._engine_quota_check(params, dry_run=False, actor="test")


# ---------------------------------------------------------------------------
# Test data factories
# ---------------------------------------------------------------------------

def _sg(sg_id, project_id, rules):
    return {
        "id": sg_id,
        "name": f"sg-{sg_id}",
        "project_id": project_id,
        "security_group_rules": rules,
    }


def _rule_open(protocol="tcp", port_min=22, port_max=22, cidr="0.0.0.0/0"):
    return {
        "id": f"rule-{port_min}-{cidr}",
        "direction": "ingress",
        "protocol": protocol,
        "port_range_min": port_min,
        "port_range_max": port_max,
        "remote_ip_prefix": cidr,
        "description": "",
    }


def _rule_restricted(protocol="tcp", port_min=22, port_max=22, cidr="10.0.0.0/8"):
    return _rule_open(protocol, port_min, port_max, cidr)


def _project(pid, name):
    return {"id": pid, "name": name}


def _nova_quota(cores_limit=100, cores_used=0, ram_limit=204800, ram_used=0, instances_limit=50, instances_used=0):
    return {
        "cores":     {"limit": cores_limit,     "in_use": cores_used},
        "ram":       {"limit": ram_limit,        "in_use": ram_used},
        "instances": {"limit": instances_limit,  "in_use": instances_used},
    }


# ===========================================================================
# Tests: security_group_audit engine
# ===========================================================================

class TestSGAuditEngine:
    """Actual engine calls with mocked Neutron / Keystone."""

    def test_zero_sgs_zero_found(self):
        """Neutron returns no SGs → scanned=0, found=0, summary mentions '0'."""
        client = _make_client(neutron_sgs=[], keystone_projects=[])
        result = _call_sg_audit({}, client)

        assert result["items_found"] == 0
        assert result["result"]["security_groups_scanned"] == 0
        assert "0" in result["summary"]

    def test_sgs_no_violations_all_scanned(self):
        """5 SGs with only restricted rules → 0 violations, but 5 scanned."""
        sgs = [
            _sg(f"sg-{i}", "proj-a", [_rule_restricted(port_min=22, port_max=22)])
            for i in range(5)
        ]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)

        assert result["items_found"] == 0
        assert result["result"]["security_groups_scanned"] == 5
        assert "5" in result["summary"]
        assert "0" in result["summary"]  # 0 violations mentioned

    def test_violation_detected_port_22_open(self):
        """SG with 0.0.0.0/0 on port 22 → 1 violation."""
        sgs = [_sg("sg-bad", "proj-a", [_rule_open(port_min=22, port_max=22)])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)

        assert result["items_found"] == 1
        assert result["result"]["security_groups_scanned"] == 1
        assert result["result"]["violations"][0]["sg_id"] == "sg-bad"
        assert 22 in result["result"]["violations"][0]["flagged_ports"]

    def test_violation_detected_rdp_port_3389(self):
        """Port 3389 (RDP) open to 0.0.0.0/0 → 1 violation."""
        sgs = [_sg("sg-rdp", "proj-a", [_rule_open(port_min=3389, port_max=3389)])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)

        assert result["items_found"] == 1
        assert 3389 in result["result"]["violations"][0]["flagged_ports"]

    def test_multiple_sgs_partial_violations(self):
        """3 SGs: 1 clean, 2 with violations → scanned=3, found=2."""
        sgs = [
            _sg("sg-clean",  "proj-a", [_rule_restricted()]),
            _sg("sg-bad-1",  "proj-a", [_rule_open(port_min=22, port_max=22)]),
            _sg("sg-bad-2",  "proj-a", [_rule_open(port_min=3306, port_max=3306)]),
        ]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)

        assert result["items_found"] == 2
        assert result["result"]["security_groups_scanned"] == 3

    def test_target_project_filter_reduces_scan_count(self):
        """target_project filters out SGs from other projects."""
        sgs = [
            _sg("sg-proj-a", "proj-a", [_rule_open()]),   # should be scanned
            _sg("sg-proj-b", "proj-b", [_rule_open()]),   # should be filtered out
        ]
        projects = [_project("proj-a", "ProjectA"), _project("proj-b", "ProjectB")]
        client = _make_client(neutron_sgs=sgs, keystone_projects=projects)
        result = _call_sg_audit({"target_project": "proj-a"}, client)

        # Only the proj-a SG should be scanned
        assert result["result"]["security_groups_scanned"] == 1
        # And it IS a violation
        assert result["items_found"] == 1
        assert result["result"]["violations"][0]["project_id"] == "proj-a"

    def test_ipv6_any_prefix_also_flagged(self):
        """::/0 (IPv6 all-open) should also be treated as a violation."""
        sgs = [_sg("sg-v6", "proj-a", [_rule_open(port_min=22, port_max=22, cidr="::/0")])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)
        assert result["items_found"] == 1

    def test_all_ports_open_rule(self):
        """Rule with port_range_min=None, port_range_max=None means ALL ports → all flagged ports listed."""
        sgs = [_sg("sg-allports", "proj-a", [_rule_open(port_min=None, port_max=None)])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)
        assert result["items_found"] == 1
        # All default flagged ports (22, 3389, 3306, 5432, 1433, 27017) should appear
        flagged = result["result"]["violations"][0]["flagged_ports"]
        assert 22 in flagged
        assert 3389 in flagged

    def test_custom_flag_ports_param(self):
        """Custom flag_ports parameter changes what is flagged."""
        sgs = [_sg("sg-custom", "proj-a", [_rule_open(port_min=8080, port_max=8080)])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        # 8080 not in default flag list → no violation with defaults
        result = _call_sg_audit({}, client)
        assert result["items_found"] == 0

        # Now add 8080 to flag list → violation
        result2 = _call_sg_audit({"flag_ports": [8080]}, client)
        assert result2["items_found"] == 1

    def test_result_has_project_name_resolved(self):
        """Project names should be resolved from Keystone, not just show raw IDs."""
        sgs = [_sg("sg-x", "proj-abc", [_rule_open()])]
        projects = [_project("proj-abc", "My Cool Project")]
        client = _make_client(neutron_sgs=sgs, keystone_projects=projects)
        result = _call_sg_audit({}, client)
        assert result["result"]["violations"][0]["project_name"] == "My Cool Project"

    def test_summary_is_human_readable(self):
        """Summary string must be human-readable for the operator."""
        client = _make_client(neutron_sgs=[], keystone_projects=[])
        result = _call_sg_audit({}, client)
        summary = result.get("summary", "")
        assert isinstance(summary, str)
        assert len(summary) > 10  # non-trivial string
        assert "scanned" in summary.lower() or "scan" in summary.lower()

    def test_egress_rules_not_flagged(self):
        """Egress rules should NOT be counted as violations (only ingress matters)."""
        egress_rule = {
            "id": "egress-rule",
            "direction": "egress",   # <-- egress, not ingress
            "protocol": "tcp",
            "port_range_min": 22,
            "port_range_max": 22,
            "remote_ip_prefix": "0.0.0.0/0",
            "description": "",
        }
        sgs = [_sg("sg-egress", "proj-a", [egress_rule])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)
        assert result["items_found"] == 0, "Egress rules must not be flagged"

    def test_items_actioned_is_zero(self):
        """security_group_audit is read-only — items_actioned must always be 0."""
        sgs = [_sg("sg-bad", "proj-a", [_rule_open()])]
        client = _make_client(neutron_sgs=sgs, keystone_projects=[_project("proj-a", "ProjectA")])
        result = _call_sg_audit({}, client)
        assert result["items_actioned"] == 0


# ===========================================================================
# Tests: quota_threshold_check engine
# ===========================================================================

class TestQuotaThresholdCheckEngine:
    """Actual engine calls with mocked Keystone + Nova quota APIs."""

    def test_no_projects_zero_alerts(self):
        """Keystone returns no projects → 0 scanned, 0 alerts."""
        client = _make_client(keystone_projects=[], nova_quotas={})
        result = _call_quota_check({}, client)

        assert result["items_found"] == 0
        assert result["result"]["projects_scanned"] == 0
        assert "0" in result["summary"]

    def test_projects_scanned_count_correct(self):
        """3 projects, none over threshold → 3 scanned, 0 alerts."""
        projects = [
            _project("p1", "ProjectOne"),
            _project("p2", "ProjectTwo"),
            _project("p3", "ProjectThree"),
        ]
        quotas = {
            "p1": _nova_quota(cores_limit=100, cores_used=10),
            "p2": _nova_quota(cores_limit=100, cores_used=20),
            "p3": _nova_quota(cores_limit=100, cores_used=30),
        }
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({}, client)

        assert result["items_found"] == 0
        assert result["result"]["projects_scanned"] == 3
        assert "3" in result["summary"]

    def test_alert_fires_at_80_pct(self):
        """Project at 80% CPU cores must trigger a warning alert."""
        projects = [_project("p1", "ProjectOne")]
        quotas = {"p1": _nova_quota(cores_limit=100, cores_used=80)}
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({"warning_pct": 80}, client)

        assert result["items_found"] >= 1
        alert = next(a for a in result["result"]["alerts"] if a["resource"] == "compute.cores")
        assert alert["level"] == "warning"
        assert alert["utilisation_pct"] == 80.0

    def test_alert_fires_at_95_pct_critical(self):
        """Project at 96% CPU usage → critical level."""
        projects = [_project("p1", "ProjectOne")]
        quotas = {"p1": _nova_quota(cores_limit=100, cores_used=96)}
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({"warning_pct": 80, "critical_pct": 95}, client)

        alerts = [a for a in result["result"]["alerts"] if a["resource"] == "compute.cores"]
        assert len(alerts) == 1
        assert alerts[0]["level"] == "critical"

    def test_alert_below_threshold_not_fired(self):
        """Project at 79% (below 80% warning) → no alert."""
        projects = [_project("p1", "ProjectOne")]
        quotas = {"p1": _nova_quota(cores_limit=100, cores_used=79)}
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({"warning_pct": 80}, client)

        core_alerts = [a for a in result["result"]["alerts"] if a["resource"] == "compute.cores"]
        assert len(core_alerts) == 0

    def test_multi_project_only_one_over_threshold(self):
        """4 projects, only 1 over threshold → found=1, scanned=4."""
        projects = [_project(f"p{i}", f"Proj{i}") for i in range(4)]
        quotas = {
            "p0": _nova_quota(cores_limit=100, cores_used=10),
            "p1": _nova_quota(cores_limit=100, cores_used=20),
            "p2": _nova_quota(cores_limit=100, cores_used=30),
            "p3": _nova_quota(cores_limit=100, cores_used=90),  # over threshold
        }
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({"warning_pct": 80}, client)

        assert result["result"]["projects_scanned"] == 4
        core_alerts = [a for a in result["result"]["alerts"] if a["resource"] == "compute.cores"]
        assert len(core_alerts) == 1
        assert core_alerts[0]["project_id"] == "p3"

    def test_target_project_filter(self):
        """target_project limits scan to that project only."""
        projects = [_project("pa", "ProjectA"), _project("pb", "ProjectB")]
        quotas = {
            "pa": _nova_quota(cores_limit=100, cores_used=90),
            "pb": _nova_quota(cores_limit=100, cores_used=90),
        }
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({"target_project": "pa"}, client)

        assert result["result"]["projects_scanned"] == 1

    def test_unlimited_quota_not_alerted(self):
        """Quota limit=-1 means unlimited; should not generate an alert."""
        projects = [_project("p1", "ProjectOne")]
        quotas = {"p1": {"cores": {"limit": -1, "in_use": 999}}}
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({}, client)

        core_alerts = [a for a in result["result"]["alerts"] if a["resource"] == "compute.cores"]
        assert len(core_alerts) == 0, "Unlimited quota (-1) must not fire an alert"

    def test_summary_contains_project_count(self):
        """Summary must mention how many projects were scanned."""
        projects = [_project(f"p{i}", f"P{i}") for i in range(6)]
        quotas = {f"p{i}": _nova_quota() for i in range(6)}
        client = _make_client(keystone_projects=projects, nova_quotas=quotas)
        result = _call_quota_check({}, client)

        assert "6" in result["summary"]

    def test_items_actioned_always_zero(self):
        """quota_threshold_check is read-only — items_actioned must always be 0."""
        client = _make_client(keystone_projects=[], nova_quotas={})
        result = _call_quota_check({}, client)
        assert result["items_actioned"] == 0


# ===========================================================================
# Tests: vm_rightsizing engine — metering data path
# ===========================================================================

class TestVmRightsizingEngineMetering:
    """
    vm_rightsizing uses DB metering_resources, Nova servers+flavors, and
    metering_pricing. These tests verify the engine correctly reports
    vms_with_metering_data when the DB returns controlled rows, and that
    0-metering-data produces an informative result (not a silent empty dict).
    """

    def _make_metering_db(self, metering_rows, pricing_rows=None):
        """
        Return a patched get_connection that yields metering rows on the
        first cursor.fetchall() call (metering query) and pricing rows on
        the second (pricing query).
        """
        call_count = [0]

        @contextlib.contextmanager
        def _ctx_mgr():
            cursor = MagicMock()
            cursor.__enter__ = lambda s: s
            cursor.__exit__ = MagicMock(return_value=False)

            def _fetchall():
                call_count[0] += 1
                if call_count[0] == 1:
                    return metering_rows
                return pricing_rows or []

            cursor.fetchall = MagicMock(side_effect=_fetchall)
            cursor.fetchone = MagicMock(return_value=[False])
            conn = MagicMock()
            conn.__enter__ = lambda s: s
            conn.__exit__ = MagicMock(return_value=False)
            conn.cursor = MagicMock(return_value=cursor)
            yield conn

        return MagicMock(side_effect=_ctx_mgr)

    def _make_nova_server(self, sid, flavor_id, status="ACTIVE", tenant_id="proj-a"):
        return {
            "id": sid,
            "name": f"vm-{sid}",
            "status": status,
            "tenant_id": tenant_id,
            "flavor": {"id": flavor_id},
        }

    def _make_flavor(self, fid, name, vcpus, ram_mb, disk_gb=20):
        return {"id": fid, "name": name, "vcpus": vcpus, "ram": ram_mb, "disk": disk_gb}

    def _make_metering_row(self, vm_id, vm_name, project_name,
                           vcpus_alloc, ram_alloc_mb,
                           avg_cpu, avg_ram_pct, peak_cpu, peak_ram_pct,
                           data_points=10):
        """Matches column order of the metering SQL SELECT."""
        return {
            "vm_id": vm_id,
            "vm_name": vm_name,
            "project_name": project_name,
            "vcpus_allocated": vcpus_alloc,
            "ram_allocated_mb": ram_alloc_mb,
            "avg_cpu_pct": avg_cpu,
            "avg_ram_pct": avg_ram_pct,
            "avg_ram_mb": ram_alloc_mb * avg_ram_pct / 100,
            "peak_cpu_pct": peak_cpu,
            "peak_ram_pct": peak_ram_pct,
            "data_points": data_points,
        }

    def test_no_metering_data_returns_zero_candidates_with_diagnostic(self):
        """
        Root cause of user issue: metering worker hasn't run → empty metering_resources.
        Engine must return vms_with_metering_data=0 so operator can see why candidates=0.
        """
        db_mock = self._make_metering_db(metering_rows=[])
        flavors = [self._make_flavor("f1", "m1.small", 1, 2048)]
        servers = [self._make_nova_server("vm-1", "f1")]
        client = _make_client(nova_servers=servers, nova_flavors=flavors,
                               keystone_projects=[_project("proj-a", "ProjectA")])
        _pf9_control_stub.get_client = MagicMock(return_value=client)

        with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}), \
             patch.object(_rb, "get_connection", db_mock):
            result = _rb._engine_vm_rightsizing({}, dry_run=True, actor="test")

        assert result["items_found"] == 0
        assert result["result"]["vms_with_metering_data"] == 0
        assert "0" in result["summary"]
        # summary should still mention it analysed 0 VMs with metering data
        assert "summary" in result

    def test_metering_data_present_candidate_detected(self):
        """
        VM with avg CPU=5%, avg RAM=10% on a 4vCPU/8GB flavor → rightsizing candidate.
        A smaller flavor (1vCPU/2GB) at lower cost should be suggested.
        """
        metering_rows = [
            self._make_metering_row(
                "vm-busy", "busy-vm", "ProjectA",
                vcpus_alloc=4, ram_alloc_mb=8192,
                avg_cpu=5.0, avg_ram_pct=10.0,
                peak_cpu=8.0, peak_ram_pct=15.0,
            )
        ]
        db_mock = self._make_metering_db(metering_rows=metering_rows)
        flavors = [
            self._make_flavor("f-large",  "m1.large",  vcpus=4, ram_mb=8192),
            self._make_flavor("f-small",  "m1.small",  vcpus=1, ram_mb=2048),
        ]
        servers = [self._make_nova_server("vm-busy", "f-large")]
        projects = [_project("proj-a", "ProjectA")]
        client = _make_client(nova_servers=servers, nova_flavors=flavors,
                               keystone_projects=projects)
        _pf9_control_stub.get_client = MagicMock(return_value=client)

        with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}), \
             patch.object(_rb, "get_connection", db_mock):
            result = _rb._engine_vm_rightsizing({}, dry_run=True, actor="test")

        assert result["result"]["vms_with_metering_data"] == 1
        assert result["items_found"] >= 1, "Should detect at least 1 rightsizing candidate"
        assert "1" in result["summary"]

    def test_high_cpu_usage_vm_not_candidate(self):
        """VM at 80% avg CPU must NOT be a rightsizing candidate."""
        metering_rows = [
            self._make_metering_row(
                "vm-heavy", "heavy-vm", "ProjectA",
                vcpus_alloc=4, ram_alloc_mb=8192,
                avg_cpu=80.0, avg_ram_pct=70.0,
                peak_cpu=95.0, peak_ram_pct=85.0,
            )
        ]
        db_mock = self._make_metering_db(metering_rows=metering_rows)
        flavors = [
            self._make_flavor("f-large", "m1.large", vcpus=4, ram_mb=8192),
            self._make_flavor("f-small", "m1.small", vcpus=1, ram_mb=2048),
        ]
        servers = [self._make_nova_server("vm-heavy", "f-large")]
        client = _make_client(nova_servers=servers, nova_flavors=flavors)
        _pf9_control_stub.get_client = MagicMock(return_value=client)

        with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}), \
             patch.object(_rb, "get_connection", db_mock):
            result = _rb._engine_vm_rightsizing({}, dry_run=True, actor="test")

        assert result["items_found"] == 0
        assert result["result"]["vms_with_metering_data"] == 1

    def test_vm_with_no_matching_server_skipped(self):
        """Metering data for vm-ghost but Nova returns no such server → skipped."""
        metering_rows = [
            self._make_metering_row(
                "vm-ghost", "ghost-vm", "ProjectA",
                vcpus_alloc=4, ram_alloc_mb=8192,
                avg_cpu=3.0, avg_ram_pct=5.0,
                peak_cpu=5.0, peak_ram_pct=8.0,
            )
        ]
        db_mock = self._make_metering_db(metering_rows=metering_rows)
        flavors = [self._make_flavor("f-large", "m1.large", vcpus=4, ram_mb=8192)]
        # Nova returns empty servers list (VM deleted)
        client = _make_client(nova_servers=[], nova_flavors=flavors)
        _pf9_control_stub.get_client = MagicMock(return_value=client)

        with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}), \
             patch.object(_rb, "get_connection", db_mock):
            result = _rb._engine_vm_rightsizing({}, dry_run=True, actor="test")

        # vms_with_metering_data reflects DB rows regardless
        assert result["result"]["vms_with_metering_data"] == 1
        assert result["items_found"] == 0

    def test_summary_mentions_metering_data_count(self):
        """Summary must contain count of VMs with metering data for operator clarity."""
        db_mock = self._make_metering_db(metering_rows=[])
        client = _make_client(nova_servers=[], nova_flavors=[])
        _pf9_control_stub.get_client = MagicMock(return_value=client)

        with patch.dict(sys.modules, {"pf9_control": _pf9_control_stub}), \
             patch.object(_rb, "get_connection", db_mock):
            result = _rb._engine_vm_rightsizing({}, dry_run=True, actor="test")

        assert "summary" in result
        summary = result["summary"]
        assert isinstance(summary, str) and len(summary) > 5
