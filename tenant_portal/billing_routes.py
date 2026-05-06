"""
billing_routes.py — Tenant Portal billing endpoints.

Provides billing-aware metering data and account status for the authenticated tenant.
Integrates with the enhanced billing system while maintaining tenant security scope.

Endpoints:
  GET /tenant/billing/status              — tenant billing account status
  GET /tenant/metering/billing-aware      — enhanced chargeback with billing awareness

TenantContext note: TenantContext carries project_ids (Keystone project UUIDs),
NOT a tenant_id. The billing config is keyed on domain_id (= domains.id UUID).
We derive domain_id by joining project_ids → projects.domain_id at the start of
each endpoint. If no billing config is set up for this tenant's domain we return
a graceful "billing_configured: false" response instead of 404.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from psycopg2.extras import RealDictCursor

from db_pool import get_tenant_connection
from middleware import get_tenant_context, inject_rls_vars
from tenant_context import TenantContext
from audit_helper import log_action_bare

logger = logging.getLogger("tenant_portal.billing")

router = APIRouter(tags=["billing"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_domain_id(cur, project_ids: List[str]) -> Optional[str]:
    """
    Derive the tenant's domain UUID from their Keystone project_ids by
    querying the projects table. Returns None if no domain can be resolved.
    """
    if not project_ids:
        return None
    cur.execute(
        "SELECT domain_id FROM projects WHERE id = ANY(%s) AND domain_id IS NOT NULL LIMIT 1",
        (project_ids,),
    )
    row = cur.fetchone()
    return row["domain_id"] if row else None


# ---------------------------------------------------------------------------
# Billing Status Endpoint
# ---------------------------------------------------------------------------

@router.get("/tenant/billing/status")
async def get_tenant_billing_status(
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get the authenticated tenant's billing configuration and account status.
    Returns billing model, currency, balance (if prepaid), and other billing details.
    Returns billing_configured=false when no config has been set up yet.
    """
    log_action_bare(tenant_ctx, "billing_status_view", details={
        "control_plane_id": tenant_ctx.control_plane_id,
    })

    with get_tenant_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        inject_rls_vars(cur, tenant_ctx)

        domain_id = _resolve_domain_id(cur, tenant_ctx.project_ids)
        if not domain_id:
            return {"billing_configured": False, "message": "No billing domain found"}

        # Get billing configuration
        cur.execute("""
            SELECT
                tenant_id,
                billing_model,
                currency_code,
                onboarding_date,
                billing_start_date,
                billing_cycle_day,
                sales_person_id,
                created_at,
                updated_at
            FROM tenant_billing_config
            WHERE tenant_id = %s
        """, (domain_id,))

        billing_config = cur.fetchone()
        if not billing_config:
            return {"billing_configured": False, "message": "Billing not yet configured for this tenant"}

        # Return sales_person_id directly (users.name stores email in K8s, not display name)
        sales_person_name = billing_config["sales_person_id"] or None

        result = {
            "billing_configured": True,
            "tenant_id": str(billing_config["tenant_id"]),
            "billing_model": billing_config["billing_model"],
            "currency_code": billing_config["currency_code"],
            "onboarding_date": billing_config["onboarding_date"].isoformat(),
            "billing_start_date": billing_config["billing_start_date"].isoformat() if billing_config["billing_start_date"] else None,
            "billing_cycle_day": billing_config["billing_cycle_day"],
            "sales_person": sales_person_name,
        }

        # For prepaid accounts, get account balance and billing dates
        if billing_config["billing_model"] == "prepaid":
            cur.execute("""
                SELECT
                    current_balance,
                    last_charge_date,
                    next_billing_date,
                    currency_code AS account_currency,
                    quota_enforcement
                FROM prepaid_accounts
                WHERE tenant_id = %s
            """, (domain_id,))

            prepaid_account = cur.fetchone()
            if prepaid_account:
                result.update({
                    "current_balance": float(prepaid_account["current_balance"]),
                    "last_charge_date": prepaid_account["last_charge_date"].isoformat() if prepaid_account["last_charge_date"] else None,
                    "next_billing_date": prepaid_account["next_billing_date"].isoformat() if prepaid_account["next_billing_date"] else None,
                    "quota_enforcement": prepaid_account["quota_enforcement"],
                })

                balance = float(prepaid_account["current_balance"])
                if balance <= 0:
                    result["status_message"] = "Account balance depleted"
                elif balance < 100:
                    result["status_message"] = "Low balance warning"
                else:
                    result["status_message"] = "Account in good standing"
            else:
                result["status_message"] = "Prepaid account not initialized"
        else:
            result["status_message"] = "Pay-as-you-go billing active"

        return result


