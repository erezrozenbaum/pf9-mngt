-- Operational Intelligence Phase 4 — MSP & Business Value Layer
-- v1.90.0 — 2026-04-21
-- Idempotent: safe to re-run.

-- ── Table 1: Contract entitlements ──────────────────────────────────────────
-- Stores what each tenant is contractually paying for.
-- Intentionally separate from project_quotas (live platform limits).
-- The Revenue Leakage engine compares project_quotas.in_use against this.
CREATE TABLE IF NOT EXISTS msp_contract_entitlements (
    id              BIGSERIAL    PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sku_name        TEXT NOT NULL DEFAULT '',
    resource        TEXT NOT NULL,      -- vcpu | ram_gb | storage_gb | floating_ip
    contracted      INT  NOT NULL,
    region_id       TEXT,               -- NULL = global entitlement (all regions)
    billing_id      TEXT,
    effective_from  DATE NOT NULL,
    effective_to    DATE,               -- NULL = currently active
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Unique: one active entitlement per (tenant, resource, region) at a given date
CREATE UNIQUE INDEX IF NOT EXISTS uq_entitlements_active_with_region
    ON msp_contract_entitlements(tenant_id, resource, effective_from, region_id)
    WHERE region_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_entitlements_active_global
    ON msp_contract_entitlements(tenant_id, resource, effective_from)
    WHERE region_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_entitlements_tenant
    ON msp_contract_entitlements(tenant_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_active
    ON msp_contract_entitlements(tenant_id, resource, region_id)
    WHERE effective_to IS NULL;

-- ── Table 2: Labor rates ─────────────────────────────────────────────────────
-- Per-insight-type hours saved + MSP billed rate.
-- QBR generator multiplies hours_saved × resolved count to produce ROI figure.
CREATE TABLE IF NOT EXISTS msp_labor_rates (
    insight_type    TEXT PRIMARY KEY,
    hours_saved     DECIMAL(5,2) NOT NULL DEFAULT 0.50,
    rate_per_hour   DECIMAL(8,2) NOT NULL DEFAULT 150.00,
    description     TEXT
);

-- Seed defaults — MSP admin can UPDATE via the settings API
INSERT INTO msp_labor_rates (insight_type, hours_saved, rate_per_hour, description) VALUES
    ('capacity',   1.50, 150.00, 'Storage capacity planning + ticket triage'),
    ('waste',      0.50, 150.00, 'Idle VM or volume cleanup per resource'),
    ('risk',       2.00, 150.00, 'Snapshot/backup gap remediation + RCA'),
    ('drift',      1.00, 150.00, 'Drift investigation + compliance note'),
    ('anomaly',    1.50, 150.00, 'Anomaly investigation + root cause analysis'),
    ('health',     0.75, 150.00, 'Health score decline review + action'),
    ('leakage',    1.00, 150.00, 'Contract entitlement review + billing reconciliation'),
    ('sla_risk',   2.00, 150.00, 'SLA breach prevention + client communication')
ON CONFLICT (insight_type) DO NOTHING;

-- ── Table 3: PSA webhook config ──────────────────────────────────────────────
-- Generic outbound webhook — PSA-agnostic.  Fires when severity >= min_severity.
-- auth_header stored encrypted via crypto_helper.py (Fernet).
CREATE TABLE IF NOT EXISTS psa_webhook_config (
    id              SERIAL PRIMARY KEY,
    psa_name        TEXT NOT NULL,
    webhook_url     TEXT NOT NULL,
    auth_header     TEXT NOT NULL,      -- encrypted: "fernet:<ciphertext>"
    min_severity    TEXT NOT NULL DEFAULT 'high',
    insight_types   TEXT[] NOT NULL DEFAULT '{}',   -- empty = all types
    region_ids      TEXT[] NOT NULL DEFAULT '{}',   -- empty = all regions
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── RBAC entries ─────────────────────────────────────────────────────────────
INSERT INTO role_permissions (role, resource, action) VALUES
    ('superadmin', 'intelligence_settings', 'read'),
    ('superadmin', 'intelligence_settings', 'write'),
    ('admin',      'intelligence_settings', 'read'),
    ('admin',      'intelligence_settings', 'write'),
    ('superadmin', 'qbr', 'read'),
    ('superadmin', 'qbr', 'write'),
    ('admin',      'qbr', 'read'),
    ('admin',      'qbr', 'write'),
    ('operator',   'qbr', 'read'),
    ('superadmin', 'psa', 'read'),
    ('superadmin', 'psa', 'write'),
    ('admin',      'psa', 'read'),
    ('admin',      'psa', 'write')
ON CONFLICT DO NOTHING;
