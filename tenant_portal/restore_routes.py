"""
restore_routes.py — P4 Tenant Portal self-service restore endpoints.

Security gates enforced before any OpenStack operation:
  1. VM/snapshot ownership verified via double-scoped DB query
     (project_id = ANY(token.project_ids) AND region_id = ANY(token.region_ids))
  2. RLS on restore_jobs via inject_rls_vars()
  3. REPLACE mode requires explicit VM-name confirmation on the frontend;
     safety_snapshot_before_replace is FORCED True for all tenant REPLACE jobs
  4. created_by = "tenant:<keystone_user_id>" on all jobs created here
  5. TENANT_RESTORE_ENABLED env var gate — 503 when false (default)
  6. Actual OpenStack execution delegated to admin API internal endpoint
     (tenant portal has no OpenStack credentials; keeps blast-radius isolated)

Endpoints:
  GET  /tenant/vms/{vm_id}/restore-points     — snapshots for a VM
  POST /tenant/restore/plan                   — create PLANNED job (via admin API)
  POST /tenant/restore/execute                — execute a PLANNED job (via admin API)
  GET  /tenant/restore/jobs                   — list restore jobs (owned)
  GET  /tenant/restore/jobs/{job_id}          — get job detail + steps
  POST /tenant/restore/jobs/{job_id}/cancel   — cancel own PLANNED/PENDING job
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from audit_helper import log_action
from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars
from tenant_context import TenantContext

logger = logging.getLogger("tenant_portal.restore")

router = APIRouter(tags=["restore"])

# ---------------------------------------------------------------------------
# Feature flag — restore is off by default until explicitly enabled
# ---------------------------------------------------------------------------
TENANT_RESTORE_ENABLED = os.getenv("TENANT_RESTORE_ENABLED", "false").lower() in (
    "true",
    "1",
    "yes",
)

# ---------------------------------------------------------------------------
# Admin API internal call settings
# ---------------------------------------------------------------------------
INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://pf9_api:8000")
INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

# ---------------------------------------------------------------------------
# Notification (P4c) — Slack/Teams alert when a tenant initiates a restore
# ---------------------------------------------------------------------------
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "")


def _notify_restore_initiated(
    username: str,
    vm_name: str,
    project_id: str,
    region_display: str,
    job_id: str,
) -> None:
    """Fire Slack/Teams ops alert when a tenant triggers restore execution.
    Best-effort — never raises.
    """
    text = (
        f":warning: *Tenant restore initiated*\n"
        f"• Tenant: `{username}`\n"
        f"• VM: `{vm_name}`\n"
        f"• Region: `{region_display}`\n"
        f"• Project: `{project_id}`\n"
        f"• Job ID: `{job_id}`"
    )
    headers = {"Content-Type": "application/json"}
    for url in (SLACK_WEBHOOK_URL, TEAMS_WEBHOOK_URL):
        if not url:
            continue
        try:
            payload = (
                {"text": text}
                if "hooks.slack.com" in url
                else {"text": text, "@type": "MessageCard"}
            )
            with httpx.Client(timeout=5.0) as client:
                client.post(url, json=payload, headers=headers)
        except Exception as exc:
            logger.warning("Restore notification failed (%s): %s", url[:60], exc)


# ---------------------------------------------------------------------------
# Internal admin API call helpers
# ---------------------------------------------------------------------------

def _call_admin_plan(
    vm_id: str,
    snapshot_id: str,
    project_id: str,
    region_id: str,
    created_by: str,
    new_vm_name: Optional[str],
    mode: str = "NEW",
    pre_restore_snapshot: bool = True,
    ip_strategy: str = "NEW_IPS",
    security_group_ids: Optional[list] = None,
    cleanup_old_storage: bool = False,
    delete_source_snapshot: bool = False,
) -> dict:
    """Call POST /internal/tenant-restore/plan on the admin API."""
    if not INTERNAL_SERVICE_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="restore_not_configured",
        )
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{INTERNAL_API_URL}/internal/tenant-restore/plan",
                json={
                    "vm_id": vm_id,
                    "snapshot_id": snapshot_id,
                    "project_id": project_id,
                    "region_id": region_id,
                    "created_by": created_by,
                    "new_vm_name": new_vm_name,
                    "mode": mode,
                    "pre_restore_snapshot": pre_restore_snapshot,
                    "ip_strategy": ip_strategy,
                    "security_group_ids": security_group_ids or [],
                    "cleanup_old_storage": cleanup_old_storage,
                    "delete_source_snapshot": delete_source_snapshot,
                },
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except httpx.HTTPError as exc:
        logger.error("Admin API call failed (plan): %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="restore_backend_unavailable",
        )
    if resp.status_code == 503:
        raise HTTPException(503, "restore_not_enabled_on_backend")
    if resp.status_code != 200:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise HTTPException(resp.status_code, body.get("detail", "plan_failed"))
    return resp.json()


def _call_admin_execute(plan_id: str, created_by: str) -> dict:
    """Call POST /internal/tenant-restore/execute on the admin API."""
    if not INTERNAL_SERVICE_SECRET:
        raise HTTPException(503, "restore_not_configured")
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                f"{INTERNAL_API_URL}/internal/tenant-restore/execute",
                json={"plan_id": plan_id, "created_by": created_by},
                headers={"X-Internal-Secret": INTERNAL_SERVICE_SECRET},
            )
    except httpx.HTTPError as exc:
        logger.error("Admin API call failed (execute): %s", exc)
        raise HTTPException(503, "restore_backend_unavailable")
    if resp.status_code != 200:
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        raise HTTPException(resp.status_code, body.get("detail", "execute_failed"))
    return resp.json()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class TenantRestorePlanRequest(BaseModel):
    vm_id: str = Field(..., description="UUID of the VM to restore")
    snapshot_id: str = Field(..., description="UUID of the snapshot to restore from")
    new_vm_name: Optional[str] = Field(
        None,
        description="Name for the restored VM (NEW mode) or confirmed VM name (REPLACE mode)",
    )
    mode: str = Field(
        "NEW",
        description="'NEW' creates a side-by-side copy; 'REPLACE' restores in-place (destructive)",
    )
    pre_restore_snapshot: bool = Field(
        True,
        description="Take a snapshot of the current VM before restore (recommended; mandatory for REPLACE)",
    )
    ip_strategy: str = Field(
        "NEW_IPS",
        description="IP allocation strategy: NEW_IPS (safest), TRY_SAME_IPS (best-effort), MANUAL_IP",
    )
    security_group_ids: Optional[list] = Field(
        None,
        description="Security group UUIDs to attach to the restored VM's ports (defaults to project default)",
    )
    cleanup_old_storage: bool = Field(
        False,
        description="Delete the original VM's orphaned root volume after a successful REPLACE restore",
    )
    delete_source_snapshot: bool = Field(
        False,
        description="Delete the source snapshot after a successful restore",
    )


class TenantRestoreExecuteRequest(BaseModel):
    plan_id: str = Field(..., description="UUID of the PLANNED restore job")


class TenantCancelRequest(BaseModel):
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------

def _check_vm_for_restore(cur, vm_id: str, ctx: TenantContext) -> dict:
    """Verify VM ownership (double-scoped). Returns VM row; 403 on mismatch."""
    cur.execute(
        """
        SELECT id, name, project_id, region_id, status
        FROM servers
        WHERE id = %s
          AND project_id = ANY(%s)
          AND region_id  = ANY(%s)
        """,
        (vm_id, ctx.project_ids, ctx.region_ids),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)


def _check_snapshot_for_restore(cur, snapshot_id: str, ctx: TenantContext) -> dict:
    """Verify snapshot ownership (double-scoped). Returns snapshot row; 403 on mismatch."""
    cur.execute(
        """
        SELECT id, name, project_id, region_id, volume_id, size_gb, status
        FROM snapshots
        WHERE id = %s
          AND project_id = ANY(%s)
          AND region_id  = ANY(%s)
        """,
        (snapshot_id, ctx.project_ids, ctx.region_ids),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)


def _check_job_ownership(cur, job_id: str, ctx: TenantContext) -> dict:
    """Return restore job for this tenant; 403 if not owned by this user."""
    inject_rls_vars(cur, ctx)
    expected_created_by = f"tenant:{ctx.keystone_user_id}"
    cur.execute(
        """
        SELECT id, project_id, vm_id, vm_name, status, mode,
               created_by, created_at, started_at, finished_at,
               failure_reason
        FROM restore_jobs
        WHERE id = %s
          AND project_id = ANY(%s)
          AND created_by = %s
        """,
        (job_id, ctx.project_ids, expected_created_by),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access_denied")
    return dict(row)


def _serialize_job(job: dict) -> dict:
    """Serialize a restore_jobs row for tenant API response (strip internal fields)."""
    out = {
        "job_id": str(job["id"]),
        "vm_id": job.get("vm_id"),
        "vm_name": job.get("vm_name"),
        "status": job.get("status"),
        "mode": job.get("mode"),
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
        "finished_at": job["finished_at"].isoformat() if job.get("finished_at") else None,
        "failure_reason": job.get("failure_reason"),
    }
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get(
    "/tenant/vms/{vm_id}/restore-points",
    summary="List restore points (snapshots) for a VM",
)
async def list_restore_points(
    vm_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Returns available restore points (snapshots of attached volumes) for a VM.
    VM ownership is double-scoped; 403 is returned if the VM is not in the
    tenant's project+region scope (never 404 — prevents existence guessing).
    """
    if not TENANT_RESTORE_ENABLED:
        raise HTTPException(503, "restore_disabled")

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            vm = _check_vm_for_restore(cur, vm_id, ctx)

            # Find volumes attached to this VM (JSONB attachments array)
            cur.execute(
                """
                SELECT v.id AS volume_id, v.name AS volume_name,
                       v.size_gb, v.bootable
                FROM volumes v
                WHERE v.project_id = ANY(%s)
                  AND v.region_id  = ANY(%s)
                  AND (
                      v.server_id = %s
                      OR (
                          v.raw_json->'attachments' IS NOT NULL
                          AND EXISTS (
                              SELECT 1
                              FROM jsonb_array_elements(v.raw_json->'attachments') elem
                              WHERE elem->>'server_id' = %s
                          )
                      )
                  )
                """,
                (ctx.project_ids, ctx.region_ids, vm_id, vm_id),
            )
            volumes = cur.fetchall()
            volume_ids = [v["volume_id"] for v in volumes]

            # Get snapshots for those volumes
            restore_points = []
            if volume_ids:
                cur.execute(
                    """
                    SELECT id, name, description, volume_id, size_gb, status,
                           created_at
                    FROM snapshots
                    WHERE volume_id = ANY(%s)
                      AND project_id = ANY(%s)
                      AND region_id  = ANY(%s)
                      AND status = 'available'
                    ORDER BY created_at DESC
                    """,
                    (volume_ids, ctx.project_ids, ctx.region_ids),
                )
                restore_points = cur.fetchall()

            log_action(
                cur, ctx, "tenant_view_restore_points",
                resource_type="vm",
                resource_id=vm_id,
            )

    return {
        "vm_id": vm_id,
        "vm_name": vm["name"],
        "volumes": [
            {"volume_id": v["volume_id"], "volume_name": v["volume_name"],
             "size_gb": v["size_gb"], "bootable": v["bootable"]}
            for v in volumes
        ],
        "restore_points": [
            {
                "id": rp["id"],
                "name": rp["name"],
                "description": rp.get("description"),
                "volume_id": rp["volume_id"],
                "size_gb": rp["size_gb"],
                "status": rp["status"],
                "created_at": rp["created_at"].isoformat() if rp.get("created_at") else None,
            }
            for rp in restore_points
        ],
    }


