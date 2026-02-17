"""
Notification management API endpoints.

Provides CRUD for notification preferences, notification history,
test email sending, and SMTP configuration status.
"""

import os
import json
import smtplib
import ssl
import hashlib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel, validator
import psycopg2
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user
from db_pool import get_connection

logger = logging.getLogger("pf9_notifications_api")

router = APIRouter(prefix="/notifications", tags=["notifications"])

# ---------------------------------------------------------------------------
# SMTP config (same env vars as the notification worker)
# ---------------------------------------------------------------------------
SMTP_ENABLED = os.getenv("SMTP_ENABLED", "false").lower() in ("true", "1", "yes")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.getenv("SMTP_FROM_ADDRESS", "pf9-mgmt@example.com")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Platform9 Management")

VALID_EVENT_TYPES = [
    "drift_critical", "drift_warning", "drift_info",
    "snapshot_failure", "compliance_violation",
    "health_score_drop",
    "resource_deleted", "domain_deleted", "domain_toggled",
    "tenant_provisioned",
]

VALID_SEVERITIES = ["info", "warning", "critical"]
VALID_DELIVERY_MODES = ["immediate", "digest"]


# DEPRECATED: use db_pool.get_connection() instead
def get_db_connection():
    """Deprecated — kept only for backward compatibility. Use get_connection() from db_pool."""
    return psycopg2.connect(
        host=os.getenv("PF9_DB_HOST", "db"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", "pf9_mgmt"),
        user=os.getenv("PF9_DB_USER", "pf9"),
        password=os.getenv("PF9_DB_PASSWORD", ""),
    )


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
        logger.warning(f"Could not ensure notification tables: {e}")


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

    @validator("event_type")
    def validate_event_type(cls, v):
        if v not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type. Must be one of: {VALID_EVENT_TYPES}")
        return v

    @validator("severity_min")
    def validate_severity(cls, v):
        if v not in VALID_SEVERITIES:
            raise ValueError(f"Invalid severity. Must be one of: {VALID_SEVERITIES}")
        return v

    @validator("delivery_mode")
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
    return {
        "smtp_enabled": SMTP_ENABLED,
        "smtp_host": SMTP_HOST if SMTP_ENABLED else "",
        "smtp_port": SMTP_PORT if SMTP_ENABLED else 0,
        "smtp_use_tls": SMTP_USE_TLS,
        "smtp_from_address": SMTP_FROM_ADDRESS,
        "smtp_from_name": SMTP_FROM_NAME,
        "smtp_username_configured": bool(SMTP_USERNAME),
    }


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
    if not SMTP_ENABLED:
        raise HTTPException(status_code=400, detail="SMTP is not enabled. Set SMTP_ENABLED=true in environment.")

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_ADDRESS}>"
        msg["To"] = body.to_email
        msg["Subject"] = "PF9 Management — Test Notification"

        html = """
        <html><body style="font-family: sans-serif; padding: 20px;">
        <h2 style="color: #1a73e8;">✅ Test Email Successful</h2>
        <p>This confirms that email notifications are working correctly for
        the Platform9 Management System.</p>
        <p style="color: #666; font-size: 13px;">Sent at: {time}</p>
        </body></html>
        """.format(time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

        msg.attach(MIMEText(html, "html"))

        if SMTP_USE_TLS:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_ADDRESS, [body.to_email], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_ADDRESS, [body.to_email], msg.as_string())

        return {"status": "ok", "message": f"Test email sent to {body.to_email}"}

    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=400, detail="SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD.")
    except smtplib.SMTPConnectError:
        raise HTTPException(status_code=400, detail=f"Could not connect to SMTP server {SMTP_HOST}:{SMTP_PORT}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")
