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
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from auth import require_permission, get_current_user, User
from db_pool import get_connection
from intelligence_utils import types_for_department, VALID_DEPARTMENTS

logger = logging.getLogger("pf9.intelligence")

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

@router.get("/insights")
def list_insights(
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    department: Optional[str] = Query(None, pattern="^(support|engineering|operations|general)$"),
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
        # Department workspace filter — applies only when no explicit type filter given
        dept_types = types_for_department(department)
        if dept_types is not None:
            conditions.append("type = ANY(%s)")
            params.append(dept_types)

    if entity_type:
        conditions.append("entity_type = %s")
        params.append(entity_type)

    if tenant_id:
        # Match tenant-scoped insights (entity_id or metadata reference)
        conditions.append("(entity_id = %s OR (entity_type = 'tenant' AND entity_id = %s))")
        params.extend([tenant_id, tenant_id])

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    offset = (page - 1) * page_size

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT *, COUNT(*) OVER() AS total_count
                FROM operational_insights
                {where}
                ORDER BY
                    CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                                   WHEN 'medium' THEN 3 ELSE 4 END,
                    last_seen_at DESC
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
    type_clause = "AND type = ANY(%s)" if dept_types is not None else ""
    base_params: list = [dept_types] if dept_types is not None else []

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
            """, (user.username, insight_id))
            row = cur.fetchone()
            conn.commit()

    if not row:
        raise HTTPException(status_code=404, detail="Insight not found or not in open/snoozed state")
    logger.info("Insight %d acknowledged by %s", insight_id, user.username)
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
    logger.info("Insight %d snoozed until %s by %s", insight_id, snooze_dt, user.username)
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
    logger.info("Insight %d resolved by %s", insight_id, user.username)
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
