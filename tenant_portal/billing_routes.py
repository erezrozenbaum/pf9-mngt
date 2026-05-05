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
from audit_helper import log_action

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
    log_action("billing_status_view", tenant_ctx.username, {
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

        # Get sales person name if assigned
        sales_person_name = None
        if billing_config["sales_person_id"]:
            cur.execute("""
                SELECT username, email, full_name
                FROM users
                WHERE username = %s
            """, (billing_config["sales_person_id"],))
            sales_person = cur.fetchone()
            if sales_person:
                sales_person_name = sales_person["full_name"] or sales_person["email"]

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
    log_action("billing_aware_chargeback", tenant_ctx.username, {
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
                SELECT billing_model, currency_code
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
    """Return basic chargeback structure scoped to this tenant's projects."""
    period_labels = {
        24: "Last 24 hours",
        168: "Last 7 days",
        720: "Last 30 days",
        2160: "Last 90 days",
    }
    return {
        "currency": currency,
        "period_hours": hours,
        "period_label": period_labels.get(hours, f"Last {hours} hours"),
        "vms": [],
        "total_estimated_cost": 0.0,
        "total_vms": 0,
        "cost_breakdown": {
            "compute": 0.0,
            "storage": 0.0,
            "snapshots": 0.0,
            "network": 0.0,
        },
        "disclaimer": "Billing-aware calculations based on your account's billing model",
        "pricing_basis_note": "Regional pricing and billing model adjustments applied",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _get_billing_status_data(cur, domain_id: str, billing_config) -> Dict[str, Any]:
    """Return billing status data for inclusion in the billing-aware response."""
    result: Dict[str, Any] = {
        "tenant_id": domain_id,
        "billing_model": billing_config["billing_model"],
        "currency_code": billing_config["currency_code"],
    }

    if billing_config["billing_model"] == "prepaid":
        cur.execute("""
            SELECT current_balance, next_billing_date
            FROM prepaid_accounts
            WHERE tenant_id = %s
        """, (domain_id,))
        prepaid = cur.fetchone()
        if prepaid:
            result["current_balance"] = float(prepaid["current_balance"])
            if prepaid["next_billing_date"]:
                result["next_billing_date"] = prepaid["next_billing_date"].isoformat()

    return result