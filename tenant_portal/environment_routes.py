"""
environment_routes.py — P3a + P3c Tenant Portal read-only API endpoints.

All routes are double-scoped:
  1. Explicit SQL WHERE project_id = ANY(%s) AND region_id = ANY(%s)
  2. PostgreSQL RLS (tenant_portal_role) via inject_rls_vars()

P3a endpoints:
  GET /tenant/vms
  GET /tenant/vms/{vm_id}
  GET /tenant/volumes
  GET /tenant/snapshots
  GET /tenant/snapshots/{snapshot_id}
  GET /tenant/snapshot-history
  GET /tenant/compliance
  GET /tenant/dashboard
  GET /tenant/events
  GET /tenant/inventory-status

P3c endpoints:
  GET /tenant/runbooks
  GET /tenant/runbooks/{name}

P4b endpoints:
  GET  /tenant/security-groups
  POST /tenant/sync-and-snapshot

P4c endpoints:
  GET /tenant/reports
  GET /tenant/reports/{name}/download
  GET /tenant/quota
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars, require_manager_role
from tenant_context import TenantContext
from audit_helper import log_action

logger = logging.getLogger("tenant_portal.environment")

router = APIRouter(tags=["environment"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _region_display(cur, region_ids: List[str]) -> dict:
    """Return {region_id: display_name} for the given region IDs."""
    if not region_ids:
        return {}
    cur.execute(
        "SELECT id, display_name FROM pf9_regions WHERE id = ANY(%s)",
        (region_ids,),
    )
    return {row["id"]: row["display_name"] for row in cur.fetchall()}


def _extract_ips(raw_json) -> list:
    """Extract IP addresses from Nova server raw_json['addresses']."""
    if not raw_json or not isinstance(raw_json, dict):
        return []
    ips = []
    for net_addrs in raw_json.get("addresses", {}).values():
        if isinstance(net_addrs, list):
            for addr_obj in net_addrs:
                addr = addr_obj.get("addr")
                if addr:
                    ips.append(addr)
    return ips


def _check_vm_ownership(cur, vm_id: str, ctx: TenantContext) -> dict:
    """
    Fetch a single VM owned by the tenant; raise 403 if not found.
    Never 404 on ownership mismatches to prevent existence oracle attacks.
    """
    inject_rls_vars(cur, ctx)
    cur.execute(
        """
        SELECT s.id, s.name, s.status, s.vm_state,
               s.flavor_id, s.image_id, s.os_distro, s.os_version,
               s.created_at, s.last_seen_at,
               s.project_id, s.region_id, s.raw_json,
               COALESCE(f.vcpus, 0)  AS vcpus,
               COALESCE(f.ram_mb, 0) AS ram_mb
        FROM servers s
        LEFT JOIN flavors f ON f.id = s.flavor_id
        WHERE s.id = %s
          AND s.project_id = ANY(%s)
          AND s.region_id  = ANY(%s)
        """,
        (vm_id, ctx.project_ids, ctx.region_ids),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)


# ---------------------------------------------------------------------------
# P3a — Virtual Machines
# ---------------------------------------------------------------------------

@router.get("/tenant/vms", summary="List tenant VMs")
async def list_vms(ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            region_map = _region_display(cur, ctx.region_ids)
            cur.execute(
                """
                SELECT s.id, s.name, s.status, s.vm_state,
                       s.flavor_id, s.image_id, s.os_distro, s.os_version,
                       s.created_at, s.last_seen_at,
                       s.project_id, s.region_id,
                       s.raw_json,
                       COALESCE(f.vcpus, 0)    AS vcpus,
                       COALESCE(f.ram_mb, 0)   AS ram_mb,
                       COALESCE(
                           NULLIF(f.disk_gb, 0),
                           (SELECT v.size_gb FROM volumes v
                            WHERE v.server_id = s.id AND v.bootable = true
                            ORDER BY v.created_at LIMIT 1),
                           0
                       )                        AS disk_gb,
                       (
                           SELECT MAX(sr.created_at)
                           FROM snapshot_records sr
                           WHERE sr.vm_id = s.id AND sr.status = 'OK'
                       ) AS last_snapshot_at,
                       (
                           SELECT ROUND(
                               COUNT(*) FILTER (WHERE sr2.status = 'OK') * 100.0
                               / NULLIF(COUNT(*), 0),
                               1
                           )
                           FROM snapshot_records sr2
                           WHERE sr2.vm_id = s.id
                       ) AS compliance_pct
                FROM servers s
                LEFT JOIN flavors f ON f.id = s.flavor_id
                WHERE s.project_id = ANY(%s)
                  AND s.region_id  = ANY(%s)
                ORDER BY s.name
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_vms")
            conn.commit()

    result = []
    for r in rows:
        r = dict(r)
        r["region_display_name"] = region_map.get(r["region_id"], r["region_id"])
        r["ip_addresses"] = _extract_ips(r.get("raw_json"))
        r.pop("raw_json", None)
        result.append(r)
    return {"vms": result, "total": len(result)}


