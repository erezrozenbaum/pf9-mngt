"""
Ticket Routes — Support ticket system with SLA policies, approval workflow,
runbook integration, and Slack / SMTP notifications.

Phases T1 + T2 (v1.58.0)

Endpoints:
  GET    /api/tickets                       list tickets (filtered)
  POST   /api/tickets                       create ticket
  GET    /api/tickets/my-queue              tickets assigned to current user
  GET    /api/tickets/stats                 aggregate statistics
  GET    /api/tickets/{id}                  get single ticket
  PUT    /api/tickets/{id}                  update ticket
  POST   /api/tickets/{id}/assign           assign ticket to a user
  POST   /api/tickets/{id}/escalate         escalate to another dept
  POST   /api/tickets/{id}/approve          approve pending-approval ticket
  POST   /api/tickets/{id}/reject           reject pending-approval ticket
  POST   /api/tickets/{id}/resolve          resolve ticket
  POST   /api/tickets/{id}/reopen          reopen resolved ticket
  POST   /api/tickets/{id}/close            close ticket
  GET    /api/tickets/{id}/comments         list comments
  POST   /api/tickets/{id}/comments         add comment
  GET    /api/tickets/{id}/trigger-runbook  (T2) run linked runbook
  POST   /api/tickets/{id}/trigger-runbook  (T2) trigger a runbook on ticket
  GET    /api/tickets/{id}/runbook-result   (T2) latest runbook result for ticket
  POST   /api/tickets/{id}/email-customer   (T2) send templated email to customer

  GET    /api/tickets/sla-policies          list SLA policies
  POST   /api/tickets/sla-policies          create SLA policy
  PUT    /api/tickets/sla-policies/{id}     update SLA policy
  DELETE /api/tickets/sla-policies/{id}     delete SLA policy

  GET    /api/tickets/email-templates       list email templates
  PUT    /api/tickets/email-templates/{template_name}  update template

  POST   /api/tickets/_auto                 (internal) auto-create ticket from system
"""

import os
import re
import json
import html
import logging
import traceback
import httpx
from datetime import datetime, timezone
from typing import Optional, List, Any

from fastapi import APIRouter, HTTPException, Depends, Request, Query, status
from pydantic import BaseModel, Field, EmailStr, validator, root_validator
from psycopg2.extras import RealDictCursor

from db_pool import get_connection
from auth import require_permission, get_current_user, User
from smtp_helper import send_email, SMTP_ENABLED
from webhook_helper import post_event

logger = logging.getLogger("pf9_tickets")

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

# ---------------------------------------------------------------------------
#  Auto-migration on import
# ---------------------------------------------------------------------------
def _ensure_tables() -> None:
    """Run migration file if core ticket tables are absent."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = 'support_tickets'
                    )
                """)
                if not cur.fetchone()[0]:
                    migration = os.path.join(
                        os.path.dirname(__file__), "..", "db",
                        "migrate_support_tickets.sql"
                    )
                    if os.path.exists(migration):
                        with open(migration) as f:
                            cur.execute(f.read())
                        logger.info("Ticket tables created via auto-migration")
    except Exception as exc:
        logger.warning("Could not ensure ticket tables on startup: %s", exc)


try:
    _ensure_tables()
except Exception:
    pass


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_caller_dept_id(username: str) -> Optional[int]:
    """Look up a user's department_id from user_roles."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT department_id FROM user_roles WHERE username = %s LIMIT 1",
                    (username,),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def _get_dept_id_by_name(name: str) -> Optional[int]:
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM departments WHERE name = %s LIMIT 1", (name,)
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def _generate_ticket_ref() -> str:
    """Generate a unique TKT-YYYY-NNNNN reference using ticket_sequence."""
    year = _now().year
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ticket_sequence (year, last_seq)
                VALUES (%s, 1)
                ON CONFLICT (year) DO UPDATE
                    SET last_seq = ticket_sequence.last_seq + 1
                RETURNING last_seq
            """, (year,))
            seq = cur.fetchone()[0]
    return f"TKT-{year}-{seq:05d}"


def _apply_sla(ticket_type: str, priority: str, to_dept_id: int,
               created_at: datetime) -> dict:
    """
    Look up the best-matching SLA policy and return deadline column values.
    Falls back gracefully if no policy exists.
    """
    result: dict = {}
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT response_sla_hours, resolution_sla_hours
                    FROM ticket_sla_policies
                    WHERE to_dept_id = %s AND ticket_type = %s AND priority = %s
                    LIMIT 1
                """, (to_dept_id, ticket_type, priority))
                policy = cur.fetchone()
    except Exception as exc:
        logger.warning("SLA lookup failed: %s", exc)
        return result

    if policy:
        r_h = policy["response_sla_hours"]
        rs_h = policy["resolution_sla_hours"]
        from datetime import timedelta
        result["sla_response_hours"] = r_h
        result["sla_resolve_hours"]  = rs_h
        result["sla_response_at"]    = created_at + timedelta(hours=r_h)
        result["sla_resolve_at"]     = created_at + timedelta(hours=rs_h)
    return result


def _sla_visible_filter(username: str, role: str) -> tuple[str, list]:
    """
    Return a WHERE clause fragment (without leading AND/WHERE) and bind-values
    that enforce row-level visibility for ticket lists.

    - superadmin / admin: see everything
    - operator / technical / viewer: see tickets routed to their dept
      OR opened by themselves
    """
    if role in ("admin", "superadmin"):
        return "1=1", []

    dept_id = _get_caller_dept_id(username)
    conditions = ["opened_by = %s"]
    values: list = [username]
    if dept_id:
        conditions.append("to_dept_id = %s")
        values.append(dept_id)
    return f"({' OR '.join(conditions)})", values


def _add_comment(
    ticket_id: int,
    author: str,
    body: str,
    *,
    is_internal: bool = False,
    comment_type: str = "comment",
    metadata: dict | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ticket_comments
                    (ticket_id, author, body, is_internal, comment_type, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (ticket_id, author, body, is_internal, comment_type,
                  json.dumps(metadata or {})))


def _render_template(tpl_name: str, context: dict) -> tuple[str, str]:
    """
    Return (subject, html_body) for the named template with {{key}} substitutions.
    Raises HTTPException(404) if the template does not exist.
    All context values are HTML-escaped before substitution to prevent XSS.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT subject, html_body FROM ticket_email_templates "
                "WHERE template_name = %s",
                (tpl_name,),
            )
            tpl = cur.fetchone()
    if not tpl:
        raise HTTPException(status_code=404,
                            detail=f"Email template '{tpl_name}' not found")

    def _sub(template_str: str) -> str:
        def replace(m: re.Match) -> str:
            key = m.group(1).strip()
            # Escape to prevent XSS from ticket data injected into HTML
            return html.escape(str(context.get(key, "")))
        return re.sub(r"\{\{(\w+)\}\}", replace, template_str)

    return _sub(tpl["subject"]), _sub(tpl["html_body"])


