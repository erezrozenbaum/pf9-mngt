"""
metrics_routes.py — P3b Tenant Portal metrics proxy endpoints.

Reads from the shared metrics_cache.json (populated by the monitoring
service) and filters to the tenant's project+region scope using the
servers table as the authoritative ownership lookup.

No raw Prometheus or Grafana queries are exposed.
No metrics for VMs outside the tenant's scope are returned.

Endpoints:
  GET /tenant/metrics/vms                — all tenant VMs current metrics
  GET /tenant/metrics/vms/{vm_id}        — single VM metrics + availability
  GET /tenant/metrics/availability       — per-VM 7/30-day uptime %
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars
from tenant_context import TenantContext
from audit_helper import log_action, log_action_bare

logger = logging.getLogger("tenant_portal.metrics")

router = APIRouter(tags=["metrics"])

# ---------------------------------------------------------------------------
# Metrics cache loader  (replicates the admin API pattern)
# ---------------------------------------------------------------------------

_METRICS_CACHE_PATHS = [
    "/app/monitoring/cache/metrics_cache.json",
    "/tmp/metrics_cache.json",  # nosec B108 — read-only fallback path, never written by user input
    "metrics_cache.json",
    "/app/metrics_cache.json",
]


def _load_metrics_cache() -> Optional[Dict[str, Any]]:
    for path in _METRICS_CACHE_PATHS:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not read metrics cache %s: %s", path, exc)
    return None


def _normalize_vm_entry(vm: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a raw metrics_cache VM entry into a consistent shape."""
    mem_used = vm.get("memory_usage_mb") or vm.get("memory_used_mb")
    mem_total = vm.get("memory_total_mb") or vm.get("memory") or vm.get("memory_mb")
    storage_used = vm.get("storage_used_gb") or vm.get("storage_usage_gb")
    storage_total = vm.get("storage_total_gb") or vm.get("storage_capacity_gb")

    mem_pct = None
    if mem_used is not None and mem_total:
        try:
            mem_pct = round(float(mem_used) / float(mem_total) * 100, 1)
        except (TypeError, ZeroDivisionError):
            pass

    storage_pct = None
    if storage_used is not None and storage_total:
        try:
            storage_pct = round(float(storage_used) / float(storage_total) * 100, 1)
        except (TypeError, ZeroDivisionError):
            pass

    return {
        "vm_id": vm.get("vm_id") or vm.get("id") or vm.get("uuid"),
        "vm_name": vm.get("vm_name") or vm.get("name") or "unknown",
        "cpu_usage_percent": vm.get("cpu_usage_percent"),
        "memory_usage_percent": vm.get("memory_usage_percent") or mem_pct,
        "memory_usage_mb": mem_used,
        "memory_total_mb": mem_total,
        "storage_used_gb": storage_used,
        "storage_total_gb": storage_total,
        "storage_usage_percent": storage_pct,
        "iops_read": vm.get("iops_read"),
        "iops_write": vm.get("iops_write"),
        "network_rx_mbps": vm.get("network_rx_mbps"),
        "network_tx_mbps": vm.get("network_tx_mbps"),
        "last_updated": vm.get("last_updated") or vm.get("timestamp"),
    }


def _get_tenant_vm_ids(ctx: TenantContext) -> List[str]:
    """Fetch the set of VM IDs owned by this tenant (double-scoped + RLS)."""
    with get_tenant_connection() as conn:
        with conn.cursor() as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                "SELECT id FROM servers WHERE project_id = ANY(%s) AND region_id = ANY(%s)",
                (ctx.project_ids, ctx.region_ids),
            )
            rows = cur.fetchall()
            conn.commit()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# P3b — Metrics endpoints
# ---------------------------------------------------------------------------

@router.get("/tenant/metrics/vms", summary="All tenant VM metrics")
async def metrics_all_vms(ctx: TenantContext = Depends(get_tenant_context)):
    owned_ids = set(_get_tenant_vm_ids(ctx))

    metrics = _load_metrics_cache()
    if metrics is None:
        log_action_bare(ctx, "tenant_view_metrics")
        return {"vms": [], "total": 0, "cache_available": False}

    raw_vms = metrics.get("vms") or []
    result = []
    for vm in raw_vms:
        vm_id = vm.get("vm_id") or vm.get("id") or vm.get("uuid")
        if vm_id in owned_ids:
            result.append(_normalize_vm_entry(vm))

    log_action_bare(ctx, "tenant_view_metrics")
    return {
        "vms": result,
        "total": len(result),
        "cache_available": True,
        "cache_timestamp": metrics.get("timestamp"),
    }


