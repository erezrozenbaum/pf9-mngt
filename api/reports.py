"""
Reports API Routes
==================
Comprehensive reporting system for PF9 management platform.
Provides 16 report types with JSON preview and CSV export.

RBAC
----
  - admin / superadmin → reports:read  (view and export all reports)

Reports Catalog
---------------
  1. Tenant Quota vs Usage           2. Domain Overview
  3. Snapshot Compliance             4. Flavor Usage Matrix
  5. Metering Summary               6. Resource Inventory
  7. User & Role Audit              8. Idle / Orphaned Resources
  9. Security Group Audit           10. Capacity Planning
  11. Backup Status                 12. Activity / Change Log
  13. Network Topology              14. Cost Allocation by Domain
  15. Drift Detection Summary       16. Virtual Machine Report
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User
from db_pool import get_connection
from pf9_control import get_client

logger = logging.getLogger("pf9.reports")

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decimal_clean(rows: List[Dict]) -> List[Dict]:
    """Convert Decimal / datetime values to JSON-safe types."""
    for r in rows:
        for k in list(r.keys()):
            if hasattr(r[k], "isoformat"):
                r[k] = r[k].isoformat()
            elif hasattr(r[k], "as_tuple"):
                r[k] = float(r[k])
    return rows


def _rows_to_csv(rows: list, filename: str) -> StreamingResponse:
    """Convert list of dicts to a streaming CSV response."""
    if not rows:
        output = io.StringIO("No data\n")
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=rows[0].keys())
    writer.writeheader()
    for row in rows:
        clean: Dict[str, Any] = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            elif hasattr(v, "as_tuple"):
                clean[k] = float(v)
            elif isinstance(v, (list, dict)):
                clean[k] = str(v)
            else:
                clean[k] = v
        writer.writerow(clean)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")


def _maybe_csv(rows: list, format: str, filename_prefix: str):
    """Return JSON or CSV depending on format param."""
    if format == "csv":
        return _rows_to_csv(rows, f"{filename_prefix}_{_ts()}.csv")
    return {"data": _decimal_clean(rows), "count": len(rows)}


# ---------------------------------------------------------------------------
# Report Catalog
# ---------------------------------------------------------------------------

REPORT_CATALOG = [
    {
        "id": "tenant-quota-usage",
        "name": "Tenant Quota vs Usage",
        "description": "Per-tenant allocated quota (vCPUs, RAM, storage, instances, networks) vs actual consumption with utilization percentages.",
        "category": "capacity",
        "parameters": ["domain_id"],
    },
    {
        "id": "domain-overview",
        "name": "Domain Overview",
        "description": "All domains with their tenants, quota rollup, and resource counts. Hierarchical view with domain-level aggregation.",
        "category": "inventory",
        "parameters": [],
    },
    {
        "id": "snapshot-compliance",
        "name": "Snapshot Compliance",
        "description": "Per-tenant snapshot policy compliance: last snapshot time, compliance status, retention stats.",
        "category": "compliance",
        "parameters": ["domain_id"],
    },
    {
        "id": "flavor-usage",
        "name": "Flavor Usage Matrix",
        "description": "All flavors with instance count, which tenants use them, and total resource footprint per flavor.",
        "category": "capacity",
        "parameters": [],
    },
    {
        "id": "metering-summary",
        "name": "Metering Summary",
        "description": "Per-tenant metering data: compute-hours, storage usage, network I/O, cost breakdown by pricing tier.",
        "category": "billing",
        "parameters": ["domain_id", "hours"],
    },
    {
        "id": "resource-inventory",
        "name": "Resource Inventory",
        "description": "Full inventory of all VMs, volumes, networks, routers, floating IPs, security groups per tenant.",
        "category": "inventory",
        "parameters": ["domain_id", "project_id"],
    },
    {
        "id": "user-role-audit",
        "name": "User & Role Audit",
        "description": "All users across domains/tenants with their role assignments. For security reviews and compliance audits.",
        "category": "security",
        "parameters": ["domain_id"],
    },
    {
        "id": "idle-resources",
        "name": "Idle / Orphaned Resources",
        "description": "VMs in SHUTOFF state, unattached volumes, unused floating IPs, empty security groups. Identifies cost savings.",
        "category": "optimization",
        "parameters": ["domain_id"],
    },
    {
        "id": "security-group-audit",
        "name": "Security Group Audit",
        "description": "All security groups with rule counts, associated instances, overly permissive rules (0.0.0.0/0), unused groups.",
        "category": "security",
        "parameters": ["project_id"],
    },
    {
        "id": "capacity-planning",
        "name": "Capacity Planning",
        "description": "Aggregate hypervisor capacity vs allocated vs used. Shows overcommit ratios and remaining runway.",
        "category": "capacity",
        "parameters": [],
    },
    {
        "id": "backup-status",
        "name": "Backup Status",
        "description": "All tenants: last backup time, backup size, success/failure history, backup age.",
        "category": "compliance",
        "parameters": [],
    },
    {
        "id": "activity-log-export",
        "name": "Activity / Change Log",
        "description": "Filterable export of all provisioning actions, deletions, role changes over a date range.",
        "category": "audit",
        "parameters": ["days", "action", "resource_type"],
    },
    {
        "id": "network-topology",
        "name": "Network Topology",
        "description": "All networks, subnets, routers, floating IPs per tenant with CIDR ranges and connectivity.",
        "category": "inventory",
        "parameters": ["domain_id"],
    },
    {
        "id": "cost-allocation",
        "name": "Cost Allocation by Domain",
        "description": "Metering data grouped by domain for chargeback and department-level cost reporting.",
        "category": "billing",
        "parameters": ["hours"],
    },
    {
        "id": "drift-summary",
        "name": "Drift Detection Summary",
        "description": "Tenants where actual state differs from expected config. Surfaces configuration drift as a report.",
        "category": "compliance",
        "parameters": [],
    },
    {
        "id": "vm-report",
        "name": "Virtual Machine Report",
        "description": "All VMs with name, status, flavor details, host, IP addresses, attached volumes, created time, and power state.",
        "category": "inventory",
        "parameters": ["domain_id", "project_id"],
    },
]


@router.get("/catalog")
async def get_report_catalog(
    user: User = Depends(require_permission("reports", "read")),
):
    """Return the list of all available report types."""
    return {"reports": REPORT_CATALOG}


# ---------------------------------------------------------------------------
# 1. Tenant Quota vs Usage
# ---------------------------------------------------------------------------

@router.get("/tenant-quota-usage")
async def report_tenant_quota_usage(
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Per-tenant allocated quota vs actual usage with utilization %."""
    try:
        client = get_client()
        projects = client.list_projects(domain_id=domain_id)
        domains = {d["id"]: d["name"] for d in client.list_domains()}

        # Fetch all resources
        servers = client.list_servers(all_tenants=True)
        volumes = client.list_volumes(all_tenants=True)
        networks = client.list_networks()
        floating_ips = client.list_floating_ips()
        security_groups = client.list_security_groups()
        try:
            vol_snapshots = client.list_volume_snapshots(all_tenants=True)
        except Exception:
            vol_snapshots = []

        # Build flavor lookup (servers/detail may omit inline vcpus/ram)
        flavors = client.list_flavors()
        flavor_map: Dict[str, Dict[str, Any]] = {}
        for f in flavors:
            flavor_map[f["id"]] = f

        # Index resources by project
        servers_by_project: Dict[str, list] = {}
        for s in servers:
            pid = s.get("tenant_id") or s.get("project_id", "")
            servers_by_project.setdefault(pid, []).append(s)

        volumes_by_project: Dict[str, list] = {}
        for v in volumes:
            pid = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id", "")
            volumes_by_project.setdefault(pid, []).append(v)

        networks_by_project: Dict[str, list] = {}
        for n in networks:
            pid = n.get("tenant_id") or n.get("project_id", "")
            networks_by_project.setdefault(pid, []).append(n)

        fips_by_project: Dict[str, list] = {}
        for fip in floating_ips:
            pid = fip.get("tenant_id") or fip.get("project_id", "")
            fips_by_project.setdefault(pid, []).append(fip)

        sgs_by_project: Dict[str, list] = {}
        for sg in security_groups:
            pid = sg.get("tenant_id") or sg.get("project_id", "")
            sgs_by_project.setdefault(pid, []).append(sg)

        snaps_by_project: Dict[str, list] = {}
        for snap in vol_snapshots:
            pid = snap.get("os-extended-snapshot-attributes:project_id") or snap.get("project_id", "")
            snaps_by_project.setdefault(pid, []).append(snap)

        rows = []
        for proj in projects:
            pid = proj["id"]
            pname = proj.get("name", "")
            did = proj.get("domain_id", "")
            dname = domains.get(did, "")

            # Get quotas
            try:
                cq = client.get_compute_quotas(pid)
            except Exception:
                cq = {}
            try:
                nq = client.get_network_quotas(pid)
            except Exception:
                nq = {}
            try:
                sq = client.get_storage_quotas(pid)
            except Exception:
                sq = {}

            # Actual usage — resolve vCPUs / RAM from flavor lookup
            proj_servers = servers_by_project.get(pid, [])
            proj_volumes = volumes_by_project.get(pid, [])

            used_vcpus = 0
            used_ram_mb = 0
            for s in proj_servers:
                flav = s.get("flavor", {})
                if isinstance(flav, dict):
                    vcpus = flav.get("vcpus") or flav.get("original_name") and 0
                    ram = flav.get("ram", 0)
                    # If inline flavor data is missing, resolve from flavor_map
                    if not vcpus or not ram:
                        fid = flav.get("id", "")
                        resolved = flavor_map.get(fid, {})
                        vcpus = vcpus or resolved.get("vcpus", 0)
                        ram = ram or resolved.get("ram", 0)
                    used_vcpus += int(vcpus or 0)
                    used_ram_mb += int(ram or 0)

            used_instances = len(proj_servers)
            used_volumes = len(proj_volumes)
            used_storage_gb = sum(v.get("size", 0) or 0 for v in proj_volumes)
            used_networks = len(networks_by_project.get(pid, []))
            used_fips = len(fips_by_project.get(pid, []))
            used_sgs = len(sgs_by_project.get(pid, []))
            used_snapshots = len(snaps_by_project.get(pid, []))

            q_vcpus = cq.get("cores", cq.get("maxTotalCores", 0))
            q_ram_mb = cq.get("ram", cq.get("maxTotalRAMSize", 0))
            q_instances = cq.get("instances", cq.get("maxTotalInstances", 0))
            q_volumes = sq.get("volumes", 0)
            q_storage_gb = sq.get("gigabytes", 0)
            q_snapshots = sq.get("snapshots", 0)
            q_networks = nq.get("network", 0)
            q_floatingips = nq.get("floatingip", 0)
            q_sgs = nq.get("security_group", 0)

            def pct(used, quota):
                if not quota or quota < 0:
                    return 0
                return round(used / quota * 100, 1)

            rows.append({
                "Domain": dname,
                "Domain ID": did,
                "Tenant": pname,
                "Tenant ID": pid,
                "Quota vCPUs": q_vcpus,
                "Used vCPUs": used_vcpus,
                "vCPU Util %": pct(used_vcpus, q_vcpus),
                "Quota RAM (MB)": q_ram_mb,
                "Used RAM (MB)": used_ram_mb,
                "RAM Util %": pct(used_ram_mb, q_ram_mb),
                "Quota Instances": q_instances,
                "Used Instances": used_instances,
                "Instance Util %": pct(used_instances, q_instances),
                "Quota Volumes": q_volumes,
                "Used Volumes": used_volumes,
                "Volume Util %": pct(used_volumes, q_volumes),
                "Quota Storage (GB)": q_storage_gb,
                "Used Storage (GB)": used_storage_gb,
                "Storage Util %": pct(used_storage_gb, q_storage_gb),
                "Quota Snapshots": q_snapshots,
                "Used Snapshots": used_snapshots,
                "Snapshot Util %": pct(used_snapshots, q_snapshots),
                "Quota Networks": q_networks,
                "Used Networks": used_networks,
                "Network Util %": pct(used_networks, q_networks),
                "Quota Floating IPs": q_floatingips,
                "Used Floating IPs": used_fips,
                "Floating IP Util %": pct(used_fips, q_floatingips),
                "Quota Security Groups": q_sgs,
                "Used Security Groups": used_sgs,
                "Security Group Util %": pct(used_sgs, q_sgs),
            })

        return _maybe_csv(rows, format, "tenant_quota_usage")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report tenant-quota-usage failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 2. Domain Overview
