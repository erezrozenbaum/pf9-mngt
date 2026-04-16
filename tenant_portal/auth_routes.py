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
import re as _re
from pydantic import BaseModel, Field, field_validator

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
# Keystone domain names: letters, digits, hyphens, underscores, dots only
_DOMAIN_RE = _re.compile(r'^[A-Za-z0-9_\-.]{1,255}$')


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=255)
    password: str = Field(..., max_length=1024)
    domain: str = Field(default="Default", max_length=255)

    @field_validator("username", "password", "domain")
    @classmethod
    def no_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v

    @field_validator("domain")
    @classmethod
    def valid_domain_name(cls, v: str) -> str:
        if not _DOMAIN_RE.match(v):
            raise ValueError(
                "domain must contain only letters, digits, hyphens, underscores, or dots"
            )
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


def _keystone_auth(auth_url: str, username: str, password: str, domain: str = "Default") -> dict:
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
                        "domain": {"name": domain},
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
    ks_body = _keystone_auth(cp["auth_url"], body.username, body.password, body.domain)
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


# ---------------------------------------------------------------------------
# P4d — MFA endpoints
# POST /tenant/auth/mfa/email-send    — send a 6-digit email OTP (email_otp mode)
# POST /tenant/auth/mfa/verify        — verify TOTP code OR email OTP, issue full JWT
# GET  /tenant/auth/mfa/setup         — get TOTP QR code for enrollment
# POST /tenant/auth/mfa/verify-setup  — confirm first TOTP code, persist secret
# ---------------------------------------------------------------------------

# Lazy import so pyotp is only required when MFA is actually used
def _pyotp():
    try:
        import pyotp
        return pyotp
    except ImportError:
        raise HTTPException(501, "MFA library not available")


class MfaEmailSendRequest(BaseModel):
    preauth_token: str


class MfaVerifyRequest(BaseModel):
    preauth_token: str
    code: Optional[str] = None          # TOTP 6-digit code OR email OTP
    backup_code: Optional[str] = None   # backup code (one-time use)


class MfaSetupRequest(BaseModel):
    preauth_token: str


class MfaVerifySetupRequest(BaseModel):
    preauth_token: str
    code: str   # First TOTP code — confirms the secret is properly enrolled


def _get_preauth(redis_client, preauth_token: str) -> dict:
    """Look up a preauth token from Redis; 401 if missing/expired."""
    raw = redis_client.get(f"tenant:preauth:{preauth_token}")
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "preauth_token_invalid_or_expired")
    return json.loads(raw)


def _consume_preauth(redis_client, preauth_token: str) -> None:
    """Delete the preauth Redis key (one-time use)."""
    redis_client.delete(f"tenant:preauth:{preauth_token}")


def _issue_full_jwt_from_preauth(preauth: dict, redis_client) -> LoginResponse:
    """Mint and store a full JWT from a validated preauth state."""
    token = _issue_jwt(
        username=preauth["username"],
        keystone_user_id=preauth["keystone_user_id"],
        control_plane_id=preauth["control_plane_id"],
        project_ids=preauth["project_ids"],
        region_ids=preauth["region_ids"],
    )
    _store_session(
        redis_client,
        token,
        keystone_user_id=preauth["keystone_user_id"],
        username=preauth["username"],
        control_plane_id=preauth["control_plane_id"],
        project_ids=preauth["project_ids"],
        region_ids=preauth["region_ids"],
        ip_address=preauth.get("ip_address", ""),
    )
    return LoginResponse(
        access_token=token,
        expires_in=TENANT_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/mfa/email-send",
    summary="Send a one-time email OTP for MFA verification",
)
async def mfa_email_send(body: MfaEmailSendRequest):
    """
    Generate a 6-digit OTP, store its SHA-256 hash in Redis under
    tenant:email_otp:<keystone_user_id> (10 min TTL), and email it to the
    tenant's registered address.  Only available in email_otp MFA mode.
    """
    if TENANT_MFA_MODE not in ("email_otp", "required"):
        raise HTTPException(400, "email_otp_not_configured")

    redis_client = get_redis()
    preauth = _get_preauth(redis_client, body.preauth_token)
    kb_user_id = preauth["keystone_user_id"]

    # Rate-limit: max 3 email sends per 10-minute window
    rate_key = f"tenant:email_otp_send:{kb_user_id}"
    sends = redis_client.incr(rate_key)
    if sends == 1:
        redis_client.expire(rate_key, 600)
    if sends > 3:
        raise HTTPException(429, "too_many_otp_requests")

    otp = secrets.randbelow(900000) + 100000          # 6-digit OTP [100000..999999]
    otp_str = str(otp)
    otp_hash = hashlib.sha256(otp_str.encode()).hexdigest()
    redis_client.setex(f"tenant:email_otp:{kb_user_id}", 600, otp_hash)  # 10-min TTL

    # Lookup email from users table
    try:
        with get_tenant_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT email FROM users WHERE id = %s", (kb_user_id,))
                row = cur.fetchone()
    except Exception:
        row = None

    email = (row or {}).get("email")
    if not email:
        logger.warning("No email found for keystone_user_id=%s — cannot send OTP", kb_user_id)
        raise HTTPException(422, "no_registered_email")

    # Send via smtp_helper (admin API is separate — inline minimal SMTP call here)
    try:
        import sys
        import importlib
        # smtp_helper lives in the admin API; tenant portal has its own smtp setup
        # Use the same env vars (SMTP_HOST/PORT/USER/PASSWORD) for simplicity
        _smtp_mod = importlib.import_module("smtp_helper") if "smtp_helper" in sys.modules else None
        if _smtp_mod:
            _smtp_mod.send_email(
                email,
                "Your one-time verification code",
                f"<p>Your verification code is: <strong>{otp_str}</strong></p>"
                f"<p>This code expires in 10 minutes. Do not share it with anyone.</p>",
            )
        else:
            logger.warning("smtp_helper not available in tenant portal process — OTP not sent")
    except Exception as exc:
        logger.error("Failed to send MFA OTP email to %s: %s", email, exc)
        # Do NOT expose whether the email send failed — the user should try the code anyway
        # (the hash is stored in Redis regardless)

    return {"message": "otp_sent", "expires_in": 600}


