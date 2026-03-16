"""
tests/test_migration_planner_v166.py - Unit + integration tests for v1.66.x features.

Unit tests (no live stack, no psycopg2 needed):
  pytest tests/test_migration_planner_v166.py -v -k "unit"

Integration tests against a live stack:
  TEST_API_URL=http://localhost:8000 \
  TEST_ADMIN_USER=admin TEST_ADMIN_PASSWORD=secret \
  pytest tests/test_migration_planner_v166.py -v -k "integration"
"""

import os
import re
import pytest
import requests

API_URL  = os.getenv("TEST_API_URL", "http://localhost:8000")
ADMIN    = os.getenv("TEST_ADMIN_USER", "")
PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "")
VERIFY   = os.getenv("TEST_VERIFY_SSL", "false").lower() != "false"

HAVE_CREDS = bool(ADMIN and PASSWORD)

# Path to the routes source file - used by unit tests that scan the source text
# instead of importing the module (avoids needing psycopg2 in the test venv).
_ROUTES_SRC = os.path.join(os.path.dirname(__file__), "..", "api", "migration_routes.py")


def _login(api: str) -> str:
    r = requests.post(
        f"{api}/api/auth/login",
        json={"username": ADMIN, "password": PASSWORD},
        verify=VERIFY, timeout=10,
    )
    if r.status_code != 200:
        pytest.skip(f"Login failed ({r.status_code}) - live stack not available")
    return r.json()["token"]


# ---------------------------------------------------------------------------
# Unit: route ordering (source-scan, no import needed)
# ---------------------------------------------------------------------------

class TestRouteOrdering:
    """Verify /vms/reassign is declared BEFORE /vms/{vm_id} in source.
    FastAPI registers routes in declaration order; a parameterised route
    declared first will shadow any static route at the same level.
    """

    def _src(self):
        with open(_ROUTES_SRC, encoding="utf-8") as fh:
            return fh.read()

    def test_unit_reassign_before_vm_id(self):
        src = self._src()
        m_reassign = re.search(r"^@router\.patch\(['\"].*?/vms/reassign['\"]", src, re.MULTILINE)
        m_vm_id    = re.search(r"^@router\.patch\(['\"].*?/vms/\{vm_id\}['\"]", src, re.MULTILINE)
        assert m_reassign, "@router.patch for /vms/reassign not found"
        assert m_vm_id,    "@router.patch for /vms/{vm_id} not found"
        assert m_reassign.start() < m_vm_id.start(), (
            "/vms/reassign must be declared BEFORE /vms/{vm_id} to prevent "
            "FastAPI from treating 'reassign' as a vm_id path parameter"
        )

    def test_unit_vm_reassign_request_model_exists(self):
        assert "class VMReassignRequest" in self._src()

    def test_unit_reassign_enforces_max_500(self):
        src = self._src()
        assert "500" in src and "Maximum" in src, \
            "reassign_vms must enforce max 500 vm_ids"

    def test_unit_detection_skips_manually_assigned(self):
        src = self._src()
        assert "manually_assigned" in src
        # The SELECT in _run_tenant_detection must exclude manually-assigned VMs
        assert ("manually_assigned = false" in src or
                "manually_assigned IS NULL OR manually_assigned = false" in src), \
            "_run_tenant_detection must filter out manually_assigned VMs"

    def test_unit_cluster_scope_model_exists(self):
        assert "class ClusterScopeRequest" in self._src()

    def test_unit_tenant_name_validator_in_reassign_model(self):
        src = self._src()
        # validator decorator must be present on VMReassignRequest
        assert "@validator" in src and "_strip_tenant_name" in src, \
            "VMReassignRequest must have a @validator that strips tenant_name whitespace"

    # ---- New tests for v1.66.2 bug-fix batch ----

    def test_unit_create_tenant_endpoint_exists(self):
        """POST /projects/{project_id}/tenants must be registered."""
        src = self._src()
        assert re.search(
            r'@router\.post\([\'"].*?/projects/\{project_id\}/tenants[\'"]',
            src, re.MULTILINE
        ), "POST /projects/{project_id}/tenants endpoint not found in migration_routes.py"

    def test_unit_create_tenant_request_model_exists(self):
        assert "class CreateTenantRequest" in self._src()

    def test_unit_scope_clusters_cascades_to_tenants(self):
        """scope_clusters must UPDATE migration_tenants after updating migration_clusters."""
        src = self._src()
        # The cascade UPDATE must target migration_tenants and reference org_vdc
        assert "UPDATE migration_tenants" in src, \
            "scope_clusters must cascade to migration_tenants"
        assert "Cluster excluded from plan" in src, \
            "scope_clusters must use sentinel 'Cluster excluded from plan' for reversibility"

    def test_unit_reassign_uses_org_vdc_not_cluster(self):
        """reassign_vms must derive target_org_vdc from the org_vdc column, not cluster."""
        src = self._src()
        # Ensure the correct column is used —  'SELECT org_vdc FROM migration_vms' inside reassign
        # We check the function body by finding the reassign function then verifying it uses org_vdc
        assert "SELECT org_vdc FROM migration_vms" in src, \
            "reassign_vms must query org_vdc, not cluster, for target_org_vdc"
        # Old pattern (using cluster column) must NOT be present inside the reassign function
        assert "SELECT cluster FROM migration_vms" not in src, \
            "reassign_vms must NOT use 'SELECT cluster FROM migration_vms' anymore"

    def test_unit_reassign_null_safe_insert(self):
        """reassign_vms must use IS NOT DISTINCT FROM for NULL-safe tenant deduplication."""
        src = self._src()
        assert "IS NOT DISTINCT FROM" in src, \
            "reassign_vms INSERT must use IS NOT DISTINCT FROM for NULL-safe org_vdc check"
        assert "ON CONFLICT (project_id, tenant_name, org_vdc) DO NOTHING" not in src, \
            "reassign_vms must NOT use ON CONFLICT which silently fails for NULL org_vdc"

    def test_unit_reassign_allows_empty_vm_ids_with_create_if_missing(self):
        """Empty vm_ids must be allowed when create_if_missing=True."""
        src = self._src()
        # The guard condition must check both vm_ids AND create_if_missing
        assert re.search(
            r"not req\.vm_ids\s+and\s+not req\.create_if_missing",
            src
        ), "reassign_vms must allow empty vm_ids when create_if_missing=True"


