"""
Migration Planner API  —  Phase 1
==================================
CRUD for migration projects, RVTools XLSX upload/parse, tenant detection,
VM listing, risk scoring, project lifecycle management.

Routes:
  POST   /api/migration/projects              Create project
  GET    /api/migration/projects              List projects
  GET    /api/migration/projects/{id}         Get project detail
  PATCH  /api/migration/projects/{id}         Update project settings
  DELETE /api/migration/projects/{id}         Delete project (cascade)
  POST   /api/migration/projects/{id}/archive Archive + purge

  POST   /api/migration/projects/{id}/upload  Upload RVTools XLSX
  POST   /api/migration/projects/{id}/reparse Re-parse from stored data

  GET    /api/migration/projects/{id}/vms     List VMs (filters, sort, pagination)
  PATCH  /api/migration/projects/{id}/vms/{vm_id}  Update VM overrides

  GET    /api/migration/projects/{id}/tenants       Detected tenants
  PATCH  /api/migration/projects/{id}/tenants/{tid} Confirm/edit tenant

  GET    /api/migration/projects/{id}/hosts         Source hosts
  GET    /api/migration/projects/{id}/clusters       Source clusters
  GET    /api/migration/projects/{id}/stats          Summary stats

  POST   /api/migration/projects/{id}/assess        Run risk + mode scoring
  GET    /api/migration/projects/{id}/risk-config    Get risk rules
  PUT    /api/migration/projects/{id}/risk-config    Update risk rules

  POST   /api/migration/projects/{id}/reset-assessment  Clear computed results
  POST   /api/migration/projects/{id}/reset-plan        Clear wave/prep data

  POST   /api/migration/projects/{id}/approve       Approve project (gate)

  GET    /api/migration/projects/{id}/bandwidth      Bandwidth model
  GET    /api/migration/projects/{id}/agent-recommendation  Agent sizing
"""

import os
import io
import json
import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from fastapi import APIRouter, HTTPException, Depends, Query, Request, UploadFile, File
from pydantic import BaseModel, validator

from auth import require_permission, get_current_user

from migration_engine import (
    build_column_map,
    extract_row,
    classify_os_family,
    assign_tenant,
    compute_risk,
    classify_migration_mode,
    compute_bandwidth_model,
    recommend_agent_sizing,
    estimate_vm_time,
    generate_migration_plan,
    summarize_rvtools_stats,
    COLUMN_ALIASES,
)

logger = logging.getLogger("migration_planner")

router = APIRouter(prefix="/api/migration", tags=["migration"])

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _get_conn():
    from db_pool import get_connection
    return get_connection()


def _ensure_tables():
    """Run migration if tables don't exist yet."""
    from db_pool import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'migration_projects'
                )
            """)
            if not cur.fetchone()[0]:
                migration = os.path.join(
                    os.path.dirname(__file__), "..", "db", "migrate_migration_planner.sql"
                )
                if os.path.exists(migration):
                    with open(migration) as f:
                        cur.execute(f.read())
                    conn.commit()
                    logger.info("Migration planner tables created")


def _ensure_activity_log_table():
    from db_pool import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'activity_log'
                )
            """)
            if not cur.fetchone()[0]:
                migration = os.path.join(
                    os.path.dirname(__file__), "..", "db", "migrate_activity_log.sql"
                )
                if os.path.exists(migration):
                    with open(migration) as f:
                        cur.execute(f.read())
                    conn.commit()


# Run on import
try:
    _ensure_tables()
except Exception as e:
    logger.warning(f"Could not ensure migration tables on startup: {e}")

try:
    _ensure_activity_log_table()
except Exception as e:
    logger.warning(f"Could not ensure activity_log table: {e}")


# ---------------------------------------------------------------------------
# Activity log helper
# ---------------------------------------------------------------------------
def _log_activity(
    actor: str, action: str, resource_type: str,
    resource_id: str = None, resource_name: str = None,
    details: dict = None, result: str = "success", error_message: str = None,
):
    try:
        from db_pool import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO activity_log
                        (actor, action, resource_type, resource_id, resource_name,
                         details, result, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (actor, action, resource_type, resource_id, resource_name,
                      Json(details or {}), result, error_message))
    except Exception as e:
        logger.error(f"Failed to write activity log: {e}")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    topology_type: Optional[str] = "local"
    # Source side
    source_nic_speed_gbps: Optional[float] = 10.0
    source_usable_pct: Optional[float] = 40.0
    # Transport link
    link_speed_gbps: Optional[float] = None
    link_usable_pct: Optional[float] = 60.0
    source_upload_mbps: Optional[float] = None
    dest_download_mbps: Optional[float] = None
    estimated_rtt_ms: Optional[float] = None
    rtt_category: Optional[str] = None
    # PCD / Agent side
    target_ingress_speed_gbps: Optional[float] = 10.0
    target_usable_pct: Optional[float] = 40.0
    pcd_storage_write_mbps: Optional[float] = 500.0
    # Agent profile
    agent_count: Optional[int] = 2
    agent_concurrent_vms: Optional[int] = 5
    agent_vcpu_per_slot: Optional[int] = 2
    agent_ram_base_gb: Optional[float] = 2.0
    agent_ram_per_slot_gb: Optional[float] = 1.0
    agent_nic_speed_gbps: Optional[float] = 10.0
    agent_nic_usable_pct: Optional[float] = 70.0
    agent_disk_buffer_factor: Optional[float] = 1.2
    # Warm migration
    daily_change_rate_pct: Optional[float] = 5.0

    @validator("name")
    def name_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("Project name cannot be empty")
        return v.strip()

    @validator("topology_type")
    def valid_topology(cls, v):
        allowed = ("local", "cross_site_dedicated", "cross_site_internet")
        if v and v not in allowed:
            raise ValueError(f"topology must be one of {allowed}")
        return v


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    topology_type: Optional[str] = None
    source_nic_speed_gbps: Optional[float] = None
    source_usable_pct: Optional[float] = None
    link_speed_gbps: Optional[float] = None
    link_usable_pct: Optional[float] = None
    source_upload_mbps: Optional[float] = None
    dest_download_mbps: Optional[float] = None
    estimated_rtt_ms: Optional[float] = None
    rtt_category: Optional[str] = None
    target_ingress_speed_gbps: Optional[float] = None
    target_usable_pct: Optional[float] = None
    pcd_storage_write_mbps: Optional[float] = None
    agent_count: Optional[int] = None
    agent_concurrent_vms: Optional[int] = None
    agent_vcpu_per_slot: Optional[int] = None
    agent_ram_base_gb: Optional[float] = None
    agent_ram_per_slot_gb: Optional[float] = None
    agent_nic_speed_gbps: Optional[float] = None
    agent_nic_usable_pct: Optional[float] = None
    agent_disk_buffer_factor: Optional[float] = None
    daily_change_rate_pct: Optional[float] = None
    migration_duration_days: Optional[int] = None
    working_hours_per_day: Optional[float] = None
    working_days_per_week: Optional[int] = None
    target_vms_per_day: Optional[int] = None


class UpdateVMRequest(BaseModel):
    exclude_from_migration: Optional[bool] = None
    exclude_reason: Optional[str] = None
    manual_mode_override: Optional[str] = None
    priority: Optional[int] = None
    tenant_name: Optional[str] = None
    app_group: Optional[str] = None


class UpdateTenantRequest(BaseModel):
    tenant_name: Optional[str] = None
    org_vdc: Optional[str] = None
    confirmed: Optional[bool] = None
    target_domain: Optional[str] = None
    target_project: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper: get project or 404
# ---------------------------------------------------------------------------
def _get_project(project_id: str, conn) -> Dict[str, Any]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM migration_projects WHERE project_id = %s", (project_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Migration project not found")
        return dict(row)


