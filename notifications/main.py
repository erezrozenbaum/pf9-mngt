"""
PF9 Notification Worker
=======================
Polls the database for new events (drift, snapshot failures, compliance
violations, health-score drops) and dispatches email notifications based
on per-user preferences.

Runs as a standalone container alongside the API and monitoring services.
"""

import os
import sys
import json
import hashlib
import logging
import time
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from jinja2 import Environment, FileSystemLoader

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

logger = logging.getLogger("pf9_notifications")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)

LOG_FILE = os.getenv("LOG_FILE", "")
if LOG_FILE:
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)

# ---------------------------------------------------------------------------
# Configuration (env vars)
# ---------------------------------------------------------------------------

DB_HOST = os.getenv("PF9_DB_HOST", "db")
DB_PORT = int(os.getenv("PF9_DB_PORT", "5432"))
DB_NAME = os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt"))
DB_USER = os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9"))
DB_PASSWORD = os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))

SMTP_ENABLED = os.getenv("SMTP_ENABLED", "false").lower() in ("true", "1", "yes")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.getenv("SMTP_FROM_ADDRESS", "pf9-mgmt@example.com")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Platform9 Management")

POLL_INTERVAL = int(os.getenv("NOTIFICATION_POLL_INTERVAL_SECONDS", "120"))
DIGEST_ENABLED = os.getenv("NOTIFICATION_DIGEST_ENABLED", "true").lower() in ("true", "1", "yes")
DIGEST_HOUR_UTC = int(os.getenv("NOTIFICATION_DIGEST_HOUR_UTC", "8"))

# How far back to look for new events on each poll (seconds)
LOOKBACK_SECONDS = int(os.getenv("NOTIFICATION_LOOKBACK_SECONDS", "300"))

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def ensure_tables(conn):
    """Run the migration SQL if tables don't exist yet."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'notification_preferences'
            )
        """)
        exists = cur.fetchone()[0]
        if not exists:
            migration_path = os.path.join(
                os.path.dirname(__file__), "..", "db", "migrate_notifications.sql"
            )
            if os.path.exists(migration_path):
                with open(migration_path) as f:
                    cur.execute(f.read())
                conn.commit()
                logger.info("Notification tables created from migration SQL")
            else:
                logger.warning(f"Migration file not found: {migration_path}")

# ---------------------------------------------------------------------------
# Dedup helper
# ---------------------------------------------------------------------------

def dedup_key(event_type: str, resource_id: str, event_id: str) -> str:
    raw = f"{event_type}:{resource_id}:{event_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def already_sent(conn, key: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM notification_log WHERE dedup_key = %s AND delivery_status = 'sent' LIMIT 1",
            (key,),
        )
        return cur.fetchone() is not None

# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

# Jinja2 templates
template_dir = os.path.join(os.path.dirname(__file__), "templates")
jinja_env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

def render_template(template_name: str, context: Dict[str, Any]) -> str:
    tpl = jinja_env.get_template(template_name)
    return tpl.render(**context)


def send_email(to_address: str, subject: str, html_body: str) -> bool:
    """Send a single email via SMTP. Returns True on success."""
    if not SMTP_ENABLED:
        logger.info(f"SMTP disabled — would send to {to_address}: {subject}")
        return True  # treat as success in dry-run mode

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM_ADDRESS}>"
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        if SMTP_USE_TLS:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_ADDRESS, [to_address], msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM_ADDRESS, [to_address], msg.as_string())

        logger.info(f"Email sent to {to_address}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_address}: {e}")
        return False

# ---------------------------------------------------------------------------
# Event collectors — each returns a list of event dicts
# ---------------------------------------------------------------------------

