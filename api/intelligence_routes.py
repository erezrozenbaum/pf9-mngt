"""
Operational Intelligence Routes
================================
CRUD + lifecycle management for the operational_insights table.

RBAC
----
  GET  endpoints — intelligence:read  (viewer, operator, admin, superadmin)
  POST endpoints — intelligence:write (admin, superadmin)
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from db_pool import get_connection
from intelligence_utils import types_for_department

logger = logging.getLogger("pf9.intelligence")

INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class InsightOut(BaseModel):
    id: int
    type: str
    severity: str
    entity_type: str
    entity_id: str
    entity_name: Optional[str]
    title: str
    message: str
    metadata: dict
    status: str
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[str]
    snooze_until: Optional[str]
    resolved_at: Optional[str]
    detected_at: str
    last_seen_at: str


class SnoozeRequest(BaseModel):
    snooze_until: str   # ISO datetime string


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_insight(row: dict) -> dict:
    def _ts(v):
        return v.isoformat() if v else None
    return {
        "id":               row["id"],
        "type":             row["type"],
        "severity":         row["severity"],
        "entity_type":      row["entity_type"],
        "entity_id":        row["entity_id"],
        "entity_name":      row.get("entity_name"),
        "title":            row["title"],
        "message":          row["message"],
        "metadata":         row.get("metadata") or {},
        "status":           row["status"],
        "acknowledged_by":  row.get("acknowledged_by"),
        "acknowledged_at":  _ts(row.get("acknowledged_at")),
        "snooze_until":     _ts(row.get("snooze_until")),
        "resolved_at":      _ts(row.get("resolved_at")),
        "detected_at":      _ts(row.get("detected_at")),
        "last_seen_at":     _ts(row.get("last_seen_at")),
    }


# ---------------------------------------------------------------------------
# GET /api/intelligence/insights — list with filters + pagination
# ---------------------------------------------------------------------------

_SORT_CLAUSES: dict[str, str] = {
    "severity":    "CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, last_seen_at DESC",
    "detected_at": "detected_at DESC",
    "last_seen":   "last_seen_at DESC",
    "type":        "type, CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END",
    "entity":      "entity_name NULLS LAST, CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END",
    "tenant":      "metadata->>'tenant_name' NULLS LAST, entity_name NULLS LAST",
    "status":      "CASE status WHEN 'open' THEN 1 WHEN 'acknowledged' THEN 2 WHEN 'snoozed' THEN 3 ELSE 4 END, CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END",
}


@router.get("/insights")
def list_insights(
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    department: Optional[str] = Query(None, pattern="^(support|engineering|operations|general)$"),
    sort_by: str = Query("severity", pattern="^(severity|detected_at|last_seen|type|entity|tenant|status)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _user: User = Depends(require_permission("intelligence", "read")),
):
    conditions = []
    params: list = []

    if status_filter:
        conditions.append("status = %s")
        params.append(status_filter)
    else:
        # Default: exclude permanently suppressed/resolved
        conditions.append("status IN ('open','acknowledged','snoozed')")

    if severity:
        conditions.append("severity = %s")
        params.append(severity)

    if type:
        conditions.append("type = %s")
        params.append(type)
    elif department:
        # Department workspace filter — applies only when no explicit type filter given.
        # Use prefix matching so "anomaly" covers "anomaly_vm_spike", etc.
        dept_types = types_for_department(department)
        if dept_types is not None:
            # Build: type = ANY(%s) OR type LIKE 'prefix_%' for each prefix type
            prefix_clauses = []
            for dt in dept_types:
                prefix_clauses.append("type = %s")
                params.append(dt)
                prefix_clauses.append("type LIKE %s")
                params.append(dt + "_%")
            conditions.append("(" + " OR ".join(prefix_clauses) + ")")

    if entity_type:
        conditions.append("entity_type = %s")
        params.append(entity_type)

    if tenant_id:
        # Match tenant-scoped insights (entity_id or metadata reference)
        conditions.append("(entity_id = %s OR (entity_type = 'tenant' AND entity_id = %s))")
        params.extend([tenant_id, tenant_id])

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * page_size

    order_clause = _SORT_CLAUSES.get(sort_by, _SORT_CLAUSES["severity"])
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT *, COUNT(*) OVER() AS total_count
                FROM operational_insights
                {where}
                ORDER BY {order_clause}
                LIMIT %s OFFSET %s
                """, params + [page_size, offset])
            rows = cur.fetchall()

    total = rows[0]["total_count"] if rows else 0
    items = [_row_to_insight(dict(r)) for r in rows]
    return {"insights": items, "total": total, "page": page, "page_size": page_size}


# ---------------------------------------------------------------------------
# GET /api/intelligence/insights/summary — counts by severity + type
# ---------------------------------------------------------------------------

