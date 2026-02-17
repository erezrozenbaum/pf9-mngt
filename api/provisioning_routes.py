"""
Customer Provisioning & Domain Management API
==============================================
Multi-step workflow that creates a complete customer environment
in Platform9 / OpenStack:

  1. Create Keystone Domain
  2. Create Keystone Project
  3. Create Keystone User (temp password, must change)
  4. Assign role (member / admin / service)
  5. Set compute quotas (Nova)
  6. Set network quotas (Neutron)
  7. Set storage quotas (Cinder)
  8. Create external VLAN network + subnet
  9. Create default security group with basic rules
 10. Send welcome email

Every step is logged to provisioning_steps for auditability.
"""

import os
import json
import secrets
import string
import logging
import smtplib
import ssl
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel, validator
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from pf9_control import get_client
from auth import require_permission, get_current_user

logger = logging.getLogger("pf9_provisioning")

router = APIRouter(prefix="/api/provisioning", tags=["provisioning"])

# ---------------------------------------------------------------------------
# SMTP config (reuse from env — same as notification_worker)
# ---------------------------------------------------------------------------
SMTP_ENABLED = os.getenv("SMTP_ENABLED", "false").lower() in ("true", "1", "yes")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes")
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.getenv("SMTP_FROM_ADDRESS", "pf9-mgmt@example.com")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Platform9 Management")

PF9_LOGIN_URL = os.getenv("PF9_LOGIN_URL", os.getenv("PF9_AUTH_URL", "").replace("/keystone/v3", ""))

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _get_conn():
    from db_pool import get_connection
    return get_connection()


def _ensure_tables():
    """Run migration if tables don't exist yet."""
    from db_pool import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'provisioning_jobs'
                )
            """)
            if not cur.fetchone()[0]:
                migration = os.path.join(
                    os.path.dirname(__file__), "..", "db", "migrate_provisioning.sql"
                )
                if os.path.exists(migration):
                    with open(migration) as f:
                        cur.execute(f.read())
                    conn.commit()
                    logger.info("Provisioning tables created")


def _ensure_activity_log_table():
    """Run activity_log migration if table doesn't exist."""
    from db_pool import get_connection
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'activity_log'
                )
            """)
            if not cur.fetchone()[0]:
                migration = os.path.join(
                    os.path.dirname(__file__), "..", "db", "migrate_activity_log.sql"
                )
                if os.path.exists(migration):
                    with open(migration) as f:
                        cur.execute(f.read())
                    conn.commit()
                    logger.info("Activity log table created")


# Run on import
try:
    _ensure_tables()
except Exception as e:
    logger.warning(f"Could not ensure provisioning tables on startup: {e}")

try:
    _ensure_activity_log_table()
except Exception as e:
    logger.warning(f"Could not ensure activity_log table on startup: {e}")


# ---------------------------------------------------------------------------
# Activity log + notification helpers
# ---------------------------------------------------------------------------

def _log_activity(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str = None,
    resource_name: str = None,
    domain_id: str = None,
    domain_name: str = None,
    details: dict = None,
    ip_address: str = None,
    result: str = "success",
    error_message: str = None,
):
    """Insert a row into activity_log for central audit trail."""
    try:
        from db_pool import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO activity_log
                        (actor, action, resource_type, resource_id, resource_name,
                         domain_id, domain_name, details, ip_address, result, error_message)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    actor, action, resource_type, resource_id, resource_name,
                    domain_id, domain_name, Json(details or {}),
                    ip_address, result, error_message,
                ))
    except Exception as e:
        logger.error(f"Failed to write activity log: {e}")


def _fire_notification(
    event_type: str,
    summary: str,
    severity: str = "info",
    resource_id: str = "",
    resource_name: str = "",
    details: dict = None,
    domain_name: str = "",
    project_name: str = "",
    actor: str = "",
):
    """Insert a notification event for each subscriber and attempt to send
    email for 'immediate' delivery mode subscribers."""
    try:
        from db_pool import get_connection
        import hashlib
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find all subscribers for this event_type
                severity_rank = {"info": 0, "warning": 1, "critical": 2}
                event_rank = severity_rank.get(severity, 0)
                cur.execute("""
                    SELECT username, email, delivery_mode, severity_min
                    FROM notification_preferences
                    WHERE event_type = %s AND enabled = true
                """, (event_type,))
                subscribers = cur.fetchall()

                dkey = hashlib.sha256(
                    f"{event_type}:{resource_id}:{datetime.now(timezone.utc).isoformat()}".encode()
                ).hexdigest()[:32]

                subject = f"PF9 Alert: {summary}"

                for sub in subscribers:
                    min_rank = severity_rank.get(sub["severity_min"], 0)
                    if event_rank < min_rank:
                        continue

                    # Attempt email for immediate subscribers
                    status = "pending"
                    sent_at = None
                    if sub["delivery_mode"] == "immediate" and SMTP_ENABLED:
                        # Build optional context rows for the email
                        context_rows = ""
                        if domain_name:
                            context_rows += f'<tr><td style="padding:4px 12px 4px 0;font-weight:600;">Domain:</td><td>{domain_name}</td></tr>\n'
                        if project_name:
                            context_rows += f'<tr><td style="padding:4px 12px 4px 0;font-weight:600;">Tenant:</td><td>{project_name}</td></tr>\n'
                        if actor:
                            context_rows += f'<tr><td style="padding:4px 12px 4px 0;font-weight:600;">Performed By:</td><td>{actor}</td></tr>\n'

                        html_body = f"""
                        <html><body style="font-family:sans-serif;padding:20px;">
                        <h2 style="color:#1a73e8;">🔔 {subject}</h2>
                        <p>{summary}</p>
                        <table style="margin:12px 0;font-size:14px;">
                          <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Event Type:</td><td>{event_type}</td></tr>
                          <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Resource:</td><td>{resource_name or resource_id or 'N/A'}</td></tr>
                          {context_rows}
                          <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Severity:</td><td>{severity}</td></tr>
                          <tr><td style="padding:4px 12px 4px 0;font-weight:600;">Time:</td><td>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</td></tr>
                        </table>
                        <p style="color:#666;font-size:12px;">You are receiving this because you subscribed to '{event_type}' notifications.</p>
                        </body></html>
                        """
                        if _send_email(sub["email"], subject, html_body):
                            status = "sent"
                            sent_at = datetime.now(timezone.utc)
                        else:
                            status = "failed"

                    cur.execute("""
                        INSERT INTO notification_log
                            (username, email, event_type, event_id, dedup_key,
                             subject, body_preview, delivery_status, sent_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        sub["username"], sub["email"], event_type,
                        resource_id, dkey, subject, summary[:200],
                        status, sent_at,
                    ))
    except Exception as e:
        logger.error(f"Failed to fire notification ({event_type}): {e}")


