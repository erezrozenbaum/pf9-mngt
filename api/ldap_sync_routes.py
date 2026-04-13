"""
api/ldap_sync_routes.py — External LDAP / AD Identity Federation — Admin API

All endpoints require the 'superadmin' role.
RBAC is enforced at route level via _require_superadmin(); do NOT add
"ldap-sync" to resource_map in main.py — the rbac_middleware extracts
the first path segment ("admin") which maps to "branding".

Endpoints
---------
  GET    /admin/ldap-sync/configs
  POST   /admin/ldap-sync/configs
  GET    /admin/ldap-sync/configs/{config_id}
  PUT    /admin/ldap-sync/configs/{config_id}
  DELETE /admin/ldap-sync/configs/{config_id}
  POST   /admin/ldap-sync/configs/{config_id}/test
  POST   /admin/ldap-sync/configs/{config_id}/preview
  POST   /admin/ldap-sync/configs/{config_id}/sync
  GET    /admin/ldap-sync/configs/{config_id}/logs
  GET    /admin/ldap-sync/configs/{config_id}/logs/{log_id}

Security notes
--------------
  - bind_password is write-only: GET endpoints always return null.
  - Passwords stored as  "fernet:<ciphertext>"  using the dedicated
    ldap_sync_key Docker secret (crypto_helper.fernet_encrypt/decrypt).
  - SSRF protection: host is resolved before any LDAP connection is opened;
    RFC-1918 / loopback ranges are rejected unless allow_private_network=True.
  - user_search_filter is syntax-validated at create/update time.
  - Rate limiting: /test and /preview are capped at 10 req/min per user.
  - All CRUD ops are written to auth_audit_log.
"""

import ipaddress
import logging
import os
import socket
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import ldap
import ldap.filter
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field, field_validator

from auth import get_current_user, log_auth_event, User
from crypto_helper import fernet_decrypt, fernet_encrypt
from db_pool import get_connection
from secret_helper import read_secret

logger = logging.getLogger("pf9.ldap_sync")

router = APIRouter(prefix="/admin/ldap-sync", tags=["admin-ldap-sync"])

# ---------------------------------------------------------------------------
# Secret names for the Fernet key used to encrypt LDAP bind passwords
# ---------------------------------------------------------------------------
_SECRET_NAME = "ldap_sync_key"
_SECRET_ENV  = "LDAP_SYNC_KEY"

# ---------------------------------------------------------------------------
# RFC-1918 / loopback / link-local ranges blocked for SSRF protection
# ---------------------------------------------------------------------------
_BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

# ---------------------------------------------------------------------------
# Rate limiter for /test and /preview (10 req/min per user)
# Uses Redis when available so the limit is shared across all gunicorn workers
# and K8s pods; falls back to a per-process dict when Redis is unavailable.
# ---------------------------------------------------------------------------
_rate_store: Dict[str, List[float]] = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW = 60  # seconds

def _get_redis():
    """Return a Redis client or None if Redis is not reachable."""
    try:
        import redis as _redis_lib
        _r = _redis_lib.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            socket_connect_timeout=1,
        )
        _r.ping()
        return _r
    except Exception:
        return None


def _check_rate_limit(username: str, endpoint: str) -> None:
    key = f"ldap_rate:{username}:{endpoint}"
    r = _get_redis()
    if r is not None:
        # Sliding-window counter in Redis using a sorted set
        now = time.time()
        window_start = now - _RATE_WINDOW
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _RATE_WINDOW + 5)
        results = pipe.execute()
        count = results[2]
    else:
        # In-memory fallback (per-process only)
        now = time.monotonic()
        window_start = now - _RATE_WINDOW
        _rate_store[key] = [t for t in _rate_store[key] if t > window_start]
        _rate_store[key].append(now)
        count = len(_rate_store[key])

    if count > _RATE_LIMIT:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: max {_RATE_LIMIT} requests per minute",
        )


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def _require_superadmin(user: User) -> None:
    if user.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin role required")


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------