@router.get("/insights/summary")
def insights_summary(
    department: Optional[str] = Query(None, pattern="^(support|engineering|operations|general)$"),
    _user: User = Depends(require_permission("intelligence", "read")),
):
    dept_types = types_for_department(department)

    # Build prefix-aware type filter
    if dept_types is not None:
        prefix_clauses = []
        base_params: list = []
        for dt in dept_types:
            prefix_clauses.append("type = %s")
            base_params.append(dt)
            prefix_clauses.append("type LIKE %s")
            base_params.append(dt + "_%")
        type_clause = "AND (" + " OR ".join(prefix_clauses) + ")"
    else:
        type_clause = ""
        base_params = []

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT
                    severity,
                    COUNT(*) AS count
                FROM operational_insights
                WHERE status IN ('open','acknowledged','snoozed')
                {type_clause}
                GROUP BY severity
                """, base_params)
            by_severity = {r["severity"]: r["count"] for r in cur.fetchall()}

            cur.execute(
                f"""
                SELECT type, COUNT(*) AS count
                FROM operational_insights
                WHERE status IN ('open','acknowledged','snoozed')
                {type_clause}
                GROUP BY type
                ORDER BY count DESC
                """, base_params)
            by_type = [{"type": r["type"], "count": r["count"]} for r in cur.fetchall()]

    return {
        "by_severity": {
            "critical": by_severity.get("critical", 0),
            "high":     by_severity.get("high", 0),
            "medium":   by_severity.get("medium", 0),
            "low":      by_severity.get("low", 0),
        },
        "by_type": by_type,
        "total_open": sum(by_severity.values()),
    }


# ---------------------------------------------------------------------------
# GET /api/intelligence/insights/{id}
# ---------------------------------------------------------------------------

@router.get("/insights/{insight_id}")
def get_insight(
    insight_id: int,
    _user: User = Depends(require_permission("intelligence", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM operational_insights WHERE id = %s", (insight_id,))
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Insight not found")
    return {"insight": _row_to_insight(dict(row))}


# ---------------------------------------------------------------------------
# POST /api/intelligence/insights/{id}/acknowledge
# ---------------------------------------------------------------------------

@router.post("/insights/{insight_id}/acknowledge", status_code=status.HTTP_200_OK)
def acknowledge_insight(
    insight_id: int,
    user: User = Depends(require_permission("intelligence", "write")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE operational_insights
                SET status = 'acknowledged',
                    acknowledged_by = %s,
                    acknowledged_at = NOW()
                WHERE id = %s
                  AND status IN ('open','snoozed')
                RETURNING *
            """, (user["username"], insight_id))
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Insight not found or not in open/snoozed state")
    logger.info("Insight %d acknowledged by %s", insight_id, user["username"])
    return {"insight": _row_to_insight(dict(row))}


# ---------------------------------------------------------------------------
# POST /api/intelligence/insights/{id}/snooze
# ---------------------------------------------------------------------------

@router.post("/insights/{insight_id}/snooze", status_code=status.HTTP_200_OK)
def snooze_insight(
    insight_id: int,
    body: SnoozeRequest,
    user: User = Depends(require_permission("intelligence", "write")),
):
    from datetime import datetime, timezone
    try:
        snooze_dt = datetime.fromisoformat(body.snooze_until.replace("Z", "+00:00"))
        if snooze_dt.tzinfo is None:
            snooze_dt = snooze_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid snooze_until datetime")

    if snooze_dt <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="snooze_until must be in the future")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE operational_insights
                SET status = 'snoozed', snooze_until = %s
                WHERE id = %s
                  AND status IN ('open','acknowledged')
                RETURNING *
            """, (snooze_dt, insight_id))
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Insight not found or not in open/acknowledged state")
    logger.info("Insight %d snoozed until %s by %s", insight_id, snooze_dt, user["username"])
    return {"insight": _row_to_insight(dict(row))}


# ---------------------------------------------------------------------------
# POST /api/intelligence/insights/{id}/resolve
# ---------------------------------------------------------------------------

@router.post("/insights/{insight_id}/resolve", status_code=status.HTTP_200_OK)
def resolve_insight(
    insight_id: int,
    user: User = Depends(require_permission("intelligence", "write")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                UPDATE operational_insights
                SET status = 'resolved', resolved_at = NOW()
                WHERE id = %s
                  AND status IN ('open','acknowledged','snoozed')
                RETURNING *
            """, (insight_id,))
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Insight not found or already resolved")
    logger.info("Insight %d resolved by %s", insight_id, user["username"])
    return {"insight": _row_to_insight(dict(row))}


# ---------------------------------------------------------------------------
# GET /api/intelligence/insights/entity/{entity_type}/{entity_id}
# ---------------------------------------------------------------------------

