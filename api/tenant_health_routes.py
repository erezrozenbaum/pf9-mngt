"""
Tenant Health Score Routes
==========================
Provides a composite 0-100 health score per tenant, broken down into
five weighted components:

  snapshot_compliance  (0-25)  — recent successful snapshot runs
  quota_headroom       (0-20)  — CPU/RAM utilisation headroom
  drift                (0-20)  — absence of recent drift events
  sla_tier             (0-20)  — active SLA commitment tier
  tickets              (0-15)  — open support-ticket burden

Scores are pre-computed by the scheduler worker every 4 hours and stored
in tenant_health_scores.  The API reads the latest stored value; it also
exposes a /recalculate endpoint for on-demand refresh.

RBAC
----
  GET  endpoints — tenants:read  (viewer, operator, admin, superadmin)
  POST /recalculate — tenants:write (admin, superadmin)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor

from auth import require_permission, User
from db_pool import get_connection

logger = logging.getLogger("pf9.tenant_health")

router = APIRouter(prefix="/api/tenants", tags=["tenant-health"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class HealthScoreOut(BaseModel):
    project_id: str
    score: int
    grade: str                      # A / B / C / D / F
    computed_at: str
    components: dict                # per-component breakdown
    details: dict


class HealthScoreHistoryItem(BaseModel):
    computed_at: str
    score: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _compute_score(conn, project_id: str) -> dict:
    """
    Compute a fresh health score for *project_id* using the live DB data.
    Returns a dict suitable for inserting into tenant_health_scores.
    """
    scores: dict = {}
    details: dict = {}

    with conn.cursor(cursor_factory=RealDictCursor) as cur:

        # 1. Snapshot compliance (0-25) ─────────────────────────────────────
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM   snapshot_records sr
            JOIN   snapshot_runs    ru ON ru.id = sr.snapshot_run_id
            WHERE  sr.project_id = %s
              AND  sr.status     = 'success'
              AND  ru.started_at >= NOW() - INTERVAL '7 days'
            """,
            (project_id,),
        )
        snap_cnt = (cur.fetchone() or {}).get("cnt", 0) or 0
        snap_score = 25 if snap_cnt > 0 else 0
        scores["snapshot_compliance"] = snap_score
        details["snapshot_compliance"] = {
            "recent_successes": int(snap_cnt),
            "window_days": 7,
        }

        # 2. Quota headroom (0-20) ───────────────────────────────────────────
        cur.execute(
            """
            SELECT vcpus_used, vcpus_quota, ram_used_mb, ram_quota_mb
            FROM   metering_quotas
            WHERE  project_id = %s
            ORDER BY collected_at DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cur.fetchone()
        if row and row["vcpus_quota"] and row["ram_quota_mb"]:
            cpu_pct = (row["vcpus_used"] or 0) / row["vcpus_quota"] * 100
            ram_pct = (row["ram_used_mb"] or 0) / row["ram_quota_mb"] * 100
            max_pct = max(cpu_pct, ram_pct)
            if max_pct < 60:
                quota_score = 20
            elif max_pct < 80:
                quota_score = 15
            elif max_pct < 90:
                quota_score = 8
            else:
                quota_score = 0
            details["quota_headroom"] = {
                "cpu_utilization_pct": round(cpu_pct, 1),
                "ram_utilization_pct": round(ram_pct, 1),
            }
        else:
            quota_score = 10  # no data → neutral score
            details["quota_headroom"] = {"note": "no_quota_data"}
        scores["quota_headroom"] = quota_score

        # 3. Drift (0-20) ────────────────────────────────────────────────────
        cur.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM   drift_events
            WHERE  project_id = %s
              AND  detected_at >= NOW() - INTERVAL '30 days'
            """,
            (project_id,),
        )
        drift_cnt = (cur.fetchone() or {}).get("cnt", 0) or 0
        if drift_cnt == 0:
            drift_score = 20
        elif drift_cnt <= 2:
            drift_score = 15
        elif drift_cnt <= 5:
            drift_score = 8
        else:
            drift_score = 0
        scores["drift"] = drift_score
        details["drift"] = {"events_30d": int(drift_cnt)}

        # 4. SLA tier (0-20) ─────────────────────────────────────────────────
        cur.execute(
            """
            SELECT tier
            FROM   sla_commitments
            WHERE  tenant_id  = %s
              AND  effective_to IS NULL
            ORDER BY effective_from DESC
            LIMIT 1
            """,
            (project_id,),
        )
        sla_row = cur.fetchone()
        tier = (sla_row or {}).get("tier", None)
        sla_map = {"gold": 20, "silver": 15, "bronze": 10}
        sla_score = sla_map.get((tier or "").lower(), 5)
        scores["sla_tier"] = sla_score
        details["sla_tier"] = {"tier": tier or "none"}

        # 5. Tickets (0-15) ──────────────────────────────────────────────────
        cur.execute(
            """
            SELECT priority, COUNT(*) AS cnt
            FROM   support_tickets
            WHERE  project_id = %s
              AND  status NOT IN ('closed', 'resolved')
            GROUP BY priority
            """,
            (project_id,),
        )
        open_tickets = {r["priority"]: int(r["cnt"]) for r in cur.fetchall()}
        total_open = sum(open_tickets.values())
        has_critical = open_tickets.get("critical", 0) > 0
        has_high = open_tickets.get("high", 0) > 0
        if total_open == 0:
            ticket_score = 15
        elif has_critical or has_high:
            ticket_score = 0
        elif total_open <= 2:
            ticket_score = 8
        else:
            ticket_score = 4
        scores["tickets"] = ticket_score
        details["tickets"] = {"open_by_priority": open_tickets}

    total = sum(scores.values())
    return {
        "score": total,
        "snapshot_compliance": scores["snapshot_compliance"],
        "quota_headroom": scores["quota_headroom"],
        "drift": scores["drift"],
        "sla_tier": scores["sla_tier"],
        "tickets": scores["tickets"],
        "details": details,
    }


