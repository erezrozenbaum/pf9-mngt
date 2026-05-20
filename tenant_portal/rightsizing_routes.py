"""
rightsizing_routes.py — Tenant Portal right-sizing endpoints.

Returns right-sizing recommendations scoped to the authenticated tenant's
own projects. Tenants cannot see recommendations for other tenants.

Endpoints:
  GET /tenant/rightsizing/summary         — aggregated savings summary
  GET /tenant/rightsizing/recommendations — list of recommendations (own VMs)
  PATCH /tenant/rightsizing/{rec_id}      — dismiss or snooze a recommendation
  POST /tenant/rightsizing/{rec_id}/request-change — request MSP to action resize
"""

import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars
from tenant_context import TenantContext
from audit_helper import log_action_bare

logger = logging.getLogger("tenant_portal.rightsizing")

router = APIRouter(tags=["rightsizing"])

_HOURS_PER_MONTH = 730.0

# Internal API (same cluster) — used to create support tickets
_INTERNAL_API_URL      = os.getenv("INTERNAL_API_URL", "http://pf9_api:8000")
_INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")
# Department to route rightsizing tickets to (configurable)
_RIGHTSIZING_DEPT      = os.getenv("RIGHTSIZING_TICKET_DEPT", "Tier3 Support")


def _load_flavor_prices(conn) -> Dict[str, float]:
    """Load per-flavor hourly costs. metering_pricing takes precedence over metering_flavor_pricing."""
    prices: Dict[str, float] = {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        try:
            cur.execute("SELECT flavor_name, cost_per_hour FROM metering_flavor_pricing")
            for r in cur.fetchall():
                if r["flavor_name"]:
                    prices[r["flavor_name"]] = float(r["cost_per_hour"] or 0)
        except Exception:
            pass
        try:
            cur.execute(
                "SELECT item_name, cost_per_hour FROM metering_pricing WHERE category = 'flavor'"
            )
            for r in cur.fetchall():
                if r["item_name"]:
                    prices[r["item_name"]] = float(r["cost_per_hour"] or 0)
        except Exception:
            pass
    return prices


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TenantRightsizingRecommendation(BaseModel):
    id: int
    vm_id: str
    vm_name: Optional[str]
    project_name: Optional[str]
    region_id: Optional[str]
    classification: str
    current_flavor: Optional[str]
    current_vcpus: Optional[int]
    current_ram_mb: Optional[int]
    recommended_flavor: Optional[str]
    recommended_vcpus: Optional[int]
    recommended_ram_mb: Optional[int]
    cpu_p95_7d: Optional[float]
    ram_p95_7d: Optional[float]
    estimated_monthly_savings_usd: Optional[float]
    current_monthly_cost: Optional[float]
    recommended_monthly_cost: Optional[float]
    currency: str
    status: str
    computed_at: str


class TenantRightsizingSummary(BaseModel):
    total_open: int
    idle_count: int
    over_provisioned_count: int
    total_estimated_savings_usd: float
    currency: str


class TenantStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(snoozed|dismissed)$")
    snooze_until: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /tenant/rightsizing/summary
# ---------------------------------------------------------------------------

@router.get("/tenant/rightsizing/summary", response_model=TenantRightsizingSummary)
async def get_tenant_rightsizing_summary(
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """Aggregated right-sizing savings summary for this tenant."""
    if not tenant_ctx.project_ids:
        return TenantRightsizingSummary(
            total_open=0, idle_count=0, over_provisioned_count=0,
            total_estimated_savings_usd=0.0, currency="USD",
        )

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, tenant_ctx)
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE r.status IN ('open','snoozed'))             AS total_open,
                    COUNT(*) FILTER (WHERE r.classification = 'idle'
                                      AND r.status IN ('open','snoozed'))              AS idle_count,
                    COUNT(*) FILTER (WHERE r.classification = 'over_provisioned'
                                      AND r.status IN ('open','snoozed'))              AS over_provisioned_count,
                    COALESCE(SUM(r.estimated_monthly_savings_usd)
                        FILTER (WHERE r.status IN ('open','snoozed')), 0)              AS total_savings,
                    MAX(r.currency)                                                    AS currency
                FROM rightsizing_recommendations r
                JOIN servers s ON s.id = r.vm_id
                WHERE s.project_id = ANY(%s)
            """, (tenant_ctx.project_ids,))
            row = cur.fetchone()

    if not row:
        return TenantRightsizingSummary(
            total_open=0, idle_count=0, over_provisioned_count=0,
            total_estimated_savings_usd=0.0, currency="USD",
        )
    return TenantRightsizingSummary(
        total_open=int(row["total_open"] or 0),
        idle_count=int(row["idle_count"] or 0),
        over_provisioned_count=int(row["over_provisioned_count"] or 0),
        total_estimated_savings_usd=float(row["total_savings"] or 0),
        currency=row["currency"] or "USD",
    )


# ---------------------------------------------------------------------------
# GET /tenant/rightsizing/recommendations
# ---------------------------------------------------------------------------

@router.get("/tenant/rightsizing/recommendations", response_model=List[TenantRightsizingRecommendation])
async def list_tenant_recommendations(
    rec_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """List right-sizing recommendations for this tenant's VMs."""
    if not tenant_ctx.project_ids:
        return []

    status_filter = "AND r.status IN ('open', 'snoozed')"
    params: list = [tenant_ctx.project_ids]
    if rec_status:
        allowed = {"open", "snoozed", "dismissed", "actioned"}
        if rec_status not in allowed:
            raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")
        status_filter = "AND r.status = %s"
        params.append(rec_status)

    params.extend([limit, offset])

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, tenant_ctx)
            cur.execute(f"""
                SELECT r.*
                FROM rightsizing_recommendations r
                JOIN servers s ON s.id = r.vm_id
                WHERE s.project_id = ANY(%s)
                {status_filter}
                ORDER BY r.estimated_monthly_savings_usd DESC NULLS LAST,
                         r.computed_at DESC
                LIMIT %s OFFSET %s
            """, params)  # nosec B608 — status_filter is a hardcoded SQL fragment, not user input
            rows = cur.fetchall()
        flavor_prices = _load_flavor_prices(conn)

    def _monthly(flavor: Optional[str]) -> Optional[float]:
        if not flavor:
            return None
        p = flavor_prices.get(flavor)
        return round(p * _HOURS_PER_MONTH, 2) if p else None

    return [
        TenantRightsizingRecommendation(
            id=r["id"],
            vm_id=r["vm_id"],
            vm_name=r["vm_name"],
            project_name=r["project_name"],
            region_id=r["region_id"],
            classification=r["classification"],
            current_flavor=r["current_flavor"],
            current_vcpus=r["current_vcpus"],
            current_ram_mb=r["current_ram_mb"],
            recommended_flavor=r["recommended_flavor"],
            recommended_vcpus=r["recommended_vcpus"],
            recommended_ram_mb=r["recommended_ram_mb"],
            cpu_p95_7d=float(r["cpu_p95_7d"]) if r["cpu_p95_7d"] is not None else None,
            ram_p95_7d=float(r["ram_p95_7d"]) if r["ram_p95_7d"] is not None else None,
            estimated_monthly_savings_usd=(
                float(r["estimated_monthly_savings_usd"])
                if r["estimated_monthly_savings_usd"] is not None else None
            ),
            current_monthly_cost=_monthly(r["current_flavor"]),
            recommended_monthly_cost=_monthly(r["recommended_flavor"]),
            currency=r["currency"] or "USD",
            status=r["status"],
            computed_at=r["computed_at"].isoformat() if r["computed_at"] else "",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# PATCH /tenant/rightsizing/{rec_id}
# ---------------------------------------------------------------------------

@router.patch("/tenant/rightsizing/{rec_id}", status_code=200)
async def update_tenant_recommendation(
    rec_id: int,
    body: TenantStatusUpdate,
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """Tenants can dismiss or snooze their own recommendations."""
    snooze_dt = None
    if body.snooze_until:
        try:
            snooze_dt = datetime.fromisoformat(body.snooze_until.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid snooze_until datetime format")

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, tenant_ctx)
            # Verify ownership: recommendation must belong to this tenant's VMs
            cur.execute("""
                SELECT r.id
                FROM rightsizing_recommendations r
                JOIN servers s ON s.id = r.vm_id
                WHERE r.id = %s AND s.project_id = ANY(%s)
            """, (rec_id, tenant_ctx.project_ids))
            rec = cur.fetchone()
            if not rec:
                raise HTTPException(
                    status_code=404,
                    detail="Recommendation not found or not accessible",
                )

            cur.execute("""
                UPDATE rightsizing_recommendations
                SET status = %s,
                    snooze_until = %s,
                    updated_at   = NOW()
                WHERE id = %s
            """, (body.status, snooze_dt, rec_id))
        conn.commit()

    log_action_bare(
        project_id=tenant_ctx.project_ids[0] if tenant_ctx.project_ids else None,
        action=f"rightsizing_{body.status}",
        details={"recommendation_id": rec_id},
    )

    return {"message": f"Recommendation {rec_id} updated to {body.status}"}


# ---------------------------------------------------------------------------
# POST /tenant/rightsizing/{rec_id}/request-change
# ---------------------------------------------------------------------------

@router.post("/tenant/rightsizing/{rec_id}/request-change", status_code=200)
async def request_rightsizing_change(
    rec_id: int,
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Tenant requests the MSP to action a rightsizing recommendation.
    - Marks the recommendation as actioned in the DB.
    - Opens a support ticket in the admin portal (via internal API).
    - The assigned department receives an email notification with full details.
    """
    if not tenant_ctx.project_ids:
        raise HTTPException(status_code=403, detail="No project access")

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            inject_rls_vars(cur, tenant_ctx)

            # Verify ownership
            cur.execute("""
                SELECT r.id, r.vm_name, r.vm_id, r.project_name, r.region_id,
                       r.current_flavor, r.recommended_flavor,
                       r.current_vcpus, r.current_ram_mb,
                       r.recommended_vcpus, r.recommended_ram_mb,
                       r.cpu_p95_7d, r.ram_p95_7d,
                       r.estimated_monthly_savings_usd, r.currency, r.status
                FROM rightsizing_recommendations r
                JOIN servers s ON s.id = r.vm_id
                WHERE r.id = %s AND s.project_id = ANY(%s)
            """, (rec_id, tenant_ctx.project_ids))
            rec = cur.fetchone()
            if not rec:
                raise HTTPException(
                    status_code=404,
                    detail="Recommendation not found or not accessible",
                )
            if rec["status"] == "actioned":
                return {"message": "Recommendation already actioned"}

            # Mark as actioned
            cur.execute("""
                UPDATE rightsizing_recommendations
                SET status = 'actioned',
                    actioned_at = NOW(),
                    actioned_by = 'tenant_request',
                    updated_at  = NOW()
                WHERE id = %s
            """, (rec_id,))
        conn.commit()

    log_action_bare(
        tenant_ctx,
        "rightsizing_change_requested",
        resource_type="rightsizing_recommendation",
        resource_id=str(rec_id),
        project_id=tenant_ctx.project_ids[0] if tenant_ctx.project_ids else None,
        details={"recommendation_id": rec_id, "vm_name": rec.get("vm_name")},
    )

    # ── Open a support ticket in the admin portal ─────────────────────────
    ticket_ref: Optional[str] = None
    vm_label    = rec["vm_name"] or rec["vm_id"]
    cur_flavor  = rec["current_flavor"] or "—"
    rec_flavor  = rec["recommended_flavor"] or "—"
    savings     = rec["estimated_monthly_savings_usd"]
    currency    = rec["currency"] or "USD"
    savings_str = f"{currency} {float(savings):.0f}/mo" if savings else "unknown"

    priority = "high" if (savings and float(savings) >= 100) else "normal"

    ticket_title = (
        f"Right-Sizing Request: {vm_label} "
        f"({cur_flavor} → {rec_flavor})"
    )
    ticket_description = (
        f"Tenant {tenant_ctx.username!r} requested a right-sizing change via the portal.\n\n"
        f"VM: {vm_label}\n"
        f"Project: {rec.get('project_name') or '—'}\n"
        f"Region: {rec.get('region_id') or 'default'}\n"
        f"Current Flavor: {cur_flavor}"
        + (f" ({rec['current_vcpus']} vCPU / {int(rec['current_ram_mb'] or 0)//1024} GB RAM)"
           if rec.get("current_vcpus") else "") + "\n"
        f"Recommended Flavor: {rec_flavor}"
        + (f" ({rec['recommended_vcpus']} vCPU / {int(rec['recommended_ram_mb'] or 0)//1024} GB RAM)"
           if rec.get("recommended_vcpus") else "") + "\n"
        f"CPU p95 (7d): {rec.get('cpu_p95_7d') or '—'}%  |  "
        f"RAM p95 (7d): {rec.get('ram_p95_7d') or '—'}%\n"
        f"Estimated Monthly Saving: {savings_str}"
    )

    # Template context for the department notification email
    dept_ctx: Dict = {
        "ticket_ref":          "",  # filled in by _auto_ticket via _render_template
        "vm_name":             vm_label,
        "project_name":        rec.get("project_name") or "—",
        "region":              rec.get("region_id") or "default",
        "current_flavor":      cur_flavor,
        "current_vcpus":       str(rec.get("current_vcpus") or "—"),
        "current_ram_gb":      str(int(rec.get("current_ram_mb") or 0) // 1024) if rec.get("current_ram_mb") else "—",
        "recommended_flavor":  rec_flavor,
        "recommended_vcpus":   str(rec.get("recommended_vcpus") or "—"),
        "recommended_ram_gb":  str(int(rec.get("recommended_ram_mb") or 0) // 1024) if rec.get("recommended_ram_mb") else "—",
        "cpu_p95":             str(round(float(rec["cpu_p95_7d"]), 1)) if rec.get("cpu_p95_7d") else "—",
        "ram_p95":             str(round(float(rec["ram_p95_7d"]), 1)) if rec.get("ram_p95_7d") else "—",
        "savings":             savings_str,
        "tenant_name":         tenant_ctx.username,
        "tenant_email":        tenant_ctx.username,
        "priority":            priority,
        "app_version":         os.getenv("APP_VERSION", "2.6.5"),
    }

    if _INTERNAL_SERVICE_SECRET:
        try:
            payload = {
                "title":         ticket_title,
                "description":   ticket_description,
                "ticket_type":   "auto_change_request",
                "priority":      priority,
                "to_dept_name":  _RIGHTSIZING_DEPT,
                "auto_source":   "tenant_rightsizing_request",
                "auto_source_id": str(rec_id),
                "resource_type": "rightsizing_recommendation",
                "resource_id":   str(rec_id),
                "resource_name": vm_label,
                "project_id":    tenant_ctx.project_ids[0] if tenant_ctx.project_ids else None,
                "project_name":  rec.get("project_name"),
                "customer_name": tenant_ctx.username,
                "customer_email": tenant_ctx.username,
                "dept_notify_template": "rightsizing_request",
                "dept_notify_context": dept_ctx,
            }
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{_INTERNAL_API_URL}/internal/tickets/auto",
                    json=payload,
                    headers={"X-Internal-Secret": _INTERNAL_SERVICE_SECRET},
                )
                resp.raise_for_status()
                ticket_ref = resp.json().get("ticket_ref")
            logger.info(
                "rightsizing_request: ticket %s created for rec %s by %s",
                ticket_ref, rec_id, tenant_ctx.username,
            )
        except Exception as exc:
            # Ticket creation is best-effort — the recommendation is already actioned
            logger.error(
                "rightsizing_request: failed to create ticket for rec %s: %s", rec_id, exc
            )
    else:
        logger.warning(
            "rightsizing_request: INTERNAL_SERVICE_SECRET not set — ticket not created for rec %s",
            rec_id,
        )

    msg = "Change request submitted successfully."
    if ticket_ref:
        msg += f" Ticket {ticket_ref} opened."
    return {"message": msg, "ticket_ref": ticket_ref}
