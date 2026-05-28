"""
SLA Defense Engine (v2.16.0 start)

Cross-references active SLA commitments with open operational insights to
raise proactive SLA-risk alerts before breach conditions materialize.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.sla_defense")


def _urgency_factor(runway_days: float, rto_hours: int | None) -> float:
    if runway_days is None or runway_days < 0:
        return 0.0
    if not rto_hours or rto_hours <= 0:
        # Conservative fallback when no explicit SLA RTO exists.
        return 0.3 if runway_days < 14 else 0.0

    rto_days = rto_hours / 24.0
    if runway_days < rto_days:
        return 1.0
    if runway_days < rto_days * 3:
        return 0.7
    if runway_days < 14:
        return 0.3
    return 0.0


def _threat_score(confidence: float | None, runway_days: float, rto_hours: int | None) -> float:
    conf = 0.6 if confidence is None else max(0.0, min(1.0, float(confidence)))
    return round(conf * _urgency_factor(runway_days, rto_hours), 4)


def _threat_type_for_insight(insight_type: str) -> str:
    t = (insight_type or "").lower()
    if t.startswith("capacity"):
        return "capacity_runway"
    if t.startswith("anomaly"):
        return "anomaly_cluster"
    return "health_decline"


class SlaDefenseEngine(BaseEngine):
    """Generate and maintain records in sla_defense_alerts."""

    def _process_candidate_row(self, row: dict[str, Any], triggered_keys: set[tuple[str, str]]) -> bool:
        project_id = row["project_id"]
        insight_id = row["insight_id"]
        insight_type = row["insight_type"]
        runway_days = float(row["runway_days"])
        confidence = float(row["confidence"]) if row.get("confidence") is not None else None
        rto_hours = row.get("rto_hours")

        threat_type = _threat_type_for_insight(insight_type)
        score = _threat_score(confidence, runway_days, rto_hours)
        if score < 0.7:
            return False

        severity = "critical" if score >= 0.9 else "warning"
        project_name = row.get("project_name") or project_id
        triggered_keys.add((project_id, threat_type))

        detail: dict[str, Any] = {
            "tier": row.get("tier"),
            "runway_days": runway_days,
            "confidence": confidence,
            "threat_score": score,
            "insight_type": insight_type,
        }

        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sla_defense_alerts
                    (project_id, sla_id, insight_id, threat_type, threat_detail, severity, status)
                VALUES
                    (%s, %s, %s, %s, %s::jsonb, %s, 'open')
                ON CONFLICT (project_id, threat_type)
                WHERE status = 'open'
                DO UPDATE SET
                    sla_id = EXCLUDED.sla_id,
                    insight_id = EXCLUDED.insight_id,
                    threat_detail = EXCLUDED.threat_detail,
                    severity = EXCLUDED.severity,
                    triggered_at = NOW(),
                    resolved_at = NULL,
                    resolution_note = NULL
                """,
                (
                    project_id,
                    row["sla_id"],
                    insight_id,
                    threat_type,
                    json.dumps(detail),
                    severity,
                ),
            )

        # Emit timeline event directly (worker container does not import api/event_bus.py).
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO operational_events (
                    occurred_at, event_type, category, severity, title, description,
                    metadata, entity_type, entity_id, entity_name,
                    project_id, project_name, region_id, source, visibility
                )
                VALUES (
                    NOW(), 'sla.defense_alert', 'intelligence', %s, %s, %s,
                    %s::jsonb, 'project', %s, %s,
                    %s, %s, 'global', 'intelligence_worker', 'operational'
                )
                """,
                (
                    severity,
                    f"SLA defense alert for {project_name}",
                    f"Threat {threat_type} with score={score:.2f} (runway={runway_days}d)",
                    json.dumps(detail),
                    project_id,
                    project_name,
                    project_id,
                    project_name,
                ),
            )

        return True

    def run(self) -> None:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                WITH active_sla AS (
                    SELECT id, tenant_id, tier, rto_hours
                    FROM sla_commitments
                    WHERE effective_to IS NULL
                ),
                open_insights AS (
                    SELECT
                        oi.id,
                        oi.entity_id AS project_id,
                        oi.entity_name AS project_name,
                        oi.type,
                        oi.severity,
                        oi.metadata,
                        CASE
                            WHEN (oi.metadata->>'runway_days') ~ '^-?[0-9]+(\\.[0-9]+)?$'
                            THEN (oi.metadata->>'runway_days')::numeric
                            ELSE NULL
                        END AS runway_days,
                        CASE
                            WHEN (oi.metadata->>'confidence') ~ '^-?[0-9]+(\\.[0-9]+)?$'
                            THEN (oi.metadata->>'confidence')::numeric
                            ELSE NULL
                        END AS confidence
                    FROM operational_insights oi
                    WHERE oi.status IN ('open', 'acknowledged', 'snoozed')
                      AND oi.entity_type = 'project'
                      AND (oi.type LIKE 'capacity%' OR oi.type LIKE 'risk%' OR oi.type LIKE 'anomaly%')
                )
                SELECT
                    s.id AS sla_id,
                    s.tenant_id AS project_id,
                    s.tier,
                    s.rto_hours,
                    i.id AS insight_id,
                    i.project_name,
                    i.type AS insight_type,
                    i.runway_days,
                    i.confidence,
                    i.metadata
                FROM active_sla s
                JOIN open_insights i ON i.project_id = s.tenant_id
                WHERE i.runway_days IS NOT NULL
                """
            )
            rows = [dict(r) for r in cur.fetchall()]

        triggered_keys: set[tuple[str, str]] = set()

        for row in rows:
            self._process_candidate_row(row, triggered_keys)

        # Resolve stale open alerts (condition no longer true).
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, project_id, threat_type
                FROM sla_defense_alerts
                WHERE status = 'open'
                """
            )
            open_alerts = [dict(r) for r in cur.fetchall()]

        for alert in open_alerts:
            key = (alert["project_id"], alert["threat_type"])
            if key in triggered_keys:
                continue
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE sla_defense_alerts
                    SET status = 'resolved',
                        resolved_at = NOW(),
                        resolution_note = 'Condition no longer active'
                    WHERE id = %s AND status = 'open'
                    """,
                    (alert["id"],),
                )

        self.conn.commit()
        log.info("SlaDefenseEngine processed %d candidate(s), active alerts=%d", len(rows), len(triggered_keys))
