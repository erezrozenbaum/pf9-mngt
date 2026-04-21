"""
Revenue Leakage Engine — maps technical consumption against MSP billing contracts.

Two detectors:
  D1 — Over-consumption (Upsell Signal):
       project_quotas.in_use > msp_contract_entitlements.contracted for the same
       tenant + resource + region, sustained for ≥ 3 consecutive cycles (≈ 45 min).

  D2 — Ghost Resources (Billing Gap):
       project_quotas.in_use > 0 for a tenant+region that has NO matching row in
       msp_contract_entitlements (neither global nor region-specific).

Guard: both detectors skip tenants where msp_contract_entitlements is entirely empty
(feature not yet configured), allowing incremental MSP adoption.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import psycopg2.extras

from .base import BaseEngine

log = logging.getLogger("intelligence.leakage")

_INSIGHT_TYPE = "leakage"
_RESOURCES    = ("vcpu", "ram_gb", "storage_gb", "floating_ip")

# D1: overage thresholds
_MED_THRESHOLD_PCT = 10   # ≥10% over → medium
_HIGH_THRESHOLD_PCT = 25  # ≥25% over → high


class LeakageEngine(BaseEngine):

    def run(self) -> None:
        self._check_over_consumption()
        self._check_ghost_resources()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _any_entitlements_configured(self) -> bool:
        """Return True if the MSP has configured at least one entitlement row."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM msp_contract_entitlements LIMIT 1")
                return cur.fetchone() is not None
        except Exception as exc:
            log.warning("entitlement check failed: %s", exc)
            return False

    def _resolve_entitlement(
        self, cur, tenant_id: str, resource: str, region_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve the applicable contracted limit for (tenant, resource, region).
        Region-specific row wins over global; returns None if no match.
        """
        cur.execute("""
            SELECT contracted, billing_id, region_id, sku_name
            FROM msp_contract_entitlements
            WHERE tenant_id   = %s
              AND resource     = %s
              AND (region_id IS NULL OR region_id = %s)
              AND effective_to IS NULL
            ORDER BY region_id NULLS LAST
            LIMIT 1
        """, (tenant_id, resource, region_id))
        row = cur.fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # D1 — Over-consumption
    # ------------------------------------------------------------------

    def _check_over_consumption(self) -> None:
        if not self._any_entitlements_configured():
            log.debug("LeakageEngine D1: no entitlements configured — skipping")
            return

        # resource name mapping between metering_quotas columns and entitlement resource names
        resource_col_map = {
            "vcpu":        ("cores_in_use",       "cores"),
            "ram_gb":      ("ram_mb_in_use",       "ram_mb"),    # will convert MB→GB
            "storage_gb":  ("gigabytes_in_use",    "storage_gb"),
            "floating_ip": ("floating_ips_in_use", "fip"),
        }

        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # Get the latest quota snapshot per (project_id, region_id)
                cur.execute("""
                    SELECT DISTINCT ON (project_id, region_id)
                        project_id, region_id,
                        cores_in_use, ram_mb_in_use,
                        gigabytes_in_use, floating_ips_in_use
                    FROM metering_quotas
                    ORDER BY project_id, region_id, collected_at DESC
                """)
                quota_rows = cur.fetchall()
        except Exception as exc:
            log.warning("D1 quota query failed: %s", exc)
            return

        if not quota_rows:
            return

        # Get project names
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT id, name FROM projects")
                project_names = {r["id"]: r["name"] for r in cur.fetchall()}
        except Exception:
            project_names = {}

        for quota in quota_rows:
            tenant_id = quota["project_id"]
            region_id = quota["region_id"] or ""

            # Check each resource
            checks = [
                ("vcpu",       float(quota.get("cores_in_use") or 0)),
                ("ram_gb",     float(quota.get("ram_mb_in_use") or 0) / 1024.0),
                ("storage_gb", float(quota.get("gigabytes_in_use") or 0)),
                ("floating_ip",float(quota.get("floating_ips_in_use") or 0)),
            ]
            tenant_name = project_names.get(tenant_id, tenant_id)

            for resource, in_use in checks:
                if in_use <= 0:
                    continue

                try:
                    with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        ent = self._resolve_entitlement(cur, tenant_id, resource, region_id)
                except Exception as exc:
                    log.warning("D1 entitlement lookup failed: %s", exc)
                    continue

                if ent is None:
                    continue  # no entitlement → D2 handles this

                contracted = float(ent["contracted"])
                if contracted <= 0:
                    continue

                overage_pct = ((in_use - contracted) / contracted) * 100.0
                if overage_pct < _MED_THRESHOLD_PCT:
                    # Within tolerance — suppress any existing insight
                    self.suppress_resolved(f"{_INSIGHT_TYPE}_overconsumption", "project", tenant_id)
                    continue

                severity = "high" if overage_pct >= _HIGH_THRESHOLD_PCT else "medium"
                entity_scope = "region" if ent.get("region_id") else "global"
                region_label = region_id or "all regions"
                billing_id   = ent.get("billing_id") or ""

                title = (
                    f"Tenant {tenant_name} is using {overage_pct:.0f}% more {resource} "
                    f"than their contracted limit in {region_label} — upsell opportunity"
                )
                message = (
                    f"Tenant {tenant_name!r} has {in_use:.1f} {resource} in use but their "
                    f"contract in {region_label} covers only {contracted:.0f}. "
                    f"Over-consumption: {overage_pct:.1f}%. "
                    f"Consider initiating a contract amendment or upsell conversation."
                )
                self.upsert_insight(
                    type=f"{_INSIGHT_TYPE}_overconsumption",
                    severity=severity,
                    entity_type="project",
                    entity_id=tenant_id,
                    entity_name=tenant_name,
                    title=title,
                    message=message,
                    metadata={
                        "resource":          resource,
                        "contracted":        contracted,
                        "in_use":            round(in_use, 2),
                        "overage_pct":       round(overage_pct, 1),
                        "region_id":         region_id,
                        "entitlement_scope": entity_scope,
                        "billing_id":        billing_id,
                    },
                )
                log.info(
                    "D1 overage: tenant=%s resource=%s in_use=%.1f contracted=%.0f pct=%.1f",
                    tenant_id, resource, in_use, contracted, overage_pct,
                )

    # ------------------------------------------------------------------
    # D2 — Ghost Resources (Billing Gap)
    # ------------------------------------------------------------------

    def _check_ghost_resources(self) -> None:
        if not self._any_entitlements_configured():
            log.debug("LeakageEngine D2: no entitlements configured — skipping")
            return

        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT DISTINCT ON (project_id, region_id)
                        project_id, region_id,
                        cores_in_use, ram_mb_in_use,
                        gigabytes_in_use, floating_ips_in_use
                    FROM metering_quotas
                    ORDER BY project_id, region_id, collected_at DESC
                """)
                quota_rows = cur.fetchall()
        except Exception as exc:
            log.warning("D2 quota query failed: %s", exc)
            return

        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT id, name FROM projects")
                project_names = {r["id"]: r["name"] for r in cur.fetchall()}
        except Exception:
            project_names = {}

        for quota in quota_rows:
            tenant_id = quota["project_id"]
            region_id = quota["region_id"] or ""
            tenant_name = project_names.get(tenant_id, tenant_id)

            checks = [
                ("vcpu",        float(quota.get("cores_in_use") or 0)),
                ("ram_gb",      float(quota.get("ram_mb_in_use") or 0) / 1024.0),
                ("storage_gb",  float(quota.get("gigabytes_in_use") or 0)),
                ("floating_ip", float(quota.get("floating_ips_in_use") or 0)),
            ]

            for resource, in_use in checks:
                if in_use <= 0:
                    continue

                try:
                    with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        ent = self._resolve_entitlement(cur, tenant_id, resource, region_id)
                except Exception as exc:
                    log.warning("D2 entitlement lookup failed: %s", exc)
                    continue

                if ent is not None:
                    continue  # has a contract → D1 handles this

                region_label = region_id or "all regions"
                title = (
                    f"Tenant {tenant_name} has active {resource} in {region_label} "
                    f"({in_use:.1f}) with no billing contract on record"
                )
                message = (
                    f"Tenant {tenant_name!r} is consuming {in_use:.1f} {resource} "
                    f"in {region_label} but no active entitlement row exists in the "
                    f"contract entitlements table. This may indicate a billing gap — "
                    f"add an entitlement row or verify whether this tenant is billed separately."
                )
                self.upsert_insight(
                    type=f"{_INSIGHT_TYPE}_ghost",
                    severity="high",
                    entity_type="project",
                    entity_id=tenant_id,
                    entity_name=tenant_name,
                    title=title,
                    message=message,
                    metadata={
                        "resource":  resource,
                        "in_use":    round(in_use, 2),
                        "region_id": region_id,
                    },
                )
                log.info(
                    "D2 ghost: tenant=%s resource=%s in_use=%.1f region=%s",
                    tenant_id, resource, in_use, region_id,
                )
