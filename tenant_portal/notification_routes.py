"""
notification_routes.py — Tenant portal notification preference endpoints.

Tenants manage per-event-type subscriptions (email or outbound webhook) for
their own project events: snapshot done/fail, restore done/fail, quota warnings,
VM provisioning, and billing invoices.

Security invariants:
  - All mutations are scoped to the authenticated user's own project_ids
  - Webhook URLs are validated against the SSRF blocklist before save
  - Tenant can only read notification history for their own projects
  - No operator-facing notification data is exposed

Endpoints:
  GET    /tenant/notifications/preferences              — list all prefs
  PUT    /tenant/notifications/preferences              — bulk upsert (max 18)
  DELETE /tenant/notifications/preferences/{event}/{ch} — remove one
  GET    /tenant/notifications/history                  — last 50 tenant events
  POST   /tenant/notifications/webhook-test             — fire a test call
"""

import ipaddress
import logging
import socket
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field, field_validator

from audit_helper import log_action
from db_pool import get_tenant_connection
from middleware import get_tenant_context
from tenant_context import TenantContext

logger = logging.getLogger("tenant_portal.notifications")

router = APIRouter(prefix="/tenant/notifications", tags=["notifications"])

# ---------------------------------------------------------------------------
# Allowed event types (whitelist — tenants cannot subscribe to operator events)
# ---------------------------------------------------------------------------
_ALLOWED_EVENT_TYPES = {
    "snapshot_completed",
    "snapshot_failed",
    "restore_completed",
    "restore_failed",
    "quota_at_80pct",
    "quota_at_95pct",
    "vm_provisioned",
    "vm_provision_failed",
    "billing_invoice_ready",
}

_ALLOWED_CHANNELS = {"email", "webhook"}

# ---------------------------------------------------------------------------
# SSRF guard — copied from billing_routes.py pattern
# ---------------------------------------------------------------------------
_WEBHOOK_BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
]


def _assert_webhook_url_allowed(url: str) -> None:
    """Resolve webhook URL host; raise 422 if it targets a private/reserved range."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Webhook URL must use http or https scheme",
        )
    host = parsed.hostname
    if not host:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid webhook URL: cannot determine host",
        )
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot resolve webhook host '{host}'",
        )
    for info in addr_infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for blocked in _WEBHOOK_BLOCKED_RANGES:
            if addr in blocked:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Webhook URL host '{host}' resolves to a private/reserved "
                        f"address ({addr_str}). External URLs only."
                    ),
                )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class NotificationPref(BaseModel):
    event_type: str
    channel: str
    endpoint: str = Field(..., max_length=1024)
    enabled: bool = True

    @field_validator("event_type")
    @classmethod
    def valid_event_type(cls, v: str) -> str:
        if v not in _ALLOWED_EVENT_TYPES:
            raise ValueError(f"event_type must be one of {sorted(_ALLOWED_EVENT_TYPES)}")
        return v

    @field_validator("channel")
    @classmethod
    def valid_channel(cls, v: str) -> str:
        if v not in _ALLOWED_CHANNELS:
            raise ValueError("channel must be 'email' or 'webhook'")
        return v

    @field_validator("endpoint")
    @classmethod
    def non_empty_endpoint(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("endpoint must not be empty")
        return v.strip()


class BulkUpsertRequest(BaseModel):
    preferences: List[NotificationPref] = Field(..., max_length=18)


class WebhookTestRequest(BaseModel):
    url: str = Field(..., max_length=1024)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/preferences")
def list_preferences(ctx: TenantContext = Depends(get_tenant_context)):
    """Return all notification preferences for the authenticated tenant user."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, project_id, event_type, channel, endpoint, enabled,
                       created_at, updated_at
                FROM   tenant_notification_prefs
                WHERE  keystone_user_id = %s
                  AND  project_id = ANY(%s)
                ORDER BY event_type, channel
                """,
                (ctx.keystone_user_id, list(ctx.project_ids)),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"preferences": rows}


@router.put("/preferences")
def upsert_preferences(
    body: BulkUpsertRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Bulk upsert notification preferences for the authenticated tenant user.

    Uses the user's first project_id as the scope for all preferences.
    If the user belongs to multiple projects, they should call this per-project
    (future: add project_id to the request body).
    """
    if not ctx.project_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="No project scope available")

    project_id = list(ctx.project_ids)[0]

    # Validate webhook URLs before any DB writes
    for pref in body.preferences:
        if pref.channel == "webhook" and pref.enabled:
            _assert_webhook_url_allowed(pref.endpoint)

    with get_tenant_connection() as conn:
        with conn.cursor() as cur:
            for pref in body.preferences:
                cur.execute(
                    """
                    INSERT INTO tenant_notification_prefs
                        (project_id, keystone_user_id, event_type, channel, endpoint, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, keystone_user_id, event_type, channel)
                    DO UPDATE SET
                        endpoint   = EXCLUDED.endpoint,
                        enabled    = EXCLUDED.enabled,
                        updated_at = now()
                    """,
                    (
                        project_id,
                        ctx.keystone_user_id,
                        pref.event_type,
                        pref.channel,
                        pref.endpoint,
                        pref.enabled,
                    ),
                )
        conn.commit()

    log_action(
        ctx.keystone_user_id,
        ctx.username,
        ctx.control_plane_id,
        "update_notification_prefs",
        "notification_prefs",
        None,
        project_id,
        None,
        True,
        {"count": len(body.preferences)},
    )
    return {"updated": len(body.preferences)}