def collect_drift_events(conn, since: datetime) -> List[Dict]:
    """Collect unacknowledged drift events since `since`."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, resource_type, resource_id, resource_name,
                   field_changed, old_value, new_value, severity,
                   project_name, detected_at
            FROM drift_events
            WHERE detected_at >= %s
              AND acknowledged = false
            ORDER BY detected_at DESC
            LIMIT 200
        """, (since,))
        for row in cur.fetchall():
            events.append({
                "event_type": f"drift_{row['severity']}",
                "event_id": str(row["id"]),
                "resource_id": row["resource_id"] or "",
                "resource_name": row.get("resource_name", ""),
                "resource_type": row.get("resource_type", ""),
                "severity": row["severity"],
                "field_name": row.get("field_changed", ""),
                "old_value": str(row.get("old_value", "")),
                "new_value": str(row.get("new_value", "")),
                "project_name": row.get("project_name", ""),
                "detected_at": row["detected_at"].isoformat() if row["detected_at"] else "",
                "summary": (
                    f"Drift detected on {row.get('resource_type', '')} "
                    f"'{row.get('resource_name', row['resource_id'])}': "
                    f"{row.get('field_changed', '')} changed"
                ),
            })
    return events


def collect_snapshot_failures(conn, since: datetime) -> List[Dict]:
    """Collect failed/partial snapshot runs since `since`."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT id, run_type, status, started_at, finished_at,
                   snapshots_created, snapshots_failed, error_summary
            FROM snapshot_runs
            WHERE started_at >= %s
              AND status IN ('failed', 'partial')
            ORDER BY started_at DESC
            LIMIT 50
        """, (since,))
        for row in cur.fetchall():
            events.append({
                "event_type": "snapshot_failure",
                "event_id": str(row["id"]),
                "resource_id": str(row["id"]),
                "resource_name": row.get("run_type", "snapshot_run"),
                "severity": "critical" if row["status"] == "failed" else "warning",
                "status": row["status"],
                "snapshots_created": row.get("snapshots_created", 0),
                "snapshots_failed": row.get("snapshots_failed", 0),
                "error_summary": row.get("error_summary", ""),
                "started_at": row["started_at"].isoformat() if row["started_at"] else "",
                "summary": (
                    f"Snapshot run {row['status']}: "
                    f"{row.get('snapshots_failed', 0)} failed, "
                    f"{row.get('snapshots_created', 0)} created"
                ),
            })
    return events


def collect_compliance_violations(conn, since: datetime) -> List[Dict]:
    """Collect non-compliant volumes from the latest compliance report."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT cd.id, cd.volume_id, cd.volume_name, cd.compliance_status,
                   cd.last_snapshot_at, cd.project_name,
                   cr.report_date
            FROM compliance_details cd
            JOIN compliance_reports cr ON cd.report_id = cr.id
            WHERE cr.report_date >= %s
              AND cd.compliance_status IN ('Non-Compliant', 'No Snapshots')
            ORDER BY cr.report_date DESC
            LIMIT 200
        """, (since,))
        for row in cur.fetchall():
            events.append({
                "event_type": "compliance_violation",
                "event_id": str(row["id"]),
                "resource_id": row.get("volume_id", ""),
                "resource_name": row.get("volume_name", ""),
                "severity": "warning",
                "compliance_status": row["compliance_status"],
                "project_name": row.get("project_name", ""),
                "last_snapshot_date": str(row.get("last_snapshot_at", "")),
                "report_date": row["report_date"].isoformat() if row.get("report_date") else "",
                "summary": (
                    f"Volume '{row.get('volume_name', row.get('volume_id', ''))}' "
                    f"is {row['compliance_status']} in {row.get('project_name', 'unknown')}"
                ),
            })
    return events


