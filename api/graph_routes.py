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
    &mode      = topology | blast_radius | delete_impact  (default: topology)

Response (topology mode):
  {
    "nodes": [ { "id", "db_id", "type", "label", "status", "badges",
                 "health_score", "capacity_pressure", "snapshot_coverage",
                 "extra" }, ... ],
    "edges": [ { "source", "target", "label" }, ... ],
    "root":             "<node-id>",
    "depth":            <int>,
    "node_count":       <int>,
    "edge_count":       <int>,
    "truncated":        <bool>,
    "graph_health_score": <int | null>,
    "orphan_summary":   { "volumes": int, "fips": int, "security_groups": int, "snapshots": int },
    "tenant_summary":   { ... } | null,
    "top_issues":       [ { "id", "label", "score", "reasons" }, ... ]
  }

Response additions for blast_radius mode:
  "blast_radius": { "mode": "failure", "summary": {...}, "impact_node_ids": [...] }

Response additions for delete_impact mode:
  "delete_impact": { "safe_to_delete": bool, "blockers": [...],
                     "cascade_node_ids": [...], "stranded_node_ids": [...], "summary": {...} }

Badge types:
  no_snapshot        Volume has no snapshots (legacy — replaced by snapshot_* below)
  snapshot_protected Volume has snapshot < 7 days old
  snapshot_stale     Volume snapshot is > 7 days old
  snapshot_missing   Volume has no snapshots
  drift              Resource has unacknowledged drift events
  error_state        status = ERROR / error
  power_off          VM is SHUTOFF
  restore_source     Snapshot referenced by a restore job
  orphan             Resource exists but is not in use

