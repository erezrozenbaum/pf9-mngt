"""
Notification management API endpoints.

Provides CRUD for notification preferences, notification history,
test email sending, and SMTP configuration status.
"""

import json
import smtplib
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, field_validator
import psycopg2
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user
from db_pool import get_connection
import os

from smtp_helper import (
    SMTP_ENABLED, SMTP_HOST, SMTP_PORT, SMTP_USE_TLS,
    SMTP_FROM_ADDRESS, SMTP_FROM_NAME, SMTP_USERNAME,
    send_email as smtp_send_email, get_smtp_config,
)
from webhook_helper import (
    SLACK_ENABLED, TEAMS_ENABLED,
    send_slack, send_teams, post_event as webhook_post_event,
)

logger = logging.getLogger("pf9_notifications_api")

router = APIRouter(prefix="/notifications", tags=["notifications"])

VALID_EVENT_TYPES = [
    "drift_critical", "drift_warning", "drift_info",
    "snapshot_failure", "compliance_violation",
    "health_score_drop",
    "resource_created", "resource_updated", "resource_deleted",
    "domain_deleted", "domain_toggled",
    "tenant_provisioned",
    "report_exported",
    "runbook_approval_requested", "runbook_completed", "runbook_failed",
    "runbook_approval_granted", "runbook_approval_rejected",
    "prep_tasks_completed",
    "prep_approval_requested", "prep_approval_granted", "prep_approval_rejected",
    "vjailbreak_bundle_exported",
    "handoff_sheet_exported",
    "onboarding_submitted",
    "onboarding_approved",
    "onboarding_rejected",
    "onboarding_completed",
    "onboarding_failed",
    "vm_provisioning_submitted",
    "vm_provisioning_approved",
    "vm_provisioning_rejected",
    "vm_provisioning_completed",
    "vm_provisioning_failed",
    # Phase T — Wave Approval
    "wave_approval_requested",
    "wave_approval_granted",
    "wave_approval_rejected",
]

VALID_SEVERITIES = ["info", "warning", "critical"]
VALID_DELIVERY_MODES = ["immediate", "digest"]


def ensure_tables():
    """Ensure notification tables exist."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'notification_preferences'
                    )
                """)
                if not cur.fetchone()[0]:
                    migration_path = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)),
                        "db", "migrate_notifications.sql"
                    )
                    if os.path.exists(migration_path):
                        with open(migration_path) as f:
                            cur.execute(f.read())
    except Exception as e:
        logger.warning("Could not ensure notification tables: %s", e)


# Run on import
ensure_tables()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class NotificationPreference(BaseModel):
    event_type: str
    email: str
    severity_min: str = "warning"
    delivery_mode: str = "immediate"
    enabled: bool = True

    @field_validator("event_type")
    def validate_event_type(cls, v):
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type. Must be one of: {VALID_EVENT_TYPES}")
        return v

    @field_validator("severity_min")
    def validate_severity(cls, v):
        if v not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity. Must be one of: {VALID_SEVERITIES}")
        return v

    @field_validator("delivery_mode")
    def validate_delivery_mode(cls, v):
        if v not in VALID_DELIVERY_MODES:
            raise ValueError(f"Invalid delivery_mode. Must be one of: {VALID_DELIVERY_MODES}")
        return v


class BulkPreferenceUpdate(BaseModel):
    preferences: List[NotificationPreference]


class TestEmailRequest(BaseModel):
    to_email: str


# ---------------------------------------------------------------------------
# SMTP status endpoint
# ---------------------------------------------------------------------------

@router.get("/smtp-status", dependencies=[Depends(require_permission("notifications", "read"))])
async def get_smtp_status():
    """Return SMTP configuration status (no secrets exposed)."""
    from smtp_helper import get_smtp_config
    cfg = get_smtp_config()
    return {
        "smtp_enabled": cfg["enabled"],
        "smtp_host": cfg["host"] if cfg["enabled"] else "",
        "smtp_port": cfg["port"] if cfg["enabled"] else 0,
        "smtp_use_tls": cfg["use_tls"],
        "smtp_from_address": cfg["from_address"],
        "smtp_from_name": cfg["from_name"],
        "smtp_username_configured": bool(cfg["username"]),
    }


