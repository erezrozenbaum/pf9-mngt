"""
api/tenant_portal_routes.py — Admin management endpoints for the tenant portal.

These routes are part of the ADMIN API service (api/ — port 8000).
They require `admin` or `superadmin` role and are protected by the existing
verify_token() + RBAC middleware.

Endpoints:
  GET    /api/admin/tenant-portal/users/{cp_id}
         List all Keystone users for a CP with current access status.

  GET    /api/admin/tenant-portal/access/{cp_id}
         List all tenant_portal_access rows for a CP.

  PUT    /api/admin/tenant-portal/access
         Grant or revoke portal access for one user.

  DELETE /api/admin/tenant-portal/sessions/{cp_id}/{keystone_user_id}
         Force-terminate all active sessions for a user.

  GET    /api/admin/tenant-portal/sessions/{cp_id}
         List active sessions for all users in this CP.

  GET    /api/admin/tenant-portal/audit/{cp_id}
         Paginated audit log from tenant_action_log for a CP.
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator

from auth import require_authentication, User, log_auth_event
from db_pool import get_connection
from request_helpers import get_request_ip

logger = logging.getLogger("pf9.tenant_portal_routes")

router = APIRouter(prefix="/api/admin/tenant-portal", tags=["admin-tenant-portal"])

# ---------------------------------------------------------------------------
# Redis (same instance as the tenant portal uses)
# ---------------------------------------------------------------------------
import os
from secret_helper import read_secret

_redis_client = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("TENANT_REDIS_DB", "0")),
            password=read_secret("redis_password", env_var="REDIS_PASSWORD") or None,
            decode_responses=True,
            socket_timeout=3,
        )
    return _redis_client


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AccessUpsertRequest(BaseModel):
    keystone_user_id: str
    user_name: Optional[str] = None        # friendly display name for the Keystone user
    control_plane_id: str
    tenant_name: Optional[str] = None      # friendly display name for the tenant / org
    enabled: bool
    mfa_required: Optional[bool] = False
    notes: Optional[str] = None

    @field_validator("keystone_user_id", "control_plane_id")
    @classmethod
    def no_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class AccessRow(BaseModel):
    id: int
    keystone_user_id: str
    user_name: Optional[str]
    control_plane_id: str
    tenant_name: Optional[str]
    enabled: bool
    mfa_required: bool
    notes: Optional[str]
    granted_by: Optional[str]
    granted_at: Optional[datetime]
    revoked_by: Optional[str]
    revoked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Permission guard — admin or superadmin required
# ---------------------------------------------------------------------------

def _require_admin(current_user: User = Depends(require_authentication)):
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin_role_required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/control-planes", summary="List all enabled control planes")
async def list_control_planes(
    current_user: User = Depends(_require_admin),
):
    """Returns [{id, name}] for every enabled control plane — used to populate the CP dropdown."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name FROM pf9_control_planes WHERE is_enabled = TRUE ORDER BY name",
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/projects/{cp_id}", summary="List projects (tenants/orgs) for a CP with member counts")
async def list_projects(
    cp_id: str,
    current_user: User = Depends(_require_admin),
):
    """
    Returns all projects linked to this CP via user role_assignments,
    including member count and how many already have portal access.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id FROM pf9_control_planes WHERE id = %s AND is_enabled = TRUE",
                (cp_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="control_plane_not_found")

            cur.execute(
                """
                SELECT p.id,
                       p.name,
                       COUNT(DISTINCT ra.user_id)                                         AS member_count,
                       COUNT(DISTINCT tpa.keystone_user_id)
                           FILTER (WHERE tpa.enabled = TRUE)                              AS portal_enabled_count
                FROM projects p
                JOIN role_assignments ra ON ra.project_id = p.id
                JOIN users u            ON u.id = ra.user_id AND u.enabled = TRUE
                LEFT JOIN tenant_portal_access tpa
                       ON tpa.keystone_user_id = u.id
                      AND tpa.control_plane_id = %s
                WHERE p.id IN (
                    SELECT DISTINCT ra2.project_id
                    FROM role_assignments ra2
                    JOIN pf9_regions pr ON pr.control_plane_id = %s
                    WHERE ra2.project_id IS NOT NULL
                )
                GROUP BY p.id, p.name
                ORDER BY p.name
                """,
                (cp_id, cp_id),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/users/{cp_id}", summary="List Keystone users for a CP with portal access status")
async def list_users_with_access(
    cp_id: str,
    project_id: Optional[str] = Query(None, description="Filter to users in a specific project"),
    current_user: User = Depends(_require_admin),
):
    """
    Returns Keystone users for this CP with their current portal access status.
    Pass ?project_id=<id> to restrict to members of a specific project (tenant).
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name FROM pf9_control_planes WHERE id = %s",
                (cp_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="control_plane_not_found")

            if project_id:
                cur.execute(
                    """
                    SELECT DISTINCT u.id AS keystone_user_id,
                           u.email,
                           u.name,
                           tpa.enabled,
                           tpa.mfa_required,
                           tpa.granted_at,
                           tpa.revoked_at
                    FROM users u
                    JOIN role_assignments ra ON ra.user_id = u.id AND ra.project_id = %s
                    LEFT JOIN tenant_portal_access tpa
                        ON tpa.keystone_user_id = u.id
                        AND tpa.control_plane_id = %s
                    WHERE u.enabled = TRUE
                    ORDER BY u.name, u.email
                    """,
                    (project_id, cp_id),
                )
            else:
                cur.execute(
                    """
                    SELECT DISTINCT u.id AS keystone_user_id,
                           u.email,
                           u.name,
                           tpa.enabled,
                           tpa.mfa_required,
                           tpa.granted_at,
                           tpa.revoked_at
                    FROM users u
                    JOIN role_assignments ra ON ra.user_id = u.id
                    JOIN projects p ON p.id = ra.project_id
                    JOIN pf9_regions pr ON pr.control_plane_id = %s
                    LEFT JOIN tenant_portal_access tpa
                        ON tpa.keystone_user_id = u.id
                        AND tpa.control_plane_id = %s
                    WHERE pr.is_enabled = TRUE AND u.enabled = TRUE
                    ORDER BY u.name, u.email
                    """,
                    (cp_id, cp_id),
                )
            rows = cur.fetchall()

    return [dict(r) for r in rows]


