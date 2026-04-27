"""
api/cluster_routes.py — Admin CRUD for Platform9 control planes and regions.

All endpoints require the `superadmin` role.  Every write operation is recorded
in auth_audit_log so there is a complete audit trail of who changed what cluster
configuration and when.

Control Plane endpoints:
  GET    /admin/control-planes
  POST   /admin/control-planes
  GET    /admin/control-planes/{cp_id}
  PUT    /admin/control-planes/{cp_id}
  DELETE /admin/control-planes/{cp_id}
  POST   /admin/control-planes/{cp_id}/test

Region endpoints:
  GET    /admin/control-planes/{cp_id}/regions
  POST   /admin/control-planes/{cp_id}/regions
  PUT    /admin/control-planes/{cp_id}/regions/{region_id}
  DELETE /admin/control-planes/{cp_id}/regions/{region_id}
  POST   /admin/control-planes/{cp_id}/regions/{region_id}/set-default
  POST   /admin/control-planes/{cp_id}/regions/{region_id}/sync
  GET    /admin/control-planes/{cp_id}/regions/{region_id}/sync-status
  PUT    /admin/control-planes/{cp_id}/regions/{region_id}/enable

Cluster task endpoint (Phase 8):
  GET    /admin/control-planes/cluster-tasks  — list pending cluster_tasks rows

Security notes:
- Passwords are Fernet-encrypted at rest (key = SHA-256 of JWT_SECRET).
  Storage prefix convention: "fernet:<ciphertext>".
  The default cluster uses "env:PF9_PASSWORD" — never re-encrypted on PUT
  unless a new password is explicitly provided.
- GET endpoints NEVER return password_enc; the field is always omitted.
- SSRF: auth_url is validated to reject loopback addresses and cloud metadata
  endpoints.  HTTP (non-TLS) is allowed for on-prem setups but logged.
- All CRUD ops write to auth_audit_log with region_id / control_plane_id.
"""

import base64
import hashlib
import ipaddress
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field, field_validator

from auth import require_authentication, User, log_auth_event
from cluster_registry import get_registry
from db_pool import get_connection
from pf9_control import Pf9Client
from request_helpers import get_request_ip

logger = logging.getLogger("pf9.cluster_routes")

router = APIRouter(prefix="/admin/control-planes", tags=["admin-clusters"])

# ---------------------------------------------------------------------------
# Fernet helpers (same pattern as integration_routes.py)
# ---------------------------------------------------------------------------

def _fernet():
    """Return a Fernet instance keyed from JWT_SECRET, or None if unavailable."""
    try:
        from cryptography.fernet import Fernet
        secret = os.environ.get("JWT_SECRET", "") or os.environ.get("JWT_SECRET_KEY", "changeme")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        return Fernet(key)
    except ImportError:
        logger.warning("cryptography library unavailable — passwords stored without Fernet encryption")
        return None


def _encrypt_password(plaintext: str) -> str:
    """Encrypt a plaintext password for storage. Returns 'fernet:<ciphertext>'."""
    f = _fernet()
    if not f:
        logger.warning("Storing control plane password without encryption — install cryptography")
        return plaintext
    return "fernet:" + f.encrypt(plaintext.encode()).decode()


def _decrypt_password(stored: str) -> str:
    """Decrypt a stored password. Handles 'fernet:' prefix and legacy plaintext."""
    if not stored:
        return ""
    if stored.startswith("env:"):
        from secret_helper import read_secret
        return read_secret("pf9_password", env_var="PF9_PASSWORD", default="")
    if stored.startswith("fernet:"):
        f = _fernet()
        if not f:
            logger.error("Cannot decrypt control plane password — cryptography unavailable")
            raise HTTPException(500, "Cannot decrypt stored credential — cryptography library unavailable")
        try:
            return f.decrypt(stored[7:].encode()).decode()
        except Exception as exc:
            logger.error("Failed to decrypt control plane password: %s", exc)
            raise HTTPException(500, "Credential decryption failed — JWT_SECRET may have changed")
    # Legacy: unrecognized prefix — treat as plaintext
    logger.warning("password_enc has unknown prefix — treating as plaintext (unsupported format)")
    return stored


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

