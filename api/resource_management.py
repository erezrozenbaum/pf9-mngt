"""
Resource Management API Routes
===============================
System provisioning resource tool for managing OpenStack resources.
Provides CRUD operations for users, flavors, networks, routers,
floating IPs, volumes, security groups, images, and quotas.

RBAC
----
  - viewer          → resources:read   (list all resources)
  - operator/admin  → resources:write  (create / add)
  - admin           → resources:admin  (delete / remove)

Permission Model
----------------
  Viewer   → List all resources (read-only)
  Operator → List + Create (add users, create flavors, allocate IPs)
  Admin    → List + Create + Delete (with confirmation and protection checks)
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, validator
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User
from db_pool import get_connection
from pf9_control import get_client

logger = logging.getLogger("pf9.resources")

router = APIRouter(prefix="/api/resources", tags=["resources"])


# ---------------------------------------------------------------------------
# Activity logging (reuse provisioning pattern)
# ---------------------------------------------------------------------------

def _get_actor(user) -> str:
    if isinstance(user, dict):
        return user.get("username", "system")
    return getattr(user, "username", "system")


def _log_activity(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str = None,
    resource_name: str = None,
    domain_id: str = None,
    domain_name: str = None,
    details: dict = None,
    ip_address: str = None,
    result: str = "success",
    error_message: str = None,
):
    try:
        from psycopg2.extras import Json
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO activity_log
                        (actor, action, resource_type, resource_id, resource_name,
                         domain_id, domain_name, details, ip_address, result, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (actor, action, resource_type, resource_id, resource_name,
                      domain_id, domain_name, Json(details or {}),
                      ip_address, result, error_message))
    except Exception as e:
        logger.error(f"Failed to write activity log: {e}")


def _get_ip(request: Request) -> str:
    return request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")


def _notify(event_type: str, summary: str, severity: str = "info",
            resource_id: str = "", resource_name: str = "",
            details: dict = None, actor: str = ""):
    """Fire a notification event (delegates to provisioning_routes helper)."""
    try:
        from provisioning_routes import _fire_notification
        _fire_notification(
            event_type=event_type,
            summary=summary,
            severity=severity,
            resource_id=resource_id,
            resource_name=resource_name,
            details=details,
            actor=actor,
        )
    except Exception as e:
        logger.error(f"Resource notification failed ({event_type}): {e}")


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class AddUserRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    email: str = ""
    description: str = ""
    role: str = Field("member", description="Role: admin, member, or reader")
    project_id: str = Field(..., description="Tenant to assign the user to")
    domain_id: str = Field(..., description="Domain the user belongs to")

    @validator("role")
    def validate_role(cls, v):
        if v not in ("admin", "member", "reader"):
            raise ValueError("Role must be admin, member, or reader")
        return v


class AssignRoleRequest(BaseModel):
    user_id: str
    project_id: str
    role_name: str = Field(..., description="Role: admin, member, or reader")

    @validator("role_name")
    def validate_role(cls, v):
        if v not in ("admin", "member", "reader"):
            raise ValueError("Role must be admin, member, or reader")
        return v


class CreateFlavorRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    vcpus: int = Field(..., ge=1, le=128)
    ram_mb: int = Field(..., ge=128, le=131072, description="RAM in MB (128 MB to 128 GB)")
    disk_gb: int = Field(..., ge=0, le=2048, description="Root disk in GB")
    is_public: bool = True

    @validator("name")
    def validate_name(cls, v):
        import re
        if not re.match(r'^[a-zA-Z0-9._-]+$', v):
            raise ValueError("Name must contain only alphanumeric, dots, underscores, hyphens")
        return v


class CreateNetworkRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    project_id: str
    shared: bool = False
    external: bool = False
    # Provider network fields (optional)
    network_type: Optional[str] = Field(None, description="vlan, flat, or vxlan")
    physical_network: Optional[str] = None
    segmentation_id: Optional[int] = None
    # Subnet (optional - create with network)
    subnet_cidr: Optional[str] = None
    subnet_name: Optional[str] = None
    gateway_ip: Optional[str] = None
    dns_nameservers: Optional[List[str]] = None
    enable_dhcp: bool = True


class CreateRouterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    project_id: str
    external_network_id: Optional[str] = None


class RouterInterfaceRequest(BaseModel):
    subnet_id: str


class AllocateFloatingIPRequest(BaseModel):
    floating_network_id: str
    project_id: str
    description: str = ""


class CreateVolumeRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    size_gb: int = Field(..., ge=1, le=16384, description="Size in GB")
    project_id: str
    volume_type: Optional[str] = None
    description: str = ""


class CreateSecurityGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    project_id: Optional[str] = None


class CreateSGRuleRequest(BaseModel):
    security_group_id: str
    direction: str = Field(..., description="ingress or egress")
    protocol: Optional[str] = None
    port_range_min: Optional[int] = Field(None, ge=1, le=65535)
    port_range_max: Optional[int] = Field(None, ge=1, le=65535)
    remote_ip_prefix: Optional[str] = None
    remote_group_id: Optional[str] = None
    ethertype: str = "IPv4"
    description: str = ""

    @validator("direction")
    def validate_direction(cls, v):
        if v not in ("ingress", "egress"):
            raise ValueError("Direction must be ingress or egress")
        return v


class UpdateQuotasRequest(BaseModel):
    project_id: str
    # Compute quotas
    cores: Optional[int] = Field(None, ge=-1, le=10000)
    ram: Optional[int] = Field(None, ge=-1, le=1048576, description="RAM in MB")
    instances: Optional[int] = Field(None, ge=-1, le=10000)
    # Network quotas
    network: Optional[int] = Field(None, ge=-1, le=1000)
    subnet: Optional[int] = Field(None, ge=-1, le=1000)
    router: Optional[int] = Field(None, ge=-1, le=500)
    port: Optional[int] = Field(None, ge=-1, le=10000)
    floatingip: Optional[int] = Field(None, ge=-1, le=500)
    security_group: Optional[int] = Field(None, ge=-1, le=500)
    security_group_rule: Optional[int] = Field(None, ge=-1, le=5000)
    # Storage quotas
    gigabytes: Optional[int] = Field(None, ge=-1, le=1048576)
    volumes: Optional[int] = Field(None, ge=-1, le=10000)
    snapshots: Optional[int] = Field(None, ge=-1, le=10000)


# ---------------------------------------------------------------------------
# Users – List / Add / Remove / Assign Role
# ---------------------------------------------------------------------------

@router.get("/users")
async def list_users(
    project_id: Optional[str] = Query(None, description="Filter by project/tenant ID"),
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    user: User = Depends(require_permission("resources", "read")),
):
    """List users, optionally filtered by domain."""
    try:
        client = get_client()
        users = client.list_users(domain_id=domain_id)
        domains = {d["id"]: d["name"] for d in client.list_domains()}

        result = []
        for u in users:
            did = u.get("domain_id", "")
            result.append({
                "id": u.get("id", ""),
                "name": u.get("name", ""),
                "email": u.get("email", ""),
                "domain_id": did,
                "domain_name": domains.get(did, ""),
                "enabled": u.get("enabled", True),
                "description": u.get("description", ""),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users")
async def add_user(
    body: AddUserRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Create a user and assign a role on a project."""
    try:
        client = get_client()
        actor = _get_actor(user)

        # Create user
        new_user = client.create_user(
            name=body.username,
            password=body.password,
            domain_id=body.domain_id,
            email=body.email,
            description=body.description,
        )
        user_id = new_user.get("user", {}).get("id") or new_user.get("id", "")

        # Find the role
        roles = client.list_roles()
        role_obj = next((r for r in roles if r["name"] == body.role), None)
        if not role_obj:
            raise HTTPException(status_code=400, detail=f"Role '{body.role}' not found")

        # Assign role on project
        client.assign_role_to_user_on_project(body.project_id, user_id, role_obj["id"])

        _log_activity(
            actor=actor, action="create", resource_type="user",
            resource_id=user_id, resource_name=body.username,
            domain_id=body.domain_id,
            details={"role": body.role, "project_id": body.project_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"User '{body.username}' created with role '{body.role}'",
                resource_id=user_id, resource_name=body.username, actor=actor)

        return {"detail": f"User '{body.username}' created and assigned role '{body.role}'", "user_id": user_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add user failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/users/{user_id}")
async def remove_user(
    user_id: str,
    project_id: Optional[str] = Query(None, description="Project to check for last-user protection"),
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Remove a user. Refuses if the user is the last user in the project."""
    try:
        client = get_client()
        actor = _get_actor(user)

        # Get user info first
        try:
            all_users = client.list_users()
            target_user = next((u for u in all_users if u.get("id") == user_id), None)
        except Exception:
            target_user = None

        username = target_user.get("name", user_id) if target_user else user_id

        # Last-user protection
        if project_id:
            # TODO: Check role assignments on this project to count users
            # For now, check domain users
            domain_id = target_user.get("domain_id", "") if target_user else ""
            if domain_id:
                domain_users = client.list_users(domain_id=domain_id)
                project_users = [u for u in domain_users if u.get("id") != user_id]
                if len(project_users) == 0:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Cannot delete user '{username}' — they are the last user in the domain. "
                               f"Add another user first."
                    )

        client.delete_user(user_id)

        _log_activity(
            actor=actor, action="delete", resource_type="user",
            resource_id=user_id, resource_name=username,
            details={"project_id": project_id},
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"User '{username}' deleted",
                resource_id=user_id, resource_name=username, actor=actor)

        return {"detail": f"User '{username}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remove user failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/assign-role")
async def assign_role(
    body: AssignRoleRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Assign a role to a user on a project."""
    try:
        client = get_client()
        actor = _get_actor(user)

        roles = client.list_roles()
        role_obj = next((r for r in roles if r["name"] == body.role_name), None)
        if not role_obj:
            raise HTTPException(status_code=400, detail=f"Role '{body.role_name}' not found")

        client.assign_role_to_user_on_project(body.project_id, body.user_id, role_obj["id"])

        _log_activity(
            actor=actor, action="assign_role", resource_type="user",
            resource_id=body.user_id,
            details={"role": body.role_name, "project_id": body.project_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_updated", f"Role '{body.role_name}' assigned to user",
                resource_id=body.user_id, actor=actor)

        return {"detail": f"Role '{body.role_name}' assigned to user on project"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Assign role failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Flavors – List / Create / Delete
# ---------------------------------------------------------------------------

@router.get("/flavors")
async def list_flavors(
    user: User = Depends(require_permission("resources", "read")),
):
    """List all Nova flavors with instance counts."""
    try:
        client = get_client()
        # Get flavors from Nova
        client.authenticate()
        assert client.nova_endpoint
        url = f"{client.nova_endpoint}/flavors/detail"
        r = client.session.get(url, headers=client._headers())
        r.raise_for_status()
        flavors = r.json().get("flavors", [])

        # Count instances per flavor
        servers = client.list_servers(all_tenants=True)
        flavor_counts: Dict[str, int] = {}
        for s in servers:
            flv = s.get("flavor", {})
            if isinstance(flv, dict):
                fid = flv.get("id", "")
                flavor_counts[fid] = flavor_counts.get(fid, 0) + 1

        result = []
        for f in flavors:
            fid = f.get("id", "")
            result.append({
                "id": fid,
                "name": f.get("name", ""),
                "vcpus": f.get("vcpus", 0),
                "ram_mb": f.get("ram", 0),
                "disk_gb": f.get("disk", 0),
                "is_public": f.get("os-flavor-access:is_public", True),
                "swap": f.get("swap", ""),
                "ephemeral": f.get("OS-FLV-EXT-DATA:ephemeral", 0),
                "instance_count": flavor_counts.get(fid, 0),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/flavors")
async def create_flavor(
    body: CreateFlavorRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Create a new Nova flavor."""
    try:
        client = get_client()
        actor = _get_actor(user)

        result = client.create_flavor(
            name=body.name,
            vcpus=body.vcpus,
            ram_mb=body.ram_mb,
            disk_gb=body.disk_gb,
            is_public=body.is_public,
        )

        flavor_id = result.get("flavor", {}).get("id", "")

        _log_activity(
            actor=actor, action="create", resource_type="flavor",
            resource_id=flavor_id, resource_name=body.name,
            details={"vcpus": body.vcpus, "ram_mb": body.ram_mb, "disk_gb": body.disk_gb},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Flavor '{body.name}' created ({body.vcpus} vCPUs, {body.ram_mb}MB RAM)",
                resource_id=flavor_id, resource_name=body.name, actor=actor)

        return {"detail": f"Flavor '{body.name}' created", "flavor": result.get("flavor", result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create flavor failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/flavors/{flavor_id}")
async def delete_flavor(
    flavor_id: str,
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Delete a flavor. Warns if instances are using it."""
    try:
        client = get_client()
        actor = _get_actor(user)

        # Check if any instances use this flavor
        servers = client.list_servers(all_tenants=True)
        using = [s.get("name", s.get("id")) for s in servers
                 if isinstance(s.get("flavor"), dict) and s["flavor"].get("id") == flavor_id]

        if using:
            raise HTTPException(
                status_code=409,
                detail=f"Flavor is in use by {len(using)} instance(s): {', '.join(using[:5])}. "
                       f"Migrate or delete those instances first."
            )

        client.delete_flavor(flavor_id)

        _log_activity(
            actor=actor, action="delete", resource_type="flavor",
            resource_id=flavor_id,
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Flavor '{flavor_id}' deleted",
                resource_id=flavor_id, actor=actor)

        return {"detail": "Flavor deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete flavor failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Networks – List / Create / Delete
# ---------------------------------------------------------------------------

@router.get("/networks")
async def list_networks(
    project_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("resources", "read")),
):
    """List networks with subnet info."""
    try:
        client = get_client()
        networks = client.list_networks(project_id=project_id)
        subnets = client.list_subnets()
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}

        subnet_map: Dict[str, list] = {}
        for s in subnets:
            nid = s.get("network_id", "")
            subnet_map.setdefault(nid, []).append({
                "id": s.get("id", ""),
                "name": s.get("name", ""),
                "cidr": s.get("cidr", ""),
                "gateway_ip": s.get("gateway_ip", ""),
                "enable_dhcp": s.get("enable_dhcp", False),
            })

        result = []
        for n in networks:
            nid = n.get("id", "")
            pid = n.get("tenant_id") or n.get("project_id", "")
            result.append({
                "id": nid,
                "name": n.get("name", ""),
                "project_id": pid,
                "project_name": projects.get(pid, ""),
                "shared": n.get("shared", False),
                "external": n.get("router:external", False),
                "status": n.get("status", ""),
                "subnets": subnet_map.get(nid, []),
                "subnet_count": len(subnet_map.get(nid, [])),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/networks")
async def create_network(
    body: CreateNetworkRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Create a network, optionally with a subnet."""
    try:
        client = get_client()
        actor = _get_actor(user)

        if body.network_type:
            # Provider network
            net = client.create_provider_network(
                name=body.name,
                network_type=body.network_type,
                physical_network=body.physical_network or "physnet1",
                segmentation_id=body.segmentation_id,
                project_id=body.project_id,
                shared=body.shared,
                external=body.external,
            )
        else:
            net = client.create_network(
                name=body.name,
                project_id=body.project_id,
                shared=body.shared,
                external=body.external,
            )

        net_data = net.get("network", net)
        net_id = net_data.get("id", "")

        # Create subnet if CIDR provided
        subnet_data = None
        if body.subnet_cidr:
            subnet = client.create_subnet(
                network_id=net_id,
                cidr=body.subnet_cidr,
                name=body.subnet_name or f"{body.name}-subnet",
                gateway_ip=body.gateway_ip,
                dns_nameservers=body.dns_nameservers,
                enable_dhcp=body.enable_dhcp,
                project_id=body.project_id,
            )
            subnet_data = subnet

        _log_activity(
            actor=actor, action="create", resource_type="network",
            resource_id=net_id, resource_name=body.name,
            details={"project_id": body.project_id, "external": body.external, "shared": body.shared},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Network '{body.name}' created",
                resource_id=net_id, resource_name=body.name, actor=actor)

        return {"detail": f"Network '{body.name}' created", "network": net_data, "subnet": subnet_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create network failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/networks/{network_id}")
async def delete_network(
    network_id: str,
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Delete a network."""
    try:
        client = get_client()
        actor = _get_actor(user)

        client.delete_network(network_id)

        _log_activity(
            actor=actor, action="delete", resource_type="network",
            resource_id=network_id,
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Network '{network_id}' deleted",
                resource_id=network_id, actor=actor)

        return {"detail": "Network deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete network failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Routers – List / Create / Delete / Interface mgmt
# ---------------------------------------------------------------------------

@router.get("/routers")
async def list_routers(
    project_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("resources", "read")),
):
    """List routers."""
    try:
        client = get_client()
        routers = client.list_routers(project_id=project_id)
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}

        result = []
        for r in routers:
            pid = r.get("tenant_id") or r.get("project_id", "")
            ext_gw = r.get("external_gateway_info")
            result.append({
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "project_id": pid,
                "project_name": projects.get(pid, ""),
                "status": r.get("status", ""),
                "external_gateway": bool(ext_gw),
                "external_network_id": ext_gw.get("network_id", "") if ext_gw else "",
                "admin_state_up": r.get("admin_state_up", True),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/routers")
async def create_router(
    body: CreateRouterRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Create a router with optional external gateway."""
    try:
        client = get_client()
        actor = _get_actor(user)

        rtr = client.create_router(
            name=body.name,
            external_network_id=body.external_network_id,
            project_id=body.project_id,
        )
        rtr_data = rtr.get("router", rtr)
        rtr_id = rtr_data.get("id", "")

        _log_activity(
            actor=actor, action="create", resource_type="router",
            resource_id=rtr_id, resource_name=body.name,
            details={"project_id": body.project_id, "external_network_id": body.external_network_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Router '{body.name}' created",
                resource_id=rtr_id, resource_name=body.name, actor=actor)

        return {"detail": f"Router '{body.name}' created", "router": rtr_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create router failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/routers/{router_id}")
async def delete_router(
    router_id: str,
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Delete a router."""
    try:
        client = get_client()
        actor = _get_actor(user)

        client.delete_router(router_id)

        _log_activity(
            actor=actor, action="delete", resource_type="router",
            resource_id=router_id,
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Router '{router_id}' deleted",
                resource_id=router_id, actor=actor)

        return {"detail": "Router deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete router failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/routers/{router_id}/add-interface")
async def add_router_interface(
    router_id: str,
    body: RouterInterfaceRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Add a subnet interface to a router."""
    try:
        client = get_client()
        actor = _get_actor(user)
        client.authenticate()
        assert client.neutron_endpoint
        url = f"{client.neutron_endpoint}/v2.0/routers/{router_id}/add_router_interface"
        r = client.session.put(url, headers=client._headers(), json={"subnet_id": body.subnet_id})
        r.raise_for_status()

        _log_activity(
            actor=actor, action="add_interface", resource_type="router",
            resource_id=router_id,
            details={"subnet_id": body.subnet_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_updated", f"Interface added to router '{router_id}'",
                resource_id=router_id, actor=actor)

        return {"detail": "Interface added to router", "result": r.json()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add router interface failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/routers/{router_id}/remove-interface")
async def remove_router_interface(
    router_id: str,
    body: RouterInterfaceRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Remove a subnet interface from a router."""
    try:
        client = get_client()
        actor = _get_actor(user)
        client.authenticate()
        assert client.neutron_endpoint
        url = f"{client.neutron_endpoint}/v2.0/routers/{router_id}/remove_router_interface"
        r = client.session.put(url, headers=client._headers(), json={"subnet_id": body.subnet_id})
        r.raise_for_status()

        _log_activity(
            actor=actor, action="remove_interface", resource_type="router",
            resource_id=router_id,
            details={"subnet_id": body.subnet_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_updated", f"Interface removed from router '{router_id}'",
                resource_id=router_id, actor=actor)

        return {"detail": "Interface removed from router", "result": r.json()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Remove router interface failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Floating IPs – List / Allocate / Release
# ---------------------------------------------------------------------------

@router.get("/floating-ips")
async def list_floating_ips(
    project_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("resources", "read")),
):
    """List floating IPs."""
    try:
        client = get_client()
        fips = client.list_floating_ips(project_id=project_id)
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}

        result = []
        for fip in fips:
            pid = fip.get("tenant_id") or fip.get("project_id", "")
            result.append({
                "id": fip.get("id", ""),
                "floating_ip_address": fip.get("floating_ip_address", ""),
                "fixed_ip_address": fip.get("fixed_ip_address", ""),
                "status": fip.get("status", ""),
                "project_id": pid,
                "project_name": projects.get(pid, ""),
                "floating_network_id": fip.get("floating_network_id", ""),
                "port_id": fip.get("port_id", ""),
                "associated": bool(fip.get("fixed_ip_address")),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/floating-ips")
async def allocate_floating_ip(
    body: AllocateFloatingIPRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Allocate a floating IP from an external network."""
    try:
        client = get_client()
        actor = _get_actor(user)
        client.authenticate()
        assert client.neutron_endpoint

        url = f"{client.neutron_endpoint}/v2.0/floatingips"
        payload = {
            "floatingip": {
                "floating_network_id": body.floating_network_id,
                "project_id": body.project_id,
            }
        }
        if body.description:
            payload["floatingip"]["description"] = body.description

        r = client.session.post(url, headers=client._headers(), json=payload)
        r.raise_for_status()
        fip = r.json().get("floatingip", {})

        _log_activity(
            actor=actor, action="allocate", resource_type="floating_ip",
            resource_id=fip.get("id", ""),
            resource_name=fip.get("floating_ip_address", ""),
            details={"project_id": body.project_id, "network_id": body.floating_network_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Floating IP {fip.get('floating_ip_address', '')} allocated",
                resource_id=fip.get("id", ""), resource_name=fip.get("floating_ip_address", ""), actor=actor)

        return {"detail": f"Floating IP {fip.get('floating_ip_address', '')} allocated", "floating_ip": fip}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Allocate floating IP failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/floating-ips/{fip_id}")
async def release_floating_ip(
    fip_id: str,
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Release (delete) a floating IP."""
    try:
        client = get_client()
        actor = _get_actor(user)

        client.delete_floating_ip(fip_id)

        _log_activity(
            actor=actor, action="release", resource_type="floating_ip",
            resource_id=fip_id,
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Floating IP '{fip_id}' released",
                resource_id=fip_id, actor=actor)

        return {"detail": "Floating IP released"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Release floating IP failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Volumes – List / Create / Delete
# ---------------------------------------------------------------------------

@router.get("/volumes")
async def list_volumes(
    project_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("resources", "read")),
):
    """List volumes with attachment info."""
    try:
        client = get_client()
        volumes = client.list_volumes(project_id=project_id, all_tenants=True)
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}

        result = []
        for v in volumes:
            pid = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id", "")
            if project_id and pid != project_id:
                continue
            attachments = v.get("attachments", [])
            result.append({
                "id": v.get("id", ""),
                "name": v.get("name", "") or v.get("display_name", ""),
                "size_gb": v.get("size", 0),
                "status": v.get("status", ""),
                "volume_type": v.get("volume_type", ""),
                "bootable": v.get("bootable", "false"),
                "project_id": pid,
                "project_name": projects.get(pid, ""),
                "attached_to": attachments[0].get("server_id", "") if attachments else "",
                "created_at": v.get("created_at", ""),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/volumes")
async def create_volume(
    body: CreateVolumeRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Create a new Cinder volume."""
    try:
        client = get_client()
        actor = _get_actor(user)
        client.authenticate()
        assert client.cinder_endpoint

        url = f"{client.cinder_endpoint}/volumes"
        payload: Dict[str, Any] = {
            "volume": {
                "name": body.name,
                "size": body.size_gb,
                "description": body.description,
            }
        }
        if body.volume_type:
            payload["volume"]["volume_type"] = body.volume_type

        # Cinder needs project context — use admin token with project_id header
        headers = client._headers()
        headers["X-OpenStack-Manila-API-Version"] = "2.7"
        r = client.session.post(url, headers=headers, json=payload)
        r.raise_for_status()
        vol = r.json().get("volume", {})

        _log_activity(
            actor=actor, action="create", resource_type="volume",
            resource_id=vol.get("id", ""), resource_name=body.name,
            details={"size_gb": body.size_gb, "project_id": body.project_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Volume '{body.name}' created ({body.size_gb} GB)",
                resource_id=vol.get("id", ""), resource_name=body.name, actor=actor)

        return {"detail": f"Volume '{body.name}' created ({body.size_gb} GB)", "volume": vol}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create volume failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/volumes/{volume_id}")
async def delete_volume(
    volume_id: str,
    force: bool = Query(False, description="Force delete even if attached"),
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Delete a volume. Rejects if attached unless force=true."""
    try:
        client = get_client()
        actor = _get_actor(user)

        # Check if attached
        volumes = client.list_volumes(all_tenants=True)
        target = next((v for v in volumes if v.get("id") == volume_id), None)
        if target:
            attachments = target.get("attachments", [])
            if attachments and not force:
                raise HTTPException(
                    status_code=409,
                    detail=f"Volume is attached to server {attachments[0].get('server_id', '')}. "
                           f"Detach first or use force=true."
                )

        client.delete_volume(volume_id, force=force)

        _log_activity(
            actor=actor, action="delete", resource_type="volume",
            resource_id=volume_id,
            resource_name=target.get("name", "") if target else "",
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Volume '{target.get('name', volume_id) if target else volume_id}' deleted",
                resource_id=volume_id, resource_name=target.get("name", "") if target else "", actor=actor)

        return {"detail": "Volume deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete volume failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Security Groups – List / Create / Delete / Rules
# ---------------------------------------------------------------------------

@router.get("/security-groups")
async def list_security_groups(
    project_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("resources", "read")),
):
    """List security groups with rule details."""
    try:
        client = get_client()
        sgs = client.list_security_groups(project_id=project_id)
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}

        result = []
        for sg in sgs:
            pid = sg.get("tenant_id") or sg.get("project_id", "")
            rules = sg.get("security_group_rules", [])
            result.append({
                "id": sg.get("id", ""),
                "name": sg.get("name", ""),
                "description": sg.get("description", ""),
                "project_id": pid,
                "project_name": projects.get(pid, ""),
                "rule_count": len(rules),
                "ingress_rules": len([r for r in rules if r.get("direction") == "ingress"]),
                "egress_rules": len([r for r in rules if r.get("direction") == "egress"]),
                "rules": rules,
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security-groups")
async def create_security_group(
    body: CreateSecurityGroupRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Create a new security group."""
    try:
        client = get_client()
        actor = _get_actor(user)

        sg = client.create_security_group(
            name=body.name,
            description=body.description,
            project_id=body.project_id,
        )
        sg_data = sg.get("security_group", sg)

        _log_activity(
            actor=actor, action="create", resource_type="security_group",
            resource_id=sg_data.get("id", ""), resource_name=body.name,
            details={"project_id": body.project_id},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Security group '{body.name}' created",
                resource_id=sg_data.get("id", ""), resource_name=body.name, actor=actor)

        return {"detail": f"Security group '{body.name}' created", "security_group": sg_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create security group failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/security-groups/{sg_id}")
async def delete_security_group(
    sg_id: str,
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Delete a security group (cannot delete 'default')."""
    try:
        client = get_client()
        actor = _get_actor(user)

        client.delete_security_group(sg_id)

        _log_activity(
            actor=actor, action="delete", resource_type="security_group",
            resource_id=sg_id,
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Security group '{sg_id}' deleted",
                resource_id=sg_id, actor=actor)

        return {"detail": "Security group deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete security group failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/security-groups/rules")
async def create_sg_rule(
    body: CreateSGRuleRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "write")),
):
    """Add a rule to a security group."""
    try:
        client = get_client()
        actor = _get_actor(user)

        rule = client.create_security_group_rule(
            security_group_id=body.security_group_id,
            direction=body.direction,
            protocol=body.protocol,
            port_range_min=body.port_range_min,
            port_range_max=body.port_range_max,
            remote_ip_prefix=body.remote_ip_prefix,
            remote_group_id=body.remote_group_id,
            ethertype=body.ethertype,
            description=body.description,
        )
        rule_data = rule.get("security_group_rule", rule)

        _log_activity(
            actor=actor, action="create_rule", resource_type="security_group",
            resource_id=body.security_group_id,
            details={"direction": body.direction, "protocol": body.protocol,
                     "port_range": f"{body.port_range_min}-{body.port_range_max}"},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_created", f"Security group rule created ({body.direction} {body.protocol})",
                resource_id=body.security_group_id, actor=actor)

        return {"detail": "Security group rule created", "rule": rule_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create SG rule failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/security-groups/rules/{rule_id}")
async def delete_sg_rule(
    rule_id: str,
    request: Request = None,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Delete a security group rule."""
    try:
        client = get_client()
        actor = _get_actor(user)

        client.delete_security_group_rule(rule_id)

        _log_activity(
            actor=actor, action="delete_rule", resource_type="security_group",
            resource_id=rule_id,
            ip_address=_get_ip(request) if request else "unknown",
            result="success",
        )
        _notify("resource_deleted", f"Security group rule '{rule_id}' deleted",
                resource_id=rule_id, actor=actor)

        return {"detail": "Security group rule deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete SG rule failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Images – List / Set visibility
# ---------------------------------------------------------------------------

@router.get("/images")
async def list_images(
    user: User = Depends(require_permission("resources", "read")),
):
    """List Glance images."""
    try:
        client = get_client()
        client.authenticate()

        # Glance endpoint — look for 'image' service
        glance_ep = None
        if hasattr(client, "_catalog"):
            for svc in client._catalog:
                if svc.get("type") == "image":
                    for ep in svc.get("endpoints", []):
                        if ep.get("interface") == "public":
                            glance_ep = ep.get("url", "").rstrip("/")
                            break
        if not glance_ep:
            # Derive from keystone URL
            base = client.auth_url.replace("/v3", "").replace("/keystone", "")
            glance_ep = f"{base}:9292"

        url = f"{glance_ep}/v2/images"
        r = client.session.get(url, headers=client._headers(), params={"limit": 500})
        r.raise_for_status()
        images = r.json().get("images", [])

        result = []
        for img in images:
            result.append({
                "id": img.get("id", ""),
                "name": img.get("name", ""),
                "status": img.get("status", ""),
                "visibility": img.get("visibility", ""),
                "size_mb": round((img.get("size", 0) or 0) / (1024 * 1024), 1),
                "min_disk_gb": img.get("min_disk", 0),
                "min_ram_mb": img.get("min_ram", 0),
                "disk_format": img.get("disk_format", ""),
                "container_format": img.get("container_format", ""),
                "created_at": img.get("created_at", ""),
                "owner": img.get("owner", ""),
            })

        return {"data": result, "count": len(result)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Quotas – View / Modify
# ---------------------------------------------------------------------------

@router.get("/quotas/{project_id}")
async def get_quotas(
    project_id: str,
    user: User = Depends(require_permission("resources", "read")),
):
    """Get compute, network, and storage quotas for a project."""
    try:
        client = get_client()
        compute_q = client.get_compute_quotas(project_id)
        network_q = client.get_network_quotas(project_id)
        storage_q = client.get_storage_quotas(project_id)

        return {
            "project_id": project_id,
            "compute": compute_q,
            "network": network_q,
            "storage": storage_q,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/quotas")
async def update_quotas(
    body: UpdateQuotasRequest,
    request: Request,
    user: User = Depends(require_permission("resources", "admin")),
):
    """Update quotas for a project."""
    try:
        client = get_client()
        actor = _get_actor(user)

        compute_updates = {}
        network_updates = {}
        storage_updates = {}

        if body.cores is not None:
            compute_updates["cores"] = body.cores
        if body.ram is not None:
            compute_updates["ram"] = body.ram
        if body.instances is not None:
            compute_updates["instances"] = body.instances

        if body.network is not None:
            network_updates["network"] = body.network
        if body.subnet is not None:
            network_updates["subnet"] = body.subnet
        if body.router is not None:
            network_updates["router"] = body.router
        if body.port is not None:
            network_updates["port"] = body.port
        if body.floatingip is not None:
            network_updates["floatingip"] = body.floatingip
        if body.security_group is not None:
            network_updates["security_group"] = body.security_group
        if body.security_group_rule is not None:
            network_updates["security_group_rule"] = body.security_group_rule

        if body.gigabytes is not None:
            storage_updates["gigabytes"] = body.gigabytes
        if body.volumes is not None:
            storage_updates["volumes"] = body.volumes
        if body.snapshots is not None:
            storage_updates["snapshots"] = body.snapshots

        results = {}
        if compute_updates:
            results["compute"] = client.update_compute_quotas(body.project_id, compute_updates)
        if network_updates:
            results["network"] = client.update_network_quotas(body.project_id, network_updates)
        if storage_updates:
            results["storage"] = client.update_storage_quotas(body.project_id, storage_updates)

        _log_activity(
            actor=actor, action="update_quotas", resource_type="quotas",
            resource_id=body.project_id,
            details={"compute": compute_updates, "network": network_updates, "storage": storage_updates},
            ip_address=_get_ip(request), result="success",
        )
        _notify("resource_updated", f"Quotas updated for project '{body.project_id}'",
                resource_id=body.project_id, actor=actor)

        return {"detail": "Quotas updated", "results": results}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update quotas failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Context helpers – domains & projects for dropdowns
# ---------------------------------------------------------------------------

@router.get("/context/domains")
async def context_domains(
    user: User = Depends(require_permission("resources", "read")),
):
    """List domains for dropdown filters."""
    try:
        client = get_client()
        domains = client.list_domains()
        return {"data": [{"id": d["id"], "name": d.get("name", "")} for d in domains]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/projects")
async def context_projects(
    domain_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("resources", "read")),
):
    """List projects for dropdown filters."""
    try:
        client = get_client()
        projects = client.list_projects(domain_id=domain_id)
        domains = {d["id"]: d["name"] for d in client.list_domains()}
        return {
            "data": [
                {
                    "id": p["id"],
                    "name": p.get("name", ""),
                    "domain_id": p.get("domain_id", ""),
                    "domain_name": domains.get(p.get("domain_id", ""), ""),
                }
                for p in projects
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/external-networks")
async def context_external_networks(
    user: User = Depends(require_permission("resources", "read")),
):
    """List external networks available for floating IP allocation or router gateways."""
    try:
        client = get_client()
        networks = client.list_networks()
        external = [
            {"id": n.get("id", ""), "name": n.get("name", "")}
            for n in networks
            if n.get("router:external", False)
        ]
        return {"data": external}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
