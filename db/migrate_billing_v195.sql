-- Enhanced Billing & Metering System (v1.95) - Database Migration
-- Apply new tables to existing database

-- ---------------------------------------------------------------------------
-- Tenant billing configuration - Prepaid vs Pay-as-you-go billing models
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_billing_config (
    tenant_id TEXT PRIMARY KEY REFERENCES domains(id),
    billing_model TEXT NOT NULL CHECK (billing_model IN ('prepaid', 'pay_as_you_go')),
    currency_code TEXT DEFAULT 'USD',
    onboarding_date DATE NOT NULL,
    billing_start_date DATE,
    billing_cycle_day INTEGER GENERATED ALWAYS AS (EXTRACT(DAY FROM COALESCE(billing_start_date, onboarding_date))::INTEGER) STORED,
    sales_person_id TEXT REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to update updated_at on tenant billing config changes
CREATE OR REPLACE FUNCTION update_tenant_billing_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tenant_billing_config_updated_at
    BEFORE UPDATE ON tenant_billing_config
    FOR EACH ROW EXECUTE FUNCTION update_tenant_billing_config_updated_at();

-- ---------------------------------------------------------------------------
-- Prepaid account management - Balance tracking for prepaid tenants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prepaid_accounts (
    tenant_id TEXT PRIMARY KEY REFERENCES domains(id),
    current_balance DECIMAL(15,2) DEFAULT 0.00,
    last_charge_date DATE,
    next_billing_date DATE,
    currency_code TEXT DEFAULT 'USD',
    quota_enforcement BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to update updated_at on prepaid account changes
CREATE TRIGGER prepaid_accounts_updated_at
    BEFORE UPDATE ON prepaid_accounts
    FOR EACH ROW EXECUTE FUNCTION update_tenant_billing_config_updated_at();

-- ---------------------------------------------------------------------------
-- Regional pricing overrides - Optional region-specific pricing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regional_pricing_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT REFERENCES domains(id),
    region_name TEXT NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT,
    price_per_hour DECIMAL(15,4),
    price_per_month DECIMAL(15,2),
    currency_code TEXT DEFAULT 'USD',
    effective_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, region_name, category, subcategory)
);

-- Index for efficient regional pricing lookups
CREATE INDEX IF NOT EXISTS idx_regional_pricing_tenant_region 
    ON regional_pricing_overrides(tenant_id, region_name);
CREATE INDEX IF NOT EXISTS idx_regional_pricing_category 
    ON regional_pricing_overrides(category, subcategory);

-- ---------------------------------------------------------------------------
-- Webhook registrations - External system integration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS webhook_registrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT REFERENCES domains(id),
    webhook_url TEXT NOT NULL,
    event_types TEXT[] NOT NULL,
    auth_token TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    last_success_at TIMESTAMPTZ,
    failure_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to update updated_at on webhook registration changes
CREATE TRIGGER webhook_registrations_updated_at
    BEFORE UPDATE ON webhook_registrations
    FOR EACH ROW EXECUTE FUNCTION update_tenant_billing_config_updated_at();

-- Index for efficient webhook lookups
CREATE INDEX IF NOT EXISTS idx_webhook_registrations_tenant 
    ON webhook_registrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhook_registrations_active 
    ON webhook_registrations(is_active) WHERE is_active = TRUE;

-- ---------------------------------------------------------------------------
-- Resource lifecycle events log - Track resource creation/deletion for billing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resource_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB,
    billing_impact JSONB,
    webhook_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient lifecycle event queries
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_tenant 
    ON resource_lifecycle_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_type 
    ON resource_lifecycle_events(resource_type);
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_webhook 
    ON resource_lifecycle_events(webhook_sent) WHERE webhook_sent = FALSE;
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_created 
    ON resource_lifecycle_events(created_at);

-- ---------------------------------------------------------------------------
-- Historical data archival tracking - 7-year compliance management
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_archival_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,
    archive_date DATE NOT NULL,
    records_archived INTEGER,
    archive_location TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for archival log queries
CREATE INDEX IF NOT EXISTS idx_data_archival_table 
    ON data_archival_log(table_name);
CREATE INDEX IF NOT EXISTS idx_data_archival_date 
    ON data_archival_log(archive_date);

-- ---------------------------------------------------------------------------
-- Grant permissions for new billing tables
-- ---------------------------------------------------------------------------

-- Enhanced billing system permissions for tenant portal
GRANT SELECT ON tenant_billing_config TO tenant_portal_role;
GRANT SELECT ON prepaid_accounts TO tenant_portal_role;
GRANT SELECT ON regional_pricing_overrides TO tenant_portal_role;
GRANT SELECT ON resource_lifecycle_events TO tenant_portal_role;

-- Role-based access permissions for billing API (v1.95)
INSERT INTO role_permissions (role, resource, action) VALUES
    ('superadmin', 'billing', 'write'),
    ('admin',      'billing', 'read'),
    ('technical',  'billing', 'read')
ON CONFLICT DO NOTHING;

-- Print completion message
\echo 'Enhanced Billing & Metering System tables created successfully!'