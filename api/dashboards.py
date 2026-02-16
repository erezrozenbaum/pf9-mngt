

"""
Dashboard endpoints for operational intelligence.

Provides 4 main endpoints:
1. GET /dashboard/health-summary - System overview metrics
2. GET /dashboard/snapshot-sla-compliance - Snapshot compliance by tenant
3. GET /dashboard/top-hosts-utilization - Top hosts by CPU/memory
4. GET /dashboard/recent-changes - Changes in last N hours
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException, Depends

import psycopg2
from psycopg2.extras import RealDictCursor
import glob
from auth import require_permission
from db_pool import get_connection



logger = logging.getLogger("pf9_dashboards")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/rvtools-last-run", dependencies=[Depends(require_permission("dashboard", "read"))])
async def get_rvtools_last_run():
    """Return the timestamp and details of the last inventory / RVTools data collection."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, started_at, finished_at, status, source, duration_seconds
                    FROM inventory_runs
                    WHERE status = 'success'
                    ORDER BY finished_at DESC
                    LIMIT 1
                """)
                row = cur.fetchone()

            if row:
                return {
                    "last_run": row["finished_at"].isoformat() if row["finished_at"] else row["started_at"].isoformat(),
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                    "source": row["source"],
                    "duration_seconds": row["duration_seconds"],
                    "run_id": row["id"],
                }
    except Exception as e:
        logger.warning(f"Could not query inventory_runs: {e}")

    # Fallback: check for Excel files on disk
    report_dir = os.getenv("RVTOOLS_REPORT_DIR", "/mnt/reports")
    pattern = os.path.join(report_dir, "pf9_rvtools_*.xlsx")
    files = glob.glob(pattern)
    if not files:
        return {"last_run": None}
    latest_file = max(files, key=os.path.getmtime)
    last_run = datetime.fromtimestamp(os.path.getmtime(latest_file), tz=timezone.utc).isoformat()
    return {"last_run": last_run}


def get_db_connection():
    """DEPRECATED: Use db_pool.get_connection() instead."""
    return psycopg2.connect(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("PF9_DB_USER", "pf9"),
        password=os.getenv("PF9_DB_PASSWORD", ""),
    )


def _calculate_metrics_summary(metrics_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize metrics cache and calculate summary stats."""
    if not metrics_data:
        return {
            "avg_cpu": 0,
            "avg_memory": 0,
            "metrics_host_count": 0,
            "metrics_last_update": None,
        }

    vm_host_aggregates = _aggregate_vm_metrics_by_host(metrics_data)
    hosts = metrics_data.get("hosts", []) or []
    cpu_values: List[float] = []
    mem_values: List[float] = []

    for host in hosts:
        cpu = host.get("cpu_usage_percent")
        if cpu is None:
            cpu = host.get("cpu_utilization")
        if cpu is None:
            cpu = host.get("cpu_utilization_percent")

        mem = host.get("memory_usage_percent")
        if mem is None:
            mem = host.get("memory_utilization")
        if mem is None:
            used = host.get("memory_used_mb")
            total = host.get("memory_total_mb")
            if used is not None and total:
                mem = (float(used) / float(total)) * 100

        if cpu is not None:
            cpu_values.append(float(cpu))
        if mem is not None:
            mem_values.append(float(mem))

    avg_cpu = sum(cpu_values) / len(cpu_values) if cpu_values else 0
    avg_memory = sum(mem_values) / len(mem_values) if mem_values else 0

    if (avg_cpu <= 0 or not cpu_values) and vm_host_aggregates:
        vm_cpu_values = [data.get("avg_cpu") for data in vm_host_aggregates.values() if data.get("avg_cpu") is not None]
        if vm_cpu_values:
            avg_cpu = sum(vm_cpu_values) / len(vm_cpu_values)

    if (avg_memory <= 0 or not mem_values) and vm_host_aggregates:
        vm_mem_values = [data.get("memory_usage_percent") for data in vm_host_aggregates.values() if data.get("memory_usage_percent") is not None]
        if vm_mem_values:
            avg_memory = sum(vm_mem_values) / len(vm_mem_values)

    metrics_last_update = None
    summary_last_update = metrics_data.get("summary", {}).get("last_update")
    if summary_last_update:
        metrics_last_update = summary_last_update
    elif metrics_data.get("timestamp"):
        metrics_last_update = metrics_data.get("timestamp")
    else:
        timestamps = [h.get("timestamp") for h in hosts if h.get("timestamp")]
        if timestamps:
            metrics_last_update = sorted(timestamps)[-1]

    if not metrics_last_update and vm_host_aggregates:
        vm_timestamps = [data.get("last_timestamp") for data in vm_host_aggregates.values() if data.get("last_timestamp")]
        if vm_timestamps:
            metrics_last_update = sorted(vm_timestamps)[-1]

    metrics_host_count = len(hosts) if hosts else len(vm_host_aggregates)

    if metrics_host_count == 0 and vm_host_aggregates:
        metrics_host_count = len(vm_host_aggregates)

    return {
        "avg_cpu": avg_cpu,
        "avg_memory": avg_memory,
        "metrics_host_count": metrics_host_count,
        "metrics_last_update": metrics_last_update,
    }


def _get_vm_count_by_host() -> Dict[str, int]:
    """Get VM counts grouped by hypervisor hostname."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT hypervisor_hostname, COUNT(*) AS vm_count
                FROM servers
                WHERE hypervisor_hostname IS NOT NULL
                GROUP BY hypervisor_hostname
                """
            )
            rows = cursor.fetchall()
            cursor.close()
            return {
                _normalize_host_key(row["hypervisor_hostname"]): int(row["vm_count"])
                for row in rows
                if row["hypervisor_hostname"]
            }
    except Exception:
        return {}


def _normalize_host_key(hostname: Optional[str]) -> str:
    """Normalize host keys for matching across sources."""
    if not hostname:
        return ""
    return hostname.strip().lower()


