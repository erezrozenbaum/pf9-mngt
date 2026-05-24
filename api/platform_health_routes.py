"""
Platform Self-Monitoring Health Endpoint  (v2.7.0)

GET /api/admin/platform/health
-------------------------------
Returns a health snapshot of the platform's own infrastructure:
  - Database connectivity + round-trip latency
  - Redis connectivity + round-trip latency
  - Worker last-run status (snapshot, backup, inventory, intelligence)
  - DB pool stats

RBAC: requires ``monitoring:read`` (admin, superadmin, operator).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from auth import require_permission
from db_pool import get_connection

logger = logging.getLogger("pf9.platform_health")

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Redis URL re-uses the same env var as cache.py
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


# ---------------------------------------------------------------------------
# Component checkers
# ---------------------------------------------------------------------------

def _check_database() -> dict[str, Any]:
    """Execute a lightweight round-trip query; return latency or error."""
    try:
        t0 = time.monotonic()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        logger.warning("platform_health: db check failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _check_redis() -> dict[str, Any]:
    """Ping Redis; return latency or error."""
    try:
        import redis  # lazy import — optional dependency

        r = redis.from_url(
            _REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        t0 = time.monotonic()
        r.ping()
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        return {"status": "ok", "latency_ms": latency_ms}
    except ImportError:
        return {"status": "unavailable", "error": "redis package not installed"}
    except Exception as exc:
        logger.warning("platform_health: redis check failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _worker_status() -> list[dict[str, Any]]:
    """
    Query last-run metadata for each background worker from the DB.

    Returns a list of worker status dicts.  Failures are caught per-worker
    so one bad query can't suppress the others.
    """
    workers: list[dict[str, Any]] = []

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                # ── Inventory collector ──────────────────────────────────
                try:
                    cur.execute(
                        """
                        SELECT status, started_at, finished_at, source,
                               duration_seconds
                        FROM inventory_runs
                        ORDER BY started_at DESC
                        LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        workers.append({
                            "worker": "inventory_collector",
                            "last_run_at": row["started_at"].isoformat()
                            if row["started_at"] else None,
                            "status": row["status"] or "unknown",
                            "details": {
                                "source": row["source"],
                                "duration_seconds": row["duration_seconds"],
                            },
                        })
                    else:
                        workers.append({"worker": "inventory_collector", "status": "never_run"})
                except Exception as exc:
                    workers.append({"worker": "inventory_collector", "status": "query_error", "error": str(exc)})
                    conn.rollback()

                # ── Snapshot worker ───────────────────────────────────────
                try:
                    cur.execute(
                        """
                        SELECT status, started_at, finished_at, run_type,
                               snapshots_created, snapshots_failed
                        FROM snapshot_runs
                        ORDER BY started_at DESC
                        LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        workers.append({
                            "worker": "snapshot_worker",
                            "last_run_at": row["started_at"].isoformat()
                            if row["started_at"] else None,
                            "status": row["status"] or "unknown",
                            "details": {
                                "run_type": row["run_type"],
                                "created": row["snapshots_created"],
                                "failed": row["snapshots_failed"],
                            },
                        })
                    else:
                        workers.append({"worker": "snapshot_worker", "status": "never_run"})
                except Exception as exc:
                    workers.append({"worker": "snapshot_worker", "status": "query_error", "error": str(exc)})
                    conn.rollback()

                # ── Backup worker ─────────────────────────────────────────
                try:
                    cur.execute(
                        """
                        SELECT status, started_at, completed_at,
                               backup_type, backup_target, duration_seconds
                        FROM backup_history
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        workers.append({
                            "worker": "backup_worker",
                            "last_run_at": row["started_at"].isoformat()
                            if row["started_at"] else None,
                            "status": row["status"] or "unknown",
                            "details": {
                                "backup_type": row["backup_type"],
                                "backup_target": row["backup_target"],
                                "duration_seconds": row["duration_seconds"],
                            },
                        })
                    else:
                        workers.append({"worker": "backup_worker", "status": "never_run"})
                except Exception as exc:
                    workers.append({"worker": "backup_worker", "status": "query_error", "error": str(exc)})
                    conn.rollback()

                # ── Intelligence / SLA worker (via harvest cursors) ───────
                try:
                    cur.execute(
                        """
                        SELECT source, last_ts, updated_at
                        FROM timeline_harvest_cursors
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    )
                    row = cur.fetchone()
                    if row:
                        workers.append({
                            "worker": "intelligence_worker",
                            "last_run_at": row["updated_at"].isoformat()
                            if row["updated_at"] else None,
                            "status": "ok",
                            "details": {"source": row["source"]},
                        })
                    else:
                        workers.append({"worker": "intelligence_worker", "status": "never_run"})
                except Exception as exc:
                    workers.append({"worker": "intelligence_worker", "status": "query_error", "error": str(exc)})
                    conn.rollback()

    except Exception as exc:
        logger.warning("platform_health: worker status query failed: %s", exc)
        workers.append({"worker": "all", "status": "query_error", "error": str(exc)})

    return workers


def _db_pool_stats() -> dict[str, Any]:
    """Return DB connection pool statistics."""
    try:
        from db_pool import _pool  # noqa: PLC0415  (internal access)
        if _pool is None:
            return {"status": "not_initialized"}
        return {
            "status": "ok",
            "min_conn": _pool.minconn,
            "max_conn": _pool.maxconn,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/platform/health")
def get_platform_health(
    current_user=Depends(require_permission("monitoring", "read")),
):
    """
    Platform self-monitoring health snapshot.

    Returns DB latency, Redis latency, background-worker last-run status,
    and DB connection pool statistics.

    Requires ``monitoring:read`` (admin / superadmin / operator).
    """
    db = _check_database()
    redis = _check_redis()
    workers = _worker_status()
    pool_stats = _db_pool_stats()

    # Overall: degraded if any critical component is down
    overall = "healthy"
    if db["status"] != "ok":
        overall = "degraded"
    elif redis["status"] == "error":
        overall = "degraded"
    elif any(w.get("status") in ("failed", "error", "query_error") for w in workers):
        overall = "degraded"

    return {
        "overall": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "components": {
            "database": db,
            "redis": redis,
            "db_pool": pool_stats,
        },
        "workers": workers,
    }