_CLOUD_METADATA = {"169.254.169.254", "fd00:ec2::254"}


def _validate_auth_url(auth_url: str) -> str:
    """
    Validate a user-supplied auth_url against SSRF risks.

    Blocks:
    - loopback addresses (127.0.0.0/8, ::1)
    - cloud metadata endpoint (169.254.169.254)
    - URLs without a hostname
    - Non-HTTPS unless ALLOW_HTTP_AUTH_URL=true (for on-prem HTTP Keystone)

    Private RFC1918 ranges (10.x, 172.16.x, 192.168.x) are ALLOWED because
    on-prem Platform9 deployments frequently live on private networks.
    """
    from urllib.parse import urlparse

    url = auth_url.strip()
    parsed = urlparse(url)

    if not parsed.scheme or not parsed.hostname:
        raise HTTPException(422, "auth_url must be a full URL (e.g. https://pf9.example.com/keystone/v3)")

    if parsed.scheme not in ("https", "http"):
        raise HTTPException(422, "auth_url scheme must be http or https")

    allow_http = os.getenv("ALLOW_HTTP_AUTH_URL", "false").lower() in ("1", "true", "yes")
    if parsed.scheme == "http" and not allow_http:
        raise HTTPException(
            422,
            "auth_url must use HTTPS. Set ALLOW_HTTP_AUTH_URL=true to allow HTTP (on-prem only)."
        )
    if parsed.scheme == "http":
        logger.warning("Control plane registered with HTTP auth_url — TLS strongly recommended")

    hostname = parsed.hostname.lower()

    # Block cloud metadata endpoint
    if hostname in _CLOUD_METADATA:
        raise HTTPException(422, "auth_url hostname is not permitted")

    # Try parsing as IP to catch loopback
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback:
            raise HTTPException(422, "auth_url must not point to a loopback address")
        if hostname in _CLOUD_METADATA:
            raise HTTPException(422, "auth_url hostname is not permitted")
    except ValueError:
        pass  # hostname is a DNS name — fine

    return url.rstrip("/")


# ---------------------------------------------------------------------------
# Auth guard helper
# ---------------------------------------------------------------------------

def _require_superadmin(user: User) -> None:
    """Raise HTTP 403 if user is not superadmin."""
    if user.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin role required")


# ---------------------------------------------------------------------------
# Pydantic models — inbound
# ---------------------------------------------------------------------------

_CP_ID_RE = re.compile(r'^[a-z0-9][a-z0-9\-]{0,62}$')
_REGION_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\-_\.]{0,62}$')


class ControlPlaneCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=63)
    name: str = Field(..., min_length=1, max_length=128)
    auth_url: str = Field(..., min_length=1, max_length=2048)
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=1024)
    user_domain: str = Field(default="Default", max_length=64)
    project_name: str = Field(default="service", max_length=64)
    project_domain: str = Field(default="Default", max_length=64)
    login_url: Optional[str] = Field(default=None, max_length=2048)
    display_color: Optional[str] = Field(default=None, max_length=16)
    tags: dict = Field(default_factory=dict)
    is_enabled: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _CP_ID_RE.match(v):
            raise ValueError("id must be lowercase alphanumeric + hyphens, starting with alphanumeric")
        return v

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: str) -> str:
        return _validate_auth_url(v)


class ControlPlaneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    auth_url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    username: Optional[str] = Field(default=None, min_length=1, max_length=255)
    password: Optional[str] = Field(default=None, min_length=1, max_length=1024)
    user_domain: Optional[str] = Field(default=None, max_length=64)
    project_name: Optional[str] = Field(default=None, max_length=64)
    project_domain: Optional[str] = Field(default=None, max_length=64)
    login_url: Optional[str] = Field(default=None, max_length=2048)
    display_color: Optional[str] = Field(default=None, max_length=16)
    tags: Optional[dict] = None
    is_enabled: Optional[bool] = None

    @field_validator("auth_url")
    @classmethod
    def validate_auth_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _validate_auth_url(v)


