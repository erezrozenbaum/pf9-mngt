"""
PSA Outbound Webhook Routes
============================
Generic outbound webhook configuration for PSA/ticketing system integration.
When a high/critical insight is created, a background task fires the configured
webhook(s) matching the insight's severity, type, and region.

The auth_header is stored encrypted at rest using crypto_helper.py (Fernet).

RBAC
----
  GET  — psa:read  (admin, superadmin)
  POST / PUT / DELETE — psa:write (admin, superadmin)
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from db_pool import get_connection
from crypto_helper import fernet_encrypt, fernet_decrypt

logger = logging.getLogger("pf9.psa")

router = APIRouter(prefix="/api/psa", tags=["psa"])

# The Fernet key is derived from the same jwt_secret used elsewhere —
# this keeps key management simple while providing encryption at rest.
_CRYPTO_SECRET_NAME = "jwt_secret"
_CRYPTO_ENV_VAR     = "JWT_SECRET_KEY"

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PsaConfigIn(BaseModel):
    psa_name:      str = Field(..., min_length=1, max_length=120)
    webhook_url:   str = Field(..., min_length=8, max_length=2048)
    auth_header:   str = Field(..., min_length=1, max_length=2048)
    min_severity:  str = Field(default="high")
    insight_types: List[str] = Field(default_factory=list)
    region_ids:    List[str] = Field(default_factory=list)
    enabled:       bool = True

    @field_validator("webhook_url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        import ipaddress
        from urllib.parse import urlparse
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("webhook_url must start with http:// or https://")
        # Block SSRF: reject URLs that resolve to private/loopback/link-local IPs
        _host = urlparse(v).hostname or ""
        try:
            _ip = ipaddress.ip_address(_host)
            if _ip.is_private or _ip.is_loopback or _ip.is_link_local or _ip.is_reserved:
                raise ValueError(
                    "webhook_url cannot target private, loopback, or link-local IP addresses"
                )
        except ValueError as _exc:
            # Re-raise our own SSRF error; ignore AddressValueError (hostname, not raw IP)
            if "webhook_url" in str(_exc):
                raise
        return v

    @field_validator("min_severity")
    @classmethod
    def _validate_severity(cls, v: str) -> str:
        if v not in _VALID_SEVERITIES:
            raise ValueError(f"min_severity must be one of {_VALID_SEVERITIES}")
        return v


class PsaConfigOut(BaseModel):
    id:            int
    psa_name:      str
    webhook_url:   str
    min_severity:  str
    insight_types: List[str]
    region_ids:    List[str]
    enabled:       bool
    created_at:    str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_config(row: dict) -> dict:
    return {
        "id":            row["id"],
        "psa_name":      row["psa_name"],
        "webhook_url":   row["webhook_url"],
        "min_severity":  row["min_severity"],
        "insight_types": row.get("insight_types") or [],
        "region_ids":    row.get("region_ids") or [],
        "enabled":       row["enabled"],
        "created_at":    row["created_at"].isoformat() if row.get("created_at") else None,
    }


# ---------------------------------------------------------------------------
# GET /api/psa/configs
# ---------------------------------------------------------------------------

@router.get("/configs")
def list_configs(
    _user: User = Depends(require_permission("psa", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, psa_name, webhook_url, min_severity,
                       insight_types, region_ids, enabled, created_at
                FROM psa_webhook_config
                ORDER BY id
            """)
            rows = cur.fetchall()
    return {"configs": [_row_to_config(dict(r)) for r in rows]}


# ---------------------------------------------------------------------------
# POST /api/psa/configs
# ---------------------------------------------------------------------------