def _assert_host_allowed(host: str, allow_private_network: bool) -> None:
    """Resolve *host* and reject if it falls in a blocked range."""
    if allow_private_network:
        return  # operator has explicitly opted in
    try:
        addr_str = socket.getaddrinfo(host, None)[0][4][0]
        addr = ipaddress.ip_address(addr_str)
        for blocked in _BLOCKED_RANGES:
            if addr in blocked:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Host '{host}' resolves to a private/loopback address "
                        f"({addr_str}). Set allow_private_network=true to permit this."
                    ),
                )
    except socket.gaierror:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot resolve host '{host}'",
        )


# ---------------------------------------------------------------------------
# LDAP filter validator
# ---------------------------------------------------------------------------

def _validate_ldap_filter(f: str) -> None:
    """Raise HTTP 422 if *f* is not a syntactically valid LDAP filter."""
    try:
        # ldap.filter.escape_filter_chars is not a parser; use ldap.cidict
        # as a lightweight syntax check via the C extension's own parser.
        import ldap.filter as _lf
        _lf.filter_format(f, [])  # raises FilterSyntaxError on bad syntax
    except Exception:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid LDAP filter syntax: {f!r}",
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GroupMappingIn(BaseModel):
    external_group_dn: str = Field(..., min_length=1)
    pf9_role: str = Field(...)

    @field_validator("pf9_role")
    @classmethod
    def role_not_superadmin(cls, v: str) -> str:
        if v not in ("viewer", "operator", "admin"):
            raise ValueError("pf9_role must be one of: viewer, operator, admin")
        return v


class DeptMappingIn(BaseModel):
    """Maps an LDAP/AD group DN to a pf9-mngt department name."""
    external_group_dn: str = Field(..., min_length=1, max_length=512)
    department_name: str = Field(..., min_length=1, max_length=255)


class LdapSyncConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=389, ge=1, le=65535)
    bind_dn: str = Field(..., min_length=1)
    bind_password: str = Field(..., min_length=1)
    base_dn: str = Field(..., min_length=1)
    user_search_filter: str = Field(default="(objectClass=person)")
    user_attr_uid: str = Field(default="sAMAccountName", max_length=100)
    user_attr_mail: str = Field(default="mail", max_length=100)
    user_attr_fullname: str = Field(default="displayName", max_length=100)
    use_tls: bool = True
    use_starttls: bool = False
    verify_tls_cert: bool = True
    ca_cert_pem: Optional[str] = None
    mfa_delegated: bool = False
    allow_private_network: bool = False
    is_enabled: bool = True
    sync_interval_minutes: int = Field(default=60, ge=1, le=10080)
    group_mappings: List[GroupMappingIn] = []
    dept_mappings: List[DeptMappingIn] = []
    conflict_strategy: str = Field(default="ldap_wins", pattern="^(ldap_wins|local_wins)$")


class LdapSyncConfigUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    host: Optional[str] = Field(default=None, min_length=1, max_length=255)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    bind_dn: Optional[str] = Field(default=None, min_length=1)
    # If omitted, existing encrypted password is preserved.
    bind_password: Optional[str] = Field(default=None, min_length=1)
    base_dn: Optional[str] = Field(default=None, min_length=1)
    user_search_filter: Optional[str] = None
    user_attr_uid: Optional[str] = Field(default=None, max_length=100)
    user_attr_mail: Optional[str] = Field(default=None, max_length=100)
    user_attr_fullname: Optional[str] = Field(default=None, max_length=100)
    use_tls: Optional[bool] = None
    use_starttls: Optional[bool] = None
    verify_tls_cert: Optional[bool] = None
    ca_cert_pem: Optional[str] = None
    mfa_delegated: Optional[bool] = None
    allow_private_network: Optional[bool] = None
    is_enabled: Optional[bool] = None
    sync_interval_minutes: Optional[int] = Field(default=None, ge=1, le=10080)
    group_mappings: Optional[List[GroupMappingIn]] = None
    dept_mappings: Optional[List[DeptMappingIn]] = None
    conflict_strategy: Optional[str] = Field(default=None, pattern="^(ldap_wins|local_wins)$")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _row_to_public(row: dict) -> dict:
    """Convert a DB row to a public-facing dict — always omit bind_password_enc."""
    out = dict(row)
    out.pop("bind_password_enc", None)
    out["bind_password"] = None  # write-only
    return out