class RegionCreate(BaseModel):
    region_name: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    is_default: bool = False
    sync_interval_minutes: int = Field(default=30, ge=1, le=1440)
    priority: int = Field(default=100, ge=1, le=9999)
    latency_threshold_ms: int = Field(default=2000, ge=100, le=60000)
    capabilities: dict = Field(default_factory=dict)
    is_enabled: bool = True

    @field_validator("region_name")
    @classmethod
    def validate_region_name(cls, v: str) -> str:
        if not _REGION_NAME_RE.match(v):
            raise ValueError("region_name must be alphanumeric + hyphens/underscores/dots")
        return v


class RegionUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    sync_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440)
    priority: Optional[int] = Field(default=None, ge=1, le=9999)
    latency_threshold_ms: Optional[int] = Field(default=None, ge=100, le=60000)
    capabilities: Optional[dict] = None


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------

def _cp_row_public(row: dict) -> dict:
    """Strip password_enc; return safe representation."""
    r = dict(row)
    r.pop("password_enc", None)
    # Convert datetimes to ISO strings for JSON serialisation
    for k in ("created_at", "updated_at"):
        if isinstance(r.get(k), datetime):
            r[k] = r[k].isoformat()
    return r


def _region_row_public(row: dict) -> dict:
    r = dict(row)
    for k in ("created_at", "last_sync_at", "health_checked_at"):
        if isinstance(r.get(k), datetime):
            r[k] = r[k].isoformat()
    return r


def _get_cp_or_404(cp_id: str) -> dict:
    """Return a pf9_control_planes row or raise HTTP 404."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM pf9_control_planes WHERE id = %s", (cp_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Control plane '{cp_id}' not found")
    return dict(row)


def _get_region_or_404(cp_id: str, region_id: str) -> dict:
    """Return a pf9_regions row (scoped to cp_id) or raise HTTP 404."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM pf9_regions WHERE id = %s AND control_plane_id = %s",
                (region_id, cp_id),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Region '{region_id}' not found under control plane '{cp_id}'")
    return dict(row)


# ---------------------------------------------------------------------------
# Control Plane routes
# ---------------------------------------------------------------------------

