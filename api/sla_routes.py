"""
SLA Compliance Routes
=====================
Endpoints for managing SLA commitments and viewing compliance history.

RBAC
----
  GET  endpoints — sla:read  (viewer, operator, admin, superadmin)
  PUT  endpoints — sla:write (admin, superadmin)
  POST endpoints — sla:write (admin, superadmin)
"""
from __future__ import annotations

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User
from db_pool import get_connection

logger = logging.getLogger("pf9.sla")

router = APIRouter(prefix="/api/sla", tags=["sla"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class SlaCommitmentIn(BaseModel):
    tier: str = Field("custom", description="bronze | silver | gold | custom")
    uptime_pct: Optional[float] = None
    rto_hours: Optional[int] = None
    rpo_hours: Optional[int] = None
    mtta_hours: Optional[int] = None
    mttr_hours: Optional[int] = None
    backup_freq_hours: int = 24
    effective_from: Optional[str] = None   # ISO date string; defaults to today
    region_id: Optional[str] = None
    notes: Optional[str] = None


class SlaCommitmentOut(BaseModel):
    tenant_id: str
    tier: str
    uptime_pct: Optional[float]
    rto_hours: Optional[int]
    rpo_hours: Optional[int]
    mtta_hours: Optional[int]
    mttr_hours: Optional[int]
    backup_freq_hours: int
    effective_from: str
    effective_to: Optional[str]
    region_id: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str


class SlaComplianceRow(BaseModel):
    tenant_id: str
    month: str
    region_id: str
    uptime_actual_pct: Optional[float]
    rto_worst_hours: Optional[float]
    rpo_worst_hours: Optional[float]
    mtta_avg_hours: Optional[float]
    mttr_avg_hours: Optional[float]
    backup_success_pct: Optional[float]
    breach_fields: List[str]
    at_risk_fields: List[str]
    computed_at: str


class SlaSummaryRow(BaseModel):
    tenant_id: str
    tenant_name: str
    tier: str
    breach_fields: List[str]
    at_risk_fields: List[str]
    overall_status: str   # ok | at_risk | breached | not_configured


class SlaTierTemplate(BaseModel):
    tier: str
    display_name: str
    uptime_pct: Optional[float]
    rto_hours: Optional[int]
    rpo_hours: Optional[int]
    mtta_hours: Optional[int]
    mttr_hours: Optional[int]
    backup_freq_hours: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_commitment(row: dict) -> dict:
    return {
        "tenant_id":         row["tenant_id"],
        "tier":              row["tier"],
        "uptime_pct":        float(row["uptime_pct"]) if row.get("uptime_pct") is not None else None,
        "rto_hours":         row.get("rto_hours"),
        "rpo_hours":         row.get("rpo_hours"),
        "mtta_hours":        row.get("mtta_hours"),
        "mttr_hours":        row.get("mttr_hours"),
        "backup_freq_hours": row.get("backup_freq_hours", 24),
        "effective_from":    str(row["effective_from"]),
        "effective_to":      str(row["effective_to"]) if row.get("effective_to") else None,
        "region_id":         row.get("region_id"),
        "notes":             row.get("notes"),
        "created_at":        row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at":        row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


def _row_to_compliance(row: dict) -> dict:
    return {
        "tenant_id":          row["tenant_id"],
        "month":              str(row["month"]),
        "region_id":          row.get("region_id", ""),
        "uptime_actual_pct":  float(row["uptime_actual_pct"]) if row.get("uptime_actual_pct") is not None else None,
        "rto_worst_hours":    float(row["rto_worst_hours"]) if row.get("rto_worst_hours") is not None else None,
        "rpo_worst_hours":    float(row["rpo_worst_hours"]) if row.get("rpo_worst_hours") is not None else None,
        "mtta_avg_hours":     float(row["mtta_avg_hours"]) if row.get("mtta_avg_hours") is not None else None,
        "mttr_avg_hours":     float(row["mttr_avg_hours"]) if row.get("mttr_avg_hours") is not None else None,
        "backup_success_pct": float(row["backup_success_pct"]) if row.get("backup_success_pct") is not None else None,
        "breach_fields":      row.get("breach_fields") or [],
        "at_risk_fields":     row.get("at_risk_fields") or [],
        "computed_at":        row["computed_at"].isoformat() if row.get("computed_at") else None,
    }


# ---------------------------------------------------------------------------
# GET /api/sla/tiers — list tier templates
# ---------------------------------------------------------------------------

@router.get("/tiers")
def get_sla_tiers(
    _user: User = Depends(require_permission("sla", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT tier, display_name, uptime_pct, rto_hours, rpo_hours,
                       mtta_hours, mttr_hours, backup_freq_hours
                FROM sla_tier_templates
                ORDER BY
                    CASE tier WHEN 'gold' THEN 1 WHEN 'silver' THEN 2
                               WHEN 'bronze' THEN 3 ELSE 4 END
            """)
            rows = cur.fetchall()
    return {"tiers": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# GET /api/sla/commitments/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/commitments/{tenant_id}")
def get_commitment(
    tenant_id: str,
    _user: User = Depends(require_permission("sla", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT sc.*, p.name AS tenant_name
                FROM sla_commitments sc
                JOIN projects p ON p.id = sc.tenant_id
                WHERE sc.tenant_id = %s
                ORDER BY sc.effective_from DESC
                LIMIT 1
            """, (tenant_id,))
            row = cur.fetchone()

    if not row:
        return {"commitment": None}
    return {"commitment": _row_to_commitment(dict(row))}


# ---------------------------------------------------------------------------
# PUT /api/sla/commitments/{tenant_id} — create or update
# ---------------------------------------------------------------------------

@router.put("/commitments/{tenant_id}", status_code=status.HTTP_200_OK)
def upsert_commitment(
    tenant_id: str,
    body: SlaCommitmentIn,
    user: User = Depends(require_permission("sla", "write")),
):
    from datetime import date
    effective_from = body.effective_from or date.today().isoformat()

    with get_connection() as conn:
        # Verify tenant exists
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s", (tenant_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Tenant not found")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO sla_commitments
                    (tenant_id, tier, uptime_pct, rto_hours, rpo_hours,
                     mtta_hours, mttr_hours, backup_freq_hours,
                     effective_from, region_id, notes, updated_at)
                VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (tenant_id, effective_from)
                DO UPDATE SET
                    tier              = EXCLUDED.tier,
                    uptime_pct        = EXCLUDED.uptime_pct,
                    rto_hours         = EXCLUDED.rto_hours,
                    rpo_hours         = EXCLUDED.rpo_hours,
                    mtta_hours        = EXCLUDED.mtta_hours,
                    mttr_hours        = EXCLUDED.mttr_hours,
                    backup_freq_hours = EXCLUDED.backup_freq_hours,
                    region_id         = EXCLUDED.region_id,
                    notes             = EXCLUDED.notes,
                    updated_at        = NOW()
                RETURNING *
            """, (
                tenant_id, body.tier, body.uptime_pct, body.rto_hours,
                body.rpo_hours, body.mtta_hours, body.mttr_hours,
                body.backup_freq_hours, effective_from,
                body.region_id, body.notes,
            ))
            row = cur.fetchone()
            conn.commit()

    logger.info("SLA commitment upserted for tenant %s by %s", tenant_id, user["username"])
    return {"commitment": _row_to_commitment(dict(row))}


# ---------------------------------------------------------------------------
# GET /api/sla/compliance/summary — all tenants, current month
# NOTE: must be registered BEFORE /compliance/{tenant_id} or FastAPI will
#       match "summary" as a tenant_id path parameter.
# ---------------------------------------------------------------------------

@router.get("/compliance/summary")
def get_compliance_summary(
    _user: User = Depends(require_permission("sla", "read")),
):
    from datetime import date
    month_start = date.today().replace(day=1)

    with get_connection() as conn:
        # All projects with their commitment status
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    p.id AS tenant_id,
                    p.name AS tenant_name,
                    sc.tier,
                    cm.breach_fields,
                    cm.at_risk_fields
                FROM projects p
                LEFT JOIN sla_commitments sc ON sc.tenant_id = p.id
                    AND sc.effective_to IS NULL
                LEFT JOIN sla_compliance_monthly cm ON cm.tenant_id = p.id
                    AND cm.month = %s AND cm.region_id = ''
                ORDER BY p.name ASC
            """, (month_start,))
            rows = cur.fetchall()

    results = []
    for row in rows:
        breach = row.get("breach_fields") or []
        at_risk = row.get("at_risk_fields") or []
        if not row.get("tier"):
            overall = "not_configured"
        elif breach:
            overall = "breached"
        elif at_risk:
            overall = "at_risk"
        else:
            overall = "ok"
        results.append({
            "tenant_id":     row["tenant_id"],
            "tenant_name":   row["tenant_name"] or row["tenant_id"],
            "tier":          row.get("tier") or "none",
            "breach_fields": breach,
            "at_risk_fields": at_risk,
            "overall_status": overall,
        })

    return {"summary": results, "month": str(month_start)}


# ---------------------------------------------------------------------------
# GET /api/sla/compliance/{tenant_id} — per-tenant monthly history
# NOTE: registered AFTER /compliance/summary to avoid path-param shadowing.
# ---------------------------------------------------------------------------

@router.get("/compliance/{tenant_id}")
def get_compliance_history(
    tenant_id: str,
    months: int = Query(12, ge=1, le=36),
    region_id: Optional[str] = Query(None),
    _user: User = Depends(require_permission("sla", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            args = [tenant_id, months]
            region_filter = ""
            if region_id is not None:
                region_filter = "AND region_id = %s"
                args.append(region_id)
            cur.execute(f"""
                SELECT *
                FROM sla_compliance_monthly
                WHERE tenant_id = %s
                ORDER BY month DESC
                LIMIT %s
                {region_filter}
            """, args)
            rows = cur.fetchall()

    return {"history": [_row_to_compliance(dict(r)) for r in rows]}


# ---------------------------------------------------------------------------
# POST /api/sla/compliance/report/{tenant_id} — PDF compliance report
# ---------------------------------------------------------------------------

@router.post("/compliance/report/{tenant_id}")
def generate_compliance_report(
    tenant_id: str,
    from_month: Optional[str] = Query(None, description="YYYY-MM-DD (first of month)"),
    to_month: Optional[str] = Query(None, description="YYYY-MM-DD (first of month)"),
    _user: User = Depends(require_permission("sla", "read")),
):
    from datetime import date
    today = date.today()
    if not to_month:
        to_month = today.replace(day=1).isoformat()
    if not from_month:
        # Default: last 12 months
        y, m = today.year, today.month - 11
        while m <= 0:
            m += 12
            y -= 1
        from_month = date(y, m, 1).isoformat()

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Tenant info + commitment
            cur.execute("""
                SELECT p.name AS tenant_name, sc.tier, sc.uptime_pct,
                       sc.rto_hours, sc.rpo_hours, sc.mtta_hours, sc.mttr_hours
                FROM projects p
                LEFT JOIN sla_commitments sc ON sc.tenant_id = p.id
                    AND sc.effective_to IS NULL
                WHERE p.id = %s
            """, (tenant_id,))
            tenant = cur.fetchone()

        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM sla_compliance_monthly
                WHERE tenant_id = %s
                  AND month >= %s AND month <= %s
                  AND region_id = ''
                ORDER BY month ASC
            """, (tenant_id, from_month, to_month))
            history = [dict(r) for r in cur.fetchall()]

    try:
        from export_reports import generate_sla_report
        pdf_bytes = generate_sla_report(tenant_id, dict(tenant), history, from_month, to_month)
    except Exception as exc:
        logger.error("PDF generation failed for %s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="PDF generation failed")

    filename = f"sla_compliance_{tenant_id}_{from_month[:7]}_{to_month[:7]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