@router.post("/configs", status_code=status.HTTP_201_CREATED)
def create_config(
    body: PsaConfigIn,
    user: User = Depends(require_permission("psa", "write")),
):
    # Encrypt auth_header before storage
    try:
        encrypted = fernet_encrypt(
            body.auth_header,
            secret_name=_CRYPTO_SECRET_NAME,
            env_var=_CRYPTO_ENV_VAR,
        )
    except Exception as exc:
        logger.error("Failed to encrypt PSA auth_header: %s", exc)
        raise HTTPException(status_code=500, detail="Encryption error — check server key configuration")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO psa_webhook_config
                    (psa_name, webhook_url, auth_header, min_severity,
                     insight_types, region_ids, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, psa_name, webhook_url, min_severity,
                          insight_types, region_ids, enabled, created_at
            """, (
                body.psa_name, body.webhook_url, encrypted,
                body.min_severity, body.insight_types, body.region_ids,
                body.enabled,
            ))
            row = cur.fetchone()
            conn.commit()

    logger.info("PSA config created id=%d by %s", row["id"], user["username"])
    return {"config": _row_to_config(dict(row))}


# ---------------------------------------------------------------------------
# PUT /api/psa/configs/{config_id}
# ---------------------------------------------------------------------------

@router.put("/configs/{config_id}", status_code=status.HTTP_200_OK)
def update_config(
    config_id: int,
    body: PsaConfigIn,
    user: User = Depends(require_permission("psa", "write")),
):
    # Always re-encrypt the auth_header on update (caller must supply current value)
    try:
        encrypted = fernet_encrypt(
            body.auth_header,
            secret_name=_CRYPTO_SECRET_NAME,
            env_var=_CRYPTO_ENV_VAR,
        )
    except Exception as exc:
        logger.error("Failed to encrypt PSA auth_header: %s", exc)
        raise HTTPException(status_code=500, detail="Encryption error")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE psa_webhook_config
                SET psa_name     = %s,
                    webhook_url  = %s,
                    auth_header  = %s,
                    min_severity = %s,
                    insight_types= %s,
                    region_ids   = %s,
                    enabled      = %s
                WHERE id = %s
                RETURNING id, psa_name, webhook_url, min_severity,
                          insight_types, region_ids, enabled, created_at
            """, (
                body.psa_name, body.webhook_url, encrypted,
                body.min_severity, body.insight_types, body.region_ids,
                body.enabled, config_id,
            ))
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="PSA config not found")
    logger.info("PSA config updated id=%d by %s", config_id, user["username"])
    return {"config": _row_to_config(dict(row))}


# ---------------------------------------------------------------------------
# DELETE /api/psa/configs/{config_id}
# ---------------------------------------------------------------------------

@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_config(
    config_id: int,
    user: User = Depends(require_permission("psa", "write")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM psa_webhook_config WHERE id = %s", (config_id,))
            deleted = cur.rowcount
            conn.commit()

    if deleted == 0:
        raise HTTPException(status_code=404, detail="PSA config not found")
    logger.info("PSA config deleted id=%d by %s", config_id, user["username"])


# ---------------------------------------------------------------------------
# POST /api/psa/configs/{config_id}/test-fire
# ---------------------------------------------------------------------------

@router.post("/configs/{config_id}/test-fire", status_code=status.HTTP_200_OK)
def test_fire_webhook(
    config_id: int,
    user: User = Depends(require_permission("psa", "write")),
):
    """Send a test event payload to the configured webhook URL."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT psa_name, webhook_url, auth_header, enabled
                FROM psa_webhook_config WHERE id = %s
            """, (config_id,))
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="PSA config not found")

    # Decrypt auth_header
    try:
        decrypted_header = fernet_decrypt(
            row["auth_header"],
            secret_name=_CRYPTO_SECRET_NAME,
            env_var=_CRYPTO_ENV_VAR,
            context=f"psa_config_id={config_id}",
        )
    except Exception as exc:
        logger.error("Failed to decrypt PSA auth_header id=%d: %s", config_id, exc)
        raise HTTPException(status_code=500, detail="Decryption error")

    import json
    from datetime import datetime, timezone
    test_payload = {
        "event":      "insight.test",
        "insight_id": 0,
        "severity":   "high",
        "type":       "test",
        "entity":     "tenant / Test Tenant",
        "region":     "test-region",
        "title":      "PSA Webhook Test — PF9 Management Plane",
        "url":        "",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }

    ok, http_status, response_text = _fire_webhook(
        webhook_url=row["webhook_url"],
        auth_header=decrypted_header,
        payload=test_payload,
    )
    logger.info("PSA test-fire id=%d status=%s by %s", config_id, http_status, user["username"])

    return {
        "success":       ok,
        "http_status":   http_status,
        "response":      response_text[:500] if response_text else None,
    }


