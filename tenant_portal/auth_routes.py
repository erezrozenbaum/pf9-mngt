"""
auth_routes.py — Tenant portal authentication endpoints.

POST /tenant/auth/login   — Keystone passthrough auth → pf9-mngt JWT
POST /tenant/auth/logout  — Delete Redis session key
GET  /tenant/auth/me      — Return current user info from token

Security invariants:
  - Keystone credentials are NEVER written to DB, Redis, or logs
  - Keystone token is discarded immediately after user_id extraction
  - Only the Keystone user_id (a UUID) and derived project/region claims
    are stored in the JWT and Redis session
  - Login records in auth_audit_log use keystone_user_id only (no password)
"""

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import httpx
import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, field_validator

from db_pool import get_tenant_connection
from middleware import (
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    TENANT_TOKEN_EXPIRE_MINUTES,
    _check_rate_limit,
    _hash_token,
    _redis_session_key,
    get_tenant_context,
)
from redis_client import get_redis
from request_helpers import get_request_ip
from tenant_context import TenantContext

logger = logging.getLogger("tenant_portal.auth")

router = APIRouter(prefix="/tenant/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
# The control plane this pod serves — set at pod level, never user-supplied
TENANT_PORTAL_CP_ID = os.getenv("TENANT_PORTAL_CONTROL_PLANE_ID", "default")

# MFA mode: email_otp | totp | none
TENANT_MFA_MODE = os.getenv("TENANT_MFA_MODE", "email_otp")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def no_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    requires_mfa: bool = False
    preauth_token: Optional[str] = None  # set only when requires_mfa=True


class MeResponse(BaseModel):
    username: str
    keystone_user_id: str
    projects: List[dict]
    regions: List[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _issue_jwt(
    *,
    username: str,
    keystone_user_id: str,
    control_plane_id: str,
    project_ids: List[str],
    region_ids: List[str],
) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=TENANT_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": username,
        "role": "tenant",
        "control_plane_id": control_plane_id,
        "keystone_user_id": keystone_user_id,
        "project_ids": project_ids,
        "region_ids": region_ids,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _store_session(
    redis_client,
    token: str,
    *,
    keystone_user_id: str,
    username: str,
    control_plane_id: str,
    project_ids: List[str],
    region_ids: List[str],
    ip_address: str,
) -> None:
    token_hash = _hash_token(token)
    key = _redis_session_key(token_hash)
    session_data = {
        "keystone_user_id": keystone_user_id,
        "username": username,
        "control_plane_id": control_plane_id,
        "project_ids": json.dumps(project_ids),
        "region_ids": json.dumps(region_ids),
        "ip_address": ip_address,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client.hset(key, mapping=session_data)
    redis_client.expire(key, TENANT_TOKEN_EXPIRE_MINUTES * 60)


def _write_audit(
    conn,
    *,
    keystone_user_id: str,
    control_plane_id: str,
    action: str,
    ip_address: str,
    success: bool,
    detail: str = "",
) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO auth_audit_log
                    (username, action, success, ip_address, details)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    keystone_user_id,
                    action,
                    success,
                    ip_address,
                    detail[:500],
                ),
            )
    except Exception as exc:
        logger.error("Failed to write audit log: %s", exc)


def _keystone_auth(auth_url: str, username: str, password: str) -> dict:
    """
    Authenticate against Keystone v3 and return the response body.
    Raises HTTPException on failure.
    Credentials are never logged or stored.
    """
    payload = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {
                    "user": {
                        "name": username,
                        "domain": {"name": "Default"},
                        "password": password,
                    }
                },
            },
            "scope": {"system": {"all": True}},
        }
    }
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            resp = client.post(
                f"{auth_url.rstrip('/')}/v3/auth/tokens",
                json=payload,
            )
    except httpx.RequestError as exc:
        logger.error("Keystone connection error for %s: %s", auth_url, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="keystone_unreachable",
        )

    # Credentials are no longer needed past this point — do NOT log them
    if resp.status_code not in (200, 201):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )
    return resp.json()


