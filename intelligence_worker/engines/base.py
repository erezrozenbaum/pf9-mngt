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