def _get_actor(user) -> str:
    """Extract username from the auth user object."""
    if isinstance(user, dict):
        return user.get("username", "system")
    return getattr(user, "username", "system")


def _get_client_ip(request: Request) -> str:
    """Extract client IP from the request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ComputeQuotas(BaseModel):
    cores: int = 20
    ram: int = 51200          # MB (50 GiB)
    instances: int = 10
    server_groups: int = 10
    server_group_members: int = 10


class NetworkQuotas(BaseModel):
    network: int = 100
    subnet: int = 100
    router: int = 10
    port: int = 500
    floatingip: int = 50
    security_group: int = 10
    security_group_rule: int = 100


class StorageQuotas(BaseModel):
    gigabytes: int = 300      # Total Block Storage (GB)
    volumes: int = 10
    snapshots: int = 10         # Volume Snapshots
    per_volume_gigabytes: int = -1   # Max Volume Size (GB), -1 = unlimited


class SecurityGroupRule(BaseModel):
    direction: str = "ingress"
    protocol: Optional[str] = None
    port_range_min: Optional[int] = None
    port_range_max: Optional[int] = None
    remote_ip_prefix: Optional[str] = "0.0.0.0/0"
    ethertype: str = "IPv4"
    description: str = ""


class ProvisionRequest(BaseModel):
    # Domain
    domain_name: str
    domain_description: str = ""
    existing_domain_id: Optional[str] = None  # if set, skip domain creation and use existing
    # Project
    project_name: str
    project_description: str = ""
    subscription_id: str = ""  # naming convention: {domain}_tenant_subid_{subscription_id}
    # User
    username: str
    user_email: str = ""
    user_password: Optional[str] = None  # auto-generated if empty
    user_role: str = "member"            # actual Keystone role name
    # Network
    create_network: bool = True
    network_name: str = ""
    network_type: str = "vlan"           # vlan | flat | vxlan
    physical_network: str = "physnet1"
    vlan_id: Optional[int] = None
    subnet_cidr: str = "10.0.0.0/24"
    gateway_ip: str = ""
    enable_dhcp: bool = True
    allocation_pool_start: str = ""
    allocation_pool_end: str = ""
    dns_nameservers: List[str] = ["8.8.8.8", "8.8.4.4"]
    # Security group
    create_security_group: bool = True
    security_group_name: str = "default-sg"
    default_sg_rules: List[SecurityGroupRule] = []
    custom_sg_rules: List[SecurityGroupRule] = []  # additional user-defined ports
    # Quotas
    compute_quotas: ComputeQuotas = ComputeQuotas()
    network_quotas: NetworkQuotas = NetworkQuotas()
    storage_quotas: StorageQuotas = StorageQuotas()
    # Email
    send_welcome_email: bool = True
    include_user_email: bool = False  # opt-in: include created user's email in recipients
    email_recipients: List[str] = []  # additional/override email recipients

    @validator("user_role")
    def validate_role(cls, v):
        # Accept any role name — will be validated against Keystone at provision time
        if not v or not v.strip():
            raise ValueError("user_role is required")
        return v.strip()

    @validator("network_type")
    def validate_net_type(cls, v):
        if v not in ("vlan", "flat", "vxlan"):
            raise ValueError("network_type must be vlan, flat, or vxlan")
        return v


# ---------------------------------------------------------------------------
# Provisioning engine
# ---------------------------------------------------------------------------

def _generate_password(length: int = 16) -> str:
    """Generate a strong random password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        # Ensure complexity
        if (any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
            and any(c in "!@#$%^&*" for c in pwd)):
            return pwd


def _log_step(conn, job_id: str, step_number: int, step_name: str,
              description: str, status: str = "pending",
              resource_id: str = None, detail: dict = None, error: str = None):
    """Insert or update a provisioning step."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO provisioning_steps
                (job_id, step_number, step_name, description, status,
                 resource_id, detail, error, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s IN ('running','completed','failed') THEN now() END,
                    CASE WHEN %s IN ('completed','failed') THEN now() END)
            ON CONFLICT (id) DO NOTHING
            RETURNING id
        """, (job_id, step_number, step_name, description, status,
              resource_id, Json(detail or {}), error, status, status))
        conn.commit()


def _update_step(conn, job_id: str, step_number: int,
                 status: str, resource_id: str = None,
                 detail: dict = None, error: str = None):
    """Update an existing step."""
    with conn.cursor() as cur:
        sets = ["status = %s"]
        vals = [status]
        if resource_id:
            sets.append("resource_id = %s")
            vals.append(resource_id)
        if detail:
            sets.append("detail = %s")
            vals.append(Json(detail))
        if error:
            sets.append("error = %s")
            vals.append(error)
        if status == "running":
            sets.append("started_at = now()")
        if status in ("completed", "failed"):
            sets.append("completed_at = now()")
        vals.extend([job_id, step_number])
        cur.execute(
            f"UPDATE provisioning_steps SET {', '.join(sets)} "
            f"WHERE job_id = %s AND step_number = %s",
            vals,
        )
        conn.commit()


# PF9 role mapping — maps our provisioning labels to actual Keystone role names.
# PF9 Private Cloud Director recognises these three tenant roles:
#   "Self-service User"  →  Keystone "member"
#   "Administrator"      →  Keystone "admin"
#   "Read Only User"     →  Keystone "reader"
# Other Keystone roles (service, manager, …) are NOT visible in the PF9 UI
# tenant assignment dropdown, so assigning them appears as "no role".
ROLE_MAP = {
    "member": "member",
    "admin": "admin",
    "reader": "reader",
}

# Human-friendly labels matching PF9 Private Cloud Director UI
PF9_ROLE_LABELS = {
    "member": "Self-service User",
    "admin": "Administrator",
    "reader": "Read Only User",
}