def _aggregate_vm_metrics_by_host(metrics_data: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate VM metrics to provide per-host utilization fallbacks."""
    if not metrics_data:
        return {}

    aggregates: Dict[str, Dict[str, Any]] = {}
    normalized_vms = _normalize_vm_metrics(metrics_data)

    for vm in normalized_vms:
        host_raw = vm.get("host")
        host_key = _normalize_host_key(host_raw)
        if not host_key:
            continue

        entry = aggregates.setdefault(
            host_key,
            {
                "hostname": host_raw,
                "vm_count": 0,
                "cpu_values": [],
                "memory_percent_values": [],
                "memory_used_mb": 0.0,
                "memory_total_mb": 0.0,
                "last_timestamp": None,
            },
        )

        entry["vm_count"] += 1

        cpu_percent = vm.get("cpu_usage_percent")
        if cpu_percent is not None:
            try:
                entry["cpu_values"].append(float(cpu_percent))
            except (TypeError, ValueError):
                pass

        mem_percent = vm.get("memory_usage_percent")
        if mem_percent is not None:
            try:
                entry["memory_percent_values"].append(float(mem_percent))
            except (TypeError, ValueError):
                pass

        mem_used = vm.get("memory_usage_mb")
        mem_total = vm.get("memory_total_mb")
        try:
            if mem_used is not None and mem_total:
                entry["memory_used_mb"] += float(mem_used)
                entry["memory_total_mb"] += float(mem_total)
        except (TypeError, ValueError):
            pass

        vm_timestamp = vm.get("timestamp")
        if vm_timestamp:
            if not entry["last_timestamp"] or vm_timestamp > entry["last_timestamp"]:
                entry["last_timestamp"] = vm_timestamp

    for host_key, entry in aggregates.items():
        cpu_values = entry.pop("cpu_values")
        if cpu_values:
            entry["avg_cpu"] = sum(cpu_values) / len(cpu_values)
        else:
            entry["avg_cpu"] = None

        total_mb = entry.get("memory_total_mb") or 0.0
        if total_mb > 0:
            entry["memory_usage_percent"] = (entry["memory_used_mb"] / total_mb) * 100
        else:
            mem_percent_values = entry.pop("memory_percent_values", [])
            if mem_percent_values:
                entry["memory_usage_percent"] = sum(mem_percent_values) / len(mem_percent_values)
            else:
                entry["memory_usage_percent"] = None

        if "memory_percent_values" in entry:
            entry.pop("memory_percent_values", None)

    return aggregates


def _get_hypervisor_display_map() -> Dict[str, str]:
    """Map hypervisor hostnames to display names."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT hostname, raw_json
                FROM hypervisors
                WHERE hostname IS NOT NULL
                """
            )
            rows = cursor.fetchall()
            cursor.close()

            display_map: Dict[str, str] = {}
            for row in rows:
                hostname = row.get("hostname")
                if not hostname:
                    continue

                display_name = hostname
                raw_json = row.get("raw_json") or {}
                if isinstance(raw_json, dict):
                    display_name = (
                        raw_json.get("hypervisor_hostname")
                        or raw_json.get("name")
                        or raw_json.get("hostname")
                        or hostname
                    )

                    host_ip = raw_json.get("host_ip") or raw_json.get("service_ip")
                    if host_ip:
                        display_map[_normalize_host_key(host_ip)] = display_name

                display_map[_normalize_host_key(hostname)] = display_name

            return display_map
    except Exception:
        return {}


def _compute_snapshot_compliance_by_tenant() -> Dict[str, Dict[str, Any]]:
    """Compute snapshot compliance warning counts by tenant."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            SELECT 
                p.id as tenant_id,
                p.name as tenant_name,
                v.id as volume_id,
                v.raw_json,
                COUNT(s.id) as snapshot_count,
                MAX(s.created_at) as latest_snapshot_at
            FROM projects p
            LEFT JOIN volumes v ON v.project_id = p.id
            LEFT JOIN snapshots s ON s.volume_id = v.id
            WHERE v.id IS NOT NULL
            GROUP BY p.id, p.name, v.id, v.raw_json
            ORDER BY p.name
            """
        )
        rows = cursor.fetchall()
        cursor.close()

        compliance_by_tenant: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            tenant_id = row["tenant_id"]
            tenant_name = row["tenant_name"]
            snapshot_count = row["snapshot_count"]
            latest_snapshot = row["latest_snapshot_at"]

            warning = False
            if row["raw_json"] and "metadata" in row["raw_json"]:
                metadata = row["raw_json"]["metadata"]
                auto_snapshot = metadata.get("auto_snapshot", "").lower() in ("true", "yes", "1")
                snapshot_policies = metadata.get("snapshot_policies", "")

                if auto_snapshot and snapshot_policies:
                    policies = [p.strip() for p in snapshot_policies.split(",")]
                    for policy in policies:
                        retention_key = f"retention_{policy}"
                        required_retention = int(metadata.get(retention_key, 1))
                        if snapshot_count < required_retention:
                            warning = True

            if tenant_id not in compliance_by_tenant:
                compliance_by_tenant[tenant_id] = {
                    "tenant_id": tenant_id,
                    "tenant_name": tenant_name,
                    "warning_volumes": 0,
                    "total_volumes": 0,
                    "latest_snapshot_at": latest_snapshot.isoformat() if latest_snapshot else None,
                }

            compliance_by_tenant[tenant_id]["total_volumes"] += 1
            if warning:
                compliance_by_tenant[tenant_id]["warning_volumes"] += 1

        return compliance_by_tenant


def _calculate_tenant_risk_scores() -> List[Dict[str, Any]]:
    """Calculate tenant risk scores based on snapshot coverage and staleness."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            """
            WITH volume_latest AS (
                SELECT v.id,
                       v.project_id,
                       MAX(s.created_at) as latest_snapshot
                FROM volumes v
                LEFT JOIN snapshots s ON s.volume_id = v.id
                GROUP BY v.id, v.project_id
            )
            SELECT p.id as tenant_id,
                   p.name as tenant_name,
                   COUNT(vl.id) as total_volumes,
                   COUNT(*) FILTER (WHERE vl.latest_snapshot IS NOT NULL) as volumes_with_snapshots,
                   COUNT(*) FILTER (WHERE vl.latest_snapshot IS NULL) as volumes_without_snapshots,
                   COUNT(*) FILTER (
                       WHERE vl.latest_snapshot IS NOT NULL
                         AND vl.latest_snapshot < now() - interval '7 days'
                   ) as stale_snapshot_volumes
            FROM projects p
            LEFT JOIN volume_latest vl ON vl.project_id = p.id
            GROUP BY p.id, p.name
            HAVING COUNT(vl.id) > 0
            ORDER BY p.name
            """
        )
        rows = cursor.fetchall()
        cursor.close()

        tenants = []
        for row in rows:
            total = row.get("total_volumes", 0) or 0
            no_snap = row.get("volumes_without_snapshots", 0) or 0
            stale = row.get("stale_snapshot_volumes", 0) or 0

            coverage = round(((total - no_snap) / total) * 100, 1) if total else 0
            risk_ratio = (no_snap + (stale * 0.5)) / total if total else 0
            risk_score = min(100, round(risk_ratio * 100, 1))

            if risk_score >= 50:
                risk_level = "high"
            elif risk_score >= 20:
                risk_level = "medium"
            else:
                risk_level = "low"

            tenants.append({
                "tenant_id": row.get("tenant_id"),
                "tenant_name": row.get("tenant_name"),
                "total_volumes": total,
                "coverage_percent": coverage,
                "volumes_without_snapshots": no_snap,
                "stale_snapshot_volumes": stale,
                "risk_score": risk_score,
                "risk_level": risk_level,
            })

        return tenants


def _safe_count_query(cursor: RealDictCursor, query: str, params: tuple) -> int:
    try:
        cursor.execute(query, params)
        row = cursor.fetchone() or {}
        return int(list(row.values())[0]) if row else 0
    except Exception as e:
        logger.warning(f"Safe count query failed: {e}")
        return 0


def _normalize_vm_metrics(metrics_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not metrics_data:
        return []

    vms = metrics_data.get("vms", []) or []
    normalized: List[Dict[str, Any]] = []

    for vm in vms:
        # Use explicit None checks for numeric fields that can legitimately be 0
        memory_used = vm.get("memory_usage_mb")
        if memory_used is None:
            memory_used = vm.get("memory_used_mb")
        
        memory_total = vm.get("memory_total_mb")
        if memory_total is None:
            memory_total = vm.get("memory") or vm.get("memory_mb")
        
        storage_used = vm.get("storage_used_gb")
        if storage_used is None:
            storage_used = vm.get("storage_usage_gb")
        
        storage_total = vm.get("storage_total_gb")
        if storage_total is None:
            storage_total = vm.get("storage_capacity_gb")
        
        normalized.append({
            "vm_id": vm.get("vm_id") or vm.get("id") or vm.get("uuid"),
            "vm_name": vm.get("vm_name") or vm.get("name") or "unknown",
            "vm_ip": vm.get("vm_ip") or vm.get("ip"),
            "project_name": vm.get("project_name") or vm.get("tenant") or vm.get("project"),
            "domain": vm.get("domain"),
            "host": vm.get("host") or vm.get("hypervisor"),
            "cpu_usage_percent": vm.get("cpu_usage_percent"),
            "memory_usage_percent": vm.get("memory_usage_percent"),
            "memory_usage_mb": memory_used,
            "memory_total_mb": memory_total,
            "storage_usage_percent": vm.get("storage_usage_percent"),
            "storage_used_gb": storage_used,
            "storage_total_gb": storage_total,
            "timestamp": vm.get("timestamp"),
        })

    return normalized


# =========================================================================
# ENDPOINT 1: Health Summary
# =========================================================================
@router.get("/health-summary")
async def get_health_summary():
    """
    Get system health summary.
    
    Returns:
    - Total tenants, VMs, volumes, networks
    - Average CPU/memory utilization (from metrics cache)
    - Alert/warning/critical counts
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        
            # Get resource counts
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT p.id) as total_tenants,
                    COUNT(DISTINCT s.id) as total_vms,
                    COUNT(DISTINCT v.id) as total_volumes,
                    COUNT(DISTINCT n.id) as total_networks
                FROM projects p
                LEFT JOIN servers s ON s.project_id = p.id
                LEFT JOIN volumes v ON v.project_id = p.id
                LEFT JOIN networks n ON n.project_id = p.id
            """)
        
            counts = dict(cursor.fetchone() or {})
        
            # Get running VM count
            cursor.execute("SELECT COUNT(*) as running_vms FROM servers WHERE status = 'ACTIVE'")
            running = dict(cursor.fetchone() or {})

            # Get total hosts (hypervisors)
            cursor.execute("SELECT COUNT(*) as total_hosts FROM hypervisors")
            hosts_count = dict(cursor.fetchone() or {})

            # Snapshot coverage and freshness
            cursor.execute("SELECT COUNT(*) as total_snapshots FROM snapshots")
            snapshots_count = dict(cursor.fetchone() or {})

            cursor.execute("SELECT COUNT(*) as snapshots_last_24h FROM snapshots WHERE created_at > now() - interval '24 hours'")
            snapshots_last_24h = dict(cursor.fetchone() or {})

            cursor.execute(
                """
                SELECT COUNT(*) as volumes_without_snapshots
                FROM volumes v
                LEFT JOIN snapshots s ON s.volume_id = v.id
                WHERE s.id IS NULL
                """
            )
            volumes_without_snapshots = dict(cursor.fetchone() or {})
        
            cursor.close()
        
            # Try to load metrics from cache for utilization data
            metrics_data = _load_metrics_cache()
            metrics_summary = _calculate_metrics_summary(metrics_data)
        
            return {
                "total_tenants": counts.get("total_tenants", 0),
                "total_vms": counts.get("total_vms", 0),
                "running_vms": running.get("running_vms", 0),
                "total_volumes": counts.get("total_volumes", 0),
                "total_networks": counts.get("total_networks", 0),
                "avg_cpu_utilization": round(metrics_summary["avg_cpu"], 1),
                "avg_memory_utilization": round(metrics_summary["avg_memory"], 1),
                "total_hosts": hosts_count.get("total_hosts", 0),
                "total_snapshots": snapshots_count.get("total_snapshots", 0),
                "snapshots_last_24h": snapshots_last_24h.get("snapshots_last_24h", 0),
                "volumes_without_snapshots": volumes_without_snapshots.get("volumes_without_snapshots", 0),
                "metrics_host_count": metrics_summary["metrics_host_count"],
                "metrics_last_update": metrics_summary["metrics_last_update"],
                "alerts_count": 0,  # Placeholder - can be enhanced
                "critical_count": 0,  # Placeholder - can be enhanced
                "warnings_count": 0,  # Placeholder - can be enhanced
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    except Exception as e:
        logger.error(f"Error in get_health_summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 2: Snapshot SLA Compliance
# =========================================================================
@router.get("/snapshot-sla-compliance")
async def get_snapshot_sla_compliance():
    """
    Get snapshot SLA compliance status by tenant.
    
    For each volume with snapshot_policies metadata, check if requirements are met:
    - Extract snapshot_policies (e.g., "daily_5,monthly_1st,monthly_15th")
    - Extract retention_* metadata (e.g., retention_daily_5: "5")
    - Count actual snapshots
    - Determine compliance status
    
    Returns:
    - Compliance data per tenant
    - Overall compliance percentage
    - Violations/warnings
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        
            # Get all volumes with metadata
            cursor.execute("""
                SELECT 
                    p.id as tenant_id,
                    p.name as tenant_name,
                    v.id as volume_id,
                    v.name as volume_name,
                    v.size_gb,
                    v.status,
                    v.created_at,
                    v.raw_json,
                    COUNT(s.id) as snapshot_count,
                    MAX(s.created_at) as latest_snapshot_at
                FROM projects p
                LEFT JOIN volumes v ON v.project_id = p.id
                LEFT JOIN snapshots s ON s.volume_id = v.id
                WHERE v.id IS NOT NULL
                GROUP BY p.id, p.name, v.id, v.raw_json
                ORDER BY p.name, v.name
            """)
        
            rows = cursor.fetchall()
            cursor.close()
        
            # Process compliance data
            compliance_by_tenant = {}
        
            for row in rows:
                tenant_id = row["tenant_id"]
                volume_data = {
                    "volume_id": row["volume_id"],
                    "volume_name": row["volume_name"],
                    "size_gb": row["size_gb"],
                    "snapshot_count": row["snapshot_count"],
                    "latest_snapshot_at": row["latest_snapshot_at"].isoformat() if row["latest_snapshot_at"] else None,
                    "status": "compliant",
                    "warning": None
                }
            
                # Extract metadata if exists
                if row["raw_json"] and "metadata" in row["raw_json"]:
                    metadata = row["raw_json"]["metadata"]
                
                    # Check if volume has auto_snapshot enabled
                    auto_snapshot = metadata.get("auto_snapshot", "").lower() in ("true", "yes", "1")
                    snapshot_policies = metadata.get("snapshot_policies", "")
                
                    if auto_snapshot and snapshot_policies:
                        # Check each policy
                        policies = [p.strip() for p in snapshot_policies.split(",")]
                    
                        for policy in policies:
                            retention_key = f"retention_{policy}"
                            required_retention = int(metadata.get(retention_key, 1))
                        
                            # Check if we have enough snapshots for this policy
                            if row["snapshot_count"] < required_retention:
                                volume_data["status"] = "warning"
                                volume_data["warning"] = f"Policy {policy} requires {required_retention} snapshots, has {row['snapshot_count']}"
            
                # Group by tenant
                if tenant_id not in compliance_by_tenant:
                    compliance_by_tenant[tenant_id] = {
                        "tenant_id": tenant_id,
                        "tenant_name": row["tenant_name"],
                        "compliant_count": 0,
                        "warning_count": 0,
                        "critical_count": 0,
                        "total_volumes": 0,
                        "volumes": [],
                        "warnings": []
                    }
            
                compliance_by_tenant[tenant_id]["total_volumes"] += 1
            
                if volume_data["status"] == "compliant":
                    compliance_by_tenant[tenant_id]["compliant_count"] += 1
                else:
                    compliance_by_tenant[tenant_id]["warning_count"] += 1
                    compliance_by_tenant[tenant_id]["warnings"].append(volume_data)
            
                compliance_by_tenant[tenant_id]["volumes"].append(volume_data)
        
            # Calculate compliance percentages
            for tenant_data in compliance_by_tenant.values():
                total = tenant_data["total_volumes"]
                if total > 0:
                    compliance_pct = ((total - tenant_data["warning_count"] - tenant_data["critical_count"]) / total) * 100
                    tenant_data["compliance_percentage"] = round(compliance_pct, 1)
                else:
                    tenant_data["compliance_percentage"] = 100
        
            # Calculate overall summary
            total_volumes = sum(t["total_volumes"] for t in compliance_by_tenant.values())
            compliant_volumes = sum(t["compliant_count"] for t in compliance_by_tenant.values())
            warning_volumes = sum(t["warning_count"] for t in compliance_by_tenant.values())
            critical_volumes = sum(t["critical_count"] for t in compliance_by_tenant.values())
        
            overall_compliance = 0
            if total_volumes > 0:
                overall_compliance = round((compliant_volumes / total_volumes) * 100, 1)
        
            return {
                "compliance_data": list(compliance_by_tenant.values()),
                "summary": {
                    "total_volumes": total_volumes,
                    "total_compliant": compliant_volumes,
                    "total_warning": warning_volumes,
                    "total_critical": critical_volumes,
                    "overall_compliance_percentage": overall_compliance
                },
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
    except Exception as e:
        logger.error(f"Error in get_snapshot_sla_compliance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 3: Top Hosts Utilization
# =========================================================================
@router.get("/top-hosts-utilization")
async def get_top_hosts_utilization(limit: int = Query(5, ge=1, le=20), sort: str = Query("cpu")):
    """
    Get top hosts by CPU or memory utilization.
    
    Data is read from metrics cache (populated by monitoring service).
    
    Parameters:
    - limit: Number of hosts to return (1-20, default 5)
    - sort: Sort metric - "cpu" or "memory"
    """
    try:
        metrics_data = _load_metrics_cache()
        vm_host_aggregates = _aggregate_vm_metrics_by_host(metrics_data)
        vm_counts = _get_vm_count_by_host()
        display_map = _get_hypervisor_display_map()

        metrics_summary = _calculate_metrics_summary(metrics_data)
        metrics_host_count = metrics_summary["metrics_host_count"]
        metrics_last_update = metrics_summary["metrics_last_update"]

        if metrics_data and metrics_host_count > 0:
            hosts = metrics_data.get("hosts", [])

            normalized_hosts = []
            seen_host_keys = set()
            for host in hosts:
                hostname = host.get("hostname") or host.get("host") or "unknown"
                host_key = _normalize_host_key(hostname)
                display_name = display_map.get(host_key, hostname)
                seen_host_keys.add(host_key)
                cpu = host.get("cpu_usage_percent")
                if cpu is None:
                    cpu = host.get("cpu_utilization")
                if cpu is None:
                    cpu = host.get("cpu_utilization_percent")

                mem = host.get("memory_usage_percent")
                if mem is None:
                    mem = host.get("memory_utilization")
                if mem is None:
                    used = host.get("memory_used_mb")
                    total = host.get("memory_total_mb")
                    if used is not None and total:
                        mem = (float(used) / float(total)) * 100

                vm_aggregate = vm_host_aggregates.get(host_key)
                if vm_aggregate:
                    if (cpu is None or cpu == 0) and vm_aggregate.get("avg_cpu") is not None:
                        cpu = vm_aggregate["avg_cpu"]
                    if (mem is None or mem == 0) and vm_aggregate.get("memory_usage_percent") is not None:
                        mem = vm_aggregate["memory_usage_percent"]

                vm_count_value: Optional[int] = None
                if vm_aggregate and vm_aggregate.get("vm_count") is not None:
                    vm_count_value = int(vm_aggregate.get("vm_count", 0) or 0)
                else:
                    fallback_vm_count = host.get("vm_count")
                    if fallback_vm_count is None:
                        fallback_vm_count = vm_counts.get(host_key)
                        if fallback_vm_count is None and display_name:
                            display_key = _normalize_host_key(display_name)
                            fallback_vm_count = vm_counts.get(display_key, 0)
                    vm_count_value = int(fallback_vm_count or 0)

                normalized_hosts.append({
                    "hostname": hostname,
                    "host_display_name": display_name,
                    "cpu_utilization_percent": round(float(cpu), 1) if cpu is not None else None,
                    "memory_utilization_percent": round(float(mem), 1) if mem is not None else None,
                    "vm_count": vm_count_value,
                })

            for host_key, vm_aggregate in vm_host_aggregates.items():
                if host_key in seen_host_keys:
                    continue
                hostname = vm_aggregate.get("hostname") or host_key
                display_name = display_map.get(host_key, hostname)
                
                vm_count_agg = vm_aggregate.get("vm_count", 0) or 0
                vm_count_db = vm_counts.get(host_key)
                if vm_count_db is None and display_name:
                    display_key = _normalize_host_key(display_name)
                    vm_count_db = vm_counts.get(display_key)
                final_vm_count = int(vm_count_db or vm_count_agg)
                
                normalized_hosts.append({
                    "hostname": hostname,
                    "host_display_name": display_name,
                    "cpu_utilization_percent": round(vm_aggregate["avg_cpu"], 1) if vm_aggregate.get("avg_cpu") is not None else None,
                    "memory_utilization_percent": round(vm_aggregate["memory_usage_percent"], 1) if vm_aggregate.get("memory_usage_percent") is not None else None,
                    "vm_count": final_vm_count,
                })

            sort_key = "memory_utilization_percent" if sort == "memory" else "cpu_utilization_percent"
            sorted_hosts = sorted(
                normalized_hosts,
                key=lambda h: h.get(sort_key) if h.get(sort_key) is not None else -1,
                reverse=True,
            )

            top_hosts = sorted_hosts[:limit]

            for host in top_hosts:
                cpu_val = host.get("cpu_utilization_percent") or 0
                mem_val = host.get("memory_utilization_percent") or 0
                host["is_critical"] = cpu_val > 85 or mem_val > 85

            return {
                "hosts": top_hosts,
                "sort_by": sort,
                "metrics_status": {
                    "source": "metrics_cache",
                    "host_count": metrics_host_count,
                    "last_updated": metrics_last_update,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Fallback: show inventory hosts without utilization
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                SELECT hostname, vcpus, memory_mb
                FROM hypervisors
                WHERE hostname IS NOT NULL
                ORDER BY hostname
                """
            )
            rows = cursor.fetchall()
            cursor.close()

            fallback_hosts = []
            for row in rows[:limit]:
                hostname = row.get("hostname")
                host_key = _normalize_host_key(hostname)
                display_name = display_map.get(host_key, hostname)
                fallback_hosts.append({
                    "hostname": hostname,
                    "host_display_name": display_name,
                    "cpu_utilization_percent": None,
                    "memory_utilization_percent": None,
                    "vm_count": int(vm_counts.get(host_key, 0)),
                    "capacity_vcpus": row.get("vcpus"),
                    "capacity_memory_mb": row.get("memory_mb"),
                    "is_critical": False,
                })

            return {
                "hosts": fallback_hosts,
                "sort_by": sort,
                "metrics_status": {
                    "source": "inventory",
                    "host_count": len(rows),
                    "last_updated": metrics_last_update,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        
    except Exception as e:
        logger.error(f"Error in get_top_hosts_utilization: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 4: Recent Changes
# =========================================================================
@router.get("/recent-changes")
async def get_recent_changes(hours: int = Query(24, ge=1, le=720)):
    """
    Get recent infrastructure changes (last N hours).
    
    Aggregates data from:
    - servers_history: New/deleted VMs
    - volumes_history: New/deleted volumes
    - users table: New users (via change detection)
    - deletions_history: Deleted resources
    
    Parameters:
    - hours: Look back window in hours (1-720, default 24)
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
            # New VMs
            cursor.execute("""
                SELECT 
                    'vm' as resource_type,
                    'created' as action,
                    s.server_id as resource_id,
                    s.name as resource_name,
                    p.name as tenant_name,
                    s.recorded_at as occurred_at
                FROM servers_history s
                LEFT JOIN projects p ON s.project_id = p.id
                WHERE s.recorded_at > %s
                  AND s.recorded_at = (
                    SELECT MIN(recorded_at) 
                    FROM servers_history 
                    WHERE server_id = s.server_id
                  )
                ORDER BY s.recorded_at DESC
                LIMIT 20
            """, (since,))
        
            new_vms = cursor.fetchall()
        
            # Deleted volumes
            cursor.execute("""
                SELECT 
                    'volume' as resource_type,
                    'deleted' as action,
                    resource_id,
                    resource_name,
                    NULL as tenant_name,
                    deleted_at as occurred_at
                FROM deletions_history
                WHERE resource_type = 'volume'
                  AND deleted_at > %s
                ORDER BY deleted_at DESC
                LIMIT 20
            """, (since,))
        
            deleted_volumes = cursor.fetchall()
        
            # New users (simplified - track by checking user_sessions)
            cursor.execute("""
                SELECT DISTINCT 
                    'user' as resource_type,
                    'created' as action,
                    username as resource_id,
                    username as resource_name,
                    NULL as tenant_name,
                    created_at as occurred_at
                FROM user_sessions
                WHERE created_at > %s
                ORDER BY created_at DESC
                LIMIT 10
            """, (since,))
        
            new_users = cursor.fetchall()
        
            cursor.close()
        
            # Combine and sort by time
            all_changes = []
        
            for vm in new_vms:
                all_changes.append({
                    "resource_type": vm["resource_type"],
                    "resource_id": vm["resource_id"],
                    "resource_name": vm["resource_name"],
                    "action": vm["action"],
                    "tenant_name": vm["tenant_name"],
                    "timestamp": vm["occurred_at"].isoformat() if vm["occurred_at"] else None
                })
        
            for vol in deleted_volumes:
                all_changes.append({
                    "resource_type": vol["resource_type"],
                    "resource_id": vol["resource_id"],
                    "resource_name": vol["resource_name"],
                    "action": vol["action"],
                    "tenant_name": vol["tenant_name"],
                    "timestamp": vol["occurred_at"].isoformat() if vol["occurred_at"] else None
                })
        
            for user in new_users:
                all_changes.append({
                    "resource_type": user["resource_type"],
                    "resource_id": user["resource_id"],
                    "resource_name": user["resource_name"],
                    "action": user["action"],
                    "tenant_name": user["tenant_name"],
                    "timestamp": user["occurred_at"].isoformat() if user["occurred_at"] else None
                })
        
            # Sort by timestamp descending
            all_changes.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        
            # Group by type for summary
            summary = {
                "new_vms": len([c for c in all_changes if c["resource_type"] == "vm" and c["action"] == "created"]),
                "deleted_volumes": len([c for c in all_changes if c["resource_type"] == "volume" and c["action"] == "deleted"]),
                "new_users": len([c for c in all_changes if c["resource_type"] == "user" and c["action"] == "created"]),
                "total_changes": len(all_changes)
            }
        
            return {
                "summary": summary,
                "changes": all_changes,
                "hours_lookback": hours,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
    except Exception as e:
        logger.error(f"Error in get_recent_changes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 5: Snapshot Coverage and Risk Summary
# =========================================================================
@router.get("/coverage-risks")
async def get_coverage_risks():
    """Return snapshot coverage risk metrics and lowest coverage tenants."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute("SELECT COUNT(*) as total_volumes FROM volumes")
            total_volumes = (cursor.fetchone() or {}).get("total_volumes", 0)

            cursor.execute("SELECT COUNT(*) as total_snapshots FROM snapshots")
            total_snapshots = (cursor.fetchone() or {}).get("total_snapshots", 0)

            cursor.execute("SELECT COUNT(*) as snapshots_last_24h FROM snapshots WHERE created_at > now() - interval '24 hours'")
            snapshots_last_24h = (cursor.fetchone() or {}).get("snapshots_last_24h", 0)

            cursor.execute(
                """
                SELECT COUNT(*) as volumes_without_snapshots
                FROM volumes v
                LEFT JOIN snapshots s ON s.volume_id = v.id
                WHERE s.id IS NULL
                """
            )
            volumes_without_snapshots = (cursor.fetchone() or {}).get("volumes_without_snapshots", 0)

            cursor.execute(
                """
                SELECT COUNT(*) as volumes_with_stale_snapshots
                FROM (
                    SELECT v.id, MAX(s.created_at) as latest_snapshot
                    FROM volumes v
                    LEFT JOIN snapshots s ON s.volume_id = v.id
                    GROUP BY v.id
                ) t
                WHERE t.latest_snapshot IS NOT NULL
                  AND t.latest_snapshot < now() - interval '7 days'
                """
            )
            volumes_with_stale_snapshots = (cursor.fetchone() or {}).get("volumes_with_stale_snapshots", 0)

            cursor.execute(
                """
                SELECT p.name as tenant_name,
                       COUNT(DISTINCT v.id) as total_volumes,
                       COUNT(DISTINCT s.volume_id) as covered_volumes,
                       COUNT(DISTINCT s.id) as snapshot_count
                FROM projects p
                LEFT JOIN volumes v ON v.project_id = p.id
                LEFT JOIN snapshots s ON s.volume_id = v.id
                GROUP BY p.name
                HAVING COUNT(DISTINCT v.id) > 0
                ORDER BY (COUNT(DISTINCT s.volume_id)::float / COUNT(DISTINCT v.id)) ASC
                LIMIT 5
                """
            )
            tenant_rows = cursor.fetchall()

            cursor.close()

            coverage_pct = 0
            snapshot_density = 0
            if total_volumes:
                covered = total_volumes - volumes_without_snapshots
                coverage_pct = round((covered / total_volumes) * 100, 1)
                snapshot_density = round((total_snapshots / total_volumes), 2)

            lowest_coverage = []
            for row in tenant_rows:
                total = row.get("total_volumes", 0)
                covered = row.get("covered_volumes", 0)
                snapshots = row.get("snapshot_count", 0)
                pct = round((covered / total) * 100, 1) if total else 0
                density = round((snapshots / total), 2) if total else 0
                lowest_coverage.append({
                    "tenant_name": row.get("tenant_name"),
                    "total_volumes": total,
                    "covered_volumes": covered,
                    "snapshot_count": snapshots,
                    "snapshot_density": density,
                    "coverage_percent": pct,
                })

            return {
                "summary": {
                    "total_volumes": total_volumes,
                    "total_snapshots": total_snapshots,
                    "snapshots_last_24h": snapshots_last_24h,
                    "volumes_without_snapshots": volumes_without_snapshots,
                    "volumes_with_stale_snapshots": volumes_with_stale_snapshots,
                    "coverage_percent": coverage_pct,
                    "snapshot_density": snapshot_density,
                },
                "lowest_coverage_tenants": lowest_coverage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Error in get_coverage_risks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 6: Capacity Pressure Summary
# =========================================================================
@router.get("/capacity-pressure")
async def get_capacity_pressure():
    """Return top tenants by resource pressure and active VM counts."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            cursor.execute(
                """
                SELECT p.id as tenant_id,
                       p.name as tenant_name,
                       COUNT(DISTINCT s.id) as vm_count,
                       COUNT(DISTINCT v.id) as volume_count,
                       COALESCE(SUM(v.size_gb), 0) as volume_gb
                FROM projects p
                LEFT JOIN servers s ON s.project_id = p.id
                LEFT JOIN volumes v ON v.project_id = p.id
                GROUP BY p.id, p.name
                ORDER BY vm_count DESC
                LIMIT 5
                """
            )
            top_by_vms = cursor.fetchall()

            cursor.execute(
                """
                SELECT p.id as tenant_id,
                       p.name as tenant_name,
                       COUNT(DISTINCT v.id) as volume_count,
                       COALESCE(SUM(v.size_gb), 0) as volume_gb
                FROM projects p
                LEFT JOIN volumes v ON v.project_id = p.id
                GROUP BY p.id, p.name
                ORDER BY volume_gb DESC
                LIMIT 5
                """
            )
            top_by_storage = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) as active_vms FROM servers WHERE status = 'ACTIVE'")
            active_vms = (cursor.fetchone() or {}).get("active_vms", 0)

            cursor.execute("SELECT COUNT(*) as total_vms FROM servers")
            total_vms = (cursor.fetchone() or {}).get("total_vms", 0)

            cursor.close()

            return {
                "summary": {
                    "active_vms": active_vms,
                    "total_vms": total_vms,
                },
                "top_by_vms": top_by_vms,
                "top_by_storage": top_by_storage,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Error in get_capacity_pressure: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 7: VM Hotspots from Monitoring
# =========================================================================
@router.get("/vm-hotspots")
async def get_vm_hotspots(limit: int = Query(5, ge=1, le=20), sort: str = Query("cpu")):
    """Return top VMs by CPU, memory, or storage usage."""
    try:
        metrics_data = _load_metrics_cache()
        vms = _normalize_vm_metrics(metrics_data)

        if not vms:
            return {
                "vms": [],
                "sort_by": sort,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        sort_key = {
            "cpu": "cpu_usage_percent",
            "memory": "memory_usage_percent",
            "storage": "storage_usage_percent",
        }.get(sort, "cpu_usage_percent")

        sorted_vms = sorted(
            vms,
            key=lambda v: v.get(sort_key) if v.get(sort_key) is not None else -1,
            reverse=True,
        )

        top_vms = sorted_vms[:limit]
        return {
            "vms": top_vms,
            "sort_by": sort,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error in get_vm_hotspots: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 8: Change and Compliance Summary
# =========================================================================
@router.get("/change-compliance")
async def get_change_compliance(hours: int = Query(24, ge=1, le=720)):
    """Return change and compliance summary for the last N hours."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            since = datetime.now(timezone.utc) - timedelta(hours=hours)

            cursor.execute("SELECT COUNT(*) as new_vms FROM servers WHERE created_at > %s", (since,))
            new_vms = (cursor.fetchone() or {}).get("new_vms", 0)

            cursor.execute("SELECT COUNT(*) as snapshots_created FROM snapshots WHERE created_at > %s", (since,))
            snapshots_created = (cursor.fetchone() or {}).get("snapshots_created", 0)

            deleted_resources = _safe_count_query(
                cursor,
                "SELECT COUNT(*) as deletions FROM deletions_history WHERE deleted_at > %s",
                (since,),
            )

            new_users = _safe_count_query(
                cursor,
                "SELECT COUNT(*) as new_users FROM user_sessions WHERE created_at > %s",
                (since,),
            )

            cursor.close()

            return {
                "summary": {
                    "new_vms": new_vms,
                    "snapshots_created": snapshots_created,
                    "deleted_resources": deleted_resources,
                    "new_users": new_users,
                },
                "hours_lookback": hours,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Error in get_change_compliance: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 9: Tenant Risk Scores
# =========================================================================
@router.get("/tenant-risk-scores")
async def get_tenant_risk_scores():
    """Return tenant snapshot risk scores based on coverage and staleness."""
    try:
        return {
            "tenants": _calculate_tenant_risk_scores(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error in get_tenant_risk_scores: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 11: Tenant Risk Heatmap
# =========================================================================
@router.get("/tenant-risk-heatmap")
async def get_tenant_risk_heatmap():
    """Return tenant risk scores formatted for heatmap display."""
    try:
        tenants = _calculate_tenant_risk_scores()
        return {
            "tenants": tenants,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.error(f"Error in get_tenant_risk_heatmap: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 10: Trendlines
# =========================================================================
@router.get("/trendlines")
async def get_trendlines(days: int = Query(14, ge=7, le=90)):
    """Return daily trendlines for key activity signals."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            base_query = """
                WITH days AS (
                    SELECT generate_series(current_date - (%s::int - 1), current_date, interval '1 day')::date AS day
                )
                SELECT d.day,
                       COALESCE(vms.new_vms, 0) AS new_vms,
                       COALESCE(snaps.snapshots_created, 0) AS snapshots_created,
                       COALESCE(dels.deleted_resources, 0) AS deleted_resources
                FROM days d
                LEFT JOIN (
                    SELECT created_at::date AS day, COUNT(*) AS new_vms
                    FROM servers
                    WHERE created_at >= current_date - (%s::int - 1)
                    GROUP BY created_at::date
                ) vms ON vms.day = d.day
                LEFT JOIN (
                    SELECT created_at::date AS day, COUNT(*) AS snapshots_created
                    FROM snapshots
                    WHERE created_at >= current_date - (%s::int - 1)
                    GROUP BY created_at::date
                ) snaps ON snaps.day = d.day
                LEFT JOIN (
                    SELECT deleted_at::date AS day, COUNT(*) AS deleted_resources
                    FROM deletions_history
                    WHERE deleted_at >= current_date - (%s::int - 1)
                    GROUP BY deleted_at::date
                ) dels ON dels.day = d.day
                ORDER BY d.day
            """

            try:
                cursor.execute(base_query, (days, days, days, days))
                rows = cursor.fetchall()
            except Exception:
                fallback_query = """
                    WITH days AS (
                        SELECT generate_series(current_date - (%s::int - 1), current_date, interval '1 day')::date AS day
                    )
                    SELECT d.day,
                           COALESCE(vms.new_vms, 0) AS new_vms,
                           COALESCE(snaps.snapshots_created, 0) AS snapshots_created,
                           0 AS deleted_resources
                    FROM days d
                    LEFT JOIN (
                        SELECT created_at::date AS day, COUNT(*) AS new_vms
                        FROM servers
                        WHERE created_at >= current_date - (%s::int - 1)
                        GROUP BY created_at::date
                    ) vms ON vms.day = d.day
                    LEFT JOIN (
                        SELECT created_at::date AS day, COUNT(*) AS snapshots_created
                        FROM snapshots
                        WHERE created_at >= current_date - (%s::int - 1)
                        GROUP BY created_at::date
                    ) snaps ON snaps.day = d.day
                    ORDER BY d.day
                """
                cursor.execute(fallback_query, (days, days, days))
                rows = cursor.fetchall()

            cursor.close()

            trendlines = []
            for row in rows:
                trendlines.append({
                    "day": row["day"].isoformat(),
                    "new_vms": int(row["new_vms"]),
                    "snapshots_created": int(row["snapshots_created"]),
                    "deleted_resources": int(row["deleted_resources"]),
                })

            return {
                "days": days,
                "trendlines": trendlines,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Error in get_trendlines: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 12: Capacity Trends
# =========================================================================
@router.get("/capacity-trends")
async def get_capacity_trends(days: int = Query(30, ge=7, le=180)):
    """Return capacity trends for VMs and volumes."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            query = """
                WITH days AS (
                    SELECT generate_series(current_date - (%s::int - 1), current_date, interval '1 day')::date AS day
                )
                SELECT d.day,
                       COALESCE(vms.new_vms, 0) AS new_vms,
                       COALESCE(vols.new_volumes, 0) AS new_volumes,
                       COALESCE(vols.new_volume_gb, 0) AS new_volume_gb
                FROM days d
                LEFT JOIN (
                    SELECT created_at::date AS day, COUNT(*) AS new_vms
                    FROM servers
                    WHERE created_at >= current_date - (%s::int - 1)
                    GROUP BY created_at::date
                ) vms ON vms.day = d.day
                LEFT JOIN (
                    SELECT created_at::date AS day,
                           COUNT(*) AS new_volumes,
                           COALESCE(SUM(size_gb), 0) AS new_volume_gb
                    FROM volumes
                    WHERE created_at >= current_date - (%s::int - 1)
                    GROUP BY created_at::date
                ) vols ON vols.day = d.day
                ORDER BY d.day
            """
            cursor.execute(query, (days, days, days))
            rows = cursor.fetchall()
            cursor.close()

            trendlines = []
            for row in rows:
                trendlines.append({
                    "day": row["day"].isoformat(),
                    "new_vms": int(row["new_vms"]),
                    "new_volumes": int(row["new_volumes"]),
                    "new_volume_gb": float(row["new_volume_gb"]),
                })

            return {
                "days": days,
                "trendlines": trendlines,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Error in get_capacity_trends: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# ENDPOINT 13: Compliance Drift Signals
# =========================================================================
@router.get("/compliance-drift")
async def get_compliance_drift():
    """Return compliance drift signals and top risk tenants."""
    try:
        tenant_compliance = _compute_snapshot_compliance_by_tenant()

        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(
                """
                WITH volume_latest AS (
                    SELECT v.id,
                           v.project_id,
                           MAX(s.created_at) as latest_snapshot
                    FROM volumes v
                    LEFT JOIN snapshots s ON s.volume_id = v.id
                    GROUP BY v.id, v.project_id
                )
                SELECT p.id as tenant_id,
                       p.name as tenant_name,
                       COUNT(vl.id) as total_volumes,
                       COUNT(*) FILTER (WHERE vl.latest_snapshot IS NULL) as volumes_without_snapshots,
                       COUNT(*) FILTER (
                           WHERE vl.latest_snapshot IS NOT NULL
                             AND vl.latest_snapshot < now() - interval '7 days'
                       ) as stale_snapshot_volumes
                FROM projects p
                LEFT JOIN volume_latest vl ON vl.project_id = p.id
                GROUP BY p.id, p.name
                HAVING COUNT(vl.id) > 0
                ORDER BY p.name
                """
            )
            rows = cursor.fetchall()
            cursor.close()

            drift_tenants = []
            for row in rows:
                tenant_id = row.get("tenant_id")
                compliance = tenant_compliance.get(tenant_id, {})
                drift_tenants.append({
                    "tenant_id": tenant_id,
                    "tenant_name": row.get("tenant_name"),
                    "total_volumes": row.get("total_volumes", 0),
                    "volumes_without_snapshots": row.get("volumes_without_snapshots", 0),
                    "stale_snapshot_volumes": row.get("stale_snapshot_volumes", 0),
                    "warning_volumes": compliance.get("warning_volumes", 0),
                })

            summary = {
                "total_warning_volumes": sum(t["warning_volumes"] for t in drift_tenants),
                "total_stale_volumes": sum(t["stale_snapshot_volumes"] for t in drift_tenants),
                "total_volumes_without_snapshots": sum(t["volumes_without_snapshots"] for t in drift_tenants),
            }

            return {
                "summary": summary,
                "tenants": drift_tenants,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        logger.error(f"Error in get_compliance_drift: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# BONUS: Tenant Summary (for quick reference)
# =========================================================================
@router.get("/tenant-summary")
async def get_tenant_summary():
    """
    Get quick summary for all tenants.
    
    Used by landing dashboard for tenant list.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        
            cursor.execute("""
                SELECT 
                    p.id as tenant_id,
                    p.name as tenant_name,
                    COUNT(DISTINCT s.id) as vm_count,
                    COUNT(DISTINCT v.id) as volume_count,
                    COUNT(DISTINCT n.id) as network_count,
                    (SELECT COUNT(DISTINCT user_id) FROM role_assignments 
                     WHERE resource_id = p.id) as user_count
                FROM projects p
                LEFT JOIN servers s ON s.project_id = p.id
                LEFT JOIN volumes v ON v.project_id = p.id
                LEFT JOIN networks n ON n.project_id = p.id
                GROUP BY p.id, p.name
                ORDER BY p.name
            """)
        
            tenants = cursor.fetchall()
            cursor.close()
        
            # Enrich with compliance status (simplified)
            for tenant in tenants:
                # This could be cached/optimized, but for now a simple check
                tenant["snapshot_sla_status"] = "compliant"  # Placeholder
                tenant["recent_errors"] = 0  # Placeholder
        
            return {
                "tenants": tenants,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
    except Exception as e:
        logger.error(f"Error in get_tenant_summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# HELPER FUNCTIONS
# =========================================================================

def _load_metrics_cache() -> Optional[Dict[str, Any]]:
    """Load metrics from cache file (populated by monitoring service)."""
    try:
        cache_paths = [
            "/app/monitoring/cache/metrics_cache.json",
            "/tmp/metrics_cache.json",
            "metrics_cache.json",
            "/app/metrics_cache.json",
        ]
        
        def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
            if not value:
                return None
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return None

        candidates: List[Dict[str, Any]] = []
        for cache_path in cache_paths:
            if not os.path.exists(cache_path):
                continue
            try:
                with open(cache_path, "r") as f:
                    payload = json.load(f)
                payload["_cache_path"] = cache_path
                candidates.append(payload)
            except Exception as e:
                logger.warning(f"Could not read metrics cache {cache_path}: {e}")

        if not candidates:
            return None

        def score_candidate(candidate: Dict[str, Any]) -> tuple:
            vms = candidate.get("vms", []) or []
            hosts = candidate.get("hosts", []) or []
            ts_value = candidate.get("timestamp") or candidate.get("summary", {}).get("last_update")
            ts = parse_timestamp(ts_value)

            score = 0
            if vms:
                score += 4
            if hosts:
                score += 2
            if ts:
                score += 1
            return (score, ts or datetime.min)

        best = max(candidates, key=score_candidate)
        return best
    except Exception as e:
        logger.warning(f"Could not load metrics cache: {e}")
        return None
