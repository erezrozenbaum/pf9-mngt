"""Admin endpoints for SLA defense alerts."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from db_pool import get_connection

router = APIRouter(prefix="/api/admin/sla/defense", tags=["sla-defense"])


class AlertActionBody(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


@router.get("/alerts")
def list_alerts(
    status: Optional[str] = Query(None, description="open|resolved|dismissed"),
    project_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _user: User = Depends(require_permission("sla", "read")),
):
    sql = """
        SELECT a.id, a.project_id, p.name AS project_name,
               a.sla_id, a.insight_id, a.threat_type, a.threat_detail,
               a.severity, a.status, a.triggered_at, a.resolved_at, a.resolution_note
        FROM sla_defense_alerts a
        LEFT JOIN projects p ON p.id = a.project_id
        WHERE (%(status)s IS NULL OR a.status = %(status)s)
          AND (%(project_id)s IS NULL OR a.project_id = %(project_id)s)
        ORDER BY a.triggered_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    params = {
        "status": status,
        "project_id": project_id,
        "limit": limit,
        "offset": offset,
    }

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

    return {"items": rows, "limit": limit, "offset": offset, "count": len(rows)}


@router.get("/alerts/summary")
def alerts_summary(
    _user: User = Depends(require_permission("sla", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT severity, COUNT(*)::int AS count
                FROM sla_defense_alerts
                WHERE status = 'open'
                GROUP BY severity
                """
            )
            rows = [dict(r) for r in cur.fetchall()]

    out = {"warning": 0, "critical": 0}
    for r in rows:
        sev = r.get("severity")
        if sev in out:
            out[sev] = int(r.get("count", 0))

    return {"open": out, "total_open": out["warning"] + out["critical"]}


@router.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(
    alert_id: int,
    body: AlertActionBody,
    _user: User = Depends(require_permission("sla", "write")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sla_defense_alerts
                SET status = 'dismissed',
                    resolved_at = NOW(),
                    resolution_note = COALESCE(%s, 'dismissed by operator')
                WHERE id = %s AND status = 'open'
                """,
                (body.note, alert_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Open SLA defense alert not found")
        conn.commit()

    return {"ok": True, "id": alert_id, "status": "dismissed"}


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(
    alert_id: int,
    body: AlertActionBody,
    _user: User = Depends(require_permission("sla", "write")),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sla_defense_alerts
                SET status = 'resolved',
                    resolved_at = NOW(),
                    resolution_note = COALESCE(%s, 'resolved by operator')
                WHERE id = %s AND status IN ('open', 'dismissed')
                """,
                (body.note, alert_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="SLA defense alert not found")
        conn.commit()

    return {"ok": True, "id": alert_id, "status": "resolved"}
