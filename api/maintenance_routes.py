"""
Operational maintenance windows (CLEA/SLA suppression).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import User, require_authentication
from db_pool import get_connection

logger = logging.getLogger("pf9.maintenance")
router = APIRouter(prefix="/api/admin/maintenance", tags=["maintenance"])

_ALLOWED_SUPPRESS_FOR = {
    "clea": "suppress_clea",
    "sla_defense": "suppress_sla_defense",
    "notifications": "suppress_notifications",
}


class MaintenanceScope(BaseModel):
    project_ids: list[str] = Field(default_factory=list)
    region_ids: list[str] = Field(default_factory=list)


class MaintenanceWindowCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    starts_at: datetime
    ends_at: datetime
    scope: Optional[MaintenanceScope] = None
    suppress_clea: bool = True
    suppress_sla_defense: bool = True
    suppress_notifications: bool = False


class MaintenanceWindowUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    scope: Optional[MaintenanceScope] = None
    suppress_clea: Optional[bool] = None
    suppress_sla_defense: Optional[bool] = None
    suppress_notifications: Optional[bool] = None


def _to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "starts_at": row["starts_at"].isoformat() if row.get("starts_at") else None,
        "ends_at": row["ends_at"].isoformat() if row.get("ends_at") else None,
        "scope": row.get("scope"),
        "suppress_clea": bool(row.get("suppress_clea")),
        "suppress_sla_defense": bool(row.get("suppress_sla_defense")),
        "suppress_notifications": bool(row.get("suppress_notifications")),
        "created_by": row.get("created_by"),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _role(user: User) -> str:
    if isinstance(user, dict):
        return str(user.get("role") or "")
    return str(getattr(user, "role", ""))


def _username(user: User) -> str:
    if isinstance(user, dict):
        return str(user.get("username") or "unknown")
    return str(getattr(user, "username", "unknown"))


def _require_admin(user: User) -> None:
    if _role(user) not in ("admin", "superadmin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")


def _require_superadmin(user: User) -> None:
    if _role(user) != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin role required")


def _validate_window_bounds(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at <= starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ends_at must be later than starts_at")


def get_active_maintenance_window(
    project_id: Optional[str],
    region_id: Optional[str],
    *,
    suppress_for: str = "clea",
) -> Optional[dict[str, Any]]:
    """Return active maintenance window for the scope, or None when not suppressed."""
    flag_column = _ALLOWED_SUPPRESS_FOR.get(suppress_for)
    if not flag_column:
        raise ValueError(f"Unsupported suppress_for={suppress_for!r}")

    cache_key = f"pf9:maint:{suppress_for}:{project_id or '*'}:{region_id or '*'}"
    try:
        from cache import _get_client as _redis_client

        rc = _redis_client()
        if rc is not None:
            raw = rc.get(cache_key)
            if raw:
                payload = json.loads(raw)
                return payload or None
    except Exception:
        pass

    sql = f"""
        SELECT id, title, starts_at, ends_at, scope,
               suppress_clea, suppress_sla_defense, suppress_notifications,
               created_by, created_at, updated_at
        FROM ops_maintenance_windows
        WHERE {flag_column} = true
          AND starts_at <= NOW()
          AND ends_at > NOW()
          AND (
                scope IS NULL
                OR (
                    %s IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(COALESCE(scope->'project_ids', '[]'::jsonb)) p(v)
                        WHERE p.v = %s
                    )
                )
                OR (
                    %s IS NOT NULL
                    AND EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(COALESCE(scope->'region_ids', '[]'::jsonb)) r(v)
                        WHERE r.v = %s
                    )
                )
          )
        ORDER BY starts_at ASC
        LIMIT 1
    """

    out: Optional[dict[str, Any]] = None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (project_id, project_id, region_id, region_id))
            row = cur.fetchone()
            if row:
                out = _to_dict(dict(row))

    try:
        from cache import _get_client as _redis_client

        rc = _redis_client()
        if rc is not None:
            rc.setex(cache_key, 60, json.dumps(out or {}))
    except Exception:
        pass

    return out


@router.get("/windows")
async def list_windows(current_user: User = Depends(require_authentication)):
    _require_admin(current_user)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, starts_at, ends_at, scope,
                       suppress_clea, suppress_sla_defense, suppress_notifications,
                       created_by, created_at, updated_at
                FROM ops_maintenance_windows
                ORDER BY starts_at DESC
                """
            )
            rows = [_to_dict(dict(r)) for r in cur.fetchall()]
    return {"windows": rows}