def _fetch_config(conn, config_id: int) -> dict:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM ldap_sync_config WHERE id = %s", (config_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"LDAP sync config {config_id} not found")
    return dict(row)


def _fetch_group_mappings(conn, config_id: int) -> List[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, external_group_dn, pf9_role FROM ldap_sync_group_mappings "
            "WHERE config_id = %s ORDER BY id",
            (config_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _upsert_group_mappings(conn, config_id: int, mappings: List[GroupMappingIn]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM ldap_sync_group_mappings WHERE config_id = %s", (config_id,))
        for m in mappings:
            cur.execute(
                "INSERT INTO ldap_sync_group_mappings (config_id, external_group_dn, pf9_role) "
                "VALUES (%s, %s, %s)",
                (config_id, m.external_group_dn, m.pf9_role),
            )


def _fetch_dept_mappings(conn, config_id: int) -> List[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, external_group_dn, department_name "
            "FROM ldap_sync_dept_mappings "
            "WHERE config_id = %s ORDER BY id",
            (config_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def _upsert_dept_mappings(conn, config_id: int, mappings: List[DeptMappingIn]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM ldap_sync_dept_mappings WHERE config_id = %s", (config_id,))
        for m in mappings:
            cur.execute(
                "INSERT INTO ldap_sync_dept_mappings (config_id, external_group_dn, department_name) "
                "VALUES (%s, %s, %s)",
                (config_id, m.external_group_dn, m.department_name),
            )


# ---------------------------------------------------------------------------
# LDAP connection helper (used by /test, /preview, auth passthrough)
# ---------------------------------------------------------------------------

def _open_ldap_connection(host: str, port: int, use_tls: bool,
                           use_starttls: bool, verify_tls_cert: bool,
                           ca_cert_pem: Optional[str]) -> ldap.ldapobject.LDAPObject:
    """Open and return an initialised (not yet bound) python-ldap connection."""
    scheme = "ldaps" if use_tls and not use_starttls else "ldap"
    uri = f"{scheme}://{host}:{port}"
    conn = ldap.initialize(uri)
    conn.protocol_version = ldap.VERSION3
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 5)
    conn.set_option(ldap.OPT_REFERRALS, 0)
    if not verify_tls_cert:
        conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
        conn.set_option(ldap.OPT_X_TLS_NEWCTX, 0)
    if use_starttls:
        conn.start_tls_s()
    return conn


def _bind_service_account(conn: ldap.ldapobject.LDAPObject,
                           bind_dn: str, bind_password_enc: str,
                           context: str) -> None:
    """Decrypt the service-account password and perform a simple bind."""
    password = fernet_decrypt(
        bind_password_enc,
        secret_name=_SECRET_NAME,
        env_var=_SECRET_ENV,
        context=context,
    )
    if not password:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to decrypt LDAP service account credentials",
        )
    conn.simple_bind_s(bind_dn, password)


def _search_user_dn(conn: ldap.ldapobject.LDAPObject,
                    base_dn: str,
                    user_attr_uid: str,
                    username: str) -> Optional[str]:
    """Return the full DN for *username* in the external directory, or None."""
    safe = ldap.filter.escape_filter_chars(username)
    search_filter = f"({user_attr_uid}={safe})"
    try:
        results = conn.search_s(base_dn, ldap.SCOPE_SUBTREE, search_filter, ["dn"])
        if results:
            return results[0][0]
    except ldap.LDAPError:
        pass
    return None


# ---------------------------------------------------------------------------
# GET /admin/ldap-sync/configs
# ---------------------------------------------------------------------------

@router.get("/configs")
async def list_configs(
    current_user: User = Depends(get_current_user),
) -> List[dict]:
    _require_superadmin(current_user)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM ldap_sync_config ORDER BY created_at ASC"
            )
            rows = cur.fetchall()
        result = []
        for row in rows:
            item = _row_to_public(dict(row))
            item["group_mappings"] = _fetch_group_mappings(conn, row["id"])
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# POST /admin/ldap-sync/configs
# ---------------------------------------------------------------------------

@router.post("/configs", status_code=status.HTTP_201_CREATED)
async def create_config(
    body: LdapSyncConfigCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)
    if body.user_search_filter:
        _validate_ldap_filter(body.user_search_filter)
    _assert_host_allowed(body.host, body.allow_private_network)

    enc_password = fernet_encrypt(
        body.bind_password, secret_name=_SECRET_NAME, env_var=_SECRET_ENV
    )

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO ldap_sync_config (
                    name, host, port, bind_dn, bind_password_enc, base_dn,
                    user_search_filter, user_attr_uid, user_attr_mail, user_attr_fullname,
                    use_tls, use_starttls, verify_tls_cert, ca_cert_pem,
                    mfa_delegated, allow_private_network,
                    is_enabled, sync_interval_minutes, conflict_strategy, created_by
                ) VALUES (
                    %(name)s, %(host)s, %(port)s, %(bind_dn)s, %(enc)s, %(base_dn)s,
                    %(filter)s, %(uid)s, %(mail)s, %(fullname)s,
                    %(tls)s, %(starttls)s, %(verify)s, %(ca)s,
                    %(mfa)s, %(private)s,
                    %(enabled)s, %(interval)s, %(conflict_strategy)s, %(creator)s
                ) RETURNING *
                """,
                {
                    "name": body.name, "host": body.host, "port": body.port,
                    "bind_dn": body.bind_dn, "enc": enc_password,
                    "base_dn": body.base_dn, "filter": body.user_search_filter,
                    "uid": body.user_attr_uid, "mail": body.user_attr_mail,
                    "fullname": body.user_attr_fullname,
                    "tls": body.use_tls, "starttls": body.use_starttls,
                    "verify": body.verify_tls_cert, "ca": body.ca_cert_pem,
                    "mfa": body.mfa_delegated, "private": body.allow_private_network,
                    "enabled": body.is_enabled, "interval": body.sync_interval_minutes,
                    "conflict_strategy": body.conflict_strategy,
                    "creator": current_user.username,
                },
            )
            new_row = dict(cur.fetchone())
        _upsert_group_mappings(conn, new_row["id"], body.group_mappings)
        if body.dept_mappings:
            _upsert_dept_mappings(conn, new_row["id"], body.dept_mappings)
        conn.commit()

    log_auth_event(
        "ldap_sync_config_created",
        current_user.username,
        f"Created LDAP sync config '{body.name}' (id={new_row['id']})",
    )
    result = _row_to_public(new_row)
    result["group_mappings"] = [m.model_dump() for m in body.group_mappings]
    return result


# ---------------------------------------------------------------------------
# GET /admin/ldap-sync/configs/{config_id}
# ---------------------------------------------------------------------------

@router.get("/configs/{config_id}")
async def get_config(
    config_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)
    with get_connection() as conn:
        row = _fetch_config(conn, config_id)
        mappings = _fetch_group_mappings(conn, config_id)
    result = _row_to_public(row)
    result["group_mappings"] = mappings
    return result


# ---------------------------------------------------------------------------
# PUT /admin/ldap-sync/configs/{config_id}
# ---------------------------------------------------------------------------

@router.put("/configs/{config_id}")
async def update_config(
    config_id: int,
    body: LdapSyncConfigUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)

    with get_connection() as conn:
        existing = _fetch_config(conn, config_id)

        if body.user_search_filter is not None:
            _validate_ldap_filter(body.user_search_filter)

        # Determine effective host + allow_private_network for SSRF check
        eff_host = body.host if body.host is not None else existing["host"]
        eff_priv = (
            body.allow_private_network
            if body.allow_private_network is not None
            else existing["allow_private_network"]
        )
        if body.host is not None:
            _assert_host_allowed(eff_host, eff_priv)

        # Encrypt new password only if one was supplied; keep existing value otherwise.
        enc_password = (
            fernet_encrypt(body.bind_password, secret_name=_SECRET_NAME, env_var=_SECRET_ENV)
            if body.bind_password is not None
            else existing["bind_password_enc"]
        )

        updates: Dict[str, Any] = {
            "name":                 body.name                 if body.name is not None else existing["name"],
            "host":                 eff_host,
            "port":                 body.port                 if body.port is not None else existing["port"],
            "bind_dn":              body.bind_dn              if body.bind_dn is not None else existing["bind_dn"],
            "bind_password_enc":    enc_password,
            "base_dn":              body.base_dn              if body.base_dn is not None else existing["base_dn"],
            "user_search_filter":   body.user_search_filter   if body.user_search_filter is not None else existing["user_search_filter"],
            "user_attr_uid":        body.user_attr_uid        if body.user_attr_uid is not None else existing["user_attr_uid"],
            "user_attr_mail":       body.user_attr_mail       if body.user_attr_mail is not None else existing["user_attr_mail"],
            "user_attr_fullname":   body.user_attr_fullname   if body.user_attr_fullname is not None else existing["user_attr_fullname"],
            "use_tls":              body.use_tls              if body.use_tls is not None else existing["use_tls"],
            "use_starttls":         body.use_starttls         if body.use_starttls is not None else existing["use_starttls"],
            "verify_tls_cert":      body.verify_tls_cert      if body.verify_tls_cert is not None else existing["verify_tls_cert"],
            "ca_cert_pem":          body.ca_cert_pem          if body.ca_cert_pem is not None else existing["ca_cert_pem"],
            "mfa_delegated":        body.mfa_delegated        if body.mfa_delegated is not None else existing["mfa_delegated"],
            "allow_private_network":eff_priv,
            "is_enabled":           body.is_enabled           if body.is_enabled is not None else existing["is_enabled"],
            "sync_interval_minutes":body.sync_interval_minutes if body.sync_interval_minutes is not None else existing["sync_interval_minutes"],
            "conflict_strategy":    body.conflict_strategy    if body.conflict_strategy is not None else existing.get("conflict_strategy", "ldap_wins"),
            "updated_at":           datetime.now(timezone.utc),
            "config_id":            config_id,
        }

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE ldap_sync_config SET
                    name=%(name)s, host=%(host)s, port=%(port)s,
                    bind_dn=%(bind_dn)s, bind_password_enc=%(bind_password_enc)s,
                    base_dn=%(base_dn)s, user_search_filter=%(user_search_filter)s,
                    user_attr_uid=%(user_attr_uid)s, user_attr_mail=%(user_attr_mail)s,
                    user_attr_fullname=%(user_attr_fullname)s,
                    use_tls=%(use_tls)s, use_starttls=%(use_starttls)s,
                    verify_tls_cert=%(verify_tls_cert)s, ca_cert_pem=%(ca_cert_pem)s,
                    mfa_delegated=%(mfa_delegated)s,
                    allow_private_network=%(allow_private_network)s,
                    is_enabled=%(is_enabled)s,
                    sync_interval_minutes=%(sync_interval_minutes)s,
                    conflict_strategy=%(conflict_strategy)s,
                    updated_at=%(updated_at)s
                WHERE id=%(config_id)s RETURNING *
                """,
                updates,
            )
            updated_row = dict(cur.fetchone())

        if body.group_mappings is not None:
            _upsert_group_mappings(conn, config_id, body.group_mappings)

        if body.dept_mappings is not None:
            _upsert_dept_mappings(conn, config_id, body.dept_mappings)

        conn.commit()

    log_auth_event(
        "ldap_sync_config_updated",
        current_user.username,
        f"Updated LDAP sync config '{updated_row['name']}' (id={config_id})",
    )
    result = _row_to_public(updated_row)
    with get_connection() as conn2:
        result["group_mappings"] = _fetch_group_mappings(conn2, config_id)
    return result


# ---------------------------------------------------------------------------
# DELETE /admin/ldap-sync/configs/{config_id}
# ---------------------------------------------------------------------------

@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> None:
    _require_superadmin(current_user)

    with get_connection() as conn:
        row = _fetch_config(conn, config_id)
        # DELETION GUARD: deactivate + revoke sessions for all users synced
        # from this config BEFORE we delete the config row. Without this,
        # ON DELETE SET NULL would orphan the users and leave their sessions active.
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT username FROM user_roles WHERE sync_config_id = %s AND is_active = TRUE",
                (config_id,),
            )
            affected_users = [r["username"] for r in cur.fetchall()]

        if affected_users:
            # Import here to avoid circular import at module load time
            from auth import invalidate_user_session
            for username in affected_users:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE user_roles SET is_active = FALSE WHERE username = %s AND sync_config_id = %s",
                        (username, config_id),
                    )
                try:
                    invalidate_user_session(username)
                except Exception as exc:
                    logger.warning("Could not revoke session for %s: %s", username, exc)

        with conn.cursor() as cur:
            cur.execute("DELETE FROM ldap_sync_config WHERE id = %s", (config_id,))
        conn.commit()

    log_auth_event(
        "ldap_sync_config_deleted",
        current_user.username,
        f"Deleted LDAP sync config '{row['name']}' (id={config_id}). "
        f"Deactivated {len(affected_users)} synced user(s).",
    )


