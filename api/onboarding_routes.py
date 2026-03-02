# ---------------------------------------------------------------------------
# Bulk Customer Onboarding API — /api/onboarding
# Version: v1.38.0
# ---------------------------------------------------------------------------
"""
Workflow:
  UPLOAD → VALIDATING → VALIDATED | INVALID
  → PENDING_APPROVAL → APPROVED | REJECTED
  → DRY_RUN_PENDING → DRY_RUN_PASSED | DRY_RUN_FAILED
  → EXECUTING → COMPLETE | PARTIALLY_FAILED

Execution is hard-locked until both:
  - approval_status == 'approved'
  - status == 'dry_run_passed'
"""

from __future__ import annotations

import io
import ipaddress
import logging
import os
import re
import secrets
import string
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2.extras
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import get_current_user, require_permission
from db_pool import get_connection

logger = logging.getLogger("onboarding")

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_temp_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in pw)
            and any(c.islower() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in "!@#$%^&*" for c in pw)
        ):
            return pw


def _fire(event: str, title: str, message: str, severity: str = "info") -> None:
    try:
        from notification_routes import _fire_notification  # type: ignore
        _fire_notification(event, title, message, severity)
    except Exception as exc:
        logger.warning("Could not fire notification %s: %s", event, exc)


def _ensure_tables() -> None:
    _MIGRATION_SQL = """
    CREATE TABLE IF NOT EXISTS onboarding_batches (
        id                  SERIAL PRIMARY KEY,
        batch_id            UUID NOT NULL DEFAULT gen_random_uuid(),
        batch_name          TEXT NOT NULL,
        uploaded_by         TEXT NOT NULL,
        status              TEXT NOT NULL DEFAULT 'validating',
        validation_errors   JSONB DEFAULT '[]'::jsonb,
        dry_run_result      JSONB,
        approval_status     TEXT DEFAULT 'not_submitted',
        approved_by         TEXT,
        approved_at         TIMESTAMPTZ,
        rejection_comment   TEXT,
        execution_result    JSONB,
        total_customers     INT DEFAULT 0,
        total_projects      INT DEFAULT 0,
        total_networks      INT DEFAULT 0,
        total_users         INT DEFAULT 0,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_onboarding_batches_batch_id
        ON onboarding_batches (batch_id);
    CREATE TABLE IF NOT EXISTS onboarding_customers (
        id              SERIAL PRIMARY KEY,
        batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
        domain_name     TEXT NOT NULL,
        display_name    TEXT,
        description     TEXT,
        contact_email   TEXT,
        department_tag  TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        error_msg       TEXT,
        pcd_domain_id   TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_onboarding_customers_batch
        ON onboarding_customers (batch_id);
    CREATE TABLE IF NOT EXISTS onboarding_projects (
        id              SERIAL PRIMARY KEY,
        batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
        customer_id     INT REFERENCES onboarding_customers(id) ON DELETE CASCADE,
        domain_name     TEXT NOT NULL,
        project_name    TEXT NOT NULL,
        description     TEXT,
        quota_vcpu      INT DEFAULT 20,
        quota_ram_mb    INT DEFAULT 51200,
        quota_disk_gb   INT DEFAULT 1000,
        status          TEXT NOT NULL DEFAULT 'pending',
        error_msg       TEXT,
        pcd_project_id  TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_onboarding_projects_batch
        ON onboarding_projects (batch_id);
    CREATE TABLE IF NOT EXISTS onboarding_networks (
        id              SERIAL PRIMARY KEY,
        batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
        project_id      INT REFERENCES onboarding_projects(id) ON DELETE CASCADE,
        domain_name     TEXT NOT NULL,
        project_name    TEXT NOT NULL,
        network_name    TEXT NOT NULL,
        cidr            TEXT NOT NULL,
        gateway         TEXT,
        dns1            TEXT DEFAULT '8.8.8.8',
        vlan_id         INT,
        dhcp_enabled    BOOLEAN DEFAULT TRUE,
        status          TEXT NOT NULL DEFAULT 'pending',
        error_msg       TEXT,
        pcd_network_id  TEXT,
        pcd_subnet_id   TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_onboarding_networks_batch
        ON onboarding_networks (batch_id);
    CREATE TABLE IF NOT EXISTS onboarding_users (
        id                  SERIAL PRIMARY KEY,
        batch_id            UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
        project_id          INT REFERENCES onboarding_projects(id) ON DELETE CASCADE,
        domain_name         TEXT NOT NULL,
        project_name        TEXT NOT NULL,
        username            TEXT NOT NULL,
        email               TEXT,
        role                TEXT NOT NULL DEFAULT 'member',
        send_welcome_email  BOOLEAN DEFAULT TRUE,
        status              TEXT NOT NULL DEFAULT 'pending',
        error_msg           TEXT,
        pcd_user_id         TEXT,
        temp_password       TEXT,
        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_onboarding_users_batch
        ON onboarding_users (batch_id);
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT EXISTS (SELECT FROM information_schema.tables "
                    "WHERE table_name = 'onboarding_batches')"
                )
                if not cur.fetchone()[0]:
                    logger.info("Running onboarding DB migration …")
                    cur.execute(_MIGRATION_SQL)
    except Exception as exc:
        logger.warning("Could not ensure onboarding tables: %s", exc)


_ensure_tables()

# ---------------------------------------------------------------------------
# Excel template generation
# ---------------------------------------------------------------------------

def _build_template_bytes() -> bytes:
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")

    wb = openpyxl.Workbook()

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="2F5496")

    def add_sheet(name: str, headers: List[str], sample_rows: List[List]) -> None:
        if name == wb.active.title:
            ws = wb.active
            ws.title = name
        else:
            ws = wb.create_sheet(name)
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
            ws.column_dimensions[get_column_letter(col_idx)].width = max(len(h) + 4, 18)
        for row_idx, row_data in enumerate(sample_rows, 2):
            for col_idx, val in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col_idx, value=val)

    add_sheet(
        "customers",
        ["domain_name", "display_name", "description", "contact_email", "department_tag"],
        [["acme-corp", "ACME Corporation", "Primary tenant", "ops@acme.com", "Engineering"]],
    )
    add_sheet(
        "projects",
        ["domain_name", "project_name", "description", "quota_vcpu", "quota_ram_gb", "quota_disk_gb"],
        [["acme-corp", "acme-prod", "Production workloads", 40, 100, 2000],
         ["acme-corp", "acme-dev",  "Development workloads", 20, 50, 500]],
    )
    add_sheet(
        "networks",
        ["domain_name", "project_name", "network_name", "cidr", "gateway", "dns1", "vlan_id", "dhcp_enabled"],
        [["acme-corp", "acme-prod", "prod-net", "10.10.10.0/24", "10.10.10.1", "8.8.8.8", "", "true"],
         ["acme-corp", "acme-dev",  "dev-net",  "10.10.20.0/24", "", "", "", "true"]],
    )
    add_sheet(
        "users",
        ["domain_name", "project_name", "username", "email", "role", "send_welcome_email"],
        [["acme-corp", "acme-prod", "alice", "alice@acme.com", "admin", "true"],
         ["acme-corp", "acme-dev",  "bob",   "bob@acme.com",   "member", "true"]],
    )

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Excel parsing + validation
# ---------------------------------------------------------------------------

VALID_ROLES = {"member", "admin", "reader", "_member_"}
CIDR_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _str(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _bool_val(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return _str(val).lower() not in ("false", "0", "no", "")


def _int_val(val: Any, default: int) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _parse_excel(raw: bytes) -> Dict[str, Any]:
    """Parse uploaded Excel bytes; return {customers, projects, networks, users, errors}."""
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")

    errors: List[Dict] = []
    customers: List[Dict] = []
    projects: List[Dict] = []
    networks: List[Dict] = []
    users: List[Dict] = []

    try:
        wb = openpyxl.load_workbook(filename=io.BytesIO(raw), data_only=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot parse Excel file: {exc}")

    required_sheets = {"customers", "projects", "networks", "users"}
    missing = required_sheets - set(wb.sheetnames)
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing sheets: {', '.join(sorted(missing))}")

    def rows_as_dicts(sheet_name: str) -> List[Dict]:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [_str(h).lower().replace(" ", "_") for h in rows[0]]
        result = []
        for row in rows[1:]:
            if all(v is None or _str(v) == "" for v in row):
                continue
            result.append(dict(zip(headers, row)))
        return result

    # ── customers ──
    known_domains: set = set()
    for i, row in enumerate(rows_as_dicts("customers"), 2):
        dn = _str(row.get("domain_name", ""))
        if not dn:
            errors.append({"sheet": "customers", "row": i, "field": "domain_name", "message": "Required"})
            continue
        if dn in known_domains:
            errors.append({"sheet": "customers", "row": i, "field": "domain_name", "message": f"Duplicate domain_name '{dn}'"})
            continue
        known_domains.add(dn)
        email = _str(row.get("contact_email", ""))
        if email and not EMAIL_RE.match(email):
            errors.append({"sheet": "customers", "row": i, "field": "contact_email", "message": f"Invalid email '{email}'"})
        customers.append({
            "domain_name": dn,
            "display_name": _str(row.get("display_name", "")),
            "description": _str(row.get("description", "")),
            "contact_email": email,
            "department_tag": _str(row.get("department_tag", "")),
        })

    # ── projects ──
    known_projects: set = set()  # (domain_name, project_name)
    for i, row in enumerate(rows_as_dicts("projects"), 2):
        dn = _str(row.get("domain_name", ""))
        pn = _str(row.get("project_name", ""))
        if not dn:
            errors.append({"sheet": "projects", "row": i, "field": "domain_name", "message": "Required"})
            continue
        if not pn:
            errors.append({"sheet": "projects", "row": i, "field": "project_name", "message": "Required"})
            continue
        if dn not in known_domains:
            errors.append({"sheet": "projects", "row": i, "field": "domain_name",
                           "message": f"domain_name '{dn}' not found in customers sheet"})
        key = (dn, pn)
        if key in known_projects:
            errors.append({"sheet": "projects", "row": i, "field": "project_name",
                           "message": f"Duplicate project '{pn}' in domain '{dn}'"})
            continue
        known_projects.add(key)
        projects.append({
            "domain_name": dn,
            "project_name": pn,
            "description": _str(row.get("description", "")),
            "quota_vcpu": _int_val(row.get("quota_vcpu"), 20),
            "quota_ram_mb": _int_val(row.get("quota_ram_gb"), 50) * 1024,
            "quota_disk_gb": _int_val(row.get("quota_disk_gb"), 1000),
        })

    # ── networks ──
    for i, row in enumerate(rows_as_dicts("networks"), 2):
        dn = _str(row.get("domain_name", ""))
        pn = _str(row.get("project_name", ""))
        nn = _str(row.get("network_name", ""))
        cidr = _str(row.get("cidr", ""))
        if not dn:
            errors.append({"sheet": "networks", "row": i, "field": "domain_name", "message": "Required"}); continue
        if not pn:
            errors.append({"sheet": "networks", "row": i, "field": "project_name", "message": "Required"}); continue
        if not nn:
            errors.append({"sheet": "networks", "row": i, "field": "network_name", "message": "Required"}); continue
        if not cidr:
            errors.append({"sheet": "networks", "row": i, "field": "cidr", "message": "Required"}); continue
        if not CIDR_RE.match(cidr):
            errors.append({"sheet": "networks", "row": i, "field": "cidr", "message": f"Invalid CIDR '{cidr}'"}); continue
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            errors.append({"sheet": "networks", "row": i, "field": "cidr", "message": f"Invalid network address '{cidr}'"}); continue
        if (dn, pn) not in known_projects and dn in known_domains:
            errors.append({"sheet": "networks", "row": i, "field": "project_name",
                           "message": f"Project '{pn}' in domain '{dn}' not found in projects sheet"})
        networks.append({
            "domain_name": dn,
            "project_name": pn,
            "network_name": nn,
            "cidr": cidr,
            "gateway": _str(row.get("gateway", "")),
            "dns1": _str(row.get("dns1", "")) or "8.8.8.8",
            "vlan_id": _int_val(row.get("vlan_id"), 0) or None,
            "dhcp_enabled": _bool_val(row.get("dhcp_enabled", True)),
        })

    # ── users ──
    for i, row in enumerate(rows_as_dicts("users"), 2):
        dn = _str(row.get("domain_name", ""))
        pn = _str(row.get("project_name", ""))
        un = _str(row.get("username", ""))
        role = _str(row.get("role", "member")).lower()
        if not dn:
            errors.append({"sheet": "users", "row": i, "field": "domain_name", "message": "Required"}); continue
        if not pn:
            errors.append({"sheet": "users", "row": i, "field": "project_name", "message": "Required"}); continue
        if not un:
            errors.append({"sheet": "users", "row": i, "field": "username", "message": "Required"}); continue
        if role not in VALID_ROLES:
            errors.append({"sheet": "users", "row": i, "field": "role",
                           "message": f"Role '{role}' not valid; use member/admin/reader"})
        email = _str(row.get("email", ""))
        if email and not EMAIL_RE.match(email):
            errors.append({"sheet": "users", "row": i, "field": "email", "message": f"Invalid email '{email}'"})
        users.append({
            "domain_name": dn,
            "project_name": pn,
            "username": un,
            "email": email,
            "role": role,
            "send_welcome_email": _bool_val(row.get("send_welcome_email", True)),
        })

    return {
        "customers": customers,
        "projects": projects,
        "networks": networks,
        "users": users,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_batch(cur, batch_id: str) -> Dict:
    cur.execute(
        "SELECT * FROM onboarding_batches WHERE batch_id = %s",
        (batch_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found")
    return dict(row)


def _batch_items(cur, batch_id: str) -> Dict:
    cur.execute("SELECT * FROM onboarding_customers WHERE batch_id = %s ORDER BY id", (batch_id,))
    customers = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM onboarding_projects  WHERE batch_id = %s ORDER BY id", (batch_id,))
    projects = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM onboarding_networks  WHERE batch_id = %s ORDER BY id", (batch_id,))
    networks = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM onboarding_users     WHERE batch_id = %s ORDER BY id", (batch_id,))
    users = [dict(r) for r in cur.fetchall()]
    return {"customers": customers, "projects": projects, "networks": networks, "users": users}


# ---------------------------------------------------------------------------
# GET /template
# ---------------------------------------------------------------------------

@router.get("/template")
def download_template(current_user: dict = Depends(get_current_user)):
    """Download the blank Excel onboarding template."""
    data = _build_template_bytes()
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="onboarding_template.xlsx"'},
    )


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------

@router.post("/upload", status_code=201)
def upload_batch(
    file: UploadFile = File(...),
    batch_name: str = "",
    current_user: dict = Depends(require_permission("onboarding", "create")),
):
    """Parse and validate uploaded Excel; create a new batch record."""
    raw = file.file.read()
    parsed = _parse_excel(raw)

    errors = parsed["errors"]
    status = "invalid" if errors else "validated"
    bn = batch_name or (file.filename or "batch").rsplit(".", 1)[0]
    actor = current_user.get("username", "unknown")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO onboarding_batches
                    (batch_name, uploaded_by, status, validation_errors,
                     total_customers, total_projects, total_networks, total_users)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    bn, actor, status,
                    psycopg2.extras.Json(errors),
                    len(parsed["customers"]),
                    len(parsed["projects"]),
                    len(parsed["networks"]),
                    len(parsed["users"]),
                ),
            )
            batch = dict(cur.fetchone())
            batch_id = batch["batch_id"]

            # Insert customers
            for c in parsed["customers"]:
                cur.execute(
                    """
                    INSERT INTO onboarding_customers
                        (batch_id, domain_name, display_name, description, contact_email, department_tag)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (batch_id, c["domain_name"], c["display_name"], c["description"],
                     c["contact_email"], c["department_tag"]),
                )

            # Insert projects
            for p in parsed["projects"]:
                cur.execute(
                    """
                    INSERT INTO onboarding_projects
                        (batch_id, domain_name, project_name, description,
                         quota_vcpu, quota_ram_mb, quota_disk_gb)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (batch_id, p["domain_name"], p["project_name"], p["description"],
                     p["quota_vcpu"], p["quota_ram_mb"], p["quota_disk_gb"]),
                )

            # Insert networks
            for n in parsed["networks"]:
                cur.execute(
                    """
                    INSERT INTO onboarding_networks
                        (batch_id, domain_name, project_name, network_name, cidr,
                         gateway, dns1, vlan_id, dhcp_enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (batch_id, n["domain_name"], n["project_name"], n["network_name"],
                     n["cidr"], n["gateway"] or None, n["dns1"], n["vlan_id"], n["dhcp_enabled"]),
                )

            # Insert users
            for u in parsed["users"]:
                cur.execute(
                    """
                    INSERT INTO onboarding_users
                        (batch_id, domain_name, project_name, username, email, role, send_welcome_email)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (batch_id, u["domain_name"], u["project_name"], u["username"],
                     u["email"] or None, u["role"], u["send_welcome_email"]),
                )

    logger.info("Onboarding batch %s created by %s — status=%s", batch_id, actor, status)
    return {
        "batch_id": str(batch_id),
        "batch_name": bn,
        "status": status,
        "total_customers": batch["total_customers"],
        "total_projects": batch["total_projects"],
        "total_networks": batch["total_networks"],
        "total_users": batch["total_users"],
        "validation_errors": errors,
    }


# ---------------------------------------------------------------------------
# GET /batches
# ---------------------------------------------------------------------------

@router.get("/batches")
def list_batches(current_user: dict = Depends(require_permission("onboarding", "read"))):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM onboarding_batches ORDER BY created_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# GET /batches/{batch_id}
# ---------------------------------------------------------------------------

@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, current_user: dict = Depends(require_permission("onboarding", "read"))):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            batch = _get_batch(cur, batch_id)
            items = _batch_items(cur, batch_id)
    return {**batch, **items}


# ---------------------------------------------------------------------------
# POST /batches/{batch_id}/dry-run
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/dry-run")
def run_dry_run(batch_id: str, current_user: dict = Depends(require_permission("onboarding", "create"))):
    """
    Connect to PCD and check which resources already exist.
    Sets batch status to dry_run_passed / dry_run_failed.
    Execution is hard-locked until dry_run_passed.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            batch = _get_batch(cur, batch_id)
            if batch["status"] not in ("validated", "dry_run_failed", "dry_run_passed"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot dry-run a batch with status '{batch['status']}'. "
                           "Batch must be validated first.",
                )
            items = _batch_items(cur, batch_id)

    # Update status to dry_run_pending
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE onboarding_batches SET status = 'dry_run_pending' WHERE batch_id = %s",
                (batch_id,),
            )

    try:
        from pf9_control import get_client  # type: ignore
        client = get_client()
        client.authenticate()

        existing_domains = {d["name"]: d for d in (client.list_domains() or [])}
        existing_projects_by_domain: Dict[str, Dict[str, Any]] = {}
        existing_networks_by_project: Dict[str, List[str]] = {}

        # Prefetch projects for existing domains
        for cust in items["customers"]:
            dn = cust["domain_name"]
            if dn in existing_domains:
                dom_id = existing_domains[dn]["id"]
                projs = client.list_projects(domain_id=dom_id) or []
                existing_projects_by_domain[dn] = {p["name"]: p for p in projs}

        dry_items: List[Dict] = []
        conflicts: List[Dict] = []

        # Check customers
        for cust in items["customers"]:
            dn = cust["domain_name"]
            if dn in existing_domains:
                dry_items.append({"resource_type": "domain", "name": dn,
                                   "action": "skip", "reason": "Domain already exists"})
                conflicts.append({"resource_type": "domain", "name": dn,
                                   "reason": "Domain already exists — rename or remove from batch"})
            else:
                dry_items.append({"resource_type": "domain", "name": dn, "action": "create", "reason": ""})

        # Check projects
        for proj in items["projects"]:
            dn = proj["domain_name"]
            pn = proj["project_name"]
            dom_projs = existing_projects_by_domain.get(dn, {})
            if pn in dom_projs:
                dry_items.append({"resource_type": "project", "name": f"{dn}/{pn}",
                                   "action": "skip", "reason": "Project already exists"})
                conflicts.append({"resource_type": "project", "name": f"{dn}/{pn}",
                                   "reason": "Project already exists in PCD"})
            else:
                dry_items.append({"resource_type": "project", "name": f"{dn}/{pn}",
                                   "action": "create", "reason": ""})

        # Check networks (lightweight — just flag if project already has a network with the same name)
        try:
            all_nets = client.list_networks() or []
            net_names_all = {n.get("name", "") for n in all_nets}
        except Exception:
            net_names_all = set()

        for net in items["networks"]:
            nn = net["network_name"]
            key = f"{net['domain_name']}/{net['project_name']}/{nn}"
            if nn in net_names_all:
                dry_items.append({"resource_type": "network", "name": key,
                                   "action": "skip", "reason": "Network name already exists in PCD"})
                conflicts.append({"resource_type": "network", "name": key,
                                   "reason": "Network already exists — rename or remove from batch"})
            else:
                dry_items.append({"resource_type": "network", "name": key, "action": "create", "reason": ""})

        # Users — just log planned creation (no global user list query)
        for user in items["users"]:
            key = f"{user['domain_name']}/{user['username']}"
            dry_items.append({"resource_type": "user", "name": key, "action": "create", "reason": ""})

    except HTTPException:
        raise
    except Exception as exc:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboarding_batches SET status = 'dry_run_failed', "
                    "dry_run_result = %s::jsonb WHERE batch_id = %s",
                    (psycopg2.extras.Json({"error": str(exc), "items": []}), batch_id),
                )
        raise HTTPException(status_code=502, detail=f"PCD connection failed: {exc}")

    # Determine pass/fail
    has_conflicts = len(conflicts) > 0
    new_status = "dry_run_failed" if has_conflicts else "dry_run_passed"

    summary = {
        "total_would_create": sum(1 for d in dry_items if d["action"] == "create"),
        "total_would_skip": sum(1 for d in dry_items if d["action"] == "skip"),
        "conflicts": conflicts,
    }
    result = {"summary": summary, "items": dry_items}

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE onboarding_batches SET status = %s, dry_run_result = %s::jsonb WHERE batch_id = %s",
                (new_status, psycopg2.extras.Json(result), batch_id),
            )

    logger.info("Dry-run for batch %s: status=%s conflicts=%d", batch_id, new_status, len(conflicts))
    return {"status": new_status, **result}


