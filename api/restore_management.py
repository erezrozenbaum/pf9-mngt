"""
Snapshot Restore Management API Endpoints + Execution Engine

Handles restore planning, execution, job tracking, and progress monitoring.
Restore uses the same service-user scoping mechanism as snapshots,
with the same fallback chain for cross-tenant operations.

Boot-from-volume restore flow:
  1. Plan: validate VM, detect boot mode, check quota, build action list
  2. Execute: create volume from snapshot → create ports → create server → wait active
  3. Track: per-step progress in restore_job_steps table

Supports:
  - NEW mode (side-by-side): create new VM alongside existing
  - REPLACE mode (destructive): delete existing VM then recreate from snapshot
  - IP strategies: NEW_IPS, TRY_SAME_IPS, SAME_IPS_OR_FAIL
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable

from psycopg2.extras import RealDictCursor, Json
from fastapi import HTTPException, Depends
from pydantic import BaseModel, Field
import requests as http_requests

from auth import require_permission, get_current_user, User

logger = logging.getLogger("pf9.restore")

# ---------------------------------------------------------------------------
# Environment / Feature flags
# ---------------------------------------------------------------------------
RESTORE_ENABLED = os.getenv("RESTORE_ENABLED", "false").lower() in ("true", "1", "yes")
RESTORE_DRY_RUN = os.getenv("RESTORE_DRY_RUN", "false").lower() in ("true", "1", "yes")

# OpenStack connection (reuse same vars as snapshot system)
PF9_AUTH_URL = os.getenv("PF9_AUTH_URL", "")
PF9_USERNAME = os.getenv("PF9_USERNAME", "")
PF9_PASSWORD = os.getenv("PF9_PASSWORD", "")
PF9_USER_DOMAIN = os.getenv("PF9_USER_DOMAIN", "Default")
PF9_PROJECT_NAME = os.getenv("PF9_PROJECT_NAME", "service")
PF9_PROJECT_DOMAIN = os.getenv("PF9_PROJECT_DOMAIN", "Default")

# Service user for cross-tenant operations
SNAPSHOT_SERVICE_USER_EMAIL = os.getenv("SNAPSHOT_SERVICE_USER_EMAIL", "")
SNAPSHOT_SERVICE_USER_DOMAIN = os.getenv("SNAPSHOT_SERVICE_USER_DOMAIN", "default")


def _resolve_service_user_password() -> str:
    """
    Resolve the snapshot service user password.
    Tries in order:
      1. SNAPSHOT_SERVICE_USER_PASSWORD (plaintext)
      2. SNAPSHOT_USER_PASSWORD_ENCRYPTED + SNAPSHOT_PASSWORD_KEY (Fernet)
    Returns empty string if no password is available.
    """
    plain = os.getenv("SNAPSHOT_SERVICE_USER_PASSWORD", "")
    if plain:
        return plain

    encrypted = os.getenv("SNAPSHOT_USER_PASSWORD_ENCRYPTED", "")
    key = os.getenv("SNAPSHOT_PASSWORD_KEY", "")
    if encrypted and key:
        try:
            from cryptography.fernet import Fernet
            f = Fernet(key.encode() if isinstance(key, str) else key)
            return f.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted).decode()
        except Exception as e:
            logger.error(f"Failed to decrypt service user password: {e}")
    return ""


SNAPSHOT_SERVICE_USER_PASSWORD = _resolve_service_user_password()


# ============================================================================
# Pydantic Request/Response Models
# ============================================================================

class RestorePlanRequest(BaseModel):
    """Request to generate a restore plan"""
    project_id: str
    vm_id: str
    restore_point_id: str  # Cinder snapshot ID
    mode: str = Field(default="NEW", pattern="^(NEW|REPLACE)$")
    new_vm_name: Optional[str] = None
    ip_strategy: str = Field(default="NEW_IPS", pattern="^(NEW_IPS|TRY_SAME_IPS|SAME_IPS_OR_FAIL|MANUAL_IP)$")
    manual_ips: Optional[Dict[str, str]] = None  # {network_id: "desired_ip"} for MANUAL_IP strategy
    security_group_ids: Optional[list] = None  # List of security group UUIDs to attach to restored VM ports
    cleanup_old_storage: bool = Field(default=False, description="Delete original VM's orphaned volume after REPLACE restore")
    delete_source_snapshot: bool = Field(default=False, description="Delete the source snapshot after a successful restore")


class RestoreExecuteRequest(BaseModel):
    """Request to execute a previously-created restore plan"""
    plan_id: str  # UUID of the restore_jobs row in PLANNED status
    confirm_destructive: Optional[str] = None  # Required for REPLACE mode: "DELETE AND RESTORE <vm_name>"


class RestoreCancelRequest(BaseModel):
    """Request to cancel a running restore job"""
    reason: Optional[str] = None


class RestoreCleanupRequest(BaseModel):
    """Request to clean up orphaned resources from a failed restore job"""
    delete_volume: bool = Field(default=False, description="Also delete the orphaned volume (default: preserve for manual recovery)")


class RestoreRetryRequest(BaseModel):
    """Request to retry a failed restore job from the failed step"""
    confirm_destructive: Optional[str] = None  # Required for REPLACE mode
    ip_strategy_override: Optional[str] = Field(default=None, pattern="^(NEW_IPS|TRY_SAME_IPS|SAME_IPS_OR_FAIL|MANUAL_IP)$")


# ============================================================================
# OpenStack Client for Restore Operations
# ============================================================================

class RestoreOpenStackClient:
    """
    Handles OpenStack API calls needed for restore.
    Authenticates as service user scoped to the target project.
    """

    def __init__(self):
        self.session: Optional[http_requests.Session] = None
        self.token: Optional[str] = None
        self.nova_endpoint: Optional[str] = None
        self.cinder_endpoint: Optional[str] = None
        self.neutron_endpoint: Optional[str] = None
        self.keystone_url = PF9_AUTH_URL.rstrip("/")

    def _new_session(self) -> http_requests.Session:
        s = http_requests.Session()
        s.verify = os.getenv("PF9_VERIFY_TLS", "true").lower() in ("1", "true", "yes")
        return s

    def authenticate_admin(self) -> http_requests.Session:
        """Get admin-scoped session for listing/reading."""
        session = self._new_session()
        auth_url = f"{self.keystone_url}/auth/tokens"
        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": PF9_USERNAME,
                            "domain": {"name": PF9_USER_DOMAIN},
                            "password": PF9_PASSWORD,
                        }
                    },
                },
                "scope": {
                    "project": {
                        "name": PF9_PROJECT_NAME,
                        "domain": {"name": PF9_PROJECT_DOMAIN},
                    }
                },
            }
        }
        r = session.post(auth_url, json=payload, timeout=60)
        r.raise_for_status()
        token = r.headers["X-Subject-Token"]
        session.headers.update({"X-Auth-Token": token})
        catalog = r.json().get("token", {}).get("catalog", [])
        self._extract_endpoints(catalog)
        self.session = session
        self.token = token
        return session

    def authenticate_service_user(self, project_id: str) -> http_requests.Session:
        """
        Authenticate as the service user scoped to a specific project.
        This is required for create operations in the target tenant.
        Falls back to admin auth if service user is not configured.
        """
        if not SNAPSHOT_SERVICE_USER_EMAIL or not SNAPSHOT_SERVICE_USER_PASSWORD:
            logger.warning("Service user not configured, using admin credentials")
            return self._authenticate_project_scoped(
                PF9_USERNAME, PF9_PASSWORD, PF9_USER_DOMAIN, project_id
            )

        # First ensure service user has admin role on the project
        admin_session = self.authenticate_admin()
        self._ensure_service_user_role(admin_session, project_id)

        return self._authenticate_project_scoped(
            SNAPSHOT_SERVICE_USER_EMAIL,
            SNAPSHOT_SERVICE_USER_PASSWORD,
            SNAPSHOT_SERVICE_USER_DOMAIN,
            project_id,
        )

    def _authenticate_project_scoped(
        self, username: str, password: str, user_domain: str, project_id: str
    ) -> http_requests.Session:
        session = self._new_session()
        auth_url = f"{self.keystone_url}/auth/tokens"
        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": username,
                            "domain": {"id": user_domain} if user_domain == "default" else {"name": user_domain},
                            "password": password,
                        }
                    },
                },
                "scope": {"project": {"id": project_id}},
            }
        }
        r = session.post(auth_url, json=payload, timeout=60)
        r.raise_for_status()
        token = r.headers["X-Subject-Token"]
        session.headers.update({"X-Auth-Token": token})
        catalog = r.json().get("token", {}).get("catalog", [])
        self._extract_endpoints(catalog)
        self.session = session
        self.token = token
        return session

    def _ensure_service_user_role(self, admin_session: http_requests.Session, project_id: str):
        """Ensure the service user has admin role on the project (same as snapshot system)."""
        # Find user
        url = f"{self.keystone_url}/users?name={SNAPSHOT_SERVICE_USER_EMAIL}"
        r = admin_session.get(url, timeout=60)
        r.raise_for_status()
        users = r.json().get("users", [])
        if not users:
            raise RuntimeError(f"Service user '{SNAPSHOT_SERVICE_USER_EMAIL}' not found in Keystone")
        user_id = users[0]["id"]

        # Find admin role
        url = f"{self.keystone_url}/roles?name=admin"
        r = admin_session.get(url, timeout=60)
        r.raise_for_status()
        roles = r.json().get("roles", [])
        if not roles:
            raise RuntimeError("'admin' role not found in Keystone")
        role_id = roles[0]["id"]

        # Check if already assigned
        url = f"{self.keystone_url}/projects/{project_id}/users/{user_id}/roles/{role_id}"
        r = admin_session.head(url, timeout=30)
        if r.status_code == 204:
            return  # Already has role

        # Assign
        r = admin_session.put(url, timeout=30)
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"Failed to assign admin role: {r.status_code} {r.text}")
        logger.info(f"Granted admin role to service user on project {project_id}")

    def _extract_endpoints(self, catalog: list):
        for svc in catalog:
            stype = svc.get("type")
            for ep in svc.get("endpoints", []):
                if ep.get("interface") == "public":
                    url = ep["url"].rstrip("/")
                    if stype == "compute":
                        self.nova_endpoint = url
                    elif stype == "network":
                        self.neutron_endpoint = url
                    elif stype in ("volumev3", "volumev2", "volume"):
                        self.cinder_endpoint = url

    # --- Cinder operations ---

    def _cinder_url(self, project_id: str, path: str) -> str:
        """Build Cinder URL scoped to the correct project."""
        if not self.cinder_endpoint:
            raise RuntimeError("Cinder endpoint not discovered")
        base = "/".join(self.cinder_endpoint.split("/")[:-1])
        return f"{base}/{project_id}{path}"

    def create_volume_from_snapshot(
        self, session: http_requests.Session, project_id: str,
        snapshot_id: str, name: str, size_gb: int, volume_type: str = None
    ) -> dict:
        url = self._cinder_url(project_id, "/volumes")
        payload = {
            "volume": {
                "snapshot_id": snapshot_id,
                "name": name,
                "size": size_gb,
            }
        }
        if volume_type:
            payload["volume"]["volume_type"] = volume_type
        r = session.post(url, json=payload, timeout=120)
        r.raise_for_status()
        return r.json().get("volume", {})

    def get_volume(self, session: http_requests.Session, project_id: str, volume_id: str) -> dict:
        url = self._cinder_url(project_id, f"/volumes/{volume_id}")
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("volume", {})

    def wait_volume_available(
        self, session: http_requests.Session, project_id: str,
        volume_id: str, timeout_secs: int = 600, poll_interval: int = 5
    ) -> dict:
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            vol = self.get_volume(session, project_id, volume_id)
            st = vol.get("status", "")
            if st == "available":
                return vol
            if st == "error":
                raise RuntimeError(f"Volume {volume_id} entered error state")
            time.sleep(poll_interval)
        raise RuntimeError(f"Volume {volume_id} not available after {timeout_secs}s")

    # --- Neutron operations ---

    def create_port(
        self, session: http_requests.Session, network_id: str,
        subnet_id: str = None, fixed_ip: str = None,
        security_groups: list = None, project_id: str = None
    ) -> dict:
        if not self.neutron_endpoint:
            raise RuntimeError("Neutron endpoint not discovered")
        url = f"{self.neutron_endpoint}/v2.0/ports"
        port_body: Dict[str, Any] = {"network_id": network_id}
        if project_id:
            port_body["project_id"] = project_id
        if fixed_ip and subnet_id:
            port_body["fixed_ips"] = [{"subnet_id": subnet_id, "ip_address": fixed_ip}]
        elif subnet_id:
            port_body["fixed_ips"] = [{"subnet_id": subnet_id}]
        if security_groups:
            port_body["security_groups"] = security_groups
        r = session.post(url, json={"port": port_body}, timeout=60)
        r.raise_for_status()
        return r.json().get("port", {})

    def check_ip_available(
        self, session: http_requests.Session, network_id: str, ip_address: str
    ) -> bool:
        """Check if an IP address is available (not assigned to any port)."""
        if not self.neutron_endpoint:
            raise RuntimeError("Neutron endpoint not discovered")
        url = f"{self.neutron_endpoint}/v2.0/ports?network_id={network_id}&fixed_ips=ip_address%3D{ip_address}"
        r = session.get(url, timeout=60)
        r.raise_for_status()
        ports = r.json().get("ports", [])
        return len(ports) == 0

    def delete_port(self, session: http_requests.Session, port_id: str):
        if not self.neutron_endpoint:
            raise RuntimeError("Neutron endpoint not discovered")
        url = f"{self.neutron_endpoint}/v2.0/ports/{port_id}"
        r = session.delete(url, timeout=60)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def list_ports_by_device(self, session: http_requests.Session, device_id: str) -> list:
        """List all ports attached to a specific device (VM)."""
        if not self.neutron_endpoint:
            raise RuntimeError("Neutron endpoint not discovered")
        url = f"{self.neutron_endpoint}/v2.0/ports?device_id={device_id}"
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("ports", [])

    def list_ports_by_network_and_ip(self, session: http_requests.Session, network_id: str, ip_address: str) -> list:
        """List ports matching a specific network+IP combination."""
        if not self.neutron_endpoint:
            raise RuntimeError("Neutron endpoint not discovered")
        url = (f"{self.neutron_endpoint}/v2.0/ports"
               f"?network_id={network_id}&fixed_ips=ip_address%3D{ip_address}")
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("ports", [])

    def delete_volume(self, session: http_requests.Session, project_id: str, volume_id: str):
        """Delete a volume by ID."""
        url = self._cinder_url(project_id, f"/volumes/{volume_id}")
        r = session.delete(url, timeout=60)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    # --- Nova operations ---

    def create_server(
        self, session: http_requests.Session, name: str,
        flavor_id: str, port_ids: list, block_device_mapping: list = None,
        image_id: str = None, availability_zone: str = None,
        user_data: str = None,
    ) -> dict:
        if not self.nova_endpoint:
            raise RuntimeError("Nova endpoint not discovered")
        url = f"{self.nova_endpoint}/servers"
        server_body: Dict[str, Any] = {
            "name": name,
            "flavorRef": flavor_id,
            "networks": [{"port": pid} for pid in port_ids],
        }
        if block_device_mapping:
            server_body["block_device_mapping_v2"] = block_device_mapping
        if image_id:
            server_body["imageRef"] = image_id
        if availability_zone:
            server_body["availability_zone"] = availability_zone
        if user_data:
            server_body["user_data"] = user_data
        r = session.post(url, json={"server": server_body}, timeout=120)
        r.raise_for_status()
        return r.json().get("server", {})

    def get_server(self, session: http_requests.Session, server_id: str) -> dict:
        if not self.nova_endpoint:
            raise RuntimeError("Nova endpoint not discovered")
        url = f"{self.nova_endpoint}/servers/{server_id}"
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("server", {})

    def get_server_user_data(self, session: http_requests.Session, server_id: str) -> Optional[str]:
        """
        Fetch the base64-encoded user_data (cloud-init) associated with a VM.
        Uses Nova microversion 2.3+ which exposes OS-EXT-SRV-ATTR:user_data.
        Returns the base64 string or None if unavailable.
        """
        if not self.nova_endpoint:
            return None
        url = f"{self.nova_endpoint}/servers/{server_id}"
        try:
            r = session.get(
                url, timeout=60,
                headers={"X-OpenStack-Nova-API-Version": "2.3"},
            )
            r.raise_for_status()
            server = r.json().get("server", {})
            user_data = server.get("OS-EXT-SRV-ATTR:user_data")
            if user_data:
                logger.info(f"Retrieved user_data for server {server_id} ({len(user_data)} chars)")
            return user_data
        except Exception as e:
            logger.warning(f"Could not retrieve user_data for {server_id}: {e}")
            return None

    def wait_server_active(
        self, session: http_requests.Session, server_id: str,
        timeout_secs: int = 600, poll_interval: int = 5
    ) -> dict:
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            server = self.get_server(session, server_id)
            st = server.get("status", "").upper()
            if st == "ACTIVE":
                return server
            if st == "ERROR":
                fault = server.get("fault", {}).get("message", "Unknown error")
                raise RuntimeError(f"Server entered ERROR state: {fault}")
            time.sleep(poll_interval)
        raise RuntimeError(f"Server {server_id} not ACTIVE after {timeout_secs}s")

    def delete_server(self, session: http_requests.Session, server_id: str):
        if not self.nova_endpoint:
            raise RuntimeError("Nova endpoint not discovered")
        url = f"{self.nova_endpoint}/servers/{server_id}"
        r = session.delete(url, timeout=120)
        if r.status_code not in (200, 204, 404):
            r.raise_for_status()

    def wait_server_deleted(
        self, session: http_requests.Session, server_id: str,
        timeout_secs: int = 300, poll_interval: int = 5
    ) -> None:
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            try:
                server = self.get_server(session, server_id)
                st = server.get("status", "").upper()
                if st == "DELETED":
                    return
            except Exception:
                return  # 404 means deleted
            time.sleep(poll_interval)
        raise RuntimeError(f"Server {server_id} not deleted after {timeout_secs}s")

    # --- Nova quota ---

    def get_project_quota(self, session: http_requests.Session, project_id: str) -> dict:
        """Get project quota limits and usage from Nova."""
        if not self.nova_endpoint:
            raise RuntimeError("Nova endpoint not discovered")
        url = f"{self.nova_endpoint}/os-quota-sets/{project_id}/detail"
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("quota_set", {})

    def get_volume_quota(self, session: http_requests.Session, project_id: str) -> dict:
        """Get volume quota limits and usage from Cinder."""
        url = self._cinder_url(project_id, f"/os-quota-sets/{project_id}?usage=true")
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("quota_set", {})

    def get_snapshot_detail(self, session: http_requests.Session, project_id: str, snapshot_id: str) -> dict:
        """Get details of a specific Cinder snapshot."""
        url = self._cinder_url(project_id, f"/snapshots/{snapshot_id}")
        r = session.get(url, timeout=60)
        r.raise_for_status()
        return r.json().get("snapshot", {})

    def delete_snapshot(self, session: http_requests.Session, project_id: str, snapshot_id: str):
        """Delete a Cinder snapshot by ID."""
        url = self._cinder_url(project_id, f"/snapshots/{snapshot_id}")
        r = session.delete(url, timeout=60)
        if r.status_code not in (200, 202, 204, 404):
            r.raise_for_status()

    def get_volume_detail(self, session: http_requests.Session, project_id: str, volume_id: str) -> dict:
        """Get volume details including attachment info."""
        url = self._cinder_url(project_id, f"/volumes/{volume_id}")
        r = session.get(url, timeout=60)
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json().get("volume", {})


# ============================================================================
# Restore Planner — builds the action plan from DB + live state
# ============================================================================

class RestorePlanner:
    """
    Builds a restore plan by querying the DB for VM configuration
    and validating against live OpenStack state.
    """

    def __init__(self, db_conn_fn: Callable, os_client: RestoreOpenStackClient):
        self.db_conn_fn = db_conn_fn
        self.os_client = os_client

    def build_plan(self, req: RestorePlanRequest, username: str) -> dict:
        """
        Build a restore plan. Returns the plan dict to be stored in restore_jobs.plan_json.
        """
        conn = self.db_conn_fn()
        try:
            # 1. Fetch VM baseline from DB
            vm_data = self._get_vm_from_db(conn, req.vm_id)
            if not vm_data:
                raise HTTPException(404, f"VM {req.vm_id} not found in inventory")

            # 2. Fetch VM's network configuration from DB (ports)
            network_config = self._get_vm_networks(conn, req.vm_id)

            # 3. Fetch the restore point (snapshot) info from DB
            restore_point = self._get_snapshot_from_db(conn, req.restore_point_id)
            if not restore_point:
                raise HTTPException(404, f"Snapshot {req.restore_point_id} not found in inventory")

            # 4. Detect boot mode
            boot_mode = self._detect_boot_mode(conn, req.vm_id, vm_data)

            if boot_mode != "BOOT_FROM_VOLUME":
                raise HTTPException(
                    400,
                    f"VM {vm_data.get('name', req.vm_id)} uses {boot_mode}. "
                    f"Only BOOT_FROM_VOLUME restore is currently supported."
                )

            # 5. Get flavor info
            flavor_data = self._get_flavor_from_db(conn, vm_data.get("flavor_id"))

            # 6. Get the snapshot's volume info for size/type
            source_volume = self._get_volume_from_db(conn, restore_point.get("volume_id"))

            # 7. Generate VM name
            new_vm_name = req.new_vm_name
            if not new_vm_name:
                original_name = vm_data.get("name", "vm")
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
                if req.mode == "REPLACE":
                    new_vm_name = original_name
                else:
                    new_vm_name = f"{original_name}-restored-{timestamp}"

            # 8. Build network plan
            network_plan = self._build_network_plan(network_config, req.ip_strategy, req.manual_ips)

            # 9. Build action steps
            actions = self._build_actions(
                boot_mode, req.mode, network_plan, new_vm_name,
                cleanup_old_storage=req.cleanup_old_storage,
                delete_source_snapshot=req.delete_source_snapshot,
                source_volume_id=source_volume.get("id") if source_volume else None,
                snapshot_id=req.restore_point_id,
            )

            # 10. Build warnings
            warnings = self._build_warnings(
                req.mode, req.ip_strategy, network_plan, boot_mode, vm_data
            )

            # 11. Try to fetch quota from OpenStack (best effort)
            quota_check = {"can_create_new_vm": True, "reasons": []}
            admin_session = None
            try:
                admin_session = self.os_client.authenticate_admin()
                nova_quota = self.os_client.get_project_quota(admin_session, req.project_id)
                cinder_quota = self.os_client.get_volume_quota(admin_session, req.project_id)
                quota_check = self._check_quota(
                    nova_quota, cinder_quota, flavor_data, source_volume, req.mode
                )
            except Exception as e:
                logger.warning(f"Could not fetch quota: {e}")
                quota_check["reasons"].append(f"Could not verify quota: {str(e)}")

            # 12. Fetch original VM's user_data (cloud-init) so it can be re-applied
            original_user_data = None
            try:
                if not admin_session:
                    admin_session = self.os_client.authenticate_admin()
                original_user_data = self.os_client.get_server_user_data(admin_session, req.vm_id)
            except Exception as e:
                logger.warning(f"Could not fetch user_data for VM {req.vm_id}: {e}")

            # Build the plan
            plan = {
                "plan_id": str(uuid.uuid4()),
                "eligible": boot_mode == "BOOT_FROM_VOLUME" and quota_check["can_create_new_vm"],
                "boot_mode": boot_mode,
                "mode": req.mode,
                "ip_strategy": req.ip_strategy,
                "vm": {
                    "id": req.vm_id,
                    "name": vm_data.get("name"),
                    "status": vm_data.get("status"),
                    "flavor_id": vm_data.get("flavor_id"),
                    "flavor_name": flavor_data.get("name") if flavor_data else None,
                    "flavor_vcpus": flavor_data.get("vcpus") if flavor_data else None,
                    "flavor_ram_mb": flavor_data.get("ram_mb") if flavor_data else None,
                    "flavor_disk_gb": flavor_data.get("disk_gb") if flavor_data else None,
                    "user_data": original_user_data,  # base64-encoded cloud-init, if any
                },
                "restore_point": {
                    "id": req.restore_point_id,
                    "name": restore_point.get("name"),
                    "volume_id": restore_point.get("volume_id"),
                    "size_gb": restore_point.get("size_gb") or (source_volume.get("size_gb") if source_volume else None),
                    "created_at": str(restore_point.get("created_at")) if restore_point.get("created_at") else None,
                    "status": restore_point.get("status"),
                },
                "new_vm_name": new_vm_name,
                "project_id": req.project_id,
                "quota_check": quota_check,
                "network_plan": network_plan,
                "actions": actions,
                "warnings": warnings,
                "source_volume": {
                    "id": source_volume.get("id") if source_volume else None,
                    "size_gb": source_volume.get("size_gb") if source_volume else None,
                    "volume_type": source_volume.get("volume_type") if source_volume else None,
                },
                "security_group_ids": req.security_group_ids or [],
                "cleanup_old_storage": req.cleanup_old_storage,
                "delete_source_snapshot": req.delete_source_snapshot,
            }

            # Store the plan as a PLANNED job in DB
            job_id = self._store_plan(conn, plan, req, username, vm_data, restore_point)
            plan["job_id"] = job_id

            return plan

        finally:
            conn.close()

    def _get_vm_from_db(self, conn, vm_id: str) -> Optional[dict]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id, name, project_id, status, vm_state, flavor_id,
                          hypervisor_hostname, created_at, raw_json
                   FROM servers WHERE id = %s""",
                (vm_id,),
            )
            return cur.fetchone()

    def _get_vm_networks(self, conn, vm_id: str) -> list:
        """Get all ports attached to this VM from the DB."""
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT p.id as port_id, p.network_id, p.mac_address,
                          p.ip_addresses, p.raw_json,
                          n.name as network_name,
                          s.id as subnet_id, s.cidr, s.name as subnet_name
                   FROM ports p
                   LEFT JOIN networks n ON p.network_id = n.id
                   LEFT JOIN subnets s ON n.id = s.network_id
                   WHERE p.device_id = %s AND p.device_owner LIKE 'compute:%%'""",
                (vm_id,),
            )
            rows = cur.fetchall()

        # Deduplicate by port_id (a port may join multiple subnets)
        ports_map = {}
        for row in rows:
            pid = row["port_id"]
            if pid not in ports_map:
                ports_map[pid] = {
                    "port_id": pid,
                    "network_id": row["network_id"],
                    "network_name": row["network_name"],
                    "mac_address": row["mac_address"],
                    "ip_addresses": row["ip_addresses"],
                    "subnets": [],
                }
            if row["subnet_id"]:
                ports_map[pid]["subnets"].append({
                    "subnet_id": row["subnet_id"],
                    "subnet_name": row["subnet_name"],
                    "cidr": row["cidr"],
                })

        return list(ports_map.values())

    def _get_snapshot_from_db(self, conn, snapshot_id: str) -> Optional[dict]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id, name, description, project_id, volume_id,
                          size_gb, status, created_at, raw_json
                   FROM snapshots WHERE id = %s""",
                (snapshot_id,),
            )
            return cur.fetchone()

    def _get_volume_from_db(self, conn, volume_id: str) -> Optional[dict]:
        if not volume_id:
            return None
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id, name, project_id, size_gb, status,
                          volume_type, bootable, raw_json
                   FROM volumes WHERE id = %s""",
                (volume_id,),
            )
            return cur.fetchone()

    def _get_flavor_from_db(self, conn, flavor_id: str) -> Optional[dict]:
        if not flavor_id:
            return None
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id, name, vcpus, ram_mb, disk_gb, ephemeral_gb, swap_mb
                   FROM flavors WHERE id = %s""",
                (flavor_id,),
            )
            return cur.fetchone()

    def _detect_boot_mode(self, conn, vm_id: str, vm_data: dict) -> str:
        """
        Detect if VM boots from volume or image.
        Check raw_json for image ref and block device mapping.
        """
        raw = vm_data.get("raw_json") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}

        # Check image field - if empty dict or empty string, it's boot-from-volume
        image = raw.get("image", "")
        if not image or image == "":
            return "BOOT_FROM_VOLUME"

        # If image is a dict with an "id" field, check if there's a root volume
        # Some VMs show an image ref but actually boot from volume via BDM
        volumes_attached = raw.get("os-extended-volumes:volumes_attached", [])
        if volumes_attached:
            # Check if any attached volume is bootable
            for va in volumes_attached:
                vol_id = va.get("id")
                vol = self._get_volume_from_db(conn, vol_id)
                if vol and vol.get("bootable"):
                    return "BOOT_FROM_VOLUME"

        return "BOOT_FROM_IMAGE"

    def _build_network_plan(self, network_config: list, ip_strategy: str, manual_ips: Optional[Dict[str, str]] = None) -> list:
        plan = []
        for port_info in network_config:
            # Parse existing IPs
            ips = port_info.get("ip_addresses") or []
            if isinstance(ips, str):
                try:
                    ips = json.loads(ips)
                except Exception:
                    ips = []

            for ip_entry in ips if ips else [{}]:
                ip_addr = ip_entry.get("ip_address") if isinstance(ip_entry, dict) else None
                subnet = ip_entry.get("subnet_id") if isinstance(ip_entry, dict) else None

                # Pick subnet from port's subnets if not in ip_entry
                if not subnet and port_info.get("subnets"):
                    subnet = port_info["subnets"][0].get("subnet_id")

                entry = {
                    "network_id": port_info["network_id"],
                    "network_name": port_info.get("network_name"),
                    "subnet_id": subnet,
                    "original_port_id": port_info["port_id"],
                    "original_fixed_ip": ip_addr,
                    "will_request_fixed_ip": False,
                    "requested_ip": None,
                    "note": "",
                }

                if ip_strategy == "NEW_IPS":
                    entry["note"] = "Allocating new IP (auto-assign)"
                elif ip_strategy == "MANUAL_IP":
                    net_id = port_info["network_id"]
                    manual_ip = (manual_ips or {}).get(net_id)
                    if manual_ip:
                        entry["will_request_fixed_ip"] = True
                        entry["requested_ip"] = manual_ip
                        entry["note"] = f"Manual IP: {manual_ip}"
                    else:
                        entry["note"] = "No manual IP specified; allocating new IP (auto-assign)"
                elif ip_strategy in ("TRY_SAME_IPS", "SAME_IPS_OR_FAIL"):
                    if ip_addr:
                        entry["will_request_fixed_ip"] = True
                        entry["requested_ip"] = ip_addr
                        entry["note"] = f"Will attempt to assign {ip_addr}"
                    else:
                        entry["note"] = "No original IP found; allocating new IP"

                plan.append(entry)

        # If no networks found at all, add a warning placeholder
        if not plan:
            plan.append({
                "network_id": None,
                "network_name": None,
                "subnet_id": None,
                "original_port_id": None,
                "original_fixed_ip": None,
                "will_request_fixed_ip": False,
                "requested_ip": None,
                "note": "No network configuration found for this VM in the database",
            })

        return plan

    def _build_actions(
        self, boot_mode: str, mode: str, network_plan: list, new_name: str,
        cleanup_old_storage: bool = False, delete_source_snapshot: bool = False,
        source_volume_id: str = None, snapshot_id: str = None,
    ) -> list:
        actions = [
            {"step": "VALIDATE_LIVE_STATE", "details": {"description": "Verify VM and snapshot still exist in OpenStack"}},
            {"step": "ENSURE_SERVICE_USER", "details": {"description": "Ensure service user has access to target project"}},
            {"step": "QUOTA_CHECK", "details": {"description": "Verify sufficient quota for restore operation"}},
        ]

        if mode == "REPLACE":
            actions.append({
                "step": "DELETE_EXISTING_VM",
                "details": {"description": "Delete the existing VM (destructive, irreversible)"},
            })
            actions.append({
                "step": "WAIT_VM_DELETED",
                "details": {"description": "Wait for existing VM to be fully removed"},
            })
            # Explicitly clean up old ports to release IPs before creating new ones
            old_port_ids = [n.get("original_port_id") for n in network_plan if n.get("original_port_id")]
            if old_port_ids:
                actions.append({
                    "step": "CLEANUP_OLD_PORTS",
                    "details": {
                        "description": f"Release {len(old_port_ids)} old port(s) to free IP addresses",
                        "port_ids": old_port_ids,
                    },
                })

        if boot_mode == "BOOT_FROM_VOLUME":
            actions.append({
                "step": "CREATE_VOLUME_FROM_SNAPSHOT",
                "details": {"description": "Create a new bootable volume from the snapshot"},
            })
            actions.append({
                "step": "WAIT_VOLUME_AVAILABLE",
                "details": {"description": "Wait for the new volume to become available"},
            })

        valid_nets = [n for n in network_plan if n.get("network_id")]
        if valid_nets:
            actions.append({
                "step": "CREATE_PORTS",
                "details": {
                    "description": f"Create {len(valid_nets)} network port(s)",
                    "port_count": len(valid_nets),
                },
            })

        actions.append({
            "step": "CREATE_SERVER",
            "details": {"description": f"Create VM '{new_name}' with restored configuration"},
        })
        actions.append({
            "step": "WAIT_SERVER_ACTIVE",
            "details": {"description": "Wait for VM to reach ACTIVE state"},
        })
        actions.append({
            "step": "FINALIZE",
            "details": {"description": "Record results and update audit trail"},
        })

        # Optional post-restore storage cleanup
        storage_items = []
        if cleanup_old_storage and mode == "REPLACE" and source_volume_id:
            storage_items.append(f"old volume {source_volume_id[:12]}…")
        if delete_source_snapshot and snapshot_id:
            storage_items.append(f"source snapshot {snapshot_id[:12]}…")
        if storage_items:
            actions.append({
                "step": "CLEANUP_OLD_STORAGE",
                "details": {
                    "description": f"Delete orphaned storage: {', '.join(storage_items)}",
                    "delete_old_volume": cleanup_old_storage and mode == "REPLACE",
                    "old_volume_id": source_volume_id if (cleanup_old_storage and mode == "REPLACE") else None,
                    "delete_source_snapshot": delete_source_snapshot,
                    "source_snapshot_id": snapshot_id if delete_source_snapshot else None,
                },
            })

        return actions

    def _build_warnings(
        self, mode: str, ip_strategy: str, network_plan: list,
        boot_mode: str, vm_data: dict,
    ) -> list:
        warnings = []

        if mode == "REPLACE":
            warnings.append(
                f"⚠️ DESTRUCTIVE: This will DELETE VM '{vm_data.get('name')}' before restoring. "
                f"This action cannot be undone."
            )

        if ip_strategy == "TRY_SAME_IPS":
            warnings.append(
                "IP preservation is best-effort. If an original IP is taken, a new IP will be assigned."
            )
        elif ip_strategy == "SAME_IPS_OR_FAIL":
            warnings.append(
                "IP preservation is strict. The restore will FAIL if any original IP is unavailable."
            )
        elif ip_strategy == "MANUAL_IP":
            pass  # No warning needed — UI presents only available IPs from Neutron

        no_net = [n for n in network_plan if not n.get("network_id")]
        if no_net:
            warnings.append(
                "No network configuration found in DB for this VM. "
                "The restored VM may not have network connectivity."
            )

        return warnings

    def _check_quota(
        self, nova_quota: dict, cinder_quota: dict,
        flavor: Optional[dict], volume: Optional[dict], mode: str,
    ) -> dict:
        result = {"can_create_new_vm": True, "reasons": [], "details": {}}

        # For REPLACE mode, we're freeing resources first, so quota is less of a concern
        # but we still check

        # Nova quota: instances, cores, ram
        for resource, label in [("instances", "Instances"), ("cores", "vCPUs"), ("ram", "RAM (MB)")]:
            q = nova_quota.get(resource, {})
            if isinstance(q, dict):
                limit = q.get("limit", -1)
                in_use = q.get("in_use", 0)
                if limit > 0:
                    remaining = limit - in_use
                    result["details"][resource] = {"limit": limit, "in_use": in_use, "remaining": remaining}

                    needed = 1 if resource == "instances" else (
                        flavor.get("vcpus", 0) if resource == "cores" and flavor else
                        flavor.get("ram_mb", 0) if resource == "ram" and flavor else 0
                    )
                    if mode == "NEW" and remaining < needed:
                        result["can_create_new_vm"] = False
                        result["reasons"].append(
                            f"Insufficient {label}: need {needed}, only {remaining} available"
                        )

        # Cinder quota: volumes, gigabytes
        for resource, label in [("volumes", "Volumes"), ("gigabytes", "Storage (GB)")]:
            q = cinder_quota.get(resource, {})
            if isinstance(q, dict):
                limit = q.get("limit", -1)
                in_use = q.get("in_use", 0)
                if limit > 0:
                    remaining = limit - in_use
                    result["details"][resource] = {"limit": limit, "in_use": in_use, "remaining": remaining}

                    needed = 1 if resource == "volumes" else (
                        volume.get("size_gb", 0) if volume else 0
                    )
                    if mode == "NEW" and remaining < needed:
                        result["can_create_new_vm"] = False
                        result["reasons"].append(
                            f"Insufficient {label}: need {needed}, only {remaining} available"
                        )

        return result

    def _store_plan(
        self, conn, plan: dict, req: RestorePlanRequest,
        username: str, vm_data: dict, restore_point: dict,
    ) -> str:
        """Store the plan as a PLANNED restore job and pre-create step rows."""
        job_id = plan["plan_id"]
        project_name = None
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT name FROM projects WHERE id = %s", (req.project_id,))
            row = cur.fetchone()
            if row:
                project_name = row["name"]

        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO restore_jobs
                   (id, created_by, project_id, project_name, vm_id, vm_name,
                    restore_point_id, restore_point_name, mode, ip_strategy,
                    requested_name, boot_mode, status, plan_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PLANNED',%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    job_id, username, req.project_id, project_name,
                    req.vm_id, vm_data.get("name"),
                    req.restore_point_id, restore_point.get("name"),
                    req.mode, req.ip_strategy,
                    plan.get("new_vm_name"), plan["boot_mode"],
                    Json(plan),
                ),
            )

            # Pre-create step rows
            for idx, action in enumerate(plan["actions"]):
                cur.execute(
                    """INSERT INTO restore_job_steps
                       (job_id, step_order, step_name, status, details_json)
                       VALUES (%s, %s, %s, 'PENDING', %s)""",
                    (job_id, idx + 1, action["step"], Json(action.get("details", {}))),
                )

        conn.commit()
        return job_id


