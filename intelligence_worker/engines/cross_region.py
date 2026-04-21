"""
Cross-Region Intelligence Engine — Phase 3

Detects imbalances and concentration risks across hypervisor regions.

Detectors:
  E1 — Utilization imbalance  : one region at ≥ 80% vCPU allocation while
                                 another is ≤ 40% — suggest workload migration.
  E2 — Risk concentration     : ≥ 3 critical/high insights concentrated in
                                 a single region — flag for DR/availability review.
  E3 — Growth rate divergence : one region growing > 2× the fleet average —
                                 capacity planning signal.

Insight type: cross_region
Insight entity: region (entity_type="region", entity_id=<region_id>)
"""
from __future__ import annotations

import logging
from typing import Dict, List

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.cross_region")

_INSIGHT_TYPE = "cross_region"

# Thresholds
_UTILIZATION_HIGH_PCT = 80.0   # region is "overloaded" above this
_UTILIZATION_LOW_PCT  = 40.0   # region is "underutilised" below this
_RISK_CONCENTRATION   = 3      # min critical/high insights in one region
_GROWTH_DIVERGENCE    = 2.0    # region grows > N× the fleet average


class CrossRegionEngine(BaseEngine):

    def run(self) -> None:
        regions = self._load_region_stats()
        if len(regions) < 2:
            # Cross-region analysis requires at least 2 regions
            log.debug("CrossRegionEngine: only %d region(s) — skipping", len(regions))
            return

        log.info("CrossRegionEngine: evaluating %d regions", len(regions))
        try:
            self._check_utilization_imbalance(regions)
        except Exception as exc:
            log.warning("CrossRegionEngine E1 failed: %s", exc)
        try:
            self._check_risk_concentration(regions)
        except Exception as exc:
            log.warning("CrossRegionEngine E2 failed: %s", exc)
        try:
            self._check_growth_divergence(regions)
        except Exception as exc:
            log.warning("CrossRegionEngine E3 failed: %s", exc)

    # ------------------------------------------------------------------
    # Data loader
    # ------------------------------------------------------------------

    def _load_region_stats(self) -> List[Dict]:
        """Return one dict per region with hypervisor aggregate metrics."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    region_id,
                    COUNT(*)                        AS hypervisor_count,
                    SUM(vcpus)                      AS total_vcpus,
                    SUM(memory_mb)                  AS total_ram_mb,
                    SUM(running_vms)                AS running_vms,
                    -- Allocated vCPUs from active servers
                    COALESCE((
                        SELECT SUM(f.vcpus)
                        FROM servers s
                        JOIN flavors f ON f.id = s.flavor_id
                        JOIN hypervisors h2 ON h2.id = s.hypervisor_id
                        WHERE h2.region_id = hypervisors.region_id
                          AND s.status = 'ACTIVE'
                    ), 0)                           AS allocated_vcpus,
                    -- Critical/high open insights scoped to hypervisors in this region
                    (
                        SELECT COUNT(*)
                        FROM operational_insights oi
                        JOIN hypervisors hv ON hv.id::text = oi.entity_id
                        WHERE hv.region_id = hypervisors.region_id
                          AND oi.severity IN ('critical','high')
                          AND oi.status IN ('open','acknowledged','snoozed')
                    )                               AS critical_high_insights
                FROM hypervisors
                WHERE state = 'up'
                GROUP BY region_id
                HAVING SUM(vcpus) > 0
            """)
            rows = [dict(r) for r in cur.fetchall()]

        # Enrich with VM-count 7-day growth rate per region
        for row in rows:
            region_id = row["region_id"]
            try:
                with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT
                            DATE_TRUNC('day', s.recorded_at) AS day,
                            COUNT(DISTINCT s.id)             AS vm_count
                        FROM servers_history s
                        JOIN hypervisors h ON h.hostname = s.hypervisor_hostname
                        WHERE h.region_id = %s
                          AND s.status    = 'ACTIVE'
                          AND s.recorded_at >= NOW() - INTERVAL '14 days'
                        GROUP BY 1
                        ORDER BY 1 ASC
                    """, (region_id,))
                    days = cur.fetchall()
                if len(days) >= 7:
                    half = len(days) // 2
                    early_avg = sum(d["vm_count"] for d in days[:half]) / half
                    late_avg  = sum(d["vm_count"] for d in days[half:]) / max(1, len(days) - half)
                    row["growth_rate"] = (late_avg - early_avg) / max(1, early_avg)
                else:
                    row["growth_rate"] = 0.0
            except Exception:
                row["growth_rate"] = 0.0

        return rows

    # ------------------------------------------------------------------
    # E1 — Utilization imbalance
    # ------------------------------------------------------------------

    def _check_utilization_imbalance(self, regions: List[Dict]) -> None:
        """Flag when one region is heavily loaded while another is lightly used."""
        utilization: Dict[str, float] = {}
        for r in regions:
            total = float(r["total_vcpus"] or 0)
            alloc = float(r["allocated_vcpus"] or 0)
            utilization[r["region_id"]] = (alloc / total * 100) if total > 0 else 0

        overloaded  = [rid for rid, pct in utilization.items() if pct >= _UTILIZATION_HIGH_PCT]
        underloaded = [rid for rid, pct in utilization.items() if pct <= _UTILIZATION_LOW_PCT]

        if not overloaded or not underloaded:
            # Resolve any previously fired insight for all regions
            for r in regions:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_imbalance", "region", r["region_id"])
            return

        # Fire one insight per overloaded region pointing at underloaded peers
        for over_rid in overloaded:
            over_pct   = utilization[over_rid]
            under_list = ", ".join(
                f"{rid} ({utilization[rid]:.0f}%)" for rid in underloaded
            )
            self.upsert_insight(
                type=f"{_INSIGHT_TYPE}_imbalance",
                severity="high" if over_pct >= 90 else "medium",
                entity_type="region",
                entity_id=over_rid,
                entity_name=over_rid,
                title=(
                    f"Region {over_rid} vCPU utilization at {over_pct:.0f}% "
                    f"while peer region(s) are underutilised"
                ),
                message=(
                    f"Region {over_rid!r} has {over_pct:.1f}% vCPU allocation. "
                    f"The following region(s) have available headroom: {under_list}. "
                    f"Consider migrating workloads to balance the fleet."
                ),
                metadata={
                    "region_utilization": {rid: round(pct, 1) for rid, pct in utilization.items()},
                    "overloaded_pct":  round(over_pct, 1),
                    "underloaded_regions": underloaded,
                },
            )

        # Resolve overloaded-insight for regions that are now below threshold
        for r in regions:
            if r["region_id"] not in overloaded:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_imbalance", "region", r["region_id"])

    # ------------------------------------------------------------------
    # E2 — Risk concentration
    # ------------------------------------------------------------------

    def _check_risk_concentration(self, regions: List[Dict]) -> None:
        """Flag when critical/high insights concentrate in a single region."""
        total_insights = sum(int(r["critical_high_insights"] or 0) for r in regions)
        if total_insights == 0:
            for r in regions:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_concentration", "region", r["region_id"])
            return

        for reg in regions:
            region_id = reg["region_id"]
            count = int(reg["critical_high_insights"] or 0)
            if count < _RISK_CONCENTRATION:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_concentration", "region", region_id)
                continue
            share = count / total_insights * 100
            severity = "high" if share >= 70 else "medium"
            self.upsert_insight(
                type=f"{_INSIGHT_TYPE}_concentration",
                severity=severity,
                entity_type="region",
                entity_id=region_id,
                entity_name=region_id,
                title=(
                    f"Risk concentration: region {region_id} holds "
                    f"{count} critical/high insights ({share:.0f}% of fleet total)"
                ),
                message=(
                    f"Region {region_id!r} has {count} active critical or high severity insights, "
                    f"representing {share:.0f}% of all fleet-wide critical/high insights. "
                    f"This concentration increases single-region failure risk. "
                    f"Review tenant placement and disaster recovery coverage."
                ),
                metadata={
                    "critical_high_count": count,
                    "fleet_total":         total_insights,
                    "concentration_pct":   round(share, 1),
                    "hypervisors":         int(reg["hypervisor_count"] or 0),
                },
            )

    # ------------------------------------------------------------------
    # E3 — Growth rate divergence
    # ------------------------------------------------------------------

    def _check_growth_divergence(self, regions: List[Dict]) -> None:
        """Flag when one region is growing significantly faster than the fleet average."""
        growth_rates = [float(r.get("growth_rate", 0)) for r in regions]
        # Need at least some growth to flag divergence
        positive_rates = [g for g in growth_rates if g > 0]
        if not positive_rates:
            for r in regions:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_growth", "region", r["region_id"])
            return

        fleet_avg = sum(positive_rates) / len(positive_rates)
        if fleet_avg <= 0:
            for r in regions:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_growth", "region", r["region_id"])
            return

        for reg in regions:
            region_id   = reg["region_id"]
            rate        = float(reg.get("growth_rate", 0))
            ratio       = rate / fleet_avg if fleet_avg > 0 else 0

            if ratio < _GROWTH_DIVERGENCE:
                self.suppress_resolved(f"{_INSIGHT_TYPE}_growth", "region", region_id)
                continue

            severity = "high" if ratio >= 3.0 else "medium"
            self.upsert_insight(
                type=f"{_INSIGHT_TYPE}_growth",
                severity=severity,
                entity_type="region",
                entity_id=region_id,
                entity_name=region_id,
                title=(
                    f"Region {region_id} is growing {ratio:.1f}× faster than fleet average"
                ),
                message=(
                    f"Region {region_id!r} VM count grew {rate * 100:.0f}% over the last 7 days, "
                    f"which is {ratio:.1f}× the fleet average growth of {fleet_avg * 100:.0f}%. "
                    f"This rapid growth may exhaust capacity sooner than forecast. "
                    f"Review provisioning pipelines and capacity plan for this region."
                ),
                metadata={
                    "region_growth_rate": round(rate, 4),
                    "fleet_avg_rate":     round(fleet_avg, 4),
                    "growth_ratio":       round(ratio, 2),
                    "running_vms":        int(reg.get("running_vms") or 0),
                    "hypervisors":        int(reg.get("hypervisor_count") or 0),
                },
            )
