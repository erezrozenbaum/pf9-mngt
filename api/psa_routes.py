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

import json
import logging
import os
import secrets
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from event_bus import emit_event
from db_pool import get_connection
from crypto_helper import fernet_encrypt, fernet_decrypt
from rate_limit import limiter

logger = logging.getLogger("pf9.psa")

router = APIRouter(prefix="/api/psa", tags=["psa"])

# The Fernet key is derived from the same jwt_secret used elsewhere —
# this keeps key management simple while providing encryption at rest.
_CRYPTO_SECRET_NAME = "jwt_secret"
_CRYPTO_ENV_VAR     = "JWT_SECRET_KEY"

_VALID_SEVERITIES = {"low", "medium", "high", "critical"}
_VALID_INSIGHT_STATUSES = {"open", "acknowledged", "snoozed", "resolved", "dismissed"}


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
    inbound_enabled: bool = False
    status_map: Dict[str, str] = Field(default_factory=dict)
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

    @field_validator("status_map")
    @classmethod
    def _validate_status_map(cls, v: Dict[str, str]) -> Dict[str, str]:
        clean: Dict[str, str] = {}
        for key, target in (v or {}).items():
            target_l = (target or "").strip().lower()
            if target_l not in _VALID_INSIGHT_STATUSES:
                raise ValueError(
                    f"status_map target for '{key}' must be one of {sorted(_VALID_INSIGHT_STATUSES)}"
                )
            clean[str(key).strip()] = target_l
        return clean


class PsaConfigOut(BaseModel):
    id:            int
    psa_name:      str
    webhook_url:   str
    min_severity:  str
    insight_types: List[str]
    region_ids:    List[str]
    inbound_enabled: bool
    status_map: Dict[str, str]
    inbound_webhook_url: str
    enabled:       bool
    created_at:    str


class PsaInboundPayload(BaseModel):
    ticket_id: str = Field(..., min_length=1, max_length=255)
    status: str = Field(..., min_length=1, max_length=255)
    resolution_note: Optional[str] = Field(default=None, max_length=4000)
    closed_by: Optional[str] = Field(default=None, max_length=255)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_config(row: dict) -> dict:
    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if base:
        inbound_url = f"{base}/api/psa/inbound/{row['id']}"
    else:
        inbound_url = f"/api/psa/inbound/{row['id']}"

    return {
        "id":            row["id"],
        "psa_name":      row["psa_name"],
        "webhook_url":   row["webhook_url"],
        "min_severity":  row["min_severity"],
        "insight_types": row.get("insight_types") or [],
        "region_ids":    row.get("region_ids") or [],
        "inbound_enabled": bool(row.get("inbound_enabled")),
        "status_map": (row.get("status_map") or {}),
        "inbound_webhook_url": inbound_url,
        "enabled":       row["enabled"],
        "created_at":    row["created_at"].isoformat() if row.get("created_at") else None,
    }