# =====================================================================
# PROJECT CRUD
# =====================================================================

@router.post("/projects", dependencies=[Depends(require_permission("migration", "write"))])
async def create_project(req: CreateProjectRequest, user = Depends(get_current_user)):
    """Create a new migration project."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO migration_projects (
                    name, description, topology_type,
                    source_nic_speed_gbps, source_usable_pct,
                    link_speed_gbps, link_usable_pct,
                    source_upload_mbps, dest_download_mbps,
                    estimated_rtt_ms, rtt_category,
                    target_ingress_speed_gbps, target_usable_pct,
                    pcd_storage_write_mbps,
                    agent_count, agent_concurrent_vms,
                    agent_vcpu_per_slot, agent_ram_base_gb, agent_ram_per_slot_gb,
                    agent_nic_speed_gbps, agent_nic_usable_pct, agent_disk_buffer_factor,
                    daily_change_rate_pct,
                    created_by
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s
                )
                RETURNING *
            """, (
                req.name, req.description, req.topology_type,
                req.source_nic_speed_gbps, req.source_usable_pct,
                req.link_speed_gbps, req.link_usable_pct,
                req.source_upload_mbps, req.dest_download_mbps,
                req.estimated_rtt_ms, req.rtt_category,
                req.target_ingress_speed_gbps, req.target_usable_pct,
                req.pcd_storage_write_mbps,
                req.agent_count, req.agent_concurrent_vms,
                req.agent_vcpu_per_slot, req.agent_ram_base_gb, req.agent_ram_per_slot_gb,
                req.agent_nic_speed_gbps, req.agent_nic_usable_pct, req.agent_disk_buffer_factor,
                req.daily_change_rate_pct,
                actor,
            ))
            project = dict(cur.fetchone())

            # Seed default risk config
            cur.execute("""
                INSERT INTO migration_risk_config (project_id) VALUES (%s)
            """, (project["project_id"],))

            # Seed default tenant detection rules
            cur.execute("""
                INSERT INTO migration_tenant_rules (project_id) VALUES (%s)
            """, (project["project_id"],))

            conn.commit()

    _log_activity(actor=actor, action="create", resource_type="migration_project",
                  resource_id=project["project_id"], resource_name=req.name)

    return {"status": "ok", "project": _serialize_project(project)}


@router.get("/projects", dependencies=[Depends(require_permission("migration", "read"))])
async def list_projects(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List migration projects with optional status filter."""
    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = "WHERE 1=1"
            params: list = []
            if status:
                where += " AND status = %s"
                params.append(status)

            cur.execute(f"""
                SELECT mp.*,
                       (SELECT count(*) FROM migration_vms mv WHERE mv.project_id = mp.project_id) as vm_count,
                       (SELECT count(*) FROM migration_tenants mt WHERE mt.project_id = mp.project_id) as tenant_count
                FROM migration_projects mp
                {where}
                ORDER BY mp.created_at DESC
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            projects = [dict(r) for r in cur.fetchall()]

            cur.execute(f"SELECT count(*) as cnt FROM migration_projects {where}", params)
            total = cur.fetchone()["cnt"]

    return {"status": "ok", "total": total, "projects": [_serialize_project(p) for p in projects]}


@router.get("/projects/{project_id}", dependencies=[Depends(require_permission("migration", "read"))])
async def get_project(project_id: str):
    """Get detailed project info."""
    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # VM counts by risk
            cur.execute("""
                SELECT risk_category, count(*) as cnt
                FROM migration_vms WHERE project_id = %s AND NOT exclude_from_migration
                GROUP BY risk_category
            """, (project_id,))
            risk_summary = {r["risk_category"]: r["cnt"] for r in cur.fetchall() if r["risk_category"]}

            # VM counts by mode
            cur.execute("""
                SELECT migration_mode, count(*) as cnt
                FROM migration_vms WHERE project_id = %s AND NOT exclude_from_migration
                GROUP BY migration_mode
            """, (project_id,))
            mode_summary = {r["migration_mode"]: r["cnt"] for r in cur.fetchall() if r["migration_mode"]}

            # Totals
            cur.execute("""
                SELECT count(*) as total_vms,
                       coalesce(sum(total_disk_gb), 0) as total_disk_gb,
                       coalesce(sum(ram_mb), 0) as total_ram_mb,
                       coalesce(sum(cpu_count), 0) as total_vcpu,
                       count(*) FILTER (WHERE exclude_from_migration) as excluded_vms
                FROM migration_vms WHERE project_id = %s
            """, (project_id,))
            totals = dict(cur.fetchone())

            # Tenant count
            cur.execute("SELECT count(*) as cnt FROM migration_tenants WHERE project_id = %s", (project_id,))
            totals["tenant_count"] = cur.fetchone()["cnt"]

    result = _serialize_project(project)
    result["risk_summary"] = risk_summary
    result["mode_summary"] = mode_summary
    result["totals"] = _serialize_row(totals)
    return {"status": "ok", "project": result}


@router.patch("/projects/{project_id}", dependencies=[Depends(require_permission("migration", "write"))])
async def update_project(project_id: str, req: UpdateProjectRequest, user = Depends(get_current_user)):
    """Update project settings (topology, bandwidth, agents)."""
    actor = user.username if user else "system"

    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = []
    params = []
    for key, val in updates.items():
        set_clauses.append(f"{key} = %s")
        params.append(val)
    set_clauses.append("updated_at = now()")

    with _get_conn() as conn:
        _get_project(project_id, conn)  # 404 check
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                UPDATE migration_projects
                SET {', '.join(set_clauses)}
                WHERE project_id = %s
                RETURNING *
            """, params + [project_id])
            project = dict(cur.fetchone())
            conn.commit()

    _log_activity(actor=actor, action="update", resource_type="migration_project",
                  resource_id=project_id, details=updates)

    return {"status": "ok", "project": _serialize_project(project)}


@router.delete("/projects/{project_id}", dependencies=[Depends(require_permission("migration", "admin"))])
async def delete_project(project_id: str, user = Depends(get_current_user)):
    """Delete a migration project and all associated data (CASCADE)."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM migration_projects WHERE project_id = %s", (project_id,))
            conn.commit()

    _log_activity(actor=actor, action="delete", resource_type="migration_project",
                  resource_id=project_id, resource_name=project["name"])

    return {"status": "ok", "message": f"Project '{project['name']}' and all data deleted"}