# ---------------------------------------------------------------------------
# POST /batches/{batch_id}/submit  (submit for approval)
# ---------------------------------------------------------------------------

@router.post("/batches/{batch_id}/submit")
def submit_for_approval(batch_id: str, current_user: dict = Depends(require_permission("onboarding", "create"))):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            batch = _get_batch(cur, batch_id)
            if batch["status"] not in ("validated", "dry_run_passed", "dry_run_failed"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot submit a batch with status '{batch['status']}'",
                )
            cur.execute(
                "UPDATE onboarding_batches SET approval_status = 'pending_approval' WHERE batch_id = %s",
                (batch_id,),
            )

    actor = current_user.get("username", "unknown")
    _fire(
        "onboarding_submitted",
        "Onboarding Batch Submitted",
        f"Batch '{batch['batch_name']}' submitted for approval by {actor}.",
        "info",
    )
    return {"status": "pending_approval", "batch_id": batch_id}


# ---------------------------------------------------------------------------
# POST /batches/{batch_id}/decision  (approve or reject)
# ---------------------------------------------------------------------------

class DecisionPayload(BaseModel):
    decision: str  # "approve" | "reject"
    comment: Optional[str] = None


@router.post("/batches/{batch_id}/decision")
def batch_decision(
    batch_id: str,
    payload: DecisionPayload,
    current_user: dict = Depends(require_permission("onboarding", "approve")),
):
    if payload.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'reject'")

    actor = current_user.get("username", "unknown")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            batch = _get_batch(cur, batch_id)
            if batch["approval_status"] != "pending_approval":
                raise HTTPException(
                    status_code=400,
                    detail=f"Batch approval_status is '{batch['approval_status']}', not pending_approval",
                )
            new_approval = "approved" if payload.decision == "approve" else "rejected"
            cur.execute(
                """
                UPDATE onboarding_batches
                   SET approval_status = %s,
                       approved_by = %s,
                       approved_at = NOW(),
                       rejection_comment = %s
                 WHERE batch_id = %s
                """,
                (new_approval, actor, payload.comment, batch_id),
            )

    event = "onboarding_approved" if new_approval == "approved" else "onboarding_rejected"
    title = f"Onboarding Batch {'Approved' if new_approval == 'approved' else 'Rejected'}"
    msg = f"Batch '{batch['batch_name']}' was {new_approval} by {actor}."
    if payload.comment:
        msg += f" Comment: {payload.comment}"
    _fire(event, title, msg, "info" if new_approval == "approved" else "warning")

    return {"approval_status": new_approval, "batch_id": batch_id}


