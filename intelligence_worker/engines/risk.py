"""
Risk Engine — proactive risk detection.

Three detectors:
  C1 — Snapshot coverage gap  : VMs with volumes but no snapshot in 7 days
  C2 — Health score decline   : health_score drop ≥ 15 points vs last run
  C3 — Unacknowledged critical drift: unack'd critical drift events < 48 h old
"""
from __future__ import annotations

import json
import logging

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.risk")

_TYPE_SNAP_GAP   = "risk_snapshot_gap"
_TYPE_HEALTH     = "risk_health_decline"
_TYPE_DRIFT      = "risk_unack_drift"

# Key used to store previous health score in insight metadata for comparison
_HEALTH_META_KEY = "previous_score"


class RiskEngine(BaseEngine):

    def run(self) -> None:
        self._check_snapshot_coverage()
        self._check_health_decline()
        self._check_unacknowledged_drift()

    # ------------------------------------------------------------------
    # C1 — Snapshot coverage gap
    # ------------------------------------------------------------------
    def _check_snapshot_coverage(self) -> None:
        """Tenants with VMs that have volumes but no snapshot in the last 7 days."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        s.project_id,
                        p.name AS project_name,
                        COUNT(DISTINCT s.id) AS uncovered_vms
                    FROM servers s
                    LEFT JOIN projects p ON p.id = s.project_id
                    WHERE s.project_id IS NOT NULL
                      AND s.status = 'ACTIVE'
                      AND EXISTS (
                          SELECT 1 FROM volumes v WHERE v.project_id = s.project_id
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM snapshots sn
                          WHERE sn.project_id = s.project_id
                            AND sn.created_at >= NOW() - INTERVAL '7 days'
                      )
                    GROUP BY s.project_id, p.name
                    HAVING COUNT(DISTINCT s.id) > 0
                """)
                rows = cur.fetchall()
        except Exception as exc:
            log.warning("snapshot_coverage query failed: %s", exc)
            return

        log.debug("RiskEngine C1: %d tenant(s) with snapshot gaps", len(rows))
        for row in rows:
            project_id   = row["project_id"]
            project_name = row["project_name"] or project_id
            count        = row["uncovered_vms"]
            title = (
                f"Tenant {project_name} has {count} VM(s) with no snapshot "
                f"coverage in the last 7 days"
            )
            message = (
                f"{count} active VM(s) in project {project_name!r} have volumes but "
                f"no snapshots were taken in the past 7 days. "
                f"These VMs have no recent restore point. "
                f"Check your snapshot schedule or create manual snapshots."
            )
            self.upsert_insight(
                type=_TYPE_SNAP_GAP,
                severity="high",
                entity_type="tenant",
                entity_id=project_id,
                entity_name=project_name,
                title=title,
                message=message,
                metadata={"uncovered_vms": count},
            )

    # ------------------------------------------------------------------
    # C2 — Health score decline
    # ------------------------------------------------------------------
    def _check_health_decline(self) -> None:
        """
        Fire when v_tenant_health.health_score drops ≥ 15 points vs the
        previous score stored in the existing insight metadata.
        """
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT project_id, health_score,
                           p.name AS project_name
                    FROM v_tenant_health vh
                    JOIN projects p ON p.id = vh.project_id
                    WHERE vh.project_id IS NOT NULL
                """)
                current = {r["project_id"]: dict(r) for r in cur.fetchall()}
        except Exception as exc:
            log.warning("health_decline fetch failed: %s", exc)
            return

        # Retrieve previously stored scores from existing open insights
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT entity_id, metadata
                    FROM operational_insights
                    WHERE type = %s
                      AND status IN ('open','acknowledged','snoozed')
                """, (_TYPE_HEALTH,))
                prev_insights = {r["entity_id"]: r["metadata"] for r in cur.fetchall()}
        except Exception:
            prev_insights = {}

        for project_id, row in current.items():
            score_now  = row.get("health_score")
            if score_now is None:
                continue

            prev_meta  = prev_insights.get(project_id) or {}
            if isinstance(prev_meta, str):
                try:
                    prev_meta = json.loads(prev_meta)
                except Exception:
                    prev_meta = {}
            score_prev = prev_meta.get("previous_score")

            if score_prev is None:
                # First run — store current score, no insight yet
                self.upsert_insight(
                    type=_TYPE_HEALTH,
                    severity="low",
                    entity_type="tenant",
                    entity_id=project_id,
                    entity_name=row.get("project_name", project_id),
                    title=f"Health baseline recorded for {row.get('project_name', project_id)}",
                    message="Health score baseline recorded. No change detected.",
                    metadata={"previous_score": score_now, "current_score": score_now},
                )
                # Immediately resolve so it doesn't clutter the feed
                self.suppress_resolved(_TYPE_HEALTH, "tenant", project_id)
                continue

            drop = score_prev - score_now
            if drop < 15:
                # Still healthy — resolve any existing health insight
                self.suppress_resolved(_TYPE_HEALTH, "tenant", project_id)
                continue

            severity   = "critical" if drop >= 30 else "high"
            project_name = row.get("project_name", project_id)
            title = (
                f"Tenant {project_name} health score dropped from "
                f"{score_prev} to {score_now} in 24 hours"
            )
            message = (
                f"The health score for {project_name!r} has declined by {drop} points "
                f"(from {score_prev} to {score_now}) since the last observation. "
                f"Investigate recent changes, errors, or compliance deductions."
            )
            self.upsert_insight(
                type=_TYPE_HEALTH,
                severity=severity,
                entity_type="tenant",
                entity_id=project_id,
                entity_name=project_name,
                title=title,
                message=message,
                metadata={"previous_score": score_prev, "current_score": score_now, "drop": drop},
            )

    # ------------------------------------------------------------------
    # C3 — Unacknowledged critical drift
    # ------------------------------------------------------------------
    def _check_unacknowledged_drift(self) -> None:
        """
        Group unacknowledged critical drift events by tenant and fire one insight
        per tenant that has unresolved critical drift in the last 48 hours.
        """
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        de.project_id,
                        p.name AS project_name,
                        COUNT(*) AS event_count
                    FROM drift_events de
                    LEFT JOIN projects p ON p.id = de.project_id
                    WHERE de.severity    = 'critical'
                      AND de.acknowledged = false
                      AND de.detected_at  >= NOW() - INTERVAL '48 hours'
                      AND de.project_id IS NOT NULL
                    GROUP BY de.project_id, p.name
                """)
                rows = cur.fetchall()
        except Exception as exc:
            log.warning("unack_drift query failed: %s", exc)
            return

        log.debug("RiskEngine C3: %d tenant(s) with unack'd critical drift", len(rows))
        for row in rows:
            project_id   = row["project_id"]
            project_name = row["project_name"] or project_id
            count        = row["event_count"]
            title = (
                f"{count} critical unacknowledged drift event(s) on tenant {project_name}"
            )
            message = (
                f"Tenant {project_name!r} has {count} critical drift event(s) detected "
                f"in the last 48 hours that have not been acknowledged. "
                f"Critical drift events indicate configuration deviations that may "
                f"create security or compliance risk. Review and acknowledge or remediate."
            )
            self.upsert_insight(
                type=_TYPE_DRIFT,
                severity="high",
                entity_type="tenant",
                entity_id=project_id,
                entity_name=project_name,
                title=title,
                message=message,
                metadata={"unack_critical_events": count},
            )