def collect_health_drops(conn, since: datetime) -> List[Dict]:
    """Collect tenants whose health score is below a threshold."""
    events = []
    threshold = int(os.getenv("HEALTH_ALERT_THRESHOLD", "50"))
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT project_id, project_name, domain_name, health_score,
                   error_servers, error_volumes, critical_drift, compliance_pct
            FROM v_tenant_health
            WHERE health_score < %s
            ORDER BY health_score ASC
            LIMIT 50
        """, (threshold,))
        for row in cur.fetchall():
            score = row["health_score"]
            severity = "critical" if score < 30 else "warning"
            events.append({
                "event_type": "health_score_drop",
                "event_id": f"health_{row['project_id']}_{datetime.utcnow().strftime('%Y%m%d')}",
                "resource_id": row["project_id"],
                "resource_name": row.get("project_name", ""),
                "severity": severity,
                "health_score": score,
                "domain_name": row.get("domain_name", ""),
                "error_servers": row.get("error_servers", 0),
                "error_volumes": row.get("error_volumes", 0),
                "critical_drift": row.get("critical_drift", 0),
                "compliance_pct": row.get("compliance_pct", 0),
                "summary": (
                    f"Tenant '{row.get('project_name', '')}' health score dropped to "
                    f"{score} (threshold: {threshold})"
                ),
            })
    return events

# ---------------------------------------------------------------------------
# Notification dispatcher
# ---------------------------------------------------------------------------

def get_subscribed_users(conn, event_type: str, severity: str) -> List[Dict]:
    """Return users subscribed to this event_type whose min severity is met."""
    severity_rank = {"info": 0, "warning": 1, "critical": 2}
    event_rank = severity_rank.get(severity, 0)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT username, email, delivery_mode, severity_min
            FROM notification_preferences
            WHERE event_type = %s AND enabled = true
        """, (event_type,))
        users = []
        for row in cur.fetchall():
            min_rank = severity_rank.get(row["severity_min"], 0)
            if event_rank >= min_rank:
                users.append(dict(row))
        return users


def dispatch_event(conn, event: Dict):
    """Match event to subscribers and send / queue notifications."""
    event_type = event["event_type"]
    severity = event.get("severity", "info")
    dkey = dedup_key(event_type, event.get("resource_id", ""), event.get("event_id", ""))

    if already_sent(conn, dkey):
        return

    users = get_subscribed_users(conn, event_type, severity)
    if not users:
        return

    # Choose template based on event type
    template_map = {
        "drift_critical": "drift_alert.html",
        "drift_warning": "drift_alert.html",
        "drift_info": "drift_alert.html",
        "snapshot_failure": "snapshot_failure.html",
        "compliance_violation": "compliance_alert.html",
        "health_score_drop": "health_alert.html",
    }
    template_name = template_map.get(event_type, "generic_alert.html")

    subject_map = {
        "drift_critical": f"🔴 Critical Drift: {event.get('summary', '')}",
        "drift_warning": f"🟡 Drift Warning: {event.get('summary', '')}",
        "drift_info": f"ℹ️ Drift Info: {event.get('summary', '')}",
        "snapshot_failure": f"🔴 Snapshot Failure: {event.get('summary', '')}",
        "compliance_violation": f"⚠️ Compliance: {event.get('summary', '')}",
        "health_score_drop": f"🏥 Health Alert: {event.get('summary', '')}",
    }
    subject = subject_map.get(event_type, f"PF9 Alert: {event.get('summary', '')}")

    for user in users:
        if user["delivery_mode"] == "digest" and DIGEST_ENABLED:
            # Queue for digest
            queue_for_digest(conn, user["username"], user["email"], event)
            log_notification(conn, user, event, dkey, subject, "digest_queued")
        else:
            # Send immediately
            try:
                html_body = render_template(template_name, {
                    "event": event,
                    "user": user,
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                })
                success = send_email(user["email"], subject, html_body)
                status = "sent" if success else "failed"
                log_notification(conn, user, event, dkey, subject, status)
            except Exception as e:
                logger.error(f"Error dispatching to {user['username']}: {e}")
                log_notification(conn, user, event, dkey, subject, "failed", str(e))


