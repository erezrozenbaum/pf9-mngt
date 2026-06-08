"""
Tenant Health Score Routes
==========================
Provides a composite 0-100 health score per tenant, broken down into
six weighted components:

  snapshot_compliance  (0-25)  — recent successful snapshot runs
  quota_headroom       (0-20)  — CPU/RAM utilisation headroom
  drift                (0-20)  — absence of recent drift events
  sla_tier             (0-20)  — active SLA commitment tier
  tickets              (0-15)  — open support-ticket burden
    security_posture     (0-15)  — MFA coverage, exposed ports, OS image recency

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
from shared.health_scoring import compute_security_posture_component

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


class HealthScoreWeightsOut(BaseModel):
    snapshot_compliance: int
    quota_headroom: int
    drift: int
    sla_tier: int
    tickets: int
    security_posture: int
    total: int


class HealthScoreWeightsIn(BaseModel):
    snapshot_compliance: int
    quota_headroom: int
    drift: int
    sla_tier: int
    tickets: int
    security_posture: int


class HealthScoreToggleIn(BaseModel):
    disabled: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS = {
    "snapshot_compliance": 22,
    "quota_headroom": 18,
    "drift": 18,
    "sla_tier": 17,
    "tickets": 10,
    "security_posture": 15,
}


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


def _compute_score(conn, project_id: str, weights: Optional[dict] = None) -> dict:
    """
    Compute a fresh health score for *project_id* using the live DB data.
    Optionally accepts *weights* dict; if None, falls back to _DEFAULT_WEIGHTS.
    Returns a dict suitable for inserting into tenant_health_scores.
    """
    if weights is None:
        weights = dict(_DEFAULT_WEIGHTS)
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

        # 6. Security posture (0-15) ───────────────────────────────────────
        cur.execute(
            """
            SELECT
                COUNT(DISTINCT u.id) AS total_users,
                COUNT(DISTINCT u.id) FILTER (WHERE um.is_enabled IS TRUE) AS mfa_enabled_users
            FROM role_assignments ra
            JOIN users u ON u.id = ra.user_id
            LEFT JOIN user_mfa um ON um.username = u.name
            WHERE ra.project_id = %s
              AND ra.user_id IS NOT NULL
            """,
            (project_id,),
        )
        mfa_row = cur.fetchone() or {}

        cur.execute(
            """
            SELECT COUNT(DISTINCT s.id) AS exposed_vm_count
            FROM servers s
            JOIN ports p ON p.device_id = s.id
            JOIN security_group_rules sgr
              ON p.raw_json::jsonb->'security_groups' ? sgr.security_group_id
            WHERE s.project_id = %s
              AND sgr.direction = 'ingress'
              AND COALESCE(sgr.remote_ip_prefix, '0.0.0.0/0') IN ('0.0.0.0/0', '::/0')
              AND (
                    sgr.protocol IS NULL OR LOWER(sgr.protocol) = 'tcp'
                  )
              AND (
                    (COALESCE(sgr.port_range_min, 22) <= 22 AND COALESCE(sgr.port_range_max, 22) >= 22)
                    OR
                    (COALESCE(sgr.port_range_min, 3389) <= 3389 AND COALESCE(sgr.port_range_max, 3389) >= 3389)
                  )
            """,
            (project_id,),
        )
        exposed_row = cur.fetchone() or {}

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_vm_count,
                COUNT(*) FILTER (
                    WHERE COALESCE(i.updated_at, i.created_at) < NOW() - INTERVAL '180 days'
                ) AS stale_vm_count
            FROM servers s
            LEFT JOIN images i ON i.id = s.image_id
            WHERE s.project_id = %s
            """,
            (project_id,),
        )
        image_row = cur.fetchone() or {}

        security_component = compute_security_posture_component(
            mfa_enabled_users=(mfa_row.get("mfa_enabled_users") or 0),
            mfa_total_users=(mfa_row.get("total_users") or 0),
            exposed_vm_count=(exposed_row.get("exposed_vm_count") or 0),
            stale_vm_count=(image_row.get("stale_vm_count") or 0),
            total_vm_count=(image_row.get("total_vm_count") or 0),
        )
        scores["security_posture"] = security_component["score"]
        details["security_posture"] = security_component["details"]

    # Apply configured weights (scale proportionally to each component's default max)
    scaled = {
        "snapshot_compliance": _scale_component(scores["snapshot_compliance"], _DEFAULT_WEIGHTS["snapshot_compliance"], weights["snapshot_compliance"]),
        "quota_headroom":      _scale_component(scores["quota_headroom"],      _DEFAULT_WEIGHTS["quota_headroom"],      weights["quota_headroom"]),
        "drift":               _scale_component(scores["drift"],               _DEFAULT_WEIGHTS["drift"],               weights["drift"]),
        "sla_tier":            _scale_component(scores["sla_tier"],            _DEFAULT_WEIGHTS["sla_tier"],            weights["sla_tier"]),
        "tickets":             _scale_component(scores["tickets"],             _DEFAULT_WEIGHTS["tickets"],             weights["tickets"]),
        "security_posture":    _scale_component(scores["security_posture"],    _DEFAULT_WEIGHTS["security_posture"],    weights["security_posture"]),
    }
    total = sum(scaled.values())
    return {
        "score": total,
        "snapshot_compliance": scaled["snapshot_compliance"],
        "quota_headroom":      scaled["quota_headroom"],
        "drift":               scaled["drift"],
        "sla_tier":            scaled["sla_tier"],
        "tickets":             scaled["tickets"],
        "security_posture":    scaled["security_posture"],
        "details": details,
    }