@router.get("", summary="List all control planes")
async def list_control_planes(
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT cp.*,
                       COUNT(r.id) AS region_count
                FROM pf9_control_planes cp
                LEFT JOIN pf9_regions r ON r.control_plane_id = cp.id
                GROUP BY cp.id
                ORDER BY cp.created_at ASC
                """
            )
            rows = cur.fetchall()
    return [_cp_row_public(dict(r)) for r in rows]


@router.post("", status_code=201, summary="Add a new control plane")
async def create_control_plane(
    body: ControlPlaneCreate,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)

    # Check if ID is already taken
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pf9_control_planes WHERE id = %s", (body.id,))
            if cur.fetchone():
                raise HTTPException(409, f"Control plane id '{body.id}' already exists")

    import json as _json
    password_enc = _encrypt_password(body.password)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO pf9_control_planes
                    (id, name, auth_url, username, password_enc,
                     user_domain, project_name, project_domain,
                     login_url, display_color, tags, is_enabled, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    body.id, body.name, body.auth_url, body.username, password_enc,
                    body.user_domain, body.project_name, body.project_domain,
                    body.login_url, body.display_color,
                    _json.dumps(body.tags),
                    body.is_enabled, current_user.username,
                ),
            )
            row = cur.fetchone()

    log_auth_event(
        current_user.username, "control_plane_created", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"control_plane:{body.id}",
        endpoint=str(request.url),
    )
    logger.info("Control plane '%s' created by %s", body.id, current_user.username)
    get_registry().reload()
    return _cp_row_public(dict(row))


@router.get("/{cp_id}", summary="Get a single control plane")
async def get_control_plane(
    cp_id: str,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    row = _get_cp_or_404(cp_id)
    return _cp_row_public(row)


@router.put("/{cp_id}", summary="Update a control plane")
async def update_control_plane(
    cp_id: str,
    body: ControlPlaneUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    row = _get_cp_or_404(cp_id)

    # Build SET clause dynamically (only provided fields)
    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.auth_url is not None:
        updates["auth_url"] = body.auth_url
    if body.username is not None:
        updates["username"] = body.username
    if body.password is not None:
        updates["password_enc"] = _encrypt_password(body.password)
    if body.user_domain is not None:
        updates["user_domain"] = body.user_domain
    if body.project_name is not None:
        updates["project_name"] = body.project_name
    if body.project_domain is not None:
        updates["project_domain"] = body.project_domain
    if body.login_url is not None:
        updates["login_url"] = body.login_url
    if body.display_color is not None:
        updates["display_color"] = body.display_color
    if body.tags is not None:
        import json as _json
        updates["tags"] = _json.dumps(body.tags)
    if body.is_enabled is not None:
        updates["is_enabled"] = body.is_enabled

    if not updates:
        return _cp_row_public(row)

    updates["updated_at"] = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [cp_id]

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE pf9_control_planes SET {set_clause} WHERE id = %s RETURNING *",  # nosec B608 — col names from Pydantic model, values parameterised
                values,
            )
            updated = cur.fetchone()

    log_auth_event(
        current_user.username, "control_plane_updated", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"control_plane:{cp_id}",
        endpoint=str(request.url),
    )
    logger.info("Control plane '%s' updated by %s (fields: %s)", cp_id, current_user.username, list(updates.keys()))
    get_registry().reload()
    return _cp_row_public(dict(updated))


@router.delete("/{cp_id}", status_code=204, summary="Delete a control plane")
async def delete_control_plane(
    cp_id: str,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    _get_cp_or_404(cp_id)  # raises 404 if not found

    # Safety: refuse if regions still exist under this control plane
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pf9_regions WHERE control_plane_id = %s", (cp_id,))
            count = cur.fetchone()[0]
    if count > 0:
        raise HTTPException(
            409,
            f"Cannot delete control plane '{cp_id}': {count} region(s) still registered. "
            "Delete all regions first."
        )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pf9_control_planes WHERE id = %s", (cp_id,))

    log_auth_event(
        current_user.username, "control_plane_deleted", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"control_plane:{cp_id}",
        endpoint=str(request.url),
    )
    logger.info("Control plane '%s' deleted by %s", cp_id, current_user.username)
    get_registry().reload()


@router.post("/{cp_id}/test", summary="Test Keystone auth and discover regions")
async def test_control_plane(
    cp_id: str,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    """
    Authenticate against the control plane's Keystone and return all regions
    discovered in the service catalog.  Reports which ones are already registered.
    """
    _require_superadmin(current_user)
    row = _get_cp_or_404(cp_id)

    try:
        password = _decrypt_password(row["password_enc"])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Could not read stored credential for cluster: %s", exc)
        raise HTTPException(500, "Could not read stored credential") from exc

    # Build a temporary client to test connectivity
    try:
        client = Pf9Client(
            auth_url=row["auth_url"],
            username=row["username"],
            password=password,
            user_domain=row["user_domain"],
            project_name=row["project_name"],
            project_domain=row["project_domain"],
            region_name="",        # we want all endpoints back from catalog
            region_id=f"{cp_id}:__test__",
        )
        client.authenticate()
    except Exception as exc:
        log_auth_event(
            current_user.username, "control_plane_test_failed", False,
            get_request_ip(request),
            request.headers.get("user-agent"),
            resource=f"control_plane:{cp_id}",
            endpoint=str(request.url),
        )
        logger.warning("Control plane test failed for '%s': %s", cp_id, exc)
        return {
            "connected": False,
            "keystone_version": None,
            "discovered_regions": [],
            "already_registered": [],
            "error": str(exc),
        }
    finally:
        try:
            client.session.close()
        except Exception:
            pass

    # Parse catalog to extract regions and their service endpoints
    discovered = _parse_catalog_regions(client)

    # Which region_names are already registered?
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT region_name FROM pf9_regions WHERE control_plane_id = %s",
                (cp_id,),
            )
            already_registered = [r[0] for r in cur.fetchall()]

    log_auth_event(
        current_user.username, "control_plane_test_ok", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"control_plane:{cp_id}",
        endpoint=str(request.url),
    )
    return {
        "connected": True,
        "keystone_version": "v3",
        "discovered_regions": discovered,
        "already_registered": already_registered,
        "error": None,
    }


def _parse_catalog_regions(client: Pf9Client) -> list:
    """
    Extract per-region service info from the cached Keystone catalog.
    Returns a list of dicts with region_name and per-service endpoints.
    """
    # After authenticate() the token and catalog are stored internally.
    # Re-authenticate to get the catalog (it was already fetched in authenticate())
    # Access the internal token body isn't exposed — re-auth and get catalog from
    # the POST /auth/tokens response directly.
    regions: dict = {}
    try:
        import requests as _req
        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": client.username,
                            "domain": {"name": client.user_domain},
                            "password": client.password,
                        }
                    },
                },
                "scope": {
                    "project": {
                        "name": client.project_name,
                        "domain": {"name": client.project_domain},
                    }
                },
            }
        }
        import os as _os
        verify_tls = _os.getenv("PF9_VERIFY_TLS", "true").lower() not in ("0", "false", "no")
        r = _req.post(
            f"{client.auth_url}/auth/tokens",
            json=payload,
            timeout=20,
            verify=verify_tls,
        )
        r.raise_for_status()
        catalog = r.json().get("token", {}).get("catalog", [])

        _INTERESTING = {"compute", "network", "volumev3", "image", "identity"}
        _ENDPOINT_LABELS = {
            "compute": "nova_endpoint",
            "network": "neutron_endpoint",
            "volumev3": "cinder_endpoint",
            "image": "glance_endpoint",
        }

        for svc in catalog:
            svc_type = svc.get("type", "")
            if svc_type not in _INTERESTING:
                continue
            for ep in svc.get("endpoints", []):
                if ep.get("interface") != "public":
                    continue
                region_id = ep.get("region_id") or ep.get("region", "unknown")
                if region_id not in regions:
                    regions[region_id] = {
                        "region_name": region_id,
                        "services": [],
                    }
                if svc_type not in regions[region_id]["services"]:
                    regions[region_id]["services"].append(svc_type)
                label = _ENDPOINT_LABELS.get(svc_type)
                if label:
                    regions[region_id][label] = ep["url"].rstrip("/")

    except Exception as exc:
        logger.warning("_parse_catalog_regions: could not extract catalog: %s", exc)

    return list(regions.values())


# ---------------------------------------------------------------------------
# Region routes
# ---------------------------------------------------------------------------

@router.get("/{cp_id}/regions", summary="List regions for a control plane")
async def list_regions(
    cp_id: str,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    _get_cp_or_404(cp_id)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM pf9_regions
                WHERE control_plane_id = %s
                ORDER BY priority ASC, region_name ASC
                """,
                (cp_id,),
            )
            rows = cur.fetchall()
    return [_region_row_public(dict(r)) for r in rows]