def _run_provisioning(conn, job_id: str, req: ProvisionRequest, created_by: str):
    """Execute the full provisioning workflow."""
    client = get_client()
    # Force re-auth to ensure fresh token
    client.token = None
    client.authenticate()

    password = req.user_password or _generate_password()
    results: Dict[str, Any] = {}
    step = 0

    def run_step(name: str, desc: str, fn):
        nonlocal step
        step += 1
        _log_step(conn, job_id, step, name, desc, "running")
        try:
            result = fn()
            rid = None
            if isinstance(result, dict):
                rid = result.get("id", None)
            _update_step(conn, job_id, step, "completed",
                         resource_id=rid,
                         detail=result if isinstance(result, dict) else {"result": str(result)})
            return result
        except Exception as e:
            _update_step(conn, job_id, step, "failed", error=str(e))
            raise

    try:
        # Update job status to running
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE provisioning_jobs SET status='running', started_at=now() WHERE job_id=%s",
                (job_id,)
            )
            conn.commit()

        # ── Step 1: Create Domain (or use existing) ──────────
        if req.existing_domain_id:
            # Using an existing domain — fetch and validate
            domain = run_step(
                "use_existing_domain",
                f"Using existing domain for: {req.domain_name}",
                lambda: client.get_domain(req.existing_domain_id),
            )
            domain_id = domain["id"]
        else:
            domain = run_step(
                "create_domain",
                f"Create Keystone domain: {req.domain_name}",
                lambda: client.create_domain(req.domain_name, req.domain_description),
            )
            domain_id = domain["id"]
        results["domain_id"] = domain_id

        # ── Step 2: Create Project ─────────────────────────
        project = run_step(
            "create_project",
            f"Create project: {req.project_name} in domain {req.domain_name}",
            lambda: client.create_project(req.project_name, domain_id, req.project_description),
        )
        project_id = project["id"]
        results["project_id"] = project_id

        # ── Step 3: Create User ────────────────────────────
        user = run_step(
            "create_user",
            f"Create user: {req.username} with temporary password",
            lambda: client.create_user(
                name=req.username,
                password=password,
                domain_id=domain_id,
                email=req.user_email,
                description=f"Provisioned user for {req.domain_name}",
                force_password_change=True,
            ),
        )
        user_id = user["id"]
        results["user_id"] = user_id

        # ── Step 4: Assign Role ────────────────────────────
        def assign_roles():
            roles = client.list_roles()
            target_role_name = ROLE_MAP.get(req.user_role, req.user_role)
            role = next((r for r in roles if r["name"] == target_role_name), None)
            if not role:
                # Try case-insensitive match
                role = next((r for r in roles if r["name"].lower() == target_role_name.lower()), None)
            if not role:
                avail = ', '.join(sorted(r['name'] for r in roles))
                raise RuntimeError(f"Role '{target_role_name}' not found in Keystone. Available roles: {avail}")
            # Assign on project
            client.assign_role_to_user_on_project(project_id, user_id, role["id"])
            # If admin, also assign on domain
            if req.user_role == "admin":
                client.assign_role_to_user_on_domain(domain_id, user_id, role["id"])
            return {"role_name": target_role_name, "role_id": role["id"],
                    "assigned_on": "project+domain" if req.user_role == "admin" else "project"}

        run_step(
            "assign_role",
            f"Assign {req.user_role} role to user {req.username}",
            assign_roles,
        )

        # ── Step 5: Set Compute Quotas ─────────────────────
        compute_q = req.compute_quotas.dict()
        run_step(
            "set_compute_quotas",
            f"Set Nova compute quotas on project {req.project_name}",
            lambda: client.update_compute_quotas(project_id, compute_q),
        )
        results["compute_quotas"] = compute_q

        # ── Step 6: Set Network Quotas ─────────────────────
        network_q = req.network_quotas.dict()
        run_step(
            "set_network_quotas",
            f"Set Neutron network quotas on project {req.project_name}",
            lambda: client.update_network_quotas(project_id, network_q),
        )
        results["network_quotas"] = network_q

        # ── Step 7: Set Storage Quotas ─────────────────────
        storage_q = req.storage_quotas.dict()
        run_step(
            "set_storage_quotas",
            f"Set Cinder storage quotas on project {req.project_name}",
            lambda: client.update_storage_quotas(project_id, storage_q),
        )
        results["storage_quotas"] = storage_q

        # ── Step 8: Create External Network + Subnet ───────
        network_id = None
        subnet_id = None
        if req.create_network:
            net_name = req.network_name or f"{req.domain_name}-ext-net"
            network = run_step(
                "create_network",
                f"Create {req.network_type.upper()} external network: {net_name}",
                lambda: client.create_provider_network(
                    name=net_name,
                    network_type=req.network_type,
                    physical_network=req.physical_network,
                    segmentation_id=req.vlan_id,
                    project_id=project_id,
                    shared=False,
                    external=True,
                ),
            )
            network_id = network["id"]
            results["network_id"] = network_id

            # Create subnet
            sub_name = f"{net_name}-subnet"
            # Build allocation pools if specified
            alloc_pools = None
            if req.allocation_pool_start and req.allocation_pool_end:
                alloc_pools = [{"start": req.allocation_pool_start, "end": req.allocation_pool_end}]
            subnet = run_step(
                "create_subnet",
                f"Create subnet {req.subnet_cidr} on {net_name}",
                lambda: client.create_subnet(
                    network_id=network_id,
                    cidr=req.subnet_cidr,
                    name=sub_name,
                    gateway_ip=req.gateway_ip or None,
                    dns_nameservers=req.dns_nameservers,
                    enable_dhcp=req.enable_dhcp,
                    allocation_pools=alloc_pools,
                    project_id=project_id,
                ),
            )
            subnet_id = subnet["id"]
            results["subnet_id"] = subnet_id

        # ── Step 9: Create Default Security Group ──────────
        sg_id = None
        if req.create_security_group:
            sg = run_step(
                "create_security_group",
                f"Create default security group: {req.security_group_name}",
                lambda: client.create_security_group(
                    name=req.security_group_name,
                    description=f"Default security group for {req.domain_name}",
                    project_id=project_id,
                ),
            )
            sg_data = sg.get("security_group", sg)
            sg_id = sg_data["id"]
            results["security_group_id"] = sg_id

            # Add default rules + any custom rules
            default_rules = req.default_sg_rules or [
                SecurityGroupRule(direction="ingress", protocol="tcp",
                                  port_range_min=22, port_range_max=22,
                                  remote_ip_prefix="0.0.0.0/0",
                                  description="SSH"),
                SecurityGroupRule(direction="ingress", protocol="icmp",
                                  remote_ip_prefix="0.0.0.0/0",
                                  description="ICMP ping"),
                SecurityGroupRule(direction="ingress", protocol="tcp",
                                  port_range_min=443, port_range_max=443,
                                  remote_ip_prefix="0.0.0.0/0",
                                  description="HTTPS"),
                SecurityGroupRule(direction="ingress", protocol="tcp",
                                  port_range_min=80, port_range_max=80,
                                  remote_ip_prefix="0.0.0.0/0",
                                  description="HTTP"),
                SecurityGroupRule(direction="egress",
                                  remote_ip_prefix="0.0.0.0/0",
                                  description="Allow all egress"),
            ]
            # Append custom user-defined rules
            all_rules = default_rules + (req.custom_sg_rules or [])

            def add_sg_rules():
                added = []
                for rule in all_rules:
                    try:
                        r = client.create_security_group_rule(
                            security_group_id=sg_id,
                            direction=rule.direction,
                            protocol=rule.protocol,
                            port_range_min=rule.port_range_min,
                            port_range_max=rule.port_range_max,
                            remote_ip_prefix=rule.remote_ip_prefix,
                            ethertype=rule.ethertype,
                            description=rule.description,
                        )
                        added.append(r)
                    except Exception as e:
                        # Duplicate rule (409) is OK
                        if "409" not in str(e) and "already exists" not in str(e).lower():
                            logger.warning(f"SG rule failed: {e}")
                return {"rules_added": len(added)}

            run_step(
                "add_security_group_rules",
                f"Add default rules to {req.security_group_name}",
                add_sg_rules,
            )

        # ── Step 10: Send Welcome Email ────────────────────
        # Determine email recipients list (user email only if opt-in)
        base_recipients = list(req.email_recipients or [])
        if req.include_user_email and req.user_email:
            base_recipients.append(req.user_email)
        recipients = list(set(base_recipients))
        recipients = [r for r in recipients if r and "@" in r]

        if req.send_welcome_email and recipients:
            def send_welcome():
                login_url = PF9_LOGIN_URL or "https://your-pf9-instance.platform9.io"
                subject = f"Welcome to Platform9 — Your account is ready"

                # Collect all SG rules for email display
                sg_rules_display = []
                effective_rules = all_rules if req.create_security_group else []
                for r in effective_rules:
                    port_str = ""
                    if r.port_range_min and r.port_range_max:
                        port_str = f"{r.port_range_min}-{r.port_range_max}" if r.port_range_min != r.port_range_max else str(r.port_range_min)
                    sg_rules_display.append({
                        "direction": r.direction.upper(),
                        "protocol": (r.protocol or "All").upper(),
                        "ports": port_str or "All",
                        "cidr": r.remote_ip_prefix or "0.0.0.0/0",
                        "description": r.description,
                    })

                html = _render_welcome_email(
                    username=req.username,
                    password=password,
                    login_url=login_url,
                    domain_name=req.domain_name,
                    project_name=req.project_name,
                    user_role=req.user_role,
                    subscription_id=req.subscription_id or "",
                    network_name=req.network_name or f"{req.domain_name}-ext-net",
                    network_type=req.network_type,
                    vlan_id=req.vlan_id,
                    subnet_cidr=req.subnet_cidr,
                    gateway_ip=req.gateway_ip,
                    dns_nameservers=req.dns_nameservers,
                    security_group_name=req.security_group_name if req.create_security_group else None,
                    sg_rules=sg_rules_display,
                    compute_quotas=compute_q,
                    network_quotas=network_q,
                    storage_quotas=storage_q,
                    create_network=req.create_network,
                    domain_description=req.domain_description,
                    project_description=req.project_description,
                )
                sent_to = []
                for recipient in recipients:
                    ok = _send_email(recipient, subject, html)
                    if ok:
                        sent_to.append(recipient)
                return {"emails_sent": len(sent_to), "to": sent_to}

            run_step(
                "send_welcome_email",
                f"Send welcome email to {', '.join(recipients)}",
                send_welcome,
            )

        # ── Mark job completed ─────────────────────────────
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE provisioning_jobs
                SET status = 'completed', completed_at = now(),
                    domain_id = %s, project_id = %s, user_id = %s,
                    network_id = %s, subnet_id = %s, security_group_id = %s
                WHERE job_id = %s
            """, (results.get("domain_id"),
                  results.get("project_id"),
                  results.get("user_id"),
                  results.get("network_id"),
                  results.get("subnet_id"),
                  results.get("security_group_id"),
                  job_id))
            conn.commit()

        return results

    except Exception as e:
        # Mark job as failed
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE provisioning_jobs SET status='failed', completed_at=now(), "
                "error_message=%s WHERE job_id=%s",
                (str(e), job_id),
            )
            conn.commit()
        raise


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def _render_welcome_email(username: str, password: str, login_url: str,
                          domain_name: str, project_name: str,
                          user_role: str,
                          subscription_id: str = "",
                          network_name: str = "",
                          network_type: str = "",
                          vlan_id: int = None,
                          subnet_cidr: str = "",
                          gateway_ip: str = "",
                          dns_nameservers: list = None,
                          security_group_name: str = None,
                          sg_rules: list = None,
                          compute_quotas: dict = None,
                          network_quotas: dict = None,
                          storage_quotas: dict = None,
                          create_network: bool = True,
                          domain_description: str = "",
                          project_description: str = "") -> str:
    """Render welcome email HTML with full provisioning details."""
    # Check multiple possible template locations
    template_dirs = [
        os.path.join(os.path.dirname(__file__), "notification_templates"),   # Docker mount
        os.path.join(os.path.dirname(__file__), "..", "notifications", "templates"),  # Dev
    ]
    template_vars = dict(
        username=username, password=password, login_url=login_url,
        domain_name=domain_name, project_name=project_name,
        user_role=user_role, subscription_id=subscription_id,
        network_name=network_name, network_type=network_type,
        vlan_id=vlan_id, subnet_cidr=subnet_cidr,
        gateway_ip=gateway_ip, dns_nameservers=dns_nameservers or [],
        security_group_name=security_group_name,
        sg_rules=sg_rules or [],
        compute_quotas=compute_quotas or {},
        network_quotas=network_quotas or {},
        storage_quotas=storage_quotas or {},
        create_network=create_network,
        domain_description=domain_description,
        project_description=project_description,
    )
    for tpl_dir in template_dirs:
        template_path = os.path.join(tpl_dir, "customer_welcome.html")
        if os.path.exists(template_path):
            from jinja2 import Environment, FileSystemLoader
            env = Environment(loader=FileSystemLoader(tpl_dir), autoescape=True)
            tpl = env.get_template("customer_welcome.html")
            return tpl.render(**template_vars)

    # Fallback inline template
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
      <div style="background: #1a365d; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
        <h1 style="margin: 0;">Welcome to Platform9</h1>
      </div>
      <div style="border: 1px solid #e2e8f0; padding: 20px; border-radius: 0 0 8px 8px;">
        <p>Hello <strong>{username}</strong>,</p>
        <p>Your Platform9 account has been provisioned. Here are your login details:</p>
        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
          <tr><td style="padding: 8px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">Login URL</td>
              <td style="padding: 8px; border-bottom: 1px solid #e2e8f0;"><a href="{login_url}">{login_url}</a></td></tr>
          <tr><td style="padding: 8px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">Username</td>
              <td style="padding: 8px; border-bottom: 1px solid #e2e8f0;">{username}</td></tr>
          <tr><td style="padding: 8px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">Temporary Password</td>
              <td style="padding: 8px; border-bottom: 1px solid #e2e8f0;"><code>{password}</code></td></tr>
          <tr><td style="padding: 8px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">Domain</td>
              <td style="padding: 8px; border-bottom: 1px solid #e2e8f0;">{domain_name}</td></tr>
          <tr><td style="padding: 8px; border-bottom: 1px solid #e2e8f0; font-weight: bold;">Project</td>
              <td style="padding: 8px; border-bottom: 1px solid #e2e8f0;">{project_name}</td></tr>
          <tr><td style="padding: 8px; font-weight: bold;">Role</td>
              <td style="padding: 8px;">{user_role}</td></tr>
        </table>
        <div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin: 16px 0; border-radius: 4px;">
          <strong>⚠️ Important:</strong> You must change your password upon first login.
        </div>
        <p>If you have any questions, please contact your Platform9 administrator.</p>
      </div>
    </body>
    </html>
    """