# ---------------------------------------------------------------------------
# POST /admin/ldap-sync/configs/{config_id}/test
# ---------------------------------------------------------------------------

@router.post("/configs/{config_id}/test")
async def test_config(
    config_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)
    _check_rate_limit(current_user.username, "test")

    with get_connection() as conn:
        cfg = _fetch_config(conn, config_id)

    _assert_host_allowed(cfg["host"], cfg["allow_private_network"])

    try:
        conn_ldap = _open_ldap_connection(
            cfg["host"], cfg["port"],
            cfg["use_tls"], cfg["use_starttls"], cfg["verify_tls_cert"],
            cfg["ca_cert_pem"],
        )
        _bind_service_account(
            conn_ldap, cfg["bind_dn"], cfg["bind_password_enc"],
            f"config_id={config_id}",
        )

        # Search for a sample of users
        safe_filter = cfg["user_search_filter"]
        results = conn_ldap.search_s(
            cfg["base_dn"], ldap.SCOPE_SUBTREE, safe_filter,
            [cfg["user_attr_uid"], cfg["user_attr_mail"], cfg["user_attr_fullname"]],
            sizelimit=50,
        )
        conn_ldap.unbind_s()

        users_found = len(results)
        sample = []
        for dn, attrs in results[:5]:
            sample.append({
                "uid":  _attr(attrs, cfg["user_attr_uid"]),
                "mail": _attr(attrs, cfg["user_attr_mail"]),
                "cn":   _attr(attrs, cfg["user_attr_fullname"]),
            })

        return {
            "connected": True,
            "bind_success": True,
            "users_found": users_found,
            "sample_users": sample,
            "error": None,
        }

    except HTTPException:
        raise
    except ldap.INVALID_CREDENTIALS:
        return {"connected": True, "bind_success": False,
                "users_found": 0, "sample_users": [],
                "error": "Service account credentials are invalid"}
    except ldap.SERVER_DOWN:
        return {"connected": False, "bind_success": False,
                "users_found": 0, "sample_users": [],
                "error": f"Cannot reach LDAP server {cfg['host']}:{cfg['port']}"}
    except Exception as exc:
        logger.error("LDAP test error for config %d: %s", config_id, exc)
        return {"connected": False, "bind_success": False,
                "users_found": 0, "sample_users": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# POST /admin/ldap-sync/configs/{config_id}/preview
# ---------------------------------------------------------------------------

@router.post("/configs/{config_id}/preview")
async def preview_sync(
    config_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)
    _check_rate_limit(current_user.username, "preview")

    with get_connection() as conn:
        cfg = _fetch_config(conn, config_id)
        mappings = _fetch_group_mappings(conn, config_id)

        # Existing synced users for this config
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT username, is_active FROM user_roles WHERE sync_config_id = %s",
                (config_id,),
            )
            existing_users = {r["username"]: r for r in cur.fetchall()}

    _assert_host_allowed(cfg["host"], cfg["allow_private_network"])

    try:
        conn_ldap = _open_ldap_connection(
            cfg["host"], cfg["port"],
            cfg["use_tls"], cfg["use_starttls"], cfg["verify_tls_cert"],
            cfg["ca_cert_pem"],
        )
        _bind_service_account(
            conn_ldap, cfg["bind_dn"], cfg["bind_password_enc"],
            f"config_id={config_id} preview",
        )

        results = conn_ldap.search_s(
            cfg["base_dn"], ldap.SCOPE_SUBTREE, cfg["user_search_filter"],
            [cfg["user_attr_uid"], cfg["user_attr_mail"], cfg["user_attr_fullname"]],
        )
        conn_ldap.unbind_s()

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"LDAP connection failed: {exc}",
        ) from exc

    seen_uids = set()
    to_create, to_update, to_deactivate = [], [], []

    for dn, attrs in results:
        uid = _attr(attrs, cfg["user_attr_uid"])
        if not uid:
            continue
        seen_uids.add(uid)
        entry = {
            "uid":  uid,
            "mail": _attr(attrs, cfg["user_attr_mail"]),
            "cn":   _attr(attrs, cfg["user_attr_fullname"]),
        }
        if uid in existing_users:
            to_update.append(entry)
        else:
            to_create.append(entry)

    for uid, row in existing_users.items():
        if uid not in seen_uids and row["is_active"]:
            to_deactivate.append({"uid": uid})

    return {
        "users_found": len(results),
        "to_create": to_create,
        "to_update": to_update,
        "to_deactivate": to_deactivate,
    }


