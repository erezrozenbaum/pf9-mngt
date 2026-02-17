"""
Backup Management API Routes
=============================
Endpoints for database backup configuration, manual trigger, history,
and restore operations.

RBAC:
  - admin  → read + write (view config, trigger backup, view history)
  - superadmin → admin (all above + restore, delete, change config)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User
from db_pool import get_connection

logger = logging.getLogger("pf9.backup")

router = APIRouter(prefix="/api/backup", tags=["backup"])

NFS_BACKUP_PATH = os.getenv("NFS_BACKUP_PATH", "/backups")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BackupConfigResponse(BaseModel):
    id: int
    enabled: bool
    nfs_path: str
    schedule_type: str
    schedule_time_utc: str
    schedule_day_of_week: int
    retention_count: int
    retention_days: int
    last_backup_at: Optional[str] = None
    ldap_backup_enabled: bool = False
    ldap_retention_count: int = 7
    ldap_retention_days: int = 30
    last_ldap_backup_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BackupConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    nfs_path: Optional[str] = None
    schedule_type: Optional[str] = Field(None, pattern="^(manual|daily|weekly)$")
    schedule_time_utc: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    schedule_day_of_week: Optional[int] = Field(None, ge=0, le=6)
    retention_count: Optional[int] = Field(None, ge=1)
    retention_days: Optional[int] = Field(None, ge=1)
    ldap_backup_enabled: Optional[bool] = None
    ldap_retention_count: Optional[int] = Field(None, ge=1)
    ldap_retention_days: Optional[int] = Field(None, ge=1)


class BackupHistoryItem(BaseModel):
    id: int
    status: str
    backup_type: str
    backup_target: str = "database"
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_size_bytes: Optional[int] = None
    duration_seconds: Optional[float] = None
    initiated_by: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: Optional[str] = None


class BackupStatusResponse(BaseModel):
    running: bool
    last_backup: Optional[BackupHistoryItem] = None
    next_scheduled: Optional[str] = None
    backup_count: int = 0
    total_size_bytes: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row):
    """Serialise datetime / None values for JSON."""
    if not row:
        return None
    out = dict(row)
    for k, v in out.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
    return out


# ---------------------------------------------------------------------------
# GET /api/backup/config
# ---------------------------------------------------------------------------
@router.get("/config", response_model=BackupConfigResponse)
async def get_backup_config(
    _perm=Depends(require_permission("backup", "read")),
    current_user: User = Depends(get_current_user),
):
    """Return current backup configuration."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM backup_config ORDER BY id LIMIT 1")
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Backup config not initialised")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# PUT /api/backup/config
# ---------------------------------------------------------------------------
@router.put("/config", response_model=BackupConfigResponse)
async def update_backup_config(
    body: BackupConfigUpdate,
    _perm=Depends(require_permission("backup", "write")),
    current_user: User = Depends(get_current_user),
):
    """Update backup configuration. Admins can toggle enable/schedule."""
    updates = body.dict(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_parts = []
    vals = []
    for k, v in updates.items():
        set_parts.append(f"{k} = %s")
        vals.append(v)
    set_parts.append("updated_at = now()")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE backup_config SET {', '.join(set_parts)} "
                "WHERE id = (SELECT id FROM backup_config ORDER BY id LIMIT 1) "
                "RETURNING *",
                vals,
            )
            row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Backup config not initialised")

    logger.info("Backup config updated by %s: %s", current_user.username, updates)
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# POST /api/backup/run  – trigger a manual backup
# ---------------------------------------------------------------------------
@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def trigger_manual_backup(
    target: str = "database",
    _perm=Depends(require_permission("backup", "write")),
    current_user: User = Depends(get_current_user),
):
    """Queue a manual backup job. target can be 'database' or 'ldap'."""
    if target not in ("database", "ldap"):
        raise HTTPException(status_code=400, detail="target must be 'database' or 'ldap'")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Prevent duplicate if one is already pending/running for this target
            cur.execute(
                "SELECT id FROM backup_history WHERE status IN ('pending', 'running') "
                "AND backup_target = %s LIMIT 1",
                (target,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail=f"A {target} backup job is already pending or running",
                )

            cur.execute(
                "INSERT INTO backup_history (status, backup_type, backup_target, initiated_by) "
                "VALUES ('pending', 'manual', %s, %s) RETURNING *",
                (target, current_user.username),
            )
            row = cur.fetchone()
        conn.commit()

    logger.info("Manual %s backup queued by %s – job %s", target, current_user.username, row["id"])
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# GET /api/backup/history
# ---------------------------------------------------------------------------
@router.get("/history")
async def get_backup_history(
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[str] = None,
    target_filter: Optional[str] = None,
    _perm=Depends(require_permission("backup", "read")),
    current_user: User = Depends(get_current_user),
):
    """Return paginated backup history. Optionally filter by status and/or target."""
    conditions = []
    params: list = []
    if status_filter:
        conditions.append("status = %s")
        params.append(status_filter)
    if target_filter:
        conditions.append("backup_target = %s")
        params.append(target_filter)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT COUNT(*) AS total FROM backup_history {where}",
                params,
            )
            total = cur.fetchone()["total"]

            cur.execute(
                f"SELECT * FROM backup_history {where} "
                "ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset],
            )
            rows = cur.fetchall()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# GET /api/backup/status  – quick dashboard summary