def _send_email(to_address: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP."""
    if not SMTP_ENABLED:
        logger.info(f"SMTP disabled — would send to {to_address}: {subject}")
        return True

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
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/provision")
async def provision_customer(
    req: ProvisionRequest,
    request: Request,
    user=Depends(require_permission("provisioning", "write")),
):
    """Execute full customer provisioning workflow."""
    from db_pool import get_connection

    with get_connection() as conn:
        # Create the job record
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO provisioning_jobs
                    (domain_name, project_name, username, user_email, user_role,
                     network_name, network_type, vlan_id, subnet_cidr, gateway_ip,
                     dns_nameservers, quota_compute, quota_network, quota_storage,
                     created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING job_id, id
            """, (
                req.domain_name, req.project_name, req.username,
                req.user_email, req.user_role,
                req.network_name or f"{req.domain_name}-ext-net",
                req.network_type, req.vlan_id, req.subnet_cidr, req.gateway_ip,
                req.dns_nameservers,
                Json(req.compute_quotas.dict()),
                Json(req.network_quotas.dict()),
                Json(req.storage_quotas.dict()),
                user.get("username", "system") if isinstance(user, dict) else "system",
            ))
            job = cur.fetchone()
            conn.commit()

        job_id = job["job_id"]

        actor = _get_actor(user)
        client_ip = _get_client_ip(request)

        try:
            results = _run_provisioning(conn, job_id, req, actor)

            # Activity log — successful provision
            _log_activity(
                actor=actor, action="provision", resource_type="tenant",
                resource_name=f"{req.domain_name}/{req.project_name}",
                domain_name=req.domain_name,
                details={"job_id": job_id, "username": req.username, "role": req.user_role},
                ip_address=client_ip, result="success",
            )
            # Notification
            _fire_notification(
                event_type="tenant_provisioned", severity="info",
                summary=f"Tenant '{req.domain_name}/{req.project_name}' provisioned by {actor}",
                resource_name=f"{req.domain_name}/{req.project_name}",
                details={"job_id": job_id, "actor": actor},
            )

            return {
                "status": "completed",
                "job_id": job_id,
                "results": results,
            }
        except Exception as e:
            logger.error(f"Provisioning failed for job {job_id}: {e}\n{traceback.format_exc()}")

            _log_activity(
                actor=actor, action="provision", resource_type="tenant",
                resource_name=f"{req.domain_name}/{req.project_name}",
                domain_name=req.domain_name,
                details={"job_id": job_id},
                ip_address=client_ip, result="failure", error_message=str(e),
            )

            return {
                "status": "failed",
                "job_id": job_id,
                "error": str(e),
            }