def _map_inbound_status(raw_status: str, status_map: dict) -> Optional[str]:
    key = (raw_status or "").strip()
    if not key:
        return None

    mapped = (status_map or {}).get(key)
    if mapped:
        mapped_l = str(mapped).lower()
        if mapped_l in _VALID_INSIGHT_STATUSES:
            return mapped_l

    lowered = key.lower()
    defaults = {
        "completed": "resolved",
        "resolved": "resolved",
        "closed": "resolved",
        "cancelled": "dismissed",
        "canceled": "dismissed",
        "dismissed": "dismissed",
        "acknowledged": "acknowledged",
        "in_progress": "acknowledged",
        "open": "open",
    }
    return defaults.get(lowered)


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
                       insight_types, region_ids, inbound_enabled,
                       status_map, enabled, created_at
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
                     insight_types, region_ids, inbound_enabled, status_map, enabled)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING id, psa_name, webhook_url, min_severity,
                          insight_types, region_ids, inbound_enabled,
                          status_map, enabled, created_at
            """, (
                body.psa_name, body.webhook_url, encrypted,
                body.min_severity, body.insight_types, body.region_ids,
                body.inbound_enabled, json.dumps(body.status_map or {}), body.enabled,
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
                    inbound_enabled = %s,
                    status_map   = %s::jsonb,
                    enabled      = %s
                WHERE id = %s
                RETURNING id, psa_name, webhook_url, min_severity,
                          insight_types, region_ids, inbound_enabled,
                          status_map, enabled, created_at
            """, (
                body.psa_name, body.webhook_url, encrypted,
                body.min_severity, body.insight_types, body.region_ids,
                body.inbound_enabled, json.dumps(body.status_map or {}),
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


@router.get("/configs/{config_id}/inbound-token", status_code=status.HTTP_200_OK)
def rotate_inbound_token(
    config_id: int,
    user: User = Depends(require_permission("psa", "write")),
):
    """Generate/rotate inbound token used by PSA callback webhook."""
    token_plain = secrets.token_urlsafe(32)
    try:
        encrypted = fernet_encrypt(
            token_plain,
            secret_name=_CRYPTO_SECRET_NAME,
            env_var=_CRYPTO_ENV_VAR,
        )
    except Exception as exc:
        logger.error("Failed to encrypt PSA inbound token: %s", exc)
        raise HTTPException(status_code=500, detail="Encryption error")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE psa_webhook_config
                SET inbound_token = %s, inbound_enabled = true
                WHERE id = %s
                RETURNING id
                """,
                (encrypted, config_id),
            )
            row = cur.fetchone()
            conn.commit()
    if not row:
        raise HTTPException(status_code=404, detail="PSA config not found")

    logger.info("PSA inbound token rotated id=%d by %s", config_id, user["username"])
    base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    inbound_url = f"{base}/api/psa/inbound/{config_id}" if base else f"/api/psa/inbound/{config_id}"
    return {
        "config_id": config_id,
        "inbound_enabled": True,
        "inbound_webhook_url": inbound_url,
        "inbound_token": token_plain,
    }


@router.post("/inbound/{config_id}")
@limiter.limit("60/minute")
def psa_inbound_status_webhook(
    request: Request,
    config_id: int,
    body: PsaInboundPayload,
    x_psa_token: Optional[str] = Header(default=None, alias="X-PSA-Token"),
):
    """Inbound PSA webhook: map ticket status to operational insight lifecycle."""
    if not x_psa_token:
        raise HTTPException(status_code=401, detail="Missing X-PSA-Token header")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, inbound_enabled, inbound_token, status_map
                FROM psa_webhook_config
                WHERE id = %s
                """,
                (config_id,),
            )
            cfg = cur.fetchone()
            if not cfg:
                raise HTTPException(status_code=404, detail="PSA config not found")
            if not cfg.get("inbound_enabled"):
                raise HTTPException(status_code=403, detail="Inbound webhook is disabled for this config")

            enc_token = cfg.get("inbound_token")
            if not enc_token:
                raise HTTPException(status_code=401, detail="Inbound token is not configured")
            try:
                token = fernet_decrypt(
                    enc_token,
                    secret_name=_CRYPTO_SECRET_NAME,
                    env_var=_CRYPTO_ENV_VAR,
                    context=f"psa_config_id={config_id}:inbound",
                )
            except Exception as exc:
                logger.error("Failed to decrypt inbound token id=%d: %s", config_id, exc)
                raise HTTPException(status_code=500, detail="Decryption error")

            if not secrets.compare_digest(token, x_psa_token):
                raise HTTPException(status_code=401, detail="Invalid X-PSA-Token")

            target_status = _map_inbound_status(body.status, cfg.get("status_map") or {})
            if not target_status:
                return {
                    "matched": False,
                    "insight_id": None,
                    "detail": "No status_map rule for provided status",
                }

            cur.execute(
                """
                SELECT id, type, entity_type, entity_id, entity_name, metadata
                FROM operational_insights
                WHERE metadata->>'psa_ticket_id' = %s
                ORDER BY detected_at DESC
                LIMIT 1
                """,
                (body.ticket_id,),
            )
            insight = cur.fetchone()
            if not insight:
                return {"matched": False, "insight_id": None}

            metadata = dict(insight.get("metadata") or {})
            if body.resolution_note:
                metadata["psa_resolution_note"] = body.resolution_note
            if body.closed_by:
                metadata["psa_closed_by"] = body.closed_by
            metadata["psa_last_status"] = body.status

            if target_status in {"resolved", "dismissed"}:
                cur.execute(
                    """
                    UPDATE operational_insights
                    SET status = %s,
                        resolved_at = NOW(),
                        metadata = %s::jsonb,
                        last_seen_at = NOW()
                    WHERE id = %s
                    """,
                    (target_status, json.dumps(metadata), insight["id"]),
                )
            else:
                cur.execute(
                    """
                    UPDATE operational_insights
                    SET status = %s,
                        metadata = %s::jsonb,
                        last_seen_at = NOW()
                    WHERE id = %s
                    """,
                    (target_status, json.dumps(metadata), insight["id"]),
                )

            conn.commit()

    emit_event(
        event_type="intelligence.insight_resolved" if target_status in {"resolved", "dismissed"} else "intelligence.insight_updated",
        category="intelligence",
        severity="info",
        title=f"Insight {target_status} from PSA inbound ticket update",
        description=f"PSA ticket {body.ticket_id} status '{body.status}' mapped to '{target_status}'",
        entity_type=str(insight.get("entity_type") or "insight"),
        entity_id=str(insight.get("entity_id") or insight["id"]),
        entity_name=insight.get("entity_name"),
        source="psa_inbound",
        source_id=f"psa:{config_id}:{body.ticket_id}:{target_status}",
        metadata={
            "psa_config_id": config_id,
            "psa_ticket_id": body.ticket_id,
            "mapped_status": target_status,
        },
    )

    return {"matched": True, "insight_id": insight["id"]}


