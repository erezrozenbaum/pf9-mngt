"""
QBR (Quarterly Business Review) Generator
==========================================
Aggregates resolved insights for a tenant over a date window and produces a
PDF executive summary using the export_reports ReportLab pipeline.

RBAC
----
  GET  endpoints — qbr:read  (operator, admin, superadmin)
  POST endpoints — qbr:write (admin, superadmin)
  PUT  endpoints — qbr:write (superadmin only for labor rates)
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from db_pool import get_connection

logger = logging.getLogger("pf9.qbr")

router = APIRouter(prefix="/api/intelligence/qbr", tags=["qbr"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LaborRateIn(BaseModel):
    hours_saved:   float = Field(..., ge=0, le=999)
    rate_per_hour: float = Field(..., ge=0, le=99999)
    description:   Optional[str] = None


class LaborRateOut(BaseModel):
    insight_type:  str
    hours_saved:   float
    rate_per_hour: float
    description:   Optional[str]


class QbrGenerateRequest(BaseModel):
    from_date: str   # ISO date: YYYY-MM-DD
    to_date:   str   # ISO date: YYYY-MM-DD
    include_sections: List[str] = Field(
        default_factory=lambda: [
            "cover", "executive_summary", "interventions",
            "health_trend", "open_items", "methodology",
        ]
    )
    region_id: Optional[str] = None


# ---------------------------------------------------------------------------
# GET /api/intelligence/qbr/labor-rates
# ---------------------------------------------------------------------------

@router.get("/labor-rates")
def list_labor_rates(
    _user: User = Depends(require_permission("qbr", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT insight_type, hours_saved, rate_per_hour, description
                FROM msp_labor_rates
                ORDER BY insight_type
            """)
            rows = cur.fetchall()
    return {"rates": [dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# PUT /api/intelligence/qbr/labor-rates/{insight_type}
# ---------------------------------------------------------------------------

@router.put("/labor-rates/{insight_type}", status_code=status.HTTP_200_OK)
def update_labor_rate(
    insight_type: str,
    body: LaborRateIn,
    user: User = Depends(require_permission("qbr", "write")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO msp_labor_rates (insight_type, hours_saved, rate_per_hour, description)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (insight_type)
                DO UPDATE SET
                    hours_saved   = EXCLUDED.hours_saved,
                    rate_per_hour = EXCLUDED.rate_per_hour,
                    description   = EXCLUDED.description
                RETURNING *
            """, (insight_type, body.hours_saved, body.rate_per_hour, body.description))
            row = cur.fetchone()
            conn.commit()

    logger.info("Labor rate updated: %s by %s", insight_type, user["username"])
    return {"rate": dict(row)}


# ---------------------------------------------------------------------------
# GET /api/intelligence/qbr/preview/{tenant_id}
# ---------------------------------------------------------------------------

@router.get("/preview/{tenant_id}")
def qbr_preview(
    tenant_id: str,
    from_date: str = Query(
        default=None,
        description="YYYY-MM-DD (default: 90 days ago)",
    ),
    to_date: str = Query(
        default=None,
        description="YYYY-MM-DD (default: today)",
    ),
    region_id: Optional[str] = Query(None),
    _user: User = Depends(require_permission("qbr", "read")),
):
    today = date.today()
    _from = from_date or (today - timedelta(days=90)).isoformat()
    _to   = to_date   or today.isoformat()

    data = _build_qbr_data(tenant_id, _from, _to, region_id)
    return data


# ---------------------------------------------------------------------------
# POST /api/intelligence/qbr/generate/{tenant_id}
# ---------------------------------------------------------------------------

@router.post("/generate/{tenant_id}")
def qbr_generate(
    tenant_id: str,
    body: QbrGenerateRequest,
    user: User = Depends(require_permission("qbr", "write")),
):
    data = _build_qbr_data(tenant_id, body.from_date, body.to_date, body.region_id)

    try:
        from export_reports import generate_qbr_pdf
        pdf_bytes = generate_qbr_pdf(data, include_sections=body.include_sections)
    except Exception as exc:
        logger.error("QBR PDF generation failed for %s: %s", tenant_id, exc)
        raise HTTPException(status_code=500, detail="PDF generation failed")

    tenant_name_safe = (data["tenant_name"] or tenant_id).replace(" ", "_")
    filename = f"qbr_{tenant_name_safe}_{body.from_date}_{body.to_date}.pdf"
    logger.info("QBR PDF generated for tenant %s by %s", tenant_id, user["username"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Internal helper — build QBR data dict
# ---------------------------------------------------------------------------

def _build_qbr_data(
    tenant_id: str,
    from_date: str,
    to_date: str,
    region_id: Optional[str],
) -> dict:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Tenant name
            cur.execute("SELECT id, name FROM projects WHERE id = %s", (tenant_id,))
            tenant_row = cur.fetchone()
        if not tenant_row:
            raise HTTPException(status_code=404, detail="Tenant not found")

        tenant_name = tenant_row["name"] or tenant_id

        # Labor rates
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT insight_type, hours_saved, rate_per_hour FROM msp_labor_rates")
            rates = {r["insight_type"]: r for r in cur.fetchall()}

        # Resolved insights within the date window for this tenant
        region_filter = ""
        params: list = [tenant_id, from_date, to_date]
        if region_id:
            region_filter = "AND metadata->>'entity_region' = %s"
            params.append(region_id)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""  # nosec B608
                SELECT id, type, severity, title, metadata, resolved_at
                FROM operational_insights
                WHERE entity_id = %s
                  AND status = 'resolved'
                  AND resolved_at >= %s
                  AND resolved_at <= %s
                  {region_filter}
                ORDER BY resolved_at DESC
            """, params)
            resolved_insights = [dict(r) for r in cur.fetchall()]

        # Current open high/critical insights
        open_params: list = [tenant_id]
        open_region = ""
        if region_id:
            open_region = "AND metadata->>'entity_region' = %s"
            open_params.append(region_id)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""  # nosec B608
                SELECT id, type, severity, title, last_seen_at
                FROM operational_insights
                WHERE entity_id = %s
                  AND status IN ('open','acknowledged','snoozed')
                  AND severity IN ('critical','high')
                  {open_region}
                ORDER BY CASE severity WHEN 'critical' THEN 1 ELSE 2 END, last_seen_at DESC
                LIMIT 10
            """, open_params)
            open_items = [dict(r) for r in cur.fetchall()]

        # SLA commitment for this tenant
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT tier, uptime_pct, rto_hours, rpo_hours, mtta_hours, mttr_hours
                FROM sla_commitments
                WHERE tenant_id = %s AND effective_to IS NULL
                ORDER BY effective_from DESC
                LIMIT 1
            """, (tenant_id,))
            sla_row = cur.fetchone()

    # Aggregate: group resolved insights by base type and compute ROI
    groups: dict = {}
    total_hours_saved = 0.0
    total_cost_avoided = 0.0

    for ins in resolved_insights:
        raw_type = ins["type"]
        # Base type: strip subtypes like "capacity_storage" → "capacity"
        base_type = raw_type.split("_")[0] if "_" in raw_type else raw_type
        rate = rates.get(raw_type) or rates.get(base_type) or {"hours_saved": 0.5, "rate_per_hour": 150.0}
        h = float(rate["hours_saved"])
        r = float(rate["rate_per_hour"])
        cost = h * r

        if base_type not in groups:
            groups[base_type] = {"count": 0, "hours_saved": 0.0, "cost_avoided": 0.0, "notes": ""}
        groups[base_type]["count"] += 1
        groups[base_type]["hours_saved"] += h
        groups[base_type]["cost_avoided"] += cost
        total_hours_saved += h
        total_cost_avoided += cost

    interventions = sorted(
        [
            {
                "type":        k,
                "count":       v["count"],
                "hours_saved": round(v["hours_saved"], 2),
                "cost_avoided":round(v["cost_avoided"], 2),
            }
            for k, v in groups.items()
        ],
        key=lambda x: x["cost_avoided"],
        reverse=True,
    )

    return {
        "tenant_id":         tenant_id,
        "tenant_name":       tenant_name,
        "from_date":         from_date,
        "to_date":           to_date,
        "region_id":         region_id,
        "incidents_prevented": len(resolved_insights),
        "total_hours_saved": round(total_hours_saved, 2),
        "total_cost_avoided":round(total_cost_avoided, 2),
        "interventions":     interventions,
        "open_items":        [
            {
                "id":         r["id"],
                "type":       r["type"],
                "severity":   r["severity"],
                "title":      r["title"],
                "last_seen":  r["last_seen_at"].isoformat() if r.get("last_seen_at") else None,
            }
            for r in open_items
        ],
        "sla_commitment": dict(sla_row) if sla_row else None,
    }
