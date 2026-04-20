"""
Capacity Engine — storage, compute, and quota growth forecasting.
For each project, fits a linear trend to the last 14 days of metering_quotas
and projects how many days until each resource hits 90 % of quota.
Insight types fired:
  capacity_storage  — storage GiB growth (Phase 1, extended with confidence)
  capacity_compute  — per-hypervisor vCPU / RAM allocation trend (Phase 3)
  capacity_quota    — per-project quota saturation for vCPUs, RAM, instances,
                      floating IPs (Phase 3)
Severity thresholds:
  ≤ 7 days  → critical
  8–14 days → high
  15–30 days→ medium
  > 30 days → no insight (resolved if one was previously open)
Confidence score (0–1) stored in metadata:
  Based on number of data points (saturates at 30) and trend linearity (R²).
  confidence = min(1.0, data_points/30) * max(0, R²)
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Tuple
import psycopg2.extras
from .base import BaseEngine
log = logging.getLogger("intelligence.capacity")
_TYPE_STORAGE = "capacity_storage"
_TYPE_COMPUTE = "capacity_compute"
_TYPE_QUOTA   = "capacity_quota"
# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------
def _linear_regression(xs: List[float], ys: List[float]) -> Tuple[float, float]:
    """
    Simple least-squares linear regression.
    Returns (slope, intercept) where y ≈ slope * x + intercept.
    """
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    sx  = sum(xs)
    sy  = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept
def _r_squared(xs: List[float], ys: List[float], slope: float, intercept: float) -> float:
    """Coefficient of determination — measures trend linearity."""
    if len(ys) < 2:
        return 0.0
    y_mean = sum(ys) / len(ys)
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot == 0:
        return 1.0
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    return max(0.0, 1.0 - ss_res / ss_tot)
def _confidence(data_points: int, r2: float) -> float:
    """
    Confidence score in [0, 1].
    Saturates at 30 data points; scaled by R² (linearity of the trend).
    """
    saturation = min(1.0, data_points / 30.0)
    return round(saturation * max(0.0, r2), 3)
def _days_to_pct(
        current_used: float, quota: float,
        trend_per_day: float, target_pct: float = 90.0) -> Optional[float]:
    """
    How many days at current trend until resource reaches target_pct of quota?
    Returns None if quota is unknown/zero or trend is flat/negative.
    """
    if not quota or quota <= 0 or trend_per_day <= 0:
        return None
    target = quota * target_pct / 100.0
    gap    = target - current_used
    if gap <= 0:
        return 0.0
    return gap / trend_per_day
def _severity_from_days(days: float) -> str:
    if days <= 7:
        return "critical"
    if days <= 14:
        return "high"
    return "medium"
# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class CapacityEngine(BaseEngine):
    def run(self) -> None:
        projects = self._load_projects()
        log.info("CapacityEngine: evaluating %d project(s)", len(projects))
        for proj in projects:
            try:
                self._evaluate_storage(proj)
                self._evaluate_project_quotas(proj)
            except Exception as exc:
                log.warning("CapacityEngine: error on project %s: %s",
                            proj.get("project_id"), exc)
        # Compute / hypervisor-level forecasting
        try:
            self._evaluate_hypervisors()
        except Exception as exc:
            log.warning("CapacityEngine: hypervisor evaluation failed: %s", exc)
    def _load_projects(self) -> list:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT DISTINCT project_id, project_name
                FROM metering_quotas
                WHERE collected_at >= NOW() - INTERVAL '14 days'
                  AND project_id IS NOT NULL
            """)
            return [dict(r) for r in cur.fetchall()]
    # ------------------------------------------------------------------
    # Storage forecast (original Phase 1 detector, with confidence)
    # ------------------------------------------------------------------
    def _evaluate_storage(self, proj: dict) -> None:
        project_id   = proj["project_id"]
        project_name = proj["project_name"] or project_id
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    EXTRACT(EPOCH FROM collected_at) AS ts,
                    storage_quota_gb,
                    storage_used_gb
                FROM metering_quotas
                WHERE project_id = %s
                  AND collected_at >= NOW() - INTERVAL '14 days'
                  AND storage_quota_gb IS NOT NULL
                  AND storage_used_gb  IS NOT NULL
                ORDER BY collected_at ASC
            """, (project_id,))
            rows = cur.fetchall()
        if len(rows) < 7:
            self.suppress_resolved(_TYPE_STORAGE, "project", project_id)
            return
        quota     = float(rows[-1]["storage_quota_gb"])
        used_now  = float(rows[-1]["storage_used_gb"])
        current_pct = (used_now / quota * 100) if quota else 0
        if quota <= 0:
            return
        t0    = float(rows[0]["ts"])
        xs    = [(float(r["ts"]) - t0) / 86400.0 for r in rows]
        ys    = [float(r["storage_used_gb"]) for r in rows]
        slope, intercept = _linear_regression(xs, ys)
        r2    = _r_squared(xs, ys, slope, intercept)
        conf  = _confidence(len(rows), r2)
        days = _days_to_pct(used_now, quota, slope)
        if days is None or days > 30:
            self.suppress_resolved(_TYPE_STORAGE, "project", project_id)
            return
        days_int = max(0, int(days))
        severity = _severity_from_days(days)
        title = (
            f"Storage critical: {project_name} hits 90% capacity in {days_int} day(s)"
            if severity == "critical"
            else f"Storage {'warning' if severity == 'high' else 'trend'}: "
                 f"{project_name} projected to hit 90% in {days_int} day(s)"
        )
        message = (
            f"Project {project_name!r} is using {used_now:.0f} GB of {quota:.0f} GB quota "
            f"({current_pct:.1f}%). At the current growth rate of {slope:.1f} GB/day, "
            f"storage will reach 90% capacity in approximately {days_int} day(s)."
        )
        self.upsert_insight(
            type=_TYPE_STORAGE,
            severity=severity,
            entity_type="project",
            entity_id=project_id,
            entity_name=project_name,
            title=title,
            message=message,
            metadata={
                "current_pct":      round(current_pct, 1),
                "days_to_90":       days_int,
                "trend_gb_per_day": round(slope, 2),
                "data_points":      len(rows),
                "quota_gb":         quota,
                "used_gb":          used_now,
                "confidence":       conf,
                "r_squared":        round(r2, 3),
            },
        )
    # ------------------------------------------------------------------
    # Quota saturation forecast — Phase 3
    # vCPUs, RAM, instances, floating IPs per project
    # ------------------------------------------------------------------
    _QUOTA_RESOURCES: Dict[str, Tuple[str, str, str]] = {
        # internal_key: (used_col, quota_col, display_label)
        "vcpu":        ("vcpus_used",        "vcpus_quota",        "vCPU"),
        "ram":         ("ram_used_mb",        "ram_quota_mb",       "RAM (MB)"),
        "instances":   ("instances_used",     "instances_quota",    "Instances"),
        "floating_ip": ("floating_ips_used",  "floating_ips_quota", "Floating IPs"),
    }
    def _evaluate_project_quotas(self, proj: dict) -> None:
        project_id   = proj["project_id"]
        project_name = proj["project_name"] or project_id
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    EXTRACT(EPOCH FROM collected_at) AS ts,
                    vcpus_used,        vcpus_quota,
                    ram_used_mb,       ram_quota_mb,
                    instances_used,    instances_quota,
                    floating_ips_used, floating_ips_quota
                FROM metering_quotas
                WHERE project_id = %s
                  AND collected_at >= NOW() - INTERVAL '14 days'
                ORDER BY collected_at ASC
            """, (project_id,))
            rows = cur.fetchall()
        if len(rows) < 7:
            for key in self._QUOTA_RESOURCES:
                self.suppress_resolved(f"{_TYPE_QUOTA}_{key}", "project", project_id)
            return
        t0 = float(rows[0]["ts"])
        xs = [(float(r["ts"]) - t0) / 86400.0 for r in rows]
        fired_any = False
        meta_by_resource: Dict[str, dict] = {}
        for key, (used_col, quota_col, label) in self._QUOTA_RESOURCES.items():
            insight_type = f"{_TYPE_QUOTA}_{key}"
            try:
                ys    = [float(r[used_col] or 0) for r in rows]
                quota = float(rows[-1][quota_col] or 0)
                if quota <= 0:
                    self.suppress_resolved(insight_type, "project", project_id)
                    continue
                used_now    = ys[-1]
                current_pct = used_now / quota * 100
                slope, intercept = _linear_regression(xs, ys)
                r2   = _r_squared(xs, ys, slope, intercept)
                conf = _confidence(len(rows), r2)
                days = _days_to_pct(used_now, quota, slope)
                meta_by_resource[key] = {
                    "used":         used_now,
                    "quota":        quota,
                    "used_pct":     round(current_pct, 1),
                    "days_to_90":   int(days) if days is not None else None,
                    "trend_per_day": round(slope, 3),
                    "confidence":   conf,
                }
                if days is None or days > 30:
                    self.suppress_resolved(insight_type, "project", project_id)
                    continue
                days_int = max(0, int(days))
                severity = _severity_from_days(days)
                fired_any = True
                self.upsert_insight(
                    type=insight_type,
                    severity=severity,
                    entity_type="project",
                    entity_id=project_id,
                    entity_name=project_name,
                    title=f"Quota saturation: {project_name} — {label} reaches 90% in {days_int} day(s)",
                    message=(
                        f"Project {project_name!r} is using {used_now:.0f} of "
                        f"{quota:.0f} {label} ({current_pct:.1f}%). "
                        f"At the current growth rate of {slope:.2f}/day, "
                        f"this quota will reach 90% in approximately {days_int} day(s)."
                    ),
                    metadata={
                        "resource":     label,
                        "used":         used_now,
                        "quota":        quota,
                        "used_pct":     round(current_pct, 1),
                        "days_to_90":   days_int,
                        "trend_per_day": round(slope, 3),
                        "data_points":  len(rows),
                        "confidence":   conf,
                        "r_squared":    round(r2, 3),
                        "project":      project_name,
                    },
                )
            except Exception as exc:
                log.debug("quota forecast for %s/%s failed: %s", project_id, key, exc)
        if not fired_any and not meta_by_resource:
            pass  # nothing to do
    # ------------------------------------------------------------------
    # Compute / hypervisor-level forecast — Phase 3
    # ------------------------------------------------------------------
    def _evaluate_hypervisors(self) -> None:
        """Forecast vCPU and RAM allocation trend per hypervisor."""
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    h.id                                   AS hypervisor_id,
                    h.hostname                             AS hostname,
                    h.region_id,
                    h.vcpus                                AS total_vcpus,
                    h.memory_mb                            AS total_ram_mb,
                    COALESCE(h.running_vms, 0)             AS running_vms,
                    ROUND(
                        COALESCE(
                            (SELECT SUM(f.vcpus)
                             FROM flavors f
                             JOIN servers s ON s.flavor_id = f.id
                                           AND s.hypervisor_id = h.id
                                           AND s.status = 'ACTIVE'), 0
                        )::numeric
                    )                                      AS allocated_vcpus,
                    ROUND(
                        COALESCE(
                            (SELECT SUM(f.ram_mb)
                             FROM flavors f
                             JOIN servers s ON s.flavor_id = f.id
                                           AND s.hypervisor_id = h.id
                                           AND s.status = 'ACTIVE'), 0
                        )::numeric
                    )                                      AS allocated_ram_mb
                FROM hypervisors h
                WHERE h.state = 'up'
            """)
            hosts = cur.fetchall()
        if not hosts:
            return
        log.info("CapacityEngine: evaluating %d hypervisor(s) for compute forecast", len(hosts))
        for host in hosts:
            try:
                self._forecast_hypervisor(dict(host))
            except Exception as exc:
                log.debug("hypervisor forecast error for %s: %s",
                          host.get("hostname"), exc)
    def _forecast_hypervisor(self, host: dict) -> None:
        hv_id      = host["hypervisor_id"]
        hostname   = host["hostname"] or str(hv_id)
        total_vcpu = float(host["total_vcpus"] or 0)
        total_ram  = float(host["total_ram_mb"] or 0)
        alloc_vcpu = float(host["allocated_vcpus"] or 0)
        alloc_ram  = float(host["allocated_ram_mb"] or 0)
        region     = host.get("region_id") or "default"
        if total_vcpu <= 0:
            return
        # Derive utilization from live snapshots in servers_history
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    EXTRACT(EPOCH FROM h.collected_at) AS ts,
                    COUNT(*)                           AS active_vms
                FROM servers_history h
                WHERE h.hypervisor_id = %s
                  AND h.status        = 'ACTIVE'
                  AND h.collected_at >= NOW() - INTERVAL '14 days'
                GROUP BY h.collected_at
                ORDER BY h.collected_at ASC
            """, (str(hv_id),))
            rows = cur.fetchall()
        # Fallback: need at least 5 data points for a meaningful trend
        if len(rows) < 5:
            self.suppress_resolved(_TYPE_COMPUTE, "hypervisor", str(hv_id))
            return
        t0    = float(rows[0]["ts"])
        xs    = [(float(r["ts"]) - t0) / 86400.0 for r in rows]
        ys    = [float(r["active_vms"]) for r in rows]
        slope, intercept = _linear_regression(xs, ys)
        r2    = _r_squared(xs, ys, slope, intercept)
        conf  = _confidence(len(rows), r2)
        # Capacity headroom in VMs (approximation: avg 2 vCPUs per VM)
        avg_vcpus_per_vm = (alloc_vcpu / max(1, rows[-1]["active_vms"]))
        if avg_vcpus_per_vm < 1:
            avg_vcpus_per_vm = 2.0
        headroom_vms     = max(0, (total_vcpu * 0.9 - alloc_vcpu) / avg_vcpus_per_vm)
        headroom_ram_vms = max(0, (total_ram * 0.9 - alloc_ram) / max(
            1, (alloc_ram / max(1, rows[-1]["active_vms"]))))
        # Days to 90% vCPU utilisation (using VM-growth proxy)
        days_vcpu = (headroom_vms / slope) if slope > 0 else None
        days_ram  = (headroom_ram_vms / slope) if slope > 0 else None
        days      = min(
            d for d in [days_vcpu, days_ram] if d is not None
        ) if any(d is not None for d in [days_vcpu, days_ram]) else None
        if days is None or days > 30:
            self.suppress_resolved(_TYPE_COMPUTE, "hypervisor", str(hv_id))
            return
        days_int  = max(0, int(days))
        severity  = _severity_from_days(days)
        vcpu_pct  = round(alloc_vcpu / total_vcpu * 100, 1) if total_vcpu else 0
        ram_pct   = round(alloc_ram / total_ram * 100, 1) if total_ram else 0
        self.upsert_insight(
            type=_TYPE_COMPUTE,
            severity=severity,
            entity_type="hypervisor",
            entity_id=str(hv_id),
            entity_name=hostname,
            title=(
                f"Compute capacity: {hostname} will reach 90% allocation in {days_int} day(s)"
            ),
            message=(
                f"Hypervisor {hostname!r} in region {region!r} is currently at "
                f"{vcpu_pct}% vCPU and {ram_pct}% RAM allocation "
                f"({rows[-1]['active_vms']:.0f} active VMs). "
                f"At the current growth rate of {slope:.2f} VMs/day, "
                f"compute capacity will reach 90% in approximately {days_int} day(s)."
            ),
            metadata={
                "region":           region,
                "total_vcpus":      int(total_vcpu),
                "allocated_vcpus":  int(alloc_vcpu),
                "vcpu_pct":         vcpu_pct,
                "total_ram_mb":     int(total_ram),
                "allocated_ram_mb": int(alloc_ram),
                "ram_pct":          ram_pct,
                "active_vms":       int(rows[-1]["active_vms"]),
                "vm_growth_per_day": round(slope, 3),
                "days_to_90":       days_int,
                "data_points":      len(rows),
                "confidence":       conf,
                "r_squared":        round(r2, 3),
            },
        )
