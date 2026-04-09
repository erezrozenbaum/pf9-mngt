"""
External Integrations Routes — CRUD and connectivity-test for billing gate,
CRM, and generic webhook integrations.

Provides:
- GET /api/integrations          — list all (admin+)
- GET /api/integrations/{name}   — get one (admin+)
- POST /api/integrations         — create (superadmin)
- PUT /api/integrations/{name}   — update (superadmin)
- DELETE /api/integrations/{name}— delete (superadmin)
- POST /api/integrations/{name}/test — fire a test request and record status

Security notes:
- auth_credential is Fernet-encrypted at rest using a key derived from JWT_SECRET.
- Credentials are NEVER returned in plaintext; only a masked suffix is shown.
- SSL verification is on by default and can only be disabled explicitly.
"""

import os
import json
import base64
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import requests as _requests
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from db_pool import get_connection
from auth import require_permission

logger = logging.getLogger("pf9_integrations")

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

# ---------------------------------------------------------------------------
#  Auto-migration on import (creates tables if they don't exist)
# ---------------------------------------------------------------------------
def _ensure_tables():
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'external_integrations'
                    )
                """)
                if not cur.fetchone()[0]:
                    migration = os.path.join(
                        os.path.dirname(__file__), "..", "db",
                        "migrate_runbooks_dept_visibility.sql"
                    )
                    if os.path.exists(migration):
                        with open(migration) as f:
                            cur.execute(f.read())
                        logger.info("External integrations tables created via auto-migration")
    except Exception as e:
        logger.warning("Could not ensure integration tables on startup: %s", e)


try:
    _ensure_tables()
except Exception:
    pass


# ---------------------------------------------------------------------------
#  Credential encryption (Fernet / AES-128-CBC + HMAC-SHA256)
# ---------------------------------------------------------------------------
def _fernet():
    """Return a Fernet instance keyed from JWT_SECRET, or None if unavailable."""
    try:
        from cryptography.fernet import Fernet
        secret = os.environ.get("JWT_SECRET", "changeme-default-secret")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        return Fernet(key)
    except ImportError:
        return None


def _encrypt(plaintext: str) -> str:
    f = _fernet()
    if not f:
        logger.warning("cryptography library unavailable — credential stored without encryption")
        return plaintext
    return f.encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    f = _fernet()
    if not f:
        return ciphertext
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext  # may already be plaintext


def _mask(ciphertext: str) -> str:
    """Return a safe display string — never reveal the actual credential."""
    if not ciphertext:
        return ""
    return "••••••••" + ciphertext[-4:] if len(ciphertext) > 4 else "••••••••"


# ---------------------------------------------------------------------------
#  Pydantic models
# ---------------------------------------------------------------------------
_VALID_TYPES = {"billing_gate", "crm", "webhook"}
_VALID_AUTH  = {"bearer", "basic", "api_key"}


class IntegrationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-z0-9_-]+$')
    display_name: str = Field(..., min_length=1, max_length=128)
    integration_type: str = Field(default="webhook")
    base_url: str = Field(..., min_length=1, max_length=2048)
    auth_type: str = Field(default="bearer")
    auth_credential: Optional[str] = None
    auth_header_name: str = Field(default="Authorization", max_length=128)
    request_template: dict = Field(default_factory=dict)
    response_approval_path: str = Field(default="approved", max_length=256)
    response_reason_path: str = Field(default="reason", max_length=256)
    response_charge_id_path: str = Field(default="charge_id", max_length=256)
    enabled: bool = False
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    verify_ssl: bool = True


class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    integration_type: Optional[str] = None
    base_url: Optional[str] = None
    auth_type: Optional[str] = None
    auth_credential: Optional[str] = None
    auth_header_name: Optional[str] = None
    request_template: Optional[dict] = None
    response_approval_path: Optional[str] = None
    response_reason_path: Optional[str] = None
    response_charge_id_path: Optional[str] = None
    enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=120)
    verify_ssl: Optional[bool] = None


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------
def _row_public(row: dict) -> dict:
    """Return a row safe for API responses with credential masked."""
    r = dict(row)
    if r.get("auth_credential"):
        r["auth_credential"] = _mask(r["auth_credential"])
    return r


def _build_auth_headers(row: dict) -> dict:
    """Build HTTP authorization headers from a DB row (decrypting credential)."""
    credential = _decrypt(row.get("auth_credential") or "") if row.get("auth_credential") else ""
    if not credential:
        return {}
    auth_type = row.get("auth_type", "bearer")
    header_name = row.get("auth_header_name", "Authorization")
    if auth_type == "bearer":
        return {header_name: f"Bearer {credential}"}
    elif auth_type == "basic":
        encoded = base64.b64encode(credential.encode()).decode()
        return {header_name: f"Basic {encoded}"}
    elif auth_type == "api_key":
        return {header_name: credential}
    return {}


# ---------------------------------------------------------------------------
#  Routes
# ---------------------------------------------------------------------------
@router.get("")
async def list_integrations(
    current_user=Depends(require_permission("integrations", "read")),
):
    """List all external integrations (credentials masked)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, display_name, integration_type, base_url,
                       auth_type, auth_credential, auth_header_name,
                       request_template, response_approval_path,
                       response_reason_path, response_charge_id_path,
                       enabled, timeout_seconds, verify_ssl,
                       last_tested_at, last_test_status,
                       created_at, updated_at
                FROM external_integrations
                ORDER BY integration_type, name
            """)
            rows = cur.fetchall()
    return [_row_public(dict(r)) for r in rows]


@router.get("/{name}")
async def get_integration(
    name: str,
    current_user=Depends(require_permission("integrations", "read")),
):
    """Get a single integration by name (credentials masked)."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM external_integrations WHERE name = %s", (name,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Integration '{name}' not found")
    return _row_public(dict(row))


@router.post("", status_code=201)
async def create_integration(
    body: IntegrationCreate,
    current_user=Depends(require_permission("integrations", "admin")),
):
    """Create a new external integration. Superadmin only."""
    if body.integration_type not in _VALID_TYPES:
        raise HTTPException(422, f"integration_type must be one of: {', '.join(sorted(_VALID_TYPES))}")
    if body.auth_type not in _VALID_AUTH:
        raise HTTPException(422, f"auth_type must be one of: {', '.join(sorted(_VALID_AUTH))}")

    encrypted_cred = _encrypt(body.auth_credential) if body.auth_credential else None

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO external_integrations (
                    name, display_name, integration_type, base_url,
                    auth_type, auth_credential, auth_header_name,
                    request_template, response_approval_path,
                    response_reason_path, response_charge_id_path,
                    enabled, timeout_seconds, verify_ssl
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                body.name, body.display_name, body.integration_type, body.base_url,
                body.auth_type, encrypted_cred, body.auth_header_name,
                json.dumps(body.request_template),
                body.response_approval_path, body.response_reason_path,
                body.response_charge_id_path,
                body.enabled, body.timeout_seconds, body.verify_ssl,
            ))
            row = cur.fetchone()
    return _row_public(dict(row))