@router.post("/projects/{project_id}/archive", dependencies=[Depends(require_permission("migration", "admin"))])
async def archive_project(project_id: str, user = Depends(get_current_user)):
    """Archive project summary then purge full data."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Build summary
            cur.execute("""
                SELECT count(*) as total_vms,
                       coalesce(sum(total_disk_gb), 0) as total_disk_gb,
                       count(*) FILTER (WHERE risk_category = 'GREEN') as green,
                       count(*) FILTER (WHERE risk_category = 'YELLOW') as yellow,
                       count(*) FILTER (WHERE risk_category = 'RED') as red
                FROM migration_vms WHERE project_id = %s
            """, (project_id,))
            vm_stats = dict(cur.fetchone())

            cur.execute("SELECT count(*) as cnt FROM migration_tenants WHERE project_id = %s", (project_id,))
            tenant_count = cur.fetchone()["cnt"]

            summary = {
                "name": project["name"],
                "status_at_archive": project["status"],
                "topology_type": project["topology_type"],
                "vm_count": vm_stats["total_vms"],
                "total_disk_tb": round(float(vm_stats["total_disk_gb"]) / 1024, 2),
                "tenant_count": tenant_count,
                "risk_green": vm_stats["green"],
                "risk_yellow": vm_stats["yellow"],
                "risk_red": vm_stats["red"],
                "created_at": project["created_at"].isoformat() if project["created_at"] else None,
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }

            cur.execute("""
                INSERT INTO migration_project_archives (original_project_id, name, summary, archived_by)
                VALUES (%s, %s, %s, %s)
            """, (project_id, project["name"], Json(summary), actor))

            cur.execute("DELETE FROM migration_projects WHERE project_id = %s", (project_id,))
            conn.commit()

    _log_activity(actor=actor, action="archive", resource_type="migration_project",
                  resource_id=project_id, resource_name=project["name"], details=summary)

    return {"status": "ok", "message": f"Project archived and data purged", "summary": summary}


# =====================================================================
# RVTOOLS UPLOAD & PARSE
# =====================================================================

@router.post("/projects/{project_id}/upload", dependencies=[Depends(require_permission("migration", "write"))])
async def upload_rvtools(project_id: str, file: UploadFile = File(...), user = Depends(get_current_user)):
    """Upload and parse an RVTools XLSX file."""
    actor = user.username if user else "system"

    if not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files accepted")

    # Read file into memory
    contents = await file.read()
    if len(contents) > 100 * 1024 * 1024:  # 100 MB limit
        raise HTTPException(status_code=400, detail="File too large (max 100 MB)")

    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        if project["status"] not in ("draft", "assessment"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot upload RVTools in status '{project['status']}'. Reset to draft first."
            )

        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Cannot read XLSX: {exc}")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Clear existing data for re-import
            for table in (
                "migration_wave_vms", "migration_waves", "migration_prep_tasks",
                "migration_target_gaps", "migration_vm_snapshots", "migration_vm_nics",
                "migration_vm_disks", "migration_vms", "migration_hosts",
                "migration_clusters", "migration_tenants",
            ):
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))

            # ----- Parse vHost -----
            vhost_count = 0
            if "vHost" in wb.sheetnames:
                vhost_count = _parse_vhost_sheet(wb["vHost"], project_id, cur)

            # ----- Parse vCluster -----
            vcluster_count = 0
            if "vCluster" in wb.sheetnames:
                vcluster_count = _parse_vcluster_sheet(wb["vCluster"], project_id, cur)

            # ----- Parse vInfo (main) -----
            vinfo_count = 0
            if "vInfo" in wb.sheetnames:
                vinfo_count = _parse_vinfo_sheet(wb["vInfo"], project_id, cur)
            else:
                raise HTTPException(status_code=400, detail="vInfo sheet not found in XLSX")

            # ----- Parse vDisk -----
            vdisk_count = 0
            if "vDisk" in wb.sheetnames:
                vdisk_count = _parse_vdisk_sheet(wb["vDisk"], project_id, cur)

            # ----- Parse vNIC -----
            vnic_count = 0
            if "vNetwork" in wb.sheetnames:
                vnic_count = _parse_vnic_sheet(wb["vNetwork"], project_id, cur)
            elif "vNIC" in wb.sheetnames:
                vnic_count = _parse_vnic_sheet(wb["vNIC"], project_id, cur)

            # ----- Parse vSnapshot -----
            vsnapshot_count = 0
            if "vSnapshot" in wb.sheetnames:
                vsnapshot_count = _parse_vsnapshot_sheet(wb["vSnapshot"], project_id, cur)

            # Update disk/nic/snapshot summaries on VMs
            _update_vm_summaries(project_id, cur)

            # Run tenant detection
            _run_tenant_detection(project_id, cur)

            # ---- Collect enriched stats from DB ----
            # Power state breakdown
            cur.execute("""
                SELECT coalesce(lower(power_state), 'unknown') as state, count(*) as cnt
                FROM migration_vms WHERE project_id = %s AND (template IS NOT TRUE)
                GROUP BY coalesce(lower(power_state), 'unknown')
            """, (project_id,))
            power_state_counts = {r["state"]: r["cnt"] for r in cur.fetchall()}

            # OS family breakdown
            cur.execute("""
                SELECT coalesce(os_family, 'unknown') as family, count(*) as cnt
                FROM migration_vms WHERE project_id = %s AND (template IS NOT TRUE)
                GROUP BY coalesce(os_family, 'unknown')
            """, (project_id,))
            os_family_counts = {r["family"]: r["cnt"] for r in cur.fetchall()}

            # Tenant count
            cur.execute("""
                SELECT count(*) as cnt FROM migration_tenants WHERE project_id = %s
            """, (project_id,))
            tenant_count = cur.fetchone()["cnt"]

            # Template count
            cur.execute("""
                SELECT count(*) as cnt FROM migration_vms
                WHERE project_id = %s AND template IS TRUE
            """, (project_id,))
            template_count = cur.fetchone()["cnt"]

            # Detect if vCD environment (any tenant detected via vcd_folder or vapp_name with org_vdc)
            cur.execute("""
                SELECT count(*) as cnt FROM migration_tenants
                WHERE project_id = %s AND detection_method IN ('vcd_folder', 'vapp_name')
                  AND org_vdc IS NOT NULL
            """, (project_id,))
            vcd_detected = cur.fetchone()["cnt"] > 0

            # Update project metadata
            stats = summarize_rvtools_stats(
                vinfo_count, vdisk_count, vnic_count, vhost_count, vcluster_count, vsnapshot_count,
                power_state_counts=power_state_counts,
                os_family_counts=os_family_counts,
                tenant_count=tenant_count,
                vcd_detected=vcd_detected,
                template_count=template_count,
            )
            cur.execute("""
                UPDATE migration_projects
                SET rvtools_filename = %s,
                    rvtools_uploaded_at = now(),
                    rvtools_sheet_stats = %s,
                    status = CASE WHEN status = 'draft' THEN 'assessment' ELSE status END,
                    updated_at = now()
                WHERE project_id = %s
            """, (file.filename, Json(stats), project_id))

            conn.commit()

        wb.close()

    _log_activity(actor=actor, action="upload_rvtools", resource_type="migration_project",
                  resource_id=project_id, details={"filename": file.filename, "stats": stats})

    return {
        "status": "ok",
        "message": f"Parsed {file.filename}",
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Clear uploaded RVTools data (keep project settings)
# ---------------------------------------------------------------------------

@router.delete("/projects/{project_id}/rvtools",
               dependencies=[Depends(require_permission("migration", "write"))])
async def clear_rvtools_data(project_id: str, user = Depends(get_current_user)):
    """Delete all uploaded RVTools data for a project (VMs, disks, NICs, etc.)
    while preserving the project itself and its settings."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor() as cur:
            for table in (
                "migration_wave_vms", "migration_waves", "migration_prep_tasks",
                "migration_target_gaps", "migration_vm_snapshots", "migration_vm_nics",
                "migration_vm_disks", "migration_vms", "migration_hosts",
                "migration_clusters", "migration_tenants",
            ):
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))

            cur.execute("""
                UPDATE migration_projects SET
                    rvtools_filename = NULL,
                    rvtools_uploaded_at = NULL,
                    rvtools_sheet_stats = '{}',
                    status = 'draft',
                    updated_at = now()
                WHERE project_id = %s
            """, (project_id,))
            conn.commit()

    _log_activity(actor=actor, action="clear_rvtools", resource_type="migration_project",
                  resource_id=project_id, resource_name=project["name"])

    return {"status": "ok", "message": "All RVTools data cleared. Project reset to draft."}


# ---------------------------------------------------------------------------
# Sheet parsers
# ---------------------------------------------------------------------------

def _sheet_headers(sheet) -> List[str]:
    """Extract header row from an openpyxl sheet."""
    for row in sheet.iter_rows(min_row=1, max_row=1, values_only=True):
        return [str(c) if c else "" for c in row]
    return []


def _sheet_rows(sheet) -> List[list]:
    """All data rows (skip header)."""
    rows = []
    for i, row in enumerate(sheet.iter_rows(values_only=True)):
        if i == 0:
            continue
        rows.append(list(row))
    return rows