def _notify_ticket(event_type: str, ticket: dict, extra: str = "") -> None:
    """Post a Slack/Teams notification for a ticket event (best-effort)."""
    try:
        ref   = ticket.get("ticket_ref", "?")
        title = ticket.get("title", "")
        dept  = ticket.get("to_dept_name", "")
        prio  = ticket.get("priority", "")
        body  = f"*{ref}* — {title}\nDept: {dept} | Priority: {prio}"
        if extra:
            body += f"\n{extra}"
        post_event(event_type, f"Ticket {event_type.replace('_', ' ').title()}", body)
    except Exception as exc:
        logger.warning("Webhook notification failed for ticket event: %s", exc)


# ---------------------------------------------------------------------------
#  Pydantic models
# ---------------------------------------------------------------------------
_VALID_TYPES = {
    "service_request", "incident", "change_request", "inquiry",
    "escalation", "auto_incident", "auto_change_request",
}
_VALID_PRIORITIES = {"low", "normal", "high", "critical"}
_VALID_STATUSES  = {
    "open", "assigned", "in_progress", "waiting_customer",
    "pending_approval", "resolved", "closed",
}


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str = ""
    ticket_type: str = "service_request"
    priority: str = "normal"
    to_dept_id: int
    from_dept_id: Optional[int] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    auto_notify_customer: bool = False
    resource_type: Optional[str] = None
    resource_id:   Optional[str] = None
    resource_name: Optional[str] = None
    project_id:    Optional[str] = None
    project_name:  Optional[str] = None
    domain_id:     Optional[str] = None
    domain_name:   Optional[str] = None
    assigned_to: Optional[str] = None
    requires_approval: bool = False

    @validator("ticket_type")
    def _vtype(cls, v: str) -> str:
        if v not in _VALID_TYPES:
            raise ValueError(f"Invalid ticket_type: {v}")
        return v

    @validator("priority")
    def _vprio(cls, v: str) -> str:
        if v not in _VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        return v


class TicketUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    ticket_type: Optional[str] = None
    priority:    Optional[str] = None
    status:      Optional[str] = None
    to_dept_id:  Optional[int] = None
    customer_name:  Optional[str] = None
    customer_email: Optional[str] = None
    auto_notify_customer: Optional[bool] = None

    @validator("ticket_type")
    def _vtype(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_TYPES:
            raise ValueError(f"Invalid ticket_type: {v}")
        return v

    @validator("priority")
    def _vprio(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        return v

    @validator("status")
    def _vstatus(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {v}")
        return v


class AssignRequest(BaseModel):
    assigned_to: str = Field(..., min_length=1, max_length=255)
    comment: str = ""


class EscalateRequest(BaseModel):
    to_dept_id: int
    reason: str = ""


class ApproveRejectRequest(BaseModel):
    note: str = ""


class ResolveRequest(BaseModel):
    resolution_note: str = ""


class ReopenRequest(BaseModel):
    reason: str = ""


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1)
    is_internal: bool = False


class TriggerRunbookRequest(BaseModel):
    runbook_name: str
    dry_run: bool = True
    parameters: dict = Field(default_factory=dict)
    comment: str = ""


class EmailCustomerRequest(BaseModel):
    template_name: str = "ticket_created"
    extra_context: dict = Field(default_factory=dict)
    reply_to: Optional[str] = None


class SLAPolicyCreate(BaseModel):
    to_dept_id: int
    ticket_type: str
    priority: str
    response_sla_hours: int
    resolution_sla_hours: int
    auto_escalate_on_breach: bool = False
    escalate_to_dept_id: Optional[int] = None

    @validator("priority")
    def _vprio(cls, v: str) -> str:
        if v not in _VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {v}")
        return v


class SLAPolicyUpdate(BaseModel):
    response_sla_hours:      Optional[int]  = None
    resolution_sla_hours:    Optional[int]  = None
    auto_escalate_on_breach: Optional[bool] = None
    escalate_to_dept_id:     Optional[int]  = None


class EmailTemplateUpdate(BaseModel):
    subject:   Optional[str] = None
    html_body: Optional[str] = None


class AutoTicketCreate(BaseModel):
    """Internal auto-ticket creation (system-generated incidents/changes)."""
    title:          str
    description:    str = ""
    ticket_type:    str = "auto_incident"
    priority:       str = "high"
    to_dept_id:     Optional[int] = None    # either to_dept_id OR to_dept_name required
    to_dept_name:   Optional[str] = None    # resolved to ID in the endpoint
    auto_source:    str
    auto_source_id: str
    resource_type:  Optional[str] = None
    resource_id:    Optional[str] = None
    resource_name:  Optional[str] = None
    project_id:     Optional[str] = None
    project_name:   Optional[str] = None
    auto_blocked:   bool = False
    requires_approval: bool = False

    @root_validator(skip_on_failure=True)
    def _check_dept_provided(cls, values: dict) -> dict:
        if values.get("to_dept_id") is None and not values.get("to_dept_name"):
            raise ValueError("Either to_dept_id or to_dept_name must be provided")
        return values


# ---------------------------------------------------------------------------
#  In-process auto-ticket helper (no FastAPI, pure DB — importable by other modules)
# ---------------------------------------------------------------------------
def _auto_ticket(
    *,
    title: str,
    description: str = "",
    ticket_type: str = "auto_incident",
    priority: str = "high",
    to_dept_name: str,
    auto_source: str,
    auto_source_id: str,
    resource_type: Optional[str] = None,
    resource_id:   Optional[str] = None,
    resource_name: Optional[str] = None,
    project_id:    Optional[str] = None,
    project_name:  Optional[str] = None,
    auto_blocked:  bool = False,
    add_comment_if_existing: bool = False,
) -> dict:
    """
    Create an auto-ticket directly via DB (no HTTP round-trip).
    Idempotent: if an open ticket for (auto_source, auto_source_id) already exists,
    optionally adds a re-detection comment and returns existing ticket info.
    Returns {ticket_id, ticket_ref, created: bool}, or {} on error.
    """
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Dedup check
                cur.execute("""
                    SELECT id, ticket_ref FROM support_tickets
                    WHERE auto_source = %s AND auto_source_id = %s
                      AND status NOT IN ('resolved', 'closed')
                    LIMIT 1
                """, (auto_source, auto_source_id))
                existing = cur.fetchone()

                if existing:
                    if add_comment_if_existing:
                        _add_comment(
                            existing["id"],
                            author="system",
                            body="Condition re-detected.",
                            is_internal=True,
                            comment_type="system",
                        )
                    return {"ticket_id": existing["id"], "ticket_ref": existing["ticket_ref"], "created": False}

                # Resolve dept name → ID
                cur.execute("SELECT id FROM departments WHERE name = %s LIMIT 1", (to_dept_name,))
                dept_row = cur.fetchone()
                if not dept_row:
                    logger.warning("_auto_ticket: dept '%s' not found", to_dept_name)
                    return {}
                to_dept_id = dept_row["id"]

                ref        = _generate_ticket_ref()
                created_at = _now()
                sla        = _apply_sla(ticket_type, priority, to_dept_id, created_at)

                cur.execute("""
                    INSERT INTO support_tickets (
                        ticket_ref, title, description, ticket_type, status, priority,
                        to_dept_id, opened_by, auto_source, auto_source_id, auto_blocked,
                        resource_type, resource_id, resource_name, project_id, project_name,
                        sla_response_hours, sla_resolve_hours, sla_response_at, sla_resolve_at,
                        created_at, updated_at
                    ) VALUES (
                        %s,%s,%s,%s,'open',%s,
                        %s,'system',%s,%s,%s,
                        %s,%s,%s,%s,%s,
                        %s,%s,%s,%s,
                        %s,%s
                    ) RETURNING id, ticket_ref
                """, (
                    ref, title, description, ticket_type, priority,
                    to_dept_id, auto_source, auto_source_id, auto_blocked,
                    resource_type, resource_id, resource_name, project_id, project_name,
                    sla.get("sla_response_hours"), sla.get("sla_resolve_hours"),
                    sla.get("sla_response_at"),    sla.get("sla_resolve_at"),
                    created_at, created_at,
                ))
                row = cur.fetchone()

        _add_comment(
            row["id"], "system",
            f"Auto-created from {auto_source} (id: {auto_source_id}).",
            is_internal=True, comment_type="auto_created",
        )
        logger.info("_auto_ticket: created %s (%s / %s)", row["ticket_ref"], auto_source, auto_source_id)
        return {"ticket_id": row["id"], "ticket_ref": row["ticket_ref"], "created": True}

    except Exception as exc:
        logger.error("_auto_ticket failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
#  Helper — fetch a full ticket row with dept names (for responses)
# ---------------------------------------------------------------------------
def _get_ticket(ticket_id: int) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT t.*,
                       d_to.name   AS to_dept_name,
                       d_from.name AS from_dept_name,
                       d_prev.name AS prev_dept_name
                FROM support_tickets t
                LEFT JOIN departments d_to   ON d_to.id   = t.to_dept_id
                LEFT JOIN departments d_from ON d_from.id = t.from_dept_id
                LEFT JOIN departments d_prev ON d_prev.id = t.prev_dept_id
                WHERE t.id = %s
            """, (ticket_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return dict(row)


# ===========================================================================
#  ROUTES — Tickets
# ===========================================================================

@router.get("")
async def list_tickets(
    status_filter: Optional[str] = Query(None, alias="status"),
    priority:      Optional[str] = Query(None),
    ticket_type:   Optional[str] = Query(None),
    to_dept_id:    Optional[int] = Query(None),
    assigned_to:   Optional[str] = Query(None),
    opened_by:     Optional[str] = Query(None),
    search:        Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_permission("tickets", "read")),
):
    """List tickets — results are scoped by caller role & department."""
    username = user["username"]
    role     = user["role"]

    vis_clause, vis_vals = _sla_visible_filter(username, role)

    conditions = [vis_clause]
    values: list[Any] = vis_vals

    if status_filter:
        conditions.append("t.status = %s")
        values.append(status_filter)
    if priority:
        conditions.append("t.priority = %s")
        values.append(priority)
    if ticket_type:
        conditions.append("t.ticket_type = %s")
        values.append(ticket_type)
    if to_dept_id:
        conditions.append("t.to_dept_id = %s")
        values.append(to_dept_id)
    if assigned_to:
        conditions.append("t.assigned_to = %s")
        values.append(assigned_to)
    if opened_by:
        conditions.append("t.opened_by = %s")
        values.append(opened_by)
    if search:
        conditions.append("(t.title ILIKE %s OR t.ticket_ref ILIKE %s OR t.description ILIKE %s)")
        like = f"%{search}%"
        values += [like, like, like]

    where = " AND ".join(conditions)
    values.extend([limit, offset])

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT t.*,
                       d_to.name   AS to_dept_name,
                       d_from.name AS from_dept_name
                FROM support_tickets t
                LEFT JOIN departments d_to   ON d_to.id   = t.to_dept_id
                LEFT JOIN departments d_from ON d_from.id = t.from_dept_id
                WHERE {where}
                ORDER BY t.created_at DESC
                LIMIT %s OFFSET %s
            """, values)
            rows = [dict(r) for r in cur.fetchall()]

            cur.execute(
                f"SELECT COUNT(*) FROM support_tickets t WHERE {where}",
                values[:-2],
            )
            total = cur.fetchone()["count"]

    return {"tickets": rows, "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201)
async def create_ticket(
    body: TicketCreate,
    user: dict = Depends(require_permission("tickets", "write")),
):
    """Create a new support ticket."""
    username = user["username"]
    now      = _now()
    ref      = _generate_ticket_ref()

    from_dept_id = body.from_dept_id or _get_caller_dept_id(username)

    sla_cols = _apply_sla(body.ticket_type, body.priority, body.to_dept_id, now)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            assignee       = body.assigned_to or None
            initial_status = "assigned" if assignee else "open"
            cur.execute("""
                INSERT INTO support_tickets (
                    ticket_ref, title, description, ticket_type, status, priority,
                    from_dept_id, to_dept_id, opened_by, assigned_to,
                    customer_name, customer_email, auto_notify_customer,
                    resource_type, resource_id, resource_name,
                    project_id, project_name, domain_id, domain_name,
                    requires_approval,
                    sla_response_hours, sla_resolve_hours,
                    sla_response_at, sla_resolve_at,
                    created_at, updated_at
                ) VALUES (
                    %s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,
                    %s,
                    %s,%s,
                    %s,%s,
                    %s,%s
                )
                RETURNING id
            """, (
                ref, body.title, body.description, body.ticket_type, initial_status, body.priority,
                from_dept_id, body.to_dept_id, username, assignee,
                body.customer_name, body.customer_email, body.auto_notify_customer,
                body.resource_type, body.resource_id, body.resource_name,
                body.project_id, body.project_name, body.domain_id, body.domain_name,
                body.requires_approval,
                sla_cols.get("sla_response_hours"), sla_cols.get("sla_resolve_hours"),
                sla_cols.get("sla_response_at"),    sla_cols.get("sla_resolve_at"),
                now, now,
            ))
            ticket_id = cur.fetchone()["id"]

    # Audit comment
    _add_comment(
        ticket_id, username,
        f"Ticket created: {ref}",
        is_internal=True, comment_type="auto_created",
    )

    if body.requires_approval:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE support_tickets SET status='pending_approval', updated_at=%s WHERE id=%s",
                    (_now(), ticket_id),
                )
        _add_comment(ticket_id, "system",
                     "Ticket requires approval before work begins.",
                     is_internal=True, comment_type="approval")

    ticket = _get_ticket(ticket_id)
    _notify_ticket("ticket_created", ticket)

    # Auto-notify customer on creation
    if body.auto_notify_customer and body.customer_email and SMTP_ENABLED:
        try:
            subj, html_body = _render_template("ticket_created", {
                "ticket_ref":    ref,
                "title":         body.title,
                "priority":      body.priority,
                "to_dept":       ticket.get("to_dept_name", ""),
                "customer_name": body.customer_name or "Customer",
            })
            send_email([body.customer_email], subj, html_body)
        except Exception as exc:
            logger.warning("Failed to auto-notify customer on ticket creation: %s", exc)

    # Confirmation email to the internal user who opened the ticket
    if SMTP_ENABLED:
        try:
            with get_connection() as _conn:
                with _conn.cursor() as _cur:
                    _cur.execute("SELECT email FROM users WHERE name = %s", (username,))
                    opener_row = _cur.fetchone()
            if opener_row and opener_row[0]:
                subj, html_body = _render_template("ticket_created", {
                    "ticket_ref":    ref,
                    "title":         body.title,
                    "priority":      body.priority,
                    "to_dept":       ticket.get("to_dept_name", ""),
                    "customer_name": username,
                })
                send_email([opener_row[0]], subj, html_body)
        except Exception as exc:
            logger.warning("Failed to send opener confirmation email: %s", exc)

    return ticket


@router.get("/my-queue")
async def my_queue(
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_permission("tickets", "read")),
):
    """Return tickets assigned to the current user."""
    username = user["username"]
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT t.*, d.name AS to_dept_name
                FROM support_tickets t
                LEFT JOIN departments d ON d.id = t.to_dept_id
                WHERE t.assigned_to = %s AND t.status NOT IN ('resolved','closed')
                ORDER BY
                    CASE t.priority
                        WHEN 'critical' THEN 1
                        WHEN 'high'     THEN 2
                        WHEN 'normal'   THEN 3
                        WHEN 'low'      THEN 4
                        ELSE 5
                    END,
                    t.created_at ASC
                LIMIT %s OFFSET %s
            """, (username, limit, offset))
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT COUNT(*) FROM support_tickets WHERE assigned_to = %s "
                "AND status NOT IN ('resolved','closed')",
                (username,),
            )
            total = cur.fetchone()["count"]
    return {"tickets": rows, "total": total, "limit": limit, "offset": offset}


@router.get("/stats")
async def ticket_stats(
    user: dict = Depends(require_permission("tickets", "read")),
):
    """Return aggregate counts grouped by status and priority."""
    username = user["username"]
    role     = user["role"]

    vis_clause, vis_vals = _sla_visible_filter(username, role)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"SELECT status, COUNT(*) AS cnt FROM support_tickets "
                f"WHERE {vis_clause} GROUP BY status",
                vis_vals,
            )
            by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

            cur.execute(
                f"SELECT priority, COUNT(*) AS cnt FROM support_tickets "
                f"WHERE {vis_clause} GROUP BY priority",
                vis_vals,
            )
            by_priority = {r["priority"]: r["cnt"] for r in cur.fetchall()}

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM support_tickets "
                f"WHERE {vis_clause} AND sla_resolve_breached = true",
                vis_vals,
            )
            sla_breach = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM support_tickets "
                f"WHERE {vis_clause} AND status NOT IN ('resolved','closed')",
                vis_vals,
            )
            open_count = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM support_tickets "
                f"WHERE {vis_clause} AND status IN ('resolved','closed') "
                f"AND resolved_at::date = CURRENT_DATE",
                vis_vals,
            )
            resolved_today = cur.fetchone()["cnt"]

            cur.execute(
                f"SELECT COUNT(*) AS cnt FROM support_tickets "
                f"WHERE {vis_clause} AND created_at::date = CURRENT_DATE",
                vis_vals,
            )
            opened_today = cur.fetchone()["cnt"]

    return {
        "by_status":      by_status,
        "by_priority":    by_priority,
        "sla_breached":   sla_breach,
        "open":           open_count,
        "resolved_today": resolved_today,
        "opened_today":   opened_today,
    }


# ===========================================================================
#  ROUTES — SLA Policies  (declared before /{ticket_id} to avoid path conflict)
# ===========================================================================

@router.get("/sla-policies")
async def list_sla_policies(
    user: dict = Depends(require_permission("tickets", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT p.*, d.name AS to_dept_name, e.name AS escalate_dept_name
                FROM ticket_sla_policies p
                LEFT JOIN departments d ON d.id = p.to_dept_id
                LEFT JOIN departments e ON e.id = p.escalate_to_dept_id
                ORDER BY p.to_dept_id, p.ticket_type, p.priority
            """)
            return {"policies": [dict(r) for r in cur.fetchall()]}