@router.get("/insights/entity/{entity_type}/{entity_id}")
def get_entity_insights(
    entity_type: str,
    entity_id: str,
    include_resolved: bool = Query(False),
    _user: User = Depends(require_permission("intelligence", "read")),
):
    status_clause = (
        "AND status NOT IN ('suppressed')"
        if include_resolved
        else "AND status IN ('open','acknowledged','snoozed')"
    )
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT * FROM operational_insights
                WHERE entity_type = %s AND entity_id = %s
                {status_clause}
                ORDER BY
                    CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                   WHEN 'medium' THEN 3 ELSE 4 END,
                    detected_at DESC
                """, (entity_type, entity_id))
            rows = cur.fetchall()

    return {"insights": [_row_to_insight(dict(r)) for r in rows]}


# ---------------------------------------------------------------------------
# POST /api/intelligence/insights/bulk-acknowledge
# POST /api/intelligence/insights/bulk-resolve
# Phase 2: batch lifecycle operations
# ---------------------------------------------------------------------------

class BulkActionRequest(BaseModel):
    severity: Optional[str] = None    # optional severity filter
    type: Optional[str] = None        # optional type filter


@router.post("/insights/bulk-acknowledge", status_code=status.HTTP_200_OK)
def bulk_acknowledge(
    body: BulkActionRequest,
    user: User = Depends(require_permission("intelligence", "write")),
):
    conditions = ["status = 'open'"]
    params: list = []
    if body.severity:
        conditions.append("severity = %s")
        params.append(body.severity)
    if body.type:
        conditions.append("type = %s")
        params.append(body.type)
    where = "WHERE " + " AND ".join(conditions)
    params.extend([user["username"]])

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE operational_insights
                SET status = 'acknowledged',
                    acknowledged_by = %s,
                    acknowledged_at = NOW()
                {where}
                """, params[-1:] + params[:-1])
            count = cur.rowcount
            conn.commit()

    logger.info("Bulk acknowledged %d insights by %s", count, user["username"])
    return {"acknowledged": count}


@router.post("/insights/bulk-resolve", status_code=status.HTTP_200_OK)
def bulk_resolve(
    body: BulkActionRequest,
    user: User = Depends(require_permission("intelligence", "write")),
):
    conditions = ["status IN ('open','acknowledged','snoozed')"]
    params: list = []
    if body.severity:
        conditions.append("severity = %s")
        params.append(body.severity)
    if body.type:
        conditions.append("type = %s")
        params.append(body.type)
    where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE operational_insights
                SET status = 'resolved', resolved_at = NOW()
                {where}
                """, params)
            count = cur.rowcount
            conn.commit()

    logger.info("Bulk resolved %d insights by %s", count, user["username"])
    return {"resolved": count}


# ---------------------------------------------------------------------------
# GET  /api/intelligence/insights/{id}/recommendations
# POST /api/intelligence/insights/{id}/recommendations/{rec_id}/dismiss
# Phase 2: recommendations
# ---------------------------------------------------------------------------

@router.get("/insights/{insight_id}/recommendations")
def get_recommendations(
    insight_id: int,
    _user: User = Depends(require_permission("intelligence", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, action_type, action_payload, estimated_impact,
                       status, created_at, executed_at
                FROM insight_recommendations
                WHERE insight_id = %s
                ORDER BY created_at ASC
            """, (insight_id,))
            rows = cur.fetchall()
    recs = [
        {
            "id":               r["id"],
            "action_type":      r["action_type"],
            "action_payload":   r["action_payload"] or {},
            "estimated_impact": r.get("estimated_impact"),
            "status":           r["status"],
            "created_at":       r["created_at"].isoformat() if r.get("created_at") else None,
            "executed_at":      r["executed_at"].isoformat() if r.get("executed_at") else None,
        }
        for r in rows
    ]
    return {"recommendations": recs}


@router.post("/insights/{insight_id}/recommendations/{rec_id}/dismiss",
             status_code=status.HTTP_200_OK)