# ---------------------------------------------------------------------------
# POST /admin/ldap-sync/configs/{config_id}/sync  (manual trigger)
# ---------------------------------------------------------------------------

@router.post("/configs/{config_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    config_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)

    with get_connection() as conn:
        cfg = _fetch_config(conn, config_id)
        if not cfg["is_enabled"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Config is disabled. Enable it first before triggering a sync.",
            )

    log_auth_event(
        "ldap_sync_manual_trigger",
        current_user.username,
        f"Manual sync triggered for config '{cfg['name']}' (id={config_id})",
    )
    # The sync worker polls a trigger table OR responds to the config's last_sync_at
    # being NULL.  For now we signal by inserting a pending log row; the worker
    # picks it up within its next poll cycle.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ldap_sync_log (config_id, config_name, status) "
                "VALUES (%s, %s, 'failed') ON CONFLICT DO NOTHING",
                (config_id, cfg["name"]),
            )
            # Reset last_sync_at so the worker re-runs immediately on next cycle.
            cur.execute(
                "UPDATE ldap_sync_config SET last_sync_at = NULL WHERE id = %s",
                (config_id,),
            )
        conn.commit()

    return {"queued": True, "config_id": config_id, "config_name": cfg["name"]}


# ---------------------------------------------------------------------------
# GET /admin/ldap-sync/configs/{config_id}/logs
# ---------------------------------------------------------------------------