@router.post("/sla-policies", status_code=201)
async def create_sla_policy(
    body: SLAPolicyCreate,
    user: dict = Depends(require_permission("tickets", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO ticket_sla_policies
                    (to_dept_id, ticket_type, priority, response_sla_hours,
                     resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (to_dept_id, ticket_type, priority)
                DO UPDATE SET
                    response_sla_hours    = EXCLUDED.response_sla_hours,
                    resolution_sla_hours  = EXCLUDED.resolution_sla_hours,
                    auto_escalate_on_breach = EXCLUDED.auto_escalate_on_breach,
                    escalate_to_dept_id   = EXCLUDED.escalate_to_dept_id
                RETURNING *
            """, (body.to_dept_id, body.ticket_type, body.priority,
                  body.response_sla_hours, body.resolution_sla_hours,
                  body.auto_escalate_on_breach, body.escalate_to_dept_id))
            return dict(cur.fetchone())


@router.put("/sla-policies/{policy_id}")
async def update_sla_policy(
    policy_id: int,
    body: SLAPolicyUpdate,
    user: dict = Depends(require_permission("tickets", "admin")),
):
    updates: dict[str, Any] = {}
    if body.response_sla_hours      is not None: updates["response_sla_hours"]      = body.response_sla_hours
    if body.resolution_sla_hours    is not None: updates["resolution_sla_hours"]    = body.resolution_sla_hours
    if body.auto_escalate_on_breach is not None: updates["auto_escalate_on_breach"] = body.auto_escalate_on_breach
    if body.escalate_to_dept_id     is not None: updates["escalate_to_dept_id"]     = body.escalate_to_dept_id

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values     = list(updates.values()) + [policy_id]

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE ticket_sla_policies SET {set_clause} WHERE id = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="SLA policy not found")
    return dict(row)


@router.delete("/sla-policies/{policy_id}", status_code=204)
async def delete_sla_policy(
    policy_id: int,
    user: dict = Depends(require_permission("tickets", "admin")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ticket_sla_policies WHERE id = %s", (policy_id,))


# ===========================================================================
#  ROUTES — Email Templates  (declared before /{ticket_id} to avoid path conflict)
# ===========================================================================

@router.get("/email-templates")
async def list_email_templates(
    user: dict = Depends(require_permission("tickets", "admin")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM ticket_email_templates ORDER BY template_name"
            )
            return {"templates": [dict(r) for r in cur.fetchall()]}


@router.put("/email-templates/{template_name}")
async def update_email_template(
    template_name: str,
    body: EmailTemplateUpdate,
    user: dict = Depends(require_permission("tickets", "admin")),
):
    if not body.subject and not body.html_body:
        raise HTTPException(status_code=400, detail="Provide subject or html_body to update")

    updates: dict[str, Any] = {"updated_at": _now()}
    if body.subject   is not None: updates["subject"]   = body.subject
    if body.html_body is not None: updates["html_body"] = body.html_body

    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values     = list(updates.values()) + [template_name]

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"UPDATE ticket_email_templates SET {set_clause} "
                f"WHERE template_name = %s RETURNING *",
                values,
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404,
                            detail=f"Template '{template_name}' not found")
    return dict(row)


# ===========================================================================
#  ROUTE — Internal auto-ticket creation  (declared before /{ticket_id})
# ===========================================================================

@router.post("/_auto", status_code=201, include_in_schema=False)
async def auto_create_ticket(
    body: AutoTicketCreate,
    user: dict = Depends(require_permission("tickets", "write")),
):
    """
    Idempotent auto-ticket endpoint: skip creation if an open ticket for
    the same (auto_source, auto_source_id) already exists.
    Accepts either to_dept_id (int) or to_dept_name (string).
    """
    # Resolve to_dept_id from name if not supplied
    resolved_dept_id = body.to_dept_id
    if resolved_dept_id is None:
        resolved_dept_id = _get_dept_id_by_name(body.to_dept_name or "")
        if not resolved_dept_id:
            raise HTTPException(status_code=422,
                                detail=f"Department '{body.to_dept_name}' not found")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, ticket_ref FROM support_tickets
                WHERE auto_source = %s AND auto_source_id = %s
                  AND status NOT IN ('resolved', 'closed')
                LIMIT 1
            """, (body.auto_source, body.auto_source_id))
            existing = cur.fetchone()

    if existing:
        return {"ticket_id": existing[0], "ticket_ref": existing[1], "created": False,
                "detail": "Existing open ticket for this source"}

    # Delegate to the normal create path
    create_body = TicketCreate(
        title=body.title,
        description=body.description,
        ticket_type=body.ticket_type,
        priority=body.priority,
        to_dept_id=resolved_dept_id,
        requires_approval=body.requires_approval,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        resource_name=body.resource_name,
        project_id=body.project_id,
        project_name=body.project_name,
    )
    ticket = await create_ticket(create_body, user=user)

    # Stamp auto_source fields
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET auto_source = %s, auto_source_id = %s, auto_blocked = %s, updated_at = %s
                WHERE id = %s
            """, (body.auto_source, body.auto_source_id, body.auto_blocked,
                  _now(), ticket["id"]))

    return {"ticket_id": ticket["id"], "ticket_ref": ticket["ticket_ref"], "created": True}


# ===========================================================================
#  ROUTES — Analytics & Bulk actions  (static paths BEFORE /{ticket_id})
# ===========================================================================

class BulkActionRequest(BaseModel):
    action: str  # "close_stale" | "reassign" | "export_csv"
    ticket_ids: Optional[List[int]] = None
    assigned_to: Optional[str] = None
    to_dept_id: Optional[int] = None
    stale_days: int = 30


@router.get("/analytics")
async def ticket_analytics(
    days: int = Query(30, ge=7, le=90),
    user: dict = Depends(require_permission("tickets", "admin")),
):
    """Management analytics: resolution time, SLA breach rates, top openers, volume trend."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT d.name AS dept_name,
                       COUNT(*) AS total,
                       ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600)::numeric, 1)
                           AS avg_resolution_hours
                FROM support_tickets t
                JOIN departments d ON d.id = t.to_dept_id
                WHERE t.resolved_at IS NOT NULL
                  AND t.created_at >= NOW() - (%s || ' days')::interval
                GROUP BY d.name
                ORDER BY avg_resolution_hours
            """, (days,))
            resolution_by_dept = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT d.name AS dept_name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN sla_resolve_breached THEN 1 ELSE 0 END) AS breached,
                       ROUND(100.0 * SUM(CASE WHEN sla_resolve_breached THEN 1 ELSE 0 END)
                             / NULLIF(COUNT(*), 0), 1) AS breach_pct
                FROM support_tickets t
                JOIN departments d ON d.id = t.to_dept_id
                WHERE t.created_at >= NOW() - (%s || ' days')::interval
                GROUP BY d.name
                ORDER BY breach_pct DESC NULLS LAST
            """, (days,))
            sla_by_dept = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT opened_by, COUNT(*) AS count
                FROM support_tickets
                WHERE created_at >= NOW() - (%s || ' days')::interval
                GROUP BY opened_by
                ORDER BY count DESC
                LIMIT 10
            """, (days,))
            top_openers = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT DATE(created_at) AS day,
                       COUNT(*) AS opened,
                       SUM(CASE WHEN status IN ('resolved','closed') THEN 1 ELSE 0 END) AS resolved
                FROM support_tickets
                WHERE created_at >= NOW() - (%s || ' days')::interval
                GROUP BY DATE(created_at)
                ORDER BY day
            """, (days,))
            volume_trend = [dict(r) for r in cur.fetchall()]

    # Make dates JSON-serialisable
    for row in volume_trend:
        if hasattr(row.get("day"), "isoformat"):
            row["day"] = row["day"].isoformat()

    return {
        "days": days,
        "resolution_by_dept": resolution_by_dept,
        "sla_by_dept": sla_by_dept,
        "top_openers": top_openers,
        "volume_trend": volume_trend,
    }