@router.post("/{cp_id}/regions", status_code=201, summary="Register a region")
async def create_region(
    cp_id: str,
    body: RegionCreate,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    _get_cp_or_404(cp_id)

    region_id = f"{cp_id}:{body.region_name}"

    # Check uniqueness
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pf9_regions WHERE control_plane_id = %s AND region_name = %s",
                (cp_id, body.region_name),
            )
            if cur.fetchone():
                raise HTTPException(
                    409,
                    f"Region '{body.region_name}' already registered under control plane '{cp_id}'"
                )

    import json as _json
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO pf9_regions
                    (id, control_plane_id, region_name, display_name,
                     is_default, sync_interval_minutes, priority,
                     latency_threshold_ms, capabilities, is_enabled)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    region_id, cp_id, body.region_name, body.display_name,
                    body.is_default, body.sync_interval_minutes, body.priority,
                    body.latency_threshold_ms, _json.dumps(body.capabilities),
                    body.is_enabled,
                ),
            )
            row = cur.fetchone()

    log_auth_event(
        current_user.username, "region_created", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"region:{region_id}",
        endpoint=str(request.url),
    )
    logger.info("Region '%s' created under '%s' by %s", region_id, cp_id, current_user.username)
    get_registry().reload()
    return _region_row_public(dict(row))


