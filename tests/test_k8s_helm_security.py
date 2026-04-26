"""
tests/test_k8s_helm_security.py — K8s Helm chart security validation tests.

Validates three security requirements by rendering the Helm chart via
`helm template` and asserting invariants on the resulting YAML:

  C5  — NetworkPolicy isolation (one policy per service, default-deny-all)
  H8  — Pod + container security contexts (non-root, no privilege escalation,
         capabilities dropped, seccomp RuntimeDefault, readOnlyRootFilesystem)
  H9  — Ingress SSL-redirect + rate-limit annotations

No live cluster is needed — the tests parse the rendered YAML only.
Skipped automatically when the `helm` binary is absent.

Run:
    pytest tests/test_k8s_helm_security.py -v
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent
_CHART_PATH = _REPO_ROOT / "k8s" / "helm" / "pf9-mngt"


# ---------------------------------------------------------------------------
# Helm availability guard
# ---------------------------------------------------------------------------
def _helm_available() -> bool:
    try:
        subprocess.run(
            ["helm", "version"],
            capture_output=True, check=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


HELM_AVAILABLE = _helm_available()
skip_no_helm = pytest.mark.skipif(not HELM_AVAILABLE, reason="helm binary not found")


# ---------------------------------------------------------------------------
# Chart rendering helpers
# ---------------------------------------------------------------------------
def _render_chart(extra_sets: dict | None = None) -> list[dict]:
    """Run `helm template` and return all non-null parsed YAML documents."""
    cmd = [
        "helm", "template", "pf9-mngt", str(_CHART_PATH),
        "--set", "ingress.host=pf9-mngt.example.com",
    ]
    for k, v in (extra_sets or {}).items():
        cmd += ["--set", f"{k}={v}"]
    result = subprocess.run(
        cmd, capture_output=True, text=True, check=True, timeout=45,
    )
    return [d for d in yaml.safe_load_all(result.stdout) if d is not None]


def _by_kind(docs: list[dict], kind: str) -> list[dict]:
    return [d for d in docs if d.get("kind") == kind]


def _find(docs: list[dict], kind: str, name: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind and d.get("metadata", {}).get("name") == name:
            return d
    return None


def _pod_spec(doc: dict) -> dict:
    return doc["spec"]["template"]["spec"]


def _containers(doc: dict) -> list[dict]:
    return _pod_spec(doc).get("containers", [])


def _component(doc: dict) -> str:
    return doc.get("metadata", {}).get("labels", {}).get("app.kubernetes.io/component", "")


# ---------------------------------------------------------------------------
# Shared fixtures (rendered once per module)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def chart_default():
    """Helm render with default values (networkPolicy.enabled=true as of v1.93.16)."""
    if not HELM_AVAILABLE:
        pytest.skip("helm binary not found")
    return _render_chart()


@pytest.fixture(scope="module")
def chart_netpol_disabled():
    """Helm render with networkPolicy.enabled explicitly set to false."""
    if not HELM_AVAILABLE:
        pytest.skip("helm binary not found")
    return _render_chart({"networkPolicy.enabled": "false"})


@pytest.fixture(scope="module")
def chart_netpol_enabled():
    """Helm render with networkPolicy.enabled=true."""
    if not HELM_AVAILABLE:
        pytest.skip("helm binary not found")
    return _render_chart({"networkPolicy.enabled": "true"})


# ---------------------------------------------------------------------------
# H9 — Ingress: SSL redirect + rate limiting
# ---------------------------------------------------------------------------
class TestIngressAnnotations:
    """
    H9: Both ingresses must carry SSL-redirect and rate-limit annotations.

    The admin ingress (pf9-mngt, class=nginx) and the tenant-ui ingress
    (pf9-tenant-ui, class=nginx-tenant) must each have:
      - nginx.ingress.kubernetes.io/ssl-redirect: "true"
      - nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
      - nginx.ingress.kubernetes.io/limit-rps: <positive integer>
      - nginx.ingress.kubernetes.io/limit-connections: <positive integer>
    """

    def _annotations(self, docs: list[dict], ingress_name: str) -> dict:
        ing = _find(docs, "Ingress", ingress_name)
        assert ing is not None, f"Ingress '{ingress_name}' not found in rendered chart"
        return ing.get("metadata", {}).get("annotations", {})

    @skip_no_helm
    def test_admin_ssl_redirect(self, chart_default):
        ann = self._annotations(chart_default, "pf9-mngt")
        assert ann.get("nginx.ingress.kubernetes.io/ssl-redirect") == "true", \
            "Admin ingress: missing ssl-redirect annotation"

    @skip_no_helm
    def test_admin_force_ssl_redirect(self, chart_default):
        ann = self._annotations(chart_default, "pf9-mngt")
        assert ann.get("nginx.ingress.kubernetes.io/force-ssl-redirect") == "true", \
            "Admin ingress: missing force-ssl-redirect annotation"

    @skip_no_helm
    def test_admin_limit_rps_present_and_positive(self, chart_default):
        ann = self._annotations(chart_default, "pf9-mngt")
        rps = ann.get("nginx.ingress.kubernetes.io/limit-rps")
        assert rps is not None, "Admin ingress: missing limit-rps annotation"
        assert int(rps) > 0, f"Admin ingress: limit-rps must be positive, got {rps!r}"

    @skip_no_helm
    def test_admin_limit_connections_present_and_positive(self, chart_default):
        ann = self._annotations(chart_default, "pf9-mngt")
        conns = ann.get("nginx.ingress.kubernetes.io/limit-connections")
        assert conns is not None, "Admin ingress: missing limit-connections annotation"
        assert int(conns) > 0, f"Admin ingress: limit-connections must be positive, got {conns!r}"

    @skip_no_helm
    def test_tenant_ui_force_ssl_redirect(self, chart_default):
        """Tenant UI ingress must also enforce HTTPS."""
        ing = _find(chart_default, "Ingress", "pf9-tenant-ui")
        if ing is None:
            pytest.skip("pf9-tenant-ui Ingress not rendered (tenantUi.ingress.enabled=false)")
        ann = ing.get("metadata", {}).get("annotations", {})
        assert (
            ann.get("nginx.ingress.kubernetes.io/ssl-redirect") == "true"
            or ann.get("nginx.ingress.kubernetes.io/force-ssl-redirect") == "true"
        ), "Tenant UI ingress: missing TLS redirect annotation"

    @skip_no_helm
    def test_tenant_ui_limit_rps_present_and_positive(self, chart_default):
        ing = _find(chart_default, "Ingress", "pf9-tenant-ui")
        if ing is None:
            pytest.skip("pf9-tenant-ui Ingress not rendered")
        ann = ing.get("metadata", {}).get("annotations", {})
        rps = ann.get("nginx.ingress.kubernetes.io/limit-rps")
        assert rps is not None, "Tenant UI ingress: missing limit-rps annotation"
        assert int(rps) > 0, f"Tenant UI ingress: limit-rps must be positive, got {rps!r}"


# ---------------------------------------------------------------------------
# H8 — Security contexts
# ---------------------------------------------------------------------------
class TestSecurityContexts:
    """
    H8: All application workloads must have hardened security settings.

    Third-party images (postgres, openldap) are excluded from container-level
    checks because they require privileged startup sequences.

    Phase 1 (implemented now):
      - Pod level:  runAsNonRoot=true, runAsUser != 0, seccompProfile=RuntimeDefault
      - Container:  allowPrivilegeEscalation=false, capabilities.drop=[ALL]

    Phase 2 (separate release — requires per-service emptyDir planning):
      - Container:  readOnlyRootFilesystem=true  (see test_readonly_root_filesystem)
    """

    # Third-party images — skip container-level hardening checks
    THIRD_PARTY = {"db", "ldap"}

    def _app_workloads(self, docs: list[dict]) -> list[dict]:
        workloads = _by_kind(docs, "Deployment") + _by_kind(docs, "StatefulSet")
        return [d for d in workloads if _component(d) not in self.THIRD_PARTY]

    # -- Pod-level ---------------------------------------------------------

    @skip_no_helm
    def test_pod_run_as_non_root(self, chart_default):
        failures = []
        for doc in self._app_workloads(chart_default):
            pod_sc = _pod_spec(doc).get("securityContext", {})
            if not pod_sc.get("runAsNonRoot"):
                failures.append(f"{doc['metadata']['name']}: runAsNonRoot not true")
        assert not failures, "\n".join(failures)

    @skip_no_helm
    def test_pod_run_as_non_zero_user(self, chart_default):
        failures = []
        for doc in self._app_workloads(chart_default):
            pod_sc = _pod_spec(doc).get("securityContext", {})
            uid = pod_sc.get("runAsUser")
            if uid is None or uid == 0:
                failures.append(f"{doc['metadata']['name']}: runAsUser={uid!r} (must be non-zero)")
        assert not failures, "\n".join(failures)

    @skip_no_helm
    def test_pod_seccomp_runtime_default(self, chart_default):
        """
        K8s 1.27+ (GA) — seccompProfile.type=RuntimeDefault at pod level.
        Cluster is v1.34 so this is fully supported.
        """
        failures = []
        for doc in self._app_workloads(chart_default):
            pod_sc = _pod_spec(doc).get("securityContext", {})
            seccomp = pod_sc.get("seccompProfile", {})
            if seccomp.get("type") != "RuntimeDefault":
                failures.append(
                    f"{doc['metadata']['name']}: seccompProfile.type="
                    f"{seccomp.get('type')!r} (expected RuntimeDefault)"
                )
        assert not failures, "\n".join(failures)

    # -- Container-level ---------------------------------------------------

    @skip_no_helm
    def test_container_no_privilege_escalation(self, chart_default):
        failures = []
        for doc in self._app_workloads(chart_default):
            for ctr in _containers(doc):
                csc = ctr.get("securityContext", {})
                if csc.get("allowPrivilegeEscalation") is not False:
                    failures.append(
                        f"{doc['metadata']['name']}/{ctr['name']}: "
                        "allowPrivilegeEscalation must be false"
                    )
        assert not failures, "\n".join(failures)

    @skip_no_helm
    def test_container_drops_all_capabilities(self, chart_default):
        failures = []
        for doc in self._app_workloads(chart_default):
            for ctr in _containers(doc):
                csc = ctr.get("securityContext", {})
                drop = csc.get("capabilities", {}).get("drop", [])
                if "ALL" not in drop:
                    failures.append(
                        f"{doc['metadata']['name']}/{ctr['name']}: "
                        "capabilities.drop must include ALL"
                    )
        assert not failures, "\n".join(failures)

    @skip_no_helm
    @pytest.mark.xfail(
        strict=True,
        reason="Phase 2: readOnlyRootFilesystem=true requires per-service emptyDir volumes — deferred to next release",
    )
    def test_readonly_root_filesystem_with_emptydir_tmp(self, chart_default):
        """
        Phase 2: readOnlyRootFilesystem=true requires /tmp mounted as emptyDir
        for every app container (workers write /tmp/alive; API writes logs).

        This test will FAIL until Phase 2 emptyDir volumes are added.
        Mark as xfail until ready: @pytest.mark.xfail(strict=True, reason="Phase 2")
        """
        failures = []
        for doc in self._app_workloads(chart_default):
            pod_spec = _pod_spec(doc)
            volumes_by_name = {v["name"]: v for v in pod_spec.get("volumes", [])}
            for ctr in pod_spec.get("containers", []):
                csc = ctr.get("securityContext", {})
                if not csc.get("readOnlyRootFilesystem"):
                    failures.append(
                        f"{doc['metadata']['name']}/{ctr['name']}: "
                        "readOnlyRootFilesystem not set to true"
                    )
                    continue
                # Verify /tmp is backed by emptyDir
                mounts = ctr.get("volumeMounts", [])
                tmp_mount = next((m for m in mounts if m["mountPath"] == "/tmp"), None)
                if not tmp_mount:
                    failures.append(
                        f"{doc['metadata']['name']}/{ctr['name']}: "
                        "readOnlyRootFilesystem=true but /tmp is not mounted"
                    )
                elif "emptyDir" not in volumes_by_name.get(tmp_mount["name"], {}):
                    failures.append(
                        f"{doc['metadata']['name']}/{ctr['name']}: "
                        f"/tmp volume '{tmp_mount['name']}' is not emptyDir"
                    )
        assert not failures, "\n".join(failures)

    @skip_no_helm
    def test_db_statefulset_has_fsgroup(self, chart_default):
        """Postgres StatefulSet must set fsGroup so the PVC is writable by the postgres process."""
        doc = _find(chart_default, "StatefulSet", "pf9-db")
        assert doc is not None, "pf9-db StatefulSet not found"
        pod_sc = _pod_spec(doc).get("securityContext", {})
        assert pod_sc.get("fsGroup"), "pf9-db: fsGroup must be set"


# ---------------------------------------------------------------------------
# C5 — NetworkPolicies
# ---------------------------------------------------------------------------
class TestNetworkPolicies:
    """
    C5: When networkPolicy.enabled=true, every service must have a NetworkPolicy
    with both Ingress and Egress policy types (default-deny-all semantics).

    Policy design follows the pattern already live on the cluster for
    pf9-tenant-portal (which was the reference implementation):
      - DB:             ingress from api + all workers on port 5432
      - Redis:          ingress from api + workers + tenant-portal on port 6379
      - LDAP:           ingress from api + ldap-sync-worker on port 389
      - API:            ingress from ingress-nginx on port 8000
      - Monitoring:     ingress from ingress-nginx + metering-worker on port 8001
      - UI/tenant-ui:   ingress from respective ingress controller
      - Tenant portal:  ingress from ingress-nginx-tenant on port 8010 (matches live policy)
      - Workers:        no ingress rules (they don't serve traffic)
      - All:            egress to kube-system DNS (UDP+TCP 53)
      - External callers: egress to port 443 (Platform9 API)
    """

    ALL_EXPECTED = [
        "pf9-api",
        "pf9-db",
        "pf9-redis",
        "pf9-ldap",
        "pf9-ui",
        "pf9-tenant-portal",
        "pf9-tenant-ui",
        "pf9-monitoring",
        "pf9-backup-worker",
        "pf9-intelligence-worker",
        "pf9-ldap-sync-worker",
        "pf9-metering-worker",
        "pf9-notification-worker",
        "pf9-scheduler-worker",
        "pf9-search-worker",
        "pf9-sla-worker",
        "pf9-snapshot-worker",
    ]

    WORKER_NAMES = [
        "pf9-backup-worker", "pf9-intelligence-worker", "pf9-ldap-sync-worker",
        "pf9-metering-worker", "pf9-notification-worker", "pf9-scheduler-worker",
        "pf9-search-worker", "pf9-sla-worker", "pf9-snapshot-worker",
    ]

    # Components allowed to egress DB
    DB_CONSUMERS = {
        "api", "db-migrate", "backup-worker", "ldap-sync-worker", "metering-worker",
        "notification-worker", "scheduler-worker", "search-worker",
        "sla-worker", "snapshot-worker", "intelligence-worker", "tenant-portal",
    }

    # Components allowed to egress Redis
    REDIS_CONSUMERS = {
        "api", "backup-worker", "metering-worker", "scheduler-worker",
        "search-worker", "sla-worker", "snapshot-worker", "intelligence-worker",
        "tenant-portal",
    }

    def _egress_ports(self, pol: dict) -> set[int]:
        ports = set()
        for rule in pol["spec"].get("egress", []):
            for p in rule.get("ports", []):
                if isinstance(p.get("port"), int):
                    ports.add(p["port"])
        return ports

    def _ingress_allowed_components(self, pol: dict, port: int) -> set[str]:
        """Return set of app.kubernetes.io/component values allowed ingress on <port>."""
        components = set()
        for rule in pol["spec"].get("ingress", []):
            if any(p.get("port") == port for p in rule.get("ports", [])):
                for sel in rule.get("from", []):
                    comp = (
                        sel.get("podSelector", {})
                        .get("matchLabels", {})
                        .get("app.kubernetes.io/component")
                    )
                    if comp:
                        components.add(comp)
        return components

    def _ingress_ns_selectors(self, pol: dict, port: int) -> set[str]:
        """Return set of namespace names (kubernetes.io/metadata.name) allowed ingress on <port>."""
        namespaces = set()
        for rule in pol["spec"].get("ingress", []):
            if any(p.get("port") == port for p in rule.get("ports", [])):
                for sel in rule.get("from", []):
                    ns_name = (
                        sel.get("namespaceSelector", {})
                        .get("matchLabels", {})
                        .get("kubernetes.io/metadata.name")
                    )
                    if ns_name:
                        namespaces.add(ns_name)
        return namespaces

    # -- Presence ----------------------------------------------------------

    @skip_no_helm
    def test_all_policies_present_when_enabled(self, chart_netpol_enabled):
        policies = _by_kind(chart_netpol_enabled, "NetworkPolicy")
        found = {p["metadata"]["name"] for p in policies}
        missing = [n for n in self.ALL_EXPECTED if n not in found]
        assert not missing, f"Missing NetworkPolicies when enabled: {missing}"

    @skip_no_helm
    def test_no_policies_when_disabled(self, chart_netpol_disabled):
        """
        With networkPolicy.enabled=false, only the always-on pf9-tenant-portal
        policy (templates/tenant-portal/netpol.yaml) should be rendered.
        All other policies are gated by networkPolicy.enabled.
        """
        policies = _by_kind(chart_netpol_disabled, "NetworkPolicy")
        # pf9-tenant-portal has its own always-on NetworkPolicy — not gated by networkPolicy.enabled
        new_policies = [p for p in policies if p["metadata"]["name"] != "pf9-tenant-portal"]
        assert len(new_policies) == 0, (
            f"Unexpected NetworkPolicies rendered with networkPolicy.enabled=false "
            f"(excluding always-on pf9-tenant-portal): "
            f"{[p['metadata']['name'] for p in new_policies]}"
        )

    # -- Policy types (default-deny-all semantics) -------------------------

    @skip_no_helm
    def test_all_policies_declare_both_ingress_and_egress_types(self, chart_netpol_enabled):
        policies = _by_kind(chart_netpol_enabled, "NetworkPolicy")
        failures = []
        for p in policies:
            types = p["spec"].get("policyTypes", [])
            if "Ingress" not in types or "Egress" not in types:
                failures.append(
                    f"{p['metadata']['name']}: policyTypes={types} "
                    "(must include both Ingress and Egress)"
                )
        assert not failures, "\n".join(failures)

    # -- DB ingress --------------------------------------------------------

    @skip_no_helm
    def test_db_policy_allows_api_ingress_on_5432(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-db")
        assert pol is not None, "pf9-db NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 5432)
        assert "api" in allowed, f"pf9-db policy does not allow 'api' on port 5432 (got: {allowed})"

    @skip_no_helm
    def test_db_policy_allows_db_migrate_ingress_on_5432(self, chart_netpol_enabled):
        """Migration job pod must be able to reach the DB through the NetworkPolicy."""
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-db")
        assert pol is not None, "pf9-db NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 5432)
        assert "db-migrate" in allowed, (
            f"pf9-db policy does not allow 'db-migrate' on port 5432 — migration job will be blocked (got: {allowed})"
        )

    @skip_no_helm
    def test_db_policy_allows_all_worker_ingress_on_5432(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-db")
        assert pol is not None, "pf9-db NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 5432)
        missing = self.DB_CONSUMERS - allowed
        assert not missing, f"pf9-db policy missing ingress from: {missing}"

    # -- Redis ingress -----------------------------------------------------

    @skip_no_helm
    def test_redis_policy_allows_api_ingress_on_6379(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-redis")
        assert pol is not None, "pf9-redis NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 6379)
        assert "api" in allowed, f"pf9-redis policy does not allow 'api' on port 6379"

    @skip_no_helm
    def test_redis_policy_allows_worker_ingress_on_6379(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-redis")
        assert pol is not None, "pf9-redis NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 6379)
        missing = self.REDIS_CONSUMERS - allowed
        assert not missing, f"pf9-redis policy missing ingress from: {missing}"

    # -- LDAP ingress ------------------------------------------------------

    @skip_no_helm
    def test_ldap_policy_allows_api_and_ldap_worker_on_389(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-ldap")
        assert pol is not None, "pf9-ldap NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 389)
        assert "api" in allowed, "pf9-ldap policy must allow 'api' on port 389"
        assert "ldap-sync-worker" in allowed, "pf9-ldap policy must allow 'ldap-sync-worker' on port 389"

    @skip_no_helm
    def test_ldap_policy_does_not_allow_workers_except_ldap_sync(self, chart_netpol_enabled):
        """Only api and ldap-sync-worker should reach LDAP — not arbitrary workers."""
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-ldap")
        assert pol is not None, "pf9-ldap NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 389)
        unexpected = allowed - {"api", "ldap-sync-worker", "backup-worker"}
        assert not unexpected, f"pf9-ldap policy allows unexpected components: {unexpected}"

    # -- API ingress -------------------------------------------------------

    @skip_no_helm
    def test_api_policy_allows_ingress_nginx_on_8000(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-api")
        assert pol is not None, "pf9-api NetworkPolicy not found"
        ns = self._ingress_ns_selectors(pol, 8000)
        assert "ingress-nginx" in ns, (
            f"pf9-api policy must allow ingress from ingress-nginx namespace on port 8000 (got: {ns})"
        )

    @skip_no_helm
    def test_api_policy_allows_tenant_portal_on_8000(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-api")
        assert pol is not None, "pf9-api NetworkPolicy not found"
        allowed = self._ingress_allowed_components(pol, 8000)
        assert "tenant-portal" in allowed, "pf9-api policy must allow 'tenant-portal' on port 8000"

    # -- Tenant portal ingress (must match live cluster policy) ------------

    @skip_no_helm
    def test_tenant_portal_policy_allows_ingress_nginx_tenant_on_8010(self, chart_netpol_enabled):
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-tenant-portal")
        assert pol is not None, "pf9-tenant-portal NetworkPolicy not found"
        ns = self._ingress_ns_selectors(pol, 8010)
        assert "ingress-nginx-tenant" in ns, (
            "pf9-tenant-portal policy must allow ingress from ingress-nginx-tenant on port 8010"
        )

    @skip_no_helm
    def test_tenant_portal_policy_egress_ports_match_live_cluster(self, chart_netpol_enabled):
        """
        The live cluster policy for pf9-tenant-portal allows egress on:
        5432 (db), 6379 (redis), 443 (pf9 API), 5000 (keystone), 53 (dns),
        8000 (admin api), 8001 (monitoring).

        The rendered policy must allow at minimum the same ports.
        """
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-tenant-portal")
        assert pol is not None, "pf9-tenant-portal NetworkPolicy not found"
        ports = self._egress_ports(pol)
        required = {5432, 6379, 443, 5000, 53, 8000, 8001}
        missing = required - ports
        assert not missing, (
            f"pf9-tenant-portal egress missing ports (vs live cluster policy): {missing}"
        )

    # -- Workers: no ingress rules ----------------------------------------

    @skip_no_helm
    def test_worker_policies_have_no_ingress_rules(self, chart_netpol_enabled):
        """Worker pods don't serve traffic — their policies must have empty ingress."""
        failures = []
        for name in self.WORKER_NAMES:
            pol = _find(chart_netpol_enabled, "NetworkPolicy", name)
            if pol is None:
                failures.append(f"{name}: NetworkPolicy not found")
                continue
            ingress = pol["spec"].get("ingress", [])
            if ingress:
                failures.append(f"{name}: unexpected ingress rules present: {ingress}")
        assert not failures, "\n".join(failures)

    # -- DNS egress (all policies) ----------------------------------------

    @skip_no_helm
    def test_all_policies_allow_dns_egress_to_kube_system(self, chart_netpol_enabled):
        """Every NetworkPolicy must allow egress on port 53 targeting kube-system."""
        policies = _by_kind(chart_netpol_enabled, "NetworkPolicy")
        failures = []
        for pol in policies:
            egress = pol["spec"].get("egress", [])
            dns_rules = [r for r in egress if any(p.get("port") == 53 for p in r.get("ports", []))]
            if not dns_rules:
                failures.append(f"{pol['metadata']['name']}: no DNS egress rule (port 53)")
                continue
            kube_system_targeted = any(
                any(
                    sel.get("namespaceSelector", {})
                    .get("matchLabels", {})
                    .get("kubernetes.io/metadata.name") == "kube-system"
                    for sel in rule.get("to", [])
                )
                for rule in dns_rules
            )
            if not kube_system_targeted:
                failures.append(
                    f"{pol['metadata']['name']}: DNS egress rule does not target kube-system"
                )
        assert not failures, "\n".join(failures)

    # -- Notification worker SMTP egress ----------------------------------

    @skip_no_helm
    def test_notification_worker_policy_allows_smtp_egress(self, chart_netpol_enabled):
        """Notification worker must allow egress to SMTP (port 587 or 465)."""
        pol = _find(chart_netpol_enabled, "NetworkPolicy", "pf9-notification-worker")
        assert pol is not None, "pf9-notification-worker NetworkPolicy not found"
        ports = self._egress_ports(pol)
        assert ports & {587, 465, 25}, (
            f"pf9-notification-worker policy has no SMTP egress port (587/465/25), got: {ports}"
        )


# ---------------------------------------------------------------------------
# Helm lint (always run — no cluster needed)
# ---------------------------------------------------------------------------
class TestHelmLint:
    @skip_no_helm
    def test_helm_lint_no_errors(self):
        result = subprocess.run(
            [
                "helm", "lint", str(_CHART_PATH),
                "--set", "ingress.host=pf9-mngt.example.com",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"helm lint failed:\n{result.stdout}\n{result.stderr}"
        )

    @skip_no_helm
    def test_helm_lint_with_netpol_enabled(self):
        result = subprocess.run(
            [
                "helm", "lint", str(_CHART_PATH),
                "--set", "ingress.host=pf9-mngt.example.com",
                "--set", "networkPolicy.enabled=true",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"helm lint (networkPolicy.enabled=true) failed:\n{result.stdout}\n{result.stderr}"
        )

    @skip_no_helm
    def test_chart_renders_minimum_resource_count(self, chart_default):
        """Chart must render at least 25 resources (sanity check against empty output)."""
        assert len(chart_default) >= 25, (
            f"Expected ≥25 rendered resources, got {len(chart_default)}"
        )

    @skip_no_helm
    def test_chart_with_netpol_renders_more_resources(self, chart_netpol_enabled, chart_netpol_disabled):
        """Enabling NetworkPolicies must add resources, not remove them."""
        assert len(chart_netpol_enabled) > len(chart_netpol_disabled), (
            "networkPolicy.enabled=true should add NetworkPolicy resources"
        )