@router.post("/bulk-action")
async def bulk_action_tickets(
    req: BulkActionRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    """Bulk close-stale, mass-reassign, or export tickets as CSV."""
    import csv
    import io

    username = user["username"]
    role     = user["role"]
    vis_clause, vis_vals = _sla_visible_filter(username, role)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if req.action == "close_stale":
                id_frag = "AND id = ANY(%s)" if req.ticket_ids else ""
                extra   = [req.ticket_ids] if req.ticket_ids else []
                cur.execute(
                    f"UPDATE support_tickets "
                    f"SET status='closed', closed_at=NOW(), updated_at=NOW() "
                    f"WHERE {vis_clause} AND status='resolved' "
                    f"AND resolved_at < NOW() - INTERVAL '{req.stale_days} days' "
                    f"{id_frag} RETURNING id",
                    vis_vals + extra,
                )
                affected = cur.rowcount

            elif req.action == "reassign":
                if not req.ticket_ids:
                    raise HTTPException(status_code=400, detail="ticket_ids required for reassign")
                cur.execute(
                    f"UPDATE support_tickets "
                    f"SET assigned_to=%s, status='assigned', updated_at=NOW() "
                    f"WHERE {vis_clause} AND id = ANY(%s) "
                    f"AND status NOT IN ('resolved','closed') RETURNING id",
                    vis_vals + [req.assigned_to, req.ticket_ids],
                )
                affected = cur.rowcount

            elif req.action == "export_csv":
                id_frag = "AND t.id = ANY(%s)" if req.ticket_ids else ""
                extra   = [req.ticket_ids] if req.ticket_ids else []
                cur.execute(
                    f"SELECT t.*, d.name AS to_dept_name "
                    f"FROM support_tickets t "
                    f"LEFT JOIN departments d ON d.id = t.to_dept_id "
                    f"WHERE {vis_clause} {id_frag} ORDER BY t.id",
                    vis_vals + extra,
                )
                rows = cur.fetchall()
                buf = io.StringIO()
                if rows:
                    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                from fastapi.responses import PlainTextResponse
                return PlainTextResponse(
                    buf.getvalue(),
                    media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=tickets_export.csv"},
                )

            else:
                raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

    return {"action": req.action, "affected": affected}


# ===========================================================================
#  ROUTES — Dept team members
# ===========================================================================

@router.get("/team-members/{dept_id}")
async def get_team_members(
    dept_id: int,
    user: dict = Depends(require_permission("tickets", "read")),
):
    """Return active users assigned to the given department."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT username FROM user_roles WHERE department_id = %s AND is_active = true ORDER BY username",
                (dept_id,),
            )
            return {"members": [r["username"] for r in cur.fetchall()]}


# ===========================================================================
#  ROUTES — Per-ticket  (parameterized routes AFTER all static paths)
# ===========================================================================

@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: int,
    user: dict = Depends(require_permission("tickets", "read")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)
    return ticket


@router.put("/{ticket_id}")
async def update_ticket(
    ticket_id: int,
    body: TicketUpdate,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    updates: dict[str, Any] = {}
    if body.title is not None:       updates["title"]       = body.title
    if body.description is not None: updates["description"] = body.description
    if body.ticket_type is not None: updates["ticket_type"] = body.ticket_type
    if body.priority is not None:    updates["priority"]    = body.priority
    if body.status is not None:      updates["status"]      = body.status
    if body.to_dept_id is not None:  updates["to_dept_id"]  = body.to_dept_id
    if body.customer_name  is not None: updates["customer_name"]  = body.customer_name
    if body.customer_email is not None: updates["customer_email"] = body.customer_email
    if body.auto_notify_customer is not None:
        updates["auto_notify_customer"] = body.auto_notify_customer

    if not updates:
        return ticket

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values     = list(updates.values()) + [ticket_id]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE support_tickets SET {set_clause} WHERE id = %s", values
            )

    _add_comment(ticket_id, user["username"],
                 f"Ticket updated: {', '.join(updates.keys())}",
                 is_internal=True, comment_type="status_change")

    return _get_ticket(ticket_id)


# ---------------------------------------------------------------------------
#  Workflow actions
# ---------------------------------------------------------------------------

@router.post("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: int,
    body: AssignRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET assigned_to = %s, status = 'assigned',
                    first_response_at = COALESCE(first_response_at, %s),
                    updated_at = %s
                WHERE id = %s
            """, (body.assigned_to, now, now, ticket_id))

    _add_comment(ticket_id, user["username"],
                 f"Assigned to {body.assigned_to}." + (f" {body.comment}" if body.comment else ""),
                 is_internal=True, comment_type="assignment")

    updated = _get_ticket(ticket_id)
    _notify_ticket("ticket_assigned", updated, f"Assignee: {body.assigned_to}")
    return updated