# ============================================================================
# Restore Executor — runs the state machine as a background task
# ============================================================================

class RestoreExecutor:
    """
    Executes a restore job step-by-step, updating the DB as it goes.
    Designed to run as a background asyncio task inside the API process.
    """

    def __init__(self, db_conn_fn: Callable, os_client: RestoreOpenStackClient):
        self.db_conn_fn = db_conn_fn
        self.os_client = os_client

    async def execute_job(self, job_id: str):
        """Main entry: run all steps for a job."""
        # Each DB operation uses its own connection for thread-safety
        conn = self.db_conn_fn()
        try:
            # Load the job
            job = self._load_job(conn, job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return
            if job["status"] not in ("PENDING",):
                logger.error(f"Job {job_id} in unexpected status: {job['status']}")
                return

            plan = job["plan_json"]
            if isinstance(plan, str):
                plan = json.loads(plan)

            project_id = job["project_id"]

            # Mark job as RUNNING
            self._update_job_status(conn, job_id, "RUNNING")
        finally:
            conn.close()

        # Authenticate service user for this project
        try:
            session = self.os_client.authenticate_service_user(project_id)
        except Exception as e:
            self._with_conn(lambda c: self._fail_job(c, job_id, f"Authentication failed: {e}"))
            return

        # Track created resources for rollback
        created_resources = {
            "volume_id": None,
            "port_ids": [],
            "server_id": None,
        }

        # Load steps (fresh conn)
        steps = self._with_conn(lambda c: self._load_steps(c, job_id))

        # Execute each step
        for step in steps:
            # Check for cancellation (fresh conn)
            job_refresh = self._with_conn(lambda c: self._load_job(c, job_id))
            if job_refresh and job_refresh["status"] == "CANCELED":
                logger.info(f"Job {job_id} was canceled, stopping execution")
                await self._cleanup_resources(session, project_id, created_resources)
                return

            step_name = step["step_name"]
            step_id = step["id"]

            self._with_conn(lambda c: self._update_step_status(c, job_id, step_id, "RUNNING"))
            self._with_conn(lambda c: self._heartbeat(c, job_id))

            try:
                result = await self._execute_step(
                    session, project_id, plan, step_name, created_resources, job
                )
                self._with_conn(
                    lambda c: self._update_step_status(c, job_id, step_id, "SUCCEEDED", details=result)
                )
            except Exception as e:
                logger.error(f"Step {step_name} failed for job {job_id}: {e}")
                self._with_conn(
                    lambda c: self._update_step_status(c, job_id, step_id, "FAILED", error=str(e))
                )
                # Attempt cleanup
                await self._cleanup_resources(session, project_id, created_resources)
                self._with_conn(lambda c: self._fail_job(c, job_id, f"Step {step_name} failed: {e}"))
                return

        # All steps succeeded
        self._with_conn(lambda c: self._complete_job(c, job_id, created_resources))

    def _with_conn(self, fn):
        """Execute a function with a fresh DB connection that is closed after use."""
        conn = self.db_conn_fn()
        try:
            return fn(conn)
        finally:
            conn.close()

    async def _execute_step(
        self, session: http_requests.Session, project_id: str,
        plan: dict, step_name: str, resources: dict, job: dict,
    ) -> dict:
        """Execute a single step and return result details."""

        if step_name == "VALIDATE_LIVE_STATE":
            return await asyncio.to_thread(
                self._step_validate, session, project_id, plan
            )

        elif step_name == "ENSURE_SERVICE_USER":
            # Already done during auth, but we log it
            return {"message": "Service user authenticated and scoped to project"}

        elif step_name == "QUOTA_CHECK":
            return await asyncio.to_thread(
                self._step_quota_check, session, project_id, plan
            )

        elif step_name == "DELETE_EXISTING_VM":
            return await asyncio.to_thread(
                self._step_delete_vm, session, plan["vm"]["id"]
            )

        elif step_name == "WAIT_VM_DELETED":
            return await asyncio.to_thread(
                self._step_wait_vm_deleted, session, plan["vm"]["id"]
            )

        elif step_name == "CLEANUP_OLD_PORTS":
            return await asyncio.to_thread(
                self._step_cleanup_old_ports, session, plan
            )

        elif step_name == "CREATE_VOLUME_FROM_SNAPSHOT":
            result = await asyncio.to_thread(
                self._step_create_volume, session, project_id, plan
            )
            resources["volume_id"] = result.get("volume_id")
            return result

        elif step_name == "WAIT_VOLUME_AVAILABLE":
            return await asyncio.to_thread(
                self._step_wait_volume, session, project_id, resources["volume_id"]
            )

        elif step_name == "CREATE_PORTS":
            result = await asyncio.to_thread(
                self._step_create_ports, session, project_id, plan
            )
            resources["port_ids"] = result.get("port_ids", [])
            return result

        elif step_name == "CREATE_SERVER":
            result = await asyncio.to_thread(
                self._step_create_server, session, plan, resources
            )
            resources["server_id"] = result.get("server_id")
            return result

        elif step_name == "WAIT_SERVER_ACTIVE":
            return await asyncio.to_thread(
                self._step_wait_server, session, resources["server_id"]
            )

        elif step_name == "FINALIZE":
            return {"message": "Restore completed successfully", "resources": resources}

        elif step_name == "CLEANUP_OLD_STORAGE":
            return await asyncio.to_thread(
                self._step_cleanup_old_storage, session, project_id, plan
            )

        else:
            return {"message": f"Unknown step {step_name}, skipped"}

    # --- Individual step implementations ---

    def _step_validate(self, session, project_id, plan) -> dict:
        """Validate that the snapshot still exists and is available."""
        snapshot_id = plan["restore_point"]["id"]
        snap = self.os_client.get_snapshot_detail(session, project_id, snapshot_id)
        snap_status = snap.get("status", "")
        if snap_status != "available":
            raise RuntimeError(f"Snapshot {snapshot_id} is not available (status: {snap_status})")
        return {"snapshot_status": snap_status, "snapshot_size_gb": snap.get("size")}

    def _step_quota_check(self, session, project_id, plan) -> dict:
        """Re-verify quota at execution time."""
        nova_quota = self.os_client.get_project_quota(session, project_id)
        # Simple check: instances remaining
        instances = nova_quota.get("instances", {})
        if isinstance(instances, dict):
            remaining = instances.get("limit", -1) - instances.get("in_use", 0)
            if instances.get("limit", -1) > 0 and remaining < 1 and plan.get("mode") == "NEW":
                raise RuntimeError(f"Insufficient instance quota: {remaining} remaining")
        return {"quota_verified": True}

    def _step_delete_vm(self, session, vm_id) -> dict:
        self.os_client.delete_server(session, vm_id)
        return {"deleted_vm_id": vm_id}

    def _step_wait_vm_deleted(self, session, vm_id) -> dict:
        self.os_client.wait_server_deleted(session, vm_id)
        return {"vm_deleted": True}

    def _step_cleanup_old_ports(self, session, plan) -> dict:
        """
        Explicitly delete old ports from the original VM to free their IP addresses.
        In REPLACE mode, Nova *should* auto-delete ports when the VM is deleted, but
        this is not always immediate (race condition) or guaranteed (externally-created ports).
        This step ensures IPs are released before we try to recreate ports.
        """
        network_plan = plan.get("network_plan", [])
        vm_id = plan.get("vm", {}).get("id", "")
        cleaned = []
        skipped = []
        force_cleaned = []

        # Strategy 1: Delete original ports listed in the network plan
        for net in network_plan:
            port_id = net.get("original_port_id")
            if not port_id:
                continue
            try:
                self.os_client.delete_port(session, port_id)
                cleaned.append(port_id)
                logger.info(f"Cleaned up old port {port_id}")
            except Exception as e:
                # Port may already be gone (auto-deleted by Nova) — that's fine
                skipped.append({"port_id": port_id, "reason": str(e)})
                logger.debug(f"Old port {port_id} already gone or inaccessible: {e}")

        # Strategy 2: Check for any remaining ports attached to the deleted VM
        if vm_id:
            try:
                remaining_ports = self.os_client.list_ports_by_device(session, vm_id)
                for port in remaining_ports:
                    pid = port.get("id")
                    if pid and pid not in cleaned:
                        try:
                            self.os_client.delete_port(session, pid)
                            force_cleaned.append(pid)
                            logger.info(f"Force-cleaned orphan port {pid} from deleted VM")
                        except Exception as e:
                            logger.warning(f"Failed to force-clean port {pid}: {e}")
            except Exception as e:
                logger.debug(f"Could not list ports for device {vm_id}: {e}")

        # Strategy 3: For SAME_IPS_OR_FAIL, also check if the specific IPs are held by
        # orphan ports (ports with no device_id) and clean those too
        ip_strategy = plan.get("ip_strategy", "")
        if ip_strategy in ("SAME_IPS_OR_FAIL", "TRY_SAME_IPS"):
            for net in network_plan:
                ip_addr = net.get("requested_ip") or net.get("original_fixed_ip")
                net_id = net.get("network_id")
                if not ip_addr or not net_id:
                    continue
                try:
                    blocking_ports = self.os_client.list_ports_by_network_and_ip(
                        session, net_id, ip_addr
                    )
                    for port in blocking_ports:
                        pid = port.get("id")
                        device = port.get("device_id", "")
                        # Only delete if port has no active device (orphaned)
                        if pid and not device and pid not in cleaned and pid not in force_cleaned:
                            try:
                                self.os_client.delete_port(session, pid)
                                force_cleaned.append(pid)
                                logger.info(f"Cleaned orphan port {pid} holding IP {ip_addr}")
                            except Exception as e:
                                logger.warning(f"Failed to clean port {pid} for IP {ip_addr}: {e}")
                except Exception as e:
                    logger.debug(f"Could not check ports for IP {ip_addr}: {e}")

        # Brief pause to let Neutron fully release the IPs
        if cleaned or force_cleaned:
            time.sleep(3)

        return {
            "cleaned_ports": cleaned,
            "force_cleaned_ports": force_cleaned,
            "already_gone": [s["port_id"] for s in skipped],
        }

    def _step_cleanup_old_storage(self, session, project_id, plan) -> dict:
        """
        Post-restore cleanup of orphaned storage resources:
        - The original VM's root volume (orphaned after VM deletion in REPLACE mode)
        - The source Cinder snapshot (optionally, if caller requested)
        This step runs after FINALIZE so a failure here does NOT fail the restore itself.
        """
        result = {"deleted_volumes": [], "deleted_snapshots": [], "errors": [], "skipped": []}

        if RESTORE_DRY_RUN:
            result["dry_run"] = True
            return result

        # Find the action details for this step
        action_details = {}
        for action in plan.get("actions", []):
            if action.get("step") == "CLEANUP_OLD_STORAGE":
                action_details = action.get("details", {})
                break

        # --- Delete the original VM's orphaned volume ---
        if action_details.get("delete_old_volume"):
            old_vol_id = action_details.get("old_volume_id") or plan.get("source_volume", {}).get("id")
            if old_vol_id:
                try:
                    # Verify the volume is not attached to anything before deleting
                    vol = self.os_client.get_volume_detail(session, project_id, old_vol_id)
                    if not vol:
                        result["skipped"].append(f"Volume {old_vol_id} not found (already deleted?)")
                    elif vol.get("attachments"):
                        result["skipped"].append(
                            f"Volume {old_vol_id} still attached — skipping to prevent data loss"
                        )
                    elif vol.get("status") in ("in-use",):
                        result["skipped"].append(
                            f"Volume {old_vol_id} is in-use — skipping to prevent data loss"
                        )
                    else:
                        self.os_client.delete_volume(session, project_id, old_vol_id)
                        result["deleted_volumes"].append(old_vol_id)
                        logger.info(f"Deleted orphaned original volume {old_vol_id}")
                except Exception as e:
                    msg = f"Failed to delete old volume {old_vol_id}: {e}"
                    result["errors"].append(msg)
                    logger.warning(msg)

        # --- Delete the source snapshot ---
        if action_details.get("delete_source_snapshot"):
            snap_id = action_details.get("source_snapshot_id") or plan.get("restore_point", {}).get("id")
            if snap_id:
                try:
                    snap = self.os_client.get_snapshot_detail(session, project_id, snap_id)
                    snap_status = snap.get("status", "")
                    if not snap or snap_status == "":
                        result["skipped"].append(f"Snapshot {snap_id} not found (already deleted?)")
                    elif snap_status != "available":
                        result["skipped"].append(
                            f"Snapshot {snap_id} status is '{snap_status}' — skipping delete"
                        )
                    else:
                        self.os_client.delete_snapshot(session, project_id, snap_id)
                        result["deleted_snapshots"].append(snap_id)
                        logger.info(f"Deleted source snapshot {snap_id}")
                except Exception as e:
                    msg = f"Failed to delete snapshot {snap_id}: {e}"
                    result["errors"].append(msg)
                    logger.warning(msg)

        return result

    def _step_create_volume(self, session, project_id, plan) -> dict:
        snapshot_id = plan["restore_point"]["id"]
        size_gb = plan["restore_point"].get("size_gb") or plan.get("source_volume", {}).get("size_gb") or 20
        vol_type = plan.get("source_volume", {}).get("volume_type")
        vol_name = f"restore-{plan.get('new_vm_name', 'vm')}-root"

        if RESTORE_DRY_RUN:
            return {"volume_id": "dry-run-vol-id", "dry_run": True}

        vol = self.os_client.create_volume_from_snapshot(
            session, project_id, snapshot_id, vol_name, size_gb, vol_type
        )
        return {"volume_id": vol.get("id"), "volume_name": vol_name, "size_gb": size_gb}

    def _step_wait_volume(self, session, project_id, volume_id) -> dict:
        if RESTORE_DRY_RUN:
            return {"volume_status": "available", "dry_run": True}
        vol = self.os_client.wait_volume_available(session, project_id, volume_id)
        return {"volume_status": vol.get("status"), "volume_id": volume_id}

    def _step_create_ports(self, session, project_id, plan) -> dict:
        network_plan = plan.get("network_plan", [])
        port_ids = []
        port_details = []
        max_ip_retries = 5
        ip_retry_delay = 3  # seconds between retries

        for net in network_plan:
            if not net.get("network_id"):
                continue

            fixed_ip = None
            if net.get("will_request_fixed_ip") and net.get("requested_ip"):
                # Retry loop: IP may still be releasing from recently-deleted port
                ip_available = False
                for attempt in range(1, max_ip_retries + 1):
                    ip_free = self.os_client.check_ip_available(
                        session, net["network_id"], net["requested_ip"]
                    )
                    if ip_free:
                        ip_available = True
                        break
                    if attempt < max_ip_retries:
                        logger.info(
                            f"IP {net['requested_ip']} not yet available on "
                            f"{net.get('network_name', net['network_id'])} "
                            f"(attempt {attempt}/{max_ip_retries}), waiting {ip_retry_delay}s..."
                        )
                        time.sleep(ip_retry_delay)

                if ip_available:
                    fixed_ip = net["requested_ip"]
                elif plan.get("ip_strategy") == "SAME_IPS_OR_FAIL":
                    raise RuntimeError(
                        f"IP {net['requested_ip']} is not available on network "
                        f"{net.get('network_name', net['network_id'])} "
                        f"(checked {max_ip_retries} times over {max_ip_retries * ip_retry_delay}s)"
                    )
                else:
                    logger.warning(
                        f"IP {net['requested_ip']} not available after retries, allocating new IP"
                    )

            if RESTORE_DRY_RUN:
                port_ids.append("dry-run-port-id")
                port_details.append({"dry_run": True, "network_id": net["network_id"]})
                continue

            security_groups = plan.get("security_group_ids") or None
            port = self.os_client.create_port(
                session,
                network_id=net["network_id"],
                subnet_id=net.get("subnet_id"),
                fixed_ip=fixed_ip,
                security_groups=security_groups,
                project_id=project_id,
            )
            port_ids.append(port["id"])
            port_details.append({
                "port_id": port["id"],
                "network_id": net["network_id"],
                "fixed_ips": port.get("fixed_ips", []),
            })

        return {"port_ids": port_ids, "port_details": port_details}

    def _step_create_server(self, session, plan, resources) -> dict:
        flavor_id = plan["vm"]["flavor_id"]
        vm_name = plan["new_vm_name"]
        port_ids = resources.get("port_ids", [])
        volume_id = resources.get("volume_id")
        user_data = plan.get("vm", {}).get("user_data")  # base64-encoded cloud-init

        if RESTORE_DRY_RUN:
            return {"server_id": "dry-run-server-id", "dry_run": True, "user_data_preserved": bool(user_data)}

        # Boot from volume: block device mapping
        bdm = [{
            "uuid": volume_id,
            "source_type": "volume",
            "destination_type": "volume",
            "boot_index": 0,
            "delete_on_termination": False,
        }]

        server = self.os_client.create_server(
            session,
            name=vm_name,
            flavor_id=flavor_id,
            port_ids=port_ids,
            block_device_mapping=bdm,
            user_data=user_data,
        )
        return {
            "server_id": server.get("id"),
            "server_name": vm_name,
            "user_data_preserved": bool(user_data),
        }

    def _step_wait_server(self, session, server_id) -> dict:
        if RESTORE_DRY_RUN:
            return {"server_status": "ACTIVE", "dry_run": True}
        server = self.os_client.wait_server_active(session, server_id)
        # Extract final IPs
        addresses = server.get("addresses", {})
        final_ips = []
        for net_name, addrs in addresses.items():
            for a in addrs:
                final_ips.append({
                    "network": net_name,
                    "ip": a.get("addr"),
                    "version": a.get("version"),
                    "type": a.get("OS-EXT-IPS:type"),
                })
        return {"server_status": "ACTIVE", "server_id": server_id, "final_ips": final_ips}

    # --- Cleanup / rollback ---

    async def _cleanup_resources(
        self, session: http_requests.Session, project_id: str, resources: dict
    ):
        """Best-effort cleanup of resources created during a failed restore."""
        logger.info(f"Cleaning up resources: {resources}")

        # Delete server first (if created)
        if resources.get("server_id") and not RESTORE_DRY_RUN:
            try:
                self.os_client.delete_server(session, resources["server_id"])
                logger.info(f"Cleaned up server {resources['server_id']}")
            except Exception as e:
                logger.warning(f"Failed to cleanup server: {e}")

        # Delete ports
        for port_id in resources.get("port_ids", []):
            if RESTORE_DRY_RUN:
                continue
            try:
                self.os_client.delete_port(session, port_id)
                logger.info(f"Cleaned up port {port_id}")
            except Exception as e:
                logger.warning(f"Failed to cleanup port {port_id}: {e}")

        # Volume cleanup: controlled by RESTORE_CLEANUP_VOLUMES env var.
        # By default we preserve volumes for manual recovery/debugging.
        cleanup_volumes = os.getenv("RESTORE_CLEANUP_VOLUMES", "false").lower() in ("true", "1", "yes")
        if resources.get("volume_id") and not RESTORE_DRY_RUN:
            if cleanup_volumes:
                try:
                    url = self.os_client._cinder_url(project_id, f"/volumes/{resources['volume_id']}")
                    session.delete(url, timeout=60)
                    logger.info(f"Cleaned up volume {resources['volume_id']}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup volume {resources['volume_id']}: {e}")
            else:
                logger.warning(
                    f"Volume {resources['volume_id']} was NOT deleted (preserved for manual recovery). "
                    f"Set RESTORE_CLEANUP_VOLUMES=true to auto-delete on failure."
                )

    # --- DB helpers ---

    def _load_job(self, conn, job_id: str) -> Optional[dict]:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM restore_jobs WHERE id = %s", (job_id,))
            return cur.fetchone()

    def _load_steps(self, conn, job_id: str) -> list:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM restore_job_steps WHERE job_id = %s ORDER BY step_order",
                (job_id,),
            )
            return cur.fetchall()

    def _update_job_status(self, conn, job_id: str, status: str):
        with conn.cursor() as cur:
            if status == "RUNNING":
                cur.execute(
                    "UPDATE restore_jobs SET status=%s, started_at=now(), last_heartbeat=now() WHERE id=%s",
                    (status, job_id),
                )
            else:
                cur.execute(
                    "UPDATE restore_jobs SET status=%s, last_heartbeat=now() WHERE id=%s",
                    (status, job_id),
                )
        conn.commit()

    def _heartbeat(self, conn, job_id: str):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE restore_jobs SET last_heartbeat=now() WHERE id=%s", (job_id,)
            )
        conn.commit()

    def _update_step_status(
        self, conn, job_id: str, step_id: int, status: str,
        details: dict = None, error: str = None,
    ):
        with conn.cursor() as cur:
            if status == "RUNNING":
                cur.execute(
                    "UPDATE restore_job_steps SET status=%s, started_at=now() WHERE id=%s",
                    (status, step_id),
                )
            elif status == "SUCCEEDED":
                cur.execute(
                    "UPDATE restore_job_steps SET status=%s, finished_at=now(), details_json=%s WHERE id=%s",
                    (status, Json(details or {}), step_id),
                )
            elif status == "FAILED":
                cur.execute(
                    "UPDATE restore_job_steps SET status=%s, finished_at=now(), error_text=%s WHERE id=%s",
                    (status, error, step_id),
                )
        conn.commit()

    def _fail_job(self, conn, job_id: str, reason: str):
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE restore_jobs
                   SET status='FAILED', finished_at=now(), failure_reason=%s, last_heartbeat=now()
                   WHERE id=%s""",
                (reason, job_id),
            )
        conn.commit()

    def _complete_job(self, conn, job_id: str, resources: dict):
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE restore_jobs
                   SET status='SUCCEEDED', finished_at=now(), result_json=%s, last_heartbeat=now()
                   WHERE id=%s""",
                (Json(resources), job_id),
            )
        conn.commit()


