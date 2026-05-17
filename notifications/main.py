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

import http.client
import ipaddress
import json as _json_stdlib
import socket
import urllib.parse

import psycopg2
from psycopg2.extras import RealDictCursor, Json

_ALIVE_FILE = "/tmp/alive"


def _touch_alive() -> None:
    """Write a heartbeat file so Kubernetes liveness probes can detect stalled workers."""
    try:
        with open(_ALIVE_FILE, "w") as fh:
            fh.write(str(time.time()))
    except OSError:
        pass
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
# SMTP config — DB overrides env vars (same pattern as api/smtp_helper.py)
# ---------------------------------------------------------------------------

def get_smtp_config(conn=None) -> dict:
    """
    Return effective SMTP configuration.  DB system_settings always win over
    env vars so changes made in the Admin UI take effect without a pod restart.
    """
    db: dict = {}
    try:
        _conn = conn or get_db_connection()
        _close = conn is None
        with _conn.cursor() as cur:
            cur.execute("SELECT key, value FROM system_settings WHERE key LIKE 'smtp.%%'")
            db = {row[0]: row[1] for row in cur.fetchall()}
        if _close:
            _conn.close()
    except Exception as exc:
        logger.debug("SMTP DB override lookup failed: %s — using env vars", exc)

    enabled_raw = db.get("smtp.enabled", "true" if SMTP_ENABLED else "false")
    enabled = enabled_raw.lower() in ("true", "1", "yes")

    host = db.get("smtp.host") or SMTP_HOST
    port_raw = db.get("smtp.port")
    port = int(port_raw) if port_raw and port_raw.isdigit() else SMTP_PORT
    tls_raw = db.get("smtp.use_tls")
    use_tls = (tls_raw.lower() in ("true", "1", "yes")) if tls_raw else SMTP_USE_TLS
    username = db.get("smtp.username") or SMTP_USERNAME

    stored_pw = db.get("smtp.password") or ""
    if stored_pw.startswith("fernet:"):
        # Decrypt the DB-stored password using the same key as the API
        try:
            from cryptography.fernet import Fernet
            _key_env = os.getenv("SMTP_CONFIG_KEY", "")
            if _key_env:
                _fernet = Fernet(_key_env.encode() if isinstance(_key_env, str) else _key_env)
                stored_pw = _fernet.decrypt(stored_pw[len("fernet:"):].encode()).decode()
            else:
                stored_pw = ""
        except Exception as exc:
            logger.warning("SMTP password decryption failed: %s", exc)
            stored_pw = ""
    password = stored_pw or SMTP_PASSWORD

    from_address = db.get("smtp.from_address") or SMTP_FROM_ADDRESS
    from_name = db.get("smtp.from_name") or SMTP_FROM_NAME

    return {
        "enabled": enabled,
        "host": host,
        "port": port,
        "use_tls": use_tls,
        "username": username,
        "password": password,
        "from_address": from_address,
        "from_name": from_name,
    }

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


# ---------------------------------------------------------------------------
# Circuit breaker (H15) — prevents cascading failures during DB outages
# ---------------------------------------------------------------------------
_cb_failure_count = 0
_cb_circuit_open_until = 0.0


def get_db_connection_with_cb():
    """Wrap get_db_connection() with a circuit breaker: after 3 consecutive
    failures, back off 60 seconds to prevent log storms during DB outages."""
    global _cb_failure_count, _cb_circuit_open_until
    if time.time() < _cb_circuit_open_until:
        raise RuntimeError("Circuit open -- DB unavailable, skipping job")
    try:
        conn = get_db_connection()
        _cb_failure_count = 0
        return conn
    except Exception:
        _cb_failure_count += 1
        if _cb_failure_count >= 3:
            _cb_circuit_open_until = time.time() + 60  # back off 60s
            logger.warning(
                "DB circuit breaker OPEN -- will retry in 60s (failure_count=%d)",
                _cb_failure_count,
            )
        raise


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
if not os.path.isdir(template_dir):  # L6: fail fast at startup, not on first render
    raise RuntimeError(f"Template directory missing: {template_dir}")