@router.post("/{ticket_id}/escalate")
async def escalate_ticket(
    ticket_id: int,
    body: EscalateRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET prev_dept_id = to_dept_id,
                    to_dept_id = %s,
                    escalation_count = escalation_count + 1,
                    ticket_type = 'escalation',
                    status = 'open',
                    assigned_to = NULL,
                    updated_at = %s
                WHERE id = %s
            """, (body.to_dept_id, now, ticket_id))

    reason_txt = body.reason or "No reason given"
    _add_comment(ticket_id, user["username"],
                 f"Escalated to dept {body.to_dept_id}. Reason: {reason_txt}",
                 is_internal=True, comment_type="escalation",
                 metadata={"reason": reason_txt, "from_dept_id": ticket["to_dept_id"]})

    updated = _get_ticket(ticket_id)
    _notify_ticket("ticket_escalated", updated, f"Reason: {reason_txt}")
    return updated


@router.post("/{ticket_id}/approve")
async def approve_ticket(
    ticket_id: int,
    body: ApproveRejectRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    if ticket["status"] != "pending_approval":
        raise HTTPException(status_code=400,
                            detail="Ticket is not in pending_approval state")

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET status = 'open', approved_by = %s, approved_at = %s,
                    approval_note = %s, updated_at = %s
                WHERE id = %s
            """, (user["username"], now, body.note, now, ticket_id))

    _add_comment(ticket_id, user["username"],
                 f"Approved. {body.note}" if body.note else "Approved.",
                 is_internal=True, comment_type="approval")
    return _get_ticket(ticket_id)


@router.post("/{ticket_id}/reject")
async def reject_ticket(
    ticket_id: int,
    body: ApproveRejectRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    if ticket["status"] != "pending_approval":
        raise HTTPException(status_code=400,
                            detail="Ticket is not in pending_approval state")

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET status = 'closed', rejected_by = %s, rejected_at = %s,
                    approval_note = %s, closed_at = %s, updated_at = %s
                WHERE id = %s
            """, (user["username"], now, body.note, now, now, ticket_id))

    _add_comment(ticket_id, user["username"],
                 f"Rejected and closed. {body.note}" if body.note else "Rejected and closed.",
                 is_internal=True, comment_type="rejection")
    return _get_ticket(ticket_id)


@router.post("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: int,
    body: ResolveRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    if ticket["status"] in ("resolved", "closed"):
        raise HTTPException(status_code=400, detail="Ticket is already resolved/closed")

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET status = 'resolved', resolved_by = %s, resolved_at = %s,
                    resolution_note = %s, updated_at = %s
                WHERE id = %s
            """, (user["username"], now, body.resolution_note, now, ticket_id))

    _add_comment(ticket_id, user["username"],
                 f"Resolved: {body.resolution_note}" if body.resolution_note else "Resolved.",
                 is_internal=True, comment_type="status_change")

    updated = _get_ticket(ticket_id)
    _notify_ticket("ticket_resolved", updated)

    # Auto-notify customer
    if updated.get("auto_notify_customer") and updated.get("customer_email") and SMTP_ENABLED:
        try:
            subj, html_body = _render_template("ticket_resolved", {
                "ticket_ref":     updated["ticket_ref"],
                "title":          updated["title"],
                "resolution_note": body.resolution_note or "Resolved.",
                "customer_name":  updated.get("customer_name") or "Customer",
            })
            send_email([updated["customer_email"]], subj, html_body)
        except Exception as exc:
            logger.warning("Failed to auto-notify customer on resolution: %s", exc)

    return updated


@router.post("/{ticket_id}/reopen")
async def reopen_ticket(
    ticket_id: int,
    body: ReopenRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    if ticket["status"] not in ("resolved", "closed"):
        raise HTTPException(status_code=400,
                            detail="Only resolved or closed tickets can be reopened")

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET status = 'open', resolved_by = NULL, resolved_at = NULL,
                    resolution_note = NULL, closed_at = NULL, updated_at = %s
                WHERE id = %s
            """, (now, ticket_id))

    _add_comment(ticket_id, user["username"],
                 f"Reopened. {body.reason}" if body.reason else "Reopened.",
                 is_internal=True, comment_type="status_change")
    return _get_ticket(ticket_id)


@router.post("/{ticket_id}/close")
async def close_ticket(
    ticket_id: int,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    if ticket["status"] == "closed":
        raise HTTPException(status_code=400, detail="Ticket is already closed")

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET status = 'closed', closed_at = %s, updated_at = %s
                WHERE id = %s
            """, (now, now, ticket_id))

    _add_comment(ticket_id, user["username"], "Ticket closed.",
                 is_internal=True, comment_type="status_change")
    return _get_ticket(ticket_id)


# ---------------------------------------------------------------------------
#  Comments
# ---------------------------------------------------------------------------

@router.get("/{ticket_id}/comments")
async def list_comments(
    ticket_id: int,
    user: dict = Depends(require_permission("tickets", "read")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    # Viewers cannot see internal comments
    internal_filter = ""
    if user["role"] == "viewer":
        internal_filter = "AND is_internal = false"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT * FROM ticket_comments
                WHERE ticket_id = %s {internal_filter}
                ORDER BY created_at ASC
            """, (ticket_id,))
            rows = [dict(r) for r in cur.fetchall()]
    return {"comments": rows}


@router.post("/{ticket_id}/comments", status_code=201)
async def add_comment(
    ticket_id: int,
    body: CommentCreate,
    user: dict = Depends(require_permission("tickets", "write")),
):
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    # Viewers cannot post internal comments
    is_internal = body.is_internal
    if user["role"] == "viewer":
        is_internal = False

    _add_comment(ticket_id, user["username"], body.body,
                 is_internal=is_internal, comment_type="comment")

    # Auto-set first_response_at on first external comment
    if not is_internal and ticket.get("first_response_at") is None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE support_tickets SET first_response_at = %s, updated_at = %s "
                    "WHERE id = %s AND first_response_at IS NULL",
                    (_now(), _now(), ticket_id),
                )

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM ticket_comments WHERE ticket_id = %s ORDER BY created_at DESC LIMIT 1",
                (ticket_id,),
            )
            return dict(cur.fetchone())


# ---------------------------------------------------------------------------
#  T2 — Runbook integration
# ---------------------------------------------------------------------------

@router.post("/{ticket_id}/trigger-runbook", status_code=202)
async def trigger_runbook(
    ticket_id: int,
    body: TriggerRunbookRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    """Trigger a runbook linked to this ticket (T2)."""
    import hashlib
    from auth import create_access_token
    from datetime import timedelta

    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    # Generate a short-lived service token for the internal runbook API call,
    # and register it as an active session so verify_token accepts it.
    service_token = create_access_token(
        data={"sub": user["username"], "role": user["role"],
              "is_active": True, "service_call": True},
        expires_delta=timedelta(minutes=5),
    )
    token_hash = hashlib.sha256(service_token.encode()).hexdigest()
    now = _now()
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO user_sessions (username, role, token_hash, is_active, expires_at, created_at)
                    VALUES (%s, %s, %s, true, %s, %s)
                    ON CONFLICT DO NOTHING
                """, (user["username"], user["role"], token_hash,
                      now + timedelta(minutes=5), now))
    except Exception as exc:
        logger.warning("Could not register service token session: %s", exc)

    # Delegate to runbook API (internal call)
    api_base = os.environ.get("INTERNAL_API_BASE", "http://localhost:8000")
    headers  = {"Authorization": f"Bearer {service_token}"}
    payload  = {
        "runbook_name": body.runbook_name,
        "dry_run":      body.dry_run,
        "parameters":   body.parameters,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{api_base}/api/runbooks/trigger",
                json=payload,
                headers=headers,
            )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail=f"Runbook API error: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail=f"Runbook service unavailable: {exc}")

    execution_id = result.get("execution_id") or result.get("id")
    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE support_tickets SET linked_execution_id = %s, updated_at = %s WHERE id = %s",
                (str(execution_id) if execution_id else None, now, ticket_id),
            )

    note = body.comment or f"Runbook '{body.runbook_name}' triggered (dry_run={body.dry_run})."
    _add_comment(ticket_id, user["username"], note,
                 is_internal=True, comment_type="runbook_result",
                 metadata={"runbook_name": body.runbook_name,
                           "execution_id": execution_id,
                           "dry_run": body.dry_run})

    return {"ticket_id": ticket_id, "execution_id": execution_id, "result": result}


@router.get("/{ticket_id}/runbook-result")
async def get_runbook_result(
    ticket_id: int,
    user: dict = Depends(require_permission("tickets", "read")),
):
    """Return the latest runbook execution result linked to this ticket (T2)."""
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    exec_id = ticket.get("linked_execution_id")
    if not exec_id:
        raise HTTPException(status_code=404,
                            detail="No runbook execution linked to this ticket")

    api_base = os.environ.get("INTERNAL_API_BASE", "http://localhost:8000")
    try:
        import hashlib
        from auth import create_access_token
        from datetime import timedelta
        svc_token = create_access_token(
            data={"sub": user["username"], "role": user["role"],
                  "is_active": True, "service_call": True},
            expires_delta=timedelta(minutes=5),
        )
        t_hash = hashlib.sha256(svc_token.encode()).hexdigest()
        now2 = _now()
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO user_sessions (username, role, token_hash, is_active, expires_at, created_at) "
                        "VALUES (%s,%s,%s,true,%s,%s) ON CONFLICT DO NOTHING",
                        (user["username"], user["role"], t_hash, now2 + timedelta(minutes=5), now2),
                    )
        except Exception:
            pass
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{api_base}/api/runbooks/executions/{exec_id}",
                headers={"Authorization": f"Bearer {svc_token}"},
            )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code,
                            detail=f"Runbook API error: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail=f"Runbook service unavailable: {exc}")


# ---------------------------------------------------------------------------
#  T2 — Email customer
# ---------------------------------------------------------------------------