def _safe_int(val, default=0) -> int:
    if val is None or val == "":
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _safe_bool(val) -> Optional[bool]:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "yes", "1", "enabled")


def _safe_str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _parse_vinfo_sheet(sheet, project_id: str, cur) -> int:
    headers = _sheet_headers(sheet)
    col_map = build_column_map(headers)
    rows = _sheet_rows(sheet)
    count = 0

    for row_vals in rows:
        d = extract_row(row_vals, col_map)
        vm_name = _safe_str(d.get("vm_name"))
        if not vm_name:
            continue

        guest_os = _safe_str(d.get("guest_os"))
        guest_os_tools = _safe_str(d.get("guest_os_tools"))
        os_family = classify_os_family(guest_os, guest_os_tools)

        # Disk sizes from vInfo (rough — refined after vDisk parse)
        prov_mb = _safe_float(d.get("provisioned_mb"))
        in_use_raw = _safe_float(d.get("in_use_mb"))
        total_disk_gb = round(prov_mb / 1024, 2) if prov_mb else 0

        cur.execute("""
            INSERT INTO migration_vms (
                project_id, vm_name, power_state, template,
                guest_os, guest_os_tools, os_family,
                folder_path, resource_pool, vapp_name, annotation,
                cpu_count, ram_mb, total_disk_gb,
                provisioned_mb, in_use_mb,
                host_name, cluster, datacenter,
                vm_uuid, firmware, change_tracking, connection_state,
                dns_name, primary_ip,
                raw_data
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s
            )
            ON CONFLICT (project_id, vm_name) DO UPDATE SET
                power_state = EXCLUDED.power_state,
                template = EXCLUDED.template,
                guest_os = EXCLUDED.guest_os,
                guest_os_tools = EXCLUDED.guest_os_tools,
                os_family = EXCLUDED.os_family,
                folder_path = EXCLUDED.folder_path,
                resource_pool = EXCLUDED.resource_pool,
                vapp_name = EXCLUDED.vapp_name,
                annotation = EXCLUDED.annotation,
                cpu_count = EXCLUDED.cpu_count,
                ram_mb = EXCLUDED.ram_mb,
                total_disk_gb = EXCLUDED.total_disk_gb,
                provisioned_mb = EXCLUDED.provisioned_mb,
                in_use_mb = EXCLUDED.in_use_mb,
                host_name = EXCLUDED.host_name,
                cluster = EXCLUDED.cluster,
                datacenter = EXCLUDED.datacenter,
                vm_uuid = EXCLUDED.vm_uuid,
                firmware = EXCLUDED.firmware,
                change_tracking = EXCLUDED.change_tracking,
                connection_state = EXCLUDED.connection_state,
                dns_name = EXCLUDED.dns_name,
                primary_ip = EXCLUDED.primary_ip,
                raw_data = EXCLUDED.raw_data,
                updated_at = now()
        """, (
            project_id, vm_name,
            _safe_str(d.get("power_state")),
            _safe_bool(d.get("template")),
            guest_os, guest_os_tools, os_family,
            _safe_str(d.get("folder_path")),
            _safe_str(d.get("resource_pool")),
            _safe_str(d.get("vapp_name")),
            _safe_str(d.get("annotation")),
            _safe_int(d.get("cpu_count")),
            _safe_int(d.get("ram_mb")),
            total_disk_gb,
            _safe_int(prov_mb),
            _safe_int(in_use_raw),
            _safe_str(d.get("host_name")),
            _safe_str(d.get("cluster")),
            _safe_str(d.get("datacenter")),
            _safe_str(d.get("vm_uuid")),
            _safe_str(d.get("firmware")),
            _safe_bool(d.get("change_tracking")),
            _safe_str(d.get("connection_state")),
            _safe_str(d.get("dns_name")),
            _safe_str(d.get("primary_ip")),
            Json({k: str(v) if v is not None else "" for k, v in d.items()}),
        ))
        count += 1

    return count


def _parse_vdisk_sheet(sheet, project_id: str, cur) -> int:
    headers = _sheet_headers(sheet)
    col_map = build_column_map(headers, prefix="disk_")
    rows = _sheet_rows(sheet)
    count = 0

    for row_vals in rows:
        d = extract_row(row_vals, col_map)
        vm_name = _safe_str(d.get("disk_vm_name") or d.get("vm_name"))
        if not vm_name:
            continue

        cap_mb = _safe_float(d.get("capacity_mb"))
        cap_gb = round(cap_mb / 1024, 2) if cap_mb else 0

        cur.execute("""
            INSERT INTO migration_vm_disks (
                project_id, vm_name, disk_label, disk_path,
                capacity_gb, thin_provisioned, eagerly_scrub, datastore,
                raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            project_id, vm_name,
            _safe_str(d.get("disk_label")),
            _safe_str(d.get("disk_path")),
            cap_gb,
            _safe_bool(d.get("thin")),
            _safe_bool(d.get("eagerly_scrub")),
            _safe_str(d.get("datastore")),
            Json({k: str(v) if v is not None else "" for k, v in d.items()}),
        ))
        count += 1

    return count


def _parse_vnic_sheet(sheet, project_id: str, cur) -> int:
    headers = _sheet_headers(sheet)
    col_map = build_column_map(headers, prefix="nic_")
    rows = _sheet_rows(sheet)
    count = 0

    for row_vals in rows:
        d = extract_row(row_vals, col_map)
        vm_name = _safe_str(d.get("nic_vm_name") or d.get("vm_name"))
        if not vm_name:
            continue

        cur.execute("""
            INSERT INTO migration_vm_nics (
                project_id, vm_name, nic_label, adapter_type,
                network_name, connected, mac_address, ip_address,
                raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            project_id, vm_name,
            _safe_str(d.get("nic_label")),
            _safe_str(d.get("adapter_type")),
            _safe_str(d.get("network_name")),
            _safe_bool(d.get("nic_connected")),
            _safe_str(d.get("mac_address")),
            _safe_str(d.get("ip_address")),
            Json({k: str(v) if v is not None else "" for k, v in d.items()}),
        ))
        count += 1

    return count


def _parse_vhost_sheet(sheet, project_id: str, cur) -> int:
    headers = _sheet_headers(sheet)
    col_map = build_column_map(headers, prefix="host_")
    rows = _sheet_rows(sheet)
    count = 0

    for row_vals in rows:
        d = extract_row(row_vals, col_map)
        host_name = _safe_str(d.get("host_host_name") or d.get("vm_name"))
        if not host_name:
            continue

        # Try to parse NIC speed (could be "10000" Mbps or "10 Gbit")
        nic_speed_raw = _safe_str(d.get("host_nic_speed"))
        nic_speed_mbps = _safe_int(nic_speed_raw)
        if "gbit" in nic_speed_raw.lower() or "gbps" in nic_speed_raw.lower():
            nic_speed_mbps = _safe_int(nic_speed_raw.split()[0]) * 1000

        cur.execute("""
            INSERT INTO migration_hosts (
                project_id, host_name, cluster, datacenter,
                cpu_model, cpu_count, cpu_cores, cpu_threads,
                ram_mb, nic_count, nic_speed_mbps,
                esx_version, raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, host_name) DO UPDATE SET
                cluster = EXCLUDED.cluster,
                datacenter = EXCLUDED.datacenter,
                cpu_model = EXCLUDED.cpu_model,
                cpu_count = EXCLUDED.cpu_count,
                cpu_cores = EXCLUDED.cpu_cores,
                cpu_threads = EXCLUDED.cpu_threads,
                ram_mb = EXCLUDED.ram_mb,
                nic_count = EXCLUDED.nic_count,
                nic_speed_mbps = EXCLUDED.nic_speed_mbps,
                esx_version = EXCLUDED.esx_version,
                raw_data = EXCLUDED.raw_data
        """, (
            project_id, host_name,
            _safe_str(d.get("host_cluster")),
            _safe_str(d.get("host_datacenter")),
            _safe_str(d.get("host_cpu_model")),
            _safe_int(d.get("host_cpu_count")),
            _safe_int(d.get("host_cpu_cores")),
            _safe_int(d.get("host_cpu_threads")),
            _safe_int(d.get("host_ram_mb")),
            _safe_int(d.get("host_nic_count")),
            nic_speed_mbps,
            _safe_str(d.get("host_esx_version")),
            Json({k: str(v) if v is not None else "" for k, v in d.items()}),
        ))
        count += 1

    return count