@router.delete("/preferences/{event_type}/{channel}")
def delete_preference(
    event_type: str,
    channel: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Delete a single notification preference."""
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Preference not found")
    if channel not in _ALLOWED_CHANNELS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Preference not found")

    with get_tenant_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM tenant_notification_prefs
                WHERE  keystone_user_id = %s
                  AND  project_id = ANY(%s)
                  AND  event_type = %s
                  AND  channel    = %s
                """,
                (ctx.keystone_user_id, list(ctx.project_ids), event_type, channel),
            )
            deleted = cur.rowcount
        conn.commit()

    if deleted == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Preference not found")
    return {"deleted": deleted}


@router.get("/history")
def notification_history(ctx: TenantContext = Depends(get_tenant_context)):
    """Return the last 50 tenant notification events for this user's projects."""
    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # notification_log rows tagged notification_target='tenant' include
            # the project_id in the username field as "tenant:<project_id>:<user_id>"
            # so we filter by the pattern matching any of the user's projects.
            cur.execute(
                """
                SELECT id, event_type, subject, delivery_status, sent_at, created_at,
                       error_message
                FROM   notification_log
                WHERE  notification_target = 'tenant'
                  AND  (
                      username = ANY(%s)
                      OR username LIKE ANY(
                          SELECT 'tenant:' || p || ':%' FROM unnest(%s::text[]) p
                      )
                  )
                ORDER BY created_at DESC
                LIMIT 50
                """,
                (
                    [f"tenant:{p}:{ctx.keystone_user_id}" for p in ctx.project_ids],
                    list(ctx.project_ids),
                ),
            )
            rows = [dict(r) for r in cur.fetchall()]
    return {"history": rows}


@router.post("/webhook-test")
def test_webhook(
    body: WebhookTestRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Fire a test POST to the given webhook URL to verify reachability.
    SSRF guard is applied before the request is made.
    """
    _assert_webhook_url_allowed(body.url)

    payload = {
        "event_type": "webhook_test",
        "message": "This is a test notification from the Platform9 tenant portal.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project_id": list(ctx.project_ids)[0] if ctx.project_ids else None,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(body.url, json=payload)
        return {"status": resp.status_code, "ok": resp.is_success}
    except httpx.TimeoutException:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Webhook endpoint timed out after 10 seconds",
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Webhook delivery failed: {exc}",
        )
