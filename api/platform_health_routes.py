"""
Platform Self-Monitoring Health Endpoint  (v2.7.0)

GET /api/admin/platform/health
-------------------------------
Returns a health snapshot of the platform's own infrastructure:
  - Database connectivity + round-trip latency
  - Redis connectivity + round-trip latency
  - Worker last-run status (snapshot, backup, inventory, intelligence)
  - DB pool stats

GET /api/admin/platform/metrics
---------------------------------
Proxies Prometheus range-query API to return pod CPU/RAM time-series,
PVC utilisation, and HTTP request rate for all pods in the configured
Kubernetes namespace (default: pf9-mngt).  Returns prometheus_available=false
gracefully when Prometheus is unreachable (local dev / Docker Compose).

RBAC: requires ``monitoring:read`` (admin, superadmin, operator).
"""

from __future__ import annotations

import logging
import os
import time
import urllib.request
import urllib.parse
import json as _json
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


# ---------------------------------------------------------------------------
# Prometheus proxy helpers
# ---------------------------------------------------------------------------

_PROMETHEUS_URL = os.getenv(
    "PROMETHEUS_URL",
    "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090",
)
_K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "pf9-mngt")
# How many seconds of history to return for sparklines (default 1 h)
_METRICS_RANGE_S = 3600
# Step between data-points (seconds) — 60 s gives 60 points per sparkline
_METRICS_STEP_S = 60


def _prom_query_range(query: str, start: float, end: float, step: int) -> list[list]:
    """
    Execute a Prometheus range query and return a list of (timestamp, value)
    pairs for the first result series.  Returns [] on any error.
    """
    params = urllib.parse.urlencode({
        "query": query,
        "start": start,
        "end": end,
        "step": step,
    })
    url = f"{_PROMETHEUS_URL}/api/v1/query_range?{params}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = _json.loads(resp.read())
        results = body.get("data", {}).get("result", [])
        if results:
            return [[float(ts), float(val)] for ts, val in results[0]["values"]]
        return []
    except Exception as exc:
        logger.debug("Prometheus range query failed (%s): %s", query[:80], exc)
        return []


def _prom_query_instant(query: str) -> list[dict]:
    """
    Execute a Prometheus instant query and return the raw result list.
    Returns [] on any error.
    """
    params = urllib.parse.urlencode({"query": query})
    url = f"{_PROMETHEUS_URL}/api/v1/query?{params}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = _json.loads(resp.read())
        return body.get("data", {}).get("result", [])
    except Exception as exc:
        logger.debug("Prometheus instant query failed (%s): %s", query[:80], exc)
        return []


def _prometheus_available() -> bool:
    """Quick liveness check — hit /-/ready on the Prometheus server."""
    url = f"{_PROMETHEUS_URL}/-/ready"
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Metrics route
# ---------------------------------------------------------------------------

@router.get("/platform/metrics")
def get_platform_metrics(
    _user=Depends(require_permission("monitoring", "read")),
):
    """
    Return Prometheus-backed pod metrics (CPU, RAM sparklines per pod),
    PVC utilisation, and HTTP request rate for the configured K8s namespace.
    Falls back gracefully with prometheus_available=false when Prometheus
    is unreachable (e.g. local Docker Compose dev environment).
    """
    if not _prometheus_available():
        return {"prometheus_available": False, "pods": [], "pvcs": [], "http_rps_series": []}

    ns = _K8S_NAMESPACE
    end = time.time()
    start = end - _METRICS_RANGE_S
    step = _METRICS_STEP_S

    # ── Discover all pods in the namespace ──────────────────────────────────
    pod_results = _prom_query_instant(
        f'container_cpu_usage_seconds_total{{namespace="{ns}",container!="",container!="POD"}}'
    )
    pod_names: list[str] = sorted({r["metric"].get("pod", "") for r in pod_results if r["metric"].get("pod")})

    # ── Per-pod CPU + RAM sparklines ─────────────────────────────────────────
    pods: list[dict[str, Any]] = []
    for pod in pod_names:
        cpu_series = _prom_query_range(
            f'sum(rate(container_cpu_usage_seconds_total{{namespace="{ns}",pod="{pod}",container!="",container!="POD"}}[5m]))',
            start, end, step,
        )
        ram_series = _prom_query_range(
            f'sum(container_memory_working_set_bytes{{namespace="{ns}",pod="{pod}",container!="",container!="POD"}})',
            start, end, step,
        )
        # Derive a stable short name (strip replica-set / deployment hash suffix)
        short = pod
        parts = pod.rsplit("-", 2)
        if len(parts) == 3 and len(parts[1]) in (5, 10) and len(parts[2]) == 5:
            short = parts[0]
        elif len(parts) >= 2 and len(parts[-1]) == 5:
            short = "-".join(parts[:-1])

        pods.append({
            "pod": pod,
            "short_name": short,
            "cpu_series": cpu_series,     # [[ts, cores], ...]
            "ram_series": ram_series,     # [[ts, bytes], ...]
        })

    # ── PVC utilisation ──────────────────────────────────────────────────────
    used_results = _prom_query_instant(
        f'kubelet_volume_stats_used_bytes{{namespace="{ns}"}}'
    )
    cap_results = _prom_query_instant(
        f'kubelet_volume_stats_capacity_bytes{{namespace="{ns}"}}'
    )
    cap_map: dict[str, float] = {
        r["metric"].get("persistentvolumeclaim", ""): float(r["value"][1])
        for r in cap_results
    }
    pvcs: list[dict[str, Any]] = []
    for r in used_results:
        name = r["metric"].get("persistentvolumeclaim", "")
        used = float(r["value"][1])
        cap = cap_map.get(name, 0)
        pvcs.append({
            "name": name,
            "used_bytes": used,
            "capacity_bytes": cap,
            "pct": round(used / cap * 100, 1) if cap > 0 else 0,
        })
    pvcs.sort(key=lambda x: x["pct"], reverse=True)

    # ── HTTP request rate (nginx-ingress or kube metrics) ────────────────────
    http_rps_series = _prom_query_range(
        f'sum(rate(container_network_receive_packets_total{{namespace="{ns}"}}[5m]))',
        start, end, step,
    )

    return {
        "prometheus_available": True,
        "namespace": ns,
        "range_seconds": _METRICS_RANGE_S,
        "step_seconds": step,
        "pods": pods,
        "pvcs": pvcs,
        "http_rps_series": http_rps_series,
    }
