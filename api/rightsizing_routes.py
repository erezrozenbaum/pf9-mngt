"""
Rightsizing Routes (Admin)
==========================
Endpoints for the Workload Right-Sizing & Cost Waste Detection feature.

RBAC
----
  - admin      → rightsizing:read  (view all recommendations)
  - superadmin → rightsizing:read + rightsizing:write (dismiss / snooze)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User, get_effective_region_filter
from db_pool import get_connection

logger = logging.getLogger("pf9.rightsizing")

router = APIRouter(prefix="/api/rightsizing", tags=["rightsizing"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RightsizingRecommendation(BaseModel):
    id: int
    vm_id: str
    vm_name: Optional[str]
    project_name: Optional[str]
    region_id: Optional[str]
    domain: Optional[str]
    classification: str
    current_flavor: Optional[str]
    current_vcpus: Optional[int]
    current_ram_mb: Optional[int]
    recommended_flavor: Optional[str]
    recommended_vcpus: Optional[int]
    recommended_ram_mb: Optional[int]
    cpu_p95_7d: Optional[float]
    ram_p95_7d: Optional[float]
    cpu_avg_7d: Optional[float]
    ram_avg_7d: Optional[float]
    estimated_monthly_savings_usd: Optional[float]
    currency: str
    status: str
    computed_at: str
    updated_at: str


class RightsizingStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(snoozed|dismissed|actioned)$")
    snooze_until: Optional[str] = None  # ISO datetime string


class RightsizingSummary(BaseModel):
    total_open: int
    idle_count: int
    over_provisioned_count: int
    total_estimated_savings_usd: float
    currency: str


# ---------------------------------------------------------------------------
# GET /api/rightsizing/summary
# ---------------------------------------------------------------------------

@router.get("/summary", response_model=RightsizingSummary)
def get_rightsizing_summary(
    region: Optional[str] = Query(None),
    user: User = Depends(require_permission("rightsizing", "read")),
):
    """Returns aggregated right-sizing stats."""
    effective_region = get_effective_region_filter(user, region)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            params: list = []
            region_clause = ""
            if effective_region:
                region_clause = "AND (region_id = %s OR region_id IS NULL)"
                params.append(effective_region)

            cur.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('open','snoozed'))              AS total_open,
                    COUNT(*) FILTER (WHERE classification = 'idle'
                                      AND status IN ('open','snoozed'))               AS idle_count,
                    COUNT(*) FILTER (WHERE classification = 'over_provisioned'
                                      AND status IN ('open','snoozed'))               AS over_provisioned_count,
                    COALESCE(SUM(estimated_monthly_savings_usd)
                        FILTER (WHERE status IN ('open','snoozed')), 0)               AS total_savings,
                    MAX(currency)                                                      AS currency
                FROM rightsizing_recommendations
                WHERE 1=1 {region_clause}
            """, params)
            row = cur.fetchone()
            if not row:
                return RightsizingSummary(
                    total_open=0, idle_count=0, over_provisioned_count=0,
                    total_estimated_savings_usd=0.0, currency="USD",
                )
            return RightsizingSummary(
                total_open=int(row["total_open"] or 0),
                idle_count=int(row["idle_count"] or 0),
                over_provisioned_count=int(row["over_provisioned_count"] or 0),
                total_estimated_savings_usd=float(row["total_savings"] or 0),
                currency=row["currency"] or "USD",
            )


# ---------------------------------------------------------------------------
# GET /api/rightsizing/recommendations
# ---------------------------------------------------------------------------

@router.get("/recommendations", response_model=List[RightsizingRecommendation])
def list_recommendations(
    region: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    rec_status: Optional[str] = Query(None, alias="status"),
    project: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("rightsizing", "read")),
):
    """List right-sizing recommendations with optional filters."""
    effective_region = get_effective_region_filter(user, region)
    filters: list = []
    params: list = []

    if effective_region:
        filters.append("(r.region_id = %s OR r.region_id IS NULL)")
        params.append(effective_region)
    if classification and classification in ("idle", "over_provisioned", "right_sized", "under_provisioned"):
        filters.append("r.classification = %s")
        params.append(classification)
    if rec_status:
        allowed = {"open", "snoozed", "dismissed", "actioned"}
        if rec_status not in allowed:
            raise HTTPException(status_code=400, detail=f"status must be one of {allowed}")
        filters.append("r.status = %s")
        params.append(rec_status)
    else:
        # Default: only open/snoozed
        filters.append("r.status IN ('open', 'snoozed')")
    if project:
        filters.append("r.project_name ILIKE %s")
        params.append(f"%{project}%")

    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params.extend([limit, offset])

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT r.*
                FROM rightsizing_recommendations r
                {where}
                ORDER BY r.estimated_monthly_savings_usd DESC NULLS LAST,
                         r.computed_at DESC
                LIMIT %s OFFSET %s
            """, params)
            rows = cur.fetchall()

    return [
        RightsizingRecommendation(
            id=r["id"],
            vm_id=r["vm_id"],
            vm_name=r["vm_name"],
            project_name=r["project_name"],
            region_id=r["region_id"],
            domain=r["domain"],
            classification=r["classification"],
            current_flavor=r["current_flavor"],
            current_vcpus=r["current_vcpus"],
            current_ram_mb=r["current_ram_mb"],
            recommended_flavor=r["recommended_flavor"],
            recommended_vcpus=r["recommended_vcpus"],
            recommended_ram_mb=r["recommended_ram_mb"],
            cpu_p95_7d=float(r["cpu_p95_7d"]) if r["cpu_p95_7d"] is not None else None,
            ram_p95_7d=float(r["ram_p95_7d"]) if r["ram_p95_7d"] is not None else None,
            cpu_avg_7d=float(r["cpu_avg_7d"]) if r["cpu_avg_7d"] is not None else None,
            ram_avg_7d=float(r["ram_avg_7d"]) if r["ram_avg_7d"] is not None else None,
            estimated_monthly_savings_usd=(
                float(r["estimated_monthly_savings_usd"])
                if r["estimated_monthly_savings_usd"] is not None else None
            ),
            currency=r["currency"] or "USD",
            status=r["status"],
            computed_at=r["computed_at"].isoformat() if r["computed_at"] else "",
            updated_at=r["updated_at"].isoformat() if r["updated_at"] else "",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# PATCH /api/rightsizing/recommendations/{rec_id}
# ---------------------------------------------------------------------------

@router.patch("/recommendations/{rec_id}", status_code=200)
def update_recommendation_status(
    rec_id: int,
    body: RightsizingStatusUpdate,
    user: User = Depends(require_permission("rightsizing", "write")),
):
    """Dismiss, snooze, or mark a recommendation as actioned."""
    snooze_dt = None
    if body.snooze_until:
        try:
            snooze_dt = datetime.fromisoformat(body.snooze_until.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid snooze_until datetime format")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT id, status FROM rightsizing_recommendations WHERE id = %s",
                (rec_id,),
            )
            rec = cur.fetchone()
            if not rec:
                raise HTTPException(status_code=404, detail="Recommendation not found")

            cur.execute("""
                UPDATE rightsizing_recommendations
                SET status = %s,
                    snooze_until = %s,
                    actioned_at  = CASE WHEN %s = 'actioned' THEN NOW() ELSE actioned_at END,
                    actioned_by  = CASE WHEN %s = 'actioned' THEN %s ELSE actioned_by END,
                    updated_at   = NOW()
                WHERE id = %s
            """, (
                body.status, snooze_dt,
                body.status, body.status, user.username,
                rec_id,
            ))
        conn.commit()

    return {"message": f"Recommendation {rec_id} updated to {body.status}"}