@router.put("/{cp_id}/regions/{region_id}", summary="Update region settings")
async def update_region(
    cp_id: str,
    region_id: str,
    body: RegionUpdate,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    _get_region_or_404(cp_id, region_id)

    updates = {}
    if body.display_name is not None:
        updates["display_name"] = body.display_name
    if body.sync_interval_minutes is not None:
        updates["sync_interval_minutes"] = body.sync_interval_minutes
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.latency_threshold_ms is not None:
        updates["latency_threshold_ms"] = body.latency_threshold_ms
    if body.capabilities is not None:
        import json as _json
        updates["capabilities"] = _json.dumps(body.capabilities)

    if not updates:
        row = _get_region_or_404(cp_id, region_id)
        return _region_row_public(row)

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [region_id, cp_id]

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE pf9_regions SET {set_clause} WHERE id = %s AND control_plane_id = %s RETURNING *",  # nosec B608 — col names from Pydantic model, values parameterised
                values,
            )
            updated = cur.fetchone()

    log_auth_event(
        current_user.username, "region_updated", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"region:{region_id}",
        endpoint=str(request.url),
    )
    get_registry().reload()
    return _region_row_public(dict(updated))


@router.delete("/{cp_id}/regions/{region_id}", status_code=204, summary="Delete a region")
async def delete_region(
    cp_id: str,
    region_id: str,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    row = _get_region_or_404(cp_id, region_id)

    # Refuse to delete the default region
    if row.get("is_default"):
        raise HTTPException(
            409,
            "Cannot delete the default region. Promote another region to default first."
        )

    # Safety: check if any resource data references this region
    _RESOURCE_TABLES = [
        "servers", "volumes", "networks", "hypervisors",
        "snapshots", "floating_ips", "images",
    ]
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in _RESOURCE_TABLES:
                cur.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE region_id = %s",  # nosec B608 — table from hardcoded allowlist _RESOURCE_TABLES, value parameterised
                    (region_id,),
                )
                count = cur.fetchone()[0]
                if count > 0:
                    raise HTTPException(
                        409,
                        f"Cannot delete region '{region_id}': {count} record(s) in '{table}' "
                        "still reference it. Archive or re-assign data first."
                    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM pf9_regions WHERE id = %s AND control_plane_id = %s",
                (region_id, cp_id),
            )

    log_auth_event(
        current_user.username, "region_deleted", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"region:{region_id}",
        endpoint=str(request.url),
    )
    logger.info("Region '%s' deleted by %s", region_id, current_user.username)
    get_registry().reload()


@router.post("/{cp_id}/regions/{region_id}/set-default", summary="Promote region to default")
async def set_default_region(
    cp_id: str,
    region_id: str,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    _get_region_or_404(cp_id, region_id)

    # Clear existing default, then set new one — in a single transaction
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE pf9_regions SET is_default = FALSE WHERE is_default = TRUE AND control_plane_id = %s",
                (cp_id,),
            )
            cur.execute(
                "UPDATE pf9_regions SET is_default = TRUE WHERE id = %s AND control_plane_id = %s RETURNING *",
                (region_id, cp_id),
            )
            updated = cur.fetchone()

    log_auth_event(
        current_user.username, "region_set_default", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"region:{region_id}",
        endpoint=str(request.url),
    )
    logger.info("Region '%s' promoted to default by %s", region_id, current_user.username)
    get_registry().reload()
    return _region_row_public(dict(updated))


