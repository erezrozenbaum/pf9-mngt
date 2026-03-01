import os
import json
from typing import Any, Dict, List, Optional

import requests


class Pf9Client:
    def __init__(self) -> None:
        self.auth_url = os.environ["PF9_AUTH_URL"].rstrip("/")
        self.username = os.environ["PF9_USERNAME"]
        self.password = os.environ["PF9_PASSWORD"]
        self.user_domain = os.getenv("PF9_USER_DOMAIN", "Default")
        self.project_name = os.environ["PF9_PROJECT_NAME"]
        self.project_domain = os.getenv("PF9_PROJECT_DOMAIN", "Default")
        self.region_name = os.getenv("PF9_REGION_NAME", "region-one")

        # Derived endpoints
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.project_id: Optional[str] = None
        self.nova_endpoint: Optional[str] = None
        self.neutron_endpoint: Optional[str] = None
        self.cinder_endpoint: Optional[str] = None
        self.keystone_endpoint: Optional[str] = None

    # ---------------------------
    # Keystone auth + catalog
    # ---------------------------
    def authenticate(self) -> None:
        """
        Get a project-scoped token & service endpoints for Nova/Neutron.
        """
        if self.token is not None:
            return

        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": self.username,
                            "domain": {"name": self.user_domain},
                            "password": self.password,
                        }
                    },
                },
                "scope": {
                    "project": {
                        "name": self.project_name,
                        "domain": {"name": self.project_domain},
                    }
                },
            }
        }

        url = f"{self.auth_url}/auth/tokens"
        r = self.session.post(url, json=payload)
        r.raise_for_status()

        self.token = r.headers["X-Subject-Token"]
        body = r.json()

        # Extract project_id from token scope
        token_data = body.get("token", {})
        self.project_id = token_data.get("project", {}).get("id")

        # Extract endpoints from catalog
        catalog = token_data.get("catalog", [])
        self.nova_endpoint = self._find_endpoint(catalog, "compute")
        self.neutron_endpoint = self._find_endpoint(catalog, "network")
        try:
            self.cinder_endpoint = self._find_endpoint(catalog, "volumev3")
        except RuntimeError:
            self.cinder_endpoint = None
        # Keystone endpoint = auth_url base (identity service)
        self.keystone_endpoint = self.auth_url

    def _find_endpoint(self, catalog: Any, service_type: str) -> str:
        for svc in catalog:
            if svc.get("type") == service_type:
                for ep in svc.get("endpoints", []):
                    if ep.get("interface") == "public":
                        return ep["url"].rstrip("/")
        raise RuntimeError(f"No public endpoint for {service_type}")

    def _headers(self) -> Dict[str, str]:
        if self.token is None:
            self.authenticate()
        return {
            "X-Auth-Token": self.token or "",
            "Content-Type": "application/json",
        }

    # ---------------------------
    # Flavors (Nova)
    # ---------------------------

    def list_servers(self, project_id: Optional[str] = None, all_tenants: bool = True) -> List[Dict[str, Any]]:
        """List Nova servers. If all_tenants=True, lists across all projects (admin only)."""
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/servers/detail"
        params: Dict[str, Any] = {}
        if all_tenants:
            params["all_tenants"] = "1"
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("servers", [])

    def delete_server(self, server_id: str) -> None:
        """Delete (terminate) a Nova server."""
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/servers/{server_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    def list_flavors(self) -> List[Dict[str, Any]]:
        """List all Nova flavors with details."""
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/flavors/detail"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("flavors", [])

    def create_flavor(
        self,
        name: str,
        vcpus: int,
        ram_mb: int,
        disk_gb: int,
        is_public: bool = True,
    ) -> Dict[str, Any]:
        """
        Creates a basic flavor. For extra_specs we can add another method.
        """
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/flavors"

        payload = {
            "flavor": {
                "name": name,
                "vcpus": vcpus,
                "ram": ram_mb,
                "disk": disk_gb,
                "id": None,
                "os-flavor-access:is_public": is_public,
            }
        }

        r = self.session.post(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def delete_flavor(self, flavor_id: str) -> None:
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/flavors/{flavor_id}"
        r = self.session.delete(url, headers=self._headers())
        # 404 -> already deleted, treat as success
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Networks (Neutron)
    # ---------------------------
    def list_networks(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Neutron networks, optionally filtered by project."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks"
        params: Dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("networks", [])

    def list_subnets(self, project_id: Optional[str] = None, network_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Neutron subnets."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/subnets"
        params: Dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if network_id:
            params["network_id"] = network_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("subnets", [])

    def list_routers(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Neutron routers."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/routers"
        params: Dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("routers", [])

    def delete_router(self, router_id: str) -> None:
        """Delete a Neutron router."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/routers/{router_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    def list_floating_ips(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Neutron floating IPs."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/floatingips"
        params: Dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("floatingips", [])

    def delete_floating_ip(self, floatingip_id: str) -> None:
        """Delete a floating IP."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/floatingips/{floatingip_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    def list_ports(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Neutron ports."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/ports"
        params: Dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("ports", [])

    def delete_port(self, port_id: str) -> None:
        """Delete a Neutron port."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/ports/{port_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    def create_network(
        self,
        name: str,
        project_id: Optional[str] = None,
        shared: bool = False,
        external: bool = False,
        port_security_enabled: bool = True,
        mtu: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a basic (virtual/tenant) network — no provider fields."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks"

        body: Dict[str, Any] = {
            "name": name,
            "shared": shared,
            "router:external": external,
            "port_security_enabled": port_security_enabled,
        }
        if project_id:
            body["project_id"] = project_id
        if mtu is not None:
            body["mtu"] = mtu

        payload = {"network": body}
        r = self.session.post(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def delete_network(self, network_id: str) -> None:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks/{network_id}"
        r = self.session.delete(url, headers=self._headers())
        # careful: this will fail if ports exist
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Security Groups (Neutron)
    # ---------------------------
    def list_security_groups(self, project_id: Optional[str] = None) -> list:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/security-groups"
        params = {}
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("security_groups", [])

    def get_security_group(self, sg_id: str) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/security-groups/{sg_id}"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("security_group", {})

    def create_security_group(
        self,
        name: str,
        description: str = "",
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/security-groups"
        body: Dict[str, Any] = {"name": name, "description": description}
        if project_id:
            body["project_id"] = project_id
        r = self.session.post(url, headers=self._headers(), json={"security_group": body})
        r.raise_for_status()
        return r.json()

    def delete_security_group(self, sg_id: str) -> None:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/security-groups/{sg_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code == 409:
            raise Exception(
                "Cannot delete this security group — it is the OpenStack "
                "default security group which is auto-created per project "
                "and protected from deletion."
            )
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    def create_security_group_rule(
        self,
        security_group_id: str,
        direction: str,
        protocol: Optional[str] = None,
        port_range_min: Optional[int] = None,
        port_range_max: Optional[int] = None,
        remote_ip_prefix: Optional[str] = None,
        remote_group_id: Optional[str] = None,
        ethertype: str = "IPv4",
        description: str = "",
    ) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/security-group-rules"
        body: Dict[str, Any] = {
            "security_group_id": security_group_id,
            "direction": direction,
            "ethertype": ethertype,
        }
        if protocol:
            body["protocol"] = protocol
        if port_range_min is not None:
            body["port_range_min"] = port_range_min
        if port_range_max is not None:
            body["port_range_max"] = port_range_max
        if remote_ip_prefix:
            body["remote_ip_prefix"] = remote_ip_prefix
        if remote_group_id:
            body["remote_group_id"] = remote_group_id
        if description:
            body["description"] = description
        r = self.session.post(url, headers=self._headers(), json={"security_group_rule": body})
        r.raise_for_status()
        return r.json()

    def delete_security_group_rule(self, rule_id: str) -> None:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/security-group-rules/{rule_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Keystone – Domains
    # ---------------------------
    def create_domain(self, name: str, description: str = "") -> Dict[str, Any]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/domains"
        body: Dict[str, Any] = {"name": name, "enabled": True}
        if description:
            body["description"] = description
        r = self.session.post(url, headers=self._headers(), json={"domain": body})
        r.raise_for_status()
        return r.json().get("domain", {})

    def get_domain(self, domain_id: str) -> Dict[str, Any]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/domains/{domain_id}"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("domain", {})

    def list_domains(self) -> List[Dict[str, Any]]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/domains"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("domains", [])

    def update_domain(self, domain_id: str, **kwargs) -> Dict[str, Any]:
        """Update domain fields (enabled, name, description)."""
        self.authenticate()
        url = f"{self.keystone_endpoint}/domains/{domain_id}"
        r = self.session.patch(url, headers=self._headers(), json={"domain": kwargs})
        r.raise_for_status()
        return r.json().get("domain", {})

    def delete_domain(self, domain_id: str) -> None:
        """Delete a domain. Domain must be disabled first."""
        self.authenticate()
        url = f"{self.keystone_endpoint}/domains/{domain_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Keystone – Projects
    # ---------------------------
    def create_project(
        self, name: str, domain_id: str, description: str = ""
    ) -> Dict[str, Any]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/projects"
        body: Dict[str, Any] = {
            "name": name,
            "domain_id": domain_id,
            "enabled": True,
        }
        if description:
            body["description"] = description
        r = self.session.post(url, headers=self._headers(), json={"project": body})
        r.raise_for_status()
        return r.json().get("project", {})

    def list_projects(self, domain_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/projects"
        params: Dict[str, str] = {}
        if domain_id:
            params["domain_id"] = domain_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("projects", [])

    def delete_project(self, project_id: str) -> None:
        self.authenticate()
        url = f"{self.keystone_endpoint}/projects/{project_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Keystone – Users
    # ---------------------------
    def create_user(
        self,
        name: str,
        password: str,
        domain_id: str,
        email: str = "",
        description: str = "",
        force_password_change: bool = True,
    ) -> Dict[str, Any]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/users"
        body: Dict[str, Any] = {
            "name": name,
            "password": password,
            "domain_id": domain_id,
            "enabled": True,
        }
        if email:
            body["email"] = email
        if description:
            body["description"] = description
        # PF9/Keystone: set password_expires_at to force change on first login
        if force_password_change:
            from datetime import datetime, timezone, timedelta
            body["options"] = {"ignore_password_expiry": False}
            # Password expires immediately — user must change at first login
            body["password_expires_at"] = (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
        r = self.session.post(url, headers=self._headers(), json={"user": body})
        r.raise_for_status()
        return r.json().get("user", {})

    def list_users(self, domain_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/users"
        params: Dict[str, str] = {}
        if domain_id:
            params["domain_id"] = domain_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("users", [])

    def delete_user(self, user_id: str) -> None:
        self.authenticate()
        url = f"{self.keystone_endpoint}/users/{user_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Keystone – Role assignments
    # ---------------------------
    def list_roles(self) -> List[Dict[str, Any]]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/roles"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("roles", [])

    def list_role_assignments(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Keystone role assignments, optionally filtered by user."""
        self.authenticate()
        url = f"{self.keystone_endpoint}/role_assignments"
        params: Dict[str, str] = {"include_names": "true"}
        if user_id:
            params["user.id"] = user_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("role_assignments", [])

    def assign_role_to_user_on_project(
        self, project_id: str, user_id: str, role_id: str
    ) -> None:
        """PUT /v3/projects/{project_id}/users/{user_id}/roles/{role_id}"""
        self.authenticate()
        url = f"{self.keystone_endpoint}/projects/{project_id}/users/{user_id}/roles/{role_id}"
        r = self.session.put(url, headers=self._headers())
        r.raise_for_status()

    def assign_role_to_user_on_domain(
        self, domain_id: str, user_id: str, role_id: str
    ) -> None:
        """PUT /v3/domains/{domain_id}/users/{user_id}/roles/{role_id}"""
        self.authenticate()
        url = f"{self.keystone_endpoint}/domains/{domain_id}/users/{user_id}/roles/{role_id}"
        r = self.session.put(url, headers=self._headers())
        r.raise_for_status()

    # ---------------------------
    # Cinder – Volumes
    # ---------------------------
    def list_volumes(self, project_id: Optional[str] = None, all_tenants: bool = True) -> List[Dict[str, Any]]:
        """List Cinder volumes."""
        self.authenticate()
        if not self.cinder_endpoint:
            return []
        url = f"{self.cinder_endpoint}/volumes/detail"
        params: Dict[str, Any] = {}
        if all_tenants:
            params["all_tenants"] = "1"
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("volumes", [])

    def delete_volume(self, volume_id: str, force: bool = False) -> None:
        """Delete a Cinder volume."""
        self.authenticate()
        if not self.cinder_endpoint:
            return
        if force:
            # Force-delete via action
            url = f"{self.cinder_endpoint}/volumes/{volume_id}/action"
            r = self.session.post(url, headers=self._headers(), json={"os-force_delete": {}})
        else:
            url = f"{self.cinder_endpoint}/volumes/{volume_id}"
            r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (200, 202, 204, 404):
            r.raise_for_status()

    # ---------------------------
    # Cinder – Volume Snapshots
    # ---------------------------
    def list_volume_snapshots(self, project_id: Optional[str] = None, all_tenants: bool = True) -> List[Dict[str, Any]]:
        """List Cinder volume snapshots."""
        self.authenticate()
        if not self.cinder_endpoint:
            return []
        url = f"{self.cinder_endpoint}/snapshots/detail"
        params: Dict[str, Any] = {}
        if all_tenants:
            params["all_tenants"] = "1"
        if project_id:
            params["project_id"] = project_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("snapshots", [])

    # ---------------------------
    # Nova – Quotas
    # ---------------------------
    def get_compute_quotas(self, project_id: str) -> Dict[str, Any]:
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/os-quota-sets/{project_id}"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("quota_set", {})

    def update_compute_quotas(
        self, project_id: str, quotas: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Update Nova compute quotas. Valid keys:
        instances, cores, ram, key_pairs, server_groups, server_group_members,
        metadata_items, injected_files, injected_file_content_bytes,
        injected_file_path_bytes
        """
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/os-quota-sets/{project_id}"
        payload = {"quota_set": quotas}
        r = self.session.put(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json().get("quota_set", {})

    # ---------------------------
    # Neutron – Quotas
    # ---------------------------
    def get_network_quotas(self, project_id: str) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/quotas/{project_id}"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("quota", {})

    def update_network_quotas(
        self, project_id: str, quotas: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Update Neutron network quotas. Valid keys:
        network, subnet, port, router, floatingip, security_group,
        security_group_rule, rbac_policy
        """
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/quotas/{project_id}"
        payload = {"quota": quotas}
        r = self.session.put(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json().get("quota", {})

    # ---------------------------
    # Cinder – Quotas
    # ---------------------------
    def get_storage_quotas(self, project_id: str) -> Dict[str, Any]:
        self.authenticate()
        if not self.cinder_endpoint:
            return {}
        url = f"{self.cinder_endpoint}/os-quota-sets/{project_id}"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("quota_set", {})

    def update_storage_quotas(
        self, project_id: str, quotas: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        Update Cinder storage quotas. Valid keys:
        volumes, snapshots, gigabytes, backups, backup_gigabytes,
        per_volume_gigabytes, groups
        """
        self.authenticate()
        if not self.cinder_endpoint:
            return {}
        url = f"{self.cinder_endpoint}/os-quota-sets/{project_id}"
        payload = {"quota_set": quotas}
        r = self.session.put(url, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json().get("quota_set", {})

    # ---------------------------
    # Neutron – Subnets
    # ---------------------------
    def create_subnet(
        self,
        network_id: str,
        cidr: str,
        name: str = "",
        gateway_ip: Optional[str] = None,
        dns_nameservers: Optional[List[str]] = None,
        ip_version: int = 4,
        enable_dhcp: bool = True,
        allocation_pools: Optional[List[Dict[str, str]]] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/subnets"
        body: Dict[str, Any] = {
            "network_id": network_id,
            "cidr": cidr,
            "ip_version": ip_version,
            "enable_dhcp": enable_dhcp,
        }
        if name:
            body["name"] = name
        if gateway_ip:
            body["gateway_ip"] = gateway_ip
        if dns_nameservers:
            body["dns_nameservers"] = dns_nameservers
        if allocation_pools:
            body["allocation_pools"] = allocation_pools
        if project_id:
            body["tenant_id"] = project_id
        r = self.session.post(url, headers=self._headers(), json={"subnet": body})
        r.raise_for_status()
        return r.json().get("subnet", {})

    # ---------------------------
    # Neutron – Physical / Provider networks
    # ---------------------------
    def list_physical_networks(self) -> List[str]:
        """Discover available physical network names from existing provider networks."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks"
        r = self.session.get(url, headers=self._headers(), params={"fields": "provider:physical_network"})
        r.raise_for_status()
        networks = r.json().get("networks", [])
        physnets: set = set()
        for net in networks:
            pn = net.get("provider:physical_network")
            if pn:
                physnets.add(pn)
        return sorted(physnets) if physnets else ["physnet1"]

    def create_provider_network(
        self,
        name: str,
        network_type: str = "vlan",
        physical_network: str = "physnet1",
        segmentation_id: Optional[int] = None,
        project_id: Optional[str] = None,
        shared: bool = False,
        external: bool = True,
        mtu: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a provider (VLAN/flat) network, with or without a subnet (for L2 use external=False)."""
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks"
        body: Dict[str, Any] = {
            "name": name,
            "shared": shared,
            "router:external": external,
            "provider:network_type": network_type,
            "provider:physical_network": physical_network,
        }
        if segmentation_id is not None:
            body["provider:segmentation_id"] = segmentation_id
        if project_id:
            body["project_id"] = project_id
        if mtu is not None:
            body["mtu"] = mtu
        r = self.session.post(url, headers=self._headers(), json={"network": body})
        r.raise_for_status()
        return r.json().get("network", {})

    # ---------------------------
    # Neutron – Routers
    # ---------------------------
    def create_router(
        self,
        name: str,
        external_network_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/routers"
        body: Dict[str, Any] = {"name": name}
        if external_network_id:
            body["external_gateway_info"] = {"network_id": external_network_id}
        if project_id:
            body["project_id"] = project_id
        r = self.session.post(url, headers=self._headers(), json={"router": body})
        r.raise_for_status()
        return r.json().get("router", {})

    # ---------------------------
    # Domain resource counts (for management)
    # ---------------------------
    def count_domain_resources(self, domain_id: str) -> Dict[str, int]:
        """Count projects, users under a domain for safety checks."""
        projects = self.list_projects(domain_id=domain_id)
        users = self.list_users(domain_id=domain_id)
        return {
            "projects": len(projects),
            "users": len(users),
        }


# A single global client for the FastAPI app
_client: Optional[Pf9Client] = None


def get_client() -> Pf9Client:
    global _client
    if _client is None:
        _client = Pf9Client()
    return _client
