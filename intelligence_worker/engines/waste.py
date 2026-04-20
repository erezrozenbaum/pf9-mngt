"""
Waste Engine — idle resources that cost money but deliver no value.

Three detectors:
  B1 — Idle VM      : metering_efficiency classification 'idle'/'poor' for ≥ 7 days
  B2 — Unattached volume: volumes.status='available' for ≥ 14 days
  B3 — Snapshot age explosion: snapshots older than 60 days without retention policy
"""
from __future__ import annotations

import logging

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.waste")

_TYPE_VM     = "waste_idle_vm"
_TYPE_VOL    = "waste_unattached_volume"
_TYPE_SNAP   = "waste_old_snapshots"


class WasteEngine(BaseEngine):

    def run(self) -> None:
        self._check_idle_vms()
        self._check_unattached_volumes()
        self._check_old_snapshots()

    # ------------------------------------------------------------------
    # B1 — Idle VMs
    # ------------------------------------------------------------------
    def _check_idle_vms(self) -> None:
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Find VMs classified as idle or poor in their last 7 consecutive
                # entries (one per metering cycle ≈ 15 min; 7 days = ~672 rows
                # but we only care that the last meaningful window is all idle/poor).
                # Simpler and efficient: the classification in the most recent row
                # plus a count of 'idle'/'poor' rows in last 7 days.
                cur.execute("""
                    WITH recent AS (
                        SELECT
                            vm_id, vm_name, project_name, classification,
                            overall_score, cpu_efficiency, ram_efficiency,
                            ROW_NUMBER() OVER (PARTITION BY vm_id ORDER BY collected_at DESC) AS rn
                        FROM metering_efficiency
                        WHERE collected_at >= NOW() - INTERVAL '7 days'
                    ),
                    latest AS (
                        SELECT vm_id, vm_name, project_name, classification,
                               overall_score, cpu_efficiency, ram_efficiency
                        FROM recent WHERE rn = 1
                    ),
                    idle_counts AS (
                        SELECT vm_id, COUNT(*) AS idle_rows,
                               COUNT(DISTINCT date_trunc('day', collected_at)) AS idle_days
                        FROM metering_efficiency
                        WHERE collected_at >= NOW() - INTERVAL '7 days'
                          AND classification IN ('idle','poor')
                        GROUP BY vm_id
                    )
                    SELECT l.vm_id, l.vm_name, l.project_name, l.classification,
                           l.overall_score, l.cpu_efficiency, l.ram_efficiency,
                           ic.idle_days
                    FROM latest l
                    JOIN idle_counts ic ON ic.vm_id = l.vm_id
                    WHERE l.classification IN ('idle','poor')
                      AND ic.idle_days >= 6
                """)
                rows = cur.fetchall()
        except Exception as exc:
            log.warning("idle_vm query failed: %s", exc)
            return

        log.debug("WasteEngine B1: %d idle/poor VMs", len(rows))
        for row in rows:
            vm_id      = row["vm_id"]
            vm_name    = row["vm_name"] or vm_id
            project    = row["project_name"] or "unknown"
            cls        = row["classification"]
            idle_days  = row["idle_days"] or 0
            severity   = "medium" if cls == "idle" else "low"
            score   = float(row["overall_score"] or 0)
            cpu_eff = float(row["cpu_efficiency"] or 0)
            ram_eff = float(row["ram_efficiency"] or 0)
            title = (
                f"VM {vm_name} has been {cls} for {idle_days} day(s) "
                f"— candidate for shutdown or rightsizing"
            )
            message = (
                f"VM {vm_name!r} in project {project!r} has maintained "
                f"{cls!r} efficiency for {idle_days} day(s). "
                f"Overall score: {score:.0f}/100 "
                f"(CPU {cpu_eff:.0f}%, RAM {ram_eff:.0f}%). "
                f"Consider downsizing the flavor, suspending, or decommissioning."
            )
            self.upsert_insight(
                type=_TYPE_VM,
                severity=severity,
                entity_type="vm",
                entity_id=vm_id,
                entity_name=vm_name,
                title=title,
                message=message,
                metadata={
                    "classification":   cls,
                    "idle_days":        idle_days,
                    "overall_score":    score,
                    "cpu_efficiency":   cpu_eff,
                    "ram_efficiency":   ram_eff,
                    "project":          project,
                },
            )

    # ------------------------------------------------------------------
    # B2 — Unattached volumes
    # ------------------------------------------------------------------
    def _check_unattached_volumes(self) -> None:
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT v.id, v.name, v.project_id, v.size_gb,
                           p.name AS project_name,
                           NOW() - v.updated_at AS idle_duration
                    FROM volumes v
                    LEFT JOIN projects p ON p.id = v.project_id
                    WHERE v.status = 'available'
                      AND v.updated_at < NOW() - INTERVAL '14 days'
                    ORDER BY v.size_gb DESC NULLS LAST
                """)
                rows = cur.fetchall()
        except Exception as exc:
            log.warning("unattached_volumes query failed: %s", exc)
            return

        log.debug("WasteEngine B2: %d unattached volumes", len(rows))
        for row in rows:
            vol_id    = row["id"]
            vol_name  = row["name"] or vol_id
            size_gb   = row["size_gb"] or 0
            project   = row["project_name"] or (row["project_id"] or "unknown")
            duration  = row["idle_duration"]
            idle_days = duration.days if duration else 14

            severity = "medium" if size_gb >= 100 else "low"
            title = (
                f"Unattached volume {vol_name} ({size_gb} GB) unused for {idle_days} day(s)"
            )
            message = (
                f"Volume {vol_name!r} ({size_gb} GB) in project {project!r} "
                f"has been unattached for {idle_days} day(s). "
                f"Unattached volumes still consume quota. "
                f"Delete if no longer needed or attach to an active VM."
            )
            self.upsert_insight(
                type=_TYPE_VOL,
                severity=severity,
                entity_type="volume",
                entity_id=vol_id,
                entity_name=vol_name,
                title=title,
                message=message,
                metadata={
                    "size_gb":   size_gb,
                    "idle_days": idle_days,
                    "project":   project,
                },
            )

    # ------------------------------------------------------------------
    # B3 — Snapshot age explosion
    # ------------------------------------------------------------------
    def _check_old_snapshots(self) -> None:
        """
        Fire one insight per tenant (project_id) when they have >= 3 snapshots
        older than 60 days and no snapshot_policy_sets assigned to that project.
        """
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        s.project_id,
                        p.name AS project_name,
                        COUNT(*) AS old_count
                    FROM snapshots s
                    LEFT JOIN projects p ON p.id = s.project_id
                    WHERE s.created_at < NOW() - INTERVAL '60 days'
                      AND s.project_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM snapshot_assignments sa
                          WHERE sa.project_id = s.project_id
                      )
                    GROUP BY s.project_id, p.name
                    HAVING COUNT(*) >= 3
                """)
                rows = cur.fetchall()
        except Exception as exc:
            log.warning("old_snapshots query failed: %s", exc)
            return

        log.debug("WasteEngine B3: %d project(s) with stale snapshots", len(rows))
        for row in rows:
            project_id   = row["project_id"]
            project_name = row["project_name"] or project_id
            count        = row["old_count"]
            title = (
                f"Tenant {project_name} has {count} snapshot(s) "
                f"older than 60 days without a retention policy"
            )
            message = (
                f"Project {project_name!r} has {count} snapshots that are more than "
                f"60 days old and no snapshot retention policy is configured. "
                f"Old snapshots consume storage quota. "
                f"Assign a retention policy or manually clean up outdated snapshots."
            )
            self.upsert_insight(
                type=_TYPE_SNAP,
                severity="low",
                entity_type="tenant",
                entity_id=project_id,
                entity_name=project_name,
                title=title,
                message=message,
                metadata={"old_snapshot_count": count},
            )
