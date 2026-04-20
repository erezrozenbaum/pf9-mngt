"""
Shared base class and upsert helper for all intelligence engines.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

import psycopg2
import psycopg2.extras

log = logging.getLogger("intelligence")


class BaseEngine:
    """
    Common base for CapacityEngine, WasteEngine, RiskEngine.

    Subclasses override `run()`.  Call `self.upsert_insight(...)` to
    write or refresh an insight.  The unique index on operational_insights
    (type, entity_type, entity_id) WHERE status IN ('open','acknowledged','snoozed')
    ensures idempotency: a live insight is updated, not duplicated.
    """

    def __init__(self, conn) -> None:
        self.conn = conn

    def run(self) -> None:
        raise NotImplementedError

    def upsert_insight(
        self,
        *,
        type: str,
        severity: str,
        entity_type: str,
        entity_id: str,
        entity_name: str,
        title: str,
        message: str,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        meta_json = json.dumps(metadata or {})
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO operational_insights
                        (type, severity, entity_type, entity_id, entity_name,
                         title, message, metadata, status, detected_at, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'open', NOW(), NOW())
                    ON CONFLICT (type, entity_type, entity_id)
                        WHERE status IN ('open','acknowledged','snoozed')
                    DO UPDATE SET
                        severity     = EXCLUDED.severity,
                        entity_name  = EXCLUDED.entity_name,
                        title        = EXCLUDED.title,
                        message      = EXCLUDED.message,
                        metadata     = EXCLUDED.metadata,
                        last_seen_at = NOW()
                """, (type, severity, entity_type, entity_id, entity_name,
                      title, message, meta_json))
            self.conn.commit()
        except Exception as exc:
            log.warning("upsert_insight failed (%s/%s/%s): %s",
                        type, entity_type, entity_id, exc)
            try:
                self.conn.rollback()
            except Exception:
                pass

    def suppress_resolved(self, type: str, entity_type: str, entity_id: str) -> None:
        """Mark an insight as resolved when the condition is no longer true."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE operational_insights
                    SET status = 'resolved', resolved_at = NOW()
                    WHERE type = %s
                      AND entity_type = %s
                      AND entity_id   = %s
                      AND status IN ('open','acknowledged','snoozed')
                """, (type, entity_type, entity_id))
            self.conn.commit()
        except Exception as exc:
            log.debug("suppress_resolved failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:
                pass

    def upsert_recommendation(
        self,
        *,
        insight_type: str,
        entity_type: str,
        entity_id: str,
        action_type: str,
        action_payload: Dict[str, Any] | None = None,
        estimated_impact: str | None = None,
    ) -> None:
        """Attach a recommendation to the open insight for this entity.

        Idempotent — if the recommendation already exists (same insight_id +
        action_type + same entity) it is left unchanged to avoid resetting
        status of dismissed/executed recs.
        """
        try:
            with self.conn.cursor() as cur:
                # Resolve the open insight id
                cur.execute("""
                    SELECT id FROM operational_insights
                    WHERE type = %s AND entity_type = %s AND entity_id = %s
                      AND status IN ('open','acknowledged','snoozed')
                    ORDER BY detected_at DESC LIMIT 1
                """, (insight_type, entity_type, entity_id))
                row = cur.fetchone()
                if not row:
                    return
                insight_id = row[0]
                # Insert only if not already present for this (insight_id, action_type)
                cur.execute("""
                    INSERT INTO insight_recommendations
                        (insight_id, action_type, action_payload, estimated_impact)
                    SELECT %s, %s, %s::jsonb, %s
                    WHERE NOT EXISTS (
                        SELECT 1 FROM insight_recommendations
                        WHERE insight_id = %s AND action_type = %s
                          AND status = 'pending'
                    )
                """, (insight_id, action_type,
                      json.dumps(action_payload or {}), estimated_impact,
                      insight_id, action_type))
            self.conn.commit()
        except Exception as exc:
            log.debug("upsert_recommendation failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:
                pass

    def auto_create_ticket(
        self,
        *,
        insight_type: str,
        entity_type: str,
        entity_id: str,
        title: str,
        description: str,
        priority: str = "high",
    ) -> None:
        """Create a support ticket for a critical insight if one doesn't already exist."""
        try:
            with self.conn.cursor() as cur:
                # Don't duplicate — check if a ticket was auto-created for this insight
                cur.execute("""
                    SELECT id FROM operational_insights
                    WHERE type = %s AND entity_type = %s AND entity_id = %s
                      AND status IN ('open','acknowledged','snoozed')
                    ORDER BY detected_at DESC LIMIT 1
                """, (insight_type, entity_type, entity_id))
                row = cur.fetchone()
                if not row:
                    return
                insight_id = row[0]
                # Check if already created a ticket for this insight
                cur.execute("""
                    SELECT 1 FROM support_tickets
                    WHERE auto_source = 'intelligence_insight'
                      AND metadata->>'insight_id' = %s::text
                """, (str(insight_id),))
                if cur.fetchone():
                    return
                # Create the ticket
                cur.execute("""
                    INSERT INTO support_tickets
                        (title, description, priority, status,
                         auto_source, metadata, created_at)
                    VALUES (%s, %s, %s, 'open',
                            'intelligence_insight',
                            jsonb_build_object('insight_id', %s,
                                               'entity_type', %s,
                                               'entity_id',   %s),
                            NOW())
                """, (title, description, priority,
                      insight_id, entity_type, entity_id))
            self.conn.commit()
            log.info("Auto-ticket created for insight %d (%s/%s)", insight_id, entity_type, entity_id)
        except Exception as exc:
            log.debug("auto_create_ticket failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:
                pass
