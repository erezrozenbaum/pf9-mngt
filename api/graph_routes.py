"""
Cloud Dependency Graph API
==========================
Builds a node+edge graph starting from any supported resource,
traversing relationships up to a configurable depth (BFS).

Endpoint:
  GET /api/graph
    ?root_type = vm | volume | network | tenant | snapshot |
                 security_group | floating_ip | subnet | port | host | image | domain
    &root_id   = <uuid>
    &depth     = 1 | 2 | 3   (default: 2)
    &domain    = <domain_id>  (optional — restrict expansion to nodes in this domain)

Response:
  {
    "nodes": [ { "id", "db_id", "type", "label", "status", "badges" }, ... ],
    "edges": [ { "source", "target", "label" }, ... ],
    "root":       "<node-id>",
    "depth":      <int>,
    "node_count": <int>,
    "edge_count": <int>,
    "truncated":  <bool>   -- true if MAX_NODES limit was hit
  }

Badge types:
  no_snapshot    Volume has no snapshots
  drift          Resource has unacknowledged drift events
  error_state    status = ERROR / error
  power_off      VM is SHUTOFF
  restore_source Snapshot referenced by a restore job
  compliance_gap (alias for no_snapshot, used in UI)

RBAC: requires resources:read (viewer and above)
"""

from __future__ import annotations

import logging
import re
from collections import deque
from typing import Optional, List, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from db_pool import get_connection

logger = logging.getLogger("pf9.graph")