@router.get("/windows/active")
async def list_active_windows(current_user: User = Depends(require_authentication)):
    # Any authenticated role may view active windows.
    _ = current_user
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, starts_at, ends_at, scope,
                       suppress_clea, suppress_sla_defense, suppress_notifications,
                       created_by, created_at, updated_at
                FROM ops_maintenance_windows
                WHERE starts_at <= NOW() AND ends_at > NOW()
                ORDER BY starts_at ASC
                """
            )
            rows = [_to_dict(dict(r)) for r in cur.fetchall()]
    return {"windows": rows}


@router.post("/windows", status_code=status.HTTP_201_CREATED)
async def create_window(body: MaintenanceWindowCreate, current_user: User = Depends(require_authentication)):
    _require_superadmin(current_user)
    _validate_window_bounds(body.starts_at, body.ends_at)

    scope_json = body.scope.model_dump() if body.scope else None
    username = _username(current_user)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO ops_maintenance_windows
                    (title, starts_at, ends_at, scope,
                     suppress_clea, suppress_sla_defense, suppress_notifications,
                     created_by)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                RETURNING id, title, starts_at, ends_at, scope,
                          suppress_clea, suppress_sla_defense, suppress_notifications,
                          created_by, created_at, updated_at
                """,
                (
                    body.title,
                    body.starts_at,
                    body.ends_at,
                    json.dumps(scope_json) if scope_json is not None else None,
                    body.suppress_clea,
                    body.suppress_sla_defense,
                    body.suppress_notifications,
                    username,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    logger.info("maintenance: created window id=%s by %s", row["id"], username)
    return {"window": _to_dict(dict(row))}


@router.patch("/windows/{window_id}")
async def update_window(
    window_id: int,
    body: MaintenanceWindowUpdate,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT starts_at, ends_at FROM ops_maintenance_windows WHERE id = %s",
                (window_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Maintenance window not found")

            new_starts = updates.get("starts_at", existing["starts_at"])
            new_ends = updates.get("ends_at", existing["ends_at"])
            _validate_window_bounds(new_starts, new_ends)

            set_parts: list[str] = []
            params: list[Any] = []
            for field, value in updates.items():
                if field == "scope":
                    set_parts.append("scope = %s::jsonb")
                    params.append(json.dumps(value))
                else:
                    set_parts.append(f"{field} = %s")
                    params.append(value)
            set_parts.append("updated_at = NOW()")
            params.append(window_id)

            cur.execute(
                f"""
                UPDATE ops_maintenance_windows
                   SET {', '.join(set_parts)}
                 WHERE id = %s
                RETURNING id, title, starts_at, ends_at, scope,
                          suppress_clea, suppress_sla_defense, suppress_notifications,
                          created_by, created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
        conn.commit()

    logger.info("maintenance: updated window id=%s by %s", window_id, _username(current_user))
    return {"window": _to_dict(dict(row))}


@router.delete("/windows/{window_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_window(window_id: int, current_user: User = Depends(require_authentication)):
    _require_superadmin(current_user)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ops_maintenance_windows WHERE id = %s", (window_id,))
            if cur.rowcount == 0:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Maintenance window not found")
        conn.commit()

    logger.info("maintenance: deleted window id=%s by %s", window_id, _username(current_user))