@router.get("/access/{cp_id}", summary="List all access rows for a CP")
async def list_access(
    cp_id: str,
    current_user: User = Depends(_require_admin),
):
    """List all tenant_portal_access rows for a control plane."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, keystone_user_id, user_name, control_plane_id, tenant_name,
                       enabled, mfa_required, notes, granted_by, granted_at,
                       revoked_by, revoked_at, created_at, updated_at
                FROM tenant_portal_access
                WHERE control_plane_id = %s
                ORDER BY created_at DESC
                """,
                (cp_id,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


@router.put("/access", summary="Grant or revoke tenant portal access for a user")
async def upsert_access(
    body: AccessUpsertRequest,
    request: Request,
    current_user: User = Depends(_require_admin),
):
    """
    Grant or revoke tenant portal access for a Keystone user.
    Writes to tenant_portal_access AND updates the Redis allowlist/blocklist key atomically.
    """
    ip = get_request_ip(request)
    now = datetime.now(timezone.utc)
    granted_by = revoked_by = None
    granted_at = revoked_at = None

    if body.enabled:
        granted_by = current_user.username
        granted_at = now
    else:
        revoked_by = current_user.username
        revoked_at = now

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO tenant_portal_access
                    (keystone_user_id, user_name, control_plane_id, tenant_name,
                     enabled, mfa_required, notes,
                     granted_by, granted_at, revoked_by, revoked_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (keystone_user_id, control_plane_id) DO UPDATE SET
                    enabled      = EXCLUDED.enabled,
                    mfa_required = EXCLUDED.mfa_required,
                    user_name    = COALESCE(EXCLUDED.user_name, tenant_portal_access.user_name),
                    tenant_name  = COALESCE(EXCLUDED.tenant_name, tenant_portal_access.tenant_name),
                    notes        = COALESCE(EXCLUDED.notes, tenant_portal_access.notes),
                    granted_by   = CASE WHEN EXCLUDED.enabled THEN EXCLUDED.granted_by
                                        ELSE tenant_portal_access.granted_by END,
                    granted_at   = CASE WHEN EXCLUDED.enabled THEN EXCLUDED.granted_at
                                        ELSE tenant_portal_access.granted_at END,
                    revoked_by   = CASE WHEN NOT EXCLUDED.enabled THEN EXCLUDED.revoked_by
                                        ELSE tenant_portal_access.revoked_by END,
                    revoked_at   = CASE WHEN NOT EXCLUDED.enabled THEN EXCLUDED.revoked_at
                                        ELSE tenant_portal_access.revoked_at END,
                    updated_at   = EXCLUDED.updated_at
                RETURNING id
                """,
                (
                    body.keystone_user_id,
                    body.user_name,
                    body.control_plane_id,
                    body.tenant_name,
                    body.enabled,
                    body.mfa_required,
                    body.notes,
                    granted_by, granted_at,
                    revoked_by, revoked_at,
                    now,
                ),
            )

        # Atomically update Redis allowed/blocked key
        try:
            r = _get_redis()
            allowed_key = f"tenant:allowed:{body.control_plane_id}:{body.keystone_user_id}"
            if body.enabled:
                r.setex(allowed_key, 300, "1")
                r.delete(f"tenant:blocked:{body.control_plane_id}:{body.keystone_user_id}")
            else:
                r.delete(allowed_key)
                r.set(f"tenant:blocked:{body.control_plane_id}:{body.keystone_user_id}", "1")
        except Exception as exc:
            logger.error("Redis key update failed for access change: %s", exc)

        log_auth_event(
            conn,
            username=current_user.username,
            action="tenant_portal_access_update",
            success=True,
            ip_address=ip,
            details=f"user={body.keystone_user_id} cp={body.control_plane_id} enabled={body.enabled}",
        )

    return {"status": "ok", "enabled": body.enabled}


class BatchAccessItem(BaseModel):
    keystone_user_id: str
    user_name: Optional[str] = None

    @field_validator("keystone_user_id")
    @classmethod
    def no_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class BatchAccessRequest(BaseModel):
    control_plane_id: str
    tenant_name: Optional[str] = None   # project/org name applied to all rows
    users: List[BatchAccessItem]
    enabled: bool
    mfa_required: Optional[bool] = False
    notes: Optional[str] = None

    @field_validator("control_plane_id")
    @classmethod
    def cp_no_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


@router.put("/access/batch", summary="Grant or revoke portal access for multiple users at once")
async def batch_upsert_access(
    body: BatchAccessRequest,
    request: Request,
    current_user: User = Depends(_require_admin),
):
    """
    Grants or revokes portal access for a list of users in one call.
    Returns a summary of how many succeeded and any per-user errors.
    """
    ip = get_request_ip(request)
    now = datetime.now(timezone.utc)
    granted_by = revoked_by = None
    granted_at = revoked_at = None
    if body.enabled:
        granted_by = current_user.username
        granted_at = now
    else:
        revoked_by = current_user.username
        revoked_at = now

    results = []
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for item in body.users:
                try:
                    cur.execute(
                        """
                        INSERT INTO tenant_portal_access
                            (keystone_user_id, user_name, control_plane_id, tenant_name,
                             enabled, mfa_required, notes,
                             granted_by, granted_at, revoked_by, revoked_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (keystone_user_id, control_plane_id) DO UPDATE SET
                            enabled      = EXCLUDED.enabled,
                            mfa_required = EXCLUDED.mfa_required,
                            user_name    = COALESCE(EXCLUDED.user_name, tenant_portal_access.user_name),
                            tenant_name  = COALESCE(EXCLUDED.tenant_name, tenant_portal_access.tenant_name),
                            notes        = COALESCE(EXCLUDED.notes, tenant_portal_access.notes),
                            granted_by   = CASE WHEN EXCLUDED.enabled THEN EXCLUDED.granted_by
                                                ELSE tenant_portal_access.granted_by END,
                            granted_at   = CASE WHEN EXCLUDED.enabled THEN EXCLUDED.granted_at
                                                ELSE tenant_portal_access.granted_at END,
                            revoked_by   = CASE WHEN NOT EXCLUDED.enabled THEN EXCLUDED.revoked_by
                                                ELSE tenant_portal_access.revoked_by END,
                            revoked_at   = CASE WHEN NOT EXCLUDED.enabled THEN EXCLUDED.revoked_at
                                                ELSE tenant_portal_access.revoked_at END,
                            updated_at   = EXCLUDED.updated_at
                        """,
                        (
                            item.keystone_user_id,
                            item.user_name,
                            body.control_plane_id,
                            body.tenant_name,
                            body.enabled,
                            body.mfa_required,
                            body.notes,
                            granted_by, granted_at,
                            revoked_by, revoked_at,
                            now,
                        ),
                    )
                    try:
                        r = _get_redis()
                        allowed_key = f"tenant:allowed:{body.control_plane_id}:{item.keystone_user_id}"
                        if body.enabled:
                            r.setex(allowed_key, 300, "1")
                            r.delete(f"tenant:blocked:{body.control_plane_id}:{item.keystone_user_id}")
                        else:
                            r.delete(allowed_key)
                            r.set(f"tenant:blocked:{body.control_plane_id}:{item.keystone_user_id}", "1")
                    except Exception as exc:
                        logger.error("Redis key update failed for %s: %s", item.keystone_user_id, exc)
                    results.append({"keystone_user_id": item.keystone_user_id, "ok": True})
                except Exception as exc:
                    logger.error("Batch access upsert failed for %s: %s", item.keystone_user_id, exc)
                    results.append({"keystone_user_id": item.keystone_user_id, "ok": False, "error": str(exc)})

        log_auth_event(
            conn,
            username=current_user.username,
            action="tenant_portal_batch_access_update",
            success=True,
            ip_address=ip,
            details=f"cp={body.control_plane_id} count={len(body.users)} enabled={body.enabled}",
        )

    succeeded = sum(1 for r in results if r["ok"])
    return {"status": "ok", "succeeded": succeeded, "total": len(body.users), "results": results}


@router.delete(
    "/sessions/{cp_id}/{keystone_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Force-terminate all active sessions for a user",
)
async def force_logout(
    cp_id: str,
    keystone_user_id: str,
    request: Request,
    current_user: User = Depends(_require_admin),
):
    """
    Scans Redis for all tenant:session:* keys matching this user and deletes them.
    Effective immediately — the user's next request returns 401.
    """
    ip = get_request_ip(request)
    r = _get_redis()
    deleted = 0

    # Scan all tenant session keys and check if they belong to this user
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="tenant:session:*", count=100)
        for key in keys:
            stored_uid = r.hget(key, "keystone_user_id")
            stored_cp = r.hget(key, "control_plane_id")
            if stored_uid == keystone_user_id and stored_cp == cp_id:
                r.delete(key)
                deleted += 1
        if cursor == 0:
            break

    with get_connection() as conn:
        log_auth_event(
            conn,
            username=current_user.username,
            action="tenant_force_logout",
            success=True,
            ip_address=ip,
            details=f"user={keystone_user_id} cp={cp_id} sessions_deleted={deleted}",
        )

    logger.info(
        "Admin %s force-logged-out user %s from CP %s (%d sessions)",
        current_user.username, keystone_user_id, cp_id, deleted,
    )


@router.get("/sessions/{cp_id}", summary="List active sessions for all users in a CP")
async def list_sessions(
    cp_id: str,
    current_user: User = Depends(_require_admin),
):
    """
    Scans Redis for all active tenant sessions belonging to this CP.
    Returns a summary: user, login time, IP, last activity inferred from TTL.
    """
    r = _get_redis()
    sessions = []

    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="tenant:session:*", count=100)
        for key in keys:
            data = r.hgetall(key)
            if data.get("control_plane_id") == cp_id:
                ttl = r.ttl(key)
                sessions.append(
                    {
                        "keystone_user_id": data.get("keystone_user_id"),
                        "username": data.get("username"),
                        "ip_address": data.get("ip_address"),
                        "created_at": data.get("created_at"),
                        "ttl_seconds_remaining": ttl,
                    }
                )
        if cursor == 0:
            break

    return sessions


@router.get("/audit/{cp_id}", summary="Paginated audit log for a CP")
async def get_audit_log(
    cp_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    keystone_user_id: Optional[str] = Query(default=None),
    current_user: User = Depends(_require_admin),
):
    """Return tenant_action_log entries for a control plane, newest first."""
    # Static parameterized SQL: IS NULL OR pattern makes keystone_user_id filter optional
    # without any string formatting — eliminates SQL injection surface entirely.
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, keystone_user_id, control_plane_id, action,
                       resource_type, resource_id, project_id, region_id,
                       ip_address, success, detail, created_at
                FROM tenant_action_log
                WHERE control_plane_id = %s
                  AND (%s::text IS NULL OR keystone_user_id = %s)
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                [cp_id, keystone_user_id, keystone_user_id, limit, offset],
            )
            rows = cur.fetchall()

            cur.execute(
                """
                SELECT count(*) FROM tenant_action_log
                WHERE control_plane_id = %s
                  AND (%s::text IS NULL OR keystone_user_id = %s)
                """,
                [cp_id, keystone_user_id, keystone_user_id],
            )
            total = cur.fetchone()["count"]

    return {"total": total, "offset": offset, "limit": limit, "items": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Branding management  (admin read + upsert)
# ---------------------------------------------------------------------------

class BrandingUpsertRequest(BaseModel):
    company_name: str = "Cloud Portal"
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: str = "#1A73E8"
    accent_color: str = "#F29900"
    support_email: Optional[str] = None
    support_url: Optional[str] = None
    welcome_message: Optional[str] = None
    footer_text: Optional[str] = None

    @field_validator("primary_color", "accent_color")
    @classmethod
    def valid_hex_color(cls, v: str) -> str:
        import re
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            raise ValueError("must be a 6-digit hex colour e.g. #1A73E8")
        return v.upper()


@router.get("/branding/{cp_id}", summary="Get branding config for a CP")
async def get_branding_admin(
    cp_id: str,
    current_user: User = Depends(_require_admin),
):
    """Return the tenant_portal_branding row for a control plane, or 404."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT control_plane_id, company_name, logo_url, favicon_url, "
                "primary_color, accent_color, support_email, support_url, "
                "welcome_message, footer_text, updated_at "
                "FROM tenant_portal_branding WHERE control_plane_id = %s",
                [cp_id],
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="branding_not_found")
    return dict(row)


@router.put("/branding/{cp_id}", summary="Upsert branding config for a CP")
async def upsert_branding(
    cp_id: str,
    body: BrandingUpsertRequest,
    request: Request,
    current_user: User = Depends(_require_admin),
):
    """Create or replace the tenant_portal_branding row for a control plane."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO tenant_portal_branding (
                    control_plane_id, company_name, logo_url, favicon_url,
                    primary_color, accent_color, support_email, support_url,
                    welcome_message, footer_text, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (control_plane_id) DO UPDATE SET
                    company_name    = EXCLUDED.company_name,
                    logo_url        = EXCLUDED.logo_url,
                    favicon_url     = EXCLUDED.favicon_url,
                    primary_color   = EXCLUDED.primary_color,
                    accent_color    = EXCLUDED.accent_color,
                    support_email   = EXCLUDED.support_email,
                    support_url     = EXCLUDED.support_url,
                    welcome_message = EXCLUDED.welcome_message,
                    footer_text     = EXCLUDED.footer_text,
                    updated_at      = now()
                RETURNING control_plane_id, updated_at
                """,
                [
                    cp_id,
                    body.company_name,
                    body.logo_url,
                    body.favicon_url,
                    body.primary_color,
                    body.accent_color,
                    body.support_email,
                    body.support_url,
                    body.welcome_message,
                    body.footer_text,
                ],
            )
            result = cur.fetchone()
    logger.info(
        "Branding upserted for CP %s by %s from %s",
        cp_id,
        current_user.username,
        get_request_ip(request),
    )
    return {"status": "ok", "control_plane_id": result["control_plane_id"], "updated_at": result["updated_at"]}


# ---------------------------------------------------------------------------
# MFA management — admin reset for a specific user
# ---------------------------------------------------------------------------

@router.delete(
    "/mfa/{cp_id}/{keystone_user_id}",
    summary="Admin: reset (delete) MFA enrollment for a specific user",
)
async def admin_reset_mfa(
    cp_id: str,
    keystone_user_id: str,
    request: Request,
    current_user: User = Depends(_require_admin),
):
    """
    Delete the tenant_portal_mfa row for a given user + control plane.

    This forces the user to re-enroll next time they log in (if MFA is
    required on their access row). The operation is logged for audit.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                DELETE FROM tenant_portal_mfa
                WHERE keystone_user_id = %s AND control_plane_id = %s
                RETURNING keystone_user_id
                """,
                [keystone_user_id, cp_id],
            )
            deleted = cur.fetchone()

    if not deleted:
        raise HTTPException(status_code=404, detail="mfa_enrollment_not_found")

    logger.info(
        "MFA reset for user %s / CP %s by admin %s from %s",
        keystone_user_id,
        cp_id,
        current_user.username,
        get_request_ip(request),
    )
    return {"status": "ok", "keystone_user_id": keystone_user_id, "control_plane_id": cp_id}