@router.get("/tenant/metrics/vms/{vm_id}", summary="Single VM metrics")
async def metrics_single_vm(vm_id: str, ctx: TenantContext = Depends(get_tenant_context)):
    # Ownership check via DB (returns 403, never 404, to prevent existence oracle)
    owned_ids = set(_get_tenant_vm_ids(ctx))
    if vm_id not in owned_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")

    metrics = _load_metrics_cache()
    if metrics is None:
        log_action_bare(ctx, "tenant_view_metrics", resource_type="vm", resource_id=vm_id)
        return {"vm_id": vm_id, "cache_available": False}

    raw_vms = metrics.get("vms") or []
    for vm in raw_vms:
        candidate_id = vm.get("vm_id") or vm.get("id") or vm.get("uuid")
        if candidate_id == vm_id:
            entry = _normalize_vm_entry(vm)
            entry["cache_available"] = True
            entry["cache_timestamp"] = metrics.get("timestamp")
            log_action_bare(ctx, "tenant_view_metrics", resource_type="vm", resource_id=vm_id)
            return entry

    # VM is in DB scope but not yet in metrics cache (e.g. newly created)
    log_action_bare(ctx, "tenant_view_metrics", resource_type="vm", resource_id=vm_id)
    return {"vm_id": vm_id, "cache_available": True, "metrics_available": False}


@router.get("/tenant/metrics/availability", summary="Per-VM 7d/30d availability")
async def metrics_availability(ctx: TenantContext = Depends(get_tenant_context)):
    """
    Compute per-VM availability percentages from snapshot_records.

    - uptime_7d_pct  : % of days in last 7 days with at least one successful run
    - uptime_30d_pct : same over last 30 days
    """
    now = datetime.now(tz=timezone.utc)
    cutoff_7d = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)

            # Get all VMs in scope
            cur.execute(
                """
                SELECT s.id AS vm_id, s.name AS vm_name, s.region_id, s.last_seen_at
                FROM servers s
                WHERE s.project_id = ANY(%s) AND s.region_id = ANY(%s)
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            vms = [dict(r) for r in cur.fetchall()]

            # Per-VM daily success counts for last 30 days
            cur.execute(
                """
                SELECT
                    vm_id,
                    DATE_TRUNC('day', created_at AT TIME ZONE 'UTC') AS day,
                    COUNT(*) FILTER (WHERE status = 'success') AS daily_success
                FROM snapshot_records
                WHERE project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                  AND created_at >= %s
                GROUP BY vm_id, day
                """,
                (ctx.project_ids, ctx.region_ids, cutoff_30d),
            )
            daily_rows = cur.fetchall()

            # Region display names
            cur.execute(
                "SELECT id, display_name FROM pf9_regions WHERE id = ANY(%s)",
                (ctx.region_ids,),
            )
            region_map = {r["id"]: r["display_name"] for r in cur.fetchall()}
            log_action(cur, ctx, "tenant_view_availability")
            conn.commit()

    # Build per-VM daily success index
    vm_days: Dict[str, set] = {}  # vm_id -> set of successful day strings
    for row in daily_rows:
        if row["daily_success"] and row["daily_success"] > 0:
            vm_days.setdefault(row["vm_id"], set()).add(str(row["day"])[:10])

    # Compute coverage
    window_7d = {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}
    window_30d = {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)}

    result = []
    for vm in vms:
        v_id = vm["vm_id"]
        days_with_success = vm_days.get(v_id, set())
        up_7 = len(days_with_success & window_7d)
        up_30 = len(days_with_success & window_30d)
        result.append({
            "vm_id": v_id,
            "vm_name": vm["vm_name"],
            "region_display_name": region_map.get(vm["region_id"], vm["region_id"]),
            "last_seen": vm["last_seen_at"],
            "uptime_7d_pct": round(up_7 / 7 * 100, 1),
            "uptime_30d_pct": round(up_30 / 30 * 100, 1),
            "successful_days_7d": up_7,
            "successful_days_30d": up_30,
        })

    return {"availability": result, "total": len(result)}