def dismiss_recommendation(
    insight_id: int,
    rec_id: int,
    user: User = Depends(require_permission("intelligence", "write")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE insight_recommendations
                SET status = 'dismissed'
                WHERE id = %s AND insight_id = %s AND status = 'pending'
            """, (rec_id, insight_id))
            affected = cur.rowcount
            conn.commit()
    if not affected:
        raise HTTPException(status_code=404, detail="Recommendation not found or already actioned")
    logger.info("Recommendation %d dismissed by %s", rec_id, user["username"])
    return {"dismissed": True}


# ---------------------------------------------------------------------------
# GET /api/intelligence/forecast
# Capacity Forecast — per-project resource runway (storage, vCPU, RAM, etc.)
# Computes linear regression on-demand from the last 14 days of metering data.
# ---------------------------------------------------------------------------

def _linear_forecast(xs: List[float], ys: List[float]) -> float:
    """Return slope (units per day). Returns 0 if insufficient data."""
    n = len(xs)
    if n < 3:
        return 0.0
    sx = sum(xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


def _days_runway(used: float, quota: float, slope: float, target_pct: float = 90.0) -> Optional[int]:
    if quota <= 0 or slope <= 0:
        return None
    gap = quota * target_pct / 100.0 - used
    if gap <= 0:
        return 0
    return max(0, int(gap / slope))


@router.get("/forecast")
def get_capacity_forecast(
    project_id: Optional[str] = Query(None),
    _user: User = Depends(require_permission("intelligence", "read")),
):
    """
    Return per-project multi-resource capacity forecast.

    Response:
      {
        "forecasts": [
          {
            "project_id":   "...",
            "project_name": "...",
            "resources": {
              "storage_gb":     { "used": 40, "quota": 100, "used_pct": 40, "days_to_90": 18,
                                  "trend_per_day": 0.5, "confidence": 0.8 },
              "vcpus":          { ... },
              "ram_mb":         { ... },
              "instances":      { ... },
              "floating_ips":   { ... }
            }
          }, ...
        ]
      }
    """
    _RESOURCES = [
        ("storage_gb",  "storage_used_gb",   "storage_quota_gb"),
        ("vcpus",       "vcpus_used",         "vcpus_quota"),
        ("ram_mb",      "ram_used_mb",         "ram_quota_mb"),
        ("instances",   "instances_used",      "instances_quota"),
        ("floating_ips", "floating_ips_used",  "floating_ips_quota"),
    ]

    # Columns we actually need
    used_cols  = [rc[1] for rc in _RESOURCES]
    quota_cols = [rc[2] for rc in _RESOURCES]
    all_cols   = ", ".join(
        ["EXTRACT(EPOCH FROM collected_at) AS ts", "project_id", "project_name"]
        + used_cols + quota_cols
    )

    pid_clause = "AND project_id = %s" if project_id else ""
    pid_params: list = [project_id] if project_id else []

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT {all_cols}
                FROM metering_quotas
                WHERE collected_at >= NOW() - INTERVAL '14 days'
                  AND project_id IS NOT NULL
                  {pid_clause}
                ORDER BY project_id, collected_at ASC
                """, pid_params)
            rows = cur.fetchall()

    # Group by project
    projects: dict = {}
    for r in rows:
        pid = r["project_id"]
        if pid not in projects:
            projects[pid] = {"name": r["project_name"] or pid, "rows": []}
        projects[pid]["rows"].append(r)

    forecasts = []
    for pid, pdata in projects.items():
        prows = pdata["rows"]
        if len(prows) < 3:
            continue
        t0 = float(prows[0]["ts"])
        xs = [(float(r["ts"]) - t0) / 86400.0 for r in prows]

        resources: dict = {}
        for res_key, used_col, quota_col in _RESOURCES:
            try:
                ys    = [float(r[used_col] or 0) for r in prows]
                quota = float(prows[-1][quota_col] or 0)
                used  = ys[-1]
                slope = _linear_forecast(xs, ys)
                # R² for confidence
                if len(ys) >= 2:
                    _, intercept = (0.0, 0.0)
                    n = len(xs)
                    sx = sum(xs)
                    sy = sum(ys)
                    sxy = sum(x * y for x, y in zip(xs, ys))
                    sxx = sum(x * x for x in xs)
                    d = n * sxx - sx * sx
                    if d:
                        slope_c = (n * sxy - sx * sy) / d
                        intercept = (sy - slope_c * sx) / n
                    y_mean = sum(ys) / len(ys)
                    ss_tot = sum((y - y_mean) ** 2 for y in ys)
                    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys)) if ss_tot else 0
                    r2     = max(0.0, 1.0 - ss_res / ss_tot) if ss_tot else 1.0
                else:
                    r2 = 0.0
                confidence = round(min(1.0, len(prows) / 30.0) * max(0.0, r2), 3)
                resources[res_key] = {
                    "used":         round(used, 2),
                    "quota":        round(quota, 2),
                    "used_pct":     round(used / quota * 100, 1) if quota > 0 else None,
                    "days_to_90":   _days_runway(used, quota, slope),
                    "trend_per_day": round(slope, 4),
                    "confidence":   confidence,
                }
            except Exception:
                pass

        if resources:
            forecasts.append({
                "project_id":   pid,
                "project_name": pdata["name"],
                "resources":    resources,
            })

    # Sort: soonest runway first (projects with no runway go last)
    def _min_runway(f: dict) -> int:
        days = [v["days_to_90"] for v in f["resources"].values()
                if v.get("days_to_90") is not None]
        return min(days) if days else 9999

    forecasts.sort(key=_min_runway)
    return {"forecasts": forecasts}


# ---------------------------------------------------------------------------
# GET /api/intelligence/client-health/{tenant_id}
# Client Health – aggregated efficiency, stability, and capacity runway
# for a single tenant (project name or project ID).
# ---------------------------------------------------------------------------

