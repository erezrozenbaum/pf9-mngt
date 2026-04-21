"""
middleware.py — Security middleware for the tenant portal.

Provides:
  verify_tenant_token()   FastAPI dependency — decodes + validates JWT,
                          checks Redis session, enforces role == "tenant",
                          optional IP binding, per-user rate limiting.
  get_tenant_context()    FastAPI dependency — thin alias used by route
                          handlers to receive a TenantContext.
  inject_rls_vars()       Helper used by DB-accessing routes to set the
                          PostgreSQL session variables required by RLS.
"""

import hashlib
import logging
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from redis_client import get_redis
from request_helpers import get_request_ip
from secret_helper import read_secret
from tenant_context import TenantContext

logger = logging.getLogger("tenant_portal.middleware")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_jwt_raw = read_secret("jwt_secret", env_var="JWT_SECRET_KEY")
if not _jwt_raw:
    import secrets as _sec

    _jwt_raw = _sec.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET_KEY not set — generated ephemeral key. "
        "Sessions will be invalidated on restart."
    )
JWT_SECRET_KEY = _jwt_raw
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Token expiry — default 60 min (shorter than admin 480 min)
TENANT_TOKEN_EXPIRE_MINUTES = int(os.getenv("TENANT_TOKEN_EXPIRE_MINUTES", "60"))

# IP binding mode: strict | warn | off
TENANT_IP_BINDING = os.getenv("TENANT_IP_BINDING", "warn").lower()

# Rate limits (per user per minute)
_RL_READ = int(os.getenv("TENANT_RL_READ_PER_MIN", "60"))
_RL_AUTH = int(os.getenv("TENANT_RL_AUTH_PER_MIN", "5"))

security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _redis_session_key(token_hash: str) -> str:
    return f"tenant:session:{token_hash}"


def _check_rate_limit(redis_client, user_id: str, group: str, limit: int) -> None:
    """Increment per-user per-minute counter; raise 429 if limit exceeded."""
    bucket = int(time.time()) // 60
    key = f"tenant:ratelimit:{user_id}:{group}:{bucket}"
    count = redis_client.incr(key)
    if count == 1:
        redis_client.expire(key, 60)
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
        )


# ---------------------------------------------------------------------------
# Core dependency
# ---------------------------------------------------------------------------

async def verify_tenant_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> TenantContext:
    """
    FastAPI dependency: validate the Bearer JWT and return a TenantContext.

    Checks (in order):
      1. Token present and Bearer scheme
      2. JWT signature valid + not expired
      3. role == "tenant" (admin JWTs rejected here even if signature valid)
      4. Redis session key exists (covers logout / admin force-logout)
      5. IP binding (strict / warn / off)
      6. Per-user rate limit (read group)
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # 1. Decode + verify JWT
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Require role == "tenant" — admin JWTs are explicitly rejected
    if payload.get("role") != "tenant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant_role_required",
        )

    # 3. Required claims
    keystone_user_id = payload.get("keystone_user_id")
    control_plane_id = payload.get("control_plane_id")
    project_ids = payload.get("project_ids") or []
    region_ids = payload.get("region_ids") or []
    username = payload.get("sub", "")
    portal_role = payload.get("portal_role", "manager")

    if not keystone_user_id or not control_plane_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="malformed_token",
        )

    # 4. Redis session check
    redis_client = get_redis()
    token_hash = _hash_token(token)
    session_key = _redis_session_key(token_hash)
    if not redis_client.exists(session_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session_expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 5. IP binding
    client_ip = get_request_ip(request)
    if TENANT_IP_BINDING != "off":
        stored_ip = redis_client.hget(session_key, "ip_address")
        if stored_ip and stored_ip != client_ip:
            if TENANT_IP_BINDING == "strict":
                logger.warning(
                    "IP mismatch for user %s: stored=%s current=%s — rejecting (strict)",
                    keystone_user_id,
                    stored_ip,
                    client_ip,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="ip_binding_violation",
                )
            else:  # warn mode
                logger.warning(
                    "IP mismatch for user %s: stored=%s current=%s (warn mode, allowing)",
                    keystone_user_id,
                    stored_ip,
                    client_ip,
                )

    # 6. Per-user rate limit (read group)
    _check_rate_limit(redis_client, keystone_user_id, "read", _RL_READ)

    return TenantContext(
        keystone_user_id=keystone_user_id,
        username=username,
        control_plane_id=control_plane_id,
        project_ids=project_ids,
        region_ids=region_ids,
        ip_address=client_ip,
        portal_role=portal_role,
    )


# Alias for use in route handlers
get_tenant_context = verify_tenant_token


def require_manager_role(ctx: TenantContext = Depends(verify_tenant_token)) -> TenantContext:
    """
    FastAPI dependency: reject requests from observer-role users.
    Apply to all write/execute routes in the tenant portal.
    """
    if ctx.portal_role != "manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="observer_role_cannot_write",
        )
    return ctx


# ---------------------------------------------------------------------------
# RLS session-variable injection
# ---------------------------------------------------------------------------

def inject_rls_vars(cur, ctx: TenantContext) -> None:
    """
    Set PostgreSQL session variables required by the RLS policies before
    any data query. Must be called at the start of every DB transaction that
    reads from servers / volumes / snapshots / snapshot_records / restore_jobs.

    Uses SET LOCAL so the variables are scoped to the current transaction only
    and are reset automatically on COMMIT/ROLLBACK.
    """
    cur.execute(
        "SET LOCAL app.tenant_project_ids = %s; "
        "SET LOCAL app.tenant_region_ids   = %s; "
        "SET LOCAL app.tenant_keystone_user_id = %s; "
        "SET LOCAL app.tenant_cp_id = %s;",
        (
            ctx.project_ids_csv,
            ctx.region_ids_csv,
            ctx.keystone_user_id,
            ctx.control_plane_id,
        ),
    )