def _parse_vcluster_sheet(sheet, project_id: str, cur) -> int:
    headers = _sheet_headers(sheet)
    col_map = build_column_map(headers, prefix="cluster_")
    rows = _sheet_rows(sheet)
    count = 0

    for row_vals in rows:
        d = extract_row(row_vals, col_map)
        name = _safe_str(d.get("cluster_name_col") or d.get("vm_name"))
        if not name:
            continue

        cur.execute("""
            INSERT INTO migration_clusters (
                project_id, cluster_name, datacenter,
                host_count, total_cpu_mhz, total_ram_mb,
                ha_enabled, drs_enabled, raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, cluster_name) DO UPDATE SET
                datacenter = EXCLUDED.datacenter,
                host_count = EXCLUDED.host_count,
                total_cpu_mhz = EXCLUDED.total_cpu_mhz,
                total_ram_mb = EXCLUDED.total_ram_mb,
                ha_enabled = EXCLUDED.ha_enabled,
                drs_enabled = EXCLUDED.drs_enabled,
                raw_data = EXCLUDED.raw_data
        """, (
            project_id, name,
            _safe_str(d.get("cluster_datacenter")),
            _safe_int(d.get("cluster_host_count")),
            _safe_int(d.get("cluster_total_cpu")),
            _safe_int(d.get("cluster_total_ram")),
            _safe_bool(d.get("cluster_ha")),
            _safe_bool(d.get("cluster_drs")),
            Json({k: str(v) if v is not None else "" for k, v in d.items()}),
        ))
        count += 1

    return count