def _store_score(conn, project_id: str, result: dict) -> None:
    """Upsert the computed score into tenant_health_scores."""
    import json
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenant_health_scores
                (project_id, computed_at, score,
                 snapshot_compliance, quota_headroom, drift, sla_tier, tickets,
                 details)
            VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id, computed_at) DO NOTHING
            """,
            (
                project_id,
                result["score"],
                result["snapshot_compliance"],
                result["quota_headroom"],
                result["drift"],
                result["sla_tier"],
                result["tickets"],
                json.dumps(result["details"]),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{project_id}/health-score", response_model=HealthScoreOut)
async def get_tenant_health_score(
    project_id: str,
    current_user: User = Depends(require_permission("tenants", "read")),
):
    """Return the latest pre-computed health score for a tenant."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Validate project exists
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project {project_id!r} not found",
                )

            cur.execute(
                """
                SELECT project_id, computed_at, score,
                       snapshot_compliance, quota_headroom, drift, sla_tier, tickets,
                       details
                FROM   tenant_health_scores
                WHERE  project_id = %s
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                (project_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Health score not yet computed for this tenant. "
                   "Use POST /health-score/recalculate to trigger.",
        )

    return HealthScoreOut(
        project_id=row["project_id"],
        score=row["score"],
        grade=_grade(row["score"]),
        computed_at=row["computed_at"].isoformat(),
        components={
            "snapshot_compliance": row["snapshot_compliance"],
            "quota_headroom": row["quota_headroom"],
            "drift": row["drift"],
            "sla_tier": row["sla_tier"],
            "tickets": row["tickets"],
        },
        details=row["details"] or {},
    )


@router.post("/{project_id}/health-score/recalculate", response_model=HealthScoreOut)
async def recalculate_tenant_health_score(
    project_id: str,
    current_user: User = Depends(require_permission("tenants", "write")),
):
    """Trigger an immediate health score recomputation for a tenant."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project {project_id!r} not found",
                )

        result = _compute_score(conn, project_id)
        _store_score(conn, project_id, result)

    logger.info(
        "Health score recalculated: project=%s score=%d",
        project_id, result["score"],
    )
    return HealthScoreOut(
        project_id=project_id,
        score=result["score"],
        grade=_grade(result["score"]),
        computed_at=datetime.now(timezone.utc).isoformat(),
        components={
            "snapshot_compliance": result["snapshot_compliance"],
            "quota_headroom": result["quota_headroom"],
            "drift": result["drift"],
            "sla_tier": result["sla_tier"],
            "tickets": result["tickets"],
        },
        details=result["details"],
    )


@router.get("/{project_id}/health-score/history", response_model=List[HealthScoreHistoryItem])
async def get_tenant_health_score_history(
    project_id: str,
    limit: int = 30,
    current_user: User = Depends(require_permission("tenants", "read")),
):
    """Return historical health score data (default: last 30 data points)."""
    if limit < 1 or limit > 365:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 365")

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project {project_id!r} not found",
                )

            cur.execute(
                """
                SELECT computed_at, score
                FROM   tenant_health_scores
                WHERE  project_id = %s
                ORDER BY computed_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
            rows = cur.fetchall()

    return [
        HealthScoreHistoryItem(
            computed_at=r["computed_at"].isoformat(),
            score=r["score"],
        )
        for r in rows
    ]