def _get_health_score_weights(conn) -> dict:
    """Load health score component weights from system_settings (falls back to defaults)."""
    weights = dict(_DEFAULT_WEIGHTS)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT key, value FROM system_settings WHERE key LIKE 'health_score.weight.%'"
            )
            for row in cur.fetchall():
                component = row["key"].replace("health_score.weight.", "")
                if component in weights:
                    try:
                        weights[component] = max(0, int(row["value"]))
                    except (ValueError, TypeError):
                        pass
    except Exception:
        pass  # always fall back to defaults
    return weights


def _scale_component(raw_score: int, default_max: int, configured_weight: int) -> int:
    """Scale a component's raw score proportionally to its configured weight."""
    if default_max == 0:
        return 0
    return round(raw_score / default_max * configured_weight)


def _store_score(conn, project_id: str, result: dict) -> None:
    """Upsert the computed score into tenant_health_scores."""
    import json
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenant_health_scores
                (project_id, computed_at, score,
                 snapshot_compliance, quota_headroom, drift, sla_tier, tickets, security_posture,
                 details)
            VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s)
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
                result["security_posture"],
                json.dumps(result["details"]),
            ),
        )
    conn.commit()


def _auto_resolve_health_score_insights(conn, project_id: str, score: int) -> list[str]:
    """
    Resolve open health-score insights when a tenant score recovers above
    hysteresis thresholds.

    Returns a list of resolved insight types.
    """
    resolved_types: list[str] = []
    thresholds = [
        ("health_score_critical", 45),
        # Keep both types for backward compatibility with older rows.
        ("health_score_low", 65),
        ("health_score_warning", 65),
    ]

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for insight_type, recovery_threshold in thresholds:
            if score <= recovery_threshold:
                continue
            cur.execute(
                """
                UPDATE operational_insights
                   SET status = 'resolved',
                       resolved_at = NOW(),
                       metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                 WHERE type = %s
                   AND entity_type = 'project'
                   AND entity_id = %s
                   AND status IN ('open', 'acknowledged', 'snoozed')
                """,
                (
                    (
                        '{"resolved_by":"auto","resolution_note":"Health score recovered"}'
                    ),
                    insight_type,
                    project_id,
                ),
            )
            if cur.rowcount > 0:
                resolved_types.append(insight_type)

    if resolved_types:
        conn.commit()
        try:
            from event_bus import emit_event  # lazy import to avoid startup cycles

            emit_event(
                event_type="health.score_recovered",
                category="intelligence",
                severity="info",
                title="Tenant health score recovered",
                description=(
                    f"Health score recovered to {score}/100 and auto-resolved "
                    f"{len(resolved_types)} insight(s)."
                ),
                entity_type="project",
                entity_id=project_id,
                project_id=project_id,
                source="api",
                metadata={
                    "score": score,
                    "resolved_types": resolved_types,
                    "resolution_note": "Health score recovered",
                },
            )
        except Exception:
            logger.debug(
                "Failed to emit health.score_recovered event for project=%s",
                project_id,
                exc_info=True,
            )

    return resolved_types


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
                      security_posture,
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
            "security_posture": row.get("security_posture", 0),
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

        result = _compute_score(conn, project_id, _get_health_score_weights(conn))
        _store_score(conn, project_id, result)
        resolved = _auto_resolve_health_score_insights(conn, project_id, result["score"])

    logger.info(
        "Health score recalculated: project=%s score=%d auto_resolved=%s",
        project_id,
        result["score"],
        ",".join(resolved) if resolved else "none",
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
            "security_posture": result["security_posture"],
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


# ---------------------------------------------------------------------------
# Health score weights admin settings
# ---------------------------------------------------------------------------

@router.get("/health-score/weights", response_model=HealthScoreWeightsOut, tags=["admin-settings"])
async def get_health_score_weights(
    current_user: User = Depends(require_permission("tenants", "read")),
):
    """Return the current health score component weights (superadmin-configurable)."""
    with get_connection() as conn:
        w = _get_health_score_weights(conn)
    return HealthScoreWeightsOut(
        snapshot_compliance=w["snapshot_compliance"],
        quota_headroom=w["quota_headroom"],
        drift=w["drift"],
        sla_tier=w["sla_tier"],
        tickets=w["tickets"],
        security_posture=w["security_posture"],
        total=sum(w.values()),
    )


@router.put("/health-score/weights", response_model=HealthScoreWeightsOut, tags=["admin-settings"])
async def update_health_score_weights(
    body: HealthScoreWeightsIn,
    current_user: User = Depends(require_permission("tenants", "write")),
):
    """Update health score component weights. Only superadmin role should use this."""
    total = (
        body.snapshot_compliance
        + body.quota_headroom
        + body.drift
        + body.sla_tier
        + body.tickets
        + body.security_posture
    )
    if total < 1:
        raise HTTPException(status_code=422, detail="Weights must sum to at least 1")

    updates = [
        ("health_score.weight.snapshot_compliance", body.snapshot_compliance),
        ("health_score.weight.quota_headroom",      body.quota_headroom),
        ("health_score.weight.drift",               body.drift),
        ("health_score.weight.sla_tier",            body.sla_tier),
        ("health_score.weight.tickets",             body.tickets),
        ("health_score.weight.security_posture",    body.security_posture),
    ]
    with get_connection() as conn:
        with conn.cursor() as cur:
            for key, val in updates:
                cur.execute(
                    """INSERT INTO system_settings (key, value)
                       VALUES (%s, %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                    (key, str(val)),
                )
        conn.commit()
        w = _get_health_score_weights(conn)

    logger.info(
        "Health score weights updated by %s: snap=%d quota=%d drift=%d sla=%d tickets=%d security=%d",
        current_user.username,
        body.snapshot_compliance, body.quota_headroom, body.drift,
        body.sla_tier, body.tickets, body.security_posture,
    )
    return HealthScoreWeightsOut(
        snapshot_compliance=w["snapshot_compliance"],
        quota_headroom=w["quota_headroom"],
        drift=w["drift"],
        sla_tier=w["sla_tier"],
        tickets=w["tickets"],
        security_posture=w["security_posture"],
        total=sum(w.values()),
    )


# ---------------------------------------------------------------------------
# Per-tenant health score disable toggle
# ---------------------------------------------------------------------------

@router.put("/{project_id}/health-score/toggle", tags=["tenant-health"])
async def toggle_tenant_health_score(
    project_id: str,
    body: HealthScoreToggleIn,
    current_user: User = Depends(require_permission("tenants", "write")),
):
    """Enable or disable health score computation for a specific tenant."""
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project {project_id!r} not found",
                )
            cur.execute(
                "UPDATE projects SET health_score_disabled = %s WHERE id = %s",
                (body.disabled, project_id),
            )
        conn.commit()

    logger.info(
        "Health score %s for project=%s by %s",
        "disabled" if body.disabled else "enabled",
        project_id,
        current_user.username,
    )
    return {"project_id": project_id, "health_score_disabled": body.disabled}