def log_notification(conn, user: Dict, event: Dict, dkey: str, subject: str,
                     status: str, error: str = None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO notification_log
                (username, email, event_type, event_id, dedup_key, subject,
                 body_preview, delivery_status, error_message, sent_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user["username"], user["email"], event["event_type"],
            event.get("event_id", ""), dkey, subject,
            event.get("summary", "")[:200], status, error,
            datetime.utcnow() if status == "sent" else None,
        ))
    conn.commit()


def queue_for_digest(conn, username: str, email: str, event: Dict):
    """Accumulate event into the user's digest bucket."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO notification_digests (username, email, events_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (username)
            DO UPDATE SET events_json = notification_digests.events_json || %s::jsonb,
                          email = EXCLUDED.email
        """, (username, email, json.dumps([event]), json.dumps([event])))
    conn.commit()


def send_digests(conn):
    """Send accumulated digest emails. Called once per day at DIGEST_HOUR_UTC."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT username, email, events_json
            FROM notification_digests
            WHERE jsonb_array_length(events_json) > 0
        """)
        rows = cur.fetchall()

    for row in rows:
        events = row["events_json"] if isinstance(row["events_json"], list) else json.loads(row["events_json"])
        if not events:
            continue

        try:
            html_body = render_template("digest.html", {
                "user": {"username": row["username"], "email": row["email"]},
                "events": events,
                "count": len(events),
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            })
            subject = f"📬 PF9 Daily Digest: {len(events)} notification(s)"
            success = send_email(row["email"], subject, html_body)

            if success:
                # Clear the digest bucket
                with conn.cursor() as cur2:
                    cur2.execute("""
                        UPDATE notification_digests
                        SET events_json = '[]'::jsonb, last_sent_at = now()
                        WHERE username = %s
                    """, (row["username"],))
                conn.commit()
                logger.info(f"Digest sent to {row['username']} ({len(events)} events)")
        except Exception as e:
            logger.error(f"Failed to send digest to {row['username']}: {e}")

# ---------------------------------------------------------------------------
# Main poll loop
# ---------------------------------------------------------------------------

def poll_cycle(conn):
    """One poll cycle: collect events, dispatch notifications."""
    since = datetime.utcnow() - timedelta(seconds=LOOKBACK_SECONDS)

    collectors = [
        collect_drift_events,
        collect_snapshot_failures,
        collect_compliance_violations,
        collect_health_drops,
    ]

    total_events = 0
    for collector in collectors:
        try:
            events = collector(conn, since)
            for event in events:
                dispatch_event(conn, event)
            total_events += len(events)
        except Exception as e:
            logger.error(f"Error in collector {collector.__name__}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    if total_events > 0:
        logger.info(f"Poll cycle complete: {total_events} events processed")


def main():
    logger.info("PF9 Notification Worker starting...")
    logger.info(f"SMTP enabled: {SMTP_ENABLED}, poll interval: {POLL_INTERVAL}s")
    logger.info(f"Digest enabled: {DIGEST_ENABLED}, digest hour UTC: {DIGEST_HOUR_UTC}")

    # Wait for DB
    conn = None
    for attempt in range(30):
        try:
            conn = get_db_connection()
            logger.info("Database connected")
            break
        except Exception as e:
            logger.warning(f"DB connection attempt {attempt + 1}/30 failed: {e}")
            time.sleep(5)

    if conn is None:
        logger.error("Could not connect to database after 30 attempts. Exiting.")
        sys.exit(1)

    ensure_tables(conn)

    last_digest_date = None

    while True:
        try:
            # Check if connection is still alive
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except Exception:
                conn = get_db_connection()

            # Regular poll
            poll_cycle(conn)

            # Daily digest check
            now_utc = datetime.utcnow()
            today = now_utc.date()
            if (DIGEST_ENABLED
                    and now_utc.hour == DIGEST_HOUR_UTC
                    and last_digest_date != today):
                logger.info("Sending daily digests...")
                send_digests(conn)
                last_digest_date = today

        except Exception as e:
            logger.error(f"Poll cycle error: {e}")
            try:
                conn = get_db_connection()
            except Exception:
                pass

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