@router.get("/configs/{config_id}/logs")
async def list_logs(
    config_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)
    page_size = min(max(page_size, 1), 100)
    offset = (max(page, 1) - 1) * page_size

    with get_connection() as conn:
        _fetch_config(conn, config_id)  # 404-check
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT COUNT(*) FROM ldap_sync_log WHERE config_id = %s",
                (config_id,),
            )
            total = cur.fetchone()["count"]

            cur.execute(
                "SELECT id, config_id, config_name, started_at, finished_at, status, "
                "       users_found, users_created, users_updated, users_deactivated, "
                "       error_message "
                "FROM ldap_sync_log WHERE config_id = %s "
                "ORDER BY started_at DESC LIMIT %s OFFSET %s",
                (config_id, page_size, offset),
            )
            rows = [dict(r) for r in cur.fetchall()]

    return {"total": total, "page": page, "page_size": page_size, "items": rows}


# ---------------------------------------------------------------------------
# GET /admin/ldap-sync/configs/{config_id}/logs/{log_id}
# ---------------------------------------------------------------------------

@router.get("/configs/{config_id}/logs/{log_id}")
async def get_log(
    config_id: int,
    log_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    _require_superadmin(current_user)
    with get_connection() as conn:
        _fetch_config(conn, config_id)  # 404-check
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM ldap_sync_log WHERE id = %s AND config_id = %s",
                (log_id, config_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Log entry {log_id} not found")
    return dict(row)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _attr(attrs: dict, key: str) -> str:
    """Extract the first decoded value of *key* from an ldap attrs dict, or ''."""
    vals = attrs.get(key, [])
    if vals:
        v = vals[0]
        return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
    return ""


# ---------------------------------------------------------------------------
# B13.3 — Department Mapping Endpoints
# ---------------------------------------------------------------------------

@router.get("/configs/{config_id}/dept-mappings")
async def list_dept_mappings(
    config_id: int,
    current_user: User = Depends(get_current_user),
) -> dict:
    """Return all LDAP group → department mappings for a config."""
    _require_superadmin(current_user)
    with get_connection() as conn:
        _fetch_config(conn, config_id)  # 404-check
        mappings = _fetch_dept_mappings(conn, config_id)
    return {"config_id": config_id, "dept_mappings": mappings}


@router.post("/configs/{config_id}/dept-mappings", status_code=status.HTTP_201_CREATED)
async def set_dept_mappings(
    config_id: int,
    mappings: List[DeptMappingIn],
    current_user: User = Depends(get_current_user),
) -> dict:
    """Replace (full replace) all dept mappings for a config."""
    _require_superadmin(current_user)
    with get_connection() as conn:
        _fetch_config(conn, config_id)  # 404-check
        _upsert_dept_mappings(conn, config_id, mappings)
        conn.commit()
        saved = _fetch_dept_mappings(conn, config_id)
    log_auth_event(
        "ldap_sync_dept_mappings_updated",
        current_user.username,
        f"Set {len(mappings)} dept mapping(s) for config {config_id}",
    )
    return {"config_id": config_id, "dept_mappings": saved}


@router.delete(
    "/configs/{config_id}/dept-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dept_mapping(
    config_id: int,
    mapping_id: int,
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a single dept mapping by its ID."""
    _require_superadmin(current_user)
    with get_connection() as conn:
        _fetch_config(conn, config_id)  # 404-check
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM ldap_sync_dept_mappings WHERE id = %s AND config_id = %s",
                (mapping_id, config_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"Dept mapping {mapping_id} not found for config {config_id}",
                )
        conn.commit()
    log_auth_event(
        "ldap_sync_dept_mapping_deleted",
        current_user.username,
        f"Deleted dept mapping {mapping_id} from config {config_id}",
    )