@router.post("/smtp-config", dependencies=[Depends(require_permission("notifications", "admin"))])
async def update_smtp_config(payload: dict):
    """Save SMTP configuration to system_settings (DB-level override of env vars)."""
    allowed = {
        "smtp.enabled", "smtp.host", "smtp.port", "smtp.use_tls",
        "smtp.username", "smtp.password", "smtp.from_address", "smtp.from_name",
    }
    with get_connection() as conn:
        with conn.cursor() as cur:
            for key, value in payload.items():
                if key not in allowed:
                    continue
                str_val = str(value) if value is not None else ""
                # Encrypt SMTP password before persisting to DB
                if key == "smtp.password" and str_val:
                    from crypto_helper import fernet_encrypt as _fe
                    str_val = _fe(str_val, secret_name="smtp_config_key",
                                  env_var="SMTP_CONFIG_KEY")
                cur.execute("""
                    INSERT INTO system_settings (key, value, description)
                    VALUES (%s, %s, 'SMTP runtime configuration')
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """, (key, str_val))
    # Invalidate Redis SMTP config cache so the next email send picks up new values
    try:
        from cache import _get_client as _redis_client
        rc = _redis_client()
        if rc is not None:
            rc.delete("pf9:smtp_config_override")
    except Exception:
        pass
    return {"status": "saved"}


# ---------------------------------------------------------------------------
# Preference CRUD
# ---------------------------------------------------------------------------

@router.get("/preferences", dependencies=[Depends(require_permission("notifications", "read"))])
async def get_preferences(current_user=Depends(get_current_user)):
    """Get notification preferences for the current user."""
    username = current_user.username
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, username, email, event_type, severity_min,
                           delivery_mode, enabled, created_at, updated_at
                    FROM notification_preferences
                    WHERE username = %s
                    ORDER BY event_type
                """, (username,))
                prefs = cur.fetchall()
            return {"preferences": prefs, "available_event_types": VALID_EVENT_TYPES}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/preferences", dependencies=[Depends(require_permission("notifications", "write"))])
async def update_preferences(
    body: BulkPreferenceUpdate,
    current_user=Depends(get_current_user),
):
    """Create or update notification preferences for the current user (bulk upsert)."""
    username = current_user.username
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for pref in body.preferences:
                    cur.execute("""
                        INSERT INTO notification_preferences
                            (username, email, event_type, severity_min, delivery_mode, enabled, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, now())
                        ON CONFLICT (username, event_type)
                        DO UPDATE SET
                            email = EXCLUDED.email,
                            severity_min = EXCLUDED.severity_min,
                            delivery_mode = EXCLUDED.delivery_mode,
                            enabled = EXCLUDED.enabled,
                            updated_at = now()
                    """, (
                        username, pref.email, pref.event_type,
                        pref.severity_min, pref.delivery_mode, pref.enabled,
                    ))
            return {"status": "ok", "updated": len(body.preferences)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/preferences/{event_type}", dependencies=[Depends(require_permission("notifications", "write"))])
async def delete_preference(event_type: str, current_user=Depends(get_current_user)):
    """Delete a notification preference for the current user."""
    username = current_user.username
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    DELETE FROM notification_preferences
                    WHERE username = %s AND event_type = %s
                """, (username, event_type))
                deleted = cur.rowcount
            if deleted == 0:
                raise HTTPException(status_code=404, detail="Preference not found")
            return {"status": "ok", "deleted": event_type}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Notification history
# ---------------------------------------------------------------------------

