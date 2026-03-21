import logging
import os
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from cache import cached
from secret_helper import read_secret

log = logging.getLogger(__name__)


class Pf9Client:
    def __init__(
        self,
        auth_url: str,
        username: str,
        password: str,
        user_domain: str = "Default",
        project_name: str = "service",
        project_domain: str = "Default",
        region_name: str = "region-one",
        region_id: str = "default",
    ) -> None:
        self.region_id = region_id          # naming contract: always region_id, never cluster_id
        self.auth_url = auth_url.rstrip("/")
        self.username = username
        self.password = password
        self.user_domain = user_domain
        self.project_name = project_name
        self.project_domain = project_domain
        self.region_name = region_name

        # Derived endpoints
        self.session = requests.Session()
        self.token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self.project_id: Optional[str] = None
        self.nova_endpoint: Optional[str] = None
        self.neutron_endpoint: Optional[str] = None
        self.cinder_endpoint: Optional[str] = None
        self.keystone_endpoint: Optional[str] = None
        self.glance_endpoint: Optional[str] = None

        # Token-bucket rate limiter (gated by PF9_RATE_LIMIT_ENABLED)
        self._rl_enabled = os.getenv("PF9_RATE_LIMIT_ENABLED", "false").lower() in ("1", "true", "yes")
        _rate = float(os.getenv("PF9_API_RATE_LIMIT", "10"))  # requests per second
        self._rl_rate = max(0.1, _rate)
        self._rl_tokens: float = self._rl_rate
        self._rl_last: float = time.monotonic()
        self._rl_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "Pf9Client":
        """Build a Pf9Client from environment variables (single-cluster / legacy mode)."""
        return cls(
            auth_url=os.environ["PF9_AUTH_URL"],
            username=os.environ["PF9_USERNAME"],
            password=read_secret("pf9_password", env_var="PF9_PASSWORD"),
            user_domain=os.getenv("PF9_USER_DOMAIN", "Default"),
            project_name=os.getenv("PF9_PROJECT_NAME", "service"),
            project_domain=os.getenv("PF9_PROJECT_DOMAIN", "Default"),
            region_name=os.getenv("PF9_REGION_NAME", "region-one"),
        )

    # ---------------------------
    # Keystone auth + catalog
    # ---------------------------
    def _token_valid(self) -> bool:
        """Return True if we have a token that won't expire in the next 5 minutes."""
        if self.token is None or self._token_expires_at is None:
            return False
        return self._token_expires_at > datetime.now(timezone.utc) + timedelta(minutes=5)

    def _throttle(self) -> None:
        """Token-bucket rate limiter. Blocks until a token is available.

        Enabled only when PF9_RATE_LIMIT_ENABLED=true/1/yes.
        Rate configured via PF9_API_RATE_LIMIT (requests/second, default 10).
        """
        if not self._rl_enabled:
            return
        with self._rl_lock:
            now = time.monotonic()
            elapsed = now - self._rl_last
            self._rl_last = now
            # Refill tokens (capped at burst == rate)
            self._rl_tokens = min(self._rl_rate, self._rl_tokens + elapsed * self._rl_rate)
            if self._rl_tokens >= 1.0:
                self._rl_tokens -= 1.0
                return
            # Need to wait for the next token
            wait = (1.0 - self._rl_tokens) / self._rl_rate
            self._rl_tokens = 0.0
        time.sleep(wait)

    def invalidate(self) -> None:
        """Force re-authentication on the next API call."""
        self.token = None
        self._token_expires_at = None

    def authenticate(self) -> None:
        """
        Get a project-scoped token & service endpoints for Nova/Neutron.
        Re-authenticates automatically when the token is expired or near expiry.
        """
        if self._token_valid():
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

        # Store expiry so we can detect when the token is about to expire
        expires_at_str = token_data.get("expires_at")
        if expires_at_str:
            try:
                # Keystone returns ISO 8601, e.g. "2026-03-02T14:00:00.000000Z"
                self._token_expires_at = datetime.fromisoformat(
                    expires_at_str.replace("Z", "+00:00")
                )
            except ValueError:
                self._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        else:
            self._token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self.project_id = token_data.get("project", {}).get("id")

        # Extract endpoints from catalog
        catalog = token_data.get("catalog", [])
        self.nova_endpoint = self._find_endpoint(catalog, "compute")
        self.neutron_endpoint = self._find_endpoint(catalog, "network")
        try:
            self.cinder_endpoint = self._find_endpoint(catalog, "volumev3")
        except RuntimeError:
            self.cinder_endpoint = None
        try:
            self.glance_endpoint = self._find_endpoint(catalog, "image")
        except RuntimeError:
            self.glance_endpoint = None
        # Keystone endpoint = auth_url base (identity service)
        self.keystone_endpoint = self.auth_url

    def _find_endpoint(self, catalog: Any, service_type: str) -> str:
        # First pass: region-aware (correct for multi-region control planes)
        for svc in catalog:
            if svc.get("type") == service_type:
                for ep in svc.get("endpoints", []):
                    region_match = (
                        ep.get("region_id") == self.region_name
                        or ep.get("region") == self.region_name
                    )
                    if ep.get("interface") == "public" and region_match:
                        return ep["url"].rstrip("/")
        # Fallback: single-region deployments where region_id may be absent from catalog
        for svc in catalog:
            if svc.get("type") == service_type:
                for ep in svc.get("endpoints", []):
                    if ep.get("interface") == "public":
                        return ep["url"].rstrip("/")
        raise RuntimeError(
            f"No public endpoint for service_type={service_type!r} "
            f"region={self.region_name!r}"
        )

    def _headers(self) -> Dict[str, str]:
        self._throttle()
        if self.token is None:
            self.authenticate()
        return {
            "X-Auth-Token": self.token or "",
            "Content-Type": "application/json",
        }

    # ---------------------------
    # Flavors (Nova)
    # ---------------------------

    @cached(ttl=60, key_prefix="pf9:servers")
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
        priv_token = self.get_privileged_token()
        h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
        r = self.session.delete(url, headers=h)
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    @cached(ttl=300, key_prefix="pf9:flavors")
    def list_flavors(self) -> List[Dict[str, Any]]:
        """List all Nova flavors with details (public + private, admin scope)."""
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/flavors/detail"
        # is_public=None (send as empty string) tells Nova to return ALL flavors
        # regardless of public/private status — requires admin token
        r = self.session.get(url, headers=self._headers(), params={"is_public": "None"})
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
        priv_token = self.get_privileged_token()
        h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
        r = self.session.delete(url, headers=h)
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
        priv_token = self.get_privileged_token()
        h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
        r = self.session.delete(url, headers=h)
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
        priv_token = self.get_privileged_token()
        h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
        r = self.session.delete(url, headers=h)
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

    def _get_admin_project_token(self) -> Optional[str]:
        """
        Get a one-time token scoped to the admin project for privileged Neutron
        operations (e.g. deleting networks owned by other tenants).
        Uses PF9_ADMIN_PROJECT_NAME env var (default 'admin').
        Returns None if the auth call fails.
        """
        import os as _os
        admin_project = _os.getenv("PF9_ADMIN_PROJECT_NAME", "admin")
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
                        "name": admin_project,
                        "domain": {"name": self.project_domain},
                    }
                },
            }
        }
        try:
            r = self.session.post(
                f"{self.auth_url}/auth/tokens", json=payload, timeout=15
            )
            if r.status_code == 201:
                return r.headers.get("X-Subject-Token")
        except Exception:
            pass
        return None

    def _ensure_svc_user_admin_role(self, svc_email: str, project_id: str) -> None:
        """
        Ensure the snapshot service user has the 'admin' role on project_id.
        Uses the current admin session (self.token).  Best-effort — silently
        ignores errors so callers can still fall back to other methods.
        """
        self.authenticate()
        if not self.keystone_endpoint:
            return
        headers = {"X-Auth-Token": self.token}

        # 1. Look up service user ID
        r = self.session.get(
            f"{self.keystone_endpoint}/users",
            params={"name": svc_email},
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            return
        users = r.json().get("users", [])
        if not users:
            return
        user_id = users[0]["id"]

        # 2. Look up admin role ID
        r = self.session.get(
            f"{self.keystone_endpoint}/roles",
            params={"name": "admin"},
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            return
        roles = r.json().get("roles", [])
        if not roles:
            return
        role_id = roles[0]["id"]

        # 3. Assign if not already present
        role_url = f"{self.keystone_endpoint}/projects/{project_id}/users/{user_id}/roles/{role_id}"
        check = self.session.head(role_url, headers=headers, timeout=30)
        if check.status_code == 204:
            return  # already has role
        self.session.put(role_url, headers=headers, timeout=30)

    def get_privileged_token(self, project_id: Optional[str] = None) -> Optional[str]:
        """
        Return a Neutron-privileged auth token for cross-tenant delete operations.

        When project_id is provided:
          Uses ensure_provisioner_in_project() — the same proven path as VM
          provisioning — to grant provisionsrv '_member_' role on the target
          project, then authenticates as provisionsrv scoped to that project.
          Neutron's owner check (token.project_id == resource.tenant_id) then
          passes, allowing the delete without needing global admin privileges.

        When project_id is None:
          Falls back to trying PF9_OS_ADMIN_USER credentials (if set), then
          the existing service-project token.

        Returns the token string, or None if all methods fail.
        """
        if project_id:
            try:
                from vm_provisioning_service_user import (
                    SERVICE_USER_EMAIL, SERVICE_USER_DOMAIN,
                    get_provision_user_password, ensure_provisioner_in_project,
                )
                if not SERVICE_USER_EMAIL:
                    return self._try_os_admin_token(project_id)

                svc_password = get_provision_user_password()

                # Ensure provisionsrv has _member_ role in the target project
                # (uses the service token — same as VM provisioning, proven to work)
                ensure_provisioner_in_project(self, project_id)

                svc_domain = SERVICE_USER_DOMAIN
                d_scope = {"id": "default"} if svc_domain.lower() == "default" else {"name": svc_domain}
                payload = {
                    "auth": {
                        "identity": {
                            "methods": ["password"],
                            "password": {
                                "user": {
                                    "name": SERVICE_USER_EMAIL,
                                    "domain": d_scope,
                                    "password": svc_password,
                                }
                            },
                        },
                        "scope": {"project": {"id": project_id}},
                    }
                }
                r = self.session.post(
                    f"{self.auth_url}/auth/tokens", json=payload, timeout=15
                )
                if r.status_code == 201:
                    return r.headers.get("X-Subject-Token")
                log.warning(
                    "get_privileged_token: Keystone auth for provisionsrv returned %s "
                    "(project=%s)", r.status_code, project_id
                )
            except Exception as _exc:
                log.warning(
                    "get_privileged_token: provisioner path failed for project %s: %s — "
                    "project may be deleted; trying OS admin fallback",
                    project_id, _exc
                )
                # Project may be deleted (404 on role assignment).  Try OS admin
                # credentials if configured — those have the OpenStack `admin` role
                # and can delete resources in any project regardless of owner.
                admin_tok = self._try_os_admin_token()
                if admin_tok:
                    return admin_tok

        # Fallback: try OS admin credentials, then service-project token.
        admin_tok = self._try_os_admin_token()
        if admin_tok:
            return admin_tok
        self.authenticate()
        return self.token

    def _try_os_admin_token(self, project_id: Optional[str] = None) -> Optional[str]:
        """
        Authenticate with PF9_OS_ADMIN_USER / PF9_OS_ADMIN_PASSWORD, which must
        be a user with the OpenStack 'admin' role.  Used as a last resort for
        cross-tenant operations involving deleted-project orphans.

        Set these env vars in .env to enable this path:
          PF9_OS_ADMIN_USER       e.g. admin@pf9.net (or whatever the PF9 admin email is)
          PF9_OS_ADMIN_PASSWORD   the admin user's password
          PF9_OS_ADMIN_PROJECT    project to scope to (default: 'admin')
          PF9_OS_ADMIN_DOMAIN     user domain (default: 'Default')
        """
        import os as _os
        admin_user = _os.getenv("PF9_OS_ADMIN_USER", "")
        admin_pass = _os.getenv("PF9_OS_ADMIN_PASSWORD", "")
        if not admin_user or not admin_pass:
            return None
        admin_project = _os.getenv("PF9_OS_ADMIN_PROJECT", "admin")
        admin_domain = _os.getenv("PF9_OS_ADMIN_DOMAIN", "Default")
        try:
            payload = {
                "auth": {
                    "identity": {
                        "methods": ["password"],
                        "password": {
                            "user": {
                                "name": admin_user,
                                "domain": {"name": admin_domain},
                                "password": admin_pass,
                            }
                        },
                    },
                    "scope": {"project": {
                        "id": project_id,
                    }} if project_id else {"project": {
                        "name": admin_project,
                        "domain": {"name": admin_domain},
                    }},
                }
            }
            r = self.session.post(
                f"{self.auth_url}/auth/tokens", json=payload, timeout=15
            )
            if r.status_code == 201:
                log.info("get_privileged_token: using OS admin user for project=%s", project_id)
                return r.headers.get("X-Subject-Token")
        except Exception as _exc:
            log.warning("_try_os_admin_token failed: %s", _exc)
        return None

    def delete_network(self, network_id: str) -> None:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks/{network_id}"

        # Try to discover the network's owner project so we can obtain a
        # token scoped to that project (required for cross-tenant deletes).
        network_project_id: Optional[str] = None
        try:
            r = self.session.get(url, headers=self._headers(), timeout=15)
            if r.status_code == 200:
                net = r.json().get("network", {})
                network_project_id = net.get("tenant_id") or net.get("project_id")
        except Exception:
            pass

        # Build a privileged token scoped to the network's project
        priv_token = self.get_privileged_token(network_project_id)
        if priv_token:
            r = self.session.delete(
                url,
                headers={"X-Auth-Token": priv_token, "Content-Type": "application/json"},
            )
        else:
            r = self.session.delete(url, headers=self._headers())

        # careful: this will fail if ports exist
        if r.status_code == 403:
            log.error(
                "delete_network 403 for %s — response: %s",
                network_id, r.text[:800]
            )
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
        priv_token = self.get_privileged_token()
        h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
        r = self.session.delete(url, headers=h)
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
        priv_token = self.get_privileged_token()
        h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
        r = self.session.delete(url, headers=h)
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

    @cached(ttl=120, key_prefix="pf9:domains")
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

    @cached(ttl=60, key_prefix="pf9:projects")
    def list_projects(self, domain_id: Optional[str] = None) -> List[Dict[str, Any]]:
        self.authenticate()
        url = f"{self.keystone_endpoint}/projects"
        params: Dict[str, str] = {}
        if domain_id:
            params["domain_id"] = domain_id
        r = self.session.get(url, headers=self._headers(), params=params)
        r.raise_for_status()
        return r.json().get("projects", [])

    def resolve_project_id(self, project_name: str, domain_name: str) -> str:
        """
        Look up the project UUID for a given project name + domain name.
        Uses the admin Keystone API — no rescoping needed.
        Raises ValueError if domain or project is not found.
        """
        self.authenticate()
        # Resolve domain_id
        r = self.session.get(
            f"{self.keystone_endpoint}/domains",
            headers=self._headers(),
            params={"name": domain_name},
        )
        r.raise_for_status()
        domains = r.json().get("domains", [])
        if not domains:
            raise ValueError(f"Domain '{domain_name}' not found")
        domain_id = domains[0]["id"]
        # Resolve project_id within that domain
        r = self.session.get(
            f"{self.keystone_endpoint}/projects",
            headers=self._headers(),
            params={"domain_id": domain_id, "name": project_name},
        )
        r.raise_for_status()
        projects = r.json().get("projects", [])
        if not projects:
            raise ValueError(f"Project '{project_name}' not found in domain '{domain_name}'")
        return projects[0]["id"]

    def delete_project(self, project_id: str) -> None:
        self.authenticate()
        url = f"{self.keystone_endpoint}/projects/{project_id}"
        r = self.session.delete(url, headers=self._headers())
        if r.status_code not in (202, 204, 404):
            r.raise_for_status()

    def cleanup_project_resources(self, project_id: str) -> Dict[str, Any]:
        """
        Idempotently delete all OpenStack resources owned by project_id BEFORE
        the Keystone project itself is deleted.

        Must be called while the project still exists so that
        ensure_provisioner_in_project() can succeed (it grants _member_ role on the
        project, giving us a project-scoped token that satisfies Neutron / Cinder
        owner checks).

        Returns a summary dict with deleted/failed counts per resource type.
        """
        self.authenticate()
        summary: Dict[str, Any] = {
            "servers": {"deleted": [], "errors": []},
            "volumes": {"deleted": [], "errors": []},
            "floating_ips": {"deleted": [], "errors": []},
            "ports": {"deleted": [], "errors": []},
            "networks": {"deleted": [], "errors": []},
        }
        if not project_id:
            return summary

        # Obtain a project-scoped privileged token while the project still exists.
        priv_token = self.get_privileged_token(project_id)
        h = {"X-Auth-Token": priv_token, "Content-Type": "application/json"} if priv_token else self._headers()

        # ── 1. Servers (Nova) ──────────────────────────────────────────────
        try:
            url = f"{self.nova_endpoint}/servers?all_tenants=1&project_id={project_id}"
            resp = self.session.get(url, headers=self._headers())
            if resp.ok:
                for srv in resp.json().get("servers", []):
                    try:
                        r = self.session.delete(
                            f"{self.nova_endpoint}/servers/{srv['id']}", headers=h
                        )
                        if r.status_code in (202, 204, 404):
                            summary["servers"]["deleted"].append(srv["id"])
                        else:
                            summary["servers"]["errors"].append({"id": srv["id"], "error": f"HTTP {r.status_code}"})
                    except Exception as exc:
                        summary["servers"]["errors"].append({"id": srv["id"], "error": str(exc)})
        except Exception as exc:
            log.warning("cleanup_project_resources: server list failed for %s: %s", project_id, exc)

        # ── 2. Volumes (Cinder) ────────────────────────────────────────────
        if self.cinder_endpoint:
            try:
                cinder_base = self.cinder_endpoint.rsplit("/", 1)[0]
                vol_url = f"{cinder_base}/{project_id}/volumes/detail"
                resp = self.session.get(vol_url, headers=h)
                if resp.ok:
                    for vol in resp.json().get("volumes", []):
                        try:
                            r = self.session.delete(
                                f"{cinder_base}/{project_id}/volumes/{vol['id']}", headers=h
                            )
                            if r.status_code in (200, 202, 204, 404):
                                summary["volumes"]["deleted"].append(vol["id"])
                            else:
                                summary["volumes"]["errors"].append({"id": vol["id"], "error": f"HTTP {r.status_code}"})
                        except Exception as exc:
                            summary["volumes"]["errors"].append({"id": vol["id"], "error": str(exc)})
            except Exception as exc:
                log.warning("cleanup_project_resources: volume list failed for %s: %s", project_id, exc)

        # ── 3. Floating IPs (Neutron) ──────────────────────────────────────
        try:
            resp = self.session.get(
                f"{self.neutron_endpoint}/v2.0/floatingips?project_id={project_id}", headers=h
            )
            if resp.ok:
                for fip in resp.json().get("floatingips", []):
                    try:
                        r = self.session.delete(
                            f"{self.neutron_endpoint}/v2.0/floatingips/{fip['id']}", headers=h
                        )
                        if r.status_code in (200, 202, 204, 404):
                            summary["floating_ips"]["deleted"].append(fip["id"])
                        else:
                            summary["floating_ips"]["errors"].append({"id": fip["id"], "error": f"HTTP {r.status_code}"})
                    except Exception as exc:
                        summary["floating_ips"]["errors"].append({"id": fip["id"], "error": str(exc)})
        except Exception as exc:
            log.warning("cleanup_project_resources: floating_ip list failed for %s: %s", project_id, exc)

        # ── 4. Ports (Neutron — unattached ones) ──────────────────────────
        try:
            resp = self.session.get(
                f"{self.neutron_endpoint}/v2.0/ports?project_id={project_id}", headers=h
            )
            if resp.ok:
                for port in resp.json().get("ports", []):
                    # Skip DHCP / router ports — deleting them manually can corrupt
                    # the network; they'll be removed when the network is deleted.
                    owner = port.get("device_owner", "")
                    if owner.startswith("network:") or owner.startswith("compute:"):
                        continue
                    try:
                        r = self.session.delete(
                            f"{self.neutron_endpoint}/v2.0/ports/{port['id']}", headers=h
                        )
                        if r.status_code in (202, 204, 404):
                            summary["ports"]["deleted"].append(port["id"])
                        else:
                            summary["ports"]["errors"].append({"id": port["id"], "error": f"HTTP {r.status_code}"})
                    except Exception as exc:
                        summary["ports"]["errors"].append({"id": port["id"], "error": str(exc)})
        except Exception as exc:
            log.warning("cleanup_project_resources: port list failed for %s: %s", project_id, exc)

        # ── 5. Networks (Neutron — delete last) ───────────────────────────
        try:
            resp = self.session.get(
                f"{self.neutron_endpoint}/v2.0/networks?project_id={project_id}", headers=h
            )
            if resp.ok:
                for net in resp.json().get("networks", []):
                    try:
                        r = self.session.delete(
                            f"{self.neutron_endpoint}/v2.0/networks/{net['id']}", headers=h
                        )
                        if r.status_code in (202, 204, 404):
                            summary["networks"]["deleted"].append(net["id"])
                        else:
                            summary["networks"]["errors"].append({"id": net["id"], "error": f"HTTP {r.status_code}"})
                    except Exception as exc:
                        summary["networks"]["errors"].append({"id": net["id"], "error": str(exc)})
        except Exception as exc:
            log.warning("cleanup_project_resources: network list failed for %s: %s", project_id, exc)

        log.info(
            "cleanup_project_resources: project=%s servers=%d volumes=%d fips=%d ports=%d networks=%d",
            project_id,
            len(summary["servers"]["deleted"]),
            len(summary["volumes"]["deleted"]),
            len(summary["floating_ips"]["deleted"]),
            len(summary["ports"]["deleted"]),
            len(summary["networks"]["deleted"]),
        )
        return summary

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

    def get_role_id(self, role_name: str) -> str:
        """Return the UUID of a Keystone role by name. Raises ValueError if not found."""
        for role in self.list_roles():
            if role.get("name") == role_name:
                return role["id"]
        raise ValueError(f"Role '{role_name}' not found in PCD Keystone")

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
    @cached(ttl=60, key_prefix="pf9:volumes")
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

    def delete_volume(self, volume_id: str, force: bool = False, project_id: Optional[str] = None) -> None:
        """Delete a Cinder volume.

        project_id: the volume owner's project UUID. When provided, the Cinder
        URL is built with the correct project scope (Cinder returns 400 when the
        URL project_id doesn't match the volume's own project).  If omitted the
        volume is looked up first to discover its project.
        """
        self.authenticate()
        if not self.cinder_endpoint:
            return

        # Resolve project_id if not supplied — needed to build the correct Cinder URL.
        if not project_id:
            try:
                vols = self.list_volumes(all_tenants=True)
                match = next((v for v in vols if v.get("id") == volume_id), None)
                if match:
                    project_id = match.get("os-vol-tenant-attr:tenant_id") or match.get("tenant_id")
            except Exception:
                pass

        # Build a properly project-scoped Cinder URL.
        # cinder_endpoint = ".../cinder/v3/{service_project_id}"
        # If the volume lives in a different project, strip and replace the project_id.
        if project_id:
            cinder_base = self.cinder_endpoint.rsplit("/", 1)[0]
            priv_token = self.get_privileged_token(project_id)
            h = {"X-Auth-Token": priv_token, "Content-Type": "application/json"} if priv_token else self._headers()
            if force:
                url = f"{cinder_base}/{project_id}/volumes/{volume_id}/action"
                r = self.session.post(url, headers=h, json={"os-force_delete": {}})
            else:
                url = f"{cinder_base}/{project_id}/volumes/{volume_id}"
                r = self.session.delete(url, headers=h)
        else:
            priv_token = self.get_privileged_token()
            h = {"X-Auth-Token": priv_token} if priv_token else self._headers()
            if force:
                url = f"{self.cinder_endpoint}/volumes/{volume_id}/action"
                r = self.session.post(url, headers=h, json={"os-force_delete": {}})
            else:
                url = f"{self.cinder_endpoint}/volumes/{volume_id}"
                r = self.session.delete(url, headers=h)

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
    @cached(ttl=60, key_prefix="pf9:compute_quotas")
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
    @cached(ttl=60, key_prefix="pf9:network_quotas")
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
        external: bool = False,
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


    # ---------------------------
    # Glance – Images
    # ---------------------------
    def list_images(self, visibility: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Glance images (v2 API). Returns all pages."""
        self.authenticate()
        if not self.glance_endpoint:
            return []
        url = f"{self.glance_endpoint}/v2/images"
        params: Dict[str, Any] = {"limit": 100}
        if visibility:
            params["visibility"] = visibility
        images: List[Dict[str, Any]] = []
        while url:
            r = self.session.get(url, headers=self._headers(), params=params)
            r.raise_for_status()
            body = r.json()
            images.extend(body.get("images", []))
            url = body.get("next", None)
            if url and not url.startswith("http"):
                base = self.glance_endpoint
                url = f"{base}{url}"
            params = {}  # next URL already includes params
        return images

    def get_image(self, image_id: str) -> Dict[str, Any]:
        """Get a single Glance image by ID."""
        self.authenticate()
        if not self.glance_endpoint:
            raise RuntimeError("Glance endpoint not available")
        url = f"{self.glance_endpoint}/v2/images/{image_id}"
        r = self.session.get(url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def update_image_properties(self, image_id: str, properties: Dict[str, str]) -> None:
        """Patch Glance image properties using JSON-Patch (Glance v2).

        Adds or replaces the given key/value pairs on the image.  Requires an
        admin token (or the image owner's token).  Uses the Glance v2
        application/openstack-images-v2.1-json-patch content-type.

        Example:
            client.update_image_properties(img_id, {
                "hw_firmware_type": "uefi",
                "hw_machine_type": "q35",
            })
        """
        self.authenticate()
        if not self.glance_endpoint:
            raise RuntimeError("Glance endpoint not available")
        url = f"{self.glance_endpoint}/v2/images/{image_id}"
        # Glance v2 PATCH uses a JSON-Patch array; "add" works for both new and existing props
        patch = [{"op": "add", "path": f"/{k}", "value": v} for k, v in properties.items()]
        hdrs = {**self._headers(), "Content-Type": "application/openstack-images-v2.1-json-patch"}
        r = self.session.patch(url, headers=hdrs, json=patch)
        if not r.ok:
            raise RuntimeError(f"Glance PATCH {image_id} failed: {r.status_code} {r.text[:300]}")

    # ---------------------------
    # Nova – Diskless flavors
    # ---------------------------
    def list_diskless_flavors(self) -> List[Dict[str, Any]]:
        """Return only flavors where disk == 0 (boot-from-volume flavors)."""
        return [f for f in self.list_flavors() if f.get("disk", -1) == 0]

    # ---------------------------
    # Nova / Cinder – Quota usage
    # ---------------------------
    def get_quota_usage(self, project_id: str) -> Dict[str, Any]:
        """Return compute + storage quota with in_use counters."""
        self.authenticate()
        assert self.nova_endpoint
        # Nova — use /detail endpoint which returns {in_use, limit, reserved} for admin cross-project queries
        compute_url = f"{self.nova_endpoint}/os-quota-sets/{project_id}/detail"
        cr = self.session.get(compute_url, headers=self._headers())
        if cr.status_code == 404:
            # Fallback: some older Nova versions use ?usage=True instead of /detail
            compute_url = f"{self.nova_endpoint}/os-quota-sets/{project_id}?usage=True"
            cr = self.session.get(compute_url, headers=self._headers())
        cr.raise_for_status()
        compute = cr.json().get("quota_set", {})
        # Cinder
        storage: Dict[str, Any] = {}
        if self.cinder_endpoint:
            storage_url = f"{self.cinder_endpoint}/os-quota-sets/{project_id}?usage=True"
            sr = self.session.get(storage_url, headers=self._headers())
            if sr.status_code == 200:
                storage = sr.json().get("quota_set", {})
        return {"compute": compute, "storage": storage}

    # ---------------------------
    # Neutron – Available IPs
    # ---------------------------
    def list_available_ips(self, network_id: str, project_id: Optional[str] = None) -> List[str]:
        """
        Return the list of IP addresses in the network's subnet allocation pools
        that are not currently allocated to any port.
        """
        import ipaddress
        self.authenticate()
        assert self.neutron_endpoint
        # Get subnets for the network
        subnets = self.list_subnets(network_id=network_id)
        if not subnets:
            return []
        # Get all allocated fixed IPs on this network
        ports_url = f"{self.neutron_endpoint}/v2.0/ports"
        pr = self.session.get(ports_url, headers=self._headers(), params={"network_id": network_id})
        pr.raise_for_status()
        allocated: set = set()
        for port in pr.json().get("ports", []):
            for fip in port.get("fixed_ips", []):
                allocated.add(fip.get("ip_address"))
        # Compute free IPs across all allocation pools
        free: List[str] = []
        for subnet in subnets:
            gw = subnet.get("gateway_ip")
            for pool in subnet.get("allocation_pools", []):
                start = ipaddress.ip_address(pool["start"])
                end = ipaddress.ip_address(pool["end"])
                current = start
                while current <= end:
                    ip_str = str(current)
                    if ip_str not in allocated and ip_str != gw:
                        free.append(ip_str)
                    current += 1
                    if len(free) >= 200:  # cap to avoid huge responses
                        return free
        return free

    # ---------------------------
    # Cinder – Boot volumes
    # ---------------------------
    def create_boot_volume(
        self,
        name: str,
        image_id: str,
        size_gb: int,
        volume_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a Cinder boot volume from a Glance image.

        This must be called on a project-scoped client (i.e. one returned by
        scoped_for_project).  The token's project scope determines where the
        volume is created — no cross-project body injection needed.
        """
        self.authenticate()
        if not self.cinder_endpoint:
            raise RuntimeError("Cinder endpoint not available")
        url = f"{self.cinder_endpoint}/volumes"
        body: Dict[str, Any] = {
            "volume": {
                "name": name,
                "size": size_gb,
                "imageRef": image_id,  # imageRef auto-makes volume bootable
            }
        }
        if volume_type:
            body["volume"]["volume_type"] = volume_type
        r = self.session.post(url, headers=self._headers(), json=body)
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.reason} — {r.text[:400]}")
        return r.json().get("volume", {})

    def get_volume(self, volume_id: str) -> Dict[str, Any]:
        """Get a Cinder volume by ID.

        Called on a project-scoped provisionsrv client, so the token already
        has access to the volume — no all_tenants flag needed.
        """
        self.authenticate()
        if not self.cinder_endpoint:
            return {}
        url = f"{self.cinder_endpoint}/volumes/{volume_id}"
        r = self.session.get(url, headers=self._headers())
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json().get("volume", {})

    # ---------------------------
    # Nova – Boot from volume
    # ---------------------------
    def create_server_bfv(
        self,
        name: str,
        volume_id: str,
        flavor_id: str,
        network_id: str,
        security_group_names: Optional[List[str]] = None,
        user_data_b64: Optional[str] = None,
        fixed_ip: Optional[str] = None,
        hostname: Optional[str] = None,
        availability_zone: Optional[str] = None,
        project_id: Optional[str] = None,
        admin_pass: Optional[str] = None,
        image_id: Optional[str] = None,
        delete_on_termination: bool = True,
    ) -> Dict[str, Any]:
        """Boot a VM from an existing Cinder volume.

        Pass image_id so Nova reads Glance image properties (hw_firmware_type,
        hw_machine_type, etc.) and creates the VM with the correct hardware
        configuration — e.g. UEFI firmware for Windows Server 2019+ images.
        Without imageRef Nova uses SeaBIOS (BIOS mode) regardless of the image,
        which breaks GPT-only Windows images with 'No bootable device'.
        """
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/servers"

        network_spec: Dict[str, Any] = {"uuid": network_id}
        if fixed_ip:
            network_spec["fixed_ip"] = fixed_ip

        block_device: Dict[str, Any] = {
            "boot_index": 0,
            "uuid": volume_id,
            "source_type": "volume",
            "destination_type": "volume",
            "delete_on_termination": delete_on_termination,
        }

        sgs: List[Dict[str, str]] = []
        if security_group_names:
            sgs = [{"name": sg} for sg in security_group_names]

        body: Dict[str, Any] = {
            "server": {
                "name": name,
                "flavorRef": flavor_id,
                "networks": [network_spec],
                "block_device_mapping_v2": [block_device],
            }
        }
        # imageRef alongside BDM tells Nova to read Glance image properties
        # (hw_firmware_type, hw_machine_type, hw_disk_bus, etc.) so the VM
        # gets the correct firmware (UEFI for Windows 2019+) even though we
        # are booting from a pre-created Cinder volume.
        if image_id:
            body["server"]["imageRef"] = image_id
        # Only include security_groups if there are any (empty list causes 400 on some Nova versions)
        if sgs:
            body["server"]["security_groups"] = sgs
        if user_data_b64:
            body["server"]["user_data"] = user_data_b64
        # adminPass: Nova metadata service passes this to cloudbase-init/nova-agent on Windows
        if admin_pass:
            body["server"]["adminPass"] = admin_pass
        # NOTE: OS-EXT-SRV-ATTR:hostname is read-only; hostname is injected via cloud-init/userdata
        if availability_zone:
            body["server"]["availability_zone"] = availability_zone

        # Use X-Project-Id header so admin token creates VM in the target project
        hdrs = {**self._headers(), "X-Project-Id": project_id} if project_id else self._headers()
        r = self.session.post(url, headers=hdrs, json=body)
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.reason} — {r.text[:600]}")
        return r.json().get("server", {})

    def get_server(self, server_id: str) -> Dict[str, Any]:
        """Get a Nova server by ID."""
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/servers/{server_id}"
        r = self.session.get(url, headers=self._headers())
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json().get("server", {})

    def get_console_log(self, server_id: str, length: int = 80) -> str:
        """Fetch the Nova console log for a server (first `length` lines)."""
        self.authenticate()
        assert self.nova_endpoint
        url = f"{self.nova_endpoint}/servers/{server_id}/action"
        r = self.session.post(
            url,
            headers=self._headers(),
            json={"os-getConsoleOutput": {"length": length}},
        )
        if r.status_code in (400, 404, 409):
            return ""
        r.raise_for_status()
        return r.json().get("output", "")

    # ---------------------------
    # Scoped client factory
    # ---------------------------
    def scoped_for_project(
        self,
        project_name: str,
        domain_name: str,
    ) -> "Pf9Client":
        """
        Return a Pf9Client authenticated as the `provisionsrv` service account,
        scoped to the target project.

        This gives a genuine Keystone token whose project scope matches the target
        project, so all Nova / Neutron / Cinder resource lookups (Security Groups,
        networks, volumes) resolve correctly within that project context.

        The provisionsrv user is a native Keystone user (not in LDAP, not visible in
        the tenant customer UI).  The `ensure_provisioner_in_project` call in the
        dry-run phase guarantees the user already has _member_ role before this is
        called during execution.
        """
        from vm_provisioning_service_user import get_provisioner_client

        # Resolve target project UUID using admin credentials
        self.authenticate()
        target_project_id = self.resolve_project_id(project_name, domain_name)

        return get_provisioner_client(
            project_id=target_project_id,
            project_name=project_name,
            project_domain=domain_name,
            auth_url=self.auth_url,
        )


# ---------------------------------------------------------------------------
# Backward-compatibility shim — preserved for all 100+ existing get_client()
# call sites across the codebase.  Phase 3 routes these through ClusterRegistry
# so they transparently benefit from per-region client management.
# ---------------------------------------------------------------------------

# Emergency fallback singleton used ONLY if ClusterRegistry itself fails to init.
_client: Optional[Pf9Client] = None


def get_client() -> Pf9Client:
    """
    Return the default region's Pf9Client.

    Phase 3: delegates to ClusterRegistry.get_default_region() so all existing
    callers automatically use the registry's managed client (session reuse,
    per-region config, future multi-region support) without any code changes.

    Falls back to the legacy env-var singleton if the registry is unavailable
    (e.g. called before DB is up during a fresh container start) — identical
    behavior to the pre-Phase-3 implementation.
    """
    try:
        # Lazy import avoids circular dependency:
        #   pf9_control → cluster_registry → pf9_control (Pf9Client)
        from cluster_registry import get_registry  # noqa: PLC0415
        return get_registry().get_default_region()
    except Exception:
        # Safety net: cluster_registry unavailable or registry not yet populated.
        global _client
        if _client is None:
            _client = Pf9Client.from_env()
        return _client


def get_client_fresh() -> Pf9Client:
    """Force-discard any cached token and return a freshly authenticated client."""
    try:
        from cluster_registry import get_registry  # noqa: PLC0415
        client = get_registry().get_default_region()
        client.invalidate()
        return client
    except Exception:
        global _client
        if _client is not None:
            _client.invalidate()
        else:
            _client = Pf9Client.from_env()
        return _client
