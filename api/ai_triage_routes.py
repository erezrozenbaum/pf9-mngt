"""API routes for AI incident triage briefs."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from psycopg2.extras import RealDictCursor

from auth import User, create_access_token, require_permission
from db_pool import get_connection

router = APIRouter(prefix="/api/copilot", tags=["copilot-triage"])


class BriefDismissBody(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


class BriefExecuteBody(BaseModel):
    dry_run: bool = True
    parameters: dict = Field(default_factory=dict)


def _where_for_status(status: Optional[str]) -> tuple[str, list]:
    if not status:
        return "", []
    st = status.lower().strip()
    if st == "open":
        return " AND b.dismissed_at IS NULL AND b.executed_runbook_id IS NULL ", []
    if st == "dismissed":
        return " AND b.dismissed_at IS NOT NULL ", []
    if st == "executed":
        return " AND b.executed_runbook_id IS NOT NULL ", []
    raise HTTPException(status_code=400, detail="status must be one of: open, dismissed, executed")


@router.get("/briefs")
def list_briefs(
    status: Optional[str] = Query(None, description="open|dismissed|executed"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    hours: int = Query(48, ge=1, le=168),
    _user: User = Depends(require_permission("copilot", "read")),
):
    where_extra, params_extra = _where_for_status(status)

    sql = (
        """
        SELECT b.id, b.event_id, b.event_type, b.entity_name,
               b.project_id, b.project_name, b.analysis, b.recommendation,
               b.risk_level, b.runbook_name, b.generated_at, b.delivered_at,
               b.dismissed_by, b.dismissed_at, b.executed_runbook_id,
               re.execution_id AS runbook_execution_id
        FROM incident_briefs b
        LEFT JOIN runbook_executions re ON re.id = b.executed_runbook_id
        WHERE b.generated_at > NOW() - (%s || ' hours')::interval
        """
        + where_extra
        + " ORDER BY b.generated_at DESC LIMIT %s OFFSET %s"
    )
    params = [hours] + params_extra + [limit, offset]

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

    for r in rows:
        for key in ("generated_at", "delivered_at", "dismissed_at"):
            if r.get(key) and hasattr(r[key], "isoformat"):
                r[key] = r[key].isoformat()

    return {"items": rows, "limit": limit, "offset": offset, "count": len(rows)}


@router.get("/briefs/summary")
def briefs_summary(
    hours: int = Query(48, ge=1, le=168),
    _user: User = Depends(require_permission("copilot", "read")),
):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  COUNT(*) FILTER (WHERE dismissed_at IS NULL AND executed_runbook_id IS NULL)::int AS open,
                  COUNT(*) FILTER (WHERE dismissed_at IS NOT NULL)::int AS dismissed,
                  COUNT(*) FILTER (WHERE executed_runbook_id IS NOT NULL)::int AS executed
                FROM incident_briefs
                WHERE generated_at > NOW() - (%s || ' hours')::interval
                """,
                (hours,),
            )
            row = dict(cur.fetchone() or {})

    open_count = int(row.get("open") or 0)
    dismissed_count = int(row.get("dismissed") or 0)
    executed_count = int(row.get("executed") or 0)

    return {
        "open": open_count,
        "dismissed": dismissed_count,
        "executed": executed_count,
        "total": open_count + dismissed_count + executed_count,
    }


@router.post("/briefs/{brief_id}/dismiss")
def dismiss_brief(
    brief_id: int,
    body: BriefDismissBody,
    current_user: User = Depends(require_permission("copilot", "write")),
):
    username = current_user.username if hasattr(current_user, "username") else str(current_user)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE incident_briefs
                SET dismissed_by = %s,
                    dismissed_at = NOW(),
                    recommendation = CASE
                        WHEN %s IS NULL OR %s = '' THEN recommendation
                        ELSE recommendation || E'\n\n[Dismiss note] ' || %s
                    END
                WHERE id = %s
                  AND dismissed_at IS NULL
                  AND executed_runbook_id IS NULL
                """,
                (username, body.note, body.note, body.note, brief_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Open incident brief not found")
        conn.commit()

    return {"ok": True, "id": brief_id, "status": "dismissed"}


@router.post("/briefs/{brief_id}/execute")
async def execute_brief(
    brief_id: int,
    body: BriefExecuteBody,
    request: Request,
    current_user: User = Depends(require_permission("copilot", "write")),
):
    username = current_user.username if hasattr(current_user, "username") else str(current_user)
    role = current_user.role if hasattr(current_user, "role") else "operator"

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, runbook_name, executed_runbook_id
                FROM incident_briefs
                WHERE id = %s
                """,
                (brief_id,),
            )
            brief = cur.fetchone()
            if not brief:
                raise HTTPException(status_code=404, detail="Incident brief not found")
            brief = dict(brief)
            if brief.get("executed_runbook_id") is not None:
                raise HTTPException(status_code=409, detail="Incident brief already executed")
            runbook_name = (brief.get("runbook_name") or "").strip()
            if not runbook_name:
                raise HTTPException(status_code=400, detail="Incident brief has no runbook suggestion")

    service_token = create_access_token(
        data={"sub": username, "role": role, "is_active": True, "service_call": True},
        expires_delta=timedelta(minutes=5),
    )

    try:
        # Persist short-lived token hash for session checks used by auth middleware.
        import hashlib

        token_hash = hashlib.sha256(service_token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_sessions (username, role, token_hash, is_active, expires_at, created_at)
                    VALUES (%s, %s, %s, true, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (username, role, token_hash, now + timedelta(minutes=5), now),
                )
            conn.commit()
    except Exception:
        pass

    payload = {
        "runbook_name": runbook_name,
        "dry_run": body.dry_run,
        "parameters": body.parameters,
    }
    api_base = os.environ.get("INTERNAL_API_BASE", "http://localhost:8000")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{api_base}/api/runbooks/trigger",
                json=payload,
                headers={"Authorization": f"Bearer {service_token}"},
            )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail=f"Runbook error: {exc.response.text}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Runbook service unavailable: {exc}")

    execution_id = result.get("execution_id") or result.get("id")
    if not execution_id:
        raise HTTPException(status_code=500, detail="Runbook trigger did not return execution identifier")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM runbook_executions WHERE execution_id = %s", (str(execution_id),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=500, detail="Could not map runbook execution to database row")
            runbook_pk = int(row["id"])
            cur.execute(
                """
                UPDATE incident_briefs
                SET executed_runbook_id = %s
                WHERE id = %s
                """,
                (runbook_pk, brief_id),
            )
        conn.commit()

    return {
        "ok": True,
        "id": brief_id,
        "runbook_name": runbook_name,
        "execution_id": execution_id,
        "runbook_execution_pk": runbook_pk,
        "result": result,
    }