# ---------------------------------------------------------------------------
# Internal fire helper (used by background tasks too)
# ---------------------------------------------------------------------------

def fire_psa_webhooks(insight: dict) -> None:
    """
    Fire all enabled PSA webhooks that match the given insight's severity,
    type, and region.  Called as a FastAPI BackgroundTask.
    Never raises — logs errors only.
    """
    import json
    from datetime import datetime, timezone

    severity = insight.get("severity", "")
    ins_type = insight.get("type", "")
    region   = (insight.get("metadata") or {}).get("entity_region", "")

    _SEV_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    sev_level  = _SEV_ORDER.get(severity, 0)

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, psa_name, webhook_url, auth_header,
                           min_severity, insight_types, region_ids
                    FROM psa_webhook_config
                    WHERE enabled = true
                """)
                configs = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("PSA: failed to load configs: %s", exc)
        return

    payload = {
        "event":      "insight.created",
        "insight_id": insight.get("id", 0),
        "severity":   severity,
        "type":       ins_type,
        "entity":     f"{insight.get('entity_type','?')} / {insight.get('entity_name','?')}",
        "region":     region,
        "title":      insight.get("title", ""),
        "url":        "",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }

    for cfg in configs:
        min_sev = _SEV_ORDER.get(cfg.get("min_severity", "high"), 3)
        if sev_level < min_sev:
            continue

        allowed_types = cfg.get("insight_types") or []
        if allowed_types and ins_type not in allowed_types:
            continue

        allowed_regions = cfg.get("region_ids") or []
        if allowed_regions and region not in allowed_regions:
            continue

        # Decrypt auth_header
        try:
            auth_header_decrypted = fernet_decrypt(
                cfg["auth_header"],
                secret_name=_CRYPTO_SECRET_NAME,
                env_var=_CRYPTO_ENV_VAR,
                context=f"psa_config_id={cfg['id']}",
            )
        except Exception as exc:
            logger.error("PSA: decrypt failed for config id=%d: %s", cfg["id"], exc)
            continue

        ok, http_status, _ = _fire_webhook(
            webhook_url=cfg["webhook_url"],
            auth_header=auth_header_decrypted,
            payload=payload,
        )
        if ok:
            logger.info(
                "PSA webhook fired: config=%s insight=%d status=%s",
                cfg["psa_name"], insight.get("id", 0), http_status,
            )
        else:
            logger.warning(
                "PSA webhook failed: config=%s insight=%d status=%s",
                cfg["psa_name"], insight.get("id", 0), http_status,
            )


def _fire_webhook(webhook_url: str, auth_header: str, payload: dict) -> tuple:
    """
    POST payload to webhook_url with the given auth header.
    Returns (success: bool, http_status: int|None, response_text: str|None).
    """
    import json
    try:
        import httpx
    except ImportError:
        logger.error("PSA: httpx is not installed — cannot fire webhook")
        return False, None, None

    headers = {"Content-Type": "application/json"}
    # auth_header can be "Bearer <token>", "Token <token>", or a full "Key: Value" header
    if ":" in auth_header:
        key, _, val = auth_header.partition(":")
        headers[key.strip()] = val.strip()
    else:
        headers["Authorization"] = auth_header

    for attempt in range(2):
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    webhook_url,
                    content=json.dumps(payload),
                    headers=headers,
                )
            ok = 200 <= resp.status_code < 300
            return ok, resp.status_code, resp.text
        except Exception as exc:
            if attempt == 0:
                logger.warning("PSA webhook attempt 1 failed: %s — retrying", exc)
            else:
                logger.error("PSA webhook attempt 2 failed: %s", exc)

    return False, None, None