jinja_env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)

def render_template(template_name: str, context: Dict[str, Any]) -> str:
    tpl = jinja_env.get_template(template_name)
    return tpl.render(**context)


def send_email(to_address: str, subject: str, html_body: str, conn=None) -> bool:
    """Send a single email via SMTP. Returns True on success.
    Reads SMTP config fresh from DB on every call so admin-UI changes
    take effect immediately without a pod restart."""
    cfg = get_smtp_config(conn)

    if not cfg["enabled"]:
        logger.info("SMTP disabled — would send to %s: %s", to_address, subject)
        return True  # treat as success in dry-run mode

    if not cfg["host"]:
        logger.warning("SMTP host not configured — cannot send email to %s", to_address)
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{cfg['from_name']} <{cfg['from_address']}>"
        msg["To"] = to_address
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        if cfg["use_tls"]:
            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                if cfg["username"]:
                    server.login(cfg["username"], cfg["password"])
                server.sendmail(cfg["from_address"], [to_address], msg.as_string())
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
                server.ehlo()
                if cfg["username"]:
                    server.login(cfg["username"], cfg["password"])
                server.sendmail(cfg["from_address"], [to_address], msg.as_string())

        logger.info("Email sent to %s: %s", to_address, subject)
        return True

    except Exception as e:
        logger.error("Failed to send email to %s: %s", to_address, e)
        return False

# ---------------------------------------------------------------------------
# Event collectors — each returns a list of event dicts
# ---------------------------------------------------------------------------

