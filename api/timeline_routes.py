"""
Operational Event Timeline Routes
==================================
Provides a unified chronological view of all infrastructure events harvested
from source tables by intelligence_worker's TimelineHarvester.

Endpoints
---------
  GET /api/timeline               — paginated event list with filters
  GET /api/timeline/correlated    — blast-radius events around a timestamp
  GET /api/timeline/stats         — aggregate counts by category + severity

RBAC
----
  All endpoints: timeline:read (all roles)

Visibility filtering (enforced server-side based on role)
  viewer / operator           → operational only
  technical / admin           → operational + billing
  admin                       → operational + billing + security
  superadmin                  → all (operational + billing + security + system)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, status
from psycopg2.extras import RealDictCursor

from auth import require_permission, User, get_effective_region_filter

from db_pool import get_connection

logger = logging.getLogger("pf9.timeline")

router = APIRouter(prefix="/api/timeline", tags=["timeline"])

# ---------------------------------------------------------------------------
# Role → allowed visibility levels (cumulative)
# ---------------------------------------------------------------------------
_VISIBILITY_FOR_ROLE: dict[str, list[str]] = {
    "viewer":          ["operational"],
    "operator":        ["operational"],
    "technical":       ["operational", "billing"],
    "admin":           ["operational", "billing", "security"],
    "superadmin":      ["operational", "billing", "security", "system"],
    "account_manager": ["operational"],
    "executive":       ["operational"],
}

_DEFAULT_VISIBILITY = ["operational"]


def _allowed_visibilities(user: User) -> list[str]:
    role = user.role if hasattr(user, "role") else (user.get("role") if isinstance(user, dict) else "viewer")
    return _VISIBILITY_FOR_ROLE.get(role, _DEFAULT_VISIBILITY)


# ---------------------------------------------------------------------------
# Row serialiser
# ---------------------------------------------------------------------------

def _row_to_event(row: dict) -> dict:
    def _ts(v):
        return v.isoformat() if v else None

    return {
        "id":           row["id"],
        "event_id":     str(row["event_id"]),
        "occurred_at":  _ts(row["occurred_at"]),
        "recorded_at":  _ts(row["recorded_at"]),
        "event_type":   row["event_type"],
        "category":     row["category"],
        "severity":     row["severity"],
        "title":        row["title"],
        "description":  row.get("description"),
        "metadata":     row.get("metadata") or {},
        "entity_type":  row["entity_type"],
        "entity_id":    row["entity_id"],
        "entity_name":  row.get("entity_name"),
        "domain_id":    row.get("domain_id"),
        "domain_name":  row.get("domain_name"),
        "project_id":   row.get("project_id"),
        "project_name": row.get("project_name"),
        "region_id":    row["region_id"],
        "source":       row["source"],
        "actor":        row.get("actor"),
        "visibility":   row["visibility"],
    }


# ---------------------------------------------------------------------------
# GET /api/timeline
# ---------------------------------------------------------------------------

@router.get("")
def list_timeline(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    domain_id: Optional[str] = Query(None),
    project_id: Optional[str] = Query(None),
    region_id: Optional[str] = Query(None),
    from_ts: Optional[str] = Query(None, alias="from", description="ISO datetime, default now()-24h"),
    to_ts: Optional[str] = Query(None, alias="to", description="ISO datetime, default now()"),
    category: Optional[str] = Query(None, description="Comma-separated list of categories"),
    severity: Optional[str] = Query(None, pattern="^(info|warning|critical)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("timeline", "read")),
):
    """Return a paginated list of operational events matching the given filters."""
    uname = user.username if hasattr(user, "username") else user.get("username", "")
    effective_region = get_effective_region_filter(uname, region_id)

    # Time range defaults
    try:
        ts_to = datetime.fromisoformat(to_ts) if to_ts else datetime.now(timezone.utc)
        ts_from = datetime.fromisoformat(from_ts) if from_ts else ts_to - timedelta(hours=24)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid datetime format: {exc}",
        ) from exc

    allowed_vis = _allowed_visibilities(user)
    conditions = [
        "occurred_at >= %s",
        "occurred_at <= %s",
        "visibility = ANY(%s)",
    ]
    params: list = [ts_from, ts_to, allowed_vis]

    if effective_region:
        conditions.append("region_id = %s")
        params.append(effective_region)

    if domain_id:
        conditions.append("domain_id = %s")
        params.append(domain_id)

    if project_id:
        conditions.append("project_id = %s")
        params.append(project_id)

    if entity_type:
        conditions.append("entity_type = %s")
        params.append(entity_type)

    if entity_id:
        conditions.append("(entity_id = %s OR entity_name ILIKE %s)")
        params.extend([entity_id, entity_id])

    if severity:
        conditions.append("severity = %s")
        params.append(severity)

    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        if cats:
            conditions.append("category = ANY(%s)")
            params.append(cats)

    where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"SELECT *, COUNT(*) OVER() AS total_count FROM operational_events {where} ORDER BY occurred_at DESC LIMIT %s OFFSET %s"  # nosec B608 — {where} built from hardcoded condition strings; all values parameterised
            cur.execute(sql, params + [limit, offset])
            rows = cur.fetchall()

    total = int(rows[0]["total_count"]) if rows else 0
    events = [_row_to_event(dict(r)) for r in rows]
    return {
        "events":   events,
        "total":    total,
        "limit":    limit,
        "offset":   offset,
        "has_more": (offset + len(events)) < total,
    }


# ---------------------------------------------------------------------------
# GET /api/timeline/correlated
# Fetch events in the blast-radius of a given entity around a timestamp.
# ---------------------------------------------------------------------------

@router.get("/correlated")
def correlated_events(
    entity_type: str = Query(...),
    entity_id: str = Query(...),
    ts: str = Query(..., description="ISO datetime — centre of the time window"),
    window_minutes: int = Query(60, ge=5, le=1440, description="±minutes around ts"),
    region_id: Optional[str] = Query(None),
    user: User = Depends(require_permission("timeline", "read")),
):
    """
    Return events temporally correlated with a given entity around a timestamp.

    Looks up all events where:
      - entity matches (entity_type + entity_id) OR same domain_id
      - occurred_at is within ±window_minutes of the provided ts
      - visibility is allowed for the caller's role
    """
    uname = user.username if hasattr(user, "username") else user.get("username", "")
    effective_region = get_effective_region_filter(uname, region_id)

    try:
        centre = datetime.fromisoformat(ts)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid datetime format: {exc}",
        ) from exc

    delta = timedelta(minutes=window_minutes)
    ts_from = centre - delta
    ts_to = centre + delta

    allowed_vis = _allowed_visibilities(user)

    # Fetch domain_id for the requested entity so we can widen to same-tenant events
    domain_id: Optional[str] = None
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT domain_id FROM operational_events
                WHERE entity_type = %s AND entity_id = %s AND domain_id IS NOT NULL
                LIMIT 1
                """,
                [entity_type, entity_id],
            )
            row = cur.fetchone()
            if row:
                domain_id = row["domain_id"]

    conditions = [
        "occurred_at >= %s",
        "occurred_at <= %s",
        "visibility = ANY(%s)",
    ]
    params: list = [ts_from, ts_to, allowed_vis]

    if effective_region:
        conditions.append("region_id = %s")
        params.append(effective_region)

    # Entity match OR same-tenant match
    if domain_id:
        conditions.append("(entity_id = %s OR domain_id = %s)")
        params.extend([entity_id, domain_id])
    else:
        conditions.append("entity_id = %s")
        params.append(entity_id)

    where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"SELECT * FROM operational_events {where} ORDER BY occurred_at DESC LIMIT 200"  # nosec B608 — {where} built from hardcoded condition strings; all values parameterised
            cur.execute(sql, params)
            rows = cur.fetchall()

    return {
        "events":         [_row_to_event(dict(r)) for r in rows],
        "total":          len(rows),
        "centre_ts":      centre.isoformat(),
        "window_minutes": window_minutes,
    }