# ---------------------------------------------------------------------------
# POST /batches/{batch_id}/execute
# ---------------------------------------------------------------------------

def _execute_batch_sync(batch_id: str, actor: str) -> None:
    """Run in a background thread — creates all PCD resources."""
    logger.info("Starting execution of batch %s by %s", batch_id, actor)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM onboarding_batches WHERE batch_id = %s", (batch_id,))
            batch = dict(cur.fetchone())
            items = _batch_items(cur, batch_id)

    try:
        from pf9_control import get_client  # type: ignore
        client = get_client()
        client.authenticate()

        existing_domains = {d["name"]: d for d in (client.list_domains() or [])}
        # domain_id lookup cache
        domain_id_map: Dict[str, str] = {dn: d["id"] for dn, d in existing_domains.items()}
        project_id_map: Dict[tuple, str] = {}  # (domain_name, project_name) → project_id

        # ── Create domains ──────────────────────────────────────────────────
        for cust in items["customers"]:
            dn = cust["domain_name"]
            if dn in existing_domains:
                logger.warning("Domain '%s' already exists — skipping", dn)
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_customers SET status = 'skipped', error_msg = %s, "
                            "pcd_domain_id = %s WHERE batch_id = %s AND domain_name = %s",
                            ("Domain already exists", existing_domains[dn]["id"], batch_id, dn),
                        )
                domain_id_map[dn] = existing_domains[dn]["id"]
                continue
            try:
                desc = cust.get("description") or ""
                result_d = client.create_domain(
                    dn,
                    description=desc,
                )
                dom_id = result_d.get("id") or result_d.get("domain", {}).get("id", "")
                domain_id_map[dn] = dom_id
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_customers SET status = 'created', pcd_domain_id = %s "
                            "WHERE batch_id = %s AND domain_name = %s",
                            (dom_id, batch_id, dn),
                        )
                logger.info("Created domain '%s' id=%s", dn, dom_id)
            except Exception as exc:
                logger.error("Failed to create domain '%s': %s", dn, exc)
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_customers SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s",
                            (str(exc), batch_id, dn),
                        )

        # ── Create projects ─────────────────────────────────────────────────
        for proj in items["projects"]:
            dn = proj["domain_name"]
            pn = proj["project_name"]
            dom_id = domain_id_map.get(dn)
            if not dom_id:
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_projects SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s",
                            (f"Parent domain '{dn}' not created", batch_id, dn, pn),
                        )
                continue
            try:
                result_p = client.create_project(
                    pn,
                    domain_id=dom_id,
                    description=proj.get("description") or "",
                )
                proj_id = result_p.get("id") or result_p.get("project", {}).get("id", "")
                project_id_map[(dn, pn)] = proj_id
                # Set compute quotas
                try:
                    client.update_compute_quotas(proj_id, {
                        "cores": proj["quota_vcpu"],
                        "ram": proj["quota_ram_mb"],
                        "gigabytes": proj["quota_disk_gb"],
                    })
                except Exception as qe:
                    logger.warning("Could not set quotas for project '%s': %s", pn, qe)
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_projects SET status = 'created', pcd_project_id = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s",
                            (proj_id, batch_id, dn, pn),
                        )
                logger.info("Created project '%s/%s' id=%s", dn, pn, proj_id)
            except Exception as exc:
                logger.error("Failed to create project '%s/%s': %s", dn, pn, exc)
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_projects SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s",
                            (str(exc), batch_id, dn, pn),
                        )

        # ── Create networks + subnets ────────────────────────────────────────
        for net in items["networks"]:
            dn = net["domain_name"]
            pn = net["project_name"]
            nn = net["network_name"]
            proj_id = project_id_map.get((dn, pn))
            if not proj_id:
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_networks SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s AND network_name = %s",
                            (f"Parent project '{dn}/{pn}' not created", batch_id, dn, pn, nn),
                        )
                continue
            try:
                kwargs_net: Dict = {"name": nn, "project_id": proj_id}
                if net.get("vlan_id"):
                    kwargs_net["provider_segmentation_id"] = net["vlan_id"]
                    kwargs_net["provider_network_type"] = "vlan"
                result_n = client.create_network(**kwargs_net)
                net_id = result_n.get("id") or result_n.get("network", {}).get("id", "")

                # Build subnet kwargs
                cidr = net["cidr"]
                net_obj = ipaddress.ip_network(cidr, strict=False)
                gateway = net.get("gateway") or str(net_obj.network_address + 1)
                first_host = str(net_obj.network_address + 2)
                last_host = str(net_obj.broadcast_address - 1)

                subnet_kwargs: Dict = {
                    "network_id": net_id,
                    "cidr": cidr,
                    "name": f"{nn}-subnet",
                    "gateway_ip": gateway,
                    "dns_nameservers": [net.get("dns1") or "8.8.8.8"],
                    "enable_dhcp": net.get("dhcp_enabled", True),
                    "allocation_pools": [{"start": first_host, "end": last_host}],
                }
                result_sn = client.create_subnet(**subnet_kwargs)
                subnet_id = result_sn.get("id") or result_sn.get("subnet", {}).get("id", "")

                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_networks SET status = 'created', "
                            "pcd_network_id = %s, pcd_subnet_id = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s AND network_name = %s",
                            (net_id, subnet_id, batch_id, dn, pn, nn),
                        )
                logger.info("Created network '%s/%s/%s' net=%s subnet=%s", dn, pn, nn, net_id, subnet_id)
            except Exception as exc:
                logger.error("Failed to create network '%s/%s/%s': %s", dn, pn, nn, exc)
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_networks SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s AND network_name = %s",
                            (str(exc), batch_id, dn, pn, nn),
                        )

        # ── Create users ──────────────────────────────────────────────────────
        for user in items["users"]:
            dn = user["domain_name"]
            pn = user["project_name"]
            un = user["username"]
            dom_id = domain_id_map.get(dn)
            proj_id = project_id_map.get((dn, pn))
            if not dom_id or not proj_id:
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_users SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s AND username = %s",
                            (f"Parent domain/project not created", batch_id, dn, pn, un),
                        )
                continue
            temp_pw = _gen_temp_password()
            try:
                result_u = client.create_user(
                    un,
                    password=temp_pw,
                    domain_id=dom_id,
                    email=user.get("email") or None,
                )
                user_id = result_u.get("id") or result_u.get("user", {}).get("id", "")

                # Map role name to role ID
                role_name = user.get("role", "member")
                try:
                    role_id = client.get_role_id(role_name)
                except Exception:
                    role_id = role_name  # fallback: pass name directly

                client.assign_role_to_user_on_project(proj_id, user_id, role_id)

                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_users SET status = 'created', "
                            "pcd_user_id = %s, temp_password = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s AND username = %s",
                            (user_id, temp_pw, batch_id, dn, pn, un),
                        )
                logger.info("Created user '%s/%s' id=%s", dn, un, user_id)
            except Exception as exc:
                logger.error("Failed to create user '%s/%s': %s", dn, un, exc)
                with get_connection() as conn2:
                    with conn2.cursor() as cur2:
                        cur2.execute(
                            "UPDATE onboarding_users SET status = 'failed', error_msg = %s "
                            "WHERE batch_id = %s AND domain_name = %s AND project_name = %s AND username = %s",
                            (str(exc), batch_id, dn, pn, un),
                        )

        # ── Compute final status ─────────────────────────────────────────────
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Count failures across all item tables
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM onboarding_customers WHERE batch_id=%s AND status='failed') +
                        (SELECT COUNT(*) FROM onboarding_projects  WHERE batch_id=%s AND status='failed') +
                        (SELECT COUNT(*) FROM onboarding_networks  WHERE batch_id=%s AND status='failed') +
                        (SELECT COUNT(*) FROM onboarding_users     WHERE batch_id=%s AND status='failed') AS fail_count
                    """,
                    (batch_id, batch_id, batch_id, batch_id),
                )
                fail_count = cur.fetchone()["fail_count"]

        final_status = "partially_failed" if fail_count > 0 else "complete"
        exec_result = {"failed_items": fail_count, "completed_by": actor, "completed_at": _now().isoformat()}

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboarding_batches SET status = %s, execution_result = %s::jsonb WHERE batch_id = %s",
                    (final_status, psycopg2.extras.Json(exec_result), batch_id),
                )

        event = "onboarding_completed" if final_status == "complete" else "onboarding_failed"
        severity = "info" if final_status == "complete" else "warning"
        _fire(
            event,
            f"Onboarding {'Completed' if final_status == 'complete' else 'Partially Failed'}",
            f"Batch '{batch['batch_name']}' finished with status '{final_status}'. "
            f"{fail_count} item(s) failed.",
            severity,
        )
        logger.info("Batch %s execution finished: %s (failures=%d)", batch_id, final_status, fail_count)

    except Exception as exc:
        logger.exception("Unexpected error executing batch %s: %s", batch_id, exc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE onboarding_batches SET status = 'partially_failed', "
                    "execution_result = %s::jsonb WHERE batch_id = %s",
                    (psycopg2.extras.Json({"error": str(exc)}), batch_id),
                )
        _fire(
            "onboarding_failed",
            "Onboarding Failed",
            f"Batch execution failed with an unexpected error: {exc}",
            "critical",
        )


@router.post("/batches/{batch_id}/execute")
def execute_batch(batch_id: str, current_user: dict = Depends(require_permission("onboarding", "execute"))):
    """
    Execute the batch. Requires:
      - approval_status == 'approved'
      - status == 'dry_run_passed'
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            batch = _get_batch(cur, batch_id)

    if batch["approval_status"] != "approved":
        raise HTTPException(
            status_code=400,
            detail="Batch must be approved before execution. "
                   f"Current approval_status: '{batch['approval_status']}'",
        )
    if batch["status"] != "dry_run_passed":
        raise HTTPException(
            status_code=400,
            detail="Dry-run must pass (zero conflicts) before execution is unlocked. "
                   f"Current status: '{batch['status']}'",
        )

    actor = current_user.get("username", "unknown")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE onboarding_batches SET status = 'executing' WHERE batch_id = %s",
                (batch_id,),
            )

    # Run async so the HTTP request returns immediately
    thread = threading.Thread(
        target=_execute_batch_sync,
        args=(batch_id, actor),
        daemon=True,
    )
    thread.start()

    logger.info("Batch %s execution started in background by %s", batch_id, actor)
    return {
        "status": "executing",
        "batch_id": batch_id,
        "message": "Execution started. Poll GET /api/onboarding/batches/{batch_id} for status.",
    }


# ---------------------------------------------------------------------------
# DELETE /batches/{batch_id}
# ---------------------------------------------------------------------------

@router.delete("/batches/{batch_id}", status_code=204)
def delete_batch(batch_id: str, current_user: dict = Depends(require_permission("onboarding", "create"))):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            batch = _get_batch(cur, batch_id)
            if batch["status"] in ("executing",):
                raise HTTPException(status_code=400, detail="Cannot delete a batch that is currently executing")
            cur.execute("DELETE FROM onboarding_batches WHERE batch_id = %s", (batch_id,))
