"""
Anomaly Detection Engine — Phase 3

Simple threshold + delta anomaly detection without external ML libraries.

Detectors:
  F1 — Snapshot size spike   : project snapshot count grows > 50% week-over-week
  F2 — VM count spike        : project instances_used grows > 20% in 48 hours
  F3 — API error rate spike  : API error rate increases > 3× the rolling 7-day baseline

Insight type: anomaly
Entity types:
  F1/F2 → project
  F3    → service (endpoint group)

Rolling averages are computed on-the-fly from existing metering tables.
No external baseline table is required.
"""
from __future__ import annotations

import logging

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.anomaly")

_INSIGHT_TYPE = "anomaly"

# Thresholds
_SNAPSHOT_SPIKE_PCT  = 0.50   # > 50% WoW growth
_VM_SPIKE_PCT        = 0.20   # > 20% growth in 48 h
_API_ERROR_MULTIPLIER = 3.0   # error rate > 3× 7-day baseline
_API_MIN_CALLS       = 10     # ignore endpoints with very low call volume


class AnomalyEngine(BaseEngine):

    def run(self) -> None:
        try:
            self._check_snapshot_spikes()
        except Exception as exc:
            log.warning("AnomalyEngine F1 failed: %s", exc)
        try:
            self._check_vm_count_spikes()
        except Exception as exc:
            log.warning("AnomalyEngine F2 failed: %s", exc)
        try:
            self._check_api_error_spikes()
        except Exception as exc:
            log.warning("AnomalyEngine F3 failed: %s", exc)

    # ------------------------------------------------------------------
    # F1 — Snapshot size spike (>50% week-over-week)
    # ------------------------------------------------------------------

    def _check_snapshot_spikes(self) -> None:
        """
        Compare snapshot count (from metering_quotas.snapshots_used) for the
        last 7 days vs the prior 7 days per project.
        """
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                WITH recent AS (
                    SELECT project_id, project_name,
                           AVG(snapshots_used)  AS avg_recent
                    FROM metering_quotas
                    WHERE collected_at >= NOW() - INTERVAL '7 days'
                      AND snapshots_used IS NOT NULL
                    GROUP BY project_id, project_name
                ),
                baseline AS (
                    SELECT project_id,
                           AVG(snapshots_used)  AS avg_baseline
                    FROM metering_quotas
                    WHERE collected_at >= NOW() - INTERVAL '14 days'
                      AND collected_at  < NOW() - INTERVAL '7 days'
                      AND snapshots_used IS NOT NULL
                    GROUP BY project_id
                )
                SELECT r.project_id, r.project_name,
                       r.avg_recent, b.avg_baseline,
                       CASE WHEN b.avg_baseline > 0
                            THEN (r.avg_recent - b.avg_baseline) / b.avg_baseline
                            ELSE NULL END AS growth_ratio
                FROM recent r
                JOIN baseline b ON b.project_id = r.project_id
                WHERE b.avg_baseline > 0
                  AND r.avg_recent > b.avg_baseline * (1 + %s)
            """, (_SNAPSHOT_SPIKE_PCT,))
            spikes = cur.fetchall()

        log.debug("AnomalyEngine F1: %d snapshot spike(s)", len(spikes))
        seen_projects = set()
        for row in spikes:
            project_id   = row["project_id"]
            project_name = row["project_name"] or project_id
            ratio        = float(row["growth_ratio"] or 0)
            recent_avg   = float(row["avg_recent"] or 0)
            baseline_avg = float(row["avg_baseline"] or 0)
            seen_projects.add(project_id)

            severity = "high" if ratio >= 1.0 else "medium"
            self.upsert_insight(
                type=f"{_INSIGHT_TYPE}_snapshot_spike",
                severity=severity,
                entity_type="project",
                entity_id=project_id,
                entity_name=project_name,
                title=(
                    f"Snapshot spike: {project_name} snapshot count grew "
                    f"{ratio * 100:.0f}% week-over-week"
                ),
                message=(
                    f"Project {project_name!r} averaged {recent_avg:.0f} snapshots "
                    f"in the last 7 days compared to {baseline_avg:.0f} in the prior 7 days "
                    f"— a {ratio * 100:.0f}% increase. "
                    f"This may indicate runaway snapshot policies, ungoverned manual snapshots, "
                    f"or a storage cost risk."
                ),
                metadata={
                    "avg_recent_snapshots":   round(recent_avg, 1),
                    "avg_baseline_snapshots": round(baseline_avg, 1),
                    "growth_pct":             round(ratio * 100, 1),
                    "project":                project_name,
                },
            )

        # Resolve for projects where spike condition no longer holds
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT entity_id FROM operational_insights
                WHERE type = %s AND status IN ('open','acknowledged','snoozed')
            """, (f"{_INSIGHT_TYPE}_snapshot_spike",))
            active_ids = {r[0] for r in cur.fetchall()}

        for eid in active_ids - seen_projects:
            self.suppress_resolved(f"{_INSIGHT_TYPE}_snapshot_spike", "project", eid)

    # ------------------------------------------------------------------
    # F2 — VM count spike (>20% growth in 48 h)
    # ------------------------------------------------------------------

    def _check_vm_count_spikes(self) -> None:
        """
        Compare current instances_used vs 48-hour-ago value per project.
        """
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                WITH current AS (
                    SELECT project_id, project_name, instances_used AS current_vms
                    FROM metering_quotas
                    WHERE collected_at = (
                        SELECT MAX(collected_at) FROM metering_quotas
                        WHERE collected_at <= NOW()
                    )
                      AND instances_used IS NOT NULL
                ),
                before AS (
                    SELECT project_id,
                           AVG(instances_used) AS vms_48h_ago
                    FROM metering_quotas
                    WHERE collected_at >= NOW() - INTERVAL '50 hours'
                      AND collected_at  < NOW() - INTERVAL '46 hours'
                      AND instances_used IS NOT NULL
                    GROUP BY project_id
                )
                SELECT c.project_id, c.project_name,
                       c.current_vms, b.vms_48h_ago,
                       (c.current_vms - b.vms_48h_ago) AS delta,
                       CASE WHEN b.vms_48h_ago > 0
                            THEN (c.current_vms - b.vms_48h_ago) / b.vms_48h_ago
                            ELSE NULL END AS growth_ratio
                FROM current c
                JOIN before b ON b.project_id = c.project_id
                WHERE b.vms_48h_ago > 0
                  AND c.current_vms > b.vms_48h_ago * (1 + %s)
                  AND (c.current_vms - b.vms_48h_ago) >= 2
            """, (_VM_SPIKE_PCT,))
            spikes = cur.fetchall()

        log.debug("AnomalyEngine F2: %d VM spike(s)", len(spikes))
        seen_projects = set()
        for row in spikes:
            project_id   = row["project_id"]
            project_name = row["project_name"] or project_id
            ratio        = float(row["growth_ratio"] or 0)
            current_vms  = float(row["current_vms"] or 0)
            before_vms   = float(row["vms_48h_ago"] or 0)
            delta        = float(row["delta"] or 0)
            seen_projects.add(project_id)

            severity = "high" if ratio >= 0.5 else "medium"
            self.upsert_insight(
                type=f"{_INSIGHT_TYPE}_vm_spike",
                severity=severity,
                entity_type="project",
                entity_id=project_id,
                entity_name=project_name,
                title=(
                    f"VM count spike: {project_name} grew by "
                    f"{int(delta)} VM(s) in 48 hours ({ratio * 100:.0f}%)"
                ),
                message=(
                    f"Project {project_name!r} went from {int(before_vms)} to "
                    f"{int(current_vms)} active instances in 48 hours "
                    f"— a {ratio * 100:.0f}% increase. "
                    f"Rapid provisioning without a governance review may indicate "
                    f"uncontrolled scaling, a misconfigured automation, or a security event."
                ),
                metadata={
                    "current_vms":  int(current_vms),
                    "vms_48h_ago":  int(before_vms),
                    "delta":        int(delta),
                    "growth_pct":   round(ratio * 100, 1),
                    "project":      project_name,
                },
            )

        # Resolve stale VM-spike insights
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT entity_id FROM operational_insights
                WHERE type = %s AND status IN ('open','acknowledged','snoozed')
            """, (f"{_INSIGHT_TYPE}_vm_spike",))
            active_ids = {r[0] for r in cur.fetchall()}

        for eid in active_ids - seen_projects:
            self.suppress_resolved(f"{_INSIGHT_TYPE}_vm_spike", "project", eid)

    # ------------------------------------------------------------------
    # F3 — API error rate spike (>3× baseline)
    # ------------------------------------------------------------------

    def _check_api_error_spikes(self) -> None:
        """
        Compare error rate in the last 4 hours vs the 7-day rolling baseline
        per endpoint prefix (grouped by first path segment).
        """
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                WITH recent AS (
                    SELECT
                        SPLIT_PART(endpoint, '/', 3) AS service,
                        SUM(total_calls)  AS total,
                        SUM(error_count)  AS errors
                    FROM metering_api_usage
                    WHERE collected_at >= NOW() - INTERVAL '4 hours'
                      AND total_calls > 0
                    GROUP BY 1
                    HAVING SUM(total_calls) >= %s
                ),
                baseline AS (
                    SELECT
                        SPLIT_PART(endpoint, '/', 3) AS service,
                        SUM(total_calls)                              AS total,
                        SUM(error_count)                              AS errors,
                        NULLIF(SUM(error_count), 0)::float /
                            NULLIF(SUM(total_calls), 0)               AS error_rate
                    FROM metering_api_usage
                    WHERE collected_at >= NOW() - INTERVAL '7 days'
                      AND collected_at  < NOW() - INTERVAL '4 hours'
                      AND total_calls > 0
                    GROUP BY 1
                    HAVING SUM(total_calls) >= %s
                )
                SELECT
                    r.service,
                    r.total  AS recent_calls,
                    r.errors AS recent_errors,
                    CASE WHEN r.total > 0 THEN r.errors::float / r.total ELSE 0 END
                                             AS recent_rate,
                    b.error_rate             AS baseline_rate
                FROM recent r
                JOIN baseline b ON b.service = r.service
                WHERE b.error_rate > 0
                  AND (CASE WHEN r.total > 0 THEN r.errors::float / r.total ELSE 0 END)
                       > b.error_rate * %s
            """, (_API_MIN_CALLS, _API_MIN_CALLS * 10, _API_ERROR_MULTIPLIER))
            spikes = cur.fetchall()

        log.debug("AnomalyEngine F3: %d API error spike(s)", len(spikes))
        seen_services = set()
        for row in spikes:
            service       = row["service"] or "unknown"
            recent_rate   = float(row["recent_rate"] or 0)
            baseline_rate = float(row["baseline_rate"] or 0)
            ratio         = recent_rate / baseline_rate if baseline_rate > 0 else 0
            recent_calls  = int(row["recent_calls"] or 0)
            recent_errors = int(row["recent_errors"] or 0)
            seen_services.add(service)

            severity = "critical" if ratio >= 5.0 else "high"
            self.upsert_insight(
                type=f"{_INSIGHT_TYPE}_api_errors",
                severity=severity,
                entity_type="service",
                entity_id=f"api_{service}",
                entity_name=f"/{service} API",
                title=(
                    f"API error spike on /{service}: "
                    f"{recent_rate * 100:.1f}% error rate ({ratio:.1f}× baseline)"
                ),
                message=(
                    f"The /{service} API recorded {recent_errors} errors "
                    f"out of {recent_calls} calls in the last 4 hours "
                    f"({recent_rate * 100:.1f}% error rate). "
                    f"The 7-day baseline error rate is {baseline_rate * 100:.1f}%. "
                    f"This is {ratio:.1f}× above baseline. "
                    f"Investigate API gateway logs, upstream services, and recent deployments."
                ),
                metadata={
                    "service":         service,
                    "recent_calls":    recent_calls,
                    "recent_errors":   recent_errors,
                    "recent_rate_pct": round(recent_rate * 100, 2),
                    "baseline_rate_pct": round(baseline_rate * 100, 2),
                    "spike_ratio":     round(ratio, 2),
                },
            )

        # Resolve stale API-error insights
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT entity_id FROM operational_insights
                WHERE type = %s AND status IN ('open','acknowledged','snoozed')
            """, (f"{_INSIGHT_TYPE}_api_errors",))
            active_ids = {r[0] for r in cur.fetchall()}

        expected_ids = {f"api_{s}" for s in seen_services}
        for eid in active_ids - expected_ids:
            self.suppress_resolved(f"{_INSIGHT_TYPE}_api_errors", "service", eid)