# ---------------------------------------------------------------------------
# Billing-Aware Chargeback Endpoint
# ---------------------------------------------------------------------------

@router.get("/tenant/metering/billing-aware")
async def get_billing_aware_chargeback(
    hours: int = Query(default=720, ge=1, le=8760, description="Time period in hours"),
    currency: Optional[str] = Query(default=None, description="Currency override"),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get billing-aware chargeback data that adapts display and calculations
    based on the tenant's billing model (prepaid vs pay-as-you-go).
    Returns basic usage data with billing_configured=false when no config exists.
    """
    log_action_bare(tenant_ctx, "billing_aware_chargeback", details={
        "control_plane_id": tenant_ctx.control_plane_id,
        "hours": hours,
        "currency": currency,
    })

    with get_tenant_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        inject_rls_vars(cur, tenant_ctx)

        domain_id = _resolve_domain_id(cur, tenant_ctx.project_ids)
        effective_currency = currency or "USD"

        billing_config = None
        if domain_id:
            cur.execute("""
                SELECT billing_model, currency_code, sales_person_id,
                       onboarding_date, billing_start_date, billing_cycle_day
                FROM tenant_billing_config
                WHERE tenant_id = %s
            """, (domain_id,))
            billing_config = cur.fetchone()
            if billing_config:
                effective_currency = currency or billing_config["currency_code"]

        chargeback_data = await _get_chargeback_data(cur, tenant_ctx, hours, effective_currency)

        # If no billing config, return base usage data with a not-configured flag
        if not billing_config:
            return {
                **chargeback_data,
                "billing_configured": False,
                "billing_explanation": (
                    "Billing has not been configured for your account yet. "
                    "Contact your administrator to set up billing."
                ),
                "billing_status": None,
                "cost_projection": {"monthly_estimate": 0.0},
            }

        billing_model = billing_config["billing_model"]
        billing_status_data = await _get_billing_status_data(cur, domain_id, billing_config)

        monthly_hours = 24 * 30
        monthly_estimate = (chargeback_data["total_estimated_cost"] / hours) * monthly_hours

        if billing_model == "prepaid":
            billing_explanation = (
                "Your account uses prepaid billing. Monthly charges are applied regardless of "
                "VM power state. The costs shown here represent your allocated resources for "
                "the selected period, with compute costs charged at full monthly rate even "
                "when VMs are powered off."
            )
        else:
            billing_explanation = (
                "Your account uses pay-as-you-go billing. You are charged only for actual "
                "resource usage. Compute costs are based on VM power state, while storage, "
                "network, and snapshot costs accrue continuously while resources exist."
            )

        result = {
            **chargeback_data,
            "billing_configured": True,
            "billing_status": billing_status_data,
            "billing_explanation": billing_explanation,
            "cost_projection": {"monthly_estimate": monthly_estimate},
        }

        if billing_model == "prepaid" and billing_status_data.get("next_billing_date"):
            try:
                next_bill_date = datetime.fromisoformat(
                    billing_status_data["next_billing_date"].replace("Z", "+00:00")
                )
                days_until_bill = (next_bill_date - datetime.now(timezone.utc)).days
                result["cost_projection"]["days_until_next_bill"] = max(0, days_until_bill)
                result["cost_projection"]["next_bill_amount"] = monthly_estimate
            except (ValueError, TypeError):
                pass

        return result


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

async def _get_chargeback_data(cur, tenant_ctx: TenantContext, hours: int, currency: str) -> Dict[str, Any]:
    """Return chargeback data scoped to this tenant's domain, with real cost calculations."""
    period_labels = {
        24: "Last 24 hours",
        168: "Last 7 days",
        720: "Last 30 days",
        2160: "Last 90 days",
    }

    base = {
        "currency": currency,
        "period_hours": hours,
        "period_label": period_labels.get(hours, f"Last {hours} hours (prorated)"),
        "vms": [],
        "total_estimated_cost": 0.0,
        "total_vms": 0,
        "cost_breakdown": {"compute": 0.0, "storage": 0.0, "snapshots": 0.0, "network": 0.0},
        "disclaimer": "Billing-aware calculations based on your account's billing model",
        "pricing_basis_note": "Regional pricing and billing model adjustments applied",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Resolve domain name from project_ids (metering_resources uses text domain name)
    if not tenant_ctx.project_ids:
        return base
    cur.execute(
        """SELECT d.name FROM domains d
           JOIN projects p ON p.domain_id = d.id
           WHERE p.id = ANY(%s) AND d.name IS NOT NULL LIMIT 1""",
        (tenant_ctx.project_ids,),
    )
    row = cur.fetchone()
    if not row:
        return base
    domain_name = row["name"]

    # Load flavor pricing
    cur.execute(
        "SELECT item_name, cost_per_hour, cost_per_month FROM metering_pricing WHERE category = 'flavor'"
    )
    flavor_pricing: Dict[str, Dict] = {
        r["item_name"]: {
            "cost_per_hour": float(r["cost_per_hour"] or 0),
            "cost_per_month": float(r["cost_per_month"] or 0),
        }
        for r in cur.fetchall()
    }

    # Load per-resource pricing (storage, snapshot, network, IP) — keyed by category
    cur.execute(
        "SELECT category, cost_per_hour, cost_per_month FROM metering_pricing"
        " WHERE category IN ('storage_gb','snapshot_gb','network','public_ip')"
    )
    cat_pricing: Dict[str, Dict] = {
        r["category"]: {
            "cost_per_hour": float(r["cost_per_hour"] or 0),
            "cost_per_month": float(r["cost_per_month"] or 0),
        }
        for r in cur.fetchall()
    }

    def _hourly(cat: str) -> float:
        e = cat_pricing.get(cat)
        if not e:
            return 0.0
        if e["cost_per_hour"] > 0:
            return e["cost_per_hour"]
        return e["cost_per_month"] / 730.0 if e["cost_per_month"] > 0 else 0.0

    storage_per_gb_hr = _hourly("storage_gb")
    snapshot_per_gb_hr = _hourly("snapshot_gb")
    network_per_hr = _hourly("network")    # per VM (1 network port per VM)

    # Latest per-VM metrics in the requested window
    cur.execute(
        """SELECT DISTINCT ON (vm_id)
               vm_id, vm_name, project_name, flavor,
               vcpus_allocated, ram_allocated_mb, disk_allocated_gb, vm_ip, collected_at
           FROM metering_resources
           WHERE domain = %s AND collected_at > NOW() - (%s || ' hours')::INTERVAL
           ORDER BY vm_id, collected_at DESC""",
        (domain_name, str(hours)),
    )
    vm_rows = cur.fetchall()

    # Metered hours per VM: count of collected snapshots = hours the VM was metered/running
    cur.execute(
        """SELECT vm_id, COUNT(*) AS metered_hours,
                  MIN(collected_at) AS first_seen, MAX(collected_at) AS last_seen
           FROM metering_resources
           WHERE domain = %s AND collected_at > NOW() - (%s || ' hours')::INTERVAL
           GROUP BY vm_id""",
        (domain_name, str(hours)),
    )
    vm_metered: Dict[str, Any] = {
        r["vm_id"]: {
            "metered_hours": int(r["metered_hours"]),
            "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
            "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
        }
        for r in cur.fetchall()
    }

    # Latest snapshot totals for this domain
    cur.execute(
        """SELECT COALESCE(SUM(size_gb), 0) AS total_snap_gb, COUNT(*) AS snap_count
           FROM (
               SELECT DISTINCT ON (snapshot_id) size_gb
               FROM metering_snapshots
               WHERE domain = %s AND collected_at > NOW() - (%s || ' hours')::INTERVAL
               ORDER BY snapshot_id, collected_at DESC
           ) s""",
        (domain_name, str(hours)),
    )
    snap_row = cur.fetchone()
    total_snap_gb = float(snap_row["total_snap_gb"] or 0) if snap_row else 0.0
    snap_count = int(snap_row["snap_count"] or 0) if snap_row else 0

    vms_out = []
    total_compute = 0.0
    total_storage = 0.0
    total_network = 0.0
    total_snap = total_snap_gb * snapshot_per_gb_hr * hours

    for vm in vm_rows:
        flavor = vm["flavor"] or ""
        vcpus = int(vm["vcpus_allocated"] or 0)
        ram_gb = float(vm["ram_allocated_mb"] or 0) / 1024.0
        disk_gb = float(vm["disk_allocated_gb"] or 0)

        fp = flavor_pricing.get(flavor)
        if fp:
            hr = fp["cost_per_hour"] if fp["cost_per_hour"] > 0 else fp["cost_per_month"] / 730.0
            compute_cost = hr * hours
            pricing_basis = f"flavor:{flavor}"
        else:
            compute_cost = 0.0
            pricing_basis = "no_pricing_configured"

        storage_cost = disk_gb * storage_per_gb_hr * hours
        snap_cost_vm = 0.0  # snapshots shown as domain total, not per-VM
        network_cost = network_per_hr * hours  # 1 network port per VM

        vm_total = compute_cost + storage_cost + network_cost

        mh_data = vm_metered.get(vm["vm_id"], {})
        metered_h = mh_data.get("metered_hours", 0)
        vms_out.append({
            "vm_id": vm["vm_id"],
            "vm_name": vm["vm_name"] or vm["vm_id"],
            "project_name": vm["project_name"] or domain_name,
            "vcpus": vcpus,
            "ram_gb": round(ram_gb, 2),
            "disk_gb": round(disk_gb, 2),
            "flavor": flavor,
            "cost_per_hour": round(hr if fp else 0.0, 6),
            "compute_cost": round(compute_cost, 4),
            "storage_cost": round(storage_cost, 4),
            "snapshot_cost": round(snap_cost_vm, 4),
            "snapshot_gb": 0.0,
            "snapshot_count": 0,
            "network_cost": round(network_cost, 4),
            "estimated_cost": round(vm_total, 4),
            "pricing_basis": pricing_basis,
            "last_metering": vm["collected_at"].isoformat() if vm["collected_at"] else None,
            "metered_hours": metered_h,
            "down_hours": max(0, hours - metered_h),
            "first_seen": mh_data.get("first_seen"),
            "last_seen": mh_data.get("last_seen"),
        })
        total_compute += compute_cost
        total_storage += storage_cost
        total_network += network_cost

    total_cost = total_compute + total_storage + total_snap + total_network

    base["vms"] = vms_out
    base["total_vms"] = len(vms_out)
    base["total_estimated_cost"] = round(total_cost, 4)
    base["cost_breakdown"] = {
        "compute": round(total_compute, 4),
        "storage": round(total_storage, 4),
        "snapshots": round(total_snap, 4),
        "network": round(total_network, 4),
    }
    return base


async def _get_billing_status_data(cur, domain_id: str, billing_config) -> Dict[str, Any]:
    """Return billing status data for inclusion in the billing-aware response."""
    result: Dict[str, Any] = {
        "tenant_id": domain_id,
        "billing_model": billing_config["billing_model"],
        "currency_code": billing_config["currency_code"],
        "onboarding_date": billing_config["onboarding_date"].isoformat() if billing_config.get("onboarding_date") else None,
        "billing_start_date": billing_config["billing_start_date"].isoformat() if billing_config.get("billing_start_date") else None,
        "billing_cycle_day": billing_config.get("billing_cycle_day"),
        "sales_person": billing_config.get("sales_person_id") or None,
    }

    if billing_config["billing_model"] == "prepaid":
        cur.execute("""
            SELECT current_balance, last_charge_date, next_billing_date, quota_enforcement
            FROM prepaid_accounts
            WHERE tenant_id = %s
        """, (domain_id,))
        prepaid = cur.fetchone()
        if prepaid:
            result["current_balance"] = float(prepaid["current_balance"])
            result["quota_enforcement"] = prepaid["quota_enforcement"]
            result["last_charge_date"] = prepaid["last_charge_date"].isoformat() if prepaid["last_charge_date"] else None
            result["next_billing_date"] = prepaid["next_billing_date"].isoformat() if prepaid["next_billing_date"] else None

    return result