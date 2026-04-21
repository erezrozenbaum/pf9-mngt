"""
Shared base class and upsert helper for all intelligence engines.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Dict, Optional

import psycopg2
import psycopg2.extras

log = logging.getLogger("intelligence")


# ---------------------------------------------------------------------------
# PSA outbound webhook helper (module-level, used by upsert_insight)
# ---------------------------------------------------------------------------

_SEV_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}

# Key material — same as API uses for Fernet (derived from JWT secret)
_PSA_SECRET_NAME = "jwt_secret"
_PSA_ENV_VAR     = "JWT_SECRET_KEY"


def _decrypt_fernet(ciphertext: str) -> Optional[str]:
    """Decrypt a 'fernet:<b64>' value using the JWT secret as key material."""
    if not ciphertext.startswith("fernet:"):
        return ciphertext   # plain-text fallback (dev/test)
    try:
        import base64
        import hashlib
        from cryptography.fernet import Fernet

        # Read secret (same derivation as crypto_helper.py in api/)
        secret_path = f"/run/secrets/{_PSA_SECRET_NAME}"
        raw: Optional[str] = None
        if os.path.isfile(secret_path):
            with open(secret_path) as fh:
                raw = fh.read().strip() or None
        if raw is None:
            raw = os.getenv(_PSA_ENV_VAR)
        if not raw:
            return None

        digest = hashlib.sha256(raw.encode()).digest()
        key    = base64.urlsafe_b64encode(digest)
        f      = Fernet(key)
        return f.decrypt(ciphertext[7:].encode()).decode()
    except Exception as exc:
        log.warning("PSA auth_header decrypt failed: %s", exc)
        return None


def _fire_psa_webhooks(conn, insight: dict) -> None:
    """
    Read enabled psa_webhook_config rows from the DB and fire matching ones.
    Called in-process from the worker (no cross-service HTTP required).
    Best-effort: errors are logged and never propagate.
    """
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, psa_name, webhook_url, auth_header,
                       min_severity, insight_types, region_ids
                FROM psa_webhook_config
                WHERE enabled = true
            """)
            configs = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        log.warning("PSA: failed to load webhook configs: %s", exc)
        return

    if not configs:
        return

    sev_level = _SEV_ORDER.get(insight.get("severity", ""), 0)
    ins_type  = insight.get("type", "")
    region    = (insight.get("metadata") or {}).get("entity_region", "")

    from datetime import datetime, timezone
    payload = {
        "event":      "insight.created",
        "insight_id": insight.get("id", 0),
        "severity":   insight.get("severity", ""),
        "type":       ins_type,
        "entity":     f"{insight.get('entity_type','?')} / {insight.get('entity_name','?')}",
        "region":     region,
        "title":      insight.get("title", ""),
        "url":        "",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }

    for cfg in configs:
        min_sev  = _SEV_ORDER.get(cfg.get("min_severity", "high"), 3)
        if sev_level < min_sev:
            continue
        allowed_types   = cfg.get("insight_types") or []
        if allowed_types and ins_type not in allowed_types:
            continue
        allowed_regions = cfg.get("region_ids") or []
        if allowed_regions and region not in allowed_regions:
            continue

        auth_header = _decrypt_fernet(cfg.get("auth_header", ""))
        if not auth_header:
            log.warning("PSA: skipping config id=%d — could not decrypt auth_header", cfg["id"])
            continue

        _send_webhook(cfg["webhook_url"], auth_header, payload, cfg["psa_name"])


def _send_webhook(url: str, auth_header: str, payload: dict, label: str) -> None:
    """Fire a single outbound HTTP POST. Retries once on failure."""
    try:
        import httpx
    except ImportError:
        log.warning("PSA: httpx not installed — cannot fire webhook '%s'", label)
        return

    headers = {"Content-Type": "application/json"}
    if ":" in auth_header:
        k, _, v = auth_header.partition(":")
        headers[k.strip()] = v.strip()
    else:
        headers["Authorization"] = auth_header

    body = json.dumps(payload)
    for attempt in range(2):
        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(url, content=body, headers=headers)
            if 200 <= resp.status_code < 300:
                log.info("PSA webhook '%s' fired successfully (HTTP %d)", label, resp.status_code)
            else:
                log.warning("PSA webhook '%s' returned HTTP %d", label, resp.status_code)
            return
        except Exception as exc:
            if attempt == 0:
                log.warning("PSA webhook '%s' attempt 1 failed: %s — retrying", label, exc)
            else:
                log.error("PSA webhook '%s' failed after 2 attempts: %s", label, exc)



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
        was_new = False
        insight_id = None
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
                    RETURNING id, xmax
                """, (type, severity, entity_type, entity_id, entity_name,
                      title, message, meta_json))
                row = cur.fetchone()
                if row:
                    insight_id = row[0]
                    # xmax == 0 means this was an INSERT (new row), not UPDATE
                    was_new = (row[1] == 0)
            self.conn.commit()
        except Exception as exc:
            log.warning("upsert_insight failed (%s/%s/%s): %s",
                        type, entity_type, entity_id, exc)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return

        # Fire PSA webhook on new high/critical insights
        if was_new and severity in ("high", "critical") and insight_id is not None:
            insight_dict = {
                "id":          insight_id,
                "type":        type,
                "severity":    severity,
                "entity_type": entity_type,
                "entity_id":   entity_id,
                "entity_name": entity_name,
                "title":       title,
                "metadata":    metadata or {},
            }
            _fire_psa_webhooks(self.conn, insight_dict)

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