@router.post("/tenant/restore/plan", summary="Create a restore plan (mode=NEW only)")
async def create_restore_plan(
    req: TenantRestorePlanRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Validate VM + snapshot ownership, build a restore plan via the backend,
    and store it as a PLANNED job.  The plan does NOT start any execution;
    call /tenant/restore/execute to trigger the actual restore.

    Supports mode=NEW (side-by-side copy) and mode=REPLACE (destructive in-place).
    For REPLACE, the admin API forces safety_snapshot_before_replace=True so a
    recovery point is always taken before the original VM is deleted.
    """
    if not TENANT_RESTORE_ENABLED:
        raise HTTPException(503, "restore_disabled")

    # Validate mode
    mode = req.mode.upper() if req.mode.upper() in ("NEW", "REPLACE") else "NEW"

    created_by = f"tenant:{ctx.keystone_user_id}"

    # 1. Ownership checks (DB, double-scoped)
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            vm = _check_vm_for_restore(cur, req.vm_id, ctx)
            snap = _check_snapshot_for_restore(cur, req.snapshot_id, ctx)

            # Verify the snapshot belongs to the same project as the VM
            if snap["project_id"] != vm["project_id"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="snapshot_project_mismatch",
                )

            log_action(
                cur, ctx, "tenant_restore_plan",
                resource_type="vm",
                resource_id=req.vm_id,
                project_id=vm["project_id"],
                region_id=vm["region_id"],
                details={"snapshot_id": req.snapshot_id, "mode": mode},
            )

    # 2. Call admin API to build the full plan (OpenStack quota check, etc.)
    plan = _call_admin_plan(
        vm_id=req.vm_id,
        snapshot_id=req.snapshot_id,
        project_id=vm["project_id"],
        region_id=vm["region_id"],
        created_by=created_by,
        new_vm_name=req.new_vm_name,
        mode=mode,
        pre_restore_snapshot=req.pre_restore_snapshot,
        ip_strategy=req.ip_strategy if req.ip_strategy in ("NEW_IPS", "TRY_SAME_IPS") else "NEW_IPS",
        security_group_ids=req.security_group_ids or [],
        cleanup_old_storage=req.cleanup_old_storage if mode == "REPLACE" else False,
        delete_source_snapshot=req.delete_source_snapshot,
    )

    # 3. Strip internal fields before returning to tenant
    return {
        "plan_id": plan.get("job_id") or plan.get("plan_id"),
        "vm": {
            "id": plan.get("vm", {}).get("id"),
            "name": plan.get("vm", {}).get("name"),
            "status": plan.get("vm", {}).get("status"),
        },
        "restore_point": {
            "id": plan.get("restore_point", {}).get("id"),
            "name": plan.get("restore_point", {}).get("name"),
            "created_at": plan.get("restore_point", {}).get("created_at"),
            "size_gb": plan.get("restore_point", {}).get("size_gb"),
        },
        "mode": mode,
        "safety_snapshot": True if mode == "REPLACE" else req.pre_restore_snapshot,
        "new_vm_name": plan.get("new_vm_name"),
        "eligible": plan.get("eligible", True),
        "warnings": plan.get("warnings", []),
    }


@router.post(
    "/tenant/restore/execute",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Execute a PLANNED restore job",
)
async def execute_restore(
    req: TenantRestoreExecuteRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Transition a PLANNED job to PENDING and start execution.
    The tenant MUST own the plan (created_by == tenant:<their_user_id>).
    Fires Slack/Teams ops alert if webhooks are configured.
    """
    if not TENANT_RESTORE_ENABLED:
        raise HTTPException(503, "restore_disabled")

    created_by = f"tenant:{ctx.keystone_user_id}"

    # Verify ownership of the plan before calling the backend
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            job = _check_job_ownership(cur, req.plan_id, ctx)

            if job["status"] != "PLANNED":
                raise HTTPException(
                    400,
                    f"Job is in status '{job['status']}' — only PLANNED jobs can be executed",
                )

            log_action(
                cur, ctx, "tenant_restore_execute",
                resource_type="restore_job",
                resource_id=req.plan_id,
                project_id=job.get("project_id"),
                region_id=job.get("region_id"),
                details={"vm_id": job.get("vm_id"), "vm_name": job.get("vm_name")},
            )

    # Notify ops team (P4c)
    region_id = job.get("region_id", "")
    _notify_restore_initiated(
        username=ctx.username,
        vm_name=job.get("vm_name", req.plan_id),
        project_id=job.get("project_id", ""),
        region_display=region_id,
        job_id=req.plan_id,
    )

    # Delegate execution to admin API
    result = _call_admin_execute(plan_id=req.plan_id, created_by=created_by)

    return {
        "job_id": result.get("job_id", req.plan_id),
        "status": result.get("status", "PENDING"),
        "message": "Restore execution started. Poll /tenant/restore/jobs/{job_id} for progress.",
    }


@router.get("/tenant/restore/jobs", summary="List your restore jobs")
async def list_restore_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List restore jobs created by this tenant user, double-scoped."""
    created_by = f"tenant:{ctx.keystone_user_id}"

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)

            query = """
                SELECT id, project_id, vm_id, vm_name, status, mode,
                       created_by, created_at, started_at, finished_at,
                       failure_reason
                FROM restore_jobs
                WHERE project_id = ANY(%s)
                  AND created_by = %s
            """
            params = [ctx.project_ids, created_by]

            if status_filter:
                query += " AND status = %s"
                params.append(status_filter.upper())

            query += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            jobs = cur.fetchall()

            log_action(cur, ctx, "tenant_view_restore_jobs")

    return {
        "jobs": [_serialize_job(dict(j)) for j in jobs],
        "total": len(jobs),
    }


@router.get(
    "/tenant/restore/jobs/{job_id}",
    summary="Get restore job detail",
)
async def get_restore_job(
    job_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Get full restore job including step progress. 403 if not owned by this tenant."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            job = _check_job_ownership(cur, job_id, ctx)

            # Load step records from restore_job_steps
            cur.execute(
                """
                SELECT step_order, step_name, status, started_at, finished_at
                FROM restore_job_steps
                WHERE job_id = %s
                ORDER BY step_order
                """,
                (job_id,),
            )
            steps = cur.fetchall()

            log_action(
                cur, ctx, "tenant_view_restore_job_detail",
                resource_type="restore_job",
                resource_id=job_id,
            )

    serialized = _serialize_job(job)

    # Add step progress (no internal details exposed)
    total = len(steps)
    done = sum(1 for s in steps if s["status"] in ("SUCCEEDED", "SKIPPED"))
    current = next((s["step_name"] for s in steps if s["status"] == "RUNNING"), None)

    serialized["steps"] = [
        {
            "order": s["step_order"],
            "name": s["step_name"],
            "status": s["status"],
            "started_at": s["started_at"].isoformat() if s.get("started_at") else None,
            "finished_at": s["finished_at"].isoformat() if s.get("finished_at") else None,
        }
        for s in steps
    ]
    serialized["progress"] = {
        "total_steps": total,
        "completed_steps": done,
        "current_step": current,
        "percent": round(done / total * 100) if total > 0 else 0,
    }

    return serialized


@router.post(
    "/tenant/restore/jobs/{job_id}/cancel",
    status_code=status.HTTP_200_OK,
    summary="Cancel a PLANNED or PENDING restore job",
)
async def cancel_restore_job(
    job_id: str,
    req: TenantCancelRequest = None,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Cancel a restore job owned by this tenant.  Only PLANNED and PENDING
    jobs can be canceled — RUNNING jobs are best-effort (the DB row is
    updated; the running async task in the admin API will notice on the
    next step check).
    """
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, ctx)
            job = _check_job_ownership(cur, job_id, ctx)

            if job["status"] not in ("PLANNED", "PENDING", "RUNNING"):
                raise HTTPException(
                    400,
                    f"Cannot cancel job in status '{job['status']}'",
                )

            reason = (req.reason if req else None) or "Canceled by tenant"
            cur.execute(
                """
                UPDATE restore_jobs
                SET status='CANCELED',
                    canceled_at = now(),
                    failure_reason = %s
                WHERE id = %s
                """,
                (f"Canceled by {ctx.username}: {reason}", job_id),
            )

            log_action(
                cur, ctx, "tenant_restore_cancel",
                resource_type="restore_job",
                resource_id=job_id,
                details={"reason": reason, "vm_name": job.get("vm_name")},
            )

    return {
        "job_id": job_id,
        "status": "CANCELED",
        "message": "Cancellation requested.",
    }
