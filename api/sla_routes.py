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
            try:
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
            except Exception as db_err:
                logger.error(
                    "SLA compliance/summary DB error: %s", db_err,
                    extra={"context": {"error": str(db_err)}}
                )
                return {"summary": [], "month": str(month_start), "error": "data_unavailable"}

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


# ---------------------------------------------------------------------------
# GET /api/sla/portfolio/summary — account-manager view: per-tenant portfolio
# Must be registered BEFORE /portfolio/executive-summary to avoid conflicts.
# ---------------------------------------------------------------------------

@router.get("/portfolio/summary")
def get_portfolio_summary(
    _user: User = Depends(require_permission("sla", "read")),
):
    """Per-tenant portfolio summary: SLA status, contract usage, quota vs real usage,
    metering cost, resource growth, and open insights."""
    from datetime import date
    from calendar import monthrange
    today = date.today()
    month_start = today.replace(day=1)
    # Previous month for growth comparison
    if today.month == 1:
        prev_month_start = today.replace(year=today.year - 1, month=12, day=1)
    else:
        prev_month_start = today.replace(month=today.month - 1, day=1)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    p.id                                        AS tenant_id,
                    p.name                                      AS tenant_name,
                    sc.tier,
                    cm.breach_fields,
                    cm.at_risk_fields,

                    -- Contracted resources
                    COALESCE(ce_vcpu.contracted, 0)             AS contracted_vcpu,
                    COALESCE(ce_ram.contracted,  0)             AS contracted_ram_mb,
                    COALESCE(ce_stor.contracted, 0)             AS contracted_storage_gb,

                    -- Live quota limits (project_quotas)
                    pq_cpu.quota_limit                          AS quota_vcpu_limit,
                    pq_cpu.in_use                               AS quota_vcpu_used,
                    pq_ram.quota_limit                          AS quota_ram_limit_mb,
                    pq_ram.in_use                               AS quota_ram_used_mb,
                    pq_stor.quota_limit                         AS quota_storage_limit_gb,
                    pq_stor.in_use                              AS quota_storage_used_gb,

                    -- Open insights
                    COALESCE(oi.critical_count, 0)              AS open_critical_count,
                    COALESCE(oi.total_count, 0)                 AS open_total_count,
                    COALESCE(lk.leakage_count, 0)               AS leakage_insight_count,

                    -- Current-month metering aggregates
                    pmm_cur.avg_vcpus                           AS metered_avg_vcpus,
                    pmm_cur.avg_ram_gb                          AS metered_avg_ram_gb,
                    pmm_cur.avg_disk_gb                         AS metered_avg_disk_gb,
                    pmm_cur.estimated_cost                      AS metered_cost_this_month,
                    pmm_cur.currency                            AS metered_currency,
                    pmm_cur.vm_count                            AS metered_vm_count,

                    -- Previous-month metering aggregates (for growth)
                    pmm_prev.avg_vcpus                          AS prev_avg_vcpus,
                    pmm_prev.avg_ram_gb                         AS prev_avg_ram_gb,
                    pmm_prev.estimated_cost                     AS prev_metered_cost

                FROM projects p
                LEFT JOIN sla_commitments sc ON sc.tenant_id = p.id
                    AND sc.effective_to IS NULL
                LEFT JOIN sla_compliance_monthly cm ON cm.tenant_id = p.id
                    AND cm.month = %s AND cm.region_id = ''

                -- Contracted resources (separate joins per resource type)
                LEFT JOIN (
                    SELECT tenant_id, SUM(contracted) AS contracted
                    FROM   msp_contract_entitlements
                    WHERE  resource = 'vcpu' AND effective_to IS NULL
                    GROUP BY tenant_id
                ) ce_vcpu ON ce_vcpu.tenant_id = p.id
                LEFT JOIN (
                    SELECT tenant_id, SUM(contracted) AS contracted
                    FROM   msp_contract_entitlements
                    WHERE  resource IN ('ram', 'ram_mb') AND effective_to IS NULL
                    GROUP BY tenant_id
                ) ce_ram ON ce_ram.tenant_id = p.id
                LEFT JOIN (
                    SELECT tenant_id, SUM(contracted) AS contracted
                    FROM   msp_contract_entitlements
                    WHERE  resource IN ('storage', 'storage_gb', 'gigabytes') AND effective_to IS NULL
                    GROUP BY tenant_id
                ) ce_stor ON ce_stor.tenant_id = p.id

                -- Live quota from project_quotas (OpenStack)
                LEFT JOIN project_quotas pq_cpu ON pq_cpu.project_id = p.id
                    AND pq_cpu.service = 'nova' AND pq_cpu.resource = 'cores'
                LEFT JOIN project_quotas pq_ram ON pq_ram.project_id = p.id
                    AND pq_ram.service = 'nova' AND pq_ram.resource = 'ram'
                LEFT JOIN project_quotas pq_stor ON pq_stor.project_id = p.id
                    AND pq_stor.service = 'cinder' AND pq_stor.resource = 'gigabytes'

                -- Insights
                LEFT JOIN (
                    SELECT
                        metadata->>'tenant_id'                            AS tenant_id,
                        COUNT(*) FILTER (WHERE severity = 'critical')     AS critical_count,
                        COUNT(*)                                           AS total_count
                    FROM   operational_insights
                    WHERE  status = 'open'
                    GROUP BY metadata->>'tenant_id'
                ) oi ON oi.tenant_id = p.id
                LEFT JOIN (
                    SELECT metadata->>'tenant_id' AS tenant_id, COUNT(*) AS leakage_count
                    FROM   operational_insights
                    WHERE  type = 'leakage' AND status = 'open'
                    GROUP BY metadata->>'tenant_id'
                ) lk ON lk.tenant_id = p.id

                -- Metering aggregates — current month
                LEFT JOIN portfolio_metering_monthly pmm_cur
                    ON pmm_cur.tenant_id = p.id AND pmm_cur.month = %s

                -- Metering aggregates — previous month
                LEFT JOIN portfolio_metering_monthly pmm_prev
                    ON pmm_prev.tenant_id = p.id AND pmm_prev.month = %s

                ORDER BY p.name ASC
            """, (month_start, month_start, prev_month_start))
            rows = cur.fetchall()

    def _f(v) -> float | None:
        return round(float(v), 2) if v is not None else None

    def _i(v) -> int | None:
        return int(v) if v is not None else None

    def _growth_pct(cur_val, prev_val) -> float | None:
        """Return month-over-month growth percentage, or None if not computable."""
        if prev_val is None or cur_val is None:
            return None
        if float(prev_val) == 0:
            return None
        return round((float(cur_val) - float(prev_val)) / float(prev_val) * 100, 1)

    results = []
    for row in rows:
        breach = row.get("breach_fields") or []
        at_risk = row.get("at_risk_fields") or []
        if not row.get("tier"):
            sla_status = "not_configured"
        elif breach:
            sla_status = "breached"
        elif at_risk:
            sla_status = "at_risk"
        else:
            sla_status = "ok"

        contracted_vcpu = int(row.get("contracted_vcpu") or 0)
        # Prefer live quota used if available, else fall back to 0
        quota_vcpu_used = _i(row.get("quota_vcpu_used"))
        used_vcpu = quota_vcpu_used if quota_vcpu_used is not None else 0
        quota_vcpu_limit = _i(row.get("quota_vcpu_limit"))

        # Contract usage pct: use contracted vcpu as denominator when set,
        # else quota limit; fall back to None (not computable).
        denom_vcpu = contracted_vcpu or quota_vcpu_limit
        contract_usage_pct = round((used_vcpu / denom_vcpu * 100), 1) if denom_vcpu else None

        # Quota utilisation pct (quota limit vs quota used)
        quota_vcpu_pct = (
            round(quota_vcpu_used / quota_vcpu_limit * 100, 1)
            if quota_vcpu_used is not None and quota_vcpu_limit
            else None
        )
        quota_ram_limit = _i(row.get("quota_ram_limit_mb"))
        quota_ram_used  = _i(row.get("quota_ram_used_mb"))
        quota_ram_pct   = (
            round(quota_ram_used / quota_ram_limit * 100, 1)
            if quota_ram_used is not None and quota_ram_limit
            else None
        )
        quota_stor_limit = _i(row.get("quota_storage_limit_gb"))
        quota_stor_used  = _f(row.get("quota_storage_used_gb"))
        quota_stor_pct   = (
            round(quota_stor_used / quota_stor_limit * 100, 1)
            if quota_stor_used is not None and quota_stor_limit
            else None
        )

        # Growth (MoM)
        vcpu_growth_pct = _growth_pct(row.get("metered_avg_vcpus"), row.get("prev_avg_vcpus"))
        ram_growth_pct  = _growth_pct(row.get("metered_avg_ram_gb"), row.get("prev_avg_ram_gb"))
        cost_growth_pct = _growth_pct(row.get("metered_cost_this_month"), row.get("prev_metered_cost"))

        results.append({
            "tenant_id":             row["tenant_id"],
            "tenant_name":           row["tenant_name"] or row["tenant_id"],
            "tier":                  row.get("tier") or "none",
            "sla_status":            sla_status,
            "breach_fields":         breach,
            "at_risk_fields":        at_risk,

            # Contract vs reality (vCPU)
            "contracted_vcpu":       contracted_vcpu,
            "contracted_ram_mb":     int(row.get("contracted_ram_mb") or 0),
            "contracted_storage_gb": int(row.get("contracted_storage_gb") or 0),
            "used_vcpu":             used_vcpu,
            "contract_usage_pct":    contract_usage_pct,

            # Quota vs real usage
            "quota_vcpu_limit":      quota_vcpu_limit,
            "quota_vcpu_used":       quota_vcpu_used,
            "quota_vcpu_pct":        quota_vcpu_pct,
            "quota_ram_limit_mb":    quota_ram_limit,
            "quota_ram_used_mb":     quota_ram_used,
            "quota_ram_pct":         quota_ram_pct,
            "quota_storage_limit_gb": quota_stor_limit,
            "quota_storage_used_gb": quota_stor_used,
            "quota_storage_pct":     quota_stor_pct,

            # Metering
            "metered_avg_vcpus":     _f(row.get("metered_avg_vcpus")),
            "metered_avg_ram_gb":    _f(row.get("metered_avg_ram_gb")),
            "metered_avg_disk_gb":   _f(row.get("metered_avg_disk_gb")),
            "metered_cost_this_month": _f(row.get("metered_cost_this_month")),
            "metered_currency":      row.get("metered_currency") or "USD",
            "metered_vm_count":      _i(row.get("metered_vm_count")),

            # Growth (month-over-month %)
            "vcpu_growth_pct":       vcpu_growth_pct,
            "ram_growth_pct":        ram_growth_pct,
            "cost_growth_pct":       cost_growth_pct,

            # Insights
            "open_critical_count":   int(row.get("open_critical_count") or 0),
            "open_total_count":      int(row.get("open_total_count") or 0),
            "leakage_insight_count": int(row.get("leakage_insight_count") or 0),
        })

    return {"portfolio": results, "month": str(month_start), "total": len(results)}


# ---------------------------------------------------------------------------
# GET /api/sla/portfolio/executive-summary — fleet-level executive view
# ---------------------------------------------------------------------------

@router.get("/portfolio/executive-summary")
def get_portfolio_executive_summary(
    _user: User = Depends(require_permission("sla", "read")),
):
    """Fleet-wide executive metrics: SLA health, leakage estimate, critical alerts."""
    from datetime import date
    month_start = date.today().replace(day=1)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Total client count
            cur.execute("SELECT COUNT(*) AS cnt FROM projects")
            total_clients = int(cur.fetchone()["cnt"])

            # SLA health breakdown this month
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (
                        WHERE cm.breach_fields IS NOT NULL
                          AND array_length(cm.breach_fields, 1) > 0
                    ) AS breached,
                    COUNT(*) FILTER (
                        WHERE (cm.at_risk_fields IS NOT NULL
                          AND array_length(cm.at_risk_fields, 1) > 0)
                          AND (cm.breach_fields IS NULL
                          OR  array_length(cm.breach_fields, 1) = 0)
                    ) AS at_risk,
                    COUNT(*) FILTER (
                        WHERE sc.tenant_id IS NULL
                    ) AS not_configured,
                    AVG(cm.mttr_avg_hours)  AS avg_mttr_hours,
                    AVG(sc.mttr_hours)      AS avg_mttr_commitment_hours
                FROM projects p
                LEFT JOIN sla_commitments sc ON sc.tenant_id = p.id
                    AND sc.effective_to IS NULL
                LEFT JOIN sla_compliance_monthly cm ON cm.tenant_id = p.id
                    AND cm.month = %s AND cm.region_id = ''
            """, (month_start,))
            sla_row = dict(cur.fetchone())

            # Revenue leakage estimate (dollar total only where unit_price is set)
            cur.execute("""
                SELECT
                    COUNT(DISTINCT oi.metadata->>'tenant_id')   AS leakage_client_count,
                    COUNT(*)                                     AS leakage_insight_count,
                    SUM(
                        CASE WHEN ce.unit_price IS NOT NULL THEN
                            ce.contracted::DECIMAL * ce.unit_price
                            * COALESCE((oi.metadata->>'overage_pct')::DECIMAL, 0)
                        ELSE NULL END
                    )                                            AS revenue_leakage_monthly
                FROM operational_insights oi
                LEFT JOIN msp_contract_entitlements ce
                    ON ce.tenant_id = oi.metadata->>'tenant_id'
                    AND ce.resource = 'vcpu' AND ce.effective_to IS NULL
                WHERE oi.type = 'leakage' AND oi.status = 'open'
            """)
            leakage_row = dict(cur.fetchone())

            # Open critical insights
            cur.execute("""
                SELECT COUNT(*) AS cnt FROM operational_insights
                WHERE severity = 'critical' AND status = 'open'
            """)
            critical_count = int(cur.fetchone()["cnt"])

    breached       = int(sla_row.get("breached") or 0)
    at_risk        = int(sla_row.get("at_risk") or 0)
    not_configured = int(sla_row.get("not_configured") or 0)
    sla_healthy    = total_clients - breached - at_risk - not_configured

    avg_mttr = (
        round(float(sla_row["avg_mttr_hours"]), 2)
        if sla_row.get("avg_mttr_hours") is not None else None
    )
    avg_mttr_commitment = (
        round(float(sla_row["avg_mttr_commitment_hours"]), 2)
        if sla_row.get("avg_mttr_commitment_hours") is not None else None
    )
    leakage_monthly = (
        round(float(leakage_row["revenue_leakage_monthly"]), 2)
        if leakage_row.get("revenue_leakage_monthly") is not None else None
    )

    return {
        "summary": {
            "total_clients":             total_clients,
            "sla_healthy":               max(sla_healthy, 0),
            "sla_at_risk":               at_risk,
            "sla_breached":              breached,
            "sla_not_configured":        not_configured,
            "sla_health_pct":            round(sla_healthy / total_clients * 100, 1) if total_clients else 0,
            "revenue_leakage_monthly":   leakage_monthly,
            "leakage_client_count":      int(leakage_row.get("leakage_client_count") or 0),
            "leakage_insight_count":     int(leakage_row.get("leakage_insight_count") or 0),
            "open_critical_insights":    critical_count,
            "avg_mttr_hours":            avg_mttr,
            "avg_mttr_commitment_hours": avg_mttr_commitment,
        },
        "month": str(month_start),
    }


