"""
Billing API Routes
==================
Enhanced billing endpoints for v1.95 metering system:
- Tenant billing configuration (prepaid vs pay-as-you-go)
- Prepaid account management with quota enforcement
- Regional pricing overrides
- Webhook integrations for external systems
- Resource lifecycle event tracking
- Billing-aware metering calculations

RBAC
----
  - admin      → billing:read  (view billing data, export reports)
  - superadmin → billing:read + billing:write (configure billing, manage accounts)
  - tenant     → billing:read (own tenant billing data only)
"""

from __future__ import annotations

import csv
import io
import logging
import json
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status, Body
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from psycopg2.extras import RealDictCursor
import psycopg2

from auth import require_permission, get_current_user, User, get_effective_region_filter
from db_pool import get_connection

logger = logging.getLogger("pf9.billing")
router = APIRouter(prefix="/api/billing", tags=["billing"])

# ===============================================================================
# Pydantic Models
# ===============================================================================

class BillingModel(str, Enum):
    PREPAID = "prepaid"
    PAY_AS_YOU_GO = "pay_as_you_go"

class TenantBillingConfigRequest(BaseModel):
    """Request model for tenant billing configuration."""
    billing_model: BillingModel
    currency_code: str = Field(default="USD", min_length=3, max_length=3)
    onboarding_date: datetime
    billing_start_date: Optional[datetime] = None
    sales_person_id: Optional[str] = None
    
    @field_validator('currency_code')
    @classmethod
    def validate_currency(cls, v: str) -> str:
        # Basic currency validation - extend with full currency list as needed
        valid_currencies = {'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD', 'CHF', 'CNY', 'INR'}
        if v.upper() not in valid_currencies:
            raise ValueError(f'Unsupported currency code: {v}')
        return v.upper()

class TenantBillingConfigResponse(BaseModel):
    """Response model for tenant billing configuration."""
    tenant_id: str
    billing_model: BillingModel
    currency_code: str
    onboarding_date: datetime
    billing_start_date: Optional[datetime]
    billing_cycle_day: int
    sales_person_id: Optional[str]
    sales_person_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class PrepaidAccountRequest(BaseModel):
    """Request model for prepaid account operations."""
    tenant_id: str
    balance_adjustment: Decimal = Field(..., description="Positive to add funds, negative to deduct")
    currency_code: str = Field(default="USD", min_length=3, max_length=3)
    quota_enforcement: bool = True
    notes: Optional[str] = None

class PrepaidAccountResponse(BaseModel):
    """Response model for prepaid account status."""
    tenant_id: str
    current_balance: Decimal
    last_charge_date: Optional[datetime]
    next_billing_date: Optional[datetime]
    currency_code: str
    quota_enforcement: bool
    status: str  # "active", "suspended", "low_balance"
    created_at: datetime
    updated_at: datetime

class RegionalPricingRequest(BaseModel):
    """Request model for regional pricing overrides."""
    tenant_id: str
    region: str
    resource_category: str  # "compute", "storage", "network", "snapshot"
    pricing_multiplier: Decimal = Field(..., gt=0, description="Multiplier applied to base pricing")
    effective_date: datetime
    expiry_date: Optional[datetime] = None
    
class RegionalPricingResponse(BaseModel):
    """Response model for regional pricing overrides."""
    id: int
    tenant_id: str
    region: str
    resource_category: str
    pricing_multiplier: Decimal
    effective_date: datetime
    expiry_date: Optional[datetime]
    created_at: datetime

class WebhookRegistrationRequest(BaseModel):
    """Request model for webhook registrations."""
    tenant_id: str
    webhook_url: str = Field(..., pattern=r"^https?://.*")
    event_types: List[str] = Field(..., description="billing_threshold, quota_exceeded, payment_due, etc.")
    secret_token: Optional[str] = None
    is_active: bool = True

class WebhookRegistrationResponse(BaseModel):
    """Response model for webhook registrations."""
    id: int
    tenant_id: str
    webhook_url: str
    event_types: List[str]
    is_active: bool
    last_success: Optional[datetime]
    failure_count: int
    created_at: datetime
    updated_at: datetime

class BillingAwareMeteringResponse(BaseModel):
    """Enhanced metering response with billing context."""
    tenant_id: str
    billing_model: BillingModel
    period_start: datetime
    period_end: datetime
    currency_code: str
    
    # Resource costs with regional adjustments
    compute_cost: Decimal
    storage_cost: Decimal
    network_cost: Decimal
    snapshot_cost: Decimal
    total_cost: Decimal
    
    # Billing-specific fields
    regional_adjustments: Dict[str, Decimal] = Field(default_factory=dict)
    prepaid_balance: Optional[Decimal] = None
    quota_status: Optional[str] = None
    next_billing_date: Optional[datetime] = None
    billing_alerts: List[str] = Field(default_factory=list)

# ===============================================================================
# Helper Functions
# ===============================================================================

async def get_tenant_billing_config(tenant_id: str, conn) -> Optional[Dict[str, Any]]:
    """Fetch tenant billing configuration."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT tbc.*, u.name as sales_person_name
        FROM tenant_billing_config tbc
        LEFT JOIN users u ON tbc.sales_person_id = u.id
        WHERE tbc.tenant_id = %s
    """, (tenant_id,))
    result = cursor.fetchone()
    cursor.close()
    return dict(result) if result else None

async def get_prepaid_account_status(tenant_id: str, conn) -> Optional[Dict[str, Any]]:
    """Fetch prepaid account status with calculated status."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT *,
            CASE 
                WHEN current_balance <= 0 AND quota_enforcement THEN 'suspended'
                WHEN current_balance <= 100 THEN 'low_balance'
                ELSE 'active'
            END as status
        FROM prepaid_accounts
        WHERE tenant_id = %s
    """, (tenant_id,))
    result = cursor.fetchone()
    cursor.close()
    return dict(result) if result else None