def _extract_user_id(ks_body: dict) -> str:
    try:
        return ks_body["token"]["user"]["id"]
    except (KeyError, TypeError):
        logger.error("Could not extract user.id from Keystone response")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="keystone_response_malformed",
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse, summary="Tenant login via Keystone")
async def login(body: LoginRequest, request: Request):
    """
    Authenticate a tenant user against the control plane's Keystone.

    - Credentials are held in-memory only for the Keystone API call duration.
    - On success, a pf9-mngt JWT is issued with project_ids and region_ids claims.
    - If MFA is required, returns requires_mfa=True + a short-lived preauth_token
      (full JWT is NOT issued until MFA is verified).
    """
    ip = get_request_ip(request)
    redis_client = get_redis()

    # Auth-group rate limit (per IP at nginx layer + per user_id here)
    # We don't have user_id yet, so rate-limit by IP key for login
    rate_key = f"tenant:ratelimit:ip:{ip}:auth:{int(__import__('time').time()) // 60}"
    ip_count = redis_client.incr(rate_key)
    if ip_count == 1:
        redis_client.expire(rate_key, 60)
    if ip_count > 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
        )

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 1. Fetch CP record (not exposing to user — internal lookup only)
            cur.execute(
                "SELECT id, auth_url FROM tenant_cp_view WHERE id = %s AND is_enabled = TRUE",
                (TENANT_PORTAL_CP_ID,),
            )
            cp = cur.fetchone()

    if not cp:
        logger.error("Control plane %s not found or disabled", TENANT_PORTAL_CP_ID)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="portal_unavailable",
        )

    # 2. Keystone authentication — credentials discarded after this call
    ks_body = _keystone_auth(cp["auth_url"], body.username, body.password)
    keystone_user_id = _extract_user_id(ks_body)
    # Credentials and ks_body are no longer needed; Python GC will handle them

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # 3. Check allowlist (default-deny)
            cur.execute(
                """
                SELECT enabled, mfa_required
                FROM tenant_portal_access
                WHERE keystone_user_id = %s
                  AND control_plane_id = %s
                  AND enabled = TRUE
                """,
                (keystone_user_id, TENANT_PORTAL_CP_ID),
            )
            access_row = cur.fetchone()

            if not access_row:
                _write_audit(
                    conn,
                    keystone_user_id=keystone_user_id,
                    control_plane_id=TENANT_PORTAL_CP_ID,
                    action="tenant_login_denied",
                    ip_address=ip,
                    success=False,
                    detail="portal_access_denied",
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="portal_access_denied",
                )

            # 4. Derive project_ids and region_ids
            cur.execute(
                "SELECT DISTINCT project_id FROM role_assignments WHERE user_id = %s",
                (keystone_user_id,),
            )
            project_rows = cur.fetchall()
            project_ids = [r["project_id"] for r in project_rows]

            cur.execute(
                "SELECT id FROM pf9_regions WHERE control_plane_id = %s AND is_enabled = TRUE",
                (TENANT_PORTAL_CP_ID,),
            )
            region_rows = cur.fetchall()
            region_ids = [r["id"] for r in region_rows]

            if not project_ids or not region_ids:
                _write_audit(
                    conn,
                    keystone_user_id=keystone_user_id,
                    control_plane_id=TENANT_PORTAL_CP_ID,
                    action="tenant_login_denied",
                    ip_address=ip,
                    success=False,
                    detail="no_project_or_region",
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="no_accessible_resources",
                )

            # 5. MFA check
            mfa_required = access_row["mfa_required"] or TENANT_MFA_MODE != "none"

            if mfa_required:
                # Issue short-lived pre-auth token (no data access)
                preauth_token = secrets.token_urlsafe(32)
                redis_client.setex(
                    f"tenant:preauth:{preauth_token}",
                    300,  # 5-minute window to complete MFA
                    json.dumps(
                        {
                            "keystone_user_id": keystone_user_id,
                            "username": body.username,
                            "control_plane_id": TENANT_PORTAL_CP_ID,
                            "project_ids": project_ids,
                            "region_ids": region_ids,
                            "ip_address": ip,
                        }
                    ),
                )
                _write_audit(
                    conn,
                    keystone_user_id=keystone_user_id,
                    control_plane_id=TENANT_PORTAL_CP_ID,
                    action="tenant_login_mfa_required",
                    ip_address=ip,
                    success=True,
                )
                return LoginResponse(
                    access_token="",
                    expires_in=0,
                    requires_mfa=True,
                    preauth_token=preauth_token,
                )

            # 6. Issue full JWT
            token = _issue_jwt(
                username=body.username,
                keystone_user_id=keystone_user_id,
                control_plane_id=TENANT_PORTAL_CP_ID,
                project_ids=project_ids,
                region_ids=region_ids,
            )
            _store_session(
                redis_client,
                token,
                keystone_user_id=keystone_user_id,
                username=body.username,
                control_plane_id=TENANT_PORTAL_CP_ID,
                project_ids=project_ids,
                region_ids=region_ids,
                ip_address=ip,
            )
            _write_audit(
                conn,
                keystone_user_id=keystone_user_id,
                control_plane_id=TENANT_PORTAL_CP_ID,
                action="tenant_login",
                ip_address=ip,
                success=True,
            )

    return LoginResponse(
        access_token=token,
        expires_in=TENANT_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Tenant logout")
async def logout(ctx: TenantContext = Depends(get_tenant_context), request: Request = None):
    """Invalidate the current session by deleting the Redis session key."""
    token_raw = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if token_raw:
        redis_client = get_redis()
        redis_client.delete(_redis_session_key(_hash_token(token_raw)))

    with get_tenant_connection() as conn:
        _write_audit(
            conn,
            keystone_user_id=ctx.keystone_user_id,
            control_plane_id=ctx.control_plane_id,
            action="tenant_logout",
            ip_address=ctx.ip_address,
            success=True,
        )


@router.get("/me", response_model=MeResponse, summary="Current user info")
async def me(ctx: TenantContext = Depends(get_tenant_context)):
    """Return current user identity (from verified JWT — no DB call needed for basic info)."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Fetch project display names (project_id → name)
            if ctx.project_ids:
                cur.execute(
                    "SELECT id, name FROM projects WHERE id = ANY(%s)",
                    (ctx.project_ids,),
                )
                project_rows = cur.fetchall()
            else:
                project_rows = []

            # Fetch region display names (tenant must never see raw region_id)
            if ctx.region_ids:
                cur.execute(
                    "SELECT id, display_name FROM pf9_regions WHERE id = ANY(%s)",
                    (ctx.region_ids,),
                )
                region_rows = cur.fetchall()
            else:
                region_rows = []

    projects = [{"id": r["id"], "name": r["name"]} for r in project_rows]
    regions = [r["display_name"] for r in region_rows]

    return MeResponse(
        username=ctx.username,
        keystone_user_id=ctx.keystone_user_id,
        projects=projects,
        regions=regions,
    )