@router.get("/tenant/vms/{vm_id}", summary="Get single VM detail")
async def get_vm(vm_id: str, ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            vm = _check_vm_ownership(cur, vm_id, ctx)
            region_map = _region_display(cur, [vm["region_id"]])

            # Latest snapshot date + compliance status
            cur.execute(
                """
                SELECT
                    MAX(CASE WHEN status = 'OK' THEN created_at END) AS last_snapshot_at,
                    COUNT(*) FILTER (WHERE status = 'OK')            AS total_success,
                    COUNT(*) FILTER (WHERE status = 'ERROR')         AS total_failed,
                    COUNT(*)                                          AS total_runs
                FROM snapshot_records
                WHERE vm_id = %s
                """,
                (vm_id,),
            )
            snap_stats = dict(cur.fetchone() or {})

            # Active restore job (if any) — PLANNED = awaiting user confirmation, not active
            cur.execute(
                """
                SELECT id, status, created_at, mode
                FROM restore_jobs
                WHERE vm_id = %s
                  AND status IN ('PENDING', 'RUNNING')
                  AND project_id = ANY(%s)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (vm_id, ctx.project_ids),
            )
            active_restore = cur.fetchone()
            log_action(cur, ctx, "tenant_view_vm_detail", resource_type="vm", resource_id=vm_id)
            conn.commit()

    vm["ip_addresses"] = _extract_ips(vm.get("raw_json"))
    vm.pop("raw_json", None)
    vm["region_display_name"] = region_map.get(vm["region_id"], vm["region_id"])
    vm["snapshot_stats"] = snap_stats
    vm["active_restore"] = dict(active_restore) if active_restore else None
    return vm


# ---------------------------------------------------------------------------
# P3a — Volumes
# ---------------------------------------------------------------------------

@router.get("/tenant/volumes", summary="List tenant volumes")
async def list_volumes(ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            region_map = _region_display(cur, ctx.region_ids)
            cur.execute(
                """
                SELECT v.id, v.name, v.project_id, v.size_gb, v.status,
                       v.volume_type, v.bootable, v.created_at,
                       v.server_id, v.region_id,
                       srv.name AS attached_vm_name,
                       (
                           SELECT MAX(sr.created_at)
                           FROM snapshot_records sr
                           WHERE sr.vm_id = v.server_id AND sr.status = 'OK'
                       ) AS last_snapshot_ts
                FROM volumes v
                LEFT JOIN servers srv ON srv.id = v.server_id
                WHERE v.project_id = ANY(%s)
                  AND v.region_id  = ANY(%s)
                ORDER BY v.name
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_volumes")
            conn.commit()

    result = []
    for r in rows:
        r = dict(r)
        r["region_display_name"] = region_map.get(r["region_id"], r["region_id"])
        result.append(r)
    return {"volumes": result, "total": len(result)}


# ---------------------------------------------------------------------------
# P3a — Snapshots
# ---------------------------------------------------------------------------

@router.get("/tenant/snapshots", summary="List tenant snapshots")
async def list_snapshots(
    vm_id:     Optional[str] = Query(None),
    region:    Optional[str] = Query(None),
    snap_status: Optional[str] = Query(None, alias="status"),
    from_date: Optional[datetime] = Query(None),
    to_date:   Optional[datetime] = Query(None),
    limit:     int = Query(200, ge=1, le=1000),
    ctx: TenantContext = Depends(get_tenant_context),
):
    # Static parameterized SQL with IS NULL OR optional filters.
    # All filtering is done via %s placeholders — no string formatting.
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            region_map = _region_display(cur, ctx.region_ids)
            cur.execute(
                """
                SELECT s.id, s.name, s.description, s.project_id, s.project_name,
                       s.volume_id, s.size_gb, s.status, s.created_at, s.region_id
                FROM snapshots s
                WHERE s.project_id = ANY(%s)
                  AND s.region_id  = ANY(%s)
                  AND (%s::text IS NULL OR EXISTS (
                          SELECT 1 FROM volumes v
                          WHERE v.id = s.volume_id AND v.server_id = %s))
                  AND (%s::text IS NULL OR s.region_id = %s)
                  AND (%s::text IS NULL OR s.status = %s)
                  AND (%s::timestamptz IS NULL OR s.created_at >= %s)
                  AND (%s::timestamptz IS NULL OR s.created_at <= %s)
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                [
                    ctx.project_ids, ctx.region_ids,
                    vm_id, vm_id,
                    region, region,
                    snap_status, snap_status,
                    from_date, from_date,
                    to_date, to_date,
                    limit,
                ],
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_snapshots")
            conn.commit()

    result = []
    for r in rows:
        r = dict(r)
        r["region_display_name"] = region_map.get(r["region_id"], r["region_id"])
        result.append(r)
    return {"snapshots": result, "total": len(result)}


@router.get("/tenant/snapshots/{snapshot_id}", summary="Get single snapshot")
async def get_snapshot(snapshot_id: str, ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                """
                SELECT id, name, description, project_id, project_name,
                       volume_id, size_gb, status, created_at, updated_at, region_id
                FROM snapshots
                WHERE id = %s
                  AND project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                """,
                (snapshot_id, ctx.project_ids, ctx.region_ids),
            )
            row = cur.fetchone()
            log_action(cur, ctx, "tenant_view_snapshot_detail", resource_type="snapshot", resource_id=snapshot_id)
            conn.commit()

    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)


# ---------------------------------------------------------------------------
# P3a — Snapshot history (calendar view)
# ---------------------------------------------------------------------------

@router.get("/tenant/snapshot-history", summary="Snapshot run history")
async def snapshot_history(
    vm_id:     Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date:   Optional[datetime] = Query(None),
    limit:     int = Query(500, ge=1, le=2000),
    ctx: TenantContext = Depends(get_tenant_context),
):
    # Static parameterized SQL with IS NULL OR optional filters.
    # All filtering is done via %s placeholders — no string formatting.
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                """
                SELECT id, vm_id, vm_name, volume_id, volume_name,
                       project_id, project_name, policy_name,
                       size_gb, status, action, error_message,
                       created_at, deleted_at, retention_days, region_id
                FROM snapshot_records
                WHERE project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                  AND (%s::text IS NULL OR vm_id = %s)
                  AND (%s::timestamptz IS NULL OR created_at >= %s)
                  AND (%s::timestamptz IS NULL OR created_at <= %s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                [
                    ctx.project_ids, ctx.region_ids,
                    vm_id, vm_id,
                    from_date, from_date,
                    to_date, to_date,
                    limit,
                ],
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_snapshot_history")
            conn.commit()

    return {"records": [dict(r) for r in rows], "total": len(rows)}


# ---------------------------------------------------------------------------
# P3a — Compliance
# ---------------------------------------------------------------------------

@router.get("/tenant/compliance", summary="Per-VM snapshot compliance summary")
async def compliance(ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            region_map = _region_display(cur, ctx.region_ids)

            cur.execute(
                """
                SELECT
                    s.id          AS vm_id,
                    s.name        AS vm_name,
                    s.project_id,
                    s.region_id,
                    COUNT(sr.id) FILTER (WHERE sr.status IN ('OK', 'ERROR'))   AS total_runs,
                    COUNT(sr.id) FILTER (WHERE sr.status = 'OK')                AS success_runs,
                    COUNT(sr.id) FILTER (WHERE sr.status = 'ERROR')             AS failed_runs,
                    MAX(sr.created_at) FILTER (WHERE sr.status = 'OK')          AS last_success_at,
                    MAX(sr.created_at)                                            AS last_run_at
                FROM servers s
                LEFT JOIN snapshot_records sr
                    ON sr.vm_id = s.id
                   AND sr.project_id = ANY(%s)
                WHERE s.project_id = ANY(%s)
                  AND s.region_id  = ANY(%s)
                GROUP BY s.id, s.name, s.project_id, s.region_id
                ORDER BY s.name
                """,
                (ctx.project_ids, ctx.project_ids, ctx.region_ids),
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_compliance")
            conn.commit()

    result = []
    for r in rows:
        r = dict(r)
        total = r["total_runs"] or 0
        success = r["success_runs"] or 0
        coverage_pct = round(success / total * 100, 1) if total > 0 else 0.0
        r["coverage_pct"] = coverage_pct
        r["is_compliant"] = coverage_pct >= 80.0
        r["region_display_name"] = region_map.get(r["region_id"], r["region_id"])
        result.append(r)

    total_vms = len(result)
    compliant = sum(1 for r in result if r["is_compliant"])
    return {
        "summary": {
            "total_vms": total_vms,
            "compliant_vms": compliant,
            "non_compliant_vms": total_vms - compliant,
            "overall_coverage_pct": (
                round(compliant / total_vms * 100, 1) if total_vms > 0 else 0.0
            ),
        },
        "vms": result,
    }


# ---------------------------------------------------------------------------
# P3a — Dashboard (aggregated summary)
# ---------------------------------------------------------------------------

@router.get("/tenant/dashboard", summary="Tenant dashboard summary")
async def dashboard(ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)

            # VM counts by status
            cur.execute(
                """
                SELECT status, COUNT(*) AS cnt
                FROM servers
                WHERE project_id = ANY(%s) AND region_id = ANY(%s)
                GROUP BY status
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            vm_by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

            # Volume count + total size
            cur.execute(
                """
                SELECT COUNT(*) AS cnt, COALESCE(SUM(size_gb), 0) AS total_gb
                FROM volumes
                WHERE project_id = ANY(%s) AND region_id = ANY(%s)
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            vol_row = dict(cur.fetchone())

            # Snapshot coverage: % of VMs with at least one success in last 7 days
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT s.id)                                AS total_vms,
                    COUNT(DISTINCT sr.vm_id)
                        FILTER (WHERE sr.status = 'OK'
                                  AND sr.created_at >= NOW() - INTERVAL '7 days') AS covered_7d
                FROM servers s
                LEFT JOIN snapshot_records sr ON sr.vm_id = s.id
                WHERE s.project_id = ANY(%s) AND s.region_id = ANY(%s)
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            cov_row = dict(cur.fetchone())

            # Active restore jobs (PLANNED = awaiting user action, not running)
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM restore_jobs
                WHERE project_id = ANY(%s)
                  AND status IN ('PENDING', 'RUNNING')
                """,
                (ctx.project_ids,),
            )
            active_restores = cur.fetchone()["cnt"]
            log_action(cur, ctx, "tenant_view_dashboard")
            conn.commit()

    total_vms = cov_row["total_vms"] or 0
    covered = cov_row["covered_7d"] or 0
    coverage_pct = round(covered / total_vms * 100, 1) if total_vms > 0 else 0.0

    return {
        "vms": {
            "total": sum(vm_by_status.values()),
            "by_status": vm_by_status,
        },
        "volumes": {
            "total": vol_row["cnt"],
            "total_gb": vol_row["total_gb"],
        },
        "snapshot_coverage": {
            "total_vms": total_vms,
            "covered_7d": covered,
            "coverage_pct_7d": coverage_pct,
        },
        "active_restore_jobs": active_restores,
    }


# ---------------------------------------------------------------------------
# Inventory sync status (global — not tenant-scoped)
# ---------------------------------------------------------------------------

@router.get("/tenant/inventory-status", summary="Last inventory sync timestamp")
async def inventory_status(
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Return the timestamp of the last successful inventory run.

    This tells the tenant UI when data was last synced from the platform so
    users know how stale the displayed VMs/snapshots/volumes may be.
    No RLS needed — inventory_runs contains no tenant-specific data.
    """
    try:
        with get_tenant_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT finished_at, started_at, duration_seconds
                    FROM inventory_runs
                    WHERE status = 'success'
                    ORDER BY finished_at DESC
                    LIMIT 1
                """)
                row = cur.fetchone()
    except Exception as exc:
        logger.warning("inventory-status query failed: %s", exc)
        return {"last_sync_at": None, "minutes_ago": None, "duration_seconds": None}

    if not row or not row.get("finished_at"):
        return {"last_sync_at": None, "minutes_ago": None, "duration_seconds": None}

    finished_at = row["finished_at"]
    minutes_ago = max(0, int((datetime.now(timezone.utc) - finished_at).total_seconds() / 60))
    return {
        "last_sync_at": finished_at.isoformat(),
        "minutes_ago": minutes_ago,
        "duration_seconds": row["duration_seconds"],
    }


# ---------------------------------------------------------------------------
# P3a — Event feed
# ---------------------------------------------------------------------------

@router.get("/tenant/events", summary="Unified event feed")
async def events(
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)

            # My audit log actions
            cur.execute(
                """
                SELECT
                    'audit'          AS event_source,
                    id::text         AS event_id,
                    action           AS event_type,
                    resource_type,
                    resource_id,
                    project_id,
                    region_id,
                    success,
                    timestamp        AS occurred_at,
                    details,
                    keystone_user_id,
                    username,
                    ip_address
                FROM tenant_action_log
                WHERE keystone_user_id = %s
                  AND control_plane_id = %s
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (ctx.keystone_user_id, ctx.control_plane_id, limit),
            )
            audit_events = [dict(r) for r in cur.fetchall()]

            # Recent snapshot records
            cur.execute(
                """
                SELECT
                    'snapshot'       AS event_source,
                    id::text         AS event_id,
                    action           AS event_type,
                    'snapshot_record' AS resource_type,
                    snapshot_id      AS resource_id,
                    project_id,
                    region_id,
                    (status = 'OK') AS success,
                    created_at       AS occurred_at,
                    json_build_object(
                        'vm_name', vm_name,
                        'volume_name', volume_name,
                        'size_gb', size_gb,
                        'status', status,
                        'error_message', error_message
                    ) AS details
                FROM snapshot_records
                WHERE project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (ctx.project_ids, ctx.region_ids, limit),
            )
            snap_events = [dict(r) for r in cur.fetchall()]

            # Recent restore jobs
            cur.execute(
                """
                SELECT
                    'restore'        AS event_source,
                    id::text         AS event_id,
                    'restore_'||status AS event_type,
                    'restore_job'    AS resource_type,
                    id::text         AS resource_id,
                    project_id,
                    NULL::text       AS region_id,
                    (status = 'COMPLETED') AS success,
                    COALESCE(finished_at, started_at, created_at) AS occurred_at,
                    json_build_object(
                        'vm_name', vm_name,
                        'mode', mode,
                        'status', status,
                        'failure_reason', failure_reason
                    ) AS details
                FROM restore_jobs
                WHERE project_id = ANY(%s)
                  AND created_by = 'tenant:' || %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (ctx.project_ids, ctx.keystone_user_id, limit),
            )
            restore_events = [dict(r) for r in cur.fetchall()]
            log_action(cur, ctx, "tenant_view_events")
            conn.commit()

    # Merge, sort by occurred_at desc, cap at limit
    all_events = audit_events + snap_events + restore_events
    all_events.sort(key=lambda e: e.get("occurred_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {"events": all_events[:limit], "total": len(all_events[:limit])}


# ---------------------------------------------------------------------------
# P3c — Runbooks (read-only, tenant-visible subset)
# ---------------------------------------------------------------------------

@router.get("/tenant/runbooks", summary="List tenant-visible runbooks")
async def list_runbooks(ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # No RLS on runbooks table — but we enforce is_tenant_visible and
            # project_tag scoping manually.
            cur.execute(
                """
                SELECT
                    r.runbook_id, r.name, r.display_name, r.description,
                    r.category, r.risk_level, r.supports_dry_run,
                    r.parameters_schema, r.created_at, r.updated_at
                FROM runbooks r
                WHERE r.is_tenant_visible = true
                  AND r.enabled = true
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM runbook_project_tags rpt
                          WHERE rpt.runbook_name = r.name
                      )
                      OR EXISTS (
                          SELECT 1 FROM runbook_project_tags rpt
                          WHERE rpt.runbook_name = r.name
                            AND rpt.project_id = ANY(%s)
                      )
                  )
                ORDER BY r.category, r.display_name
                """,
                (ctx.project_ids,),
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_runbooks")
            conn.commit()

    return {"runbooks": [dict(r) for r in rows], "total": len(rows)}


@router.get("/tenant/runbooks/{name}", summary="Get single runbook detail")
async def get_runbook(name: str, ctx: TenantContext = Depends(get_tenant_context)):
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    r.runbook_id, r.name, r.display_name, r.description,
                    r.category, r.risk_level, r.supports_dry_run,
                    r.parameters_schema, r.created_at, r.updated_at
                FROM runbooks r
                WHERE r.name = %s
                  AND r.is_tenant_visible = true
                  AND r.enabled = true
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM runbook_project_tags rpt
                          WHERE rpt.runbook_name = r.name
                      )
                      OR EXISTS (
                          SELECT 1 FROM runbook_project_tags rpt
                          WHERE rpt.runbook_name = r.name
                            AND rpt.project_id = ANY(%s)
                      )
                  )
                """,
                (name, ctx.project_ids),
            )
            row = cur.fetchone()
            log_action(cur, ctx, "tenant_view_runbook_detail", resource_type="runbook", resource_id=name)
            conn.commit()

    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)


# ---------------------------------------------------------------------------
# P3d — Runbook execution (tenant-initiated, tenant-visible runbooks only)
# ---------------------------------------------------------------------------

class _TenantRunbookExecuteRequest(BaseModel):
    parameters: dict = {}
    dry_run: bool = False


@router.post("/tenant/runbooks/{name}/execute", summary="Execute a tenant-visible runbook", status_code=202)
async def execute_runbook(
    name: str,
    body: _TenantRunbookExecuteRequest,
    ctx: TenantContext = Depends(require_manager_role),
):
    """Execute a tenant-visible runbook via the admin API internal endpoint."""
    import os
    import httpx as _hx

    _INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://pf9_api:8000")
    _INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

    if not _INTERNAL_SERVICE_SECRET:
        raise HTTPException(status_code=503, detail="execution_not_configured")

    try:
        with _hx.Client(timeout=120.0) as hclient:
            resp = hclient.post(
                f"{_INTERNAL_API_URL}/internal/tenant-runbook-execute",
                json={
                    "runbook_name": name,
                    "parameters": body.parameters,
                    "dry_run": body.dry_run,
                    "project_ids": ctx.project_ids,
                    "region_ids": ctx.region_ids,
                    "triggered_by": f"tenant:{ctx.username}",
                },
                headers={"X-Internal-Secret": _INTERNAL_SERVICE_SECRET},
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="execution_backend_unavailable") from exc

    if resp.status_code not in (200, 201, 202):
        body_json = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise HTTPException(resp.status_code, body_json.get("detail", "execution_failed"))

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_execute_runbook", resource_type="runbook", resource_id=name)
            conn.commit()

    return resp.json()


@router.get("/tenant/runbook-executions", summary="List my runbook executions")
async def list_runbook_executions(
    limit: int = Query(20, ge=1, le=100),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Return recent runbook executions triggered by this tenant user."""
    import os
    import httpx as _hx

    _INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://pf9_api:8000")
    _INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

    if not _INTERNAL_SERVICE_SECRET:
        return {"executions": []}

    try:
        with _hx.Client(timeout=10.0) as hclient:
            resp = hclient.get(
                f"{_INTERNAL_API_URL}/internal/tenant-runbook-executions",
                params={"triggered_by": f"tenant:{ctx.username}", "limit": limit},
                headers={"X-Internal-Secret": _INTERNAL_SERVICE_SECRET},
            )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"executions": []}


# ---------------------------------------------------------------------------
# P4b — Security groups for restore configuration
# ---------------------------------------------------------------------------

@router.get("/tenant/security-groups", summary="List tenant security groups")
async def list_security_groups(ctx: TenantContext = Depends(get_tenant_context)):
    """Return security groups belonging to the tenant's projects (for restore config)."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                """
                SELECT id, name, description, project_id
                FROM security_groups
                WHERE project_id = ANY(%s)
                ORDER BY name
                """,
                (ctx.project_ids,),
            )
            rows = cur.fetchall()
            log_action(cur, ctx, "tenant_view_security_groups")
            conn.commit()
    return {
        "security_groups": [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "description": r.get("description") or "",
                "project_id": r["project_id"],
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# P4b — Sync & Snapshot Now (self-service trigger)
# ---------------------------------------------------------------------------

@router.post("/tenant/sync-and-snapshot", summary="Trigger inventory sync and immediate snapshots")
async def sync_and_snapshot(ctx: TenantContext = Depends(require_manager_role)):
    """
    Trigger an on-demand inventory sync followed by immediate snapshots for all
    tenant VMs that do not already have a snapshot today.  The request is
    delegated to the admin API internal endpoint so the tenant portal never
    touches OpenStack credentials directly.
    Rate-limited to one call per project per hour (enforced in the admin API).
    """
    import os
    import httpx

    INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://pf9_api:8000")
    INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

    if not INTERNAL_SERVICE_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="sync_not_configured",
        )

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{INTERNAL_API_URL}/internal/tenant-sync-and-snapshot",
                json={
                    "project_ids": ctx.project_ids,
                    "region_ids": ctx.region_ids,
                    "requested_by": f"tenant:{ctx.keystone_user_id}",
                },
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except httpx.HTTPError as exc:
        logger.error("Admin API call failed (sync-and-snapshot): %s", exc)
        raise HTTPException(503, "sync_backend_unavailable")

    if resp.status_code not in (200, 202):
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise HTTPException(resp.status_code, body.get("detail", "sync_failed"))

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_sync_and_snapshot")
            conn.commit()

    return {"message": "Sync and snapshot triggered. Inventory will update within a few minutes.", "status": "accepted"}


# ---------------------------------------------------------------------------
# P4c — Tenant reports (read-only, project-scoped)
# ---------------------------------------------------------------------------

_TENANT_REPORTS = [
    {
        "name": "snapshot_coverage",
        "display_name": "Snapshot Coverage Report",
        "description": "Per-VM snapshot coverage and compliance status over the last 30 days.",
        "category": "Protection",
    },
    {
        "name": "restore_history",
        "display_name": "Restore History Report",
        "description": "List of all restore operations performed on your VMs including status and duration.",
        "category": "Recovery",
    },
    {
        "name": "vm_inventory",
        "display_name": "VM Inventory Report",
        "description": "Full inventory of your virtual machines with flavor, status, and last-snapshot date.",
        "category": "Inventory",
    },
    {
        "name": "storage_usage",
        "display_name": "Storage Usage Report",
        "description": "Snapshot storage consumption per VM and total usage vs. quota.",
        "category": "Storage",
    },
    {
        "name": "quota_usage",
        "display_name": "Quota Usage Report",
        "description": "Current vCPU, RAM, instances, volumes, and storage quota usage vs. limits for your projects.",
        "category": "Quota",
    },
    {
        "name": "activity_log",
        "display_name": "Activity Log Report",
        "description": "Downloadable export of all portal actions and events for auditing purposes.",
        "category": "Audit",
    },
]


@router.get("/tenant/reports", summary="List available tenant reports")
async def list_tenant_reports(ctx: TenantContext = Depends(get_tenant_context)):
    """Return the catalogue of reports available to this tenant."""
    log_action_noop = lambda: None  # noqa: E731
    _ = log_action_noop  # keep RLS established for consistency
    return {
        "reports": [
            {
                "name": r["name"],
                "display_name": r["display_name"],
                "description": r["description"],
                "category": r["category"],
                "download_url": f"/tenant/reports/{r['name']}/download",
            }
            for r in _TENANT_REPORTS
        ]
    }


@router.get("/tenant/reports/{report_name}/download", summary="Download a tenant report as CSV")
async def download_tenant_report(
    report_name: str,
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Generate and stream a CSV report scoped to the tenant's projects."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    valid_names = {r["name"] for r in _TENANT_REPORTS}
    if report_name not in valid_names:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report_not_found")

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_download_report", resource_type="report", resource_id=report_name)

            if report_name == "snapshot_coverage":
                cur.execute(
                    """
                    SELECT s.name AS vm_name, s.region_id,
                           COUNT(sr.id) FILTER (WHERE sr.status = 'OK')    AS success_count,
                           COUNT(sr.id) FILTER (WHERE sr.status = 'ERROR') AS fail_count,
                           MAX(sr.created_at) FILTER (WHERE sr.status = 'OK') AS last_snapshot
                    FROM servers s
                    LEFT JOIN snapshot_records sr ON sr.vm_id = s.id AND sr.project_id = ANY(%s)
                    WHERE s.project_id = ANY(%s) AND s.region_id = ANY(%s)
                    GROUP BY s.id, s.name, s.region_id
                    ORDER BY s.name
                    """,
                    (ctx.project_ids, ctx.project_ids, ctx.region_ids),
                )
                rows = cur.fetchall()
                headers = ["VM Name", "Region", "Successes (30d)", "Failures (30d)", "Last Snapshot"]
                data = [[r["vm_name"], r["region_id"], r["success_count"] or 0, r["fail_count"] or 0,
                         r["last_snapshot"].isoformat() if r.get("last_snapshot") else ""] for r in rows]

            elif report_name == "restore_history":
                cur.execute(
                    """
                    SELECT vm_name, mode, status, created_at, finished_at, failure_reason
                    FROM restore_jobs
                    WHERE project_id = ANY(%s)
                      AND (%s::timestamptz IS NULL OR created_at >= %s)
                      AND (%s::timestamptz IS NULL OR created_at <= %s)
                    ORDER BY created_at DESC
                    LIMIT 1000
                    """,
                    (ctx.project_ids, from_date, from_date, to_date, to_date),
                )
                rows = cur.fetchall()
                headers = ["VM Name", "Mode", "Status", "Started", "Finished", "Failure Reason"]
                data = [[r["vm_name"], r["mode"], r["status"],
                         r["created_at"].isoformat() if r.get("created_at") else "",
                         r["finished_at"].isoformat() if r.get("finished_at") else "",
                         r.get("failure_reason") or ""] for r in rows]

            elif report_name == "vm_inventory":
                cur.execute(
                    """
                    SELECT s.name, s.status, s.region_id,
                           COALESCE(f.vcpus, 0)   AS vcpus,
                           COALESCE(f.ram_mb, 0)  AS ram_mb,
                           COALESCE(f.disk_gb, 0) AS disk_gb,
                           s.raw_json,
                           s.created_at,
                           (SELECT MAX(sr.created_at) FROM snapshot_records sr
                            WHERE sr.vm_id = s.id AND sr.status = 'OK') AS last_snapshot
                    FROM servers s
                    LEFT JOIN flavors f ON f.id = s.flavor_id
                    WHERE s.project_id = ANY(%s) AND s.region_id = ANY(%s)
                    ORDER BY s.name
                    """,
                    (ctx.project_ids, ctx.region_ids),
                )
                rows = cur.fetchall()
                headers = ["VM Name", "Status", "Region", "vCPUs", "RAM (MB)", "Disk (GB)", "IP Addresses", "Created", "Last Snapshot"]
                data = []
                for r in rows:
                    ips = ", ".join(_extract_ips(r.get("raw_json")))
                    data.append([
                        r["name"], r["status"], r["region_id"],
                        r["vcpus"], r["ram_mb"], r["disk_gb"],
                        ips,
                        r["created_at"].isoformat() if r.get("created_at") else "",
                        r["last_snapshot"].isoformat() if r.get("last_snapshot") else "",
                    ])

            elif report_name == "storage_usage":
                cur.execute(
                    """
                    SELECT s.name AS vm_name, s.region_id,
                           COUNT(snap.id) AS snapshot_count,
                           COALESCE(SUM(snap.size_gb), 0) AS total_snapshot_gb
                    FROM servers s
                    LEFT JOIN volumes v ON v.server_id = s.id AND v.project_id = ANY(%s)
                    LEFT JOIN snapshots snap ON snap.volume_id = v.id AND snap.project_id = ANY(%s)
                    WHERE s.project_id = ANY(%s) AND s.region_id = ANY(%s)
                    GROUP BY s.id, s.name, s.region_id
                    ORDER BY total_snapshot_gb DESC
                    """,
                    (ctx.project_ids, ctx.project_ids, ctx.project_ids, ctx.region_ids),
                )
                rows = cur.fetchall()
                headers = ["VM Name", "Region", "Snapshot Count", "Total Snapshot GB"]
                data = [[r["vm_name"], r["region_id"], r["snapshot_count"], r["total_snapshot_gb"]] for r in rows]

            elif report_name == "quota_usage":
                # Fetch from admin API, then render as CSV
                import httpx as _httpx
                from restore_routes import INTERNAL_API_URL, INTERNAL_SERVICE_SECRET
                project_ids_csv = ",".join(ctx.project_ids)
                try:
                    with _httpx.Client(timeout=10.0) as hclient:
                        qresp = hclient.get(
                            f"{INTERNAL_API_URL}/internal/tenant-quota",
                            params={"project_ids": project_ids_csv, "control_plane_id": ctx.control_plane_id},
                            headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
                        )
                    qdata = qresp.json().get("projects", []) if qresp.status_code == 200 else []
                except Exception:
                    qdata = []
                headers = ["Project ID", "Resource", "Limit", "Used", "Available", "% Used"]
                data = []
                for proj in qdata:
                    pid = proj.get("project_id", "")
                    for section, items in [("compute", proj.get("compute", {})), ("storage", proj.get("storage", {}))]:
                        for key, vals in items.items():
                            limit = vals.get("limit", -1)
                            used = vals.get("used", 0)
                            avail = (limit - used) if limit >= 0 else "∞"
                            pct = f"{round(used/limit*100, 1)}%" if limit > 0 else "N/A"
                            data.append([pid, f"{section}/{key}", limit if limit >= 0 else "unlimited", used, avail, pct])
                conn.commit()

            else:  # activity_log
                cur.execute(
                    """
                    SELECT action, resource_type, resource_id, occurred_at, success, ip_address
                    FROM tenant_action_log
                    WHERE project_id = ANY(%s)
                      AND (%s::timestamptz IS NULL OR occurred_at >= %s)
                      AND (%s::timestamptz IS NULL OR occurred_at <= %s)
                    ORDER BY occurred_at DESC
                    LIMIT 5000
                    """,
                    (ctx.project_ids, from_date, from_date, to_date, to_date),
                )
                rows = cur.fetchall()
                headers = ["Action", "Resource Type", "Resource ID", "Timestamp", "Success", "IP"]
                data = [[r["action"], r.get("resource_type") or "", r.get("resource_id") or "",
                         r["occurred_at"].isoformat() if r.get("occurred_at") else "",
                         "Yes" if r.get("success") else "No", r.get("ip_address") or ""] for r in rows]

            conn.commit()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(data)
    csv_bytes = output.getvalue().encode("utf-8")

    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{report_name}.csv"'},
    )


# ---------------------------------------------------------------------------
# P4c — Tenant quota usage (live from OpenStack via admin API)
# ---------------------------------------------------------------------------

@router.get("/tenant/quota", summary="Get quota limits and current usage for tenant projects")
async def get_tenant_quota(ctx: TenantContext = Depends(get_tenant_context)):
    """Fetch Nova + Cinder quota limits and in_use counts for all tenant projects
    by delegating to the admin API (which has OpenStack credentials).
    Returns an aggregated total plus a per-project breakdown."""
    import httpx as _httpx

    from restore_routes import INTERNAL_API_URL, INTERNAL_SERVICE_SECRET  # reuse env vars

    if not INTERNAL_SERVICE_SECRET:
        raise HTTPException(status_code=503, detail="internal_secret_not_configured")

    project_ids_csv = ",".join(ctx.project_ids)

    try:
        with _httpx.Client(timeout=10.0) as client:
            resp = client.get(
                f"{INTERNAL_API_URL}/internal/tenant-quota",
                params={
                    "project_ids": project_ids_csv,
                    "control_plane_id": ctx.control_plane_id,
                },
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except _httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"admin_api_unreachable: {exc}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="quota_fetch_failed")

    data = resp.json()
    projects = data.get("projects", [])

    # Aggregate totals across all projects
    def _sum(projects, section, key, field):
        vals = [p.get(section, {}).get(key, {}).get(field, 0) for p in projects]
        return sum(v for v in vals if v >= 0)

    def _limit(projects, section, key):
        limits = [p.get(section, {}).get(key, {}).get("limit", -1) for p in projects]
        if all(l == -1 for l in limits):
            return -1
        return sum(l for l in limits if l >= 0)

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_view_quota")
            conn.commit()

    return {
        "totals": {
            "compute": {
                "instances": {"limit": _limit(projects, "compute", "instances"), "used": _sum(projects, "compute", "instances", "used")},
                "cores":     {"limit": _limit(projects, "compute", "cores"),     "used": _sum(projects, "compute", "cores", "used")},
                "ram_mb":    {"limit": _limit(projects, "compute", "ram_mb"),    "used": _sum(projects, "compute", "ram_mb", "used")},
            },
            "storage": {
                "volumes":   {"limit": _limit(projects, "storage", "volumes"),   "used": _sum(projects, "storage", "volumes", "used")},
                "gigabytes": {"limit": _limit(projects, "storage", "gigabytes"), "used": _sum(projects, "storage", "gigabytes", "used")},
                "snapshots": {"limit": _limit(projects, "storage", "snapshots"), "used": _sum(projects, "storage", "snapshots", "used")},
            },
        },
        "projects": projects,
    }


# ---------------------------------------------------------------------------
# P5a — Networks & Subnets (read-only inventory)
# ---------------------------------------------------------------------------

@router.get("/tenant/networks", summary="List tenant networks with subnets")
async def list_networks(ctx: TenantContext = Depends(get_tenant_context)):
    """Return networks and their subnets for the tenant's projects."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                """
                SELECT n.id, n.name, n.status, n.admin_state_up,
                       n.is_shared, n.is_external, n.project_id, n.region_id
                FROM networks n
                WHERE n.project_id = ANY(%s)
                   OR n.is_shared = true
                ORDER BY n.name
                """,
                (ctx.project_ids,),
            )
            networks = cur.fetchall()
            net_ids = [r["id"] for r in networks]

            subnets: list = []
            if net_ids:
                cur.execute(
                    """
                    SELECT id, name, network_id, cidr, gateway_ip, enable_dhcp, region_id
                    FROM subnets
                    WHERE network_id = ANY(%s)
                    ORDER BY cidr
                    """,
                    (net_ids,),
                )
                subnets = cur.fetchall()

            log_action(cur, ctx, "tenant_view_networks")
            conn.commit()

    subnet_map: dict = {}
    for s in subnets:
        subnet_map.setdefault(s["network_id"], []).append({
            "id": s["id"],
            "name": s.get("name") or "",
            "cidr": s.get("cidr") or "",
            "gateway_ip": s.get("gateway_ip") or "",
            "enable_dhcp": s.get("enable_dhcp"),
            "region_id": s.get("region_id") or "",
        })

    return {
        "networks": [
            {
                "id": r["id"],
                "name": r.get("name") or "",
                "status": r.get("status") or "",
                "admin_state_up": r.get("admin_state_up"),
                "is_shared": r.get("is_shared"),
                "is_external": r.get("is_external"),
                "project_id": r.get("project_id") or "",
                "region_id": r.get("region_id") or "",
                "subnets": subnet_map.get(r["id"], []),
            }
            for r in networks
        ]
    }


# ---------------------------------------------------------------------------
# P5a-2 — Used IPs in a network (for Fixed IP picker in New VM)
# ---------------------------------------------------------------------------

@router.get("/tenant/networks/{network_id}/used-ips", summary="List IPs already assigned in a network")
async def get_network_used_ips(network_id: str, ctx: TenantContext = Depends(get_tenant_context)):
    """Return IPs currently assigned to VMs in this network, derived from
    servers.raw_json.  Used by the tenant New VM screen to show which IPs are
    already taken so the operator can pick a free one."""
    import ipaddress as _ipaddress

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            # Verify network is accessible by this tenant and get its name
            cur.execute(
                """
                SELECT id, name FROM networks
                WHERE id = %s AND (project_id = ANY(%s) OR is_shared = true)
                LIMIT 1
                """,
                (network_id, ctx.project_ids),
            )
            net_row = cur.fetchone()
            if net_row is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
            network_name = net_row["name"] or ""

            # Get subnet CIDRs for this network (used as fallback IP filter)
            cur.execute(
                "SELECT cidr FROM subnets WHERE network_id = %s",
                (network_id,),
            )
            subnet_cidrs = [r["cidr"] for r in cur.fetchall() if r.get("cidr")]

            # Fetch raw_json for all running servers in tenant projects
            cur.execute(
                """
                SELECT id, name, raw_json
                FROM servers
                WHERE project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                  AND status NOT IN ('DELETED', 'ERROR')
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            servers = cur.fetchall()
            log_action(cur, ctx, "tenant_view_used_ips")
            conn.commit()

    # Pre-compute CIDR network objects for fallback matching
    cidr_nets: list = []
    for cidr in subnet_cidrs:
        try:
            cidr_nets.append(_ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            pass

    def _ips_for_network(raw_json) -> list:
        """Extract IPs that belong to the requested network from Nova raw_json."""
        if not raw_json or not isinstance(raw_json, dict):
            return []
        addresses = raw_json.get("addresses", {})

        # Primary: match by network name key (Nova groups addresses by net name)
        if network_name and network_name in addresses:
            net_addrs = addresses[network_name]
            if isinstance(net_addrs, list):
                return [a.get("addr") for a in net_addrs if a.get("addr")]

        # Fallback: check every IP against the network's subnet CIDRs
        if cidr_nets:
            matched: list = []
            for net_addrs in addresses.values():
                if not isinstance(net_addrs, list):
                    continue
                for addr_obj in net_addrs:
                    addr = addr_obj.get("addr")
                    if not addr:
                        continue
                    try:
                        ip_obj = _ipaddress.ip_address(addr)
                        if any(ip_obj in net for net in cidr_nets):
                            matched.append(addr)
                    except ValueError:
                        pass
            return matched

        return []

    used: list = []
    for srv in servers:
        ips = _ips_for_network(srv.get("raw_json"))
        if ips:
            used.append({"vm_id": srv["id"], "vm_name": srv["name"], "ips": ips})

    return {"network_id": network_id, "used": used}


# ---------------------------------------------------------------------------
# P5b — Security Group detail + rule management
# ---------------------------------------------------------------------------

@router.get("/tenant/security-groups/{sg_id}", summary="Get security group with its rules")
async def get_security_group(sg_id: str, ctx: TenantContext = Depends(get_tenant_context)):
    """Return a single security group including all its rules."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                """
                SELECT id, name, description, project_id
                FROM security_groups
                WHERE id = %s AND project_id = ANY(%s)
                """,
                (sg_id, ctx.project_ids),
            )
            sg = cur.fetchone()
            if sg is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")

            cur.execute(
                """
                SELECT id, direction, ethertype, protocol,
                       port_range_min, port_range_max,
                       remote_ip_prefix, remote_group_id, description
                FROM security_group_rules
                WHERE security_group_id = %s
                ORDER BY direction, protocol NULLS LAST, port_range_min NULLS LAST
                """,
                (sg_id,),
            )
            rules = cur.fetchall()
            log_action(cur, ctx, "tenant_view_sg_detail", resource_id=sg_id)
            conn.commit()

    return {
        "id": sg["id"],
        "name": sg["name"],
        "description": sg.get("description") or "",
        "project_id": sg["project_id"],
        "rules": [
            {
                "id": r["id"],
                "direction": r.get("direction") or "",
                "ethertype": r.get("ethertype") or "IPv4",
                "protocol": r.get("protocol") or "any",
                "port_range_min": r.get("port_range_min"),
                "port_range_max": r.get("port_range_max"),
                "remote_ip_prefix": r.get("remote_ip_prefix") or "",
                "remote_group_id": r.get("remote_group_id") or "",
                "description": r.get("description") or "",
            }
            for r in rules
        ],
    }


class AddSgRuleRequest(BaseModel):
    direction: str           # ingress | egress
    ethertype: str = "IPv4"  # IPv4 | IPv6
    protocol: Optional[str] = None   # tcp | udp | icmp | None = any
    port_range_min: Optional[int] = None
    port_range_max: Optional[int] = None
    remote_ip_prefix: Optional[str] = None
    remote_group_id: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def __get_validators__(cls):
        yield cls._validate_direction

    @staticmethod
    def _validate_direction(v):
        return v

    def model_post_init(self, __context) -> None:
        if self.direction not in ("ingress", "egress"):
            raise ValueError("direction must be ingress or egress")
        if self.ethertype not in ("IPv4", "IPv6"):
            raise ValueError("ethertype must be IPv4 or IPv6")
        if self.protocol and self.protocol not in ("tcp", "udp", "icmp", "icmpv6", "ah", "esp", "gre"):
            raise ValueError(f"unsupported protocol: {self.protocol}")


from pydantic import BaseModel as _BM, validator as _validator  # noqa: E402 – already imported above via BaseModel


@router.post("/tenant/security-groups/{sg_id}/rules", summary="Add a security group rule", status_code=201)
async def add_sg_rule(sg_id: str, body: AddSgRuleRequest, ctx: TenantContext = Depends(require_manager_role)):
    """Add an ingress/egress rule to a tenant-owned security group via the admin API."""
    import httpx as _hx
    from restore_routes import INTERNAL_API_URL, INTERNAL_SERVICE_SECRET

    # Verify ownership before calling out
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                "SELECT id, project_id FROM security_groups WHERE id = %s AND project_id = ANY(%s)",
                (sg_id, ctx.project_ids),
            )
            sg = cur.fetchone()
            if sg is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
            conn.commit()

    payload = {
        "sg_id": sg_id,
        "project_id": sg["project_id"],
        "direction": body.direction,
        "ethertype": body.ethertype,
        "protocol": body.protocol,
        "port_range_min": body.port_range_min,
        "port_range_max": body.port_range_max,
        "remote_ip_prefix": body.remote_ip_prefix,
        "remote_group_id": body.remote_group_id,
        "description": body.description or "",
    }

    try:
        with _hx.Client(timeout=15.0) as hclient:
            resp = hclient.post(
                f"{INTERNAL_API_URL}/internal/sg-rule",
                json=payload,
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="upstream_error") from exc

    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "rule_create_failed"))

    # Audit
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_add_sg_rule", resource_id=sg_id)
            conn.commit()

    return resp.json()


@router.delete("/tenant/security-groups/{sg_id}/rules/{rule_id}", summary="Delete a security group rule", status_code=204)
async def delete_sg_rule(sg_id: str, rule_id: str, ctx: TenantContext = Depends(require_manager_role)):
    """Remove a rule from a tenant-owned security group via the admin API."""
    import httpx as _hx
    from restore_routes import INTERNAL_API_URL, INTERNAL_SERVICE_SECRET

    # Verify ownership
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                """
                SELECT r.id FROM security_group_rules r
                JOIN security_groups g ON g.id = r.security_group_id
                WHERE r.id = %s AND r.security_group_id = %s AND g.project_id = ANY(%s)
                """,
                (rule_id, sg_id, ctx.project_ids),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
            conn.commit()

    try:
        with _hx.Client(timeout=15.0) as hclient:
            resp = hclient.delete(
                f"{INTERNAL_API_URL}/internal/sg-rule/{rule_id}",
                params={"sg_id": sg_id},
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="upstream_error") from exc

    if resp.status_code not in (200, 204):
        raise HTTPException(status_code=resp.status_code, detail="rule_delete_failed")

    # Audit
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_delete_sg_rule", resource_id=sg_id)
            conn.commit()


# ---------------------------------------------------------------------------
# P5c — Dependency / resource graph
# ---------------------------------------------------------------------------

@router.get("/tenant/resource-graph", summary="Return VM → network / security-group dependency graph")
async def resource_graph(ctx: TenantContext = Depends(get_tenant_context)):
    """
    Returns nodes (VMs, networks, subnets, security groups, volumes) and edges for
    the dependency visualisation. Edges are derived from:
      - VM → network: ports table (device_id = vm_id, network_id)
      - VM → SG:      servers.raw_json → security_groups[].name matched to sg.id
      - network → subnet: subnets.network_id
      - VM → volume: volumes.server_id
    """
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)

            # VMs
            cur.execute(
                """
                SELECT id, name, status, project_id, region_id
                FROM servers
                WHERE project_id = ANY(%s) AND region_id = ANY(%s)
                ORDER BY name
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            vms = cur.fetchall()

            # Networks (tenant-owned + shared)
            cur.execute(
                """
                SELECT id, name, project_id
                FROM networks
                WHERE project_id = ANY(%s) OR is_shared = true
                """,
                (ctx.project_ids,),
            )
            networks = cur.fetchall()

            # Subnets for those networks
            net_ids = [n["id"] for n in networks]
            subnets: list = []
            if net_ids:
                cur.execute(
                    """
                    SELECT id, name, network_id, cidr
                    FROM subnets
                    WHERE network_id = ANY(%s)
                    ORDER BY cidr
                    """,
                    (net_ids,),
                )
                subnets = cur.fetchall()

            # Security groups
            cur.execute(
                """
                SELECT id, name, project_id
                FROM security_groups
                WHERE project_id = ANY(%s)
                """,
                (ctx.project_ids,),
            )
            sgs = cur.fetchall()

            # Volumes attached to tenant VMs
            vm_ids = [v["id"] for v in vms]
            volumes: list = []
            if vm_ids:
                cur.execute(
                    """
                    SELECT id, name, server_id, size_gb
                    FROM volumes
                    WHERE server_id = ANY(%s)
                      AND project_id = ANY(%s)
                    ORDER BY name
                    """,
                    (vm_ids, ctx.project_ids),
                )
                volumes = cur.fetchall()

            # VM → Network edges via ports
            net_edges: list = []
            if vm_ids:
                cur.execute(
                    """
                    SELECT DISTINCT device_id AS vm_id, network_id
                    FROM ports
                    WHERE device_id = ANY(%s)
                      AND device_owner LIKE 'compute:%%'
                    """,
                    (vm_ids,),
                )
                net_edges = cur.fetchall()

            # VM → SG edges via servers.raw_json
            sg_by_name = {s["name"]: s["id"] for s in sgs}
            sg_edges: list = []
            for vm in vms:
                raw = vm.get("raw_json") or {}
                if isinstance(raw, str):
                    import json as _json
                    try:
                        raw = _json.loads(raw)
                    except Exception:
                        raw = {}
                for sg_ref in raw.get("security_groups", []):
                    sg_name = sg_ref.get("name", "")
                    sg_id_found = sg_by_name.get(sg_name)
                    if sg_id_found:
                        sg_edges.append({"vm_id": vm["id"], "sg_id": sg_id_found})

            log_action(cur, ctx, "tenant_view_resource_graph")
            conn.commit()

    return {
        "nodes": {
            "vms": [{"id": v["id"], "name": v.get("name") or v["id"], "status": v.get("status") or "", "project_id": v.get("project_id") or ""} for v in vms],
            "networks": [{"id": n["id"], "name": n.get("name") or n["id"], "project_id": n.get("project_id") or ""} for n in networks],
            "subnets": [{"id": s["id"], "name": s.get("name") or s.get("cidr") or s["id"], "network_id": s["network_id"], "cidr": s.get("cidr") or ""} for s in subnets],
            "security_groups": [{"id": s["id"], "name": s.get("name") or s["id"], "project_id": s.get("project_id") or ""} for s in sgs],
            "volumes": [{"id": v["id"], "name": v.get("name") or v["id"], "server_id": v.get("server_id") or "", "size_gb": v.get("size_gb") or 0} for v in volumes],
        },
        "edges": {
            "vm_network": [{"vm_id": e["vm_id"], "network_id": e["network_id"]} for e in net_edges],
            "network_subnet": [{"network_id": s["network_id"], "subnet_id": s["id"]} for s in subnets],
            "vm_sg": sg_edges,
            "vm_volume": [{"vm_id": v["server_id"], "volume_id": v["id"]} for v in volumes if v.get("server_id")],
        },
    }


# ---------------------------------------------------------------------------
# P5d — VM Provisioning (single VM creation for tenant admins)
# ---------------------------------------------------------------------------

@router.get("/tenant/provision/resources", summary="List flavors, images and networks available for provisioning")
async def provision_resources(ctx: TenantContext = Depends(get_tenant_context)):
    """Return flavors, images, networks and security groups the tenant can use to create a VM."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)

            cur.execute(
                "SELECT id, name, vcpus, ram_mb, disk_gb FROM flavors ORDER BY vcpus, ram_mb"
            )
            flavors = cur.fetchall()

            cur.execute(
                """
                SELECT id, name, os_distro, os_version, disk_format, size_bytes, status
                FROM images
                WHERE status = 'active'
                ORDER BY name
                """
            )
            images = cur.fetchall()

            cur.execute(
                """
                SELECT n.id, n.name, n.is_shared
                FROM networks n
                WHERE (n.project_id = ANY(%s) OR n.is_shared = true)
                  AND n.admin_state_up = true
                ORDER BY n.name
                """,
                (ctx.project_ids,),
            )
            networks = cur.fetchall()

            # Attach subnets to each network
            subnets_by_net: dict = {}
            if networks:
                net_ids = [n["id"] for n in networks]
                cur.execute(
                    "SELECT id, name, network_id, cidr FROM subnets WHERE network_id = ANY(%s) ORDER BY name",
                    (net_ids,),
                )
                subnet_rows = cur.fetchall()
                subnets_by_net: dict = {}
                for srow in subnet_rows:
                    subnets_by_net.setdefault(srow["network_id"], []).append(
                        {"id": srow["id"], "name": srow["name"], "cidr": srow["cidr"]}
                    )

            cur.execute(
                "SELECT id, name FROM security_groups WHERE project_id = ANY(%s) ORDER BY name",
                (ctx.project_ids,),
            )
            sgs = cur.fetchall()

            log_action(cur, ctx, "tenant_view_provision_resources")
            conn.commit()

    return {
        "flavors": [{"id": r["id"], "name": r["name"], "vcpus": r["vcpus"], "ram_mb": r["ram_mb"], "disk_gb": r.get("disk_gb")} for r in flavors],
        "images": [{"id": r["id"], "name": r["name"], "os_distro": r.get("os_distro") or "", "status": r.get("status") or ""} for r in images],
        "networks": [{"id": r["id"], "name": r["name"], "is_shared": r.get("is_shared"), "subnets": subnets_by_net.get(r["id"], []) if networks else []} for r in networks],
        "security_groups": [{"id": r["id"], "name": r["name"]} for r in sgs],
    }


class ProvisionVmRequest(BaseModel):
    name: str
    flavor_id: str
    image_id: str
    network_id: str
    security_group_ids: List[str] = []
    key_pair_name: Optional[str] = None
    user_data: Optional[str] = None
    count: int = 1

    fixed_ip: Optional[str] = None

    def model_post_init(self, __context) -> None:
        import re as _re
        if not self.name or len(self.name) > 63:
            raise ValueError("name must be 1-63 characters")
        if not _re.match(r'^[a-z0-9][a-z0-9-]*$', self.name):
            raise ValueError("name must start with a letter or digit and contain only lowercase letters, numbers, and hyphens")
        if self.count < 1 or self.count > 10:
            raise ValueError("count must be 1-10")


@router.post("/tenant/vms", summary="Provision one or more VMs (tenant admin)", status_code=202)
async def provision_vm(body: ProvisionVmRequest, ctx: TenantContext = Depends(require_manager_role)):
    """
    Create VM(s) in the tenant's primary project via the admin API.
    Delegates to POST /internal/tenant-provision-vm — the admin API validates
    quota, resolves the control-plane token, and calls Nova.
    """
    import httpx as _hx
    from restore_routes import INTERNAL_API_URL, INTERNAL_SERVICE_SECRET

    if not INTERNAL_SERVICE_SECRET:
        raise HTTPException(status_code=503, detail="provisioning_not_configured")

    # Use first project as the provisioning target
    project_id = ctx.project_ids[0] if ctx.project_ids else None
    if not project_id:
        raise HTTPException(status_code=400, detail="no_project_available")

    payload = {
        "project_id": project_id,
        "control_plane_id": ctx.control_plane_id,
        "name": body.name,
        "flavor_id": body.flavor_id,
        "image_id": body.image_id,
        "network_id": body.network_id,
        "security_group_ids": body.security_group_ids,
        "key_pair_name": body.key_pair_name,
        "user_data": body.user_data,
        "fixed_ip": body.fixed_ip,
        "count": body.count,
    }

    try:
        with _hx.Client(timeout=30.0) as hclient:
            resp = hclient.post(
                f"{INTERNAL_API_URL}/internal/tenant-provision-vm",
                json=payload,
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="upstream_unavailable") from exc

    if resp.status_code not in (200, 201, 202):
        raise HTTPException(status_code=resp.status_code, detail=resp.json().get("detail", "provision_failed"))

    # Audit
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            log_action(cur, ctx, "tenant_provision_vm", resource_id=body.name)
            conn.commit()

    return resp.json()



# ---------------------------------------------------------------------------
# GET /tenant/client-health — proxy to admin API intelligence endpoint
# Returns health scores for the tenant's primary project
# ---------------------------------------------------------------------------

@router.get("/tenant/client-health", summary="Get client health scores for this tenant")
async def get_client_health(ctx: TenantContext = Depends(get_tenant_context)):
    """
    Proxy to GET /api/intelligence/client-health/{tenant_id}.
    Uses the first project name as the tenant identifier.
    """
    import os
    import httpx as _hx

    INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://pf9_api:8000")
    INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

    if not INTERNAL_SERVICE_SECRET:
        raise HTTPException(status_code=503, detail="health_service_not_configured")

    # Use the first project id as tenant_id
    tenant_id = ctx.project_ids[0] if ctx.project_ids else ctx.control_plane_id

    try:
        with _hx.Client(timeout=15.0) as hclient:
            resp = hclient.get(
                f"{INTERNAL_API_URL}/internal/client-health/{tenant_id}",
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="upstream_unavailable") from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="health_fetch_failed")

    return resp.json()
