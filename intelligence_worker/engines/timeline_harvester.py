"""
Timeline Harvester Engine
=========================
Incrementally reads source tables and writes normalised events into
``operational_events``.  Uses ``timeline_harvest_cursors`` to track the
highest ``id`` (or ``computed_at`` for SLA) processed per source so that
re-runs are idempotent and only process new rows.

Sources harvested
-----------------
  activity_log            → provisioning / quota / role-change events
  operational_insights    → insight_fired / insight_resolved
  support_tickets         → ticket_opened / ticket_resolved
  backup_history          → backup_completed / backup_failed
  snapshot_records        → snapshot_completed / snapshot_failed
  sla_compliance_monthly  → sla_breached / sla_at_risk
  runbook_executions      → runbook_executed / runbook_failed
  metering_efficiency     → cpu_spike / ram_spike
  metering_quotas         → storage_high
  auth_audit_log          → user_login / user_role_changed  (visibility=security)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.timeline_harvester")

RETENTION_DAYS = int(os.getenv("TIMELINE_RETENTION_DAYS", "180"))
BATCH_SIZE     = 500

# ---------------------------------------------------------------------------
# activity_log action → (event_type, category, severity)
# ---------------------------------------------------------------------------
_ACTIVITY_ACTION_MAP: Dict[str, tuple] = {
    "provision":                      ("tenant_provisioned",      "provisioning", "info"),
    "provisioning_complete":          ("tenant_provisioned",      "provisioning", "info"),
    "provisioning_failed":            ("tenant_provision_failed", "provisioning", "critical"),
    "batch_created":                  ("vm_batch_executed",       "provisioning", "info"),
    "vm_provisioning_approved":       ("vm_batch_executed",       "provisioning", "info"),
    "vm_provisioning_submitted":      ("vm_batch_executed",       "provisioning", "info"),
    "vm_provisioning_dry_run_passed": ("vm_batch_executed",       "provisioning", "info"),
    "vm_provisioning_rejected":       ("provisioning_rejected",   "provisioning", "warning"),
    "update_quotas":                  ("quota_modified",          "provisioning", "info"),
    "update_quota":                   ("quota_modified",          "provisioning", "info"),
}

# insight severity (low/medium/high/critical) → operational_events severity
_INSIGHT_SEV: Dict[str, str] = {
    "low": "info", "medium": "warning", "high": "warning", "critical": "critical",
}

# ticket priority → severity
_TICKET_SEV: Dict[str, str] = {
    "low": "info", "normal": "info", "high": "warning",
    "urgent": "critical", "emergency": "critical",
}


class TimelineHarvester(BaseEngine):
    """Harvest events from source tables into operational_events."""

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def run(self) -> None:
        sources = [
            ("activity_log",           self._harvest_activity_log),
            ("operational_insights",   self._harvest_insights),
            ("support_tickets",        self._harvest_tickets),
            ("backup_history",         self._harvest_backups),
            ("snapshot_records",       self._harvest_snapshots),
            ("sla_compliance_monthly", self._harvest_sla),
            ("runbook_executions",     self._harvest_runbooks),
            ("metering_efficiency",    self._harvest_efficiency),
            ("metering_quotas",        self._harvest_quotas),
            ("auth_audit_log",         self._harvest_auth),
        ]
        for name, method in sources:
            try:
                method()
                log.debug("TimelineHarvester: %s done", name)
            except Exception as exc:
                log.warning("TimelineHarvester: %s failed: %s", name, exc)
                try:
                    self.conn.rollback()
                except Exception:  # nosec B110 — best-effort rollback, never propagate
                    pass
        self._prune_old_events()

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------
    def _get_cursor(self, source_key: str):
        """Return (last_id, last_ts) for a source key, both may be None."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT last_id, last_ts FROM timeline_harvest_cursors WHERE source = %s",
                (source_key,),
            )
            row = cur.fetchone()
        if row:
            return row[0], row[1]
        return None, None

    def _advance_cursor(
        self,
        source_key: str,
        last_id: Optional[int] = None,
        last_ts: Optional[datetime] = None,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO timeline_harvest_cursors (source, last_id, last_ts, updated_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (source) DO UPDATE SET
                    last_id    = COALESCE(EXCLUDED.last_id,    timeline_harvest_cursors.last_id),
                    last_ts    = COALESCE(EXCLUDED.last_ts,    timeline_harvest_cursors.last_ts),
                    updated_at = NOW()
                """,
                (source_key, last_id, last_ts),
            )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Bulk insert helper
    # ------------------------------------------------------------------
    def _bulk_insert(self, events: List[Dict[str, Any]]) -> int:
        """Insert events into operational_events, skip duplicates. Returns inserted count."""
        if not events:
            return 0
        inserted = 0
        with self.conn.cursor() as cur:
            for ev in events:
                cur.execute(
                    """
                    INSERT INTO operational_events (
                        occurred_at, event_type, category, severity,
                        title, description, metadata,
                        entity_type, entity_id, entity_name,
                        domain_id, domain_name, project_id, project_name,
                        region_id, source, source_id, actor, visibility
                    ) VALUES (
                        %(occurred_at)s, %(event_type)s, %(category)s, %(severity)s,
                        %(title)s, %(description)s, %(metadata)s::jsonb,
                        %(entity_type)s, %(entity_id)s, %(entity_name)s,
                        %(domain_id)s, %(domain_name)s, %(project_id)s, %(project_name)s,
                        %(region_id)s, %(source)s, %(source_id)s, %(actor)s, %(visibility)s
                    )
                    ON CONFLICT (source, source_id)
                    WHERE source_id IS NOT NULL
                    DO NOTHING
                    """,
                    ev,
                )
                inserted += cur.rowcount
        self.conn.commit()
        return inserted

    def _ev_base(self) -> Dict[str, Any]:
        """Return a base event dict with all optional fields set to safe defaults."""
        return {
            "description": None,
            "metadata":    "{}",
            "entity_name": None,
            "domain_id":   None,
            "domain_name": None,
            "project_id":  None,
            "project_name": None,
            "region_id":   "global",
            "actor":       "system",
            "visibility":  "operational",
        }

    # ------------------------------------------------------------------
    # activity_log
    # ------------------------------------------------------------------
    def _harvest_activity_log(self) -> None:
        last_id, _ = self._get_cursor("activity_log")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.id, a.timestamp, a.actor, a.action, a.resource_type,
                       a.resource_id, a.resource_name, a.details, a.result,
                       COALESCE(NULLIF(a.domain_id, ''), d.id)  AS domain_id,
                       COALESCE(NULLIF(a.domain_name, ''), b.domain_name) AS domain_name
                FROM activity_log a
                LEFT JOIN vm_provisioning_batches b
                       ON a.resource_type = 'vm_provisioning'
                      AND b.id::text = a.resource_id
                LEFT JOIN domains d ON d.name = b.domain_name
                WHERE a.id > %s
                  AND a.action = ANY(%s)
                ORDER BY a.id ASC
                LIMIT %s
                """,
                (last_id, list(_ACTIVITY_ACTION_MAP.keys()), BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            event_type, category, severity = _ACTIVITY_ACTION_MAP[row["action"]]
            # Override if result indicates failure despite action name
            if row.get("result") == "failure" and category == "provisioning":
                event_type = "tenant_provision_failed"
                severity   = "critical"
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["timestamp"],
                "event_type":  event_type,
                "category":    category,
                "severity":    severity,
                "title":       f"{row['action'].replace('_', ' ').title()}: "
                               f"{row['resource_name'] or row['resource_id'] or '—'}",
                "metadata":    json.dumps(dict(row["details"] or {})),
                "entity_type": row["resource_type"] or "unknown",
                "entity_id":   row["resource_id"] or str(row["id"]),
                "entity_name": row["resource_name"],
                "domain_id":   row["domain_id"],
                "domain_name": row["domain_name"],
                "source":      "activity_log",
                "source_id":   str(row["id"]),
                "actor":       row["actor"],
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: activity_log — %d inserted", count)
        self._advance_cursor("activity_log", last_id=max_id)

    # ------------------------------------------------------------------
    # operational_insights — insight_fired / insight_resolved
    # ------------------------------------------------------------------
    def _harvest_insights(self) -> None:
        self._harvest_insights_opened()
        self._harvest_insights_resolved()

    def _harvest_insights_opened(self) -> None:
        last_id, _ = self._get_cursor("operational_insights:open")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.id, i.detected_at, i.type, i.severity, i.entity_type,
                       i.entity_id, i.entity_name, i.title, i.message, i.metadata,
                       COALESCE(p_id.domain_id,  p_vm.domain_id)  AS resolved_domain_id,
                       COALESCE(d_id.name,        d_vm.name)       AS resolved_domain_name
                FROM operational_insights i
                -- tenant/project: entity_id IS a project UUID
                LEFT JOIN projects p_id ON i.entity_type IN ('tenant', 'project')
                                       AND p_id.id = i.entity_id
                LEFT JOIN domains  d_id ON d_id.id = p_id.domain_id
                -- vm: look up via metadata->>'project' (project name)
                LEFT JOIN projects p_vm ON i.entity_type = 'vm'
                                       AND p_vm.name = i.metadata->>'project'
                LEFT JOIN domains  d_vm ON d_vm.id = p_vm.domain_id
                WHERE i.id > %s
                  AND i.status IN ('open', 'acknowledged', 'snoozed')
                ORDER BY i.id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            ev = self._ev_base()
            ev.update({
                "occurred_at":  row["detected_at"],
                "event_type":   "insight_fired",
                "category":     "intelligence",
                "severity":     _INSIGHT_SEV.get(row["severity"], "warning"),
                "title":        row["title"],
                "description":  row["message"],
                "metadata":     json.dumps(dict(row["metadata"] or {})),
                "entity_type":  row["entity_type"],
                "entity_id":    row["entity_id"],
                "entity_name":  row["entity_name"],
                "domain_id":    row["resolved_domain_id"],
                "domain_name":  row["resolved_domain_name"],
                "source":       "operational_insights",
                "source_id":    f"open:{row['id']}",
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: insights opened — %d inserted", count)
        self._advance_cursor("operational_insights:open", last_id=max_id)

    def _harvest_insights_resolved(self) -> None:
        last_id, _ = self._get_cursor("operational_insights:resolved")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT i.id, i.resolved_at, i.entity_type, i.entity_id,
                       i.entity_name, i.title, i.metadata,
                       COALESCE(p_id.domain_id,  p_vm.domain_id)  AS resolved_domain_id,
                       COALESCE(d_id.name,        d_vm.name)       AS resolved_domain_name
                FROM operational_insights i
                LEFT JOIN projects p_id ON i.entity_type IN ('tenant', 'project')
                                       AND p_id.id = i.entity_id
                LEFT JOIN domains  d_id ON d_id.id = p_id.domain_id
                LEFT JOIN projects p_vm ON i.entity_type = 'vm'
                                       AND p_vm.name = i.metadata->>'project'
                LEFT JOIN domains  d_vm ON d_vm.id = p_vm.domain_id
                WHERE i.id > %s
                  AND i.status = 'resolved'
                  AND i.resolved_at IS NOT NULL
                ORDER BY i.id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            ev = self._ev_base()
            ev.update({
                "occurred_at":  row["resolved_at"],
                "event_type":   "insight_resolved",
                "category":     "intelligence",
                "severity":     "info",
                "title":        f"Resolved: {row['title']}",
                "entity_type":  row["entity_type"],
                "entity_id":    row["entity_id"],
                "entity_name":  row["entity_name"],
                "domain_id":    row["resolved_domain_id"],
                "domain_name":  row["resolved_domain_name"],
                "source":       "operational_insights",
                "source_id":    f"resolved:{row['id']}",
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: insights resolved — %d inserted", count)
        self._advance_cursor("operational_insights:resolved", last_id=max_id)

    # ------------------------------------------------------------------
    # support_tickets — ticket_opened / ticket_resolved
    # ------------------------------------------------------------------
    def _harvest_tickets(self) -> None:
        self._harvest_tickets_opened()
        self._harvest_tickets_resolved()

    def _harvest_tickets_opened(self) -> None:
        last_id, _ = self._get_cursor("support_tickets:open")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT t.id, t.created_at, t.title, t.ticket_type, t.priority,
                       t.opened_by, t.resource_type, t.resource_id, t.resource_name,
                       t.project_id, t.project_name, t.ticket_ref,
                       COALESCE(NULLIF(t.domain_id, ''),   p.domain_id) AS domain_id,
                       COALESCE(NULLIF(t.domain_name, ''), d.name)      AS domain_name
                FROM support_tickets t
                LEFT JOIN projects p ON t.domain_id IS NULL AND p.id = t.project_id
                LEFT JOIN domains  d ON d.id = COALESCE(NULLIF(t.domain_id, ''), p.domain_id)
                WHERE t.id > %s
                ORDER BY t.id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["created_at"],
                "event_type":  "ticket_opened",
                "category":    "ticket",
                "severity":    _TICKET_SEV.get(row["priority"], "info"),
                "title":       f"Ticket: {row['title']}",
                "metadata":    json.dumps({
                    "ticket_ref":  row["ticket_ref"],
                    "ticket_type": row["ticket_type"],
                    "priority":    row["priority"],
                }),
                "entity_type": row["resource_type"] or "ticket",
                "entity_id":   row["resource_id"] or str(row["id"]),
                "entity_name": row["resource_name"],
                "domain_id":   row["domain_id"],
                "domain_name": row["domain_name"],
                "project_id":  row["project_id"],
                "project_name": row["project_name"],
                "source":      "support_tickets",
                "source_id":   f"open:{row['id']}",
                "actor":       row["opened_by"],
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: tickets opened — %d inserted", count)
        self._advance_cursor("support_tickets:open", last_id=max_id)

    def _harvest_tickets_resolved(self) -> None:
        last_id, _ = self._get_cursor("support_tickets:resolved")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT t.id, t.resolved_at, t.title, t.priority, t.resolved_by,
                       t.resource_type, t.resource_id, t.resource_name,
                       t.project_id, t.project_name, t.ticket_ref,
                       COALESCE(NULLIF(t.domain_id, ''),   p.domain_id) AS domain_id,
                       COALESCE(NULLIF(t.domain_name, ''), d.name)      AS domain_name
                FROM support_tickets t
                LEFT JOIN projects p ON t.domain_id IS NULL AND p.id = t.project_id
                LEFT JOIN domains  d ON d.id = COALESCE(NULLIF(t.domain_id, ''), p.domain_id)
                WHERE t.id > %s
                  AND t.status IN ('resolved', 'closed')
                  AND t.resolved_at IS NOT NULL
                ORDER BY t.id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["resolved_at"],
                "event_type":  "ticket_resolved",
                "category":    "ticket",
                "severity":    "info",
                "title":       f"Resolved: {row['title']}",
                "metadata":    json.dumps({"ticket_ref": row["ticket_ref"]}),
                "entity_type": row["resource_type"] or "ticket",
                "entity_id":   row["resource_id"] or str(row["id"]),
                "entity_name": row["resource_name"],
                "domain_id":   row["domain_id"],
                "domain_name": row["domain_name"],
                "project_id":  row["project_id"],
                "project_name": row["project_name"],
                "source":      "support_tickets",
                "source_id":   f"resolved:{row['id']}",
                "actor":       row["resolved_by"] or "system",
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: tickets resolved — %d inserted", count)
        self._advance_cursor("support_tickets:resolved", last_id=max_id)

    # ------------------------------------------------------------------
    # backup_history — backup_completed / backup_failed
    # ------------------------------------------------------------------
    def _harvest_backups(self) -> None:
        last_id, _ = self._get_cursor("backup_history")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, completed_at, created_at, status, backup_type,
                       backup_target, initiated_by, error_message, region_id,
                       file_size_bytes, duration_seconds
                FROM backup_history
                WHERE id > %s
                  AND status IN ('completed', 'failed')
                ORDER BY id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            is_ok      = row["status"] == "completed"
            event_type = "backup_completed" if is_ok else "backup_failed"
            occurred   = row["completed_at"] or row["created_at"]
            meta: Dict[str, Any] = {
                "backup_type":   row["backup_type"],
                "backup_target": row["backup_target"],
            }
            if row["file_size_bytes"] is not None:
                meta["file_size_bytes"] = row["file_size_bytes"]
            if row["duration_seconds"] is not None:
                meta["duration_seconds"] = row["duration_seconds"]
            if row["error_message"]:
                meta["error_message"] = row["error_message"]
            ev = self._ev_base()
            ev.update({
                "occurred_at": occurred,
                "event_type":  event_type,
                "category":    "backup",
                "severity":    "info" if is_ok else "critical",
                "title":       (
                    f"{'Backup completed' if is_ok else 'Backup failed'}: "
                    f"{row['backup_type']} {row['backup_target']}"
                ),
                "description": row["error_message"],
                "metadata":    json.dumps(meta),
                "entity_type": "system",
                "entity_id":   row["backup_target"],
                "region_id":   row["region_id"] or "global",
                "source":      "backup_history",
                "source_id":   str(row["id"]),
                "actor":       row["initiated_by"] or "system",
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: backups — %d inserted", count)
        self._advance_cursor("backup_history", last_id=max_id)

    # ------------------------------------------------------------------
    # snapshot_records — snapshot_completed / snapshot_failed
    # ------------------------------------------------------------------
    def _harvest_snapshots(self) -> None:
        last_id, _ = self._get_cursor("snapshot_records")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, created_at, action, status, snapshot_id, snapshot_name,
                       volume_id, volume_name, vm_id, vm_name,
                       tenant_id, tenant_name, project_id, project_name,
                       region_id, policy_name, size_gb, error_message
                FROM snapshot_records
                WHERE id > %s
                  AND action = 'create'
                  AND status IN ('completed', 'failed')
                ORDER BY id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            is_ok      = row["status"] == "completed"
            event_type = "snapshot_completed" if is_ok else "snapshot_failed"
            meta: Dict[str, Any] = {}
            if row["policy_name"]:
                meta["policy_name"] = row["policy_name"]
            if row["size_gb"] is not None:
                meta["size_gb"] = row["size_gb"]
            if row["error_message"]:
                meta["error_message"] = row["error_message"]
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["created_at"],
                "event_type":  event_type,
                "category":    "snapshot",
                "severity":    "info" if is_ok else "critical",
                "title":       (
                    f"{'Snapshot created' if is_ok else 'Snapshot failed'}: "
                    f"{row['snapshot_name'] or row['volume_name'] or row['volume_id']}"
                ),
                "description": row["error_message"],
                "metadata":    json.dumps(meta),
                "entity_type": "volume",
                "entity_id":   row["volume_id"],
                "entity_name": row["volume_name"],
                "domain_id":   row["tenant_id"],
                "domain_name": row["tenant_name"],
                "project_id":  row["project_id"],
                "project_name": row["project_name"],
                "region_id":   row["region_id"] or "global",
                "source":      "snapshot_records",
                "source_id":   str(row["id"]),
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: snapshots — %d inserted", count)
        self._advance_cursor("snapshot_records", last_id=max_id)

    # ------------------------------------------------------------------
    # sla_compliance_monthly — sla_breached / sla_at_risk
    # ------------------------------------------------------------------
    def _harvest_sla(self) -> None:
        _, last_ts = self._get_cursor("sla_compliance_monthly")
        if last_ts is None:
            last_ts = datetime(2000, 1, 1, tzinfo=timezone.utc)
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT tenant_id, month, region_id, computed_at,
                       breach_fields, at_risk_fields,
                       uptime_actual_pct, backup_success_pct
                FROM sla_compliance_monthly
                WHERE computed_at > %s
                  AND (cardinality(breach_fields) > 0
                    OR cardinality(at_risk_fields) > 0)
                ORDER BY computed_at ASC
                LIMIT %s
                """,
                (last_ts, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_ts = [], last_ts
        for row in rows:
            has_breach  = bool(row["breach_fields"])
            active_flds = row["breach_fields"] if has_breach else row["at_risk_fields"]
            fields_str  = ", ".join(active_flds or [])
            meta: Dict[str, Any] = {
                "month":         str(row["month"]),
                "breach_fields": list(row["breach_fields"] or []),
                "at_risk_fields": list(row["at_risk_fields"] or []),
            }
            if row["uptime_actual_pct"] is not None:
                meta["uptime_actual_pct"] = float(row["uptime_actual_pct"])
            if row["backup_success_pct"] is not None:
                meta["backup_success_pct"] = float(row["backup_success_pct"])
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["computed_at"],
                "event_type":  "sla_breached" if has_breach else "sla_at_risk",
                "category":    "sla",
                "severity":    "critical" if has_breach else "warning",
                "title":       f"SLA {'breach' if has_breach else 'at risk'}: {fields_str}",
                "metadata":    json.dumps(meta),
                "entity_type": "tenant",
                "entity_id":   row["tenant_id"],
                "domain_id":   row["tenant_id"],
                "region_id":   row["region_id"] or "global",
                "source":      "sla_compliance_monthly",
                "source_id":   f"{row['tenant_id']}:{row['month']}:{row['region_id']}",
            })
            events.append(ev)
            if row["computed_at"] > max_ts:
                max_ts = row["computed_at"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: sla — %d inserted", count)
        self._advance_cursor("sla_compliance_monthly", last_ts=max_ts)

    # ------------------------------------------------------------------
    # runbook_executions — runbook_executed / runbook_failed
    # ------------------------------------------------------------------
    def _harvest_runbooks(self) -> None:
        last_id, _ = self._get_cursor("runbook_executions")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, execution_id, runbook_name, status, triggered_by,
                       triggered_at, completed_at, error_message,
                       items_found, items_actioned
                FROM runbook_executions
                WHERE id > %s
                  AND status IN ('completed', 'failed')
                ORDER BY id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            is_ok    = row["status"] == "completed"
            occurred = row["completed_at"] or row["triggered_at"]
            meta: Dict[str, Any] = {
                "items_found":    row["items_found"],
                "items_actioned": row["items_actioned"],
            }
            if row["error_message"]:
                meta["error_message"] = row["error_message"]
            ev = self._ev_base()
            ev.update({
                "occurred_at": occurred,
                "event_type":  "runbook_executed" if is_ok else "runbook_failed",
                "category":    "runbook",
                "severity":    "info" if is_ok else "critical",
                "title":       (
                    f"{'Runbook executed' if is_ok else 'Runbook failed'}: "
                    f"{row['runbook_name']}"
                ),
                "description": row["error_message"],
                "metadata":    json.dumps(meta),
                "entity_type": "system",
                "entity_id":   row["execution_id"],
                "entity_name": row["runbook_name"],
                "source":      "runbook_executions",
                "source_id":   str(row["id"]),
                "actor":       row["triggered_by"],
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: runbooks — %d inserted", count)
        self._advance_cursor("runbook_executions", last_id=max_id)

    # ------------------------------------------------------------------
    # metering_efficiency — cpu_spike / ram_spike
    # High efficiency score (>85) = high utilisation on that VM
    # ------------------------------------------------------------------
    def _harvest_efficiency(self) -> None:
        last_id, _ = self._get_cursor("metering_efficiency")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT me.id, me.collected_at, me.vm_id, me.vm_name, me.project_name,
                       me.domain, me.cpu_efficiency, me.ram_efficiency, me.region_id,
                       COALESCE(p.domain_id, d_dm.id) AS domain_id,
                       COALESCE(d_p.name, d_dm.name)  AS resolved_domain_name
                FROM metering_efficiency me
                LEFT JOIN projects p   ON p.name = me.project_name
                LEFT JOIN domains  d_p ON d_p.id = p.domain_id
                LEFT JOIN domains  d_dm ON d_dm.name = me.domain
                WHERE me.id > %s
                  AND (me.cpu_efficiency > 85 OR me.ram_efficiency > 85)
                ORDER BY me.id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            cpu = float(row["cpu_efficiency"] or 0)
            ram = float(row["ram_efficiency"] or 0)
            if cpu > 85:
                ev = self._ev_base()
                ev.update({
                    "occurred_at": row["collected_at"],
                    "event_type":  "cpu_spike",
                    "category":    "monitoring",
                    "severity":    "critical" if cpu > 95 else "warning",
                    "title":       f"CPU spike on {row['vm_name'] or row['vm_id']}: {cpu:.0f}%",
                    "metadata":    json.dumps({
                        "cpu_efficiency": cpu,
                        "ram_efficiency": float(row["ram_efficiency"] or 0),
                    }),
                    "entity_type": "vm",
                    "entity_id":   row["vm_id"],
                    "entity_name": row["vm_name"],
                    "project_name": row["project_name"],
                    "domain_id":   row["domain_id"],
                    "domain_name": row["resolved_domain_name"],
                    "region_id":   row["region_id"] or "global",
                    "source":      "metering_efficiency",
                    "source_id":   f"cpu:{row['id']}",
                })
                events.append(ev)
            if ram > 85:
                ev = self._ev_base()
                ev.update({
                    "occurred_at": row["collected_at"],
                    "event_type":  "ram_spike",
                    "category":    "monitoring",
                    "severity":    "critical" if ram > 95 else "warning",
                    "title":       f"RAM spike on {row['vm_name'] or row['vm_id']}: {ram:.0f}%",
                    "metadata":    json.dumps({
                        "cpu_efficiency": float(row["cpu_efficiency"] or 0),
                        "ram_efficiency": ram,
                    }),
                    "entity_type": "vm",
                    "entity_id":   row["vm_id"],
                    "entity_name": row["vm_name"],
                    "project_name": row["project_name"],
                    "domain_id":   row["domain_id"],
                    "domain_name": row["resolved_domain_name"],
                    "region_id":   row["region_id"] or "global",
                    "source":      "metering_efficiency",
                    "source_id":   f"ram:{row['id']}",
                })
                events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: metering_efficiency — %d inserted", count)
        self._advance_cursor("metering_efficiency", last_id=max_id)

    # ------------------------------------------------------------------
    # metering_quotas — storage_high (>85% of quota)
    # ------------------------------------------------------------------
    def _harvest_quotas(self) -> None:
        last_id, _ = self._get_cursor("metering_quotas")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, collected_at, project_id, project_name, domain,
                       storage_used_gb, storage_quota_gb, region_id
                FROM metering_quotas
                WHERE id > %s
                  AND storage_quota_gb > 0
                  AND (storage_used_gb::float / storage_quota_gb::float) > 0.85
                ORDER BY id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            used  = row["storage_used_gb"] or 0
            quota = row["storage_quota_gb"] or 1
            pct   = round(used * 100 / quota, 1)
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["collected_at"],
                "event_type":  "storage_high",
                "category":    "monitoring",
                "severity":    "critical" if pct > 95 else "warning",
                "title":       (
                    f"Storage high for {row['project_name'] or row['project_id']}: {pct}%"
                ),
                "metadata":    json.dumps({
                    "storage_used_gb":  used,
                    "storage_quota_gb": quota,
                    "pct":              pct,
                }),
                "entity_type": "tenant",
                "entity_id":   row["project_id"],
                "entity_name": row["project_name"],
                "domain_name": row["domain"],
                "project_id":  row["project_id"],
                "project_name": row["project_name"],
                "region_id":   row["region_id"] or "global",
                "source":      "metering_quotas",
                "source_id":   str(row["id"]),
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: metering_quotas — %d inserted", count)
        self._advance_cursor("metering_quotas", last_id=max_id)

    # ------------------------------------------------------------------
    # auth_audit_log — user_login / user_role_changed  (visibility=security)
    # ------------------------------------------------------------------
    def _harvest_auth(self) -> None:
        last_id, _ = self._get_cursor("auth_audit_log")
        last_id = last_id or 0
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.id, a.timestamp, a.username, a.action, a.success,
                       a.ip_address, a.details,
                       u.domain_id AS resolved_domain_id,
                       d.name      AS resolved_domain_name
                FROM auth_audit_log a
                LEFT JOIN users   u ON u.name = a.username
                LEFT JOIN domains d ON d.id   = u.domain_id
                WHERE a.id > %s
                  AND a.action IN ('login', 'failed_login', 'permission_changed')
                ORDER BY a.id ASC
                LIMIT %s
                """,
                (last_id, BATCH_SIZE),
            )
            rows = cur.fetchall()
        if not rows:
            return
        events, max_id = [], last_id
        for row in rows:
            action = row["action"]
            if action in ("login", "failed_login"):
                success    = row["success"]
                event_type = "user_login"
                severity   = "info" if success else "warning"
                title      = (
                    f"{'Login' if success else 'Failed login'}: "
                    f"{row['username'] or '?'}"
                )
            else:  # permission_changed
                event_type = "user_role_changed"
                severity   = "warning"
                title      = f"Permission changed for {row['username'] or '?'}"
            meta = dict(row["details"] or {})
            if row["ip_address"]:
                meta["ip_address"] = str(row["ip_address"])
            ev = self._ev_base()
            ev.update({
                "occurred_at": row["timestamp"],
                "event_type":  event_type,
                "category":    "security",
                "severity":    severity,
                "title":       title,
                "metadata":    json.dumps(meta),
                "entity_type": "user",
                "entity_id":   row["username"] or str(row["id"]),
                "entity_name": row["username"],
                "domain_id":   row["resolved_domain_id"],
                "domain_name": row["resolved_domain_name"],
                "source":      "auth_audit_log",
                "source_id":   str(row["id"]),
                "actor":       row["username"] or "unknown",
                "visibility":  "security",
            })
            events.append(ev)
            if row["id"] > max_id:
                max_id = row["id"]
        count = self._bulk_insert(events)
        log.info("TimelineHarvester: auth_audit_log — %d inserted", count)
        self._advance_cursor("auth_audit_log", last_id=max_id)

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------
    def _prune_old_events(self) -> None:
        if RETENTION_DAYS <= 0:
            return
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM operational_events "
                    "WHERE recorded_at < NOW() - INTERVAL '1 day' * %s",
                    (RETENTION_DAYS,),
                )
                pruned = cur.rowcount
            self.conn.commit()
            if pruned:
                log.info(
                    "TimelineHarvester: pruned %d events older than %d days",
                    pruned,
                    RETENTION_DAYS,
                )
        except Exception as exc:
            log.warning("TimelineHarvester: pruning failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:  # nosec B110 — best-effort rollback, never propagate
                pass