RBAC: requires resources:read (viewer and above)
"""

from __future__ import annotations

import logging
import re
from collections import deque
from typing import Optional, List, Dict, Any, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from psycopg2.extras import RealDictCursor

from auth import require_permission, User, get_current_user
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

def _make_node(row: Dict, ntype: str, badges: List[str], extra: Optional[Dict] = None) -> Dict:
    """Convert a DB row dict into a standardised graph node dict."""
    label = (
        row.get("name")
        or row.get("hostname")
        or row.get("floating_ip")
        or row.get("id", "")
    )
    status = row.get("status") or row.get("state")
    node: Dict[str, Any] = {
        "id":                 f"{ntype}-{row['id']}",
        "db_id":              row["id"],
        "type":               ntype,
        "label":              label,
        "status":             status,
        "badges":             badges,
        "health_score":       None,   # filled by _apply_health_scores after BFS
        "capacity_pressure":  None,   # filled for host nodes: healthy|warning|critical
        "snapshot_coverage":  None,   # filled for volume nodes: protected|stale|missing
        "extra":              extra or {},
    }
    return node


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
        "SELECT id, "
        "       COALESCE(raw_json->>'hypervisor_hostname', hostname) AS hostname, "
        "       state, status, "
        "       COALESCE((raw_json->>'vcpus')::integer, vcpus, 0)          AS vcpus, "
        "       COALESCE((raw_json->>'vcpus_used')::integer, 0)            AS vcpus_used, "
        "       COALESCE((raw_json->>'memory_mb')::bigint, memory_mb, 0)   AS memory_mb, "
        "       COALESCE((raw_json->>'memory_mb_used')::bigint, 0)         AS memory_mb_used, "
        "       COALESCE((raw_json->>'local_gb')::integer, local_gb, 0)    AS local_gb, "
        "       CASE "
        "         WHEN COALESCE((raw_json->>'local_gb')::integer, local_gb, 0) > 0 "
        "              AND (raw_json->>'disk_available_least') IS NOT NULL "
        "         THEN COALESCE((raw_json->>'local_gb')::integer, local_gb, 0) "
        "              - GREATEST(0, (raw_json->>'disk_available_least')::integer) "
        "         ELSE COALESCE((raw_json->>'local_gb_used')::integer, 0) "
        "       END AS local_gb_used_calc "
        "FROM hypervisors WHERE id = %s",
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

    # Snapshot coverage (volumes only) — 3-state: protected / stale / missing
    if ntype == "volume":
        cur.execute(
            "SELECT MAX(created_at) AS latest FROM snapshots WHERE volume_id = %s",
            (db_id,),
        )
        snap_row = cur.fetchone()
        latest = snap_row["latest"] if snap_row else None
        if latest is None:
            badges.append("snapshot_missing")
        else:
            import datetime
            age_days = (datetime.datetime.utcnow() - latest.replace(tzinfo=None)).days
            if age_days > 7:
                badges.append("snapshot_stale")
            else:
                badges.append("snapshot_protected")

        # Orphan volume: not attached to any VM
        if not row.get("server_id"):
            vs = (row.get("status") or "").lower()
            if vs == "available":
                badges.append("orphan")

    # Orphan floating IP: not bound to a port
    if ntype == "fip" and not row.get("port_id"):
        badges.append("orphan")

    # Orphan security group: not referenced by any VM port, and not named 'default'
    if ntype == "sg":
        sg_name = (row.get("name") or "").lower()
        if sg_name != "default":
            cur.execute(
                "SELECT 1 FROM ports "
                "WHERE (raw_json->'security_groups') ? %s LIMIT 1",
                (db_id,),
            )
            if not cur.fetchone():
                badges.append("orphan")

    # Orphan snapshot: parent volume is deleted/gone
    if ntype == "snapshot":
        vol_id = row.get("volume_id")
        if vol_id:
            cur.execute("SELECT 1 FROM volumes WHERE id = %s LIMIT 1", (vol_id,))
            if not cur.fetchone():
                badges.append("orphan")

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

    # Network → VMs attached via ports (include first IP on this network)
    cur.execute(
        "SELECT DISTINCT ON (s.id) "
        "s.id, s.name, s.status, s.project_id, s.hypervisor_hostname, s.image_id, "
        "(p.ip_addresses->0->>'ip_address') AS ip_address "
        "FROM servers s "
        "JOIN ports p ON p.device_id = s.id "
        "WHERE p.network_id = %s AND p.device_owner LIKE 'compute:%%' "
        "ORDER BY s.id",
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
# Health score engine (Phase 6)
# ---------------------------------------------------------------------------

def _compute_health_score(ntype: str, badges: List[str], row: Dict) -> Optional[int]:
    """
    Compute a 0–100 health score for a node based on badge penalties and
    resource-specific conditions.  Returns None for node types where scoring
    is not meaningful (networks, subnets, ports, fips, images, domains).
    """
    if ntype not in ("vm", "volume", "host"):
        return None

    score = 100

    if ntype == "vm":
        if "error_state"   in badges: score -= 30
        if "power_off"     in badges: score -= 10
        if "snapshot_missing" in badges: score -= 15
        elif "snapshot_stale" in badges: score -= 8
        if "drift"         in badges: score -= 15

    elif ntype == "volume":
        if "error_state"      in badges: score -= 30
        if "orphan"           in badges: score -= 5
        if "snapshot_missing" in badges: score -= 20
        elif "snapshot_stale" in badges: score -= 10

    elif ntype == "host":
        vcpus       = row.get("vcpus") or 0
        vcpus_used  = row.get("vcpus_used") or 0
        mem         = row.get("memory_mb") or 0
        mem_used    = row.get("memory_mb_used") or 0

        if vcpus > 0:
            cpu_pct = (vcpus_used / vcpus) * 100
            if cpu_pct > 80: score -= 20
            elif cpu_pct > 60: score -= 8

        if mem > 0:
            ram_pct = (mem_used / mem) * 100
            if ram_pct > 80: score -= 20
            elif ram_pct > 60: score -= 8

    return max(0, score)


def _capacity_pressure(row: Dict) -> str:
    """Return 'healthy' | 'warning' | 'critical' for a hypervisor row."""
    vcpus      = row.get("vcpus") or 0
    vcpus_used = row.get("vcpus_used") or 0
    mem        = row.get("memory_mb") or 0
    mem_used   = row.get("memory_mb_used") or 0

    cpu_pct = (vcpus_used / vcpus * 100) if vcpus > 0 else 0
    ram_pct = (mem_used / mem * 100)     if mem > 0 else 0

    if cpu_pct > 80 or ram_pct > 80:
        return "critical"
    if cpu_pct > 60 or ram_pct > 60:
        return "warning"
    return "healthy"


def _apply_health_scores(nodes_by_id: Dict[str, Dict]) -> None:
    """Enrich nodes in-place with health_score and capacity_pressure."""
    for node in nodes_by_id.values():
        ntype  = node["type"]
        badges = node["badges"]
        # We need the raw row values — stash them in extra during _make_node
        row_data = node.get("extra", {})

        score = _compute_health_score(ntype, badges, row_data)
        node["health_score"] = score

        if ntype == "host":
            node["capacity_pressure"] = _capacity_pressure(row_data)
        elif ntype == "volume":
            if "snapshot_missing"   in badges: node["snapshot_coverage"] = "missing"
            elif "snapshot_stale"   in badges: node["snapshot_coverage"] = "stale"
            elif "snapshot_protected" in badges: node["snapshot_coverage"] = "protected"


def _trigger_health_auto_tickets(nodes_by_id: Dict[str, Dict]) -> None:
    """
    T3.2 — Fire auto-incident tickets for resources with critically low health scores.
    Idempotent: the ticket helper skips creation if an open ticket already exists
    for the same (auto_source, auto_source_id) key.
    Threshold: health_score < 40.
    """
    try:
        from ticket_routes import _auto_ticket
        for node in nodes_by_id.values():
            score = node.get("health_score")
            if score is None or score >= 40:
                continue
            ntype = node["type"]
            badges_str = ", ".join(node.get("badges", []))
            if ntype == "host":
                _auto_ticket(
                    title=f"Hypervisor '{node['label']}' health critical (score={score})",
                    description=(
                        f"Host health score dropped to {score}/100. "
                        f"Badges: {badges_str or 'none'}."
                    ),
                    ticket_type="auto_incident",
                    priority="critical",
                    to_dept_name="Engineering",
                    auto_source="health_score",
                    auto_source_id=f"host:{node['db_id']}",
                    resource_type="host",
                    resource_id=node["db_id"],
                    resource_name=node["label"],
                )
            elif ntype == "vm":
                _auto_ticket(
                    title=f"VM '{node['label']}' health critical (score={score})",
                    description=(
                        f"VM health score dropped to {score}/100. "
                        f"Badges: {badges_str or 'none'}."
                    ),
                    ticket_type="auto_incident",
                    priority="high",
                    to_dept_name="Tier2 Support",
                    auto_source="health_score",
                    auto_source_id=f"vm:{node['db_id']}",
                    resource_type="vm",
                    resource_id=node["db_id"],
                    resource_name=node["label"],
                )
    except Exception as exc:
        logger.warning("Health auto-ticket trigger failed: %s", exc)


def _build_graph_summary(nodes_by_id: Dict[str, Dict]) -> Dict:
    """
    Compute orphan_summary, graph_health_score, tenant_summary, top_issues
    from the fully-built node set.
    """
    orphan_counts: Dict[str, int] = {
        "volumes": 0, "fips": 0, "security_groups": 0, "snapshots": 0
    }
    scores: List[int] = []
    issues: List[Dict] = []

    vm_critical = vm_degraded = 0
    vms_missing_snapshot = vms_with_drift = 0

    for node in nodes_by_id.values():
        badges = node["badges"]
        ntype  = node["type"]

        if "orphan" in badges:
            if ntype == "volume":        orphan_counts["volumes"]         += 1
            elif ntype == "fip":         orphan_counts["fips"]            += 1
            elif ntype == "sg":          orphan_counts["security_groups"] += 1
            elif ntype == "snapshot":    orphan_counts["snapshots"]       += 1

        hs = node.get("health_score")
        if hs is not None:
            scores.append(hs)
            if hs < 60:
                issues.append({
                    "id": node["id"],
                    "label": node["label"],
                    "score": hs,
                    "reasons": [b for b in badges if b not in ("snapshot_protected",)],
                })
            if ntype == "vm":
                if hs < 60: vm_critical += 1
                elif hs < 80: vm_degraded += 1
                if "snapshot_missing" in badges: vms_missing_snapshot += 1
                if "drift" in badges: vms_with_drift += 1

    graph_health_score = int(sum(scores) / len(scores)) if scores else None
    issues.sort(key=lambda x: x["score"])

    tenant_nodes = [n for n in nodes_by_id.values() if n["type"] == "tenant"]
    tenant_summary = None
    if tenant_nodes:
        tenant_summary = {
            "vms_critical":          vm_critical,
            "vms_degraded":          vm_degraded,
            "vms_missing_snapshot":  vms_missing_snapshot,
            "vms_with_drift":        vms_with_drift,
        }

    return {
        "orphan_summary":     orphan_counts,
        "graph_health_score": graph_health_score,
        "tenant_summary":     tenant_summary,
        "top_issues":         issues[:10],
    }


# ---------------------------------------------------------------------------
# Blast radius engine (Phase 7)
# ---------------------------------------------------------------------------

def _compute_blast_radius(root_ntype: str, root_db_id: str, nodes_by_id: Dict[str, Dict], edges_list: List[Dict]) -> Dict:
    """
    From the root node, find all nodes that depend on it being alive.
    Returns blast_radius dict with impact_node_ids and summary.
    """
    root_node_id = f"{root_ntype}-{root_db_id}"

    # Build adjacency: for each edge, record what the source "provides to" the target
    # Impact flows: things that *use* the root resource
    impact_edges: Dict[str, List[str]] = {}  # node_id → list of nodes it serves
    for edge in edges_list:
        src, tgt = edge["source"], edge["target"]
        impact_edges.setdefault(src, []).append(tgt)

    # BFS from root following "serves" direction
    impacted: set = set()
    queue: deque = deque([root_node_id])
    while queue:
        current = queue.popleft()
        for neighbor in impact_edges.get(current, []):
            if neighbor not in impacted and neighbor != root_node_id:
                impacted.add(neighbor)
                queue.append(neighbor)

    # Summarize
    vms = fips = tenants = volumes = 0
    for nid in impacted:
        node = nodes_by_id.get(nid)
        if not node: continue
        t = node["type"]
        if t == "vm":     vms += 1
        elif t == "fip":  fips += 1
        elif t == "tenant": tenants += 1
        elif t == "volume": volumes += 1

    return {
        "mode": "failure",
        "summary": {
            "vms_impacted":       vms,
            "tenants_impacted":   tenants,
            "floating_ips_stranded": fips,
            "volumes_at_risk":    volumes,
        },
        "impact_node_ids": list(impacted),
    }


def _compute_delete_impact(cur, root_ntype: str, root_db_id: str, nodes_by_id: Dict[str, Dict], edges_list: List[Dict]) -> Dict:
    """
    Determine what gets cascade-deleted or stranded if the root resource is deleted.
    """
    root_node_id = f"{root_ntype}-{root_db_id}"
    cascade_ids: List[str] = []
    stranded_ids: List[str] = []
    blockers: List[str] = []
    safe = True

    if root_ntype == "network":
        # Cascade: subnets that belong to this network
        for node in nodes_by_id.values():
            if node["id"] == root_node_id:
                continue
            if node["type"] == "subnet":
                cascade_ids.append(node["id"])
            elif node["type"] == "fip":
                stranded_ids.append(node["id"])
        # VMs with compute ports on this network BLOCK the delete.
        # OpenStack returns 409 if active ports with device_owner='compute:nova' exist.
        for node in nodes_by_id.values():
            if node["type"] != "vm":
                continue
            vm_id = node["db_id"]
            cur.execute(
                "SELECT COUNT(*) AS nic_count FROM ports "
                "WHERE device_id = %s AND network_id = %s AND device_owner LIKE 'compute:%%'",
                (vm_id, root_db_id),
            )
            r = cur.fetchone()
            nic_count = (r.get("nic_count", 0) if isinstance(r, dict) else (r[0] if r else 0)) or 0
            if nic_count > 0:
                blockers.append(
                    f"VM \"{node['label']}\" has {nic_count} NIC(s) on this network — "
                    f"OpenStack will reject delete while active ports exist"
                )
                stranded_ids.append(node["id"])

    elif root_ntype == "volume":
        # Cascade: all snapshots of this volume
        for node in nodes_by_id.values():
            if node["type"] == "snapshot" and node["id"] != root_node_id:
                cascade_ids.append(node["id"])

    elif root_ntype == "tenant":
        # Cascade: everything the tenant owns
        for node in nodes_by_id.values():
            if node["id"] != root_node_id:
                cascade_ids.append(node["id"])
        safe = False

    elif root_ntype == "vm":
        # OpenStack detaches (not deletes) volumes. FIPs become unassigned.
        for node in nodes_by_id.values():
            if node["type"] == "fip" and node["id"] != root_node_id:
                stranded_ids.append(node["id"])

    elif root_ntype == "sg":
        # OpenStack blocks SG delete if VMs are using it
        vm_count = sum(1 for n in nodes_by_id.values() if n["type"] == "vm")
        if vm_count > 0:
            blockers.append(f"Security group is in use by {vm_count} VM(s) — OpenStack will reject delete")
            safe = False

    # Deduplicate
    cascade_ids = list(dict.fromkeys(cascade_ids))
    stranded_ids = list(dict.fromkeys(stranded_ids))

    # Remove overlap — cascade takes priority
    cascade_set = set(cascade_ids)
    stranded_ids = [s for s in stranded_ids if s not in cascade_set]

    def count_type(id_list: List[str], t: str) -> int:
        return sum(1 for nid in id_list if nodes_by_id.get(nid, {}).get("type") == t)

    return {
        "safe_to_delete":  safe and len(blockers) == 0,
        "blockers":        blockers,
        "cascade_node_ids": cascade_ids,
        "stranded_node_ids": stranded_ids,
        "summary": {
            "cascade_count":  len(cascade_ids),
            "stranded_vms":   count_type(stranded_ids, "vm"),
            "stranded_fips":  count_type(stranded_ids, "fip"),
        },
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
            # Store raw row fields needed for health score in extra
            extra = {k: row.get(k) for k in (
                "vcpus", "vcpus_used", "memory_mb", "memory_mb_used",
                "local_gb", "local_gb_used_calc", "server_id", "ip_address",
            ) if row.get(k) is not None}
            nodes_by_id[nid] = _make_node(row, ntype, badges, extra)
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

    # Apply health scores + capacity pressure in-place after BFS is complete
    _apply_health_scores(nodes_by_id)
    _trigger_health_auto_tickets(nodes_by_id)

    summary = _build_graph_summary(nodes_by_id)

    return {
        "nodes":      list(nodes_by_id.values()),
        "edges":      edges_list,
        "root":       root_node_id,
        "depth":      max_depth,
        "node_count": len(nodes_by_id),
        "edge_count": len(edges_list),
        "truncated":  truncated,
        **summary,
    }


# ---------------------------------------------------------------------------
# UUID validation
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _is_valid_id(value: str) -> bool:
    """Accept standard UUID format, pure integer IDs (hosts), or legacy short IDs."""
    if _UUID_RE.match(value):
        return True
    # Hosts use integer PKs (e.g. hypervisors.id = 8)
    if re.match(r'^\d+$', value):
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
    mode: str = Query("topology", description="Graph mode: topology | blast_radius | delete_impact"),
    migration_project_id: Optional[int] = Query(None, description="Migration project ID — enriches nodes with migration status overlay"),
    current_user: User = Depends(require_permission("resources", "read")),
):
    """
    Return a dependency graph starting from the specified resource.

    Traverses up to `depth` hops using BFS, collecting all connected nodes and
    the relationships between them.  Stops at MAX_NODES (150) to prevent
    hairball graphs; sets `truncated: true` in the response when capped.

    mode=blast_radius   adds 'blast_radius' key showing failure impact.
    mode=delete_impact  adds 'delete_impact' key showing cascade/stranded nodes.
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

    valid_modes = ("topology", "blast_radius", "delete_impact")
    if mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Must be one of: {', '.join(valid_modes)}")

    ntype = ROOT_TYPE_ALIAS[root_type]

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                result = _build_graph(cur, ntype, root_id, depth, domain)
                if result is not None and migration_project_id is not None:
                    _apply_migration_overlay(cur, result, migration_project_id)
                if result is not None and mode in ("blast_radius", "delete_impact"):
                    # Reconstruct nodes_by_id for impact engines
                    nodes_by_id = {n["id"]: n for n in result["nodes"]}
                    if mode == "blast_radius":
                        result["blast_radius"] = _compute_blast_radius(
                            ntype, root_id, nodes_by_id, result["edges"]
                        )
                    elif mode == "delete_impact":
                        with conn.cursor(cursor_factory=RealDictCursor) as cur2:
                            result["delete_impact"] = _compute_delete_impact(
                                cur2, ntype, root_id, nodes_by_id, result["edges"]
                            )
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
# T3.3 — Delete impact gate: request a change ticket before deleting
# ---------------------------------------------------------------------------