def _parse_vsnapshot_sheet(sheet, project_id: str, cur) -> int:
    headers = _sheet_headers(sheet)
    col_map = build_column_map(headers, prefix="snap_")
    rows = _sheet_rows(sheet)
    count = 0

    for row_vals in rows:
        d = extract_row(row_vals, col_map)
        vm_name = _safe_str(d.get("snap_vm_name") or d.get("vm_name"))
        if not vm_name:
            continue

        # Parse snapshot date
        snap_date = d.get("snap_created")
        if snap_date and not isinstance(snap_date, datetime):
            try:
                snap_date = datetime.fromisoformat(str(snap_date))
            except (ValueError, TypeError):
                snap_date = None

        size_raw = _safe_float(d.get("snap_size_mb"))
        size_gb = round(size_raw / 1024, 2) if size_raw else 0

        cur.execute("""
            INSERT INTO migration_vm_snapshots (
                project_id, vm_name, snapshot_name, description,
                created_date, size_gb, is_current, raw_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            project_id, vm_name,
            _safe_str(d.get("snap_name")),
            _safe_str(d.get("snap_description")),
            snap_date,
            size_gb,
            _safe_bool(d.get("snap_is_current")),
            Json({k: str(v) if v is not None else "" for k, v in d.items()}),
        ))
        count += 1

    return count


# ---------------------------------------------------------------------------
# Post-parse: update VM summaries (disk/nic/snapshot counts from detail tables)
# ---------------------------------------------------------------------------

def _update_vm_summaries(project_id: str, cur):
    """Update disk_count, nic_count, snapshot_count etc from detail tables."""
    # Disk totals
    cur.execute("""
        UPDATE migration_vms mv SET
            total_disk_gb = sub.sum_gb,
            disk_count = sub.cnt
        FROM (
            SELECT vm_name, coalesce(sum(capacity_gb), 0) as sum_gb, count(*) as cnt
            FROM migration_vm_disks WHERE project_id = %s
            GROUP BY vm_name
        ) sub
        WHERE mv.project_id = %s AND mv.vm_name = sub.vm_name
    """, (project_id, project_id))

    # NIC count
    cur.execute("""
        UPDATE migration_vms mv SET
            nic_count = sub.cnt
        FROM (
            SELECT vm_name, count(*) as cnt
            FROM migration_vm_nics WHERE project_id = %s
            GROUP BY vm_name
        ) sub
        WHERE mv.project_id = %s AND mv.vm_name = sub.vm_name
    """, (project_id, project_id))

    # Snapshot count + oldest
    cur.execute("""
        UPDATE migration_vms mv SET
            snapshot_count = sub.cnt,
            snapshot_oldest_days = sub.oldest_days
        FROM (
            SELECT vm_name,
                   count(*) as cnt,
                   EXTRACT(DAY FROM now() - min(created_date))::int as oldest_days
            FROM migration_vm_snapshots WHERE project_id = %s
            GROUP BY vm_name
        ) sub
        WHERE mv.project_id = %s AND mv.vm_name = sub.vm_name
    """, (project_id, project_id))

    # Host VM counts
    cur.execute("""
        UPDATE migration_hosts mh SET
            vm_count = sub.cnt
        FROM (
            SELECT host_name, count(*) as cnt
            FROM migration_vms WHERE project_id = %s
            GROUP BY host_name
        ) sub
        WHERE mh.project_id = %s AND mh.host_name = sub.host_name
    """, (project_id, project_id))


# ---------------------------------------------------------------------------
# Tenant detection
# ---------------------------------------------------------------------------

def _run_tenant_detection(project_id: str, cur):
    """Run tenant detection for all VMs in a project."""
    # Get detection config
    cur.execute("""
        SELECT detection_config FROM migration_tenant_rules
        WHERE project_id = %s ORDER BY id DESC LIMIT 1
    """, (project_id,))
    row = cur.fetchone()
    if row:
        raw = row["detection_config"]
        detection_config = raw if isinstance(raw, dict) else json.loads(raw)
    else:
        detection_config = {}

    # Default detection: try vCD folder first, then vApp, folder path, resource pool
    default_methods = [
        {"method": "vcd_folder", "enabled": True},
        {"method": "vapp_name", "enabled": True},
        {"method": "folder_path", "enabled": True, "depth": 2},
        {"method": "resource_pool", "enabled": True},
        {"method": "cluster", "enabled": True},
    ]

    # Use stored methods, but ensure vcd_folder is present (may be missing in old configs)
    methods = detection_config.get("methods", default_methods)
    has_vcd_folder = any(m.get("method") == "vcd_folder" for m in methods)
    if not has_vcd_folder:
        methods.insert(0, {"method": "vcd_folder", "enabled": True})
    detection_config["methods"] = methods

    if "fallback_tenant" not in detection_config:
        detection_config["fallback_tenant"] = "Unassigned"
    if "orgvdc_detection" not in detection_config:
        detection_config["orgvdc_detection"] = {"use_resource_pool": True, "use_folder_depth3": True}

    # Get all VMs
    cur.execute("""
        SELECT vm_name, folder_path, resource_pool, vapp_name, annotation, cluster
        FROM migration_vms WHERE project_id = %s
    """, (project_id,))
    vms = [dict(row) for row in cur.fetchall()]

    # Detect tenants
    tenant_map: Dict[str, Dict] = {}
    for vm in vms:
        assignment = assign_tenant(vm, detection_config)

        # Update VM
        cur.execute("""
            UPDATE migration_vms SET
                tenant_name = %s,
                org_vdc = %s,
                app_group = %s,
                updated_at = now()
            WHERE project_id = %s AND vm_name = %s
        """, (assignment.tenant_name, assignment.org_vdc, assignment.app_group,
              project_id, vm["vm_name"]))

        # Aggregate tenant info
        key = (assignment.tenant_name, assignment.org_vdc or "")
        if key not in tenant_map:
            tenant_map[key] = {
                "tenant_name": assignment.tenant_name,
                "org_vdc": assignment.org_vdc,
                "detection_method": assignment.detection_method,
                "vm_count": 0,
            }
        tenant_map[key]["vm_count"] += 1

    # Upsert tenants
    for (tname, ovdc), info in tenant_map.items():
        cur.execute("""
            INSERT INTO migration_tenants (project_id, tenant_name, org_vdc, detection_method, vm_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (project_id, tenant_name, org_vdc) DO UPDATE SET
                detection_method = EXCLUDED.detection_method,
                vm_count = EXCLUDED.vm_count,
                updated_at = now()
        """, (project_id, info["tenant_name"], info["org_vdc"] or None,
              info["detection_method"], info["vm_count"]))

    # Update tenant disk/ram/vcpu totals
    cur.execute("""
        UPDATE migration_tenants mt SET
            total_disk_gb = sub.disk_gb,
            total_ram_mb = sub.ram_mb,
            total_vcpu = sub.vcpu
        FROM (
            SELECT tenant_name, coalesce(org_vdc, '') as ovdc,
                   coalesce(sum(total_disk_gb), 0) as disk_gb,
                   coalesce(sum(ram_mb), 0) as ram_mb,
                   coalesce(sum(cpu_count), 0) as vcpu
            FROM migration_vms WHERE project_id = %s
            GROUP BY tenant_name, coalesce(org_vdc, '')
        ) sub
        WHERE mt.project_id = %s
          AND mt.tenant_name = sub.tenant_name
          AND coalesce(mt.org_vdc, '') = sub.ovdc
    """, (project_id, project_id))


# =====================================================================
# VM ENDPOINTS
# =====================================================================

@router.get("/projects/{project_id}/vms", dependencies=[Depends(require_permission("migration", "read"))])
async def list_vms(
    project_id: str,
    tenant: Optional[str] = Query(None),
    risk: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    host: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    os_family: Optional[str] = Query(None),
    power_state: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    exclude_templates: bool = Query(True),
    sort_by: str = Query("vm_name"),
    sort_dir: str = Query("asc"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List VMs in a migration project with filters."""
    allowed_sorts = {
        "vm_name", "risk_score", "total_disk_gb", "ram_mb", "cpu_count",
        "tenant_name", "host_name", "cluster", "migration_mode", "risk_category",
        "power_state", "priority", "nic_count", "disk_count", "in_use_mb",
        "primary_ip", "dns_name", "os_family",
    }
    if sort_by not in allowed_sorts:
        sort_by = "vm_name"
    if sort_dir.lower() not in ("asc", "desc"):
        sort_dir = "asc"

    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = "WHERE project_id = %s"
            params: list = [project_id]

            if exclude_templates:
                where += " AND (template IS NULL OR template = false)"
            if tenant:
                where += " AND tenant_name = %s"
                params.append(tenant)
            if risk:
                where += " AND risk_category = %s"
                params.append(risk.upper())
            if mode:
                where += " AND migration_mode = %s"
                params.append(mode)
            if host:
                where += " AND host_name = %s"
                params.append(host)
            if cluster:
                where += " AND cluster = %s"
                params.append(cluster)
            if os_family:
                where += " AND os_family = %s"
                params.append(os_family)
            if power_state:
                where += " AND power_state = %s"
                params.append(power_state)
            if search:
                where += " AND (vm_name ILIKE %s OR dns_name ILIKE %s OR primary_ip ILIKE %s)"
                pattern = f"%{search}%"
                params.extend([pattern, pattern, pattern])

            cur.execute(f"""
                SELECT * FROM migration_vms
                {where}
                ORDER BY {sort_by} {sort_dir}
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            vms = [_serialize_row(dict(r)) for r in cur.fetchall()]

            cur.execute(f"SELECT count(*) as cnt FROM migration_vms {where}", params)
            total = cur.fetchone()["cnt"]

    return {"status": "ok", "total": total, "vms": vms}


@router.patch("/projects/{project_id}/vms/{vm_id}",
              dependencies=[Depends(require_permission("migration", "write"))])
async def update_vm(project_id: str, vm_id: str, req: UpdateVMRequest, user = Depends(get_current_user)):
    """Update VM overrides (exclude, mode, priority, tenant)."""
    actor = user.username if user else "system"

    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = [f"{k} = %s" for k in updates]
    set_clauses.append("updated_at = now()")
    params = list(updates.values())

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                UPDATE migration_vms
                SET {', '.join(set_clauses)}
                WHERE project_id = %s AND vm_id = %s
                RETURNING *
            """, params + [project_id, vm_id])
            vm = cur.fetchone()
            if not vm:
                raise HTTPException(status_code=404, detail="VM not found")
            conn.commit()

    _log_activity(actor=actor, action="update_vm", resource_type="migration_vm",
                  resource_id=vm_id, details=updates)

    return {"status": "ok", "vm": _serialize_row(dict(vm))}


# =====================================================================
# TENANT ENDPOINTS
# =====================================================================

@router.get("/projects/{project_id}/tenants", dependencies=[Depends(require_permission("migration", "read"))])
async def list_tenants(project_id: str):
    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM migration_tenants
                WHERE project_id = %s ORDER BY vm_count DESC
            """, (project_id,))
            tenants = [_serialize_row(dict(r)) for r in cur.fetchall()]
    return {"status": "ok", "tenants": tenants}


@router.patch("/projects/{project_id}/tenants/{tenant_id}",
              dependencies=[Depends(require_permission("migration", "write"))])
async def update_tenant(project_id: str, tenant_id: int, req: UpdateTenantRequest, user = Depends(get_current_user)):
    actor = user.username if user else "system"

    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clauses = [f"{k} = %s" for k in updates]
    set_clauses.append("updated_at = now()")
    params = list(updates.values())

    with _get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get old tenant name first (for VM cascade)
            cur.execute("SELECT tenant_name FROM migration_tenants WHERE id = %s AND project_id = %s",
                        (tenant_id, project_id))
            old_row = cur.fetchone()
            if not old_row:
                raise HTTPException(status_code=404, detail="Tenant not found")
            old_tenant_name = old_row["tenant_name"]

            cur.execute(f"""
                UPDATE migration_tenants
                SET {', '.join(set_clauses)}
                WHERE id = %s AND project_id = %s
                RETURNING *
            """, params + [tenant_id, project_id])
            tenant = cur.fetchone()

            # If tenant_name changed, update VMs too (use OLD name for the WHERE)
            if "tenant_name" in updates and updates["tenant_name"] != old_tenant_name:
                cur.execute("""
                    UPDATE migration_vms SET tenant_name = %s, updated_at = now()
                    WHERE project_id = %s AND tenant_name = %s
                """, (updates["tenant_name"], project_id, old_tenant_name))

            conn.commit()

    _log_activity(actor=actor, action="update_tenant", resource_type="migration_tenant",
                  resource_id=str(tenant_id), details=updates)

    return {"status": "ok", "tenant": _serialize_row(dict(tenant))}


# =====================================================================
# HOST / CLUSTER / STATS
# =====================================================================

@router.get("/projects/{project_id}/hosts", dependencies=[Depends(require_permission("migration", "read"))])
async def list_hosts(project_id: str):
    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM migration_hosts
                WHERE project_id = %s ORDER BY host_name
            """, (project_id,))
            hosts = [_serialize_row(dict(r)) for r in cur.fetchall()]
    return {"status": "ok", "hosts": hosts}


@router.get("/projects/{project_id}/clusters", dependencies=[Depends(require_permission("migration", "read"))])
async def list_clusters(project_id: str):
    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM migration_clusters
                WHERE project_id = %s ORDER BY cluster_name
            """, (project_id,))
            clusters = [_serialize_row(dict(r)) for r in cur.fetchall()]
    return {"status": "ok", "clusters": clusters}


@router.get("/projects/{project_id}/stats", dependencies=[Depends(require_permission("migration", "read"))])
async def get_stats(project_id: str):
    """Summary statistics for a migration project."""
    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    count(*) as total_vms,
                    count(*) FILTER (WHERE template = true) as templates,
                    count(*) FILTER (WHERE NOT coalesce(exclude_from_migration, false) AND NOT coalesce(template, false)) as migratable_vms,
                    count(*) FILTER (WHERE exclude_from_migration) as excluded_vms,
                    coalesce(sum(total_disk_gb), 0) as total_disk_gb,
                    coalesce(sum(ram_mb), 0) as total_ram_mb,
                    coalesce(sum(cpu_count), 0) as total_vcpus,
                    round(coalesce(sum(in_use_mb), 0) / 1024.0, 2) as total_in_use_gb,
                    count(DISTINCT host_name) as host_count,
                    count(DISTINCT cluster) as cluster_count,
                    count(DISTINCT tenant_name) as tenant_count,
                    count(*) FILTER (WHERE risk_category = 'GREEN') as risk_green,
                    count(*) FILTER (WHERE risk_category = 'YELLOW') as risk_yellow,
                    count(*) FILTER (WHERE risk_category = 'RED') as risk_red,
                    count(*) FILTER (WHERE migration_mode = 'warm_eligible') as mode_warm,
                    count(*) FILTER (WHERE migration_mode = 'warm_risky') as mode_warm_risky,
                    count(*) FILTER (WHERE migration_mode = 'cold_required') as mode_cold,
                    count(*) FILTER (WHERE power_state ILIKE '%%poweredOn%%') as powered_on,
                    count(*) FILTER (WHERE power_state ILIKE '%%poweredOff%%') as powered_off
                FROM migration_vms WHERE project_id = %s
            """, (project_id,))
            stats = _serialize_row(dict(cur.fetchone()))

            # ---- Build UI-friendly aliases ----
            stats["total_vcpu"] = stats["total_vcpus"]  # backward compat
            stats["total_provisioned_gb"] = stats["total_disk_gb"]

            # Risk & migration-mode distributions as dicts
            stats["risk_distribution"] = {
                "GREEN": stats.get("risk_green", 0),
                "YELLOW": stats.get("risk_yellow", 0),
                "RED": stats.get("risk_red", 0),
            }
            stats["mode_distribution"] = {
                "warm_eligible": stats.get("mode_warm", 0),
                "warm_risky": stats.get("mode_warm_risky", 0),
                "cold_required": stats.get("mode_cold", 0),
            }

            # OS family distribution
            cur.execute("""
                SELECT os_family, count(*) as cnt
                FROM migration_vms WHERE project_id = %s
                GROUP BY os_family ORDER BY cnt DESC
            """, (project_id,))
            os_fam = {r["os_family"]: r["cnt"] for r in cur.fetchall()}
            stats["os_families"] = os_fam
            stats["os_distribution"] = os_fam  # alias for UI

            # Top 10 largest VMs
            cur.execute("""
                SELECT vm_name, total_disk_gb, ram_mb, cpu_count, risk_category
                FROM migration_vms WHERE project_id = %s
                ORDER BY total_disk_gb DESC NULLS LAST LIMIT 10
            """, (project_id,))
            stats["largest_vms"] = [_serialize_row(dict(r)) for r in cur.fetchall()]

    return {"status": "ok", "stats": stats}