@router.post("/mfa/verify", response_model=LoginResponse, summary="Verify MFA code and issue full JWT")
async def mfa_verify(body: MfaVerifyRequest):
    """
    Verify a TOTP or email OTP code for a pre-authenticated session.
    On success: deletes the preauth Redis key and issues a full JWT.
    On failure: increments failure counter; 5 failures → 1-hour lockout.
    """
    redis_client = get_redis()
    preauth = _get_preauth(redis_client, body.preauth_token)
    kb_user_id = preauth["keystone_user_id"]
    cp_id = preauth.get("control_plane_id", TENANT_PORTAL_CP_ID)

    # Check lockout
    fail_key = f"tenant:mfa_fail:{kb_user_id}"
    fail_count_raw = redis_client.get(fail_key)
    fail_count = int(fail_count_raw) if fail_count_raw else 0
    if fail_count >= 5:
        raise HTTPException(429, "mfa_locked_too_many_failures")

    verified = False

    if body.backup_code:
        # Backup code path
        with get_tenant_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SET LOCAL app.tenant_keystone_user_id = %s; "
                    "SET LOCAL app.tenant_cp_id = %s;",
                    (kb_user_id, cp_id),
                )
                cur.execute(
                    "SELECT id, backup_codes, used_backup_codes FROM tenant_portal_mfa "
                    "WHERE keystone_user_id = %s AND control_plane_id = %s",
                    (kb_user_id, cp_id),
                )
                mfa_row = cur.fetchone()
        if mfa_row:
            stored_codes = mfa_row["backup_codes"] or []
            used_indexes = list(mfa_row.get("used_backup_codes") or [])
            import bcrypt
            for idx, hashed in enumerate(stored_codes):
                if idx in used_indexes:
                    continue
                try:
                    if bcrypt.checkpw(body.backup_code.upper().encode(), hashed.encode()):
                        verified = True
                        # Mark backup code as used
                        used_indexes.append(idx)
                        with get_tenant_connection() as conn2:
                            with conn2.cursor() as cur2:
                                cur2.execute(
                                    "SET LOCAL app.tenant_keystone_user_id = %s; "
                                    "SET LOCAL app.tenant_cp_id = %s;",
                                    (kb_user_id, cp_id),
                                )
                                cur2.execute(
                                    "UPDATE tenant_portal_mfa SET used_backup_codes = %s, last_used_at = now() "
                                    "WHERE keystone_user_id = %s AND control_plane_id = %s",
                                    (used_indexes, kb_user_id, cp_id),
                                )
                        break
                except Exception:
                    continue

    elif body.code:
        if TENANT_MFA_MODE in ("email_otp",):
            # Email OTP path
            stored_hash = redis_client.get(f"tenant:email_otp:{kb_user_id}")
            if stored_hash:
                expected = hashlib.sha256(body.code.encode()).hexdigest()
                if secrets.compare_digest(expected, stored_hash.decode() if isinstance(stored_hash, bytes) else stored_hash):
                    verified = True
                    redis_client.delete(f"tenant:email_otp:{kb_user_id}")
        else:
            # TOTP path
            pyotp = _pyotp()
            with get_tenant_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SET LOCAL app.tenant_keystone_user_id = %s; "
                        "SET LOCAL app.tenant_cp_id = %s;",
                        (kb_user_id, cp_id),
                    )
                    cur.execute(
                        "SELECT totp_secret FROM tenant_portal_mfa "
                        "WHERE keystone_user_id = %s AND control_plane_id = %s",
                        (kb_user_id, cp_id),
                    )
                    mfa_row = cur.fetchone()
            if mfa_row:
                totp = pyotp.TOTP(mfa_row["totp_secret"])
                if totp.verify(body.code, valid_window=1):
                    verified = True
                    # Update last_used_at
                    with get_tenant_connection() as conn2:
                        with conn2.cursor() as cur2:
                            cur2.execute(
                                "SET LOCAL app.tenant_keystone_user_id = %s; "
                                "SET LOCAL app.tenant_cp_id = %s;",
                                (kb_user_id, cp_id),
                            )
                            cur2.execute(
                                "UPDATE tenant_portal_mfa SET last_used_at = now() "
                                "WHERE keystone_user_id = %s AND control_plane_id = %s",
                                (kb_user_id, cp_id),
                            )
    else:
        raise HTTPException(400, "code_or_backup_code_required")

    if not verified:
        # Increment failure counter
        new_count = redis_client.incr(fail_key)
        if new_count == 1:
            redis_client.expire(fail_key, 3600)  # 1-hour window
        remaining = max(0, 5 - new_count)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"invalid_mfa_code — {remaining} attempts remaining before lockout",
        )

    # Success — consume preauth token and issue full JWT
    redis_client.delete(fail_key)
    _consume_preauth(redis_client, body.preauth_token)
    return _issue_full_jwt_from_preauth(preauth, redis_client)