router = APIRouter(prefix="/api/graph", tags=["graph"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_NODES = 150      # hard cap; BFS stops and sets truncated=True
MAX_DEPTH = 3

# Root-type aliases: user-facing name → internal ntype key
ROOT_TYPE_ALIAS: Dict[str, str] = {
    "vm":             "vm",
    "volume":         "volume",
    "snapshot":       "snapshot",
    "network":        "network",
    "subnet":         "subnet",
    "port":           "port",
    "floating_ip":    "fip",
    "security_group": "sg",
    "tenant":         "tenant",
    "host":           "host",
    "image":          "image",
    "domain":         "domain",
}

# Map internal ntype → drift_events.resource_type string
_DRIFT_TYPE_MAP: Dict[str, str] = {
    "vm":       "servers",
    "volume":   "volumes",
    "snapshot": "snapshots",
    "network":  "networks",
    "sg":       "security_groups",
    "host":     "hypervisors",
}

# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _make_node(row: Dict, ntype: str, badges: List[str]) -> Dict:
    """Convert a DB row dict into a standardised graph node dict."""
    label = (
        row.get("name")
        or row.get("hostname")
        or row.get("floating_ip")
        or row.get("id", "")
    )
    status = row.get("status") or row.get("state")
    return {
        "id":     f"{ntype}-{row['id']}",
        "db_id":  row["id"],
        "type":   ntype,
        "label":  label,
        "status": status,
        "badges": badges,
    }


def _make_edge(
    src_ntype: str, src_db_id: str,
    tgt_ntype: str, tgt_db_id: str,
    label: str,
) -> Dict:
    return {
        "source": f"{src_ntype}-{src_db_id}",
        "target": f"{tgt_ntype}-{tgt_db_id}",
        "label":  label,
    }


# ---------------------------------------------------------------------------
# Per-type DB fetchers — each returns a plain dict or None
# ---------------------------------------------------------------------------

def _fetch_vm(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, status, project_id, hypervisor_hostname, image_id "
        "FROM servers WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_volume(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, status, project_id, server_id FROM volumes WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_snapshot(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, status, volume_id, project_id FROM snapshots WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_network(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, status, project_id FROM networks WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_subnet(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, network_id FROM subnets WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_port(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, status, network_id, device_id, device_owner "
        "FROM ports WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_fip(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, floating_ip AS name, floating_ip, status, project_id, port_id "
        "FROM floating_ips WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_sg(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, project_id FROM security_groups WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_tenant(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, domain_id FROM projects WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_host(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, hostname, state, status FROM hypervisors WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_image(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name, status FROM images WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


def _fetch_domain(cur, db_id: str) -> Optional[Dict]:
    cur.execute(
        "SELECT id, name FROM domains WHERE id = %s",
        (db_id,),
    )
    r = cur.fetchone()
    return dict(r) if r else None


FETCHERS: Dict[str, Any] = {
    "vm":       _fetch_vm,
    "volume":   _fetch_volume,
    "snapshot": _fetch_snapshot,
    "network":  _fetch_network,
    "subnet":   _fetch_subnet,
    "port":     _fetch_port,
    "fip":      _fetch_fip,
    "sg":       _fetch_sg,
    "tenant":   _fetch_tenant,
    "host":     _fetch_host,
    "image":    _fetch_image,
    "domain":   _fetch_domain,
}


# ---------------------------------------------------------------------------
# Badge computation
# ---------------------------------------------------------------------------

def _compute_badges(cur, ntype: str, db_id: str, row: Dict) -> List[str]:
    badges: List[str] = []

    # error_state
    s = (row.get("status") or "").upper()
    if s in ("ERROR", "ERROR_RESTORING", "ERROR_DELETING", "ERROR_EXTENDING"):
        badges.append("error_state")

    # power_off (VMs only)
    if ntype == "vm" and s == "SHUTOFF":
        badges.append("power_off")

    # no_snapshot (volumes only)
    if ntype == "volume":
        cur.execute(
            "SELECT 1 FROM snapshots WHERE volume_id = %s LIMIT 1",
            (db_id,),
        )
        if not cur.fetchone():
            badges.append("no_snapshot")

    # drift — resource has unacknowledged drift events
    drift_rtype = _DRIFT_TYPE_MAP.get(ntype)
    if drift_rtype:
        cur.execute(
            "SELECT 1 FROM drift_events "
            "WHERE resource_type = %s AND resource_id = %s AND acknowledged = false "
            "LIMIT 1",
            (drift_rtype, db_id),
        )
        if cur.fetchone():
            badges.append("drift")

    # restore_source — snapshot used as a restore point
    if ntype == "snapshot":
        cur.execute(
            "SELECT 1 FROM restore_jobs WHERE restore_point_id = %s LIMIT 1",
            (db_id,),
        )
        if cur.fetchone():
            badges.append("restore_source")

    return badges


# ---------------------------------------------------------------------------
# Domain filter helper
# ---------------------------------------------------------------------------

def _in_domain(row: Dict, domain_filter: Optional[str]) -> bool:
    if not domain_filter:
        return True
    return row.get("domain_id") == domain_filter


# ---------------------------------------------------------------------------
# Neighbor expansion — returns list of (ntype, row_dict, edge_label)
# ---------------------------------------------------------------------------

def _expand_vm(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    vm_id = row["id"]

    # VM → Tenant
    if row.get("project_id"):
        t = _fetch_tenant(cur, row["project_id"])
        if t and _in_domain(t, domain_filter):
            neighbors.append(("tenant", t, "belongs to"))

    # VM → Volumes attached to this VM
    cur.execute(
        "SELECT id, name, status, project_id, server_id FROM volumes WHERE server_id = %s",
        (vm_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("volume", dict(r), "has volume"))

    # VM → Networks (via ports)
    cur.execute(
        "SELECT DISTINCT n.id, n.name, n.status, n.project_id "
        "FROM networks n "
        "JOIN ports p ON p.network_id = n.id "
        "WHERE p.device_id = %s AND p.device_owner LIKE 'compute:%%'",
        (vm_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("network", dict(r), "connected to"))

    # VM → Security Groups (via ports.raw_json->'security_groups' UUID array)
    cur.execute(
        "SELECT DISTINCT sg.id, sg.name, sg.project_id "
        "FROM security_groups sg "
        "JOIN ports p ON (p.raw_json->'security_groups') ? sg.id "
        "WHERE p.device_id = %s AND p.device_owner LIKE 'compute:%%'",
        (vm_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("sg", dict(r), "member of"))

    # VM → Floating IPs (via port chain)
    cur.execute(
        "SELECT fi.id, fi.floating_ip AS name, fi.floating_ip, fi.status, "
        "       fi.project_id, fi.port_id "
        "FROM floating_ips fi "
        "JOIN ports p ON p.id = fi.port_id "
        "WHERE p.device_id = %s AND p.device_owner LIKE 'compute:%%'",
        (vm_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("fip", dict(r), "has floating IP"))

    # VM → Hypervisor/Host
    if row.get("hypervisor_hostname"):
        cur.execute(
            "SELECT id, hostname, state, status FROM hypervisors "
            "WHERE hostname = %s LIMIT 1",
            (row["hypervisor_hostname"],),
        )
        r = cur.fetchone()
        if r:
            neighbors.append(("host", dict(r), "runs on"))

    # VM → Image
    if row.get("image_id"):
        img = _fetch_image(cur, row["image_id"])
        if img:
            neighbors.append(("image", img, "uses image"))

    return neighbors


def _expand_volume(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    vol_id = row["id"]

    # Volume → Tenant
    if row.get("project_id"):
        t = _fetch_tenant(cur, row["project_id"])
        if t and _in_domain(t, domain_filter):
            neighbors.append(("tenant", t, "belongs to"))

    # Volume → Snapshots
    cur.execute(
        "SELECT id, name, status, volume_id, project_id FROM snapshots WHERE volume_id = %s",
        (vol_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("snapshot", dict(r), "has snapshot"))

    # Volume → VM (attached to)
    if row.get("server_id"):
        vm = _fetch_vm(cur, row["server_id"])
        if vm:
            neighbors.append(("vm", vm, "attached to VM"))

    return neighbors


def _expand_snapshot(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []

    # Snapshot → Volume
    if row.get("volume_id"):
        vol = _fetch_volume(cur, row["volume_id"])
        if vol:
            neighbors.append(("volume", vol, "snapshot of"))

    return neighbors


def _expand_network(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    net_id = row["id"]

    # Network → Tenant
    if row.get("project_id"):
        t = _fetch_tenant(cur, row["project_id"])
        if t and _in_domain(t, domain_filter):
            neighbors.append(("tenant", t, "belongs to"))

    # Network → Subnets
    cur.execute(
        "SELECT id, name, network_id FROM subnets WHERE network_id = %s",
        (net_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("subnet", dict(r), "has subnet"))

    # Network → VMs attached via ports
    cur.execute(
        "SELECT DISTINCT s.id, s.name, s.status, s.project_id, "
        "       s.hypervisor_hostname, s.image_id "
        "FROM servers s "
        "JOIN ports p ON p.device_id = s.id "
        "WHERE p.network_id = %s AND p.device_owner LIKE 'compute:%%'",
        (net_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("vm", dict(r), "hosts VM"))

    return neighbors


def _expand_subnet(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []

    # Subnet → Network
    if row.get("network_id"):
        net = _fetch_network(cur, row["network_id"])
        if net:
            neighbors.append(("network", net, "part of"))

    return neighbors


def _expand_port(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    port_id = row["id"]

    # Port → Network
    if row.get("network_id"):
        net = _fetch_network(cur, row["network_id"])
        if net:
            neighbors.append(("network", net, "on network"))

    # Port → Floating IP
    cur.execute(
        "SELECT id, floating_ip AS name, floating_ip, status, project_id, port_id "
        "FROM floating_ips WHERE port_id = %s",
        (port_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("fip", dict(r), "has floating IP"))

    # Port → VM (if compute port)
    if row.get("device_id") and (row.get("device_owner") or "").startswith("compute:"):
        vm = _fetch_vm(cur, row["device_id"])
        if vm:
            neighbors.append(("vm", vm, "belongs to VM"))

    return neighbors


def _expand_fip(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []

    # FIP → VM (via port, resolved directly to avoid spending depth on port)
    if row.get("port_id"):
        cur.execute(
            "SELECT p.id, p.name, p.status, p.network_id, p.device_id, p.device_owner "
            "FROM ports p WHERE p.id = %s",
            (row["port_id"],),
        )
        port_row = cur.fetchone()
        if port_row:
            port = dict(port_row)
            if port.get("device_id") and (port.get("device_owner") or "").startswith("compute:"):
                vm = _fetch_vm(cur, port["device_id"])
                if vm:
                    neighbors.append(("vm", vm, "assigned to VM"))

    return neighbors


def _expand_sg(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    sg_id = row["id"]

    # SG → Tenant
    if row.get("project_id"):
        t = _fetch_tenant(cur, row["project_id"])
        if t and _in_domain(t, domain_filter):
            neighbors.append(("tenant", t, "belongs to"))

    # SG → VMs protected by this SG (reverse: VMs whose ports have this SG UUID)
    cur.execute(
        "SELECT DISTINCT s.id, s.name, s.status, s.project_id, "
        "       s.hypervisor_hostname, s.image_id "
        "FROM servers s "
        "JOIN ports p ON p.device_id = s.id "
        "WHERE (p.raw_json->'security_groups') ? %s "
        "  AND p.device_owner LIKE 'compute:%%'",
        (sg_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("vm", dict(r), "protects VM"))

    return neighbors


def _expand_tenant(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    tenant_id = row["id"]

    # Tenant → Domain
    if row.get("domain_id"):
        dom = _fetch_domain(cur, row["domain_id"])
        if dom:
            neighbors.append(("domain", dom, "in domain"))

    # Tenant → VMs
    cur.execute(
        "SELECT id, name, status, project_id, hypervisor_hostname, image_id "
        "FROM servers WHERE project_id = %s",
        (tenant_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("vm", dict(r), "owns VM"))

    # Tenant → Networks
    cur.execute(
        "SELECT id, name, status, project_id FROM networks WHERE project_id = %s",
        (tenant_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("network", dict(r), "owns network"))

    # Tenant → Volumes
    cur.execute(
        "SELECT id, name, status, project_id, server_id FROM volumes WHERE project_id = %s",
        (tenant_id,),
    )
    for r in cur.fetchall():
        neighbors.append(("volume", dict(r), "owns volume"))

    return neighbors


def _expand_host(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []
    hostname = row.get("hostname") or ""

    # Host → VMs running on it
    if hostname:
        cur.execute(
            "SELECT id, name, status, project_id, hypervisor_hostname, image_id "
            "FROM servers WHERE hypervisor_hostname = %s",
            (hostname,),
        )
        for r in cur.fetchall():
            neighbors.append(("vm", dict(r), "runs VM"))

    return neighbors


def _expand_image(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []

    # Image → VMs using this image
    cur.execute(
        "SELECT id, name, status, project_id, hypervisor_hostname, image_id "
        "FROM servers WHERE image_id = %s",
        (row["id"],),
    )
    for r in cur.fetchall():
        neighbors.append(("vm", dict(r), "used by VM"))

    return neighbors


def _expand_domain(
    cur, row: Dict, domain_filter: Optional[str]
) -> List[Tuple[str, Dict, str]]:
    neighbors: List[Tuple[str, Dict, str]] = []

    # Domain → Tenants
    cur.execute(
        "SELECT id, name, domain_id FROM projects WHERE domain_id = %s",
        (row["id"],),
    )
    for r in cur.fetchall():
        neighbors.append(("tenant", dict(r), "has tenant"))

    return neighbors


EXPANDERS: Dict[str, Any] = {
    "vm":       _expand_vm,
    "volume":   _expand_volume,
    "snapshot": _expand_snapshot,
    "network":  _expand_network,
    "subnet":   _expand_subnet,
    "port":     _expand_port,
    "fip":      _expand_fip,
    "sg":       _expand_sg,
    "tenant":   _expand_tenant,
    "host":     _expand_host,
    "image":    _expand_image,
    "domain":   _expand_domain,
}


# ---------------------------------------------------------------------------
# BFS graph builder
# ---------------------------------------------------------------------------

def _build_graph(
    cur,
    root_ntype: str,
    root_db_id: str,
    max_depth: int,
    domain_filter: Optional[str],
) -> Optional[Dict]:
    """
    BFS from (root_ntype, root_db_id) up to max_depth hops.
    Returns the complete graph dict, or None if the root resource is not found.
    """
    root_row = FETCHERS[root_ntype](cur, root_db_id)
    if root_row is None:
        return None

    nodes_by_id: Dict[str, Dict] = {}
    edges_set: set = set()
    edges_list: List[Dict] = []
    truncated = False

    def add_node(ntype: str, row: Dict) -> str:
        nid = f"{ntype}-{row['id']}"
        if nid not in nodes_by_id:
            badges = _compute_badges(cur, ntype, row["id"], row)
            nodes_by_id[nid] = _make_node(row, ntype, badges)
        return nid

    def add_edge(
        src_ntype: str, src_id: str,
        tgt_ntype: str, tgt_id: str,
        label: str,
    ) -> None:
        key = (f"{src_ntype}-{src_id}", f"{tgt_ntype}-{tgt_id}", label)
        if key not in edges_set:
            edges_set.add(key)
            edges_list.append(_make_edge(src_ntype, src_id, tgt_ntype, tgt_id, label))

    # Seed BFS with the root
    add_node(root_ntype, root_row)
    root_node_id = f"{root_ntype}-{root_db_id}"

    # queue items: (ntype, row_dict, current_depth)
    queue: deque = deque([(root_ntype, root_row, 0)])
    visited: set = {root_node_id}

    while queue:
        ntype, row, depth = queue.popleft()
        if depth >= max_depth:
            continue

        expander = EXPANDERS.get(ntype)
        if not expander:
            continue

        for neighbor_ntype, neighbor_row, edge_label in expander(cur, row, domain_filter):
            if len(nodes_by_id) >= MAX_NODES:
                truncated = True
                break

            add_node(neighbor_ntype, neighbor_row)
            add_edge(ntype, row["id"], neighbor_ntype, neighbor_row["id"], edge_label)

            neighbor_node_id = f"{neighbor_ntype}-{neighbor_row['id']}"
            if neighbor_node_id not in visited:
                visited.add(neighbor_node_id)
                queue.append((neighbor_ntype, neighbor_row, depth + 1))

        if truncated:
            break

    return {
        "nodes":      list(nodes_by_id.values()),
        "edges":      edges_list,
        "root":       root_node_id,
        "depth":      max_depth,
        "node_count": len(nodes_by_id),
        "edge_count": len(edges_list),
        "truncated":  truncated,
    }


# ---------------------------------------------------------------------------
# UUID validation
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _is_valid_id(value: str) -> bool:
    """Accept standard UUID format or legacy short IDs (at least 8 hex chars)."""
    if _UUID_RE.match(value):
        return True
    # Some OpenStack resources use non-UUID IDs (e.g. flavors)
    return bool(re.match(r'^[0-9a-zA-Z_\-]{4,64}$', value))


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("")
async def get_dependency_graph(
    root_type: str = Query(..., description="Resource type to start from"),
    root_id: str = Query(..., description="ID of the root resource"),
    depth: int = Query(2, ge=1, le=MAX_DEPTH, description="Number of hops to traverse (1–3)"),
    domain: Optional[str] = Query(None, description="Restrict expansion to nodes in this domain"),
    migration_project_id: Optional[int] = Query(None, description="Migration project ID — enriches nodes with migration status overlay"),
    current_user: User = Depends(require_permission("resources", "read")),
):
    """
    Return a dependency graph starting from the specified resource.

    Traverses up to `depth` hops using BFS, collecting all connected nodes and
    the relationships between them.  Stops at MAX_NODES (150) to prevent
    hairball graphs; sets `truncated: true` in the response when capped.

    Optional `migration_project_id` adds a `migration_overlay` field to every
    vm/tenant node: {"status": "confirmed"|"pending"|"missing"} based on that
    node's current migration status within the given migration project.
    """
    if root_type not in ROOT_TYPE_ALIAS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid root_type '{root_type}'. "
                f"Must be one of: {', '.join(sorted(ROOT_TYPE_ALIAS))}"
            ),
        )

    if not _is_valid_id(root_id):
        raise HTTPException(status_code=400, detail="Invalid root_id format")

    if domain and not _is_valid_id(domain):
        raise HTTPException(status_code=400, detail="Invalid domain filter format")

    ntype = ROOT_TYPE_ALIAS[root_type]

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = _build_graph(cur, ntype, root_id, depth, domain)
                if result is not None and migration_project_id is not None:
                    _apply_migration_overlay(cur, result, migration_project_id)
    except Exception as exc:
        logger.error("Graph build error for %s/%s: %s", root_type, root_id, exc)
        raise HTTPException(status_code=500, detail="Graph query failed")

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"{root_type} '{root_id}' not found",
        )

    return result


# ---------------------------------------------------------------------------
# Migration overlay enrichment
# ---------------------------------------------------------------------------

# VM migration_status values → overlay status
_VM_STATUS_CONFIRMED = {"complete", "validated"}
_VM_STATUS_PENDING   = {"in_progress", "validating", "pre_checks_passed", "executing"}


def _apply_migration_overlay(cur, result: Dict, migration_project_id: int) -> None:
    """
    Enrich graph nodes with migration status from the given migration project.

    Matching is by name:
      - tenant node label  → migration_tenants.tenant_name  (also tries target_project_name)
      - vm node label      → migration_vms.vm_name

    Adds   node["migration_overlay"] = {"status": "confirmed"|"pending"|"missing"}
    for matched nodes.  Unmatched nodes get  migration_overlay = None.
    """
    # Load migration tenant statuses — key by both tenant_name and target_project_name
    cur.execute(
        """
        SELECT tenant_name, target_project_name, target_confirmed, include_in_plan
        FROM migration_tenants
        WHERE project_id = %s
        """,
        (str(migration_project_id),),
    )
    tenant_overlay: Dict[str, Dict] = {}
    for row in cur.fetchall():
        entry = {
            "target_confirmed": row["target_confirmed"],
            "include_in_plan":  row["include_in_plan"],
        }
        if row["tenant_name"]:
            tenant_overlay[row["tenant_name"]] = entry
        if row["target_project_name"]:
            # target_project_name takes priority — it's the OpenStack destination
            tenant_overlay[row["target_project_name"]] = entry

    # Load migration VM statuses — key by vm_name
    cur.execute(
        """
        SELECT vm_name, migration_status
        FROM migration_vms
        WHERE project_id = %s AND (template IS NOT TRUE)
        """,
        (str(migration_project_id),),
    )
    vm_overlay: Dict[str, str] = {
        r["vm_name"]: (r["migration_status"] or "not_started")
        for r in cur.fetchall()
    }

    # Annotate each node
    for node in result["nodes"]:
        ntype = node["type"]
        label = node.get("label") or ""

        if ntype == "tenant":
            entry = tenant_overlay.get(label)
            if entry is None:
                node["migration_overlay"] = None
            elif entry["include_in_plan"] is False:
                # Out of scope — treat as missing
                node["migration_overlay"] = {"status": "missing"}
            elif entry["target_confirmed"]:
                node["migration_overlay"] = {"status": "confirmed"}
            else:
                node["migration_overlay"] = {"status": "pending"}

        elif ntype == "vm":
            vm_status = vm_overlay.get(label)
            if vm_status is None:
                node["migration_overlay"] = None
            elif vm_status.lower() in _VM_STATUS_CONFIRMED:
                node["migration_overlay"] = {"status": "confirmed"}
            elif vm_status.lower() in _VM_STATUS_PENDING:
                node["migration_overlay"] = {"status": "pending"}
            else:
                node["migration_overlay"] = {"status": "missing"}

        else:
            node["migration_overlay"] = None