def collect_drift_events(conn, since: datetime) -> List[Dict]:
    """Collect unacknowledged drift events since `since`."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT
                de.id, de.resource_type, de.resource_id,
                COALESCE(
                    NULLIF(NULLIF(de.resource_name, ''), de.resource_id),
                    NULLIF(CASE de.resource_type
                        WHEN 'servers'   THEN (SELECT s.name FROM servers   s WHERE s.id = de.resource_id)
                        WHEN 'volumes'   THEN (SELECT v.name FROM volumes   v WHERE v.id = de.resource_id)
                        WHEN 'networks'  THEN (SELECT n.name FROM networks  n WHERE n.id = de.resource_id)
                        WHEN 'snapshots' THEN (SELECT snap.name FROM snapshots snap WHERE snap.id = de.resource_id)
                    END, ''),
                    de.resource_id
                ) AS resource_name,
                de.field_changed, de.old_value, de.new_value, de.severity,
                COALESCE(de.project_name, proj.name) AS project_name,
                COALESCE(de.domain_name,  dom.name)  AS domain_name,
                de.detected_at,
                CASE de.field_changed
                    WHEN 'server_id'  THEN (SELECT s.name FROM servers  s WHERE s.id = de.old_value)
                    WHEN 'flavor_id'  THEN (SELECT f.name FROM flavors  f WHERE f.id = de.old_value)
                    WHEN 'network_id' THEN (SELECT n.name FROM networks n WHERE n.id = de.old_value)
                    WHEN 'image_id'   THEN (SELECT i.name FROM images   i WHERE i.id = de.old_value)
                END AS old_value_label,
                CASE de.field_changed
                    WHEN 'server_id'  THEN (SELECT s.name FROM servers  s WHERE s.id = de.new_value)
                    WHEN 'flavor_id'  THEN (SELECT f.name FROM flavors  f WHERE f.id = de.new_value)
                    WHEN 'network_id' THEN (SELECT n.name FROM networks n WHERE n.id = de.new_value)
                    WHEN 'image_id'   THEN (SELECT i.name FROM images   i WHERE i.id = de.new_value)
                END AS new_value_label
            FROM drift_events de
            LEFT JOIN projects proj ON proj.id = de.project_id
            LEFT JOIN domains  dom  ON dom.id  = de.domain_id
            WHERE de.detected_at >= %s
              AND de.acknowledged = false
            ORDER BY de.detected_at DESC
            LIMIT 200
        """, (since,))
        for row in cur.fetchall():
            resource_name = row.get("resource_name") or row["resource_id"]
            project_name  = row.get("project_name") or ""
            domain_name   = row.get("domain_name") or ""
            old_label = row.get("old_value_label")
            new_label = row.get("new_value_label")
            summary = (
                f"Drift detected on {row.get('resource_type', '')} "
                f"'{resource_name}'"
                + (f" (tenant: {project_name})" if project_name else "")
                + f": {row.get('field_changed', '')} changed"
            )
            events.append({
                "event_type": f"drift_{row['severity']}",
                "event_id": str(row["id"]),
                "resource_id": row["resource_id"] or "",
                "resource_name": resource_name,
                "resource_type": row.get("resource_type", ""),
                "severity": row["severity"],
                "field_name": row.get("field_changed", ""),
                "old_value": old_label or str(row.get("old_value", "") or ""),
                "old_value_raw": str(row.get("old_value", "") or "") if old_label else "",
                "new_value": new_label or str(row.get("new_value", "") or ""),
                "new_value_raw": str(row.get("new_value", "") or "") if new_label else "",
                "project_name": project_name,
                "domain_name": domain_name,
                "detected_at": row["detected_at"].isoformat() if row["detected_at"] else "",
                "summary": summary,
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
                success = send_email(user["email"], subject, html_body, conn=conn)
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


_MAX_DIGEST_EVENTS = 1000  # cap per-user digest bucket to prevent unbounded growth


def queue_for_digest(conn, username: str, email: str, event: Dict):
    """Accumulate event into the user's digest bucket (capped at _MAX_DIGEST_EVENTS)."""
    event_json = json.dumps([event])
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO notification_digests (username, email, events_json)
            VALUES (%s, %s, %s::jsonb)
            ON CONFLICT (username)
            DO UPDATE SET events_json = (
                CASE
                    WHEN jsonb_array_length(notification_digests.events_json) >= %s
                    THEN (
                        SELECT jsonb_agg(elem ORDER BY ord)
                        FROM jsonb_array_elements(notification_digests.events_json)
                             WITH ORDINALITY t(elem, ord)
                        WHERE ord > jsonb_array_length(notification_digests.events_json) - (%s - 1)
                    ) || %s::jsonb
                    ELSE notification_digests.events_json || %s::jsonb
                END
            ),
            email = EXCLUDED.email
        """, (
            username, email, event_json,           # INSERT values
            _MAX_DIGEST_EVENTS,                    # CASE: when >= cap
            _MAX_DIGEST_EVENTS,                    # trim: keep last N-1
            event_json,                            # append (trim branch)
            event_json,                            # append (normal branch)
        ))
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
            success = send_email(row["email"], subject, html_body, conn=conn)

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
# SSRF guard for tenant outbound webhooks
# ---------------------------------------------------------------------------

_TENANT_WEBHOOK_BLOCKED_RANGES = [
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


def _webhook_url_allowed(url: str) -> bool:
    """Return True if the URL host resolves only to public addresses."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in addr_infos:
        addr_str = info[4][0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for blocked in _TENANT_WEBHOOK_BLOCKED_RANGES:
            if addr in blocked:
                return False
    return True


def send_tenant_webhook(url: str, payload: dict) -> bool:
    """POST payload to tenant webhook URL. Returns True on success.
    SSRF guard is applied before any network call.
    Uses only stdlib http.client — no extra dependencies.
    """
    if not _webhook_url_allowed(url):
        logger.warning("Tenant webhook blocked (SSRF guard): %s", url)
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        body = _json_stdlib.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PF9-Notification-Worker/2.1",
            "Content-Length": str(len(body)),
        }
        port = parsed.port
        use_tls = parsed.scheme == "https"
        if use_tls:
            conn_cls = http.client.HTTPSConnection
        else:
            conn_cls = http.client.HTTPConnection
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        c = conn_cls(parsed.hostname, port or (443 if use_tls else 80), timeout=10)
        c.request("POST", path, body=body, headers=headers)
        resp = c.getresponse()
        resp.read()  # drain
        c.close()
        if 200 <= resp.status < 300:
            logger.info("Tenant webhook delivered to %s: HTTP %d", url, resp.status)
            return True
        logger.warning("Tenant webhook non-2xx: %s → HTTP %d", url, resp.status)
        return False
    except Exception as exc:
        logger.error("Tenant webhook delivery failed (%s): %s", url, exc)
        return False


# ---------------------------------------------------------------------------
# Tenant event collectors
# ---------------------------------------------------------------------------

def collect_tenant_snapshot_events(conn, since: datetime) -> List[Dict]:
    """Collect per-project snapshot status changes (completed/error) since `since`."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, project_id, project_name, name AS snapshot_name,
                   volume_id, size_gb, status, updated_at
            FROM   snapshots
            WHERE  updated_at >= %s
              AND  status IN ('available', 'error')
              AND  project_id IS NOT NULL
            ORDER  BY updated_at DESC
            LIMIT  200
            """,
            (since,),
        )
        for row in cur.fetchall():
            etype = (
                "snapshot_completed" if row["status"] == "available" else "snapshot_failed"
            )
            events.append({
                "event_type": etype,
                "event_id": str(row["id"]),
                "project_id": row["project_id"],
                "project_name": row.get("project_name", ""),
                "resource_id": str(row["id"]),
                "resource_name": row.get("snapshot_name", str(row["id"])),
                "volume_id": row.get("volume_id", ""),
                "size_gb": row.get("size_gb", 0),
                "status": row["status"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else "",
                "summary": (
                    f"Snapshot '{row.get('snapshot_name', row['id'])}' "
                    f"{'completed' if etype == 'snapshot_completed' else 'failed'} "
                    f"in project {row.get('project_name', row['project_id'])}"
                ),
            })
    return events


def collect_tenant_restore_events(conn, since: datetime) -> List[Dict]:
    """Collect per-project restore job completions/failures since `since`."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, project_id, project_name, vm_id, vm_name,
                   mode, status, failure_reason, finished_at
            FROM   restore_jobs
            WHERE  finished_at >= %s
              AND  status IN ('COMPLETED', 'FAILED')
            ORDER  BY finished_at DESC
            LIMIT  200
            """,
            (since,),
        )
        for row in cur.fetchall():
            etype = (
                "restore_completed" if row["status"] == "COMPLETED" else "restore_failed"
            )
            events.append({
                "event_type": etype,
                "event_id": str(row["id"]),
                "project_id": row["project_id"],
                "project_name": row.get("project_name", ""),
                "resource_id": str(row["id"]),
                "resource_name": row.get("vm_name", row.get("vm_id", str(row["id"]))),
                "vm_id": row.get("vm_id", ""),
                "vm_name": row.get("vm_name", ""),
                "mode": row.get("mode", ""),
                "status": row["status"],
                "failure_reason": row.get("failure_reason", ""),
                "finished_at": row["finished_at"].isoformat() if row["finished_at"] else "",
                "summary": (
                    f"Restore '{row.get('vm_name', row.get('vm_id', ''))}' "
                    f"{'completed' if etype == 'restore_completed' else 'failed'} "
                    f"in project {row.get('project_name', row['project_id'])}"
                ),
            })
    return events


def collect_tenant_quota_warnings(conn, since: datetime) -> List[Dict]:
    """Emit quota warning events for projects that crossed 80% or 95% usage."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT pq.project_id, p.name AS project_name,
                   pq.service, pq.resource,
                   pq.quota_limit, pq.in_use, pq.last_seen_at
            FROM   project_quotas pq
            LEFT   JOIN projects p ON p.id = pq.project_id
            WHERE  pq.quota_limit > 0
              AND  pq.in_use IS NOT NULL
              AND  (pq.in_use::float / pq.quota_limit) >= 0.80
              AND  pq.last_seen_at >= %s
            ORDER  BY (pq.in_use::float / pq.quota_limit) DESC
            LIMIT  200
            """,
            (since,),
        )
        for row in cur.fetchall():
            pct = (row["in_use"] / row["quota_limit"]) * 100
            etype = "quota_at_95pct" if pct >= 95.0 else "quota_at_80pct"
            events.append({
                "event_type": etype,
                "event_id": (
                    f"quota_{row['project_id']}_{row['service']}_{row['resource']}_"
                    f"{datetime.utcnow().strftime('%Y%m%d')}"
                ),
                "project_id": row["project_id"],
                "project_name": row.get("project_name", row["project_id"]),
                "resource_id": f"{row['service']}:{row['resource']}",
                "resource_name": f"{row['service']} / {row['resource']}",
                "service": row["service"],
                "resource": row["resource"],
                "quota_limit": row["quota_limit"],
                "in_use": row["in_use"],
                "pct_used": round(pct, 1),
                "last_seen_at": row["last_seen_at"].isoformat() if row["last_seen_at"] else "",
                "summary": (
                    f"Quota '{row['service']}/{row['resource']}' at {round(pct, 1)}% "
                    f"in project {row.get('project_name', row['project_id'])}"
                ),
            })
    return events