# ---------------------------------------------------------------------------
# Internal fire helper (used by background tasks too)
# ---------------------------------------------------------------------------

def fire_psa_webhooks(insight: dict) -> None:
    """
    Fire all enabled PSA webhooks that match the given insight's severity,
    type, and region.  Called as a FastAPI BackgroundTask.
    Never raises — logs errors only.
    """
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

        ok, http_status, response_text = _fire_webhook(
            webhook_url=cfg["webhook_url"],
            auth_header=auth_header_decrypted,
            payload=payload,
        )
        if ok:
            # Best-effort: capture returned PSA ticket id and store in insight metadata.
            ticket_id = _extract_ticket_id(response_text)
            if ticket_id and insight.get("id"):
                try:
                    with get_connection() as conn2:
                        with conn2.cursor() as cur2:
                            cur2.execute(
                                """
                                UPDATE operational_insights
                                SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                                WHERE id = %s
                                """,
                                (json.dumps({"psa_ticket_id": str(ticket_id)}), insight["id"]),
                            )
                            conn2.commit()
                except Exception:
                    logger.debug(
                        "PSA: failed to persist returned ticket_id for insight=%s",
                        insight.get("id"),
                        exc_info=True,
                    )

            logger.info(
                "PSA webhook fired: config=%s insight=%d status=%s",
                cfg["psa_name"], insight.get("id", 0), http_status,
            )
        else:
            logger.warning(
                "PSA webhook failed: config=%s insight=%d status=%s",
                cfg["psa_name"], insight.get("id", 0), http_status,
            )


def _extract_ticket_id(response_text: Optional[str]) -> Optional[str]:
    if not response_text:
        return None
    try:
        payload = json.loads(response_text)
        if isinstance(payload, dict):
            for key in ("ticket_id", "id", "ticketId", "ticket"):
                val = payload.get(key)
                if val is not None:
                    return str(val)
    except Exception:
        return None
    return None


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