@router.put("/{name}")
async def update_integration(
    name: str,
    body: IntegrationUpdate,
    current_user=Depends(require_permission("integrations", "admin")),
):
    """Update an external integration. Only provided fields are changed. Superadmin only."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM external_integrations WHERE name = %s", (name,))
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(404, f"Integration '{name}' not found")

            updates: dict = {}
            if body.display_name is not None:
                updates["display_name"] = body.display_name
            if body.integration_type is not None:
                if body.integration_type not in _VALID_TYPES:
                    raise HTTPException(422, f"integration_type must be one of: {', '.join(sorted(_VALID_TYPES))}")
                updates["integration_type"] = body.integration_type
            if body.base_url is not None:
                updates["base_url"] = body.base_url
            if body.auth_type is not None:
                if body.auth_type not in _VALID_AUTH:
                    raise HTTPException(422, f"auth_type must be one of: {', '.join(sorted(_VALID_AUTH))}")
                updates["auth_type"] = body.auth_type
            if body.auth_credential is not None:
                updates["auth_credential"] = _encrypt(body.auth_credential)
            if body.auth_header_name is not None:
                updates["auth_header_name"] = body.auth_header_name
            if body.request_template is not None:
                updates["request_template"] = json.dumps(body.request_template)
            if body.response_approval_path is not None:
                updates["response_approval_path"] = body.response_approval_path
            if body.response_reason_path is not None:
                updates["response_reason_path"] = body.response_reason_path
            if body.response_charge_id_path is not None:
                updates["response_charge_id_path"] = body.response_charge_id_path
            if body.enabled is not None:
                updates["enabled"] = body.enabled
            if body.timeout_seconds is not None:
                updates["timeout_seconds"] = body.timeout_seconds
            if body.verify_ssl is not None:
                updates["verify_ssl"] = body.verify_ssl

            if not updates:
                return _row_public(dict(existing))

            updates["updated_at"] = datetime.now(timezone.utc)
            set_clause = ", ".join(f"{k} = %s" for k in updates)
            values = list(updates.values()) + [name]
            cur.execute(
                f"UPDATE external_integrations SET {set_clause} WHERE name = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
    return _row_public(dict(row))


@router.delete("/{name}", status_code=204)
async def delete_integration(
    name: str,
    current_user=Depends(require_permission("integrations", "admin")),
):
    """Delete an external integration. Superadmin only."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM external_integrations WHERE name = %s RETURNING id", (name,)
            )
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(404, f"Integration '{name}' not found")
    return None


@router.post("/{name}/test")
async def test_integration(
    name: str,
    current_user=Depends(require_permission("integrations", "admin")),
):
    """Fire a test POST to the integration endpoint and record the outcome."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM external_integrations WHERE name = %s", (name,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(404, f"Integration '{name}' not found")

    row = dict(row)
    headers = {"Content-Type": "application/json"}
    headers.update(_build_auth_headers(row))

    test_payload = dict(row.get("request_template") or {})
    test_payload["_test"] = True
    test_payload["_timestamp"] = datetime.now(timezone.utc).isoformat()

    test_status = "error"
    test_detail = ""
    try:
        resp = _requests.post(
            row["base_url"],
            json=test_payload,
            headers=headers,
            verify=bool(row.get("verify_ssl", True)),
            timeout=int(row.get("timeout_seconds", 10)),
        )
        test_status = "ok" if resp.status_code < 400 else f"http_{resp.status_code}"
        test_detail = resp.text[:500]
    except _requests.exceptions.ConnectionError as e:
        test_status = "connection_error"
        test_detail = str(e)[:500]
    except _requests.exceptions.Timeout:
        test_status = "timeout"
        test_detail = f"Request timed out after {row.get('timeout_seconds', 10)}s"
    except Exception as e:
        test_status = "error"
        test_detail = str(e)[:500]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE external_integrations SET last_tested_at = now(), "
                "last_test_status = %s, updated_at = now() WHERE name = %s",
                (test_status, name),
            )

    return {
        "name": name,
        "test_status": test_status,
        "detail": test_detail,
        "tested_at": datetime.now(timezone.utc).isoformat(),
    }