@router.post("/{ticket_id}/email-customer")
async def email_customer(
    ticket_id: int,
    body: EmailCustomerRequest,
    user: dict = Depends(require_permission("tickets", "write")),
):
    """Send a templated email to the ticket's customer contact (T2)."""
    ticket = _get_ticket(ticket_id)
    _assert_visible(ticket, user)

    if not SMTP_ENABLED:
        raise HTTPException(status_code=503,
                            detail="SMTP is not configured on this server")

    customer_email = ticket.get("customer_email")
    if not customer_email:
        raise HTTPException(status_code=400,
                            detail="Ticket has no customer_email set")

    # Build context from ticket fields + extra_context override
    ctx = {
        "ticket_ref":      ticket.get("ticket_ref", ""),
        "title":           ticket.get("title", ""),
        "priority":        ticket.get("priority", ""),
        "status":          ticket.get("status", ""),
        "ticket_type":     ticket.get("ticket_type", ""),
        "to_dept":         ticket.get("to_dept_name", ""),
        "assigned_to":     ticket.get("assigned_to", "Unassigned"),
        "opened_by":       ticket.get("opened_by", ""),
        "resolution_note": ticket.get("resolution_note", ""),
        "customer_name":   ticket.get("customer_name") or "Customer",
    }
    ctx.update(body.extra_context)

    subj, html_body = _render_template(body.template_name, ctx)

    send_email([customer_email], subj, html_body, raise_on_error=True)

    now = _now()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE support_tickets
                SET customer_notified_at = %s, last_email_subject = %s, updated_at = %s
                WHERE id = %s
            """, (now, subj, now, ticket_id))

    _add_comment(ticket_id, user["username"],
                 f"Email sent to customer ({customer_email}): {subj}",
                 is_internal=True, comment_type="email_sent",
                 metadata={"to": customer_email, "template": body.template_name})

    return {"sent": True, "to": customer_email, "subject": subj}


# ===========================================================================
#  SLA daemon — called from APScheduler in main.py every 15 min
# ===========================================================================

def run_sla_checks() -> None:
    """
    Scan open tickets for SLA breaches and:
    1. Mark breached flags.
    2. Post Slack/Teams notifications.
    3. Auto-escalate if configured.
    4. Add an internal comment on first breach.
    """
    now = _now()
    logger.debug("SLA check running at %s", now.isoformat())

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find tickets where response SLA is due but not marked yet
                cur.execute("""
                    SELECT t.id, t.ticket_ref, t.title, t.priority,
                           t.ticket_type, t.to_dept_id, t.assigned_to,
                           t.sla_response_at, t.sla_resolve_at,
                           t.sla_response_breached, t.sla_resolve_breached,
                           d.name AS to_dept_name
                    FROM support_tickets t
                    LEFT JOIN departments d ON d.id = t.to_dept_id
                    WHERE t.status NOT IN ('resolved','closed')
                      AND (
                          (t.sla_response_at IS NOT NULL AND t.sla_response_at < %s AND t.sla_response_breached = false)
                          OR
                          (t.sla_resolve_at  IS NOT NULL AND t.sla_resolve_at  < %s AND t.sla_resolve_breached  = false)
                      )
                """, (now, now))
                breached_rows = [dict(r) for r in cur.fetchall()]

        for row in breached_rows:
            _handle_sla_breach(row, now)

    except Exception as exc:
        logger.error("SLA check failed: %s\n%s", exc, traceback.format_exc())


def _handle_sla_breach(row: dict, now: datetime) -> None:
    tid    = row["id"]
    ref    = row["ticket_ref"]
    title  = row["title"]
    prio   = row["priority"]
    dept   = row["to_dept_name"]
    assignee = row.get("assigned_to", "Unassigned")

    resp_breach   = (row["sla_response_at"] and row["sla_response_at"] < now
                     and not row["sla_response_breached"])
    resolve_breach = (row["sla_resolve_at"] and row["sla_resolve_at"] < now
                      and not row["sla_resolve_breached"])

    breach_types = []
    update_parts = []
    update_vals  = []

    if resp_breach:
        breach_types.append("response")
        update_parts.append("sla_response_breached = true")
    if resolve_breach:
        breach_types.append("resolve")
        update_parts.append("sla_resolve_breached = true")

    update_parts.append("updated_at = %s")
    update_vals.append(now)
    update_vals.append(tid)

    breach_label = " & ".join(breach_types)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE support_tickets SET {', '.join(update_parts)} WHERE id = %s",
                    update_vals,
                )
    except Exception as exc:
        logger.error("Failed to mark SLA breach for ticket %s: %s", ref, exc)
        return

    _add_comment(tid, "system",
                 f"SLA breach: {breach_label} SLA exceeded.",
                 is_internal=True, comment_type="sla_breach",
                 metadata={"breach_type": breach_label, "at": now.isoformat()})

    _notify_ticket("ticket_sla_breach", row,
                   f"SLA '{breach_label}' breached | Assignee: {assignee}")

    # Auto-escalate?
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT escalate_to_dept_id
                    FROM ticket_sla_policies
                    WHERE to_dept_id = %s AND ticket_type = %s AND priority = %s
                      AND auto_escalate_on_breach = true
                      AND escalate_to_dept_id IS NOT NULL
                    LIMIT 1
                """, (row["to_dept_id"], row["ticket_type"], prio))
                pol = cur.fetchone()
    except Exception:
        pol = None

    if pol:
        esc_dept = pol["escalate_to_dept_id"]
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE support_tickets
                        SET prev_dept_id = to_dept_id,
                            to_dept_id = %s,
                            escalation_count = escalation_count + 1,
                            ticket_type = 'escalation',
                            status = 'open',
                            assigned_to = NULL,
                            updated_at = %s
                        WHERE id = %s
                    """, (esc_dept, now, tid))
            _add_comment(tid, "system",
                         f"Auto-escalated to dept {esc_dept} due to SLA breach.",
                         is_internal=True, comment_type="escalation",
                         metadata={"reason": "sla_auto_escalate",
                                   "breach_type": breach_label})
            logger.info("Auto-escalated ticket %s to dept %s due to SLA breach", ref, esc_dept)
        except Exception as exc:
            logger.error("Auto-escalation failed for ticket %s: %s", ref, exc)


# ---------------------------------------------------------------------------
#  Internal visibility guard (used by all single-ticket endpoints)
# ---------------------------------------------------------------------------
def _assert_visible(ticket: dict, user: dict) -> None:
    """Raise 404 (not 403) if the caller cannot access this ticket."""
    role     = user["role"]
    username = user["username"]
    if role in ("admin", "superadmin"):
        return
    dept_id = _get_caller_dept_id(username)
    if ticket["opened_by"] == username:
        return
    if dept_id and ticket["to_dept_id"] == dept_id:
        return
    raise HTTPException(status_code=404, detail="Ticket not found")