# ---------------------------------------------------------------------------
# GET /api/timeline/stats
# Aggregate counts for dashboard widgets.
# ---------------------------------------------------------------------------

@router.get("/stats")
def timeline_stats(
    domain_id: Optional[str] = Query(None),
    region_id: Optional[str] = Query(None),
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    user: User = Depends(require_permission("timeline", "read")),
):
    """Return event counts grouped by category and severity for the given scope/time range."""
    uname = user.username if hasattr(user, "username") else user.get("username", "")
    effective_region = get_effective_region_filter(uname, region_id)

    try:
        ts_to = datetime.fromisoformat(to_ts) if to_ts else datetime.now(timezone.utc)
        ts_from = datetime.fromisoformat(from_ts) if from_ts else ts_to - timedelta(hours=24)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid datetime format: {exc}",
        ) from exc

    allowed_vis = _allowed_visibilities(user)
    conditions = [
        "occurred_at >= %s",
        "occurred_at <= %s",
        "visibility = ANY(%s)",
    ]
    params: list = [ts_from, ts_to, allowed_vis]

    if effective_region:
        conditions.append("region_id = %s")
        params.append(effective_region)

    if domain_id:
        conditions.append("domain_id = %s")
        params.append(domain_id)

    where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"SELECT category, severity, COUNT(*) AS cnt FROM operational_events {where} GROUP BY category, severity ORDER BY category, severity"  # nosec B608 — {where} built from hardcoded condition strings; all values parameterised
            cur.execute(sql, params)
            rows = cur.fetchall()

    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    total = 0

    for r in rows:
        cat = r["category"]
        sev = r["severity"]
        cnt = int(r["cnt"])
        by_category[cat] = by_category.get(cat, 0) + cnt
        by_severity[sev] = by_severity.get(sev, 0) + cnt
        total += cnt

    return {
        "by_category": by_category,
        "by_severity": by_severity,
        "total":       total,
        "from":        ts_from.isoformat(),
        "to":          ts_to.isoformat(),
    }
