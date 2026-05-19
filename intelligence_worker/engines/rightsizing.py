"""
Rightsizing Engine — Workload Right-Sizing & Cost Waste Detection.

Analyses each VM's actual CPU/memory utilisation vs. allocated flavor over
rolling 7-day and 30-day windows, then classifies VMs as:
  idle             — <5% avg CPU AND <10% avg RAM for 7+ days
  over_provisioned — <30% p95 CPU AND <40% p95 RAM sustained
  right_sized      — utilisation in healthy range (30–80% p95)
  under_provisioned— p95 CPU or RAM > 85%

For idle and over_provisioned VMs the engine:
  1. Writes/updates a row in rightsizing_recommendations.
  2. Identifies the next-smaller standard flavor from the flavors table.
  3. Calculates estimated monthly savings using metering_pricing or
     metering_config cost model as fallback.
  4. Upserts a rightsizing_alert operational_insight.

For right_sized and under_provisioned VMs any existing open recommendations
are resolved/superseded.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.rightsizing")

_INSIGHT_TYPE = "rightsizing_alert"

# Thresholds
_IDLE_CPU_AVG    = 5.0    # % avg CPU to be considered idle
_IDLE_RAM_AVG    = 10.0   # % avg RAM to be considered idle
_OVER_CPU_P95    = 30.0   # % p95 CPU to be considered over-provisioned
_OVER_RAM_P95    = 40.0   # % p95 RAM to be considered over-provisioned
_UNDER_CPU_P95   = 85.0   # % p95 CPU to be considered under-provisioned
_UNDER_RAM_P95   = 85.0   # % p95 RAM to be considered under-provisioned


class RightsizingEngine(BaseEngine):

    def run(self) -> None:
        cost_model = self._load_cost_model()
        flavors = self._load_flavors()
        pricing = self._load_flavor_pricing()
        vm_stats = self._compute_vm_stats()
        for row in vm_stats:
            self._process_vm(row, cost_model, flavors, pricing)
        self._resolve_stale_recommendations(vm_stats)

    # ------------------------------------------------------------------
    # Data loaders
    # ------------------------------------------------------------------

    def _load_cost_model(self) -> Dict[str, float]:
        """Load global cost model from metering_config."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT cost_per_vcpu_hour, cost_per_gb_ram_hour, cost_currency
                    FROM metering_config LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    return {
                        "vcpu_hour": float(row["cost_per_vcpu_hour"] or 0),
                        "gb_ram_hour": float(row["cost_per_gb_ram_hour"] or 0),
                        "currency": row["cost_currency"] or "USD",
                    }
        except Exception as exc:
            log.warning("cost_model load failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:
                pass
        return {"vcpu_hour": 0.0, "gb_ram_hour": 0.0, "currency": "USD"}

    def _load_flavors(self) -> List[Dict[str, Any]]:
        """Load all flavors sorted by vcpus then ram_mb ascending."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, name, vcpus, ram_mb, disk_gb
                    FROM flavors
                    WHERE vcpus IS NOT NULL AND ram_mb IS NOT NULL
                    ORDER BY vcpus ASC, ram_mb ASC
                """)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            log.warning("flavors load failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:
                pass
        return []

    def _load_flavor_pricing(self) -> Dict[str, float]:
        """Load per-flavor hourly cost from metering_pricing if available."""
        pricing: Dict[str, float] = {}
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT flavor_name, price_per_hour FROM metering_pricing")
                for row in cur.fetchall():
                    if row["flavor_name"] and row["price_per_hour"] is not None:
                        pricing[row["flavor_name"]] = float(row["price_per_hour"])
        except Exception:
            pass  # metering_pricing may not exist in older environments
            try:
                self.conn.rollback()
            except Exception:
                pass
        return pricing

    def _compute_vm_stats(self) -> List[Dict[str, Any]]:
        """
        Aggregate metering_resources rows per VM over last 30 days.
        Returns VMs that have sufficient data (>= 4 data points in last 7 days).
        """
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    WITH base AS (
                        SELECT
                            vm_id, vm_name, project_name,
                            COALESCE(region_id, '') AS region_id,
                            domain,
                            flavor,
                            vcpus_allocated,
                            ram_allocated_mb,
                            cpu_usage_percent,
                            ram_usage_percent,
                            collected_at,
                            collected_at >= NOW() - INTERVAL '7 days' AS in_7d
                        FROM metering_resources
                        WHERE collected_at >= NOW() - INTERVAL '30 days'
                          AND cpu_usage_percent IS NOT NULL
                          AND ram_usage_percent IS NOT NULL
                    ),
                    stats AS (
                        SELECT
                            vm_id,
                            MAX(vm_name)        AS vm_name,
                            MAX(project_name)   AS project_name,
                            MAX(region_id)      AS region_id,
                            MAX(domain)         AS domain,
                            MAX(flavor)         AS flavor,
                            MAX(vcpus_allocated)  AS vcpus_allocated,
                            MAX(ram_allocated_mb) AS ram_allocated_mb,
                            -- 7-day stats
                            COUNT(*) FILTER (WHERE in_7d)          AS rows_7d,
                            AVG(cpu_usage_percent) FILTER (WHERE in_7d) AS cpu_avg_7d,
                            AVG(ram_usage_percent) FILTER (WHERE in_7d) AS ram_avg_7d,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (
                                ORDER BY cpu_usage_percent
                            ) FILTER (WHERE in_7d)                 AS cpu_p95_7d,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (
                                ORDER BY ram_usage_percent
                            ) FILTER (WHERE in_7d)                 AS ram_p95_7d,
                            -- 30-day stats
                            PERCENTILE_CONT(0.95) WITHIN GROUP (
                                ORDER BY cpu_usage_percent
                            )                                      AS cpu_p95_30d,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (
                                ORDER BY ram_usage_percent
                            )                                      AS ram_p95_30d
                        FROM base
                        GROUP BY vm_id
                    )
                    SELECT *
                    FROM stats
                    WHERE rows_7d >= 4
                """)
                return [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            log.warning("vm_stats query failed: %s", exc)
            try:
                self.conn.rollback()
            except Exception:
                pass
        return []

    # ------------------------------------------------------------------
    # Per-VM processing
    # ------------------------------------------------------------------

    def _classify(self, row: Dict[str, Any]) -> str:
        cpu_avg = float(row.get("cpu_avg_7d") or 0)
        ram_avg = float(row.get("ram_avg_7d") or 0)
        cpu_p95 = float(row.get("cpu_p95_7d") or 0)
        ram_p95 = float(row.get("ram_p95_7d") or 0)

        if cpu_avg < _IDLE_CPU_AVG and ram_avg < _IDLE_RAM_AVG:
            return "idle"
        if cpu_p95 < _OVER_CPU_P95 and ram_p95 < _OVER_RAM_P95:
            return "over_provisioned"
        if cpu_p95 > _UNDER_CPU_P95 or ram_p95 > _UNDER_RAM_P95:
            return "under_provisioned"
        return "right_sized"

    def _find_recommended_flavor(
        self,
        flavors: List[Dict[str, Any]],
        current_vcpus: Optional[int],
        current_ram_mb: Optional[int],
        classification: str,
    ) -> Optional[Dict[str, Any]]:
        """Find the smallest flavor that still covers needs (with headroom)."""
        if not flavors or not current_vcpus or not current_ram_mb:
            return None
        if classification not in ("idle", "over_provisioned"):
            return None

        # For idle VMs, recommend the smallest available flavor.
        # For over-provisioned, recommend a flavor where
        #   vcpus >= ceil(current_vcpus * 0.5) and
        #   ram_mb >= ceil(current_ram_mb * 0.5)
        if classification == "idle":
            return flavors[0]

        # over_provisioned: need at least 50% of current allocation
        min_vcpus = max(1, (current_vcpus + 1) // 2)
        min_ram   = max(512, (current_ram_mb + 1) // 2)

        for f in flavors:
            if (f["vcpus"] or 0) >= min_vcpus and (f["ram_mb"] or 0) >= min_ram:
                # Only recommend if it's actually smaller
                if (f["vcpus"] or 0) < current_vcpus or (f["ram_mb"] or 0) < current_ram_mb:
                    return f
        return None

    def _estimate_monthly_savings(
        self,
        current_vcpus: Optional[int],
        current_ram_mb: Optional[int],
        rec_vcpus: Optional[int],
        rec_ram_mb: Optional[int],
        current_flavor: Optional[str],
        rec_flavor: Optional[str],
        cost_model: Dict[str, float],
        pricing: Dict[str, float],
    ) -> float:
        """Calculate estimated monthly savings in USD."""
        hours_per_month = 730.0

        # Use flavor-level pricing if available
        if current_flavor and rec_flavor and current_flavor in pricing and rec_flavor in pricing:
            diff = pricing[current_flavor] - pricing[rec_flavor]
            return round(max(0.0, diff * hours_per_month), 2)

        # Fall back to component cost model
        vcpu_rate   = cost_model.get("vcpu_hour", 0.0)
        ram_rate    = cost_model.get("gb_ram_hour", 0.0)
        if not (vcpu_rate or ram_rate):
            return 0.0

        cur_vcpus = current_vcpus or 0
        cur_ram   = (current_ram_mb or 0) / 1024.0
        rec_v     = rec_vcpus or 0
        rec_r     = (rec_ram_mb or 0) / 1024.0

        delta_vcpu = max(0, cur_vcpus - rec_v)
        delta_ram  = max(0.0, cur_ram - rec_r)

        savings = (delta_vcpu * vcpu_rate + delta_ram * ram_rate) * hours_per_month
        return round(savings, 2)

    def _process_vm(
        self,
        row: Dict[str, Any],
        cost_model: Dict[str, float],
        flavors: List[Dict[str, Any]],
        pricing: Dict[str, float],
    ) -> None:
        vm_id   = row["vm_id"]
        vm_name = row["vm_name"] or vm_id
        project = row["project_name"] or "unknown"
        region  = row["region_id"] or ""
        domain  = row["domain"] or ""
        flavor  = row["flavor"]
        cur_vcpus = row.get("vcpus_allocated")
        cur_ram   = row.get("ram_allocated_mb")

        classification = self._classify(row)

        rec_flavor_row = self._find_recommended_flavor(
            flavors, cur_vcpus, cur_ram, classification
        )
        rec_flavor  = rec_flavor_row["name"] if rec_flavor_row else None
        rec_vcpus   = rec_flavor_row["vcpus"] if rec_flavor_row else None
        rec_ram     = rec_flavor_row["ram_mb"] if rec_flavor_row else None

        savings = self._estimate_monthly_savings(
            cur_vcpus, cur_ram, rec_vcpus, rec_ram,
            flavor, rec_flavor, cost_model, pricing
        )
        currency = cost_model.get("currency", "USD")

        # Upsert into rightsizing_recommendations
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO rightsizing_recommendations (
                        vm_id, vm_name, project_name, region_id, domain,
                        classification,
                        current_flavor, current_vcpus, current_ram_mb,
                        recommended_flavor, recommended_vcpus, recommended_ram_mb,
                        cpu_p95_7d, ram_p95_7d, cpu_avg_7d, ram_avg_7d,
                        cpu_p95_30d, ram_p95_30d,
                        analysis_period_days,
                        estimated_monthly_savings_usd, currency,
                        status, computed_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s,
                        7,
                        %s, %s,
                        'open', NOW(), NOW()
                    )
                    ON CONFLICT (vm_id)
                    WHERE status IN ('open', 'snoozed')
                    DO UPDATE SET
                        vm_name        = EXCLUDED.vm_name,
                        project_name   = EXCLUDED.project_name,
                        region_id      = EXCLUDED.region_id,
                        classification = EXCLUDED.classification,
                        current_flavor = EXCLUDED.current_flavor,
                        current_vcpus  = EXCLUDED.current_vcpus,
                        current_ram_mb = EXCLUDED.current_ram_mb,
                        recommended_flavor = EXCLUDED.recommended_flavor,
                        recommended_vcpus  = EXCLUDED.recommended_vcpus,
                        recommended_ram_mb = EXCLUDED.recommended_ram_mb,
                        cpu_p95_7d     = EXCLUDED.cpu_p95_7d,
                        ram_p95_7d     = EXCLUDED.ram_p95_7d,
                        cpu_avg_7d     = EXCLUDED.cpu_avg_7d,
                        ram_avg_7d     = EXCLUDED.ram_avg_7d,
                        cpu_p95_30d    = EXCLUDED.cpu_p95_30d,
                        ram_p95_30d    = EXCLUDED.ram_p95_30d,
                        estimated_monthly_savings_usd = EXCLUDED.estimated_monthly_savings_usd,
                        updated_at     = NOW()
                """, (
                    vm_id, vm_name, project, region, domain,
                    classification,
                    flavor, cur_vcpus, cur_ram,
                    rec_flavor, rec_vcpus, rec_ram,
                    row.get("cpu_p95_7d"), row.get("ram_p95_7d"),
                    row.get("cpu_avg_7d"), row.get("ram_avg_7d"),
                    row.get("cpu_p95_30d"), row.get("ram_p95_30d"),
                    savings, currency,
                ))
            self.conn.commit()
        except Exception as exc:
            log.warning("upsert recommendation for VM %s failed: %s", vm_id, exc)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return

        # Only generate operational insights for waste classifications
        if classification in ("idle", "over_provisioned"):
            severity = "medium" if classification == "idle" else "low"
            savings_str = f"~${savings:.0f}/mo" if savings > 0 else "unknown savings"
            title = (
                f"VM {vm_name} is {classification.replace('_', ' ')} "
                f"— {savings_str} in potential savings"
            )
            cpu_p95 = float(row.get("cpu_p95_7d") or 0)
            ram_p95 = float(row.get("ram_p95_7d") or 0)
            message = (
                f"VM {vm_name!r} in project {project!r} "
                f"(region: {region or 'default'}) "
                f"has been {classification.replace('_', ' ')} over the past 7 days. "
                f"CPU p95: {cpu_p95:.1f}%, RAM p95: {ram_p95:.1f}%. "
                f"Current flavor: {flavor or 'unknown'}. "
                + (f"Recommended: {rec_flavor}. " if rec_flavor else "")
                + f"Estimated savings: {savings_str}."
            )
            self.upsert_insight(
                type=_INSIGHT_TYPE,
                severity=severity,
                entity_type="vm",
                entity_id=vm_id,
                entity_name=vm_name,
                title=title,
                message=message,
                metadata={
                    "classification":              classification,
                    "project":                     project,
                    "region":                      region,
                    "current_flavor":              flavor,
                    "recommended_flavor":          rec_flavor,
                    "cpu_p95_7d":                  float(row.get("cpu_p95_7d") or 0),
                    "ram_p95_7d":                  float(row.get("ram_p95_7d") or 0),
                    "estimated_monthly_savings":   savings,
                    "currency":                    currency,
                },
            )

    # ------------------------------------------------------------------
    # Stale recommendation cleanup
    # ------------------------------------------------------------------

    def _resolve_stale_recommendations(self, vm_stats: List[Dict[str, Any]]) -> None:
        """
        Mark open recommendations as 'actioned' for VMs that are now right_sized
        or that no longer exist / have no recent data.
        """
        active_vm_ids = {r["vm_id"] for r in vm_stats}
        right_sized_vm_ids = {
            r["vm_id"] for r in vm_stats if self._classify(r) == "right_sized"
        }

        # Resolve recommendations for right-sized VMs
        if right_sized_vm_ids:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("""
                        UPDATE rightsizing_recommendations
                        SET status = 'actioned', actioned_at = NOW(),
                            actioned_by = 'auto_resolved'
                        WHERE vm_id = ANY(%s) AND status IN ('open', 'snoozed')
                    """, (list(right_sized_vm_ids),))
                self.conn.commit()
            except Exception as exc:
                log.warning("resolve right_sized recommendations failed: %s", exc)
                try:
                    self.conn.rollback()
                except Exception:
                    pass

        # Suppress operational insights for right_sized VMs
        for vm_id in right_sized_vm_ids:
            self.suppress_resolved(_INSIGHT_TYPE, "vm", vm_id)

        # Resolve recommendations for VMs that have dropped out of metering data
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT vm_id FROM rightsizing_recommendations
                    WHERE status IN ('open', 'snoozed')
                """)
                open_vm_ids = [r["vm_id"] for r in cur.fetchall()]
        except Exception as exc:
            log.warning("stale recommendation lookup failed: %s", exc)
            return

        for vm_id in open_vm_ids:
            if vm_id not in active_vm_ids:
                # VM no longer exists in metering data
                try:
                    with self.conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM servers WHERE id = %s LIMIT 1", (vm_id,))
                        if not cur.fetchone():
                            with self.conn.cursor() as cur2:
                                cur2.execute("""
                                    UPDATE rightsizing_recommendations
                                    SET status = 'actioned', actioned_at = NOW(),
                                        actioned_by = 'auto_resolved_deleted'
                                    WHERE vm_id = %s AND status IN ('open', 'snoozed')
                                """, (vm_id,))
                            self.conn.commit()
                            self.suppress_resolved(_INSIGHT_TYPE, "vm", vm_id)
                except Exception as exc:
                    log.warning("stale cleanup for VM %s failed: %s", vm_id, exc)
                    try:
                        self.conn.rollback()
                    except Exception:
                        pass