# ---------------------------------------------------------------------------
@router.get("/status", response_model=BackupStatusResponse)
async def get_backup_status(
    _perm=Depends(require_permission("backup", "read")),
    current_user: User = Depends(get_current_user),
):
    """Return a compact status summary for the UI header card."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Is anything running?
            cur.execute(
                "SELECT * FROM backup_history WHERE status = 'running' LIMIT 1"
            )
            running_row = cur.fetchone()

            # Last completed backup
            cur.execute(
                "SELECT * FROM backup_history WHERE status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            )
            last_row = cur.fetchone()

            # Aggregate stats
            cur.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(file_size_bytes), 0) AS total_bytes "
                "FROM backup_history WHERE status = 'completed'"
            )
            agg = cur.fetchone()

    return {
        "running": running_row is not None,
        "last_backup": _row_to_dict(last_row) if last_row else None,
        "backup_count": agg["cnt"],
        "total_size_bytes": agg["total_bytes"],
    }


# ---------------------------------------------------------------------------
# POST /api/backup/restore/{id}  – restore from a specific backup
# ---------------------------------------------------------------------------
@router.post("/restore/{backup_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_restore(
    backup_id: int,
    _perm=Depends(require_permission("backup", "admin")),
    current_user: User = Depends(get_current_user),
):
    """Queue a restore job from an existing backup. Superadmin only."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Find the source backup
            cur.execute(
                "SELECT * FROM backup_history WHERE id = %s AND status = 'completed'",
                (backup_id,),
            )
            source = cur.fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="Completed backup not found")

            source_path = source.get("file_path")
            if not source_path:
                raise HTTPException(
                    status_code=400, detail="Backup file path is missing"
                )

            # Prevent overlapping restores
            cur.execute(
                "SELECT id FROM backup_history "
                "WHERE status IN ('pending', 'running') AND backup_type = 'restore' LIMIT 1"
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=409, detail="A restore job is already in progress"
                )

            # Insert restore job (preserve the same backup_target as source)
            restore_target = source.get("backup_target", "database")
            cur.execute(
                "INSERT INTO backup_history (status, backup_type, backup_target, file_name, file_path, initiated_by) "
                "VALUES ('pending', 'restore', %s, %s, %s, %s) RETURNING *",
                (restore_target, source.get("file_name"), source_path, current_user.username),
            )
            row = cur.fetchone()
        conn.commit()

    logger.info(
        "Restore queued by %s from backup %s – job %s",
        current_user.username, backup_id, row["id"],
    )
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# DELETE /api/backup/{id}  – delete a backup file and record
# ---------------------------------------------------------------------------
@router.delete("/{backup_id}")
async def delete_backup(
    backup_id: int,
    _perm=Depends(require_permission("backup", "admin")),
    current_user: User = Depends(get_current_user),
):
    """Delete a backup record and its file on disk. Superadmin only."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM backup_history WHERE id = %s", (backup_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Backup not found")

            # Remove file from disk
            fpath = row.get("file_path")
            if fpath and os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                    logger.info("Deleted backup file %s", fpath)
                except OSError as exc:
                    logger.warning("Could not delete file %s: %s", fpath, exc)

            cur.execute("DELETE FROM backup_history WHERE id = %s", (backup_id,))
        conn.commit()

    logger.info("Backup %s deleted by %s", backup_id, current_user.username)
    return {"detail": "Backup deleted", "id": backup_id}