# ---------------------------------------------------------------------------
# GET /api/sla/portfolio/fleet-metering — fleet-wide metering & growth view
# ---------------------------------------------------------------------------

@router.get("/portfolio/fleet-metering")
def get_portfolio_fleet_metering(
    months: int = Query(6, ge=1, le=24),
    _user: User = Depends(require_permission("sla", "read")),
):
    """Fleet-wide metering summary: resource totals, cost estimate, quota health,
    and month-over-month trends for the last N months."""
    from datetime import date

    today = date.today()
    month_start = today.replace(day=1)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # ---------------------------------------------------------------
            # Monthly trend: last N months from portfolio_metering_monthly
            # ---------------------------------------------------------------
            cur.execute("""
                SELECT
                    pmm.month,
                    COUNT(*)                          AS tenant_count,
                    COALESCE(SUM(pmm.avg_vcpus), 0)   AS total_avg_vcpus,
                    COALESCE(SUM(pmm.avg_ram_gb), 0)   AS total_avg_ram_gb,
                    COALESCE(SUM(pmm.avg_disk_gb), 0)  AS total_avg_disk_gb,
                    COALESCE(SUM(pmm.estimated_cost), 0) AS total_cost,
                    COALESCE(SUM(pmm.vm_count), 0)    AS total_vms
                FROM portfolio_metering_monthly pmm
                WHERE pmm.month >= (date_trunc('month', now()) - ((%s - 1) * interval '1 month'))::date
                GROUP BY pmm.month
                ORDER BY pmm.month ASC
            """, (months,))
            trend_rows = [dict(r) for r in cur.fetchall()]

            # ---------------------------------------------------------------
            # Current-month fleet totals from portfolio_metering_monthly
            # ---------------------------------------------------------------
            cur.execute("""
                SELECT
                    COALESCE(SUM(avg_vcpus), 0)     AS fleet_avg_vcpus,
                    COALESCE(SUM(avg_ram_gb), 0)     AS fleet_avg_ram_gb,
                    COALESCE(SUM(avg_disk_gb), 0)    AS fleet_avg_disk_gb,
                    COALESCE(SUM(estimated_cost), 0) AS fleet_cost_this_month,
                    COALESCE(SUM(vm_count), 0)        AS fleet_vm_count,
                    MIN(currency)                     AS currency
                FROM portfolio_metering_monthly
                WHERE month = %s
            """, (month_start,))
            fleet_row = dict(cur.fetchone() or {})

            # ---------------------------------------------------------------
            # Previous-month fleet totals (for MoM growth)
            # ---------------------------------------------------------------
            if today.month == 1:
                prev_month = today.replace(year=today.year - 1, month=12, day=1)
            else:
                prev_month = today.replace(month=today.month - 1, day=1)

            cur.execute("""
                SELECT
                    COALESCE(SUM(avg_vcpus), 0)     AS fleet_avg_vcpus,
                    COALESCE(SUM(estimated_cost), 0) AS fleet_cost
                FROM portfolio_metering_monthly
                WHERE month = %s
            """, (prev_month,))
            prev_row = dict(cur.fetchone() or {})

            # ---------------------------------------------------------------
            # Fleet-wide quota health from project_quotas (live snapshot)
            # ---------------------------------------------------------------
            cur.execute("""
                SELECT
                    resource,
                    SUM(quota_limit) AS total_limit,
                    SUM(in_use)       AS total_used
                FROM project_quotas
                WHERE service = 'nova' AND resource IN ('cores', 'ram')
                GROUP BY resource
                UNION ALL
                SELECT
                    'storage_gb' AS resource,
                    SUM(quota_limit) AS total_limit,
                    SUM(in_use)       AS total_used
                FROM project_quotas
                WHERE service = 'cinder' AND resource = 'gigabytes'
            """)
            quota_rows = cur.fetchall()

            # ---------------------------------------------------------------
            # Per-tenant growth summary: top 5 fastest-growing tenants (vCPU)
            # ---------------------------------------------------------------
            cur.execute("""
                SELECT
                    p.name AS tenant_name,
                    cur.avg_vcpus  AS vcpus_this_month,
                    prev.avg_vcpus AS vcpus_prev_month,
                    cur.estimated_cost  AS cost_this_month,
                    prev.estimated_cost AS cost_prev_month
                FROM projects p
                JOIN portfolio_metering_monthly cur  ON cur.tenant_id  = p.id AND cur.month  = %s
                JOIN portfolio_metering_monthly prev ON prev.tenant_id = p.id AND prev.month = %s
                WHERE prev.avg_vcpus > 0
                ORDER BY ((cur.avg_vcpus - prev.avg_vcpus) / prev.avg_vcpus) DESC
                LIMIT 10
            """, (month_start, prev_month))
            growth_rows = [dict(r) for r in cur.fetchall()]

            # ---------------------------------------------------------------
            # Fleet contracted totals (MSP entitlements)
            # ---------------------------------------------------------------
            cur.execute("""
                SELECT resource, SUM(contracted) AS total_contracted
                FROM msp_contract_entitlements
                WHERE effective_to IS NULL
                GROUP BY resource
            """)
            contract_rows = {r["resource"]: int(r["total_contracted"] or 0) for r in cur.fetchall()}

    def _f(v) -> float | None:
        return round(float(v), 2) if v is not None else None

    def _growth(cur_val, prev_val) -> float | None:
        if not prev_val or float(prev_val) == 0 or cur_val is None:
            return None
        return round((float(cur_val) - float(prev_val)) / float(prev_val) * 100, 1)

    # Quota health map
    quota_health: dict = {}
    for qr in quota_rows:
        resource = qr["resource"]
        limit = int(qr["total_limit"] or 0) if qr["total_limit"] else None
        used  = int(qr["total_used"]  or 0) if qr["total_used"]  else None
        pct   = round(used / limit * 100, 1) if limit and used is not None else None
        quota_health[resource] = {"limit": limit, "used": used, "utilization_pct": pct}

    # Format trend rows
    def _trend_row(r: dict) -> dict:
        return {
            "month":          str(r["month"]),
            "tenant_count":   int(r["tenant_count"] or 0),
            "total_avg_vcpus": _f(r["total_avg_vcpus"]),
            "total_avg_ram_gb": _f(r["total_avg_ram_gb"]),
            "total_avg_disk_gb": _f(r["total_avg_disk_gb"]),
            "total_cost":     _f(r["total_cost"]),
            "total_vms":      int(r["total_vms"] or 0),
        }

    # Format growth rows
    def _growth_row(r: dict) -> dict:
        vcpu_growth = _growth(r.get("vcpus_this_month"), r.get("vcpus_prev_month"))
        cost_growth = _growth(r.get("cost_this_month"),  r.get("cost_prev_month"))
        return {
            "tenant_name":      r["tenant_name"],
            "vcpus_this_month": _f(r.get("vcpus_this_month")),
            "vcpus_prev_month": _f(r.get("vcpus_prev_month")),
            "vcpu_growth_pct":  vcpu_growth,
            "cost_this_month":  _f(r.get("cost_this_month")),
            "cost_prev_month":  _f(r.get("cost_prev_month")),
            "cost_growth_pct":  cost_growth,
        }

    fleet_vcpu_prev = float(prev_row.get("fleet_avg_vcpus") or 0)
    fleet_cost_prev = float(prev_row.get("fleet_cost") or 0)

    return {
        "month": str(month_start),
        "fleet_totals": {
            "avg_vcpus":           _f(fleet_row.get("fleet_avg_vcpus")),
            "avg_ram_gb":          _f(fleet_row.get("fleet_avg_ram_gb")),
            "avg_disk_gb":         _f(fleet_row.get("fleet_avg_disk_gb")),
            "cost_this_month":     _f(fleet_row.get("fleet_cost_this_month")),
            "vm_count":            int(fleet_row.get("fleet_vm_count") or 0),
            "currency":            fleet_row.get("currency") or "USD",
            "vcpu_growth_pct":     _growth(fleet_row.get("fleet_avg_vcpus"), fleet_vcpu_prev),
            "cost_growth_pct":     _growth(fleet_row.get("fleet_cost_this_month"), fleet_cost_prev),
        },
        "contracted_totals": contract_rows,
        "quota_health":      quota_health,
        "monthly_trend":     [_trend_row(r) for r in trend_rows],
        "top_growing_tenants": [_growth_row(r) for r in growth_rows],
    }