@router.get("/client-health/{tenant_id}")
def get_client_health(
    tenant_id: str,
    _user: User = Depends(require_permission("client_health", "read")),
):
    """
    Return a three-axis health summary for a single tenant.

    Response:
      {
        "tenant_id":                "acme-corp",
        "efficiency_score":         72.4,   // avg overall_score last 7 days
        "efficiency_classification":"good",
        "stability_score":          85.0,   // 100 - deductions for open insights
        "open_critical":            0,
        "open_high":                1,
        "open_medium":              2,
        "capacity_runway_days":     45,     // soonest-exhausting resource
        "capacity_runway_resource": "vcpus",
        "last_computed":            "2025-01-15T12:00:00Z"
      }
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Resolve project UUID → human-readable name used in metering_efficiency
            cur.execute("SELECT name FROM projects WHERE id = %s", (tenant_id,))
            _proj_row = cur.fetchone()
            project_key = _proj_row["name"] if _proj_row else tenant_id

            # 1. Efficiency — avg over last 7 days for this tenant
            cur.execute(
                """
                SELECT
                    COALESCE(AVG(overall_score), 0)::NUMERIC(5,2) AS avg_score,
                    CASE
                        WHEN AVG(overall_score) >= 80 THEN 'excellent'
                        WHEN AVG(overall_score) >= 60 THEN 'good'
                        WHEN AVG(overall_score) >= 40 THEN 'fair'
                        ELSE 'poor'
                    END AS classification
                FROM metering_efficiency
                WHERE collected_at >= NOW() - INTERVAL '7 days'
                  AND (project_name = %s OR project_name ILIKE %s)
                """,
                (project_key, f"%{project_key}%"),
            )
            eff_row = cur.fetchone() or {}
            efficiency_score = float(eff_row.get("avg_score") or 0)
            efficiency_classification = eff_row.get("classification") or "unknown"

            # 2. Stability — penalise for open insights
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE severity = 'critical') AS open_critical,
                    COUNT(*) FILTER (WHERE severity = 'high')     AS open_high,
                    COUNT(*) FILTER (WHERE severity = 'medium')   AS open_medium
                FROM operational_insights
                WHERE status IN ('open', 'acknowledged')
                  AND (
                        metadata->>'tenant_name' = %s
                     OR metadata->>'project'      = %s
                     OR entity_name ILIKE %s
                  )
                """,
                (tenant_id, tenant_id, f"%{tenant_id}%"),
            )
            stab_row = cur.fetchone() or {}
            open_critical = int(stab_row.get("open_critical") or 0)
            open_high     = int(stab_row.get("open_high")     or 0)
            open_medium   = int(stab_row.get("open_medium")   or 0)
            # Deduct: critical=20pts, high=10pts, medium=5pts — floor 0
            stability_score = max(0.0, 100.0 - open_critical * 20 - open_high * 10 - open_medium * 5)

            # 3. Capacity runway — minimum days_to_90 across resources for this tenant's projects
            cur.execute(
                """
                SELECT project_id, project_name,
                       storage_used_gb,   storage_quota_gb,
                       vcpus_used,        vcpus_quota,
                       ram_used_mb,       ram_quota_mb,
                       instances_used,    instances_quota
                FROM metering_quotas
                WHERE collected_at >= NOW() - INTERVAL '14 days'
                  AND (project_name = %s OR project_name ILIKE %s)
                ORDER BY project_id, collected_at ASC
                """,
                (tenant_id, f"%{tenant_id}%"),
            )
            q_rows = cur.fetchall()

    # Compute runway from quota rows (reuse existing helper)
    _QUOTA_RESOURCES = [
        ("vcpus",       "vcpus_used",        "vcpus_quota"),
        ("ram_mb",      "ram_used_mb",        "ram_quota_mb"),
        ("storage_gb",  "storage_used_gb",    "storage_quota_gb"),
        ("instances",   "instances_used",     "instances_quota"),
    ]

    min_runway: Optional[int] = None
    min_runway_resource: Optional[str] = None

    if q_rows:
        # Build xs/ys per resource using all rows (project-level)
        from collections import defaultdict
        projects_rows: dict = defaultdict(list)
        for r in q_rows:
            projects_rows[r["project_id"]].append(r)

        for _pid, prows in projects_rows.items():
            if len(prows) < 3:
                continue
            import time as _time
            # Approximate ts using row position (rows ordered by collected_at)
            xs = list(range(len(prows)))
            for res_key, used_col, quota_col in _QUOTA_RESOURCES:
                try:
                    ys    = [float(r[used_col] or 0) for r in prows]
                    quota = float(prows[-1][quota_col] or 0)
                    used  = ys[-1]
                    slope = _linear_forecast(xs, ys)
                    runway = _days_runway(used, quota, slope)
                    if runway is not None:
                        if min_runway is None or runway < min_runway:
                            min_runway = runway
                            min_runway_resource = res_key
                except Exception:
                    pass

    return {
        "tenant_id":                 tenant_id,
        "efficiency_score":          round(efficiency_score, 1),
        "efficiency_classification": efficiency_classification,
        "stability_score":           round(stability_score, 1),
        "open_critical":             open_critical,
        "open_high":                 open_high,
        "open_medium":               open_medium,
        "capacity_runway_days":      min_runway,
        "capacity_runway_resource":  min_runway_resource,
        "last_computed":             datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# GET /api/intelligence/regions
# Cross-Region Comparison — per-region health and utilization summary
# ---------------------------------------------------------------------------

@router.get("/regions")
def get_region_comparison(
    _user: User = Depends(require_permission("intelligence", "read")),
):
    """
    Return per-region compute utilization, health score, and insight summary.

    Response:
      {
        "regions": [
          {
            "region_id":            "default:region-one",
            "hypervisors":          4,
            "total_vcpus":          48,
            "allocated_vcpus":      20,
            "vcpu_utilization":     41.7,
            "total_ram_mb":         65536,
            "allocated_ram_mb":     32768,
            "ram_utilization":      50.0,
            "running_vms":          10,
            "open_critical":        2,
            "open_high":            3,
            "capacity_runway_days": 18,
            "growth_rate_pct":      5.2
          }
        ]
      }
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Basic hypervisor aggregates per region
            cur.execute("""
                SELECT
                    region_id,
                    COUNT(*)          AS hypervisors,
                    SUM(vcpus)        AS total_vcpus,
                    SUM(memory_mb)    AS total_ram_mb,
                    SUM(running_vms)  AS running_vms
                FROM hypervisors
                WHERE state = 'up'
                GROUP BY region_id
                ORDER BY region_id
            """)
            base_rows = {r["region_id"]: dict(r) for r in cur.fetchall()}

            if not base_rows:
                return {"regions": []}

            # Allocated vCPUs + RAM per region from active servers
            cur.execute("""
                SELECT
                    h.region_id,
                    COALESCE(SUM(f.vcpus),  0) AS allocated_vcpus,
                    COALESCE(SUM(f.ram_mb), 0) AS allocated_ram_mb
                FROM servers s
                JOIN hypervisors h ON h.hostname = s.hypervisor_hostname
                JOIN flavors     f ON f.id = s.flavor_id
                WHERE s.status = 'ACTIVE'
                GROUP BY h.region_id
            """)
            for r in cur.fetchall():
                rid = r["region_id"]
                if rid in base_rows:
                    base_rows[rid]["allocated_vcpus"] = float(r["allocated_vcpus"] or 0)
                    base_rows[rid]["allocated_ram_mb"] = float(r["allocated_ram_mb"] or 0)

            # Open critical + high insights per region (via hypervisor entity_id)
            cur.execute("""
                SELECT
                    h.region_id,
                    oi.severity,
                    COUNT(*) AS cnt
                FROM operational_insights oi
                JOIN hypervisors h ON h.id::text = oi.entity_id
                WHERE oi.status IN ('open','acknowledged','snoozed')
                  AND oi.severity IN ('critical','high')
                GROUP BY h.region_id, oi.severity
            """)
            for r in cur.fetchall():
                rid = r["region_id"]
                if rid in base_rows:
                    key = f"open_{r['severity']}"
                    base_rows[rid][key] = int(r["cnt"] or 0)

    # Compute storage capacity runway from metering_quotas (fleet-wide per region)
    region_runways: dict = {}
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    region_id,
                    DATE_TRUNC('day', collected_at) AS day,
                    SUM(storage_used_gb)  AS used,
                    SUM(storage_quota_gb) AS quota
                FROM metering_quotas
                WHERE collected_at >= NOW() - INTERVAL '14 days'
                  AND region_id IS NOT NULL
                  AND storage_quota_gb IS NOT NULL
                GROUP BY region_id, 2
                ORDER BY region_id, 2
            """)
            quota_rows = cur.fetchall()

    from collections import defaultdict
    region_quota_data: dict = defaultdict(list)
    for r in quota_rows:
        region_quota_data[r["region_id"]].append(r)

    for region_id, data_pts in region_quota_data.items():
        if len(data_pts) < 3:
            continue
        xs   = list(range(len(data_pts)))
        ys   = [float(d["used"] or 0) for d in data_pts]
        quot = float(data_pts[-1]["quota"] or 0)
        slope = _linear_forecast(xs, ys)
        runway = _days_runway(ys[-1], quot, slope) if quot > 0 else None
        region_runways[region_id] = runway

    # VM growth rate per region (last 7 days)
    region_growth: dict = {}
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    h.region_id,
                    DATE_TRUNC('day', s.recorded_at) AS day,
                    COUNT(DISTINCT s.id)             AS vms
                FROM servers_history s
                JOIN hypervisors h ON h.hostname = s.hypervisor_hostname
                WHERE s.status = 'ACTIVE'
                  AND s.recorded_at >= NOW() - INTERVAL '14 days'
                GROUP BY h.region_id, 2
                ORDER BY h.region_id, 2
            """)
            growth_rows = cur.fetchall()

    from collections import defaultdict as _dd
    region_vm_history: dict = _dd(list)
    for r in growth_rows:
        region_vm_history[r["region_id"]].append(int(r["vms"] or 0))

    for rid, vm_counts in region_vm_history.items():
        if len(vm_counts) >= 7:
            half = len(vm_counts) // 2
            early_avg = sum(vm_counts[:half]) / half
            late_avg  = sum(vm_counts[half:]) / max(1, len(vm_counts) - half)
            region_growth[rid] = round(
                (late_avg - early_avg) / max(1, early_avg) * 100, 1
            )
        else:
            region_growth[rid] = 0.0

    # Build response
    result = []
    for region_id, row in sorted(base_rows.items()):
        total_vcpu = float(row.get("total_vcpus") or 0)
        alloc_vcpu = float(row.get("allocated_vcpus", 0))
        total_ram  = float(row.get("total_ram_mb") or 0)
        alloc_ram  = float(row.get("allocated_ram_mb", 0))
        result.append({
            "region_id":            region_id,
            "hypervisors":          int(row.get("hypervisors") or 0),
            "total_vcpus":          int(total_vcpu),
            "allocated_vcpus":      int(alloc_vcpu),
            "vcpu_utilization":     round(alloc_vcpu / total_vcpu * 100, 1) if total_vcpu else 0,
            "total_ram_mb":         int(total_ram),
            "allocated_ram_mb":     int(alloc_ram),
            "ram_utilization":      round(alloc_ram / total_ram * 100, 1) if total_ram else 0,
            "running_vms":          int(row.get("running_vms") or 0),
            "open_critical":        row.get("open_critical", 0),
            "open_high":            row.get("open_high", 0),
            "capacity_runway_days": region_runways.get(region_id),
            "growth_rate_pct":      region_growth.get(region_id, 0.0),
        })

    return {"regions": result}


# ---------------------------------------------------------------------------
# POST /api/intelligence/invite-observer
# Send observer invite email + store portal_invite_tokens row
# ---------------------------------------------------------------------------

class ObserverInviteRequest(BaseModel):
    email: str = Field(..., pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    project_id: str
    tenant_name: str
    portal_url: str = Field(default="")


@router.post("/invite-observer", status_code=202, summary="Invite an observer to the Tenant Portal")
def invite_observer(
    body: ObserverInviteRequest,
    current_user: User = Depends(require_permission("client_health", "read")),
):
    """
    Generate a one-time portal_invite_tokens row (portal_role=observer),
    send an invite email, and return the token ID.
    The token expires in 72 hours.
    """
    import secrets as _sec
    from smtp_helper import send_observer_invite_email

    raw_token = _sec.token_urlsafe(32)
    expires_at = datetime.utcnow().replace(tzinfo=None)
    from datetime import timedelta
    expires_at = datetime.utcnow() + timedelta(hours=72)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO portal_invite_tokens
                    (token, project_id, invited_email, portal_role, created_by, expires_at)
                VALUES (%s, %s, %s, 'observer', %s, %s)
                RETURNING id
                """,
                (raw_token, body.project_id, body.email, current_user.username, expires_at),
            )
            row = cur.fetchone()

    portal_url = body.portal_url or "https://portal"

    send_observer_invite_email(
        to_email=body.email,
        invited_by=current_user.username,
        tenant_name=body.tenant_name,
        portal_url=portal_url,
        token=raw_token,
        expires_hours=72,
    )

    return {"invite_id": row["id"], "message": "invite_sent"}


