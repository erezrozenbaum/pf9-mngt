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

P3c endpoints:
  GET /tenant/runbooks
  GET /tenant/runbooks/{name}
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars
from tenant_context import TenantContext

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
               s.project_id, s.region_id, s.raw_json
        FROM servers s
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
                       (
                           SELECT MAX(sr.created_at)
                           FROM snapshot_records sr
                           WHERE sr.vm_id = s.id AND sr.status = 'success'
                       ) AS last_snapshot_at
                FROM servers s
                WHERE s.project_id = ANY(%s)
                  AND s.region_id  = ANY(%s)
                ORDER BY s.name
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            rows = cur.fetchall()
            conn.commit()

    result = []
    for r in rows:
        r = dict(r)
        r["region_display_name"] = region_map.get(r["region_id"], r["region_id"])
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
                    MAX(CASE WHEN status = 'success' THEN created_at END) AS last_snapshot_at,
                    COUNT(*) FILTER (WHERE status = 'success')            AS total_success,
                    COUNT(*) FILTER (WHERE status = 'failed')             AS total_failed,
                    COUNT(*)                                               AS total_runs
                FROM snapshot_records
                WHERE vm_id = %s
                """,
                (vm_id,),
            )
            snap_stats = dict(cur.fetchone() or {})

            # Active restore job (if any)
            cur.execute(
                """
                SELECT id, status, created_at, mode
                FROM restore_jobs
                WHERE vm_id = %s
                  AND status IN ('PLANNED', 'PENDING', 'RUNNING')
                  AND project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (vm_id, ctx.project_ids, ctx.region_ids),
            )
            active_restore = cur.fetchone()
            conn.commit()

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
                SELECT id, name, project_id, size_gb, status,
                       volume_type, bootable, created_at,
                       server_id, region_id
                FROM volumes
                WHERE project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                ORDER BY name
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            rows = cur.fetchall()
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
    conditions = [
        "s.project_id = ANY(%s)",
        "s.region_id  = ANY(%s)",
    ]
    params: list = [ctx.project_ids, ctx.region_ids]

    if vm_id:
        conditions.append(
            "EXISTS (SELECT 1 FROM volumes v WHERE v.id = s.volume_id AND v.server_id = %s)"
        )
        params.append(vm_id)
    if region:
        conditions.append("s.region_id = %s")
        params.append(region)
    if snap_status:
        conditions.append("s.status = %s")
        params.append(snap_status)
    if from_date:
        conditions.append("s.created_at >= %s")
        params.append(from_date)
    if to_date:
        conditions.append("s.created_at <= %s")
        params.append(to_date)

    where_clause = " AND ".join(conditions)
    params.append(limit)

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            region_map = _region_display(cur, ctx.region_ids)
            cur.execute(
                f"""
                SELECT s.id, s.name, s.description, s.project_id, s.project_name,
                       s.volume_id, s.size_gb, s.status, s.created_at, s.region_id
                FROM snapshots s
                WHERE {where_clause}
                ORDER BY s.created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
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
    conditions = ["project_id = ANY(%s)", "region_id = ANY(%s)"]
    params: list = [ctx.project_ids, ctx.region_ids]

    if vm_id:
        conditions.append("vm_id = %s")
        params.append(vm_id)
    if from_date:
        conditions.append("created_at >= %s")
        params.append(from_date)
    if to_date:
        conditions.append("created_at <= %s")
        params.append(to_date)

    params.append(limit)
    where_clause = " AND ".join(conditions)

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            cur.execute(
                f"""
                SELECT id, vm_id, vm_name, volume_id, volume_name,
                       project_id, project_name, policy_name,
                       size_gb, status, action, error_message,
                       created_at, deleted_at, retention_days, region_id
                FROM snapshot_records
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
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
                    COUNT(sr.id)                                                  AS total_runs,
                    COUNT(sr.id) FILTER (WHERE sr.status = 'success')            AS success_runs,
                    COUNT(sr.id) FILTER (WHERE sr.status = 'failed')             AS failed_runs,
                    MAX(sr.created_at) FILTER (WHERE sr.status = 'success')      AS last_success_at,
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
                        FILTER (WHERE sr.status = 'success'
                                  AND sr.created_at >= NOW() - INTERVAL '7 days') AS covered_7d
                FROM servers s
                LEFT JOIN snapshot_records sr ON sr.vm_id = s.id
                WHERE s.project_id = ANY(%s) AND s.region_id = ANY(%s)
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            cov_row = dict(cur.fetchone())

            # Active restore jobs
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM restore_jobs
                WHERE project_id = ANY(%s)
                  AND region_id  = ANY(%s)
                  AND status IN ('PLANNED', 'PENDING', 'RUNNING')
                """,
                (ctx.project_ids, ctx.region_ids),
            )
            active_restores = cur.fetchone()["cnt"]

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
                    details
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
                    (status = 'success') AS success,
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
                    r.category, r.risk_level, r.created_at, r.updated_at
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
            conn.commit()

    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)