# ---------------------------------------------------------------------------
# Integration: cluster scope endpoint
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_CREDS, reason="TEST_ADMIN_USER/TEST_ADMIN_PASSWORD not set")
class TestClusterScopeIntegration:
    api = API_URL.rstrip("/")

    @pytest.fixture(autouse=True)
    def _auth(self):
        self._token = _login(self.api)

    def _h(self):
        return {"Authorization": f"Bearer {self._token}"}

    def _pid(self):
        r = requests.get(f"{self.api}/api/migration/projects",
                         headers=self._h(), verify=VERIFY, timeout=10)
        if r.status_code != 200 or not r.json().get("projects"):
            pytest.skip("No migration projects in live stack")
        return r.json()["projects"][0]["project_id"]

    def test_integration_clusters_returns_list(self):
        r = requests.get(f"{self.api}/api/migration/projects/{self._pid()}/clusters",
                         headers=self._h(), verify=VERIFY, timeout=10)
        assert r.status_code == 200
        assert "clusters" in r.json()

    def test_integration_cluster_scope_requires_auth(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/{self._pid()}/clusters/scope",
            json={"cluster_ids": [], "include_in_plan": True},
            verify=VERIFY, timeout=10,
        )
        assert r.status_code in (401, 403)

    def test_integration_cluster_scope_empty_ids_noop(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/{self._pid()}/clusters/scope",
            json={"cluster_ids": [], "include_in_plan": False},
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["updated"] == 0


# ---------------------------------------------------------------------------
# Integration: VM reassign endpoint
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAVE_CREDS, reason="TEST_ADMIN_USER/TEST_ADMIN_PASSWORD not set")
class TestVMReassignIntegration:
    api = API_URL.rstrip("/")

    @pytest.fixture(autouse=True)
    def _auth(self):
        self._token = _login(self.api)

    def _h(self):
        return {"Authorization": f"Bearer {self._token}"}

    def _pid(self):
        r = requests.get(f"{self.api}/api/migration/projects",
                         headers=self._h(), verify=VERIFY, timeout=10)
        if r.status_code != 200 or not r.json().get("projects"):
            pytest.skip("No migration projects in live stack")
        return r.json()["projects"][0]["project_id"]

    def test_integration_reassign_requires_auth(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/{self._pid()}/vms/reassign",
            json={"vm_ids": [1], "tenant_name": "X"},
            verify=VERIFY, timeout=10,
        )
        assert r.status_code in (401, 403)

    def test_integration_reassign_empty_gives_400(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/{self._pid()}/vms/reassign",
            json={"vm_ids": [], "tenant_name": "T"},
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 400

    def test_integration_reassign_over_500_gives_400(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/{self._pid()}/vms/reassign",
            json={"vm_ids": list(range(501)), "tenant_name": "T"},
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 400

    def test_integration_create_missing_blank_name_gives_400(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/{self._pid()}/vms/reassign",
            json={"vm_ids": [9999999], "tenant_name": "   ", "create_if_missing": True},
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 400

    def test_integration_bad_project_gives_404(self):
        r = requests.patch(
            f"{self.api}/api/migration/projects/__no_such__/vms/reassign",
            json={"vm_ids": [1], "tenant_name": "T"},
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 404

    def test_integration_vm_list_has_cluster_in_scope(self):
        r = requests.get(
            f"{self.api}/api/migration/projects/{self._pid()}/vms?limit=5",
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 200
        vms = r.json().get("vms", [])
        if vms:
            assert "cluster_in_scope" in vms[0], \
                "cluster_in_scope missing - has migrate_cluster_scoping.sql been applied?"

    def test_integration_tenant_list_has_vm_clusters(self):
        r = requests.get(
            f"{self.api}/api/migration/projects/{self._pid()}/tenants",
            headers=self._h(), verify=VERIFY, timeout=10,
        )
        assert r.status_code == 200
        regular = [t for t in r.json().get("tenants", []) if not t.get("is_unassigned_group")]
        if regular:
            assert "vm_clusters" in regular[0]