# ---------------------------------------------------------------------------
# Internal service-to-service endpoint (no JWT required — uses X-Internal-Secret)
# Registered on the app object by setup_intelligence_internal_routes(app).
# ---------------------------------------------------------------------------

def setup_intelligence_internal_routes(app) -> None:  # noqa: ANN001
    """Register /internal/client-health under the main FastAPI app.

    Called from main.py after the app is constructed.  The RBAC middleware
    skips JWT verification for all /internal/* paths, so the endpoint
    performs its own pre-shared-secret check.
    """

    @app.get("/internal/client-health/{tenant_id}", include_in_schema=False)
    def _internal_client_health(
        tenant_id: str,
        x_internal_secret: str = Header(alias="X-Internal-Secret", default=""),
    ):
        """Internal proxy used by the Tenant Portal to fetch client-health without
        a full admin JWT.  Validates X-Internal-Secret and delegates to the same
        DB query as the public /api/intelligence/client-health/{tenant_id} endpoint."""
        if not INTERNAL_SERVICE_SECRET or not secrets.compare_digest(
            x_internal_secret, INTERNAL_SERVICE_SECRET
        ):
            raise HTTPException(status_code=403, detail="Forbidden")

        # Re-use the same query logic as the public endpoint
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Resolve project UUID → human-readable name used in metering_efficiency
                cur.execute("SELECT name FROM projects WHERE id = %s", (tenant_id,))
                _proj_row = cur.fetchone()
                project_key = _proj_row["name"] if _proj_row else tenant_id

                # Efficiency
                cur.execute(
                    """
                    SELECT
                        COALESCE(AVG(overall_score), 0)::NUMERIC(5,2) AS avg_score,
                        CASE
                            WHEN AVG(overall_score) >= 80 THEN 'excellent'
                            WHEN AVG(overall_score) >= 60 THEN 'good'
                            WHEN AVG(overall_score) >= 40 THEN 'fair'
                            ELSE 'poor'
                        END AS classification
                    FROM metering_efficiency
                    WHERE collected_at >= NOW() - INTERVAL '7 days'
                      AND (project_name = %s OR project_name ILIKE %s)
                    """,
                    (project_key, f"%{project_key}%"),
                )
                eff = cur.fetchone() or {}

                # Stability
                cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE severity = 'critical') AS open_critical,
                        COUNT(*) FILTER (WHERE severity = 'high')     AS open_high,
                        COUNT(*) FILTER (WHERE severity = 'medium')   AS open_medium
                    FROM operational_insights
                    WHERE status IN ('open', 'acknowledged')
                      AND (
                        metadata->>'tenant_name' ILIKE %s
                        OR metadata->>'project_name' ILIKE %s
                        OR metadata->>'tenant_id'   = %s
                      )
                    """,
                    (f"%{tenant_id}%", f"%{tenant_id}%", tenant_id),
                )
                stab = cur.fetchone() or {}
                deductions = (
                    int(stab.get("open_critical") or 0) * 20
                    + int(stab.get("open_high") or 0) * 10
                    + int(stab.get("open_medium") or 0) * 5
                )
                stability_score = max(0.0, 100.0 - deductions)

                # Capacity runway — query last 14 days of quota rows, compute slope
                cur.execute(
                    """
                    SELECT project_id,
                           storage_used_gb,  storage_quota_gb,
                           vcpus_used,       vcpus_quota,
                           ram_used_mb,      ram_quota_mb,
                           instances_used,   instances_quota
                    FROM metering_quotas
                    WHERE collected_at >= NOW() - INTERVAL '14 days'
                      AND (project_id = %s OR project_name ILIKE %s)
                    ORDER BY project_id, collected_at ASC
                    """,
                    (tenant_id, f"%{tenant_id}%"),
                )
                q_rows = cur.fetchall() or []

                # quota_configured = True when project_quotas has at least one nova compute
                # resource (cores/ram/instances) with a positive limit for this project.
                # We use project_quotas (not metering_quotas) because metering_quota columns
                # are often NULL even when quotas ARE configured in OpenStack.
                cur.execute(
                    """
                    SELECT 1 FROM project_quotas
                    WHERE project_id = %s
                      AND service = 'nova'
                      AND resource IN ('cores', 'ram', 'instances')
                      AND quota_limit > 0
                    LIMIT 1
                    """,
                    (tenant_id,),
                )
                quota_configured: bool = cur.fetchone() is not None

        # Compute runway using the same helper as the public endpoint
        _QUOTA_RESOURCES = [
            ("vcpus",      "vcpus_used",      "vcpus_quota"),
            ("ram_mb",     "ram_used_mb",      "ram_quota_mb"),
            ("storage_gb", "storage_used_gb",  "storage_quota_gb"),
            ("instances",  "instances_used",   "instances_quota"),
        ]
        min_runway: Optional[int] = None
        min_runway_resource: Optional[str] = None

        if q_rows:
            from collections import defaultdict
            projects_rows: dict = defaultdict(list)
            for r in q_rows:
                projects_rows[r["project_id"]].append(r)
            for _pid, prows in projects_rows.items():
                if len(prows) < 3:
                    continue
                xs = list(range(len(prows)))
                for res_key, used_col, quota_col in _QUOTA_RESOURCES:
                    try:
                        ys    = [float(r[used_col] or 0) for r in prows]
                        quota = float(prows[-1][quota_col] or 0)
                        used  = ys[-1]
                        slope = _linear_forecast(xs, ys)
                        runway = _days_runway(used, quota, slope)
                        if runway is not None:
                            if min_runway is None or runway < min_runway:
                                min_runway = runway
                                min_runway_resource = res_key
                    except Exception:
                        pass

        return {
            "tenant_id": tenant_id,
            "efficiency_score": float(eff.get("avg_score") or 0),
            "efficiency_classification": eff.get("classification") or "unknown",
            "stability_score": stability_score,
            "open_critical": int(stab.get("open_critical") or 0),
            "open_high": int(stab.get("open_high") or 0),
            "open_medium": int(stab.get("open_medium") or 0),
            "capacity_runway_days": min_runway,
            "capacity_runway_resource": min_runway_resource,
            "quota_configured": quota_configured,
            "last_computed": datetime.utcnow().isoformat() + "Z",
        }
