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
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars
from tenant_context import TenantContext
from audit_helper import log_action_bare

logger = logging.getLogger("tenant_portal.rightsizing")

router = APIRouter(tags=["rightsizing"])


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
        inject_rls_vars(conn, tenant_ctx)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
        inject_rls_vars(conn, tenant_ctx)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT r.*
                FROM rightsizing_recommendations r
                JOIN servers s ON s.id = r.vm_id
                WHERE s.project_id = ANY(%s)
                {status_filter}
                ORDER BY r.estimated_monthly_savings_usd DESC NULLS LAST,
                         r.computed_at DESC
                LIMIT %s OFFSET %s
            """, params)
            rows = cur.fetchall()

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
        inject_rls_vars(conn, tenant_ctx)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
