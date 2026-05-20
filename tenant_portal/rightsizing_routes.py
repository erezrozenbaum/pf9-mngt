"""
rightsizing_routes.py — Tenant Portal right-sizing endpoints.

Returns right-sizing recommendations scoped to the authenticated tenant's
own projects. Tenants cannot see recommendations for other tenants.

Endpoints:
  GET /tenant/rightsizing/summary         — aggregated savings summary
  GET /tenant/rightsizing/recommendations — list of recommendations (own VMs)
  PATCH /tenant/rightsizing/{rec_id}      — dismiss or snooze a recommendation
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

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
    Sends an email to the configured support address and marks the
    recommendation as actioned.
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

            # Load support email from branding
            cur.execute(
                "SELECT support_email, company_name FROM tenant_portal_branding WHERE control_plane_id = %s LIMIT 1",
                (tenant_ctx.control_plane_id,)
            )
            branding = cur.fetchone() or {}
            support_email = branding.get("support_email")
            company_name = branding.get("company_name") or "Cloud Portal"

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

    if not support_email:
        # No support email configured — still succeed (request is logged)
        return {"message": "Request logged. No support email configured."}

    # Build email
    vm_label = rec["vm_name"] or rec["vm_id"]
    cur_flavor = rec["current_flavor"] or "—"
    rec_flavor = rec["recommended_flavor"] or "—"
    savings = rec["estimated_monthly_savings_usd"]
    currency = rec["currency"] or "USD"
    savings_str = (
        f"{currency} {float(savings):.0f}/mo" if savings else "unknown"
    )

    subject = f"[{company_name}] Resize Request: {vm_label} ({rec.get('project_name') or 'unknown project'})"
    body_html = f"""
<p>A tenant has submitted a right-sizing change request via <strong>{company_name}</strong> Cloud Portal.</p>
<table cellpadding="6" cellspacing="0" border="0" style="font-family:sans-serif;font-size:14px">
  <tr><td style="color:#6b7280">VM</td><td><strong>{vm_label}</strong></td></tr>
  <tr><td style="color:#6b7280">Project</td><td>{rec.get("project_name") or "—"}</td></tr>
  <tr><td style="color:#6b7280">Region</td><td>{rec.get("region_id") or "default"}</td></tr>
  <tr><td style="color:#6b7280">Current Flavor</td><td>{cur_flavor}
    {f"({rec['current_vcpus']} vCPU / {int(rec['current_ram_mb'] or 0)//1024} GB RAM)" if rec.get("current_vcpus") else ""}</td></tr>
  <tr><td style="color:#6b7280">Recommended Flavor</td><td style="color:#16a34a"><strong>{rec_flavor}</strong>
    {f"({rec['recommended_vcpus']} vCPU / {int(rec['recommended_ram_mb'] or 0)//1024} GB RAM)" if rec.get("recommended_vcpus") else ""}</td></tr>
  <tr><td style="color:#6b7280">Est. Monthly Saving</td><td style="color:#16a34a;font-weight:bold">{savings_str}</td></tr>
</table>
<p style="margin-top:1.2em">Please review and action this request at your earliest convenience.</p>
"""

    try:
        import sys
        import importlib
        _smtp = importlib.import_module("smtp_helper") if "smtp_helper" in sys.modules else None
        if not _smtp:
            try:
                _smtp = importlib.import_module("smtp_helper")
            except ImportError:
                _smtp = None
        if _smtp:
            _smtp.send_email(support_email, subject, body_html)
        else:
            import os
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            smtp_host = os.getenv("SMTP_HOST", "")
            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_user = os.getenv("SMTP_USER", "")
            smtp_pass = os.getenv("SMTP_PASSWORD", "")
            smtp_from = os.getenv("SMTP_FROM", smtp_user)
            if smtp_host:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = smtp_from
                msg["To"] = support_email
                msg.attach(MIMEText(body_html, "html"))
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    if smtp_user and smtp_pass:
                        server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_from, [support_email], msg.as_string())
    except Exception as exc:
        logger.error("Failed to send resize request email to %s: %s", support_email, exc)
        # Request is already actioned/logged — don't fail the whole response

    return {"message": "Change request submitted successfully"}
