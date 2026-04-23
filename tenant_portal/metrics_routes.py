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
    "/tmp/cache/metrics_cache.json",   # nosec B108 — read-only; written by monitoring service
    "/tmp/metrics_cache.json",         # nosec B108 — read-only fallback path
    "metrics_cache.json",
    "/app/metrics_cache.json",
]

# Internal monitoring service URL (same cluster, no auth required — not exposed externally)
_MONITORING_SERVICE_URL = os.getenv("MONITORING_SERVICE_URL", "http://pf9-monitoring:8001")
# Internal admin API URL (same cluster)
_INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://pf9-api:8000")


def _load_metrics_cache() -> Optional[Dict[str, Any]]:
    # 1. Try local file paths (works in Docker Compose with shared volume)
    for path in _METRICS_CACHE_PATHS:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                # Only use the file if it actually contains VM data; an empty cache
                # file would otherwise block the DB fallback below.
                if data.get("vms"):
                    return data
            except Exception as exc:
                logger.warning("Could not read metrics cache %s: %s", path, exc)

    # 2. Try the monitoring service HTTP API (works in K8s where there is no shared volume)
    _monitoring_empty: Optional[Dict[str, Any]] = None
    try:
        import httpx  # already in requirements via restore_routes
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{_MONITORING_SERVICE_URL}/metrics/vms")
            resp.raise_for_status()
            data = resp.json()
            vms = data.get("data", data.get("vms", []))
            monitoring_response = {
                "vms": vms,
                "timestamp": data.get("timestamp"),
                "source": "monitoring",
            }
            if vms:
                # Monitoring service has real data — use it.
                return monitoring_response
            # Monitoring is reachable but its cache is empty (not yet bootstrapped
            # or no hypervisors configured).  Save as last-resort fallback so that
            # cache_available stays True, but keep trying the DB path.
            _monitoring_empty = monitoring_response
    except Exception as exc:
        logger.warning("Could not fetch metrics from monitoring service %s: %s", _MONITORING_SERVICE_URL, exc)

    # 3. Fallback: call the main API's DB-backed metrics endpoint.
    #    This returns allocation-based resource data derived from servers + flavors + hypervisors
    #    when no Prometheus exporters are configured on the hypervisor nodes.
    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{_INTERNAL_API_URL}/monitoring/vm-metrics")
            resp.raise_for_status()
            data = resp.json()
            api_vms = data.get("data", [])
            if api_vms:
                # Normalise admin API shape → monitoring cache shape
                cache_vms = []
                for v in api_vms:
                    cache_vms.append({
                        "vm_id": v.get("vm_id"),
                        "vm_name": v.get("vm_name"),
                        "cpu_usage_percent": v.get("cpu_usage_percent"),
                        "memory_usage_percent": v.get("memory_usage_percent"),
                        "storage_total_gb": v.get("storage_total_gb"),
                        "storage_used_gb": v.get("storage_used_gb"),
                        "storage_usage_percent": v.get("storage_usage_percent"),
                        "last_updated": data.get("timestamp"),
                    })
                logger.info(
                    "Loaded %d VM metrics from admin API DB fallback (no Prometheus data available)",
                    len(cache_vms),
                )
                return {
                    "vms": cache_vms,
                    "timestamp": data.get("timestamp"),
                    "source": "database",
                }
    except Exception as exc:
        logger.warning("Could not fetch metrics from admin API %s: %s", _INTERNAL_API_URL, exc)

    # If monitoring was reachable but empty, return that response so the UI shows
    # "No metrics collected yet" rather than "Monitoring unreachable".
    return _monitoring_empty


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
                    COUNT(*) FILTER (WHERE status = 'OK') AS daily_success
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
        # Derive VM status from last_seen_at: up if seen within 2 h, down if seen
        # more than 2 h ago, unknown if never recorded.
        last_seen = vm.get("last_seen_at")
        if last_seen is not None:
            try:
                last_seen_dt = last_seen if hasattr(last_seen, "tzinfo") else datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
                if last_seen_dt.tzinfo is None:
                    last_seen_dt = last_seen_dt.replace(tzinfo=timezone.utc)
                hours_ago = (now - last_seen_dt).total_seconds() / 3600
                vm_status = "up" if hours_ago < 2 else "down"
            except Exception:
                vm_status = "unknown"
        else:
            vm_status = "unknown"
        result.append({
            "vm_id": v_id,
            "vm_name": vm["vm_name"],
            "region_display_name": region_map.get(vm["region_id"], vm["region_id"]),
            "last_seen": last_seen,
            "status": vm_status,
            "uptime_7d_pct": round(up_7 / 7 * 100, 1),
            "uptime_30d_pct": round(up_30 / 30 * 100, 1),
            "successful_days_7d": up_7,
            "successful_days_30d": up_30,
        })

    return {"availability": result, "total": len(result)}


# ---------------------------------------------------------------------------
# Chargeback / Cost estimation
# ---------------------------------------------------------------------------

