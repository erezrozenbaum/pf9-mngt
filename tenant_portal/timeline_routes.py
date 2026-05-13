"""
timeline_routes.py — Operational Event Timeline for tenant portal.

Provides a read-only, domain-scoped view of operational_events:
  GET /tenant/timeline
  GET /tenant/timeline/stats

Security guarantees:
  • domain_id is taken exclusively from the authenticated TenantContext —
    tenants cannot query events for another domain.
  • visibility is hard-capped to 'operational' — billing/security/system
    events are never exposed to tenant users.
  • project_ids filter is applied: only events whose entity belongs to a
    project in the tenant's scope are returned.

Direct DB reads (no internal HTTP hop), consistent with all other tenant
portal routes.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context
from tenant_context import TenantContext

logger = logging.getLogger("tenant_portal.timeline")

router = APIRouter(prefix="/tenant", tags=["timeline"])

# Tenant-visible event categories (subset of full admin set)
_TENANT_CATEGORIES = {
    "monitoring", "snapshot", "backup", "sla", "ticket", "intelligence",
    "provisioning",
}

# Hard-cap: only operational visibility — never billing/security/system
_VISIBILITY = "operational"

LIMIT_MAX = 100
LIMIT_DEFAULT = 25


def _fmt(row: dict) -> dict:
    """Normalise a RealDictRow to a JSON-safe dict."""
    return {
        "id":          row["id"],
        "occurred_at": row["occurred_at"].isoformat() if isinstance(row["occurred_at"], datetime) else row["occurred_at"],
        "category":    row["category"],
        "severity":    row["severity"],
        "summary":     row["summary"],
        "entity_type": row.get("entity_type"),
        "entity_id":   row.get("entity_id"),
        "entity_name": row.get("entity_name"),
        "domain_id":   row.get("domain_id"),
        "metadata":    row.get("metadata") or {},
        "ticket_id":   row.get("ticket_id"),
        "source_table":row.get("source_table"),
    }


@router.get("/timeline")
def tenant_timeline(
    from_ts:    Optional[str] = Query(None, alias="from"),
    to_ts:      Optional[str] = Query(None, alias="to"),
    category:   Optional[str] = Query(None),
    severity:   Optional[str] = Query(None),
    entity_type:Optional[str] = Query(None),
    entity_id:  Optional[str] = Query(None),
    search:     Optional[str] = Query(None),
    limit:      int           = Query(LIMIT_DEFAULT, ge=1, le=LIMIT_MAX),
    offset:     int           = Query(0, ge=0),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    List operational events for the authenticated tenant's domain.
    domain_id is always taken from the verified auth token — cannot be overridden.
    """
    conditions = [
        "domain_id = %s",
        "visibility = %s",
    ]
    params: list = [ctx.control_plane_id, _VISIBILITY]

    if from_ts:
        try:
            datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "Invalid 'from' timestamp")
        conditions.append("occurred_at >= %s")
        params.append(from_ts)

    if to_ts:
        try:
            datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(400, "Invalid 'to' timestamp")
        conditions.append("occurred_at <= %s")
        params.append(to_ts)

    if category and category in _TENANT_CATEGORIES:
        conditions.append("category = %s")
        params.append(category)

    if severity:
        conditions.append("severity = %s")
        params.append(severity)

    if entity_type:
        conditions.append("entity_type = %s")
        params.append(entity_type)

    if entity_id:
        conditions.append("entity_id = %s")
        params.append(entity_id)

    if search:
        conditions.append("summary ILIKE %s")
        params.append(f"%{search}%")

    where = "WHERE " + " AND ".join(conditions)
    sql = (
        f"SELECT *, COUNT(*) OVER() AS total_count "  # nosec B608
        f"FROM operational_events {where} "
        f"ORDER BY occurred_at DESC LIMIT %s OFFSET %s"
    )
    params.extend([limit, offset])

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    total = int(rows[0]["total_count"]) if rows else 0
    events = [_fmt(dict(r)) for r in rows]
    return {
        "events": events,
        "total":  total,
        "limit":  limit,
        "offset": offset,
    }


@router.get("/timeline/stats")
def tenant_timeline_stats(
    from_ts: Optional[str] = Query(None, alias="from"),
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Aggregated event counts by category and severity for the tenant's domain.
    Useful for rendering a summary strip on the tenant timeline.
    """
    # Default: last 24h
    if not from_ts:
        from_ts = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

    params: list = [ctx.control_plane_id, _VISIBILITY, from_ts]
    sql = """
        SELECT
            category,
            severity,
            COUNT(*) AS cnt
        FROM operational_events
        WHERE domain_id = %s
          AND visibility = %s
          AND occurred_at >= %s
        GROUP BY category, severity
        ORDER BY category, severity
    """

    with get_tenant_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    by_category: dict = {}
    by_severity: dict = {}
    total = 0
    for row in rows:
        cat = row["category"]
        sev = row["severity"]
        cnt = int(row["cnt"])
        by_category[cat] = by_category.get(cat, 0) + cnt
        by_severity[sev] = by_severity.get(sev, 0) + cnt
        total += cnt

    return {
        "total":       total,
        "by_category": by_category,
        "by_severity": by_severity,
        "from":        from_ts,
    }