@router.get("/history", dependencies=[Depends(require_permission("notifications", "read"))])
async def get_notification_history(
    current_user=Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
):
    """Get notification history for the current user."""
    username = current_user.username
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT id, username, email, event_type, event_id, subject,
                           body_preview, delivery_status, error_message, sent_at, created_at
                    FROM notification_log
                    WHERE username = %s
                """
                params = [username]

                if event_type:
                    query += " AND event_type = %s"
                    params.append(event_type)
                if status:
                    query += " AND delivery_status = %s"
                    params.append(status)

                query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                logs = cur.fetchall()

                # Get total count
                count_query = "SELECT COUNT(*) FROM notification_log WHERE username = %s"
                count_params = [username]
                if event_type:
                    count_query += " AND event_type = %s"
                    count_params.append(event_type)
                if status:
                    count_query += " AND delivery_status = %s"
                    count_params.append(status)
                cur.execute(count_query, count_params)
                total = cur.fetchone()["count"]

            return {"history": logs, "total": total, "limit": limit, "offset": offset}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Admin: all users notification stats
# ---------------------------------------------------------------------------

@router.get("/admin/stats", dependencies=[Depends(require_permission("notifications", "admin"))])
async def get_notification_stats():
    """Admin: summary stats for all notification activity."""
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        COUNT(*)                                                           AS total_sent,
                        COUNT(*) FILTER (WHERE delivery_status = 'sent')                   AS delivered,
                        COUNT(*) FILTER (WHERE delivery_status = 'failed')                 AS failed,
                        COUNT(*) FILTER (WHERE delivery_status = 'digest_queued')           AS digest_queued,
                        COUNT(DISTINCT username)                                            AS unique_users,
                        COUNT(*) FILTER (WHERE created_at >= now() - interval '24 hours')  AS last_24h,
                        COUNT(*) FILTER (WHERE created_at >= now() - interval '7 days')    AS last_7d
                    FROM notification_log
                """)
                stats = cur.fetchone()

                cur.execute("""
                    SELECT event_type, COUNT(*) AS count
                    FROM notification_log
                    WHERE created_at >= now() - interval '7 days'
                    GROUP BY event_type
                    ORDER BY count DESC
                """)
                by_type = cur.fetchall()

                cur.execute("""
                    SELECT COUNT(*) AS total_subscribers,
                           COUNT(*) FILTER (WHERE enabled = true) AS active_subscribers
                    FROM notification_preferences
                """)
                sub_stats = cur.fetchone()

            return {
                "stats": stats,
                "by_event_type_7d": by_type,
                "subscribers": sub_stats,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Test email
# ---------------------------------------------------------------------------

@router.post("/test-email", dependencies=[Depends(require_permission("notifications", "write"))])
async def send_test_email(body: TestEmailRequest, current_user=Depends(get_current_user)):
    """Send a test email to verify SMTP configuration."""
    cfg = get_smtp_config()
    if not cfg["enabled"] or not cfg["host"]:
        raise HTTPException(status_code=400, detail="SMTP is not enabled. Configure SMTP via the Settings tab or set SMTP_ENABLED=true in environment.")

    html = """
        <html><body style="font-family: sans-serif; padding: 20px;">
        <h2 style="color: #1a73e8;">✅ Test Email Successful</h2>
        <p>This confirms that email notifications are working correctly for
        the Platform9 Management System.</p>
        <p style="color: #666; font-size: 13px;">Sent at: {time}</p>
        </body></html>
        """.format(time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    try:
        smtp_send_email(
            body.to_email,
            "PF9 Management — Test Notification",
            html,
            raise_on_error=True,
        )
        return {"status": "ok", "message": f"Test email sent to {body.to_email}"}

    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=400, detail="SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD.")
    except smtplib.SMTPConnectError:
        raise HTTPException(status_code=400, detail=f"Could not connect to SMTP server {cfg['host']}:{cfg['port']}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")


# ---------------------------------------------------------------------------
# Webhook (Slack / Teams) config and test
# ---------------------------------------------------------------------------

class TestWebhookRequest(BaseModel):
    channel: str = "all"  # "slack" | "teams" | "all"


@router.get(
    "/webhook-config",
    dependencies=[Depends(require_permission("notifications", "read"))],
)
async def get_webhook_config():
    """Return which webhook channels are configured (no secrets exposed)."""
    return {
        "slack_enabled": SLACK_ENABLED,
        "teams_enabled": TEAMS_ENABLED,
        "any_enabled": SLACK_ENABLED or TEAMS_ENABLED,
    }


@router.post(
    "/test-webhook",
    dependencies=[Depends(require_permission("notifications", "write"))],
)
async def send_test_webhook(body: TestWebhookRequest):
    """Send a test message to Slack and/or Teams to verify webhook configuration."""
    channel = body.channel.lower()
    if channel not in ("slack", "teams", "all"):
        raise HTTPException(status_code=400, detail="channel must be 'slack', 'teams', or 'all'")

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = "PF9 Management — Test Webhook Notification"
    body_text = (
        f"This confirms that webhook notifications are working correctly "
        f"for the Platform9 Management System.\nSent at: {now_str}"
    )

    results: dict = {}

    if channel in ("slack", "all"):
        if not SLACK_ENABLED:
            results["slack"] = {"status": "skipped", "reason": "SLACK_WEBHOOK_URL not configured"}
        else:
            ok = send_slack(subject, body_text, event_type="test")
            results["slack"] = {"status": "ok" if ok else "error"}

    if channel in ("teams", "all"):
        if not TEAMS_ENABLED:
            results["teams"] = {"status": "skipped", "reason": "TEAMS_WEBHOOK_URL not configured"}
        else:
            ok = send_teams(subject, body_text, event_type="test")
            results["teams"] = {"status": "ok" if ok else "error"}

    return {"results": results}