# ---------------------------------------------------------------------------

@router.get("/domain-overview")
async def report_domain_overview(
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """All domains with their tenants, resource counts, and quota rollup."""
    try:
        client = get_client()
        domains = client.list_domains()
        projects = client.list_projects()
        users = client.list_users()
        servers = client.list_servers(all_tenants=True)
        volumes = client.list_volumes(all_tenants=True)
        networks = client.list_networks()
        floating_ips = client.list_floating_ips()

        # Index by domain
        projects_by_domain: Dict[str, list] = {}
        for p in projects:
            did = p.get("domain_id", "")
            projects_by_domain.setdefault(did, []).append(p)

        users_by_domain: Dict[str, list] = {}
        for u in users:
            did = u.get("domain_id", "")
            users_by_domain.setdefault(did, []).append(u)

        servers_by_project: Dict[str, list] = {}
        for s in servers:
            pid = s.get("tenant_id") or s.get("project_id", "")
            servers_by_project.setdefault(pid, []).append(s)

        volumes_by_project: Dict[str, list] = {}
        for v in volumes:
            pid = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id", "")
            volumes_by_project.setdefault(pid, []).append(v)

        networks_by_project: Dict[str, int] = {}
        for n in networks:
            pid = n.get("tenant_id") or n.get("project_id", "")
            networks_by_project[pid] = networks_by_project.get(pid, 0) + 1

        fips_by_project: Dict[str, int] = {}
        for f in floating_ips:
            pid = f.get("tenant_id") or f.get("project_id", "")
            fips_by_project[pid] = fips_by_project.get(pid, 0) + 1

        rows = []
        for dom in domains:
            did = dom["id"]
            dname = dom.get("name", "")
            dom_projects = projects_by_domain.get(did, [])
            dom_users = users_by_domain.get(did, [])

            # Aggregate resource usage across all projects in this domain
            total_vms = 0
            active_vms = 0
            shutoff_vms = 0
            total_volumes = 0
            total_storage_gb = 0
            total_networks = 0
            total_fips = 0
            used_vcpus = 0
            used_ram_mb = 0

            # Aggregate quotas across all projects in this domain
            quota_vcpus = 0
            quota_ram_mb = 0
            quota_instances = 0
            quota_volumes = 0
            quota_storage_gb = 0
            quota_networks = 0
            quota_fips = 0

            for p in dom_projects:
                pid = p["id"]
                proj_servers = servers_by_project.get(pid, [])
                proj_volumes = volumes_by_project.get(pid, [])

                total_vms += len(proj_servers)
                active_vms += sum(1 for s in proj_servers if s.get("status", "").upper() == "ACTIVE")
                shutoff_vms += sum(1 for s in proj_servers if s.get("status", "").upper() == "SHUTOFF")
                total_volumes += len(proj_volumes)
                total_storage_gb += sum(v.get("size", 0) or 0 for v in proj_volumes)
                total_networks += networks_by_project.get(pid, 0)
                total_fips += fips_by_project.get(pid, 0)

                # Used compute from server flavors
                for s in proj_servers:
                    flv = s.get("flavor", {})
                    if isinstance(flv, dict):
                        used_vcpus += flv.get("vcpus", 0)
                        used_ram_mb += flv.get("ram", 0)

                # Fetch quotas
                try:
                    cq = client.get_compute_quotas(pid)
                    qv = cq.get("cores", cq.get("maxTotalCores", 0))
                    qr = cq.get("ram", cq.get("maxTotalRAMSize", 0))
                    qi = cq.get("instances", cq.get("maxTotalInstances", 0))
                    if qv > 0: quota_vcpus += qv
                    if qr > 0: quota_ram_mb += qr
                    if qi > 0: quota_instances += qi
                except Exception:
                    pass
                try:
                    sq = client.get_storage_quotas(pid)
                    qvol = sq.get("volumes", 0)
                    qgb = sq.get("gigabytes", 0)
                    if qvol > 0: quota_volumes += qvol
                    if qgb > 0: quota_storage_gb += qgb
                except Exception:
                    pass
                try:
                    nq = client.get_network_quotas(pid)
                    qn = nq.get("network", 0)
                    qf = nq.get("floatingip", 0)
                    if qn > 0: quota_networks += qn
                    if qf > 0: quota_fips += qf
                except Exception:
                    pass

            def pct(used, quota):
                if not quota or quota < 0:
                    return 0
                return round(used / quota * 100, 1)

            tenant_names = ", ".join(p.get("name", "") for p in dom_projects)

            rows.append({
                "Domain": dname,
                "Domain ID": did,
                "Enabled": dom.get("enabled", True),
                "Description": dom.get("description", ""),
                "Tenant Count": len(dom_projects),
                "Tenant Names": tenant_names,
                "User Count": len(dom_users),
                "Total VMs": total_vms,
                "Active VMs": active_vms,
                "Shutoff VMs": shutoff_vms,
                "Total Volumes": total_volumes,
                "Total Storage (GB)": total_storage_gb,
                "Total Networks": total_networks,
                "Total Floating IPs": total_fips,
                "Quota vCPUs": quota_vcpus,
                "Used vCPUs": used_vcpus,
                "vCPU Util %": pct(used_vcpus, quota_vcpus),
                "Quota RAM (MB)": quota_ram_mb,
                "Used RAM (MB)": used_ram_mb,
                "RAM Util %": pct(used_ram_mb, quota_ram_mb),
                "Quota Instances": quota_instances,
                "Instance Util %": pct(total_vms, quota_instances),
                "Quota Volumes": quota_volumes,
                "Volume Util %": pct(total_volumes, quota_volumes),
                "Quota Storage (GB)": quota_storage_gb,
                "Storage Util %": pct(total_storage_gb, quota_storage_gb),
            })

        return _maybe_csv(rows, format, "domain_overview")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report domain-overview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 3. Snapshot Compliance
# ---------------------------------------------------------------------------

@router.get("/snapshot-compliance")
async def report_snapshot_compliance(
    domain_id: Optional[str] = Query(None),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Per-tenant snapshot compliance status."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get snapshot policy assignments
                cur.execute("""
                    SELECT
                        p.name AS tenant_name,
                        p.id AS tenant_id,
                        d.name AS domain_name,
                        d.id AS domain_id,
                        spa.policy_set_id,
                        sps.name AS policy_name,
                        spa.created_at AS assigned_at
                    FROM projects p
                    LEFT JOIN domains d ON d.id = p.domain_id
                    LEFT JOIN snapshot_policy_assignments spa ON spa.project_id = p.id
                    LEFT JOIN snapshot_policy_sets sps ON sps.id = spa.policy_set_id
                    WHERE 1=1
                    """ + (" AND p.domain_id = %s" if domain_id else "") + """
                    ORDER BY d.name, p.name
                """, [domain_id] if domain_id else [])
                assignments = cur.fetchall()

                # Get latest snapshot per tenant
                cur.execute("""
                    SELECT
                        project_id,
                        MAX(collected_at) AS last_snapshot_time,
                        COUNT(*) AS total_snapshots,
                        COUNT(*) FILTER (WHERE is_compliant = true) AS compliant_count,
                        COUNT(*) FILTER (WHERE is_compliant = false) AS non_compliant_count
                    FROM metering_snapshots
                    WHERE collected_at > now() - interval '30 days'
                    GROUP BY project_id
                """)
                snap_stats = {r["project_id"]: r for r in cur.fetchall()}

        rows = []
        for a in assignments:
            tid = a["tenant_id"]
            ss = snap_stats.get(tid, {})
            last_snap = ss.get("last_snapshot_time")
            total = ss.get("total_snapshots", 0)
            compliant = ss.get("compliant_count", 0)
            non_compliant = ss.get("non_compliant_count", 0)

            if not a.get("policy_set_id"):
                status = "No Policy"
            elif not last_snap:
                status = "Never Snapshotted"
            elif non_compliant > 0:
                status = "Non-Compliant"
            else:
                status = "Compliant"

            rows.append({
                "Domain": a.get("domain_name", ""),
                "Tenant": a.get("tenant_name", ""),
                "Tenant ID": tid,
                "Policy Assigned": a.get("policy_name") or "None",
                "Assigned At": a.get("assigned_at"),
                "Last Snapshot": last_snap,
                "Total Snapshots (30d)": total,
                "Compliant": compliant,
                "Non-Compliant": non_compliant,
                "Status": status,
            })

        return _maybe_csv(rows, format, "snapshot_compliance")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report snapshot-compliance failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 4. Flavor Usage Matrix
# ---------------------------------------------------------------------------

@router.get("/flavor-usage")
async def report_flavor_usage(
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """All flavors with instance count, tenant breakdown, and resource footprint."""
    try:
        client = get_client()
        servers = client.list_servers(all_tenants=True)
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}

        # Fetch all flavors to get proper name/specs (Nova server flavor embed is often incomplete)
        all_flavors = client.list_flavors()
        flavor_details: Dict[str, Dict[str, Any]] = {}
        for f in all_flavors:
            fid = f.get("id", "")
            flavor_details[fid] = {
                "name": f.get("name", fid),
                "vcpus": f.get("vcpus", 0),
                "ram": f.get("ram", 0),
                "disk": f.get("disk", 0),
            }

        # Build flavor → usage map
        flavor_map: Dict[str, Dict[str, Any]] = {}
        for s in servers:
            flv = s.get("flavor", {})
            if isinstance(flv, dict):
                fid = flv.get("id", "")
                # Prefer the full flavor catalog info over the embedded server data
                if fid and fid in flavor_details:
                    fname = flavor_details[fid]["name"]
                    vcpus = flavor_details[fid]["vcpus"]
                    ram = flavor_details[fid]["ram"]
                    disk = flavor_details[fid]["disk"]
                else:
                    fname = flv.get("original_name") or flv.get("id", "unknown")
                    vcpus = flv.get("vcpus", 0)
                    ram = flv.get("ram", 0)
                    disk = flv.get("disk", 0)
            else:
                fid = str(flv)
                if fid in flavor_details:
                    fname = flavor_details[fid]["name"]
                    vcpus = flavor_details[fid]["vcpus"]
                    ram = flavor_details[fid]["ram"]
                    disk = flavor_details[fid]["disk"]
                else:
                    fname = str(flv)
                    vcpus = ram = disk = 0

            if fname not in flavor_map:
                flavor_map[fname] = {
                    "id": fid,
                    "vcpus": vcpus,
                    "ram_mb": ram,
                    "disk_gb": disk,
                    "instance_count": 0,
                    "tenants": set(),
                    "active_count": 0,
                    "shutoff_count": 0,
                }
            fm = flavor_map[fname]
            fm["instance_count"] += 1
            pid = s.get("tenant_id") or s.get("project_id", "")
            fm["tenants"].add(projects.get(pid, pid))
            if s.get("status", "").upper() == "ACTIVE":
                fm["active_count"] += 1
            elif s.get("status", "").upper() == "SHUTOFF":
                fm["shutoff_count"] += 1

        rows = []
        for fname, fm in sorted(flavor_map.items()):
            rows.append({
                "Flavor": fname,
                "Flavor ID": fm["id"],
                "vCPUs": fm["vcpus"],
                "RAM (MB)": fm["ram_mb"],
                "Disk (GB)": fm["disk_gb"],
                "Total Instances": fm["instance_count"],
                "Active Instances": fm["active_count"],
                "Shutoff Instances": fm["shutoff_count"],
                "Tenant Count": len(fm["tenants"]),
                "Tenants": ", ".join(sorted(fm["tenants"])),
                "Total vCPU Footprint": fm["vcpus"] * fm["instance_count"],
                "Total RAM Footprint (MB)": fm["ram_mb"] * fm["instance_count"],
                "Total Disk Footprint (GB)": fm["disk_gb"] * fm["instance_count"],
            })

        return _maybe_csv(rows, format, "flavor_usage")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report flavor-usage failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 5. Metering Summary
# ---------------------------------------------------------------------------

@router.get("/metering-summary")
async def report_metering_summary(
    domain_id: Optional[str] = Query(None),
    hours: int = Query(720, ge=1, le=8760, description="Lookback hours (default 30 days)"),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Per-tenant metering: compute usage, storage, network I/O, cost breakdown."""
    try:
        with get_connection() as conn:
            domain_filter = ""
            params: list = [hours]
            if domain_id:
                domain_filter = " AND domain = (SELECT name FROM domains WHERE id = %s)"
                params.append(domain_id)

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    WITH latest AS (
                        SELECT DISTINCT ON (vm_id) *
                        FROM metering_resources
                        WHERE collected_at > now() - interval '%s hours'
                        {domain_filter}
                        ORDER BY vm_id, collected_at DESC
                    )
                    SELECT
                        COALESCE(project_name, 'unknown') AS tenant,
                        COALESCE(domain, '') AS domain,
                        COUNT(*) AS vm_count,
                        ROUND(SUM(COALESCE(vcpus_allocated, 0))::numeric, 0) AS total_vcpus,
                        ROUND(SUM(COALESCE(ram_allocated_mb, 0))::numeric / 1024, 2) AS total_ram_gb,
                        ROUND(SUM(COALESCE(disk_allocated_gb, 0))::numeric, 1) AS total_disk_gb,
                        ROUND(AVG(COALESCE(cpu_usage_percent, 0))::numeric, 1) AS avg_cpu_pct,
                        ROUND(AVG(COALESCE(ram_usage_percent, 0))::numeric, 1) AS avg_ram_pct,
                        ROUND(SUM(COALESCE(network_rx_bytes, 0))::numeric / 1073741824, 2) AS total_net_rx_gb,
                        ROUND(SUM(COALESCE(network_tx_bytes, 0))::numeric / 1073741824, 2) AS total_net_tx_gb
                    FROM latest
                    GROUP BY project_name, domain
                    ORDER BY project_name
                """, params)
                rows = cur.fetchall()

                # Get pricing config
                cur.execute("SELECT * FROM metering_config WHERE id = 1")
                cfg = cur.fetchone()

            cost_vcpu = float(cfg.get("cost_per_vcpu_hour", 0)) if cfg else 0
            cost_ram = float(cfg.get("cost_per_gb_ram_hour", 0)) if cfg else 0
            cost_storage = float(cfg.get("cost_per_gb_storage_month", 0)) if cfg else 0
            currency = cfg.get("cost_currency", "USD") if cfg else "USD"

            result = []
            for r in rows:
                r = dict(r)
                total_vcpus = float(r.get("total_vcpus", 0))
                total_ram_gb = float(r.get("total_ram_gb", 0))
                total_disk_gb = float(r.get("total_disk_gb", 0))
                compute_cost = (total_vcpus * cost_vcpu + total_ram_gb * cost_ram) * hours
                storage_cost = total_disk_gb * cost_storage
                r[f"Compute Cost ({currency})"] = round(compute_cost, 2)
                r[f"Storage Cost ({currency})"] = round(storage_cost, 2)
                r[f"Total Cost ({currency})"] = round(compute_cost + storage_cost, 2)
                r["Period (hours)"] = hours
                # Clean decimals
                for k in list(r.keys()):
                    if hasattr(r[k], "as_tuple"):
                        r[k] = float(r[k])
                result.append(r)

        if format == "csv":
            return _rows_to_csv(result, f"metering_summary_{_ts()}.csv")
        return {"data": result, "count": len(result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report metering-summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 6. Resource Inventory
# ---------------------------------------------------------------------------

@router.get("/resource-inventory")
async def report_resource_inventory(
    domain_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Full inventory: VMs, volumes, networks, routers, floating IPs, SGs per tenant."""
    try:
        client = get_client()
        projects = client.list_projects(domain_id=domain_id)
        domains = {d["id"]: d["name"] for d in client.list_domains()}

        if project_id:
            projects = [p for p in projects if p["id"] == project_id]

        servers = client.list_servers(all_tenants=True)
        volumes = client.list_volumes(all_tenants=True)
        networks = client.list_networks()
        routers = client.list_routers()
        floating_ips = client.list_floating_ips()
        sgs = client.list_security_groups()

        # Index by project
        def by_project(items, key="tenant_id", alt="project_id"):
            idx: Dict[str, list] = {}
            for item in items:
                pid = item.get(key) or item.get(alt, "")
                idx.setdefault(pid, []).append(item)
            return idx

        servers_idx = by_project(servers)
        volumes_idx = by_project(volumes, "os-vol-tenant-attr:tenant_id", "project_id")
        networks_idx = by_project(networks)
        routers_idx = by_project(routers)
        fips_idx = by_project(floating_ips)
        sgs_idx = by_project(sgs)

        rows = []
        for proj in projects:
            pid = proj["id"]
            did = proj.get("domain_id", "")
            rows.append({
                "Domain": domains.get(did, ""),
                "Tenant": proj.get("name", ""),
                "Tenant ID": pid,
                "VMs": len(servers_idx.get(pid, [])),
                "Active VMs": sum(1 for s in servers_idx.get(pid, []) if s.get("status", "").upper() == "ACTIVE"),
                "Shutoff VMs": sum(1 for s in servers_idx.get(pid, []) if s.get("status", "").upper() == "SHUTOFF"),
                "Volumes": len(volumes_idx.get(pid, [])),
                "Storage (GB)": sum(v.get("size", 0) or 0 for v in volumes_idx.get(pid, [])),
                "Networks": len(networks_idx.get(pid, [])),
                "Routers": len(routers_idx.get(pid, [])),
                "Floating IPs": len(fips_idx.get(pid, [])),
                "Security Groups": len(sgs_idx.get(pid, [])),
            })

        return _maybe_csv(rows, format, "resource_inventory")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report resource-inventory failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 7. User & Role Audit
# ---------------------------------------------------------------------------

@router.get("/user-role-audit")
async def report_user_role_audit(
    domain_id: Optional[str] = Query(None),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """All users across domains with their role assignments."""
    try:
        client = get_client()
        all_users = client.list_users(domain_id=domain_id)
        domains = {d["id"]: d["name"] for d in client.list_domains()}
        projects = client.list_projects(domain_id=domain_id)
        roles = {r["id"]: r["name"] for r in client.list_roles()}

        ROLE_LABELS = {
            "admin": "Administrator",
            "member": "Self-service User",
            "reader": "Read Only User",
        }

        rows = []
        for u in all_users:
            did = u.get("domain_id", "")
            rows.append({
                "Username": u.get("name", ""),
                "User ID": u.get("id", ""),
                "Email": u.get("email", ""),
                "Domain": domains.get(did, ""),
                "Domain ID": did,
                "Enabled": u.get("enabled", True),
                "Description": u.get("description", ""),
                "Password Expires At": u.get("password_expires_at", ""),
            })

        return _maybe_csv(rows, format, "user_role_audit")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report user-role-audit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 8. Idle / Orphaned Resources
# ---------------------------------------------------------------------------

@router.get("/idle-resources")
async def report_idle_resources(
    domain_id: Optional[str] = Query(None),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """VMs in SHUTOFF, unattached volumes, unused floating IPs."""
    try:
        client = get_client()
        projects_data = client.list_projects(domain_id=domain_id)
        project_ids = {p["id"] for p in projects_data}
        project_names = {p["id"]: p.get("name", "") for p in projects_data}
        domains = {d["id"]: d["name"] for d in client.list_domains()}
        domain_of_project = {p["id"]: domains.get(p.get("domain_id", ""), "") for p in projects_data}

        servers = client.list_servers(all_tenants=True)
        volumes = client.list_volumes(all_tenants=True)
        floating_ips = client.list_floating_ips()

        rows = []

        # Shutoff VMs
        for s in servers:
            pid = s.get("tenant_id") or s.get("project_id", "")
            if domain_id and pid not in project_ids:
                continue
            if s.get("status", "").upper() == "SHUTOFF":
                rows.append({
                    "Resource Type": "VM (SHUTOFF)",
                    "Name": s.get("name", ""),
                    "ID": s.get("id", ""),
                    "Tenant": project_names.get(pid, pid),
                    "Domain": domain_of_project.get(pid, ""),
                    "Status": s.get("status", ""),
                    "Created": s.get("created", ""),
                    "Issue": "VM in SHUTOFF state — consuming quota but not running",
                })

        # Unattached volumes
        for v in volumes:
            pid = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id", "")
            if domain_id and pid not in project_ids:
                continue
            attachments = v.get("attachments", [])
            if not attachments or len(attachments) == 0:
                rows.append({
                    "Resource Type": "Volume (Unattached)",
                    "Name": v.get("name", "") or v.get("display_name", ""),
                    "ID": v.get("id", ""),
                    "Tenant": project_names.get(pid, pid),
                    "Domain": domain_of_project.get(pid, ""),
                    "Status": v.get("status", ""),
                    "Created": v.get("created_at", ""),
                    "Issue": f"Unattached volume — {v.get('size', 0)} GB wasted storage",
                })

        # Unused floating IPs (not associated)
        for fip in floating_ips:
            pid = fip.get("tenant_id") or fip.get("project_id", "")
            if domain_id and pid not in project_ids:
                continue
            if not fip.get("fixed_ip_address"):
                rows.append({
                    "Resource Type": "Floating IP (Unused)",
                    "Name": fip.get("floating_ip_address", ""),
                    "ID": fip.get("id", ""),
                    "Tenant": project_names.get(pid, pid),
                    "Domain": domain_of_project.get(pid, ""),
                    "Status": fip.get("status", ""),
                    "Created": fip.get("created_at", ""),
                    "Issue": "Floating IP allocated but not associated to any instance",
                })

        return _maybe_csv(rows, format, "idle_resources")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report idle-resources failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 9. Security Group Audit
# ---------------------------------------------------------------------------

@router.get("/security-group-audit")
async def report_security_group_audit(
    project_id: Optional[str] = Query(None),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """All security groups with rule analysis."""
    try:
        client = get_client()
        sgs = client.list_security_groups(project_id=project_id)
        projects = {p["id"]: p.get("name", "") for p in client.list_projects()}
        servers = client.list_servers(all_tenants=True)

        # Map SG → servers using it
        sg_usage: Dict[str, list] = {}
        for s in servers:
            for sg in s.get("security_groups", []):
                sgname = sg.get("name", "")
                sg_usage.setdefault(sgname, []).append(s.get("name", s.get("id", "")))

        rows = []
        for sg in sgs:
            rules = sg.get("security_group_rules", [])
            pid = sg.get("tenant_id") or sg.get("project_id", "")
            sgname = sg.get("name", "")

            # Analyze rules
            rule_count = len(rules)
            ingress_rules = [r for r in rules if r.get("direction") == "ingress"]
            egress_rules = [r for r in rules if r.get("direction") == "egress"]
            wide_open = any(
                r.get("remote_ip_prefix") == "0.0.0.0/0" and r.get("direction") == "ingress"
                and r.get("protocol") is None
                for r in rules
            )
            permissive_ports = any(
                r.get("remote_ip_prefix") == "0.0.0.0/0" and r.get("direction") == "ingress"
                for r in rules
            )

            associated_servers = sg_usage.get(sgname, [])

            rows.append({
                "Security Group": sgname,
                "SG ID": sg.get("id", ""),
                "Tenant": projects.get(pid, pid),
                "Tenant ID": pid,
                "Description": sg.get("description", ""),
                "Total Rules": rule_count,
                "Ingress Rules": len(ingress_rules),
                "Egress Rules": len(egress_rules),
                "Wide Open (any/any)": "YES" if wide_open else "No",
                "Has 0.0.0.0/0 Ingress": "YES" if permissive_ports else "No",
                "Associated Instances": len(associated_servers),
                "Instance Names": ", ".join(associated_servers[:10]),
                "Risk Level": "HIGH" if wide_open else ("MEDIUM" if permissive_ports else "LOW"),
            })

        return _maybe_csv(rows, format, "security_group_audit")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report security-group-audit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 10. Capacity Planning
# ---------------------------------------------------------------------------

@router.get("/capacity-planning")
async def report_capacity_planning(
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Aggregate hypervisor capacity vs allocated vs used."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Hypervisor capacity from local cache
                cur.execute("""
                    SELECT
                        hostname,
                        hypervisor_type,
                        vcpus,
                        memory_mb,
                        local_gb,
                        state,
                        status,
                        raw_json
                    FROM hypervisors
                    ORDER BY hostname
                """)
                hyps = cur.fetchall()

        client = get_client()
        servers = client.list_servers(all_tenants=True)

        # Total allocated by servers
        total_alloc_vcpus = 0
        total_alloc_ram_mb = 0
        total_alloc_disk_gb = 0
        servers_per_host: Dict[str, int] = {}
        for s in servers:
            flv = s.get("flavor", {})
            if isinstance(flv, dict):
                total_alloc_vcpus += flv.get("vcpus", 0)
                total_alloc_ram_mb += flv.get("ram", 0)
                total_alloc_disk_gb += flv.get("disk", 0)
            host = s.get("OS-EXT-SRV-ATTR:hypervisor_hostname") or s.get("hypervisor_hostname", "")
            if host:
                servers_per_host[host] = servers_per_host.get(host, 0) + 1

        # Total capacity
        total_cap_vcpus = sum(h.get("vcpus", 0) or 0 for h in hyps)
        total_cap_ram_mb = sum(h.get("memory_mb", 0) or 0 for h in hyps)
        total_cap_disk_gb = sum(h.get("local_gb", 0) or 0 for h in hyps)

        def ratio(alloc, cap):
            if not cap:
                return 0
            return round(alloc / cap, 2)

        rows = []
        for h in hyps:
            hostname = h.get("hostname", "")
            rows.append({
                "Hypervisor": hostname,
                "Type": h.get("hypervisor_type", ""),
                "State": h.get("state", ""),
                "Status": h.get("status", ""),
                "Capacity vCPUs": h.get("vcpus", 0),
                "Capacity RAM (MB)": h.get("memory_mb", 0),
                "Capacity Disk (GB)": h.get("local_gb", 0),
                "Running VMs": servers_per_host.get(hostname, 0),
            })

        # Add summary row
        rows.append({
            "Hypervisor": "=== TOTAL ===",
            "Type": "",
            "State": "",
            "Status": f"{len(hyps)} hosts",
            "Capacity vCPUs": total_cap_vcpus,
            "Capacity RAM (MB)": total_cap_ram_mb,
            "Capacity Disk (GB)": total_cap_disk_gb,
            "Running VMs": len(servers),
        })
        rows.append({
            "Hypervisor": "=== ALLOCATED ===",
            "Type": "",
            "State": "",
            "Status": "",
            "Capacity vCPUs": total_alloc_vcpus,
            "Capacity RAM (MB)": total_alloc_ram_mb,
            "Capacity Disk (GB)": total_alloc_disk_gb,
            "Running VMs": "",
        })
        rows.append({
            "Hypervisor": "=== OVERCOMMIT RATIO ===",
            "Type": "",
            "State": "",
            "Status": "",
            "Capacity vCPUs": f"{ratio(total_alloc_vcpus, total_cap_vcpus)}x",
            "Capacity RAM (MB)": f"{ratio(total_alloc_ram_mb, total_cap_ram_mb)}x",
            "Capacity Disk (GB)": f"{ratio(total_alloc_disk_gb, total_cap_disk_gb)}x",
            "Running VMs": "",
        })

        return _maybe_csv(rows, format, "capacity_planning")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report capacity-planning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 11. Backup Status
# ---------------------------------------------------------------------------

@router.get("/backup-status")
async def report_backup_status(
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """All tenants: backup status, last backup, size, success/failure."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        p.name AS tenant_name,
                        p.id AS tenant_id,
                        d.name AS domain_name,
                        bj.id AS job_id,
                        bj.status,
                        bj.started_at,
                        bj.completed_at,
                        bj.backup_size_bytes,
                        bj.error_message
                    FROM projects p
                    LEFT JOIN domains d ON d.id = p.domain_id
                    LEFT JOIN LATERAL (
                        SELECT * FROM backup_jobs
                        WHERE project_id = p.id
                        ORDER BY started_at DESC
                        LIMIT 1
                    ) bj ON TRUE
                    ORDER BY d.name, p.name
                """)
                rows = cur.fetchall()

        result = []
        for r in rows:
            r = dict(r)
            size_bytes = r.get("backup_size_bytes") or 0
            r["Backup Size (MB)"] = round(size_bytes / (1024 * 1024), 2) if size_bytes else 0
            if r.get("started_at") and r.get("completed_at"):
                try:
                    duration = (r["completed_at"] - r["started_at"]).total_seconds()
                    r["Duration (sec)"] = round(duration, 1)
                except Exception:
                    r["Duration (sec)"] = ""
            else:
                r["Duration (sec)"] = ""
            result.append(r)

        return _maybe_csv(result, format, "backup_status")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report backup-status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 12. Activity / Change Log
# ---------------------------------------------------------------------------

@router.get("/activity-log-export")
async def report_activity_log(
    days: int = Query(30, ge=1, le=365, description="Lookback in days"),
    action: Optional[str] = Query(None, description="Filter by action"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Export activity log entries."""
    try:
        with get_connection() as conn:
            where = ["timestamp > now() - interval '%s days'"]
            params: list = [days]
            if action:
                where.append("action = %s")
                params.append(action)
            if resource_type:
                where.append("resource_type = %s")
                params.append(resource_type)

            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT
                        timestamp, actor, action, resource_type,
                        resource_id, resource_name, domain_id, domain_name,
                        ip_address, result, error_message
                    FROM activity_log
                    WHERE {' AND '.join(where)}
                    ORDER BY timestamp DESC
                    LIMIT 10000
                """, params)
                rows = cur.fetchall()

        return _maybe_csv(rows, format, "activity_log")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report activity-log failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 13. Network Topology
# ---------------------------------------------------------------------------

@router.get("/network-topology")
async def report_network_topology(
    domain_id: Optional[str] = Query(None),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """All networks, subnets, routers, floating IPs per tenant."""
    try:
        client = get_client()
        projects = client.list_projects(domain_id=domain_id)
        project_names = {p["id"]: p.get("name", "") for p in projects}
        domains = {d["id"]: d["name"] for d in client.list_domains()}
        domain_of_project = {p["id"]: domains.get(p.get("domain_id", ""), "") for p in projects}

        networks = client.list_networks()
        subnets = client.list_subnets()
        routers = client.list_routers()
        floating_ips = client.list_floating_ips()

        # Index subnets by network
        subnets_by_network: Dict[str, list] = {}
        for sub in subnets:
            nid = sub.get("network_id", "")
            subnets_by_network.setdefault(nid, []).append(sub)

        rows = []
        for net in networks:
            pid = net.get("tenant_id") or net.get("project_id", "")
            if domain_id and pid not in {p["id"] for p in projects}:
                continue
            nid = net.get("id", "")
            net_subnets = subnets_by_network.get(nid, [])
            cidrs = ", ".join(s.get("cidr", "") for s in net_subnets)
            gateways = ", ".join(s.get("gateway_ip", "") or "" for s in net_subnets)

            rows.append({
                "Resource Type": "Network",
                "Name": net.get("name", ""),
                "ID": nid,
                "Tenant": project_names.get(pid, pid),
                "Domain": domain_of_project.get(pid, ""),
                "Shared": net.get("shared", False),
                "External": net.get("router:external", False),
                "CIDRs": cidrs,
                "Gateways": gateways,
                "Subnet Count": len(net_subnets),
            })

        for rtr in routers:
            pid = rtr.get("tenant_id") or rtr.get("project_id", "")
            if domain_id and pid not in {p["id"] for p in projects}:
                continue
            ext_gw = rtr.get("external_gateway_info", {})
            rows.append({
                "Resource Type": "Router",
                "Name": rtr.get("name", ""),
                "ID": rtr.get("id", ""),
                "Tenant": project_names.get(pid, pid),
                "Domain": domain_of_project.get(pid, ""),
                "Shared": "",
                "External": bool(ext_gw),
                "CIDRs": "",
                "Gateways": ext_gw.get("network_id", "") if ext_gw else "",
                "Subnet Count": "",
            })

        for fip in floating_ips:
            pid = fip.get("tenant_id") or fip.get("project_id", "")
            if domain_id and pid not in {p["id"] for p in projects}:
                continue
            rows.append({
                "Resource Type": "Floating IP",
                "Name": fip.get("floating_ip_address", ""),
                "ID": fip.get("id", ""),
                "Tenant": project_names.get(pid, pid),
                "Domain": domain_of_project.get(pid, ""),
                "Shared": "",
                "External": "",
                "CIDRs": "",
                "Gateways": fip.get("fixed_ip_address", "") or "Unassociated",
                "Subnet Count": "",
            })

        return _maybe_csv(rows, format, "network_topology")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report network-topology failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 14. Cost Allocation by Domain
# ---------------------------------------------------------------------------

@router.get("/cost-allocation")
async def report_cost_allocation(
    hours: int = Query(720, ge=1, le=8760, description="Lookback hours (default 30 days)"),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Metering data grouped by domain for chargeback."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM metering_config WHERE id = 1")
                cfg = cur.fetchone()

                cur.execute(f"""
                    WITH latest AS (
                        SELECT DISTINCT ON (vm_id) *
                        FROM metering_resources
                        WHERE collected_at > now() - interval '%s hours'
                        ORDER BY vm_id, collected_at DESC
                    )
                    SELECT
                        COALESCE(domain, 'unknown') AS domain,
                        COUNT(*) AS vm_count,
                        ROUND(SUM(COALESCE(vcpus_allocated, 0))::numeric, 0) AS total_vcpus,
                        ROUND(SUM(COALESCE(ram_allocated_mb, 0))::numeric / 1024, 2) AS total_ram_gb,
                        ROUND(SUM(COALESCE(disk_allocated_gb, 0))::numeric, 1) AS total_disk_gb,
                        ROUND(AVG(COALESCE(cpu_usage_percent, 0))::numeric, 1) AS avg_cpu_pct,
                        ROUND(AVG(COALESCE(ram_usage_percent, 0))::numeric, 1) AS avg_ram_pct,
                        COUNT(DISTINCT project_name) AS tenant_count
                    FROM latest
                    GROUP BY domain
                    ORDER BY domain
                """, [hours])
                rows = cur.fetchall()

            cost_vcpu = float(cfg.get("cost_per_vcpu_hour", 0)) if cfg else 0
            cost_ram = float(cfg.get("cost_per_gb_ram_hour", 0)) if cfg else 0
            cost_storage = float(cfg.get("cost_per_gb_storage_month", 0)) if cfg else 0
            currency = cfg.get("cost_currency", "USD") if cfg else "USD"

            result = []
            for r in rows:
                r = dict(r)
                total_vcpus = float(r.get("total_vcpus", 0))
                total_ram_gb = float(r.get("total_ram_gb", 0))
                total_disk_gb = float(r.get("total_disk_gb", 0))
                compute_cost = (total_vcpus * cost_vcpu + total_ram_gb * cost_ram) * hours
                storage_cost = total_disk_gb * cost_storage
                r[f"Compute Cost ({currency})"] = round(compute_cost, 2)
                r[f"Storage Cost ({currency})"] = round(storage_cost, 2)
                r[f"Total Cost ({currency})"] = round(compute_cost + storage_cost, 2)
                r["Period (hours)"] = hours
                for k in list(r.keys()):
                    if hasattr(r[k], "as_tuple"):
                        r[k] = float(r[k])
                result.append(r)

        if format == "csv":
            return _rows_to_csv(result, f"cost_allocation_{_ts()}.csv")
        return {"data": result, "count": len(result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report cost-allocation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 15. Drift Detection Summary
# ---------------------------------------------------------------------------

@router.get("/drift-summary")
async def report_drift_summary(
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Summary of configuration drift detection results."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        dd.resource_type,
                        dd.resource_id,
                        dd.resource_name,
                        dd.project_id,
                        p.name AS project_name,
                        d.name AS domain_name,
                        dd.drift_type,
                        dd.severity,
                        dd.detected_at,
                        dd.resolved_at,
                        dd.current_value,
                        dd.expected_value
                    FROM drift_detections dd
                    LEFT JOIN projects p ON p.id = dd.project_id
                    LEFT JOIN domains d ON d.id = p.domain_id
                    WHERE dd.resolved_at IS NULL
                    ORDER BY dd.severity DESC, dd.detected_at DESC
                    LIMIT 5000
                """)
                rows = cur.fetchall()

        return _maybe_csv(rows, format, "drift_summary")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report drift-summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 16. Virtual Machine Report
# ---------------------------------------------------------------------------

@router.get("/vm-report")
async def report_vm_report(
    domain_id: Optional[str] = Query(None, description="Filter by domain ID"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    format: str = Query("json", description="json or csv"),
    user: User = Depends(require_permission("reports", "read")),
):
    """Detailed report of all VMs with flavor, host, IPs, volumes, quota context, and status."""
    try:
        client = get_client()
        projects = client.list_projects(domain_id=domain_id)
        domains = {d["id"]: d["name"] for d in client.list_domains()}
        project_map = {p["id"]: p for p in projects}

        if project_id:
            projects = [p for p in projects if p["id"] == project_id]
            project_map = {p["id"]: p for p in projects}

        valid_pids = set(project_map.keys())

        # Fetch all data
        servers = client.list_servers(all_tenants=True)
        all_flavors = client.list_flavors()
        volumes = client.list_volumes(all_tenants=True)

        # Build lookup maps
        flavor_details = {}
        for f in all_flavors:
            fid = f.get("id", "")
            flavor_details[fid] = {
                "name": f.get("name", fid),
                "vcpus": f.get("vcpus", 0),
                "ram_mb": f.get("ram", 0),
                "disk_gb": f.get("disk", 0),
            }

        # Index volumes by server attachment
        volume_by_server: Dict[str, list] = {}
        for v in volumes:
            for att in v.get("attachments", []):
                sid = att.get("server_id", "")
                if sid:
                    volume_by_server.setdefault(sid, []).append({
                        "name": v.get("name", v.get("id", "")),
                        "size_gb": v.get("size", 0),
                        "status": v.get("status", ""),
                    })

        # Pre-fetch quotas per project for allocation context
        project_quotas: Dict[str, dict] = {}
        project_usage: Dict[str, dict] = {}
        for pid in valid_pids:
            try:
                cq = client.get_compute_quotas(pid)
                sq = client.get_storage_quotas(pid)
                project_quotas[pid] = {
                    "vcpu_quota": cq.get("quota", {}).get("cores", cq.get("cores", -1)),
                    "ram_quota_mb": cq.get("quota", {}).get("ram", cq.get("ram", -1)),
                    "instances_quota": cq.get("quota", {}).get("instances", cq.get("instances", -1)),
                    "storage_quota_gb": sq.get("quota", {}).get("gigabytes", sq.get("gigabytes", -1)),
                }
            except Exception:
                project_quotas[pid] = {}

        # Aggregate usage per project from servers + volumes
        for s in servers:
            pid = s.get("tenant_id") or s.get("project_id", "")
            if pid not in valid_pids:
                continue
            if pid not in project_usage:
                project_usage[pid] = {"vcpus_used": 0, "ram_used_mb": 0, "instances": 0, "storage_used_gb": 0}
            fl_id = ""
            flav = s.get("flavor", {})
            if isinstance(flav, dict):
                fl_id = flav.get("id", "")
            fl = flavor_details.get(fl_id, {})
            project_usage[pid]["vcpus_used"] += fl.get("vcpus", 0)
            project_usage[pid]["ram_used_mb"] += fl.get("ram_mb", 0)
            project_usage[pid]["instances"] += 1

        for v in volumes:
            pid = v.get("os-vol-tenant-attr:tenant_id") or v.get("project_id", "")
            if pid not in valid_pids:
                continue
            if pid not in project_usage:
                project_usage[pid] = {"vcpus_used": 0, "ram_used_mb": 0, "instances": 0, "storage_used_gb": 0}
            project_usage[pid]["storage_used_gb"] += v.get("size", 0) or 0

        rows = []
        for s in servers:
            pid = s.get("tenant_id") or s.get("project_id", "")
            if valid_pids and pid not in valid_pids:
                continue

            proj = project_map.get(pid, {})
            did = proj.get("domain_id", "")
            sid = s.get("id", "")

            # Flavor info
            flavor = s.get("flavor", {})
            fid = flavor.get("id", "") if isinstance(flavor, dict) else ""
            fl = flavor_details.get(fid, {})
            flavor_name = fl.get("name", flavor.get("original_name", fid) if isinstance(flavor, dict) else fid)
            vcpus = fl.get("vcpus", flavor.get("vcpus", 0) if isinstance(flavor, dict) else 0)
            ram_mb = fl.get("ram_mb", flavor.get("ram", 0) if isinstance(flavor, dict) else 0)
            disk_gb = fl.get("disk_gb", flavor.get("disk", 0) if isinstance(flavor, dict) else 0)

            # Extract IP addresses
            addresses = s.get("addresses", {})
            fixed_ips = []
            floating_ips = []
            for net_name, addrs in addresses.items():
                for addr in addrs:
                    ip = addr.get("addr", "")
                    atype = addr.get("OS-EXT-IPS:type", "fixed")
                    if atype == "floating":
                        floating_ips.append(ip)
                    else:
                        fixed_ips.append(ip)

            # Attached volumes summary + total storage
            vm_volumes = volume_by_server.get(sid, [])
            vol_summary = "; ".join(
                f"{v['name']} ({v['size_gb']}GB)" for v in vm_volumes
            ) if vm_volumes else "None"
            vol_storage_gb = sum(v.get("size_gb", 0) for v in vm_volumes)

            # Power state mapping
            power_state_map = {0: "NO_STATE", 1: "RUNNING", 3: "PAUSED", 4: "SHUTDOWN", 6: "CRASHED", 7: "SUSPENDED"}
            ps = s.get("OS-EXT-STS:power_state", 0)
            power_label = power_state_map.get(ps, str(ps))

            # Project quota context
            pq = project_quotas.get(pid, {})
            pu = project_usage.get(pid, {})

            rows.append({
                "VM Name": s.get("name", ""),
                "VM ID": sid,
                "Status": s.get("status", ""),
                "Power State": power_label,
                "Flavor": flavor_name,
                "vCPUs": vcpus,
                "RAM (MB)": ram_mb,
                "Ephemeral Disk (GB)": disk_gb,
                "Volume Storage (GB)": vol_storage_gb,
                "Total Storage (GB)": disk_gb + vol_storage_gb,
                "Hypervisor": s.get("OS-EXT-SRV-ATTR:hypervisor_hostname", ""),
                "Host": s.get("OS-EXT-SRV-ATTR:host", ""),
                "Fixed IPs": ", ".join(fixed_ips) if fixed_ips else "",
                "Floating IPs": ", ".join(floating_ips) if floating_ips else "",
                "Attached Volumes": vol_summary,
                "Volume Count": len(vm_volumes),
                "Tenant": proj.get("name", pid),
                "Tenant ID": pid,
                "Domain": domains.get(did, did),
                "Domain ID": did,
                "Project vCPU Quota": pq.get("vcpu_quota", ""),
                "Project vCPU Used": pu.get("vcpus_used", ""),
                "Project RAM Quota (MB)": pq.get("ram_quota_mb", ""),
                "Project RAM Used (MB)": pu.get("ram_used_mb", ""),
                "Project Storage Quota (GB)": pq.get("storage_quota_gb", ""),
                "Project Storage Used (GB)": pu.get("storage_used_gb", ""),
                "Project Instance Quota": pq.get("instances_quota", ""),
                "Project Instance Count": pu.get("instances", ""),
                "Created": s.get("created", ""),
                "Updated": s.get("updated", ""),
                "Availability Zone": s.get("OS-EXT-AZ:availability_zone", ""),
                "Key Pair": s.get("key_name", ""),
                "Image ID": s.get("image", {}).get("id", "") if isinstance(s.get("image"), dict) else s.get("image", ""),
            })

        return _maybe_csv(rows, format, "vm_report")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report vm-report failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