# ============================================================================
# Route setup — called from main.py
# ============================================================================

def setup_restore_routes(app, db_conn_fn):
    """Register all restore API routes on the FastAPI app."""

    os_client = RestoreOpenStackClient()
    planner = RestorePlanner(db_conn_fn, os_client)
    executor = RestoreExecutor(db_conn_fn, os_client)

    # ------------------------------------------------------------------
    # Startup: recover stale jobs left in PENDING/RUNNING from a crash
    # ------------------------------------------------------------------
    try:
        conn = db_conn_fn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE restore_jobs
                       SET status='INTERRUPTED',
                           finished_at=now(),
                           failure_reason='API restarted while job was in progress'
                       WHERE status IN ('PENDING','RUNNING')"""
                )
                count = cur.rowcount
            conn.commit()
            if count:
                logger.warning(f"Marked {count} stale restore job(s) as INTERRUPTED on startup")
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to recover stale restore jobs on startup: {e}")

    # ------------------------------------------------------------------
    # GET /restore/quota/{project_id}  — free resources for a project
    # ------------------------------------------------------------------
    @app.get("/restore/quota/{project_id}", tags=["Snapshot Restore"])
    async def get_restore_quota(
        project_id: str,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "read")),
    ):
        """Get project quota (free resources) for restore planning."""
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        try:
            admin_session = os_client.authenticate_admin()
            nova_q = os_client.get_project_quota(admin_session, project_id)
            cinder_q = os_client.get_volume_quota(admin_session, project_id)

            def _extract(q, key):
                v = q.get(key, {})
                if isinstance(v, dict):
                    return {
                        "limit": v.get("limit", -1),
                        "in_use": v.get("in_use", 0),
                        "remaining": v.get("limit", -1) - v.get("in_use", 0) if v.get("limit", -1) > 0 else -1,
                    }
                return {"limit": -1, "in_use": 0, "remaining": -1}

            return {
                "project_id": project_id,
                "instances": _extract(nova_q, "instances"),
                "cores": _extract(nova_q, "cores"),
                "ram_mb": _extract(nova_q, "ram"),
                "volumes": _extract(cinder_q, "volumes"),
                "gigabytes": _extract(cinder_q, "gigabytes"),
            }
        except Exception as e:
            logger.error(f"Failed to fetch quota for {project_id}: {e}")
            raise HTTPException(500, f"Failed to fetch quota: {str(e)}")

    # ------------------------------------------------------------------
    # GET /restore/networks/{network_id}/available-ips  — list free IPs
    # ------------------------------------------------------------------
    @app.get("/restore/networks/{network_id}/available-ips", tags=["Snapshot Restore"])
    async def get_available_ips(
        network_id: str,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "read")),
    ):
        """
        List available (unused) IPs on a network's subnets.
        Queries Neutron for subnet CIDR and existing ports, then computes free IPs.
        Returns up to 200 available IPs per subnet.
        """
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        try:
            import ipaddress
            admin_session = os_client.authenticate_admin()

            # 1. Get subnets for this network
            url = f"{os_client.neutron_endpoint}/v2.0/subnets?network_id={network_id}"
            r = admin_session.get(url, timeout=60)
            r.raise_for_status()
            subnets = r.json().get("subnets", [])

            # 2. Get all ports on this network to find used IPs
            url = f"{os_client.neutron_endpoint}/v2.0/ports?network_id={network_id}&limit=1000"
            r = admin_session.get(url, timeout=60)
            r.raise_for_status()
            ports = r.json().get("ports", [])

            used_ips = set()
            for port in ports:
                for fip in port.get("fixed_ips", []):
                    used_ips.add(fip.get("ip_address"))

            result = []
            for subnet in subnets:
                cidr = subnet.get("cidr")
                subnet_id = subnet.get("id")
                subnet_name = subnet.get("name", "")
                gateway_ip = subnet.get("gateway_ip")
                allocation_pools = subnet.get("allocation_pools", [])

                available = []
                if allocation_pools:
                    # Use allocation pools to enumerate available IPs
                    for pool in allocation_pools:
                        start = ipaddress.ip_address(pool["start"])
                        end = ipaddress.ip_address(pool["end"])
                        current = start
                        while current <= end and len(available) < 200:
                            ip_str = str(current)
                            if ip_str not in used_ips and ip_str != gateway_ip:
                                available.append(ip_str)
                            current += 1
                else:
                    # Fallback: enumerate from CIDR, skip network/broadcast/gateway
                    try:
                        network = ipaddress.ip_network(cidr, strict=False)
                        for addr in network.hosts():
                            if len(available) >= 200:
                                break
                            ip_str = str(addr)
                            if ip_str not in used_ips and ip_str != gateway_ip:
                                available.append(ip_str)
                    except Exception:
                        pass

                result.append({
                    "subnet_id": subnet_id,
                    "subnet_name": subnet_name,
                    "cidr": cidr,
                    "gateway_ip": gateway_ip,
                    "total_used": len([ip for ip in used_ips if any(
                        ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
                        for _ in [None]
                    )]) if cidr else 0,
                    "available_ips": available,
                    "available_count": len(available),
                })

            return {
                "network_id": network_id,
                "subnets": result,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to list available IPs for network {network_id}: {e}")
            raise HTTPException(500, f"Failed to list available IPs: {str(e)}")

    # ------------------------------------------------------------------
    # GET /restore/vms/{vm_id}/restore-points  — snapshots for a VM
    # ------------------------------------------------------------------
    @app.get("/restore/vms/{vm_id}/restore-points", tags=["Snapshot Restore"])
    async def get_restore_points(
        vm_id: str,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "read")),
    ):
        """
        Get available restore points (Cinder snapshots) for a VM's volumes.
        Groups by date for easy selection.
        """
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get VM details
                cur.execute("SELECT id, name, project_id, flavor_id, raw_json FROM servers WHERE id = %s", (vm_id,))
                vm = cur.fetchone()
                if not vm:
                    raise HTTPException(404, f"VM {vm_id} not found")

                # Detect boot mode
                raw = vm.get("raw_json") or {}
                if isinstance(raw, str):
                    try:
                        raw = json.loads(raw)
                    except Exception:
                        raw = {}

                image = raw.get("image", "")
                boot_mode = "BOOT_FROM_IMAGE"
                if not image or image == "":
                    boot_mode = "BOOT_FROM_VOLUME"
                else:
                    # Check for bootable attached volumes
                    volumes_attached = raw.get("os-extended-volumes:volumes_attached", [])
                    for va in volumes_attached:
                        vol_id = va.get("id")
                        cur.execute("SELECT bootable FROM volumes WHERE id = %s", (vol_id,))
                        vrow = cur.fetchone()
                        if vrow and vrow.get("bootable"):
                            boot_mode = "BOOT_FROM_VOLUME"
                            break

                # Find all volumes attached to this VM using proper JSONB querying
                cur.execute(
                    """SELECT v.id as volume_id, v.name as volume_name, v.size_gb, v.bootable
                       FROM volumes v
                       WHERE v.raw_json->'attachments' IS NOT NULL
                         AND EXISTS (
                             SELECT 1 FROM jsonb_array_elements(v.raw_json->'attachments') elem
                             WHERE elem->>'server_id' = %s
                         )""",
                    (vm_id,),
                )
                volumes = cur.fetchall()

                # Also find from ports → device_id mapping in volume attachments
                volume_ids = [v["volume_id"] for v in volumes]

                # Get snapshots for these volumes from local DB
                snapshots = []
                if volume_ids:
                    cur.execute(
                        """SELECT s.id, s.name, s.volume_id, s.size_gb, s.status,
                                  s.created_at, s.description, s.project_id
                           FROM snapshots s
                           WHERE s.volume_id = ANY(%s)
                             AND s.status = 'available'
                           ORDER BY s.created_at DESC""",
                        (volume_ids,),
                    )
                    snapshots = cur.fetchall()

                # Also query Cinder API directly to catch manual/recent snapshots
                # not yet synced to the local DB
                live_snapshots = []
                try:
                    admin_session = os_client.authenticate_admin()
                    project_id = vm.get("project_id") or ""
                    for vol_id in volume_ids:
                        url = os_client._cinder_url(
                            project_id,
                            f"/snapshots/detail?volume_id={vol_id}&status=available"
                        )
                        r = admin_session.get(url, timeout=60)
                        if r.status_code == 200:
                            for snap in r.json().get("snapshots", []):
                                live_snapshots.append(snap)
                except Exception as ex:
                    logger.warning(f"Failed to query Cinder for live snapshots: {ex}")

                # Merge: local DB snapshots + live Cinder snapshots (deduplicated)
                seen_ids = set()
                restore_points = []

                # Add local DB snapshots first
                for snap in snapshots:
                    sid = snap["id"]
                    seen_ids.add(sid)
                    restore_points.append({
                        "id": sid,
                        "name": snap["name"],
                        "volume_id": snap["volume_id"],
                        "size_gb": snap["size_gb"],
                        "status": snap["status"],
                        "created_at": snap["created_at"].isoformat() if snap["created_at"] else None,
                        "description": snap.get("description"),
                    })

                # Add live Cinder snapshots that aren't already in local DB
                for snap in live_snapshots:
                    sid = snap.get("id")
                    if sid in seen_ids:
                        continue
                    seen_ids.add(sid)
                    restore_points.append({
                        "id": sid,
                        "name": snap.get("name"),
                        "volume_id": snap.get("volume_id"),
                        "size_gb": snap.get("size"),
                        "status": snap.get("status"),
                        "created_at": snap.get("created_at"),
                        "description": snap.get("description"),
                    })

                # Sort all by created_at descending
                restore_points.sort(
                    key=lambda x: x.get("created_at") or "",
                    reverse=True,
                )

                return {
                    "vm_id": vm_id,
                    "vm_name": vm.get("name"),
                    "boot_mode": boot_mode,
                    "boot_mode_supported": boot_mode == "BOOT_FROM_VOLUME",
                    "volumes": [dict(v) for v in volumes],
                    "restore_points": restore_points,
                    "message": (
                        None if boot_mode == "BOOT_FROM_VOLUME"
                        else "This VM uses boot-from-image. Snapshot restore for image-booted VMs is not yet supported."
                    ),
                }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # POST /restore/plan  — build a restore plan
    # ------------------------------------------------------------------
    @app.post("/restore/plan", tags=["Snapshot Restore"])
    async def create_restore_plan(
        req: RestorePlanRequest,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "write")),
    ):
        """Build a restore plan without executing it."""
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        try:
            plan = planner.build_plan(req, current_user.username)
            return plan
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to build restore plan: {e}")
            raise HTTPException(500, f"Failed to build restore plan: {str(e)}")

    # ------------------------------------------------------------------
    # POST /restore/execute  — execute a saved plan
    # ------------------------------------------------------------------
    @app.post("/restore/execute", tags=["Snapshot Restore"])
    async def execute_restore(
        req: RestoreExecuteRequest,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "admin")),
    ):
        """Execute a previously-created restore plan."""
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM restore_jobs WHERE id = %s", (req.plan_id,))
                job = cur.fetchone()

            if not job:
                raise HTTPException(404, f"Restore plan {req.plan_id} not found")

            if job["status"] != "PLANNED":
                raise HTTPException(
                    400,
                    f"Plan {req.plan_id} is in status '{job['status']}' — only PLANNED jobs can be executed"
                )

            # REPLACE mode requires destructive confirmation
            if job["mode"] == "REPLACE":
                expected = f"DELETE AND RESTORE {job['vm_name']}"
                if req.confirm_destructive != expected:
                    raise HTTPException(
                        400,
                        f"Replace mode requires confirmation. "
                        f"Set confirm_destructive to: '{expected}'"
                    )
                # Only superadmin can do REPLACE
                if current_user.role not in ("superadmin",):
                    raise HTTPException(403, "Only superadmin can execute REPLACE mode restores")

            # Update job to PENDING and record who executed
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE restore_jobs SET status='PENDING', executed_by=%s WHERE id=%s""",
                    (current_user.username, req.plan_id),
                )
            conn.commit()

        finally:
            conn.close()

        # Launch execution as background task
        asyncio.create_task(executor.execute_job(req.plan_id))

        return {
            "job_id": req.plan_id,
            "status": "PENDING",
            "message": "Restore execution started. Poll /restore/jobs/{job_id} for progress.",
        }

    # ------------------------------------------------------------------
    # GET /restore/jobs  — list restore jobs
    # ------------------------------------------------------------------
    @app.get("/restore/jobs", tags=["Snapshot Restore"])
    async def list_restore_jobs(
        project_id: str = None,
        status: str = None,
        created_by: str = None,
        search: str = None,
        date_from: str = None,
        date_to: str = None,
        limit: int = 50,
        offset: int = 0,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "read")),
    ):
        """List restore jobs with optional filters."""
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            conditions = []
            params = []

            if project_id:
                conditions.append("project_id = %s")
                params.append(project_id)
            if status:
                conditions.append("status = %s")
                params.append(status)
            if created_by:
                conditions.append("created_by ILIKE %s")
                params.append(f"%{created_by}%")
            if search:
                conditions.append(
                    "(vm_name ILIKE %s OR vm_id ILIKE %s OR project_name ILIKE %s "
                    "OR requested_name ILIKE %s OR created_by ILIKE %s)"
                )
                like = f"%{search}%"
                params.extend([like, like, like, like, like])
            if date_from:
                conditions.append("created_at >= %s::timestamptz")
                params.append(date_from)
            if date_to:
                conditions.append("created_at <= %s::timestamptz")
                params.append(date_to)

            where = ""
            if conditions:
                where = "WHERE " + " AND ".join(conditions)

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"SELECT COUNT(*) as total FROM restore_jobs {where}", params)
                total = cur.fetchone()["total"]

                cur.execute(
                    f"""SELECT id, created_by, executed_by, project_id, project_name,
                               vm_id, vm_name, restore_point_id, restore_point_name,
                               mode, ip_strategy, requested_name, boot_mode, status,
                               failure_reason, result_json,
                               created_at, started_at, finished_at
                        FROM restore_jobs {where}
                        ORDER BY created_at DESC
                        LIMIT %s OFFSET %s""",
                    params + [limit, offset],
                )
                jobs = cur.fetchall()

            # Serialize datetimes
            for j in jobs:
                for key in ("created_at", "started_at", "finished_at"):
                    if j.get(key):
                        j[key] = j[key].isoformat()

            return {"total": total, "jobs": jobs, "limit": limit, "offset": offset}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # GET /restore/jobs/{job_id}  — full job detail with steps
    # ------------------------------------------------------------------
    @app.get("/restore/jobs/{job_id}", tags=["Snapshot Restore"])
    async def get_restore_job(
        job_id: str,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "read")),
    ):
        """Get full restore job detail including steps and progress."""
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM restore_jobs WHERE id = %s", (job_id,))
                job = cur.fetchone()
                if not job:
                    raise HTTPException(404, f"Restore job {job_id} not found")

                cur.execute(
                    "SELECT * FROM restore_job_steps WHERE job_id = %s ORDER BY step_order",
                    (job_id,),
                )
                steps = cur.fetchall()

            # Serialize
            for key in ("created_at", "started_at", "finished_at", "last_heartbeat", "canceled_at"):
                if job.get(key):
                    job[key] = job[key].isoformat()

            for s in steps:
                for key in ("started_at", "finished_at", "created_at"):
                    if s.get(key):
                        s[key] = s[key].isoformat()

            # Calculate progress
            total_steps = len(steps)
            completed_steps = len([s for s in steps if s["status"] in ("SUCCEEDED", "SKIPPED")])
            current_step = next(
                (s["step_name"] for s in steps if s["status"] == "RUNNING"), None
            )

            return {
                **job,
                "steps": steps,
                "progress": {
                    "total_steps": total_steps,
                    "completed_steps": completed_steps,
                    "current_step": current_step,
                    "percent": round(completed_steps / total_steps * 100) if total_steps > 0 else 0,
                },
            }
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # POST /restore/jobs/{job_id}/cancel  — cancel a running job
    # ------------------------------------------------------------------
    @app.post("/restore/jobs/{job_id}/cancel", tags=["Snapshot Restore"])
    async def cancel_restore_job(
        job_id: str,
        req: RestoreCancelRequest = None,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "write")),
    ):
        """Cancel a running or pending restore job (best effort)."""
        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT status FROM restore_jobs WHERE id = %s", (job_id,))
                job = cur.fetchone()
                if not job:
                    raise HTTPException(404, f"Restore job {job_id} not found")

                if job["status"] not in ("PENDING", "RUNNING", "PLANNED"):
                    raise HTTPException(
                        400, f"Cannot cancel job in status '{job['status']}'"
                    )

                reason = (req.reason if req else None) or "Canceled by user"
                cur.execute(
                    """UPDATE restore_jobs
                       SET status='CANCELED', canceled_at=now(), failure_reason=%s
                       WHERE id=%s""",
                    (f"Canceled by {current_user.username}: {reason}", job_id),
                )
            conn.commit()

            return {"job_id": job_id, "status": "CANCELED", "message": "Job cancellation requested"}
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # POST /restore/jobs/{job_id}/cleanup  — clean up orphaned resources
    # ------------------------------------------------------------------
    @app.post("/restore/jobs/{job_id}/cleanup", tags=["Snapshot Restore"])
    async def cleanup_restore_job(
        job_id: str,
        req: RestoreCleanupRequest = None,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "admin")),
    ):
        """
        Clean up orphaned OpenStack resources from a failed restore job.
        Deletes ports and optionally volumes that were created before the failure.
        """
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM restore_jobs WHERE id = %s", (job_id,))
                job = cur.fetchone()
                if not job:
                    raise HTTPException(404, f"Restore job {job_id} not found")
                if job["status"] not in ("FAILED", "CANCELED", "INTERRUPTED"):
                    raise HTTPException(400, f"Can only cleanup jobs in FAILED/CANCELED/INTERRUPTED status, got '{job['status']}'")

                # Load step results to find created resources
                cur.execute(
                    "SELECT * FROM restore_job_steps WHERE job_id = %s ORDER BY step_order",
                    (job_id,),
                )
                steps = cur.fetchall()
        finally:
            conn.close()

        plan = job["plan_json"]
        if isinstance(plan, str):
            plan = json.loads(plan)

        project_id = job["project_id"]
        delete_volume = req.delete_volume if req else False

        # Extract resources from step results
        resources_to_clean = {"volume_id": None, "port_ids": [], "server_id": None}
        for step in steps:
            if step["status"] != "SUCCEEDED":
                continue
            details = step.get("details_json") or {}
            if isinstance(details, str):
                details = json.loads(details)
            if step["step_name"] == "CREATE_VOLUME_FROM_SNAPSHOT":
                resources_to_clean["volume_id"] = details.get("volume_id")
            elif step["step_name"] == "CREATE_PORTS":
                resources_to_clean["port_ids"] = details.get("port_ids") or []
            elif step["step_name"] == "CREATE_SERVER":
                resources_to_clean["server_id"] = details.get("server_id")

        # Authenticate and clean
        try:
            session = os_client.authenticate_service_user(project_id)
        except Exception as e:
            raise HTTPException(500, f"Failed to authenticate for cleanup: {e}")

        cleaned = {"ports": [], "volume": None, "server": None, "errors": []}

        # Clean server if it was created
        if resources_to_clean["server_id"]:
            try:
                os_client.delete_server(session, resources_to_clean["server_id"])
                cleaned["server"] = resources_to_clean["server_id"]
            except Exception as e:
                cleaned["errors"].append(f"Server {resources_to_clean['server_id']}: {e}")

        # Clean ports
        for port_id in resources_to_clean["port_ids"]:
            try:
                os_client.delete_port(session, port_id)
                cleaned["ports"].append(port_id)
            except Exception as e:
                cleaned["errors"].append(f"Port {port_id}: {e}")

        # Clean volume
        if resources_to_clean["volume_id"]:
            if delete_volume:
                try:
                    os_client.delete_volume(session, project_id, resources_to_clean["volume_id"])
                    cleaned["volume"] = resources_to_clean["volume_id"]
                except Exception as e:
                    cleaned["errors"].append(f"Volume {resources_to_clean['volume_id']}: {e}")
            else:
                cleaned["volume"] = f"{resources_to_clean['volume_id']} (preserved — use delete_volume=true to remove)"

        # Update job status to reflect cleanup
        conn2 = db_conn_fn()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    """UPDATE restore_jobs
                       SET failure_reason = COALESCE(failure_reason, '') || %s
                       WHERE id = %s""",
                    (f"\n[Cleanup by {current_user.username}: {json.dumps(cleaned)}]", job_id),
                )
            conn2.commit()
        finally:
            conn2.close()

        return {
            "job_id": job_id,
            "cleaned": cleaned,
            "message": "Cleanup completed" if not cleaned["errors"] else "Cleanup completed with some errors",
        }

    # ------------------------------------------------------------------
    # POST /restore/jobs/{job_id}/cleanup-storage  — delete old volume / snapshot
    # ------------------------------------------------------------------
    @app.post("/restore/jobs/{job_id}/cleanup-storage", tags=["Snapshot Restore"])
    async def cleanup_restore_storage(
        job_id: str,
        delete_old_volume: bool = True,
        delete_source_snapshot: bool = False,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "admin")),
    ):
        """
        Delete orphaned storage left behind by a completed REPLACE-mode restore:
        - The original VM's root volume (orphaned after VM deletion)
        - The source Cinder snapshot used for the restore (optional)
        """
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM restore_jobs WHERE id = %s", (job_id,))
                job = cur.fetchone()
                if not job:
                    raise HTTPException(404, f"Restore job {job_id} not found")
                if job["status"] != "COMPLETED":
                    raise HTTPException(400, f"Storage cleanup is only for COMPLETED jobs, got '{job['status']}'")
        finally:
            conn.close()

        plan = job["plan_json"]
        if isinstance(plan, str):
            plan = json.loads(plan)

        project_id = job["project_id"]
        mode = plan.get("mode", "NEW")
        if mode != "REPLACE" and delete_old_volume:
            raise HTTPException(400, "Old volume cleanup only applies to REPLACE mode restores")

        result = {"deleted_volumes": [], "deleted_snapshots": [], "errors": [], "skipped": []}

        # Authenticate
        try:
            session = os_client.authenticate_service_user(project_id)
        except Exception as e:
            raise HTTPException(500, f"Failed to authenticate for storage cleanup: {e}")

        # Delete old volume (the source volume the snapshot was taken from)
        if delete_old_volume:
            old_vol_id = plan.get("source_volume", {}).get("id")
            if old_vol_id:
                try:
                    vol = os_client.get_volume_detail(session, project_id, old_vol_id)
                    if not vol:
                        result["skipped"].append(f"Volume {old_vol_id} not found (already deleted?)")
                    elif vol.get("attachments"):
                        result["skipped"].append(f"Volume {old_vol_id} still attached — skipping")
                    elif vol.get("status") == "in-use":
                        result["skipped"].append(f"Volume {old_vol_id} is in-use — skipping")
                    else:
                        os_client.delete_volume(session, project_id, old_vol_id)
                        result["deleted_volumes"].append(old_vol_id)
                except Exception as e:
                    result["errors"].append(f"Volume {old_vol_id}: {e}")
            else:
                result["skipped"].append("No source volume ID in restore plan")

        # Delete source snapshot
        if delete_source_snapshot:
            snap_id = plan.get("restore_point", {}).get("id")
            if snap_id:
                try:
                    snap = os_client.get_snapshot_detail(session, project_id, snap_id)
                    snap_status = snap.get("status", "")
                    if not snap or not snap_status:
                        result["skipped"].append(f"Snapshot {snap_id} not found")
                    elif snap_status != "available":
                        result["skipped"].append(f"Snapshot {snap_id} status '{snap_status}' — skipping")
                    else:
                        os_client.delete_snapshot(session, project_id, snap_id)
                        result["deleted_snapshots"].append(snap_id)
                except Exception as e:
                    result["errors"].append(f"Snapshot {snap_id}: {e}")
            else:
                result["skipped"].append("No snapshot ID in restore plan")

        # Audit log
        conn2 = db_conn_fn()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    """UPDATE restore_jobs
                       SET failure_reason = COALESCE(failure_reason, '') || %s
                       WHERE id = %s""",
                    (f"\n[Storage cleanup by {current_user.username}: {json.dumps(result)}]", job_id),
                )
            conn2.commit()
        finally:
            conn2.close()

        return {
            "job_id": job_id,
            "result": result,
            "message": "Storage cleanup completed" if not result["errors"] else "Storage cleanup completed with errors",
        }

    # ------------------------------------------------------------------
    # POST /restore/jobs/{job_id}/retry  — retry a failed job
    # ------------------------------------------------------------------
    @app.post("/restore/jobs/{job_id}/retry", tags=["Snapshot Restore"])
    async def retry_restore_job(
        job_id: str,
        req: RestoreRetryRequest = None,
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "admin")),
    ):
        """
        Retry a failed restore job. Creates a new job that resumes from the
        failed step, reusing resources (volumes, ports) already created.
        Optionally override ip_strategy (e.g., switch from SAME_IPS_OR_FAIL to TRY_SAME_IPS).
        """
        if not RESTORE_ENABLED:
            raise HTTPException(503, "Restore feature is not enabled")

        conn = db_conn_fn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM restore_jobs WHERE id = %s", (job_id,))
                job = cur.fetchone()
                if not job:
                    raise HTTPException(404, f"Restore job {job_id} not found")
                if job["status"] not in ("FAILED",):
                    raise HTTPException(400, f"Can only retry FAILED jobs, got '{job['status']}'")

                # REPLACE mode requires destructive confirmation
                if job["mode"] == "REPLACE":
                    expected = f"DELETE AND RESTORE {job['vm_name']}"
                    confirm = req.confirm_destructive if req else None
                    if confirm != expected:
                        raise HTTPException(
                            400,
                            f"Replace mode requires confirmation. "
                            f"Set confirm_destructive to: '{expected}'"
                        )
                    if current_user.role not in ("superadmin",):
                        raise HTTPException(403, "Only superadmin can retry REPLACE mode restores")

                # Load steps to find the failed step and any existing resources
                cur.execute(
                    "SELECT * FROM restore_job_steps WHERE job_id = %s ORDER BY step_order",
                    (job_id,),
                )
                steps = cur.fetchall()
        finally:
            conn.close()

        plan = job["plan_json"]
        if isinstance(plan, str):
            plan = json.loads(plan)

        # Apply ip_strategy override
        if req and req.ip_strategy_override:
            plan["ip_strategy"] = req.ip_strategy_override
            # Update network plan entries
            for net in plan.get("network_plan", []):
                ip = net.get("original_fixed_ip")
                if req.ip_strategy_override == "NEW_IPS":
                    net["will_request_fixed_ip"] = False
                    net["requested_ip"] = None
                    net["note"] = "Allocating new IP (auto-assign) [retry override]"
                elif req.ip_strategy_override == "TRY_SAME_IPS" and ip:
                    net["will_request_fixed_ip"] = True
                    net["requested_ip"] = ip
                    net["note"] = f"Will attempt to assign {ip} [retry override, fallback to new IP]"

        # Collect resources already created by successful steps
        existing_resources = {"volume_id": None, "port_ids": [], "server_id": None}
        failed_step_order = None
        for step in steps:
            details = step.get("details_json") or {}
            if isinstance(details, str):
                details = json.loads(details)

            if step["status"] == "SUCCEEDED":
                if step["step_name"] == "CREATE_VOLUME_FROM_SNAPSHOT":
                    existing_resources["volume_id"] = details.get("volume_id")
                elif step["step_name"] == "CREATE_PORTS":
                    existing_resources["port_ids"] = details.get("port_ids") or []
                elif step["step_name"] == "CREATE_SERVER":
                    existing_resources["server_id"] = details.get("server_id")
            elif step["status"] == "FAILED":
                failed_step_order = step["step_order"]
                break

        if failed_step_order is None:
            raise HTTPException(400, "Could not determine which step failed")

        # Build retry actions: only include steps from the failed one onwards
        retry_actions = []
        for step in steps:
            if step["step_order"] >= failed_step_order:
                retry_actions.append({
                    "step": step["step_name"],
                    "details": step.get("details_json") or {},
                })

        # Create a new job for the retry
        new_job_id = str(uuid.uuid4())
        conn2 = db_conn_fn()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    """INSERT INTO restore_jobs
                       (id, created_by, project_id, project_name, vm_id, vm_name,
                        restore_point_id, restore_point_name, mode, ip_strategy,
                        requested_name, boot_mode, status, plan_json, executed_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s)""",
                    (
                        new_job_id, current_user.username,
                        job["project_id"], job["project_name"],
                        job["vm_id"], job["vm_name"],
                        job["restore_point_id"], job["restore_point_name"],
                        job["mode"], plan.get("ip_strategy", job["ip_strategy"]),
                        job["requested_name"], job["boot_mode"],
                        Json(plan), current_user.username,
                    ),
                )

                for idx, action in enumerate(retry_actions):
                    cur.execute(
                        """INSERT INTO restore_job_steps
                           (job_id, step_order, step_name, status, details_json)
                           VALUES (%s, %s, %s, 'PENDING', %s)""",
                        (new_job_id, idx + 1, action["step"], Json(action.get("details", {}))),
                    )

                # Link retry to original job
                cur.execute(
                    """UPDATE restore_jobs
                       SET failure_reason = COALESCE(failure_reason, '') || %s
                       WHERE id = %s""",
                    (f"\n[Retried as job {new_job_id} by {current_user.username}]", job_id),
                )
            conn2.commit()
        finally:
            conn2.close()

        # Launch execution with pre-existing resources
        async def retry_with_resources():
            """Custom execution that pre-populates resources from the original job."""
            conn3 = db_conn_fn()
            try:
                executor._update_job_status(conn3, new_job_id, "RUNNING")
            finally:
                conn3.close()

            try:
                session = os_client.authenticate_service_user(job["project_id"])
            except Exception as e:
                executor._with_conn(lambda c: executor._fail_job(c, new_job_id, f"Authentication failed: {e}"))
                return

            # Start with existing resources
            created_resources = {
                "volume_id": existing_resources["volume_id"],
                "port_ids": list(existing_resources["port_ids"]),
                "server_id": existing_resources["server_id"],
            }

            retry_steps = executor._with_conn(lambda c: executor._load_steps(c, new_job_id))

            for step in retry_steps:
                step_name = step["step_name"]
                step_id = step["id"]

                executor._with_conn(lambda c: executor._update_step_status(c, new_job_id, step_id, "RUNNING"))
                executor._with_conn(lambda c: executor._heartbeat(c, new_job_id))

                try:
                    result = await executor._execute_step(
                        session, job["project_id"], plan, step_name, created_resources, job
                    )
                    executor._with_conn(
                        lambda c: executor._update_step_status(c, new_job_id, step_id, "SUCCEEDED", details=result)
                    )
                except Exception as e:
                    logger.error(f"Retry step {step_name} failed for job {new_job_id}: {e}")
                    executor._with_conn(
                        lambda c: executor._update_step_status(c, new_job_id, step_id, "FAILED", error=str(e))
                    )
                    await executor._cleanup_resources(session, job["project_id"], created_resources)
                    executor._with_conn(
                        lambda c: executor._fail_job(c, new_job_id, f"Step {step_name} failed: {e}")
                    )
                    return

            executor._with_conn(lambda c: executor._complete_job(c, new_job_id, created_resources))

        asyncio.create_task(retry_with_resources())

        return {
            "job_id": new_job_id,
            "original_job_id": job_id,
            "status": "PENDING",
            "resumed_from_step": steps[failed_step_order - 1]["step_name"] if failed_step_order else None,
            "reused_resources": {k: v for k, v in existing_resources.items() if v},
            "ip_strategy": plan.get("ip_strategy", job["ip_strategy"]),
            "message": "Retry execution started. Poll /restore/jobs/{job_id} for progress.",
        }

    # ------------------------------------------------------------------
    # GET /restore/config  — feature flag + configuration status
    # ------------------------------------------------------------------
    @app.get("/restore/config", tags=["Snapshot Restore"])
    async def get_restore_config(
        current_user: User = Depends(get_current_user),
        _perm: bool = Depends(require_permission("restore", "read")),
    ):
        """Get restore feature configuration status."""
        return {
            "enabled": RESTORE_ENABLED,
            "dry_run": RESTORE_DRY_RUN,
            "service_user_configured": bool(SNAPSHOT_SERVICE_USER_EMAIL),
        }
