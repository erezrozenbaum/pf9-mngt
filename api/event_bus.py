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
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("pf9.event_bus")

_REALTIME_ANOMALY_ENABLED = os.getenv("REALTIME_ANOMALY_ENABLED", "true").lower() in ("true", "1", "yes")
_REALTIME_SUPPORTED_TYPES = {
    "vm.cpu_spike": "anomaly_realtime_vm_cpu_spike",
    "vm.ram_spike": "anomaly_realtime_vm_ram_spike",
    "quota.sudden_jump": "anomaly_realtime_quota_sudden_jump",
}
_REALTIME_STATS_TTL_SECONDS = 12 * 60 * 60


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
RETURNING id
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
                row = cur.fetchone()
                event_id = row[0] if row else None

        # Evaluate CLEA policies in this same background thread
        if event_id is not None:
            try:
                from clea_routes import evaluate_clea_policies  # lazy import
                evaluate_clea_policies(event_id, event_type, metadata)
            except Exception:
                logger.debug("event_bus: clea evaluation failed for %r", event_type, exc_info=True)

            try:
                from ai_triage import evaluate_ai_triage  # lazy import

                evaluate_ai_triage(
                    event_id=event_id,
                    event_type=event_type,
                    severity=severity,
                    entity_name=entity_name,
                    project_id=project_id,
                    project_name=project_name,
                    metadata=metadata,
                )
            except Exception:
                logger.debug("event_bus: ai triage evaluation failed for %r", event_type, exc_info=True)

            # Realtime anomaly fast-path: evaluate only supported signal events
            # against precomputed Redis stats and upsert an insight immediately.
            try:
                _quick_anomaly_check(
                    event_type=event_type,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    project_id=project_id,
                    project_name=project_name,
                    metadata=metadata,
                )
            except Exception:
                logger.debug("event_bus: realtime anomaly quick-check failed for %r", event_type, exc_info=True)

        # Publish to SSE channel so connected browser clients see the event
        # in real time.  Redis unavailability is silently ignored.
        try:
            from cache import _get_client as _redis_client  # lazy import
            rc = _redis_client()
            if rc is not None and event_id is not None:
                payload = json.dumps({
                    "id": event_id,
                    "type": event_type,
                    "title": title,
                    "severity": severity,
                    "category": category,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "occurred_at": occurred_at.isoformat(),
                })
                rc.publish("pf9:live_events", payload)
        except Exception:
            logger.debug("event_bus: redis publish failed for %r", event_type, exc_info=True)

    except Exception:
        logger.debug("event_bus: failed to write event %r", event_type, exc_info=True)


def _extract_metric_value(metadata: dict) -> Optional[float]:
    for key in ("metric_value", "value", "current_value", "usage", "used"):
        val = metadata.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except Exception:
            continue
    return None


def _get_realtime_stats(entity_type: str, entity_id: str) -> Optional[dict[str, float]]:
    try:
        from cache import _get_client as _redis_client

        rc = _redis_client()
        if rc is None:
            return None

        key = f"pf9:stats:{entity_type}:{entity_id}"
        raw = rc.get(key)
        if not raw:
            return None
        payload = json.loads(raw)

        mean = payload.get("mean")
        stddev = payload.get("stddev")
        if mean is None or stddev is None:
            return None
        return {"mean": float(mean), "stddev": float(stddev)}
    except Exception:
        return None


def _upsert_realtime_anomaly_insight(
    *,
    insight_type: str,
    severity: str,
    entity_type: str,
    entity_id: str,
    entity_name: str,
    title: str,
    message: str,
    metadata: dict[str, Any],
) -> bool:
    try:
        from db_pool import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Hard query budget for quick-path writes.
                cur.execute("SET LOCAL statement_timeout = '200ms'")
                cur.execute(
                    """
                    INSERT INTO operational_insights
                        (type, severity, entity_type, entity_id, entity_name,
                         title, message, metadata, status, detected_at, last_seen_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'open', NOW(), NOW())
                    ON CONFLICT (type, entity_type, entity_id)
                        WHERE status IN ('open','acknowledged','snoozed')
                    DO UPDATE SET
                        severity = EXCLUDED.severity,
                        entity_name = EXCLUDED.entity_name,
                        title = EXCLUDED.title,
                        message = EXCLUDED.message,
                        metadata = EXCLUDED.metadata,
                        last_seen_at = NOW()
                    """,
                    (
                        insight_type,
                        severity,
                        entity_type,
                        entity_id,
                        entity_name,
                        title,
                        message,
                        json.dumps(metadata),
                    ),
                )
            conn.commit()
        return True
    except Exception:
        return False


def _quick_anomaly_check(
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    entity_name: Optional[str],
    project_id: Optional[str],
    project_name: Optional[str],
    metadata: dict,
) -> None:
    if not _REALTIME_ANOMALY_ENABLED:
        return

    insight_type = _REALTIME_SUPPORTED_TYPES.get(event_type)
    if not insight_type:
        return

    metric_value = _extract_metric_value(metadata)
    if metric_value is None:
        return

    stats = _get_realtime_stats(entity_type, entity_id)
    if not stats:
        return

    mean = float(stats.get("mean", 0.0))
    stddev = float(stats.get("stddev", 0.0))
    if stddev <= 0:
        return

    sigma = abs(metric_value - mean) / stddev
    if sigma < 3.0:
        return

    severity = "critical" if sigma >= 5.0 else "high"
    resolved_entity_name = entity_name or entity_id
    title = f"Realtime anomaly detected: {event_type} on {resolved_entity_name}"
    message = (
        f"Signal {event_type!r} on {resolved_entity_name!r} deviates by "
        f"{sigma:.2f} sigma from baseline (value={metric_value:.4g}, mean={mean:.4g}, stddev={stddev:.4g})."
    )
    anomaly_meta = {
        "trigger_event_type": event_type,
        "metric_value": metric_value,
        "baseline_mean": mean,
        "baseline_stddev": stddev,
        "sigma": round(sigma, 3),
        "project_id": project_id,
        "project_name": project_name,
        "stats_ttl_seconds": _REALTIME_STATS_TTL_SECONDS,
        **(metadata or {}),
    }

    ok = _upsert_realtime_anomaly_insight(
        insight_type=insight_type,
        severity=severity,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=resolved_entity_name,
        title=title,
        message=message,
        metadata=anomaly_meta,
    )
    if not ok:
        return

    emit_event(
        event_type="anomaly.realtime",
        category="intelligence",
        severity=severity,
        title=title,
        description=message,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=resolved_entity_name,
        project_id=project_id,
        project_name=project_name,
        source="realtime_anomaly",
        source_id=f"{insight_type}:{entity_id}:{int(metric_value)}",
        metadata=anomaly_meta,
    )