@router.get("/mfa/setup", summary="Get TOTP enrollment QR code")
async def mfa_setup(preauth_token: str):
    """
    Generate a new TOTP secret, store it temporarily in Redis under
    tenant:mfa_pending:<keystone_user_id>, and return a QR code URL for
    the user to scan in their authenticator app.

    The secret is NOT persisted to the DB until /mfa/verify-setup confirms
    the first valid code.
    """
    redis_client = get_redis()
    preauth = _get_preauth(redis_client, preauth_token)
    kb_user_id = preauth["keystone_user_id"]

    pyotp = _pyotp()
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    # Store pending secret in Redis (5-min TTL — same as preauth window)
    redis_client.setex(f"tenant:mfa_pending:{kb_user_id}", 300, secret)

    issuer = os.getenv("TENANT_MFA_ISSUER", "PF9 Cloud Portal")
    otpauth_url = totp.provisioning_uri(name=preauth["username"], issuer_name=issuer)

    return {
        "secret": secret,
        "otpauth_url": otpauth_url,
        "qr_hint": "Scan the otpauth_url with Google Authenticator, Authy, or a compatible app.",
    }


@router.post(
    "/mfa/verify-setup",
    response_model=LoginResponse,
    summary="Confirm first TOTP code and complete MFA enrollment",
)
async def mfa_verify_setup(body: MfaVerifySetupRequest):
    """
    Validate the first TOTP code against the pending secret (stored in Redis).
    On success: persist the secret to tenant_portal_mfa, generate 8 backup codes,
    issue a full JWT, and return the backup codes (shown ONCE — never again).
    """
    import bcrypt

    redis_client = get_redis()
    preauth = _get_preauth(redis_client, body.preauth_token)
    kb_user_id = preauth["keystone_user_id"]
    cp_id = preauth.get("control_plane_id", TENANT_PORTAL_CP_ID)

    # Retrieve pending secret
    pending_secret = redis_client.get(f"tenant:mfa_pending:{kb_user_id}")
    if not pending_secret:
        raise HTTPException(400, "mfa_setup_session_expired")
    pending_secret = pending_secret.decode() if isinstance(pending_secret, bytes) else pending_secret

    pyotp = _pyotp()
    totp = pyotp.TOTP(pending_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_totp_code")

    # Generate 8 backup codes (8-char uppercase alphanumeric)
    raw_backup_codes = [secrets.token_urlsafe(6).upper()[:8] for _ in range(8)]
    hashed_backup_codes = [
        bcrypt.hashpw(c.encode(), bcrypt.gensalt()).decode() for c in raw_backup_codes
    ]

    # Persist to DB (upsert — user may re-enroll)
    with get_tenant_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SET LOCAL app.tenant_keystone_user_id = %s; "
                "SET LOCAL app.tenant_cp_id = %s;",
                (kb_user_id, cp_id),
            )
            cur.execute(
                """
                INSERT INTO tenant_portal_mfa
                    (keystone_user_id, control_plane_id, totp_secret, backup_codes,
                     enrolled_at, used_backup_codes)
                VALUES (%s, %s, %s, %s, now(), '{}')
                ON CONFLICT (keystone_user_id, control_plane_id)
                DO UPDATE SET
                    totp_secret = EXCLUDED.totp_secret,
                    backup_codes = EXCLUDED.backup_codes,
                    enrolled_at = now(),
                    used_backup_codes = '{}',
                    last_used_at = NULL
                """,
                (kb_user_id, cp_id, pending_secret, hashed_backup_codes),
            )

    # Clean up Redis pending state
    redis_client.delete(f"tenant:mfa_pending:{kb_user_id}")
    _consume_preauth(redis_client, body.preauth_token)

    jwt_response = _issue_full_jwt_from_preauth(preauth, redis_client)

    # Return backup codes in the response (plaintext, ONE TIME ONLY)
    return {
        **jwt_response.model_dump(),
        "backup_codes": raw_backup_codes,
        "backup_codes_note": (
            "Save these backup codes now — they will NOT be shown again. "
            "Each code can only be used once."
        ),
    }