@router.post("/{cp_id}/regions/{region_id}/sync", summary="Trigger immediate inventory sync")
async def trigger_region_sync(
    cp_id: str,
    region_id: str,
    request: Request,
    current_user: User = Depends(require_authentication),
):
    """
    Marks the region as pending sync so the scheduler worker picks it up on its
    next iteration.  Returns immediately — does not wait for sync completion.
    """
    _require_superadmin(current_user)
    _get_region_or_404(cp_id, region_id)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE pf9_regions
                   SET last_sync_at = NULL,
                       last_sync_status = 'pending',
                       health_status = 'unknown'
                 WHERE id = %s AND control_plane_id = %s
                """,
                (region_id, cp_id),
            )

    log_auth_event(
        current_user.username, "region_sync_triggered", True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"region:{region_id}",
        endpoint=str(request.url),
    )
    logger.info("Sync triggered for region '%s' by %s", region_id, current_user.username)
    return {"region_id": region_id, "status": "sync_queued"}


@router.get("/{cp_id}/regions/{region_id}/sync-status", summary="Get last sync status")
async def get_region_sync_status(
    cp_id: str,
    region_id: str,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    row = _get_region_or_404(cp_id, region_id)

    # Also fetch last N sync metric rows
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT started_at, finished_at, status,
                       sync_type, resource_count, error_count, duration_ms
                FROM cluster_sync_metrics
                WHERE region_id = %s
                ORDER BY started_at DESC
                LIMIT 10
                """,
                (region_id,),
            )
            history = [dict(r) for r in cur.fetchall()]

    for h in history:
        for k in ("started_at", "finished_at"):
            if isinstance(h.get(k), datetime):
                h[k] = h[k].isoformat()

    return {
        "region_id": region_id,
        "health_status": row.get("health_status"),
        "last_sync_at": row.get("last_sync_at").isoformat() if row.get("last_sync_at") else None,
        "last_sync_status": row.get("last_sync_status"),
        "last_sync_vm_count": row.get("last_sync_vm_count"),
        "health_checked_at": row.get("health_checked_at").isoformat() if row.get("health_checked_at") else None,
        "sync_history": history,
    }


@router.put("/{cp_id}/regions/{region_id}/enable", summary="Enable or disable a region")
async def set_region_enabled(
    cp_id: str,
    region_id: str,
    request: Request,
    enabled: bool = True,
    current_user: User = Depends(require_authentication),
):
    _require_superadmin(current_user)
    _get_region_or_404(cp_id, region_id)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "UPDATE pf9_regions SET is_enabled = %s WHERE id = %s AND control_plane_id = %s RETURNING *",
                (enabled, region_id, cp_id),
            )
            updated = cur.fetchone()

    action = "region_enabled" if enabled else "region_disabled"
    log_auth_event(
        current_user.username, action, True,
        get_request_ip(request),
        request.headers.get("user-agent"),
        resource=f"region:{region_id}",
        endpoint=str(request.url),
    )
    logger.info("Region '%s' %s by %s", region_id, "enabled" if enabled else "disabled", current_user.username)
    get_registry().reload()
    return _region_row_public(dict(updated))


# ---------------------------------------------------------------------------
# Phase 8 — Cluster task visibility (cross-region replication bus)
# ---------------------------------------------------------------------------

@router.get("/cluster-tasks", summary="List cluster tasks (NOT_IMPLEMENTED)")
async def list_cluster_tasks(
    status: Optional[str] = None,
    current_user: User = Depends(require_authentication),
):
    """
    Return pending/in-progress rows from the ``cluster_tasks`` table for
    superadmin inspection.

    The cross-region replication processor (image_copy, volume_transfer,
    backup_restore) is **not yet implemented**.  Tasks queued in this table
    will not be executed until the processor is added. This endpoint makes
    deferred work visible rather than silently ignored so operators can plan
    accordingly.
    """
    _require_superadmin(current_user)
    task_status = status or "pending"
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM cluster_tasks WHERE status = %s ORDER BY created_at LIMIT 100",
                (task_status,),
            )
            tasks = [dict(r) for r in cur.fetchall()]
    return {
        "processor_status": "NOT_IMPLEMENTED",
        "note": "Cross-region replication processor is deferred. Tasks queued here will not execute until the processor is added.",
        "count": len(tasks),
        "tasks": tasks,
    }