# =====================================================================
# RISK SCORING & ASSESSMENT
# =====================================================================

@router.get("/projects/{project_id}/risk-config",
            dependencies=[Depends(require_permission("migration", "read"))])
async def get_risk_config(project_id: str):
    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM migration_risk_config
                WHERE project_id = %s ORDER BY id DESC LIMIT 1
            """, (project_id,))
            config = cur.fetchone()
            if not config:
                raise HTTPException(status_code=404, detail="Risk config not found")
    return {"status": "ok", "config": _serialize_row(dict(config))}


@router.put("/projects/{project_id}/risk-config",
            dependencies=[Depends(require_permission("migration", "write"))])
async def update_risk_config(project_id: str, request: Request, user = Depends(get_current_user)):
    actor = user.username if user else "system"
    body = await request.json()
    rules = body.get("rules")
    if not rules:
        raise HTTPException(status_code=400, detail="rules field required")

    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE migration_risk_config SET rules = %s
                WHERE project_id = %s
                RETURNING *
            """, (Json(rules), project_id))
            config = cur.fetchone()
            if not config:
                cur.execute("""
                    INSERT INTO migration_risk_config (project_id, rules)
                    VALUES (%s, %s) RETURNING *
                """, (project_id, Json(rules)))
                config = cur.fetchone()
            conn.commit()

    _log_activity(actor=actor, action="update_risk_config", resource_type="migration_project",
                  resource_id=project_id)

    return {"status": "ok", "config": _serialize_row(dict(config))}


@router.post("/projects/{project_id}/assess",
             dependencies=[Depends(require_permission("migration", "write"))])
async def run_assessment(project_id: str, user = Depends(get_current_user)):
    """Run risk scoring and warm/cold classification for all VMs."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Get risk rules
            cur.execute("""
                SELECT rules FROM migration_risk_config
                WHERE project_id = %s ORDER BY id DESC LIMIT 1
            """, (project_id,))
            config_row = cur.fetchone()
            rules = config_row["rules"] if config_row else {}
            if isinstance(rules, str):
                rules = json.loads(rules)

            # Get all VMs
            cur.execute("""
                SELECT * FROM migration_vms WHERE project_id = %s
            """, (project_id,))
            vms = [dict(r) for r in cur.fetchall()]

            scored = 0
            for vm in vms:
                # Risk scoring
                risk = compute_risk(vm, rules)
                # Migration mode
                mode = classify_migration_mode(vm, rules)

                cur.execute("""
                    UPDATE migration_vms SET
                        risk_score = %s,
                        risk_category = %s,
                        risk_reasons = %s,
                        migration_mode = %s,
                        mode_reasons = %s,
                        updated_at = now()
                    WHERE project_id = %s AND vm_id = %s
                """, (
                    risk.score, risk.category, Json(risk.reasons),
                    mode.mode, Json(mode.reasons),
                    project_id, vm["vm_id"],
                ))
                scored += 1

            # Update project status
            cur.execute("""
                UPDATE migration_projects SET
                    status = CASE WHEN status IN ('draft', 'assessment') THEN 'assessment' ELSE status END,
                    updated_at = now()
                WHERE project_id = %s
            """, (project_id,))

            conn.commit()

    _log_activity(actor=actor, action="run_assessment", resource_type="migration_project",
                  resource_id=project_id, details={"vms_scored": scored})

    return {"status": "ok", "message": f"Assessment complete: {scored} VMs scored"}


# =====================================================================
# RESET ENDPOINTS
# =====================================================================

@router.post("/projects/{project_id}/reset-assessment",
             dependencies=[Depends(require_permission("migration", "write"))])
async def reset_assessment(project_id: str, user = Depends(get_current_user)):
    """Clear all computed risk/mode scores. Keep source data."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE migration_vms SET
                    risk_score = NULL, risk_category = NULL, risk_reasons = '[]',
                    migration_mode = NULL, mode_reasons = '[]',
                    phase1_duration_hours = NULL, cutover_downtime_hours = NULL,
                    total_migration_hours = NULL, production_impact = NULL,
                    target_flavor = NULL, target_flavor_id = NULL,
                    target_network = NULL, target_project = NULL,
                    updated_at = now()
                WHERE project_id = %s
            """, (project_id,))

            # Also clear waves, gaps, prep tasks
            for table in ("migration_wave_vms", "migration_waves",
                          "migration_prep_tasks", "migration_target_gaps"):
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))

            cur.execute("""
                UPDATE migration_projects SET status = 'assessment', updated_at = now()
                WHERE project_id = %s
            """, (project_id,))
            conn.commit()

    _log_activity(actor=actor, action="reset_assessment", resource_type="migration_project",
                  resource_id=project_id)

    return {"status": "ok", "message": "Assessment data cleared"}


@router.post("/projects/{project_id}/reset-plan",
             dependencies=[Depends(require_permission("migration", "write"))])
async def reset_plan(project_id: str, user = Depends(get_current_user)):
    """Clear wave/prep data only. Keep assessment results."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor() as cur:
            for table in ("migration_wave_vms", "migration_waves",
                          "migration_prep_tasks", "migration_target_gaps"):
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))

            cur.execute("""
                UPDATE migration_projects
                SET status = CASE WHEN status IN ('planned', 'approved', 'preparing', 'ready')
                                  THEN 'assessment' ELSE status END,
                    updated_at = now()
                WHERE project_id = %s
            """, (project_id,))
            conn.commit()

    _log_activity(actor=actor, action="reset_plan", resource_type="migration_project",
                  resource_id=project_id)

    return {"status": "ok", "message": "Plan data cleared"}


