import os
import json
from typing import Any, Dict, Optional

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
        self.nova_endpoint: Optional[str] = None
        self.neutron_endpoint: Optional[str] = None

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

        # Extract endpoints from catalog
        catalog = body.get("token", {}).get("catalog", [])
        self.nova_endpoint = self._find_endpoint(catalog, "compute")
        self.neutron_endpoint = self._find_endpoint(catalog, "network")

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
    def create_network(
        self,
        name: str,
        project_id: Optional[str] = None,
        shared: bool = False,
        external: bool = False,
    ) -> Dict[str, Any]:
        self.authenticate()
        assert self.neutron_endpoint
        url = f"{self.neutron_endpoint}/v2.0/networks"

        body: Dict[str, Any] = {
            "name": name,
            "shared": shared,
            "router:external": external,
        }
        if project_id:
            body["project_id"] = project_id

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


# A single global client for the FastAPI app
_client: Optional[Pf9Client] = None


def get_client() -> Pf9Client:
    global _client
    if _client is None:
        _client = Pf9Client()
    return _client