@router.get("/logs")
async def get_provisioning_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    user=Depends(require_permission("provisioning", "read")),
):
    """Get provisioning job history."""
    from db_pool import get_connection

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where = ""
            params: list = []
            if status_filter:
                where = "WHERE status = %s"
                params.append(status_filter)
            params.extend([limit, offset])
            cur.execute(f"""
                SELECT job_id, domain_name, project_name, username, user_email,
                       user_role, status, created_by, created_at, started_at,
                       completed_at, error_message,
                       domain_id, project_id, user_id, network_id
                FROM provisioning_jobs
                {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, params)
            jobs = cur.fetchall()

            cur.execute(f"SELECT count(*) FROM provisioning_jobs {where}",
                        params[:1] if status_filter else [])
            total = cur.fetchone()["count"]

    return {"jobs": jobs, "total": total, "limit": limit, "offset": offset}


@router.get("/logs/{job_id}")
async def get_provisioning_job_detail(
    job_id: str,
    user=Depends(require_permission("provisioning", "read")),
):
    """Get detailed steps for a specific provisioning job."""
    from db_pool import get_connection

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM provisioning_jobs WHERE job_id = %s", (job_id,)
            )
            job = cur.fetchone()
            if not job:
                raise HTTPException(404, "Job not found")

            cur.execute(
                "SELECT * FROM provisioning_steps WHERE job_id = %s ORDER BY step_number",
                (job_id,),
            )
            steps = cur.fetchall()

    return {"job": job, "steps": steps}


@router.get("/quota-defaults")
async def get_quota_defaults(
    user=Depends(require_permission("provisioning", "read")),
):
    """Return all available quota fields with their default values."""
    return {
        "compute": ComputeQuotas().dict(),
        "network": NetworkQuotas().dict(),
        "storage": StorageQuotas().dict(),
    }


@router.get("/check-domain/{domain_name}")
async def check_domain_exists(
    domain_name: str,
    user=Depends(require_permission("provisioning", "read")),
):
    """
    Check if a domain name already exists in Keystone.
    Returns the domain info if found, or exists=false.
    """
    client = get_client()
    try:
        domains = client.list_domains()
        for d in domains:
            if d.get("name", "").lower() == domain_name.lower():
                counts = {"projects": 0, "users": 0}
                try:
                    counts = client.count_domain_resources(d["id"])
                except Exception:
                    pass
                return {
                    "exists": True,
                    "domain": {
                        "id": d["id"],
                        "name": d.get("name", ""),
                        "description": d.get("description", ""),
                        "enabled": d.get("enabled", True),
                        "projects": counts["projects"],
                        "users": counts["users"],
                    },
                }
    except Exception as e:
        raise HTTPException(502, f"Failed to query Keystone: {e}")

    return {"exists": False, "domain": None}


@router.get("/check-project/{project_name}")
async def check_project_exists(
    project_name: str,
    domain_id: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "read")),
):
    """
    Check if a project name already exists, optionally within a specific domain.
    Returns the project info if found.
    """
    client = get_client()
    try:
        projects = client.list_projects(domain_id=domain_id) if domain_id else client.list_projects()
        for p in projects:
            if p.get("name", "").lower() == project_name.lower():
                return {
                    "exists": True,
                    "project": {
                        "id": p["id"],
                        "name": p.get("name", ""),
                        "description": p.get("description", ""),
                        "domain_id": p.get("domain_id", ""),
                        "enabled": p.get("enabled", True),
                    },
                }
    except Exception as e:
        raise HTTPException(502, f"Failed to query Keystone: {e}")

    return {"exists": False, "project": None}


# ---------------------------------------------------------------------------
# Physical networks endpoint
# ---------------------------------------------------------------------------

@router.get("/physical-networks")
async def list_physical_networks(
    user=Depends(require_permission("provisioning", "read")),
):
    """List available physical network names from Neutron provider networks."""
    client = get_client()
    client.token = None
    try:
        physnets = client.list_physical_networks()
    except Exception as e:
        raise HTTPException(502, f"Failed to list physical networks: {e}")
    return {"physical_networks": physnets}


# ---------------------------------------------------------------------------
# Roles endpoint
# ---------------------------------------------------------------------------

@router.get("/roles")
async def list_keystone_roles(
    user=Depends(require_permission("provisioning", "read")),
):
    """List available Keystone roles for tenant assignment during provisioning.

    Only returns PF9-compatible roles that are visible in the Platform9
    Private Cloud Director Tenant Assignment dropdown:
      - member  → "Self-service User"
      - admin   → "Administrator"
      - reader  → "Read Only User"
    """
    client = get_client()
    client.token = None
    try:
        roles = client.list_roles()
    except Exception as e:
        raise HTTPException(502, f"Failed to list roles: {e}")

    # Only return roles that PF9 UI recognises for tenant assignment
    PF9_TENANT_ROLES = {"member", "admin", "reader"}
    filtered = []
    for r in roles:
        name = r["name"]
        if name in PF9_TENANT_ROLES:
            filtered.append({
                "id": r["id"],
                "name": name,
                "label": PF9_ROLE_LABELS.get(name, name),
            })
    # Sort: member first, admin second, reader last
    SORT_ORDER = {"member": 0, "admin": 1, "reader": 2}
    filtered.sort(key=lambda r: SORT_ORDER.get(r["name"], 99))
    return {"roles": filtered}


# ---------------------------------------------------------------------------
# Domain Management endpoints
# ---------------------------------------------------------------------------

@router.get("/domains")
async def list_managed_domains(
    user=Depends(require_permission("provisioning", "read")),
):
    """List all Keystone domains with resource counts."""
    client = get_client()
    client.token = None  # force re-auth
    try:
        domains = client.list_domains()
    except Exception as e:
        raise HTTPException(502, f"Failed to list domains from Keystone: {e}")

    result = []
    for d in domains:
        # Skip the system 'Default' domain from management view
        if d.get("name") == "Default":
            continue
        counts = {"projects": 0, "users": 0}
        try:
            counts = client.count_domain_resources(d["id"])
        except Exception:
            pass
        result.append({
            "id": d["id"],
            "name": d.get("name", ""),
            "description": d.get("description", ""),
            "enabled": d.get("enabled", True),
            "projects": counts["projects"],
            "users": counts["users"],
        })

    return {"domains": result}


@router.get("/domains/{domain_id}/resources")
async def get_domain_resources(
    domain_id: str,
    user=Depends(require_permission("provisioning", "read")),
):
    """Get detailed resource listing for a domain — queries OpenStack directly."""
    client = get_client()
    client.token = None
    try:
        domain = client.get_domain(domain_id)
        projects = client.list_projects(domain_id=domain_id)
        users = client.list_users(domain_id=domain_id)
    except Exception as e:
        raise HTTPException(502, f"Failed to query Keystone: {e}")

    project_details = []
    all_servers = []
    all_volumes = []
    all_networks = []
    all_routers = []
    all_floating_ips = []
    all_security_groups = []

    for p in projects:
        pid = p["id"]
        # Query each OpenStack service for project resources
        servers = []
        volumes = []
        networks = []
        routers = []
        fips = []
        sgs = []
        try:
            servers = [s for s in client.list_servers(project_id=pid) if s.get("tenant_id") == pid]
        except Exception:
            pass
        try:
            volumes = [v for v in client.list_volumes(project_id=pid) if v.get("os-vol-tenant-attr:tenant_id") == pid]
        except Exception:
            pass
        try:
            networks = [n for n in client.list_networks(project_id=pid) if n.get("project_id") == pid or n.get("tenant_id") == pid]
        except Exception:
            pass
        try:
            routers = [r for r in client.list_routers(project_id=pid) if r.get("project_id") == pid or r.get("tenant_id") == pid]
        except Exception:
            pass
        try:
            fips = [f for f in client.list_floating_ips(project_id=pid) if f.get("project_id") == pid or f.get("tenant_id") == pid]
        except Exception:
            pass
        try:
            sgs = [sg for sg in client.list_security_groups(project_id=pid) if sg.get("project_id") == pid or sg.get("tenant_id") == pid]
        except Exception:
            pass

        project_details.append({
            "id": pid,
            "name": p.get("name", ""),
            "description": p.get("description", ""),
            "enabled": p.get("enabled", True),
            "vm_count": len(servers),
            "volume_count": len(volumes),
            "network_count": len(networks),
            "router_count": len(routers),
            "floating_ip_count": len(fips),
            "security_group_count": len(sgs),
        })

        for s in servers:
            all_servers.append({
                "id": s["id"],
                "name": s.get("name", ""),
                "status": s.get("status", ""),
                "flavor": s.get("flavor", {}).get("original_name", "") or str(s.get("flavor", {}).get("id", "")),
                "addresses": ", ".join(
                    f"{net}: {', '.join(a.get('addr', '') for a in addrs)}"
                    for net, addrs in (s.get("addresses") or {}).items()
                ),
                "project_id": pid,
                "project_name": p.get("name", ""),
                "created": s.get("created", ""),
            })
        for v in volumes:
            all_volumes.append({
                "id": v["id"],
                "name": v.get("name", "") or v.get("display_name", ""),
                "status": v.get("status", ""),
                "size": v.get("size", 0),
                "volume_type": v.get("volume_type", ""),
                "project_id": pid,
                "project_name": p.get("name", ""),
                "created_at": v.get("created_at", ""),
            })
        for n in networks:
            all_networks.append({
                "id": n["id"],
                "name": n.get("name", ""),
                "status": n.get("status", ""),
                "shared": n.get("shared", False),
                "external": n.get("router:external", False),
                "subnets": n.get("subnets", []),
                "project_id": pid,
                "project_name": p.get("name", ""),
            })
        for r in routers:
            all_routers.append({
                "id": r["id"],
                "name": r.get("name", ""),
                "status": r.get("status", ""),
                "external_gateway": bool(r.get("external_gateway_info")),
                "project_id": pid,
                "project_name": p.get("name", ""),
            })
        for f in fips:
            all_floating_ips.append({
                "id": f["id"],
                "floating_ip_address": f.get("floating_ip_address", ""),
                "fixed_ip_address": f.get("fixed_ip_address", ""),
                "status": f.get("status", ""),
                "port_id": f.get("port_id", ""),
                "project_id": pid,
                "project_name": p.get("name", ""),
            })
        for sg in sgs:
            all_security_groups.append({
                "id": sg["id"],
                "name": sg.get("name", ""),
                "description": sg.get("description", ""),
                "rules_count": len(sg.get("security_group_rules", [])),
                "project_id": pid,
                "project_name": p.get("name", ""),
            })

    has_resources = (
        len(all_servers) > 0 or len(all_volumes) > 0 or
        len(all_networks) > 0 or len(all_routers) > 0
    )

    return {
        "domain": {
            "id": domain["id"],
            "name": domain.get("name", ""),
            "enabled": domain.get("enabled", True),
        },
        "projects": project_details,
        "users": [{"id": u["id"], "name": u.get("name", ""), "email": u.get("email", "")} for u in users],
        "servers": all_servers,
        "volumes": all_volumes,
        "networks": all_networks,
        "routers": all_routers,
        "floating_ips": all_floating_ips,
        "security_groups": all_security_groups,
        "can_delete": len(projects) == 0 and len(users) == 0,
        "summary": {
            "total_projects": len(projects),
            "total_users": len(users),
            "total_vms": len(all_servers),
            "total_volumes": len(all_volumes),
            "total_networks": len(all_networks),
            "total_routers": len(all_routers),
            "total_floating_ips": len(all_floating_ips),
            "total_security_groups": len(all_security_groups),
        },
    }


# ---------------------------------------------------------------------------
# Resource deletion endpoints
# ---------------------------------------------------------------------------

@router.delete("/resources/server/{server_id}")
async def delete_server_resource(
    server_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific server (VM)."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_server(server_id)
        _log_activity(actor=actor, action="delete", resource_type="server",
                       resource_id=server_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Server '{resource_name or server_id}' deleted by {actor}",
                           resource_id=server_id, resource_name=resource_name or server_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Server {server_id} deleted", "resource_type": "server"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="server",
                       resource_id=server_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete server: {e}")


@router.delete("/resources/volume/{volume_id}")
async def delete_volume_resource(
    volume_id: str,
    request: Request,
    force: bool = Query(False),
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific volume."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_volume(volume_id, force=force)
        _log_activity(actor=actor, action="delete", resource_type="volume",
                       resource_id=volume_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success", details={"force": force})
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Volume '{resource_name or volume_id}' deleted by {actor}",
                           resource_id=volume_id, resource_name=resource_name or volume_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Volume {volume_id} deleted", "resource_type": "volume"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="volume",
                       resource_id=volume_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete volume: {e}")


@router.delete("/resources/network/{network_id}")
async def delete_network_resource(
    network_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific network."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_network(network_id)
        _log_activity(actor=actor, action="delete", resource_type="network",
                       resource_id=network_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Network '{resource_name or network_id}' deleted by {actor}",
                           resource_id=network_id, resource_name=resource_name or network_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Network {network_id} deleted", "resource_type": "network"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="network",
                       resource_id=network_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete network: {e}")


@router.delete("/resources/router/{router_id}")
async def delete_router_resource(
    router_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific router."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_router(router_id)
        _log_activity(actor=actor, action="delete", resource_type="router",
                       resource_id=router_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Router '{resource_name or router_id}' deleted by {actor}",
                           resource_id=router_id, resource_name=resource_name or router_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Router {router_id} deleted", "resource_type": "router"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="router",
                       resource_id=router_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete router: {e}")


@router.delete("/resources/floating-ip/{floatingip_id}")
async def delete_floating_ip_resource(
    floatingip_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific floating IP."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_floating_ip(floatingip_id)
        _log_activity(actor=actor, action="delete", resource_type="floating_ip",
                       resource_id=floatingip_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Floating IP '{resource_name or floatingip_id}' deleted by {actor}",
                           resource_id=floatingip_id, resource_name=resource_name or floatingip_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Floating IP {floatingip_id} deleted", "resource_type": "floating_ip"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="floating_ip",
                       resource_id=floatingip_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete floating IP: {e}")


@router.delete("/resources/security-group/{sg_id}")
async def delete_security_group_resource(
    sg_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific security group."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_security_group(sg_id)
        _log_activity(actor=actor, action="delete", resource_type="security_group",
                       resource_id=sg_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Security group '{resource_name or sg_id}' deleted by {actor}",
                           resource_id=sg_id, resource_name=resource_name or sg_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Security group {sg_id} deleted", "resource_type": "security_group"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="security_group",
                       resource_id=sg_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete security group: {e}")


@router.delete("/resources/user/{user_id}")
async def delete_user_resource(
    user_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific Keystone user."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_user(user_id)
        _log_activity(actor=actor, action="delete", resource_type="user",
                       resource_id=user_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"User '{resource_name or user_id}' deleted by {actor}",
                           resource_id=user_id, resource_name=resource_name or user_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"User {user_id} deleted", "resource_type": "user"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="user",
                       resource_id=user_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete user: {e}")


@router.delete("/resources/project/{project_id}")
async def delete_project_resource(
    project_id: str,
    request: Request,
    resource_name: Optional[str] = Query(None),
    domain_name: Optional[str] = Query(None),
    project_name: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "resource_delete")),
):
    """Delete a specific Keystone project."""
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None
    try:
        client.delete_project(project_id)
        _log_activity(actor=actor, action="delete", resource_type="project",
                       resource_id=project_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="success")
        _fire_notification(event_type="resource_deleted", severity="warning",
                           summary=f"Project '{resource_name or project_id}' deleted by {actor}",
                           resource_id=project_id, resource_name=resource_name or project_id,
                           domain_name=domain_name or "", project_name=project_name or "", actor=actor)
        return {"message": f"Project {project_id} deleted", "resource_type": "project"}
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="project",
                       resource_id=project_id, resource_name=resource_name,
                       domain_name=domain_name, ip_address=client_ip, result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to delete project: {e}")


@router.put("/domains/{domain_id}/toggle")
async def toggle_domain(
    domain_id: str,
    request: Request,
    user=Depends(require_permission("provisioning", "tenant_disable")),
):
    """Enable or disable a domain. Requires 'tenant_disable' permission."""
    body = await request.json()
    enabled = body.get("enabled", True)
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)

    client = get_client()
    client.token = None
    try:
        domain = client.update_domain(domain_id, enabled=enabled)
    except Exception as e:
        action = "enable" if enabled else "disable"
        _log_activity(actor=actor, action=action, resource_type="domain",
                       resource_id=domain_id, ip_address=client_ip,
                       result="failure", error_message=str(e))
        raise HTTPException(502, f"Failed to update domain: {e}")

    action = "enable" if enabled else "disable"
    domain_name = domain.get("name", domain_id)
    _log_activity(actor=actor, action=action, resource_type="domain",
                   resource_id=domain_id, resource_name=domain_name,
                   ip_address=client_ip, result="success")
    _fire_notification(
        event_type="domain_toggled", severity="warning",
        summary=f"Domain '{domain_name}' {'enabled' if enabled else 'disabled'} by {actor}",
        resource_id=domain_id, resource_name=domain_name,
    )

    return {
        "id": domain["id"],
        "name": domain.get("name", ""),
        "enabled": domain.get("enabled"),
        "message": f"Domain {'enabled' if enabled else 'disabled'} successfully",
    }


@router.delete("/domains/{domain_id}")
async def delete_domain(
    domain_id: str,
    request: Request,
    force: bool = Query(False),
    user=Depends(require_permission("provisioning", "tenant_delete")),
):
    """
    Delete a domain. Requires 'tenant_delete' permission.
    By default, refuses if any projects or users exist.
    With force=true, will attempt to delete all child resources first.
    """
    actor = _get_actor(user)
    client_ip = _get_client_ip(request)
    client = get_client()
    client.token = None

    try:
        domain = client.get_domain(domain_id)
    except Exception as e:
        raise HTTPException(404, f"Domain not found: {e}")

    domain_name = domain.get("name", domain_id)
    projects = client.list_projects(domain_id=domain_id)
    users = client.list_users(domain_id=domain_id)

    if (projects or users) and not force:
        return {
            "error": "Domain is not empty",
            "projects": len(projects),
            "users": len(users),
            "message": "Delete all projects and users first, or use force=true",
        }

    errors = []
    if force:
        # Delete users first
        for u in users:
            try:
                client.delete_user(u["id"])
            except Exception as e:
                errors.append(f"Failed to delete user {u.get('name', u['id'])}: {e}")

        # Delete projects
        for p in projects:
            try:
                client.delete_project(p["id"])
            except Exception as e:
                errors.append(f"Failed to delete project {p.get('name', p['id'])}: {e}")

    # Disable domain first (Keystone requires this)
    try:
        client.update_domain(domain_id, enabled=False)
    except Exception as e:
        errors.append(f"Failed to disable domain: {e}")

    # Delete domain
    try:
        client.delete_domain(domain_id)
    except Exception as e:
        _log_activity(actor=actor, action="delete", resource_type="domain",
                       resource_id=domain_id, resource_name=domain_name,
                       ip_address=client_ip, result="failure", error_message=str(e),
                       details={"force": force})
        raise HTTPException(502, f"Failed to delete domain: {e}")

    _log_activity(actor=actor, action="delete", resource_type="domain",
                   resource_id=domain_id, resource_name=domain_name,
                   ip_address=client_ip, result="success",
                   details={"force": force, "child_errors": errors})
    _fire_notification(
        event_type="domain_deleted", severity="critical",
        summary=f"Domain '{domain_name}' deleted by {actor}" + (" (force)" if force else ""),
        resource_id=domain_id, resource_name=domain_name,
    )

    return {
        "message": f"Domain '{domain_name}' deleted successfully",
        "warnings": errors if errors else None,
    }


# ---------------------------------------------------------------------------
# Activity Log endpoint
# ---------------------------------------------------------------------------

@router.get("/activity-log")
async def get_activity_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    user=Depends(require_permission("provisioning", "read")),
):
    """Get paginated, filterable activity log."""
    from db_pool import get_connection
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            where_clauses = []
            params: list = []
            if action:
                where_clauses.append("action = %s")
                params.append(action)
            if resource_type:
                where_clauses.append("resource_type = %s")
                params.append(resource_type)
            if actor:
                where_clauses.append("actor ILIKE %s")
                params.append(f"%{actor}%")
            if result:
                where_clauses.append("result = %s")
                params.append(result)

            where = ""
            if where_clauses:
                where = "WHERE " + " AND ".join(where_clauses)

            # Count
            cur.execute(f"SELECT COUNT(*) FROM activity_log {where}", params)
            total = cur.fetchone()["count"]

            # Fetch rows
            params.extend([limit, offset])
            cur.execute(f"""
                SELECT id, timestamp, actor, action, resource_type, resource_id,
                       resource_name, domain_id, domain_name, details,
                       ip_address, result, error_message
                FROM activity_log
                {where}
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s
            """, params)
            rows = cur.fetchall()

    return {"logs": rows, "total": total, "limit": limit, "offset": offset}