@router.post("/request-delete", status_code=202)
async def request_delete_ticket(
    root_type: str = Body(..., description="Resource type, e.g. 'vm', 'network'"),
    root_id:   str = Body(..., description="Resource ID (UUID or integer)"),
    reason:    str = Body("", description="Optional reason for delete request"),
    current_user: User = Depends(require_permission("resources", "write")),
):
    """
    T3.3 — Gate for high-impact deletes.
    Creates an auto_change_request ticket (idempotent) and returns 202 with ticket_ref
    so the caller can track approval before actually deleting the resource.
    """
    if root_type not in ROOT_TYPE_ALIAS:
        raise HTTPException(status_code=400, detail=f"Invalid root_type '{root_type}'")
    if not _is_valid_id(root_id):
        raise HTTPException(status_code=400, detail="Invalid root_id format")

    ntype = ROOT_TYPE_ALIAS[root_type]
    resource_name = root_id

    # Best-effort: fetch the resource name
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                row = FETCHERS[ntype](cur, root_id)
                if row:
                    resource_name = row.get("name") or row.get("hostname") or root_id
    except Exception:
        pass

    actor = getattr(current_user, "username", "?")

    try:
        from ticket_routes import _auto_ticket
        result = _auto_ticket(
            title=f"Delete request: {root_type} '{resource_name}'",
            description=(
                f"User {actor} requested deletion of {root_type} '{resource_name}' (ID: {root_id}). "
                f"Reason: {reason or 'not specified'}. "
                f"Review delete-impact graph before approving."
            ),
            ticket_type="auto_change_request",
            priority="high",
            to_dept_name="Engineering",
            auto_source="delete_impact",
            auto_source_id=f"{root_type}:{root_id}",
            resource_type=root_type,
            resource_id=root_id,
            resource_name=resource_name,
            auto_blocked=True,
        )
    except Exception as exc:
        logger.error("request-delete ticket creation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not create change-request ticket")

    return {
        "status": "pending_change_request",
        "ticket_id":  result.get("ticket_id"),
        "ticket_ref": result.get("ticket_ref"),
        "created":    result.get("created", False),
        "message": (
            f"Change-request ticket {result.get('ticket_ref', '?')} "
            "created. Deletion is blocked until the ticket is resolved and approved."
            if result.get("created")
            else f"An existing open change-request ticket already covers this resource."
        ),
    }


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