@router.get("/tenant/metering/chargeback", summary="Tenant cost estimate (chargeback)")
async def tenant_chargeback(
    hours: int = 720,
    currency: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Return per-VM estimated cost for the authenticated tenant's projects.

    This is an ESTIMATION based on vCPU/RAM allocation and the pricing table
    configured by the platform administrator.  Actual billing may differ.

    Pricing basis (in order of precedence):
      1. Flavor-specific price from the metering_pricing table
      2. Per-vCPU + per-GB-RAM hourly rates from metering_config
      3. Zero (pricing not configured)
    """
    from psycopg2.extras import RealDictCursor as _RDC

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=_RDC) as cur:
            inject_rls_vars(cur, ctx)

            # Pricing config (admin-set)
            cur.execute("SELECT * FROM metering_config WHERE id = 1")
            cfg = cur.fetchone() or {}
            cur.execute("SELECT * FROM metering_pricing ORDER BY id")
            pricing_rows = cur.fetchall()

            since = datetime.now(tz=timezone.utc) - timedelta(hours=hours)

            # Latest metering snapshot per VM, scoped to this tenant's projects
            cur.execute(
                """
                SELECT DISTINCT ON (vm_id)
                    vm_id, vm_name, project_name,
                    vcpus_allocated AS vcpus,
                    ram_allocated_mb AS ram_mb,
                    flavor AS flavor_name,
                    collected_at
                FROM metering_resources
                WHERE project_id = ANY(%s)
                  AND collected_at > %s
                ORDER BY vm_id, collected_at DESC
                """,
                (ctx.project_ids, since),
            )
            vms = [dict(r) for r in cur.fetchall()]
            log_action(cur, ctx, "tenant_view_chargeback")
            conn.commit()

    fb_vcpu = float(cfg.get("cost_per_vcpu_hour") or 0)
    fb_ram = float(cfg.get("cost_per_gb_ram_hour") or 0)
    config_currency = cfg.get("cost_currency") or "USD"

    # Build flavor → price map
    flavor_pricing: Dict[str, float] = {}
    for p in pricing_rows:
        if p.get("category") == "flavor":
            flavor_pricing[p["item_name"]] = float(p.get("cost_per_hour") or 0)

    # Determine display currency
    if not currency:
        if pricing_rows:
            currency = pricing_rows[0].get("currency") or config_currency
        else:
            currency = config_currency

    rows = []
    total_cost = 0.0
    for vm in vms:
        fp = flavor_pricing.get(vm.get("flavor_name") or "")
        if fp and fp > 0:
            cost_per_hour = fp
            pricing_basis = f"Flavor price ({vm.get('flavor_name')})"
        elif fb_vcpu > 0 or fb_ram > 0:
            cost_per_hour = (vm.get("vcpus") or 0) * fb_vcpu + ((vm.get("ram_mb") or 0) / 1024) * fb_ram
            pricing_basis = f"{vm.get('vcpus') or 0} vCPU × {fb_vcpu}/hr + {round((vm.get('ram_mb') or 0)/1024, 1)} GB RAM × {fb_ram}/hr"
        else:
            cost_per_hour = 0.0
            pricing_basis = "Pricing not configured"

        estimated_cost = round(cost_per_hour * hours, 4)
        total_cost += estimated_cost
        rows.append({
            "vm_id": vm["vm_id"],
            "vm_name": vm["vm_name"],
            "project_name": vm.get("project_name") or "unknown",
            "vcpus": vm.get("vcpus") or 0,
            "ram_gb": round((vm.get("ram_mb") or 0) / 1024, 1),
            "flavor": vm.get("flavor_name") or "unknown",
            "cost_per_hour": round(cost_per_hour, 6),
            "estimated_cost": estimated_cost,
            "pricing_basis": pricing_basis,
            "last_metering": vm["collected_at"].isoformat() if vm.get("collected_at") else None,
        })

    rows.sort(key=lambda r: r["estimated_cost"], reverse=True)

    return {
        "currency": currency,
        "period_hours": hours,
        "period_label": _hours_to_label(hours),
        "vms": rows,
        "total_estimated_cost": round(total_cost, 2),
        "total_vms": len(rows),
        "disclaimer": (
            "This is an ESTIMATION based on resource allocation and the pricing rates "
            "configured by your platform administrator. It does not represent a final invoice. "
            "Actual charges may vary."
        ),
        "pricing_basis_note": (
            f"Rates: {fb_vcpu} {currency}/vCPU/hr, {fb_ram} {currency}/GB-RAM/hr "
            f"(flavor-specific overrides applied where configured)."
            if (fb_vcpu > 0 or fb_ram > 0 or flavor_pricing)
            else "Pricing rates have not been configured by the administrator."
        ),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _hours_to_label(hours: int) -> str:
    if hours <= 24:
        return f"Last {hours} hours"
    if hours % 720 == 0:
        return f"Last {hours // 720} month(s)"
    if hours % 168 == 0:
        return f"Last {hours // 168} week(s)"
    return f"Last {hours // 24} days"