# =====================================================================
# APPROVAL GATE
# =====================================================================

@router.post("/projects/{project_id}/approve",
             dependencies=[Depends(require_permission("migration", "admin"))])
async def approve_project(project_id: str, user = Depends(get_current_user)):
    """Approve a project — gate before any PCD write operations."""
    actor = user.username if user else "system"

    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        if project["status"] not in ("planned", "assessment"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve project in status '{project['status']}'. Must be 'planned' or 'assessment'."
            )

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE migration_projects SET
                    status = 'approved',
                    approved_by = %s,
                    approved_at = now(),
                    updated_at = now()
                WHERE project_id = %s
            """, (actor, project_id))
            conn.commit()

    _log_activity(actor=actor, action="approve", resource_type="migration_project",
                  resource_id=project_id, resource_name=project["name"])

    return {"status": "ok", "message": f"Project approved by {actor}"}


# =====================================================================
# BANDWIDTH & AGENT RECOMMENDATION
# =====================================================================

@router.get("/projects/{project_id}/bandwidth",
            dependencies=[Depends(require_permission("migration", "read"))])
async def get_bandwidth_model(project_id: str):
    """Compute the bandwidth constraint model for the project."""
    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        model = compute_bandwidth_model(project)

    return {
        "status": "ok",
        "bandwidth": {
            "source_effective_mbps": round(model.source_effective_mbps, 1),
            "link_effective_mbps": round(model.link_effective_mbps, 1) if model.link_effective_mbps else None,
            "agent_effective_mbps": round(model.agent_effective_mbps, 1),
            "storage_effective_mbps": round(model.storage_effective_mbps, 1),
            "bottleneck": model.bottleneck,
            "bottleneck_mbps": round(model.bottleneck_mbps, 1),
            "topology_type": project["topology_type"],
        },
    }


@router.get("/projects/{project_id}/agent-recommendation",
            dependencies=[Depends(require_permission("migration", "read"))])
async def get_agent_recommendation(project_id: str):
    """Compute recommended vJailbreak agent sizing."""
    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT count(*) as vm_count,
                       coalesce(max(total_disk_gb), 0) as max_disk_gb,
                       coalesce(sum(total_disk_gb), 0) as total_disk_gb
                FROM migration_vms
                WHERE project_id = %s AND NOT coalesce(exclude_from_migration, false)
                  AND NOT coalesce(template, false)
            """, (project_id,))
            summary = dict(cur.fetchone())

            cur.execute("""
                SELECT total_disk_gb FROM migration_vms
                WHERE project_id = %s AND NOT coalesce(exclude_from_migration, false)
                  AND NOT coalesce(template, false)
                ORDER BY total_disk_gb DESC NULLS LAST LIMIT 10
            """, (project_id,))
            top_disks = [float(r["total_disk_gb"] or 0) for r in cur.fetchall()]

    rec = recommend_agent_sizing(
        vm_count=summary["vm_count"],
        largest_disk_gb=float(summary["max_disk_gb"]),
        top5_disk_sizes_gb=top_disks[:5],
        project_settings=project,
        total_disk_gb=float(summary["total_disk_gb"]),
    )

    return {
        "status": "ok",
        "recommendation": {
            "recommended_agent_count": rec.recommended_count,
            "vcpu_per_agent": rec.vcpu_per_agent,
            "ram_gb_per_agent": rec.ram_gb_per_agent,
            "disk_gb_per_agent": round(rec.disk_gb_per_agent, 0),
            "max_concurrent_vms": rec.max_concurrent_vms,
            "reasoning": rec.reasoning,
        },
    }


# =====================================================================
# VM DETAIL (Disks + NICs per VM)
# =====================================================================

@router.get("/projects/{project_id}/vms/{vm_name}/details",
            dependencies=[Depends(require_permission("migration", "read"))])
async def get_vm_details(project_id: str, vm_name: str):
    """Get detailed disk and NIC info for a specific VM."""
    with _get_conn() as conn:
        _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT disk_label, disk_path, capacity_gb, thin_provisioned,
                       eagerly_scrub, datastore
                FROM migration_vm_disks
                WHERE project_id = %s AND vm_name = %s
                ORDER BY disk_label
            """, (project_id, vm_name))
            disks = [_serialize_row(dict(r)) for r in cur.fetchall()]

            cur.execute("""
                SELECT nic_label, adapter_type, network_name, connected,
                       mac_address, ip_address
                FROM migration_vm_nics
                WHERE project_id = %s AND vm_name = %s
                ORDER BY nic_label
            """, (project_id, vm_name))
            nics = [_serialize_row(dict(r)) for r in cur.fetchall()]

    return {"status": "ok", "disks": disks, "nics": nics}


# =====================================================================
# MIGRATION PLAN EXPORT
# =====================================================================

@router.get("/projects/{project_id}/export-plan",
            dependencies=[Depends(require_permission("migration", "read"))])
async def export_migration_plan(project_id: str):
    """
    Generate a comprehensive migration plan with per-tenant assessment,
    daily VM schedule, and per-VM time estimates (warm/cold).
    """
    with _get_conn() as conn:
        project = _get_project(project_id, conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM migration_vms
                WHERE project_id = %s
                  AND NOT coalesce(template, false)
                ORDER BY tenant_name, priority, total_disk_gb DESC NULLS LAST
            """, (project_id,))
            vms = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT * FROM migration_tenants
                WHERE project_id = %s ORDER BY vm_count DESC
            """, (project_id,))
            tenants = [dict(r) for r in cur.fetchall()]

    bw_model = compute_bandwidth_model(project)
    plan = generate_migration_plan(
        vms=vms,
        tenants=tenants,
        project_settings=project,
        bottleneck_mbps=bw_model.bottleneck_mbps,
    )

    return {
        "status": "ok",
        "project_name": project["name"],
        "topology_type": project["topology_type"],
        **plan,
    }


# =====================================================================
# Serialization helpers
# =====================================================================

def _serialize_project(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DB row to JSON-safe dict."""
    return _serialize_row(row)


def _serialize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a single DB row dict to JSON-safe format."""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, (int, float, str, bool, list, dict)) or v is None:
            result[k] = v
        else:
            result[k] = str(v)
    return result
