"""
Event Bus — fire-and-forget writer to the operational_events timeline.

Usage
-----
    from event_bus import emit_event

    emit_event(
        event_type="vm.provisioned",
        category="provisioning",
        title="VM acme-web-01 provisioned successfully",
        entity_type="server",
        entity_id=server_id,
        entity_name="acme-web-01",
        project_id=project_id,
        project_name="production",
        actor="alice@acme-corp.com",
        metadata={"flavor": "m1.medium"},
    )

Design
------
- Runs the INSERT in a daemon thread so the caller's request path is never
  blocked or delayed.
- All exceptions are caught and logged at DEBUG level — never propagated.
- Deduplication: if ``source_id`` is provided the INSERT uses
  ON CONFLICT DO NOTHING against the unique index
  ``idx_oe_source_dedup (source, source_id)``.

Added: v2.7.0
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("pf9.event_bus")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def emit_event(
    event_type: str,
    category: str,
    title: str,
    entity_type: str,
    entity_id: str,
    *,
    severity: str = "info",
    description: Optional[str] = None,
    entity_name: Optional[str] = None,
    domain_id: Optional[str] = None,
    domain_name: Optional[str] = None,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    region_id: str = "global",
    source: str = "api",
    source_id: Optional[str] = None,
    actor: Optional[str] = None,
    visibility: str = "operational",
    metadata: Optional[dict[str, Any]] = None,
    occurred_at: Optional[datetime] = None,
) -> None:
    """
    Emit an operational event to the timeline (non-blocking).

    Parameters
    ----------
    event_type:
        Dot-separated event type, e.g. ``"vm.provisioned"``,
        ``"backup.completed"``, ``"ticket.opened"``.
    category:
        Must be one of the DB CHECK constraint values:
        ``monitoring | provisioning | backup | snapshot | sla |
          billing | security | ticket | intelligence | runbook | system``.
    title:
        Short human-readable summary (shown in the timeline UI).
    entity_type:
        Resource class, e.g. ``"server"``, ``"volume"``, ``"ticket"``.
    entity_id:
        Identifier of the primary entity (OpenStack UUID, ticket ref, etc.).
    severity:
        ``"info"`` | ``"warning"`` | ``"critical"``  (default: ``"info"``).
    source_id:
        Stable identifier for deduplication.  When provided, a second call
        with the same ``(source, source_id)`` pair is silently dropped.
    """
    t = threading.Thread(
        target=_write_event,
        kwargs=dict(
            event_type=event_type,
            category=category,
            title=title,
            entity_type=entity_type,
            entity_id=entity_id,
            severity=severity,
            description=description,
            entity_name=entity_name,
            domain_id=domain_id,
            domain_name=domain_name,
            project_id=project_id,
            project_name=project_name,
            region_id=region_id,
            source=source,
            source_id=source_id,
            actor=actor,
            visibility=visibility,
            metadata=metadata or {},
            occurred_at=occurred_at or datetime.now(timezone.utc),
        ),
        daemon=True,
    )
    t.start()


# ---------------------------------------------------------------------------
# Internal writer (runs in background thread)
# ---------------------------------------------------------------------------

_INSERT_SQL = """
INSERT INTO operational_events (
    occurred_at, event_type, category, severity, title, description,
    metadata, entity_type, entity_id, entity_name,
    domain_id, domain_name, project_id, project_name, region_id,
    source, source_id, actor, visibility
)
VALUES (
    %s, %s, %s, %s, %s, %s,
    %s::jsonb, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s
)
ON CONFLICT (source, source_id)
WHERE source_id IS NOT NULL
DO NOTHING
"""


def _write_event(
    *,
    event_type: str,
    category: str,
    title: str,
    entity_type: str,
    entity_id: str,
    severity: str,
    description: Optional[str],
    entity_name: Optional[str],
    domain_id: Optional[str],
    domain_name: Optional[str],
    project_id: Optional[str],
    project_name: Optional[str],
    region_id: str,
    source: str,
    source_id: Optional[str],
    actor: Optional[str],
    visibility: str,
    metadata: dict,
    occurred_at: datetime,
) -> None:
    try:
        from db_pool import get_connection  # lazy import avoids circular dependency at module load

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _INSERT_SQL,
                    (
                        occurred_at,
                        event_type,
                        category,
                        severity,
                        title,
                        description,
                        json.dumps(metadata),
                        entity_type,
                        entity_id,
                        entity_name,
                        domain_id,
                        domain_name,
                        project_id,
                        project_name,
                        region_id,
                        source,
                        source_id,
                        actor,
                        visibility,
                    ),
                )
    except Exception:
        logger.debug("event_bus: failed to write event %r", event_type, exc_info=True)
