"""
Capacity Engine — storage growth forecasting.

For each project, fits a linear trend to the last 14 days of metering_quotas
and projects how many days until storage hits 90 % of quota.  Fires insights
at different severity thresholds:

  ≤ 7 days  → critical
  8–14 days → high
  15–30 days→ medium
  > 30 days → no insight (resolved if one was previously open)
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.capacity")

_INSIGHT_TYPE = "capacity"


def _linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """
    Simple least-squares linear regression.
    Returns (slope, intercept) where y ≈ slope * x + intercept.
    """
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    sx  = sum(xs)
    sy  = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _days_to_pct(current_used: float, quota: float,
                  trend_per_day: float, target_pct: float = 90.0) -> Optional[float]:
    """
    How many days at current trend until storage reaches target_pct of quota?
    Returns None if quota is unknown/zero or trend is flat/negative.
    """
    if not quota or quota <= 0 or trend_per_day <= 0:
        return None
    target_gb   = quota * target_pct / 100.0
    gap_gb      = target_gb - current_used
    if gap_gb <= 0:
        return 0.0  # already at / above target
    return gap_gb / trend_per_day


class CapacityEngine(BaseEngine):

    def run(self) -> None:
        projects = self._load_projects()
        log.info("CapacityEngine: evaluating %d project(s)", len(projects))
        for proj in projects:
            try:
                self._evaluate_project(proj)
            except Exception as exc:
                log.warning("CapacityEngine: error on project %s: %s",
                            proj.get("project_id"), exc)

    def _load_projects(self) -> list:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT project_id, project_name
                FROM metering_quotas
                WHERE collected_at >= NOW() - INTERVAL '14 days'
                  AND project_id IS NOT NULL
            """)
            return [dict(r) for r in cur.fetchall()]

    def _evaluate_project(self, proj: dict) -> None:
        project_id   = proj["project_id"]
        project_name = proj["project_name"] or project_id

        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    EXTRACT(EPOCH FROM collected_at) AS ts,
                    storage_quota_gb,
                    storage_used_gb
                FROM metering_quotas
                WHERE project_id = %s
                  AND collected_at >= NOW() - INTERVAL '14 days'
                  AND storage_quota_gb IS NOT NULL
                  AND storage_used_gb  IS NOT NULL
                ORDER BY collected_at ASC
            """, (project_id,))
            rows = cur.fetchall()

        if len(rows) < 7:
            # Not enough data points for a reliable forecast.
            self.suppress_resolved(_INSIGHT_TYPE, "project", project_id)
            return

        quota     = float(rows[-1]["storage_quota_gb"])
        used_now  = float(rows[-1]["storage_used_gb"])
        current_pct = (used_now / quota * 100) if quota else 0

        if quota <= 0:
            return

        # Normalise timestamps to days-since-first-point for numerical stability
        t0    = float(rows[0]["ts"])
        xs    = [(float(r["ts"]) - t0) / 86400.0 for r in rows]
        ys    = [float(r["storage_used_gb"]) for r in rows]
        slope, _intercept = _linear_regression(xs, ys)

        days = _days_to_pct(used_now, quota, slope)

        if days is None or days > 30:
            self.suppress_resolved(_INSIGHT_TYPE, "project", project_id)
            return

        if days <= 0:
            severity = "critical"
        elif days <= 7:
            severity = "critical"
        elif days <= 14:
            severity = "high"
        else:
            severity = "medium"

        days_int = max(0, int(days))
        title = (
            f"Storage critical: {project_name} hits 90% capacity in {days_int} day(s)"
            if severity == "critical"
            else f"Storage {'warning' if severity == 'high' else 'trend'}: "
                 f"{project_name} projected to hit 90% in {days_int} day(s)"
        )
        message = (
            f"Project {project_name!r} is using {used_now:.0f} GB of {quota:.0f} GB quota "
            f"({current_pct:.1f}%). At the current growth rate of {slope:.1f} GB/day, "
            f"storage will reach 90% capacity in approximately {days_int} day(s)."
        )

        self.upsert_insight(
            type=_INSIGHT_TYPE,
            severity=severity,
            entity_type="project",
            entity_id=project_id,
            entity_name=project_name,
            title=title,
            message=message,
            metadata={
                "current_pct":     round(current_pct, 1),
                "days_to_90":      days_int,
                "trend_gb_per_day": round(slope, 2),
                "data_points":     len(rows),
                "quota_gb":        quota,
                "used_gb":         used_now,
            },
        )