def collect_tenant_vm_provision_events(conn, since: datetime) -> List[Dict]:
    """Collect VM provisioning completion / failure events since `since`."""
    events = []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT  v.id, v.vm_name_suffix, v.status, v.error_msg,
                    v.created_at,
                    b.project_name, b.domain_name, b.region_id, b.created_by,
                    p.id AS project_id
            FROM    vm_provisioning_vms v
            JOIN    vm_provisioning_batches b ON b.id = v.batch_id
            LEFT    JOIN projects p ON p.name = b.project_name
            WHERE   v.created_at >= %s
              AND   v.status IN ('completed', 'failed')
            ORDER   BY v.created_at DESC
            LIMIT   200
            """,
            (since,),
        )
        for row in cur.fetchall():
            # Skip if we cannot resolve a project_id — nowhere to route notification
            if not row.get("project_id"):
                continue
            etype = (
                "vm_provisioned" if row["status"] == "completed" else "vm_provision_failed"
            )
            events.append({
                "event_type": etype,
                "event_id": f"vmprov_{row['id']}",
                "project_id": row["project_id"],
                "project_name": row.get("project_name", ""),
                "resource_id": str(row["id"]),
                "resource_name": row.get("vm_name_suffix", str(row["id"])),
                "status": row["status"],
                "error_msg": row.get("error_msg", ""),
                "region_id": row.get("region_id", ""),
                "created_by": row.get("created_by", ""),
                "created_at": row["created_at"].isoformat() if row["created_at"] else "",
                "summary": (
                    f"VM '{row.get('vm_name_suffix', row['id'])}' "
                    f"{'provisioned' if etype == 'vm_provisioned' else 'provision failed'} "
                    f"in project {row.get('project_name', row['project_id'])}"
                ),
            })
    return events


# ---------------------------------------------------------------------------
# Tenant notification dispatcher
# ---------------------------------------------------------------------------

def log_tenant_notification(
    conn,
    project_id: str,
    keystone_user_id: str,
    event_type: str,
    subject: str,
    delivery_status: str,
    error_message: Optional[str] = None,
    dedup_key_val: str = "",
):
    """Write a notification_log row tagged notification_target='tenant'."""
    username_tag = f"tenant:{project_id}:{keystone_user_id}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO notification_log
                (username, email, event_type, event_id, dedup_key, subject,
                 body_preview, delivery_status, error_message, sent_at,
                 notification_target)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                username_tag,
                "",
                event_type,
                "",
                dedup_key_val,
                subject,
                subject[:200],
                delivery_status,
                error_message,
                datetime.utcnow() if delivery_status == "sent" else None,
                "tenant",
            ),
        )
    conn.commit()


def dispatch_tenant_notifications(
    conn,
    event: Dict,
):
    """For a tenant event dict (must have project_id + event_type), look up
    tenant_notification_prefs and deliver via email or webhook.
    """
    event_type = event["event_type"]
    project_id = event.get("project_id")
    if not project_id:
        return

    dkey = dedup_key(
        event_type,
        event.get("resource_id", ""),
        event.get("event_id", ""),
    )

    # Dedup: skip if we already delivered this exact event (tenant path)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM notification_log
            WHERE dedup_key = %s
              AND delivery_status = 'sent'
              AND notification_target = 'tenant'
            LIMIT 1
            """,
            (dkey,),
        )
        if cur.fetchone():
            return

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, keystone_user_id, channel, endpoint, enabled
            FROM   tenant_notification_prefs
            WHERE  project_id = %s
              AND  event_type  = %s
              AND  enabled     = true
            """,
            (project_id, event_type),
        )
        prefs = cur.fetchall()

    if not prefs:
        return

    # Template mapping for email channel
    _template_map = {
        "snapshot_completed": "tenant_snapshot_completed.html",
        "snapshot_failed":    "tenant_snapshot_failed.html",
        "restore_completed":  "tenant_restore_done.html",
        "restore_failed":     "tenant_restore_done.html",
        "quota_at_80pct":     "tenant_quota_warning.html",
        "quota_at_95pct":     "tenant_quota_warning.html",
        "vm_provisioned":     "tenant_snapshot_completed.html",  # generic fallback
        "vm_provision_failed":"tenant_snapshot_failed.html",     # generic fallback
        "billing_invoice_ready": "tenant_snapshot_completed.html",
    }

    for pref in prefs:
        user_id = pref["keystone_user_id"]
        channel = pref["channel"]
        endpoint = pref["endpoint"]
        subject = f"Platform9: {event_type.replace('_', ' ').title()} — {event.get('resource_name', '')}"

        try:
            if channel == "email":
                template_name = _template_map.get(event_type, "tenant_snapshot_completed.html")
                html_body = render_template(
                    template_name,
                    {
                        "event": event,
                        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
                    },
                )
                success = send_email(endpoint, subject, html_body, conn=conn)
                status_val = "sent" if success else "failed"

            elif channel == "webhook":
                success = send_tenant_webhook(endpoint, event)
                status_val = "sent" if success else "failed"

            else:
                continue

            log_tenant_notification(
                conn, project_id, user_id, event_type, subject, status_val,
                dedup_key_val=dkey,
            )

        except Exception as exc:
            logger.error(
                "Tenant notification dispatch error [project=%s event=%s channel=%s]: %s",
                project_id, event_type, channel, exc,
            )
            try:
                log_tenant_notification(
                    conn, project_id, user_id, event_type,
                    subject if "subject" in dir() else event_type,
                    "failed", str(exc), dedup_key_val=dkey,
                )
            except Exception:
                pass


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

    # Tenant-facing event collectors
    tenant_collectors = [
        collect_tenant_snapshot_events,
        collect_tenant_restore_events,
        collect_tenant_quota_warnings,
        collect_tenant_vm_provision_events,
    ]

    tenant_total = 0
    for collector in tenant_collectors:
        try:
            events = collector(conn, since)
            for event in events:
                dispatch_tenant_notifications(conn, event)
            tenant_total += len(events)
        except Exception as e:
            logger.error(f"Error in tenant collector {collector.__name__}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    total_events += tenant_total
    if total_events > 0:
        logger.info(
            f"Poll cycle complete: {total_events} events processed "
            f"({tenant_total} tenant)"
        )


def main():
    logger.info("PF9 Notification Worker starting...")
    logger.info(f"SMTP env-var enabled: {SMTP_ENABLED} (DB override may differ), poll interval: {POLL_INTERVAL}s")
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

    # Log resolved SMTP config now that DB is available
    try:
        _smtp = get_smtp_config(conn)
        logger.info(
            "Effective SMTP config — enabled=%s host=%s port=%s tls=%s from=%s",
            _smtp["enabled"], _smtp["host"] or "(not set)", _smtp["port"],
            _smtp["use_tls"], _smtp["from_address"],
        )
    except Exception as _e:
        logger.warning("Could not resolve SMTP config at startup: %s", _e)

    last_digest_date = None

    while True:
        try:
            # Check if connection is still alive
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except Exception:
                conn = get_db_connection_with_cb()

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
                conn = get_db_connection_with_cb()
            except Exception:
                pass

        _touch_alive()  # heartbeat — liveness probe checks /tmp/alive mtime
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