async def calculate_billing_aware_costs(
    tenant_id: str,
    period_start: datetime,
    period_end: datetime,
    conn
) -> Dict[str, Any]:
    """Calculate costs with regional pricing adjustments."""
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get base costs from existing metering
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN resource_type = 'compute' THEN cost_usd ELSE 0 END) as base_compute_cost,
            SUM(CASE WHEN resource_type = 'storage' THEN cost_usd ELSE 0 END) as base_storage_cost,
            SUM(CASE WHEN resource_type = 'network' THEN cost_usd ELSE 0 END) as base_network_cost,
            SUM(CASE WHEN resource_type = 'snapshot' THEN cost_usd ELSE 0 END) as base_snapshot_cost
        FROM resource_metering
        WHERE domain_id = %s 
            AND metered_at BETWEEN %s AND %s
    """, (tenant_id, period_start, period_end))
    
    base_costs = cursor.fetchone() or {}
    
    # Get regional pricing multipliers
    cursor.execute("""
        SELECT region, resource_category, pricing_multiplier
        FROM regional_pricing_overrides
        WHERE tenant_id = %s
            AND effective_date <= %s
            AND (expiry_date IS NULL OR expiry_date > %s)
    """, (tenant_id, period_end, period_start))
    
    regional_multipliers = cursor.fetchall()
    cursor.close()
    
    # Apply regional adjustments
    costs = {
        'compute_cost': Decimal(str(base_costs.get('base_compute_cost', 0))),
        'storage_cost': Decimal(str(base_costs.get('base_storage_cost', 0))),
        'network_cost': Decimal(str(base_costs.get('base_network_cost', 0))),
        'snapshot_cost': Decimal(str(base_costs.get('base_snapshot_cost', 0)))
    }
    
    regional_adjustments = {}
    
    for multiplier_data in regional_multipliers:
        region = multiplier_data['region']
        category = multiplier_data['resource_category']
        multiplier = Decimal(str(multiplier_data['pricing_multiplier']))
        
        if category in ['compute', 'storage', 'network', 'snapshot']:
            cost_key = f"{category}_cost"
            adjustment = costs[cost_key] * (multiplier - 1)  # Additional cost from multiplier
            costs[cost_key] *= multiplier
            
            if region not in regional_adjustments:
                regional_adjustments[region] = Decimal('0')
            regional_adjustments[region] += adjustment
    
    costs['total_cost'] = sum(costs.values())
    costs['regional_adjustments'] = regional_adjustments
    
    return costs

# ===============================================================================
# API Endpoints
# ===============================================================================

@router.get("/config/{tenant_id}", response_model=TenantBillingConfigResponse)
async def get_tenant_billing_config_endpoint(
    tenant_id: str,
    user: User = Depends(require_permission("billing", "read"))
):
    """Get billing configuration for a specific tenant."""
    async with get_connection() as conn:
        config = await get_tenant_billing_config(tenant_id, conn)
        
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Billing configuration not found for tenant {tenant_id}"
            )
        
        return TenantBillingConfigResponse(**config)

@router.post("/config", response_model=TenantBillingConfigResponse)
async def create_tenant_billing_config(
    config_request: TenantBillingConfigRequest,
    tenant_id: str = Query(..., description="Target tenant ID"),
    user: User = Depends(require_permission("billing", "write"))
):
    """Create or update billing configuration for a tenant."""
    async with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Check if tenant exists
            cursor.execute("SELECT id FROM domains WHERE id = %s", (tenant_id,))
            if not cursor.fetchone():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Tenant {tenant_id} not found"
                )
            
            # Insert or update billing configuration
            cursor.execute("""
                INSERT INTO tenant_billing_config 
                (tenant_id, billing_model, currency_code, onboarding_date, billing_start_date, sales_person_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id) 
                DO UPDATE SET 
                    billing_model = EXCLUDED.billing_model,
                    currency_code = EXCLUDED.currency_code,
                    onboarding_date = EXCLUDED.onboarding_date,
                    billing_start_date = EXCLUDED.billing_start_date,
                    sales_person_id = EXCLUDED.sales_person_id,
                    updated_at = NOW()
                RETURNING *
            """, (
                tenant_id,
                config_request.billing_model.value,
                config_request.currency_code,
                config_request.onboarding_date,
                config_request.billing_start_date,
                config_request.sales_person_id
            ))
            
            result = cursor.fetchone()
            
            # Create prepaid account if billing model is prepaid
            if config_request.billing_model == BillingModel.PREPAID:
                cursor.execute("""
                    INSERT INTO prepaid_accounts (tenant_id, currency_code)
                    VALUES (%s, %s)
                    ON CONFLICT (tenant_id) DO NOTHING
                """, (tenant_id, config_request.currency_code))
            
            conn.commit()
            
            # Fetch complete configuration with sales person name
            config = await get_tenant_billing_config(tenant_id, conn)
            return TenantBillingConfigResponse(**config)
            
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"Database error creating billing config: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create billing configuration"
            )
        finally:
            cursor.close()

@router.get("/prepaid/{tenant_id}", response_model=PrepaidAccountResponse)
async def get_prepaid_account(
    tenant_id: str,
    user: User = Depends(require_permission("billing", "read"))
):
    """Get prepaid account status for a tenant."""
    async with get_connection() as conn:
        account = await get_prepaid_account_status(tenant_id, conn)
        
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Prepaid account not found for tenant {tenant_id}"
            )
        
        return PrepaidAccountResponse(**account)

@router.post("/prepaid/adjust", response_model=PrepaidAccountResponse)
async def adjust_prepaid_balance(
    adjustment: PrepaidAccountRequest,
    user: User = Depends(require_permission("billing", "write"))
):
    """Adjust prepaid account balance (add funds or charge usage)."""
    async with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            # Update prepaid account balance
            cursor.execute("""
                UPDATE prepaid_accounts 
                SET 
                    current_balance = current_balance + %s,
                    last_charge_date = CASE WHEN %s < 0 THEN NOW() ELSE last_charge_date END,
                    updated_at = NOW()
                WHERE tenant_id = %s
                RETURNING *
            """, (adjustment.balance_adjustment, adjustment.balance_adjustment, adjustment.tenant_id))
            
            result = cursor.fetchone()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Prepaid account not found for tenant {adjustment.tenant_id}"
                )
            
            # Log the balance adjustment
            cursor.execute("""
                INSERT INTO resource_lifecycle_events (tenant_id, event_type, resource_type, metadata)
                VALUES (%s, 'balance_adjustment', 'prepaid_account', %s)
            """, (
                adjustment.tenant_id,
                json.dumps({
                    "adjustment_amount": float(adjustment.balance_adjustment),
                    "new_balance": float(result['current_balance']),
                    "notes": adjustment.notes,
                    "adjusted_by": user.id
                })
            ))
            
            conn.commit()
            
            account = await get_prepaid_account_status(adjustment.tenant_id, conn)
            return PrepaidAccountResponse(**account)
            
        except psycopg2.Error as e:
            conn.rollback()
            logger.error(f"Database error adjusting prepaid balance: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to adjust prepaid balance"
            )
        finally:
            cursor.close()

@router.get("/metering/{tenant_id}", response_model=BillingAwareMeteringResponse)
async def get_billing_aware_metering(
    tenant_id: str,
    period_start: datetime = Query(..., description="Start of billing period"),
    period_end: datetime = Query(..., description="End of billing period"),
    user: User = Depends(require_permission("billing", "read"))
):
    """Get metering data with billing model awareness and regional pricing."""
    async with get_connection() as conn:
        # Get billing configuration
        billing_config = await get_tenant_billing_config(tenant_id, conn)
        if not billing_config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Billing configuration not found for tenant {tenant_id}"
            )
        
        # Calculate costs with regional adjustments
        costs = await calculate_billing_aware_costs(tenant_id, period_start, period_end, conn)
        
        # Get prepaid account status if applicable
        prepaid_balance = None
        quota_status = None
        billing_alerts = []
        
        if billing_config['billing_model'] == 'prepaid':
            prepaid_account = await get_prepaid_account_status(tenant_id, conn)
            if prepaid_account:
                prepaid_balance = prepaid_account['current_balance']
                quota_status = prepaid_account['status']
                
                # Generate billing alerts
                if prepaid_balance <= 0:
                    billing_alerts.append("Account suspended - zero balance")
                elif prepaid_balance <= 100:
                    billing_alerts.append("Low balance warning")
        
        return BillingAwareMeteringResponse(
            tenant_id=tenant_id,
            billing_model=BillingModel(billing_config['billing_model']),
            period_start=period_start,
            period_end=period_end,
            currency_code=billing_config['currency_code'],
            compute_cost=costs['compute_cost'],
            storage_cost=costs['storage_cost'],
            network_cost=costs['network_cost'],
            snapshot_cost=costs['snapshot_cost'],
            total_cost=costs['total_cost'],
            regional_adjustments=costs['regional_adjustments'],
            prepaid_balance=prepaid_balance,
            quota_status=quota_status,
            next_billing_date=billing_config.get('billing_start_date'),
            billing_alerts=billing_alerts
        )

@router.get("/overview")
async def get_billing_overview(
    user: User = Depends(require_permission("billing", "read"))
):
    """Get billing system overview with key metrics."""
    async with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get billing statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tenants,
                COUNT(*) FILTER (WHERE billing_model = 'prepaid') as prepaid_tenants,
                COUNT(*) FILTER (WHERE billing_model = 'pay_as_you_go') as payg_tenants
            FROM tenant_billing_config
        """)
        billing_stats = cursor.fetchone()
        
        # Get prepaid account statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_accounts,
                COUNT(*) FILTER (WHERE current_balance <= 0 AND quota_enforcement) as suspended_accounts,
                COUNT(*) FILTER (WHERE current_balance <= 100) as low_balance_accounts,
                COALESCE(SUM(current_balance), 0) as total_balance
            FROM prepaid_accounts
        """)
        prepaid_stats = cursor.fetchone()
        
        # Get recent lifecycle events
        cursor.execute("""
            SELECT event_type, COUNT(*) as count
            FROM resource_lifecycle_events
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            GROUP BY event_type
            ORDER BY count DESC
            LIMIT 10
        """)
        recent_events = cursor.fetchall()
        
        cursor.close()
        
        return {
            "billing_summary": dict(billing_stats),
            "prepaid_summary": dict(prepaid_stats),
            "recent_events": [dict(event) for event in recent_events],
            "generated_at": datetime.now(timezone.utc)
        }

# Add the router to be imported by main.py
__all__ = ["router"]