-- =============================================================================
-- SLA Compliance Tracking — tier templates, commitments, monthly rollups + RBAC
-- Version: v1.85.0
-- =============================================================================
-- Idempotent: all guarded by IF NOT EXISTS / ON CONFLICT DO NOTHING.

-- ---------------------------------------------------------------------------
-- Tier templates — bronze / silver / gold / custom defaults
-- MSP admins can extend this list; it drives the "quick-fill" UX.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_tier_templates (
    tier              TEXT PRIMARY KEY,
    uptime_pct        DECIMAL(5,3),           -- NULL = customer-defined
    rto_hours         INT,
    rpo_hours         INT,
    mtta_hours        INT,
    mttr_hours        INT,
    backup_freq_hours INT NOT NULL DEFAULT 24,
    display_name      TEXT NOT NULL
);

INSERT INTO sla_tier_templates
    (tier, uptime_pct, rto_hours, rpo_hours, mtta_hours, mttr_hours, backup_freq_hours, display_name)
VALUES
    ('bronze', 99.0,  8,  24, 8,  72, 24, 'Bronze'),
    ('silver', 99.5,  4,  12, 4,  48, 12, 'Silver'),
    ('gold',   99.9,  2,   4, 2,  24,  4, 'Gold'),
    ('custom', NULL, NULL, NULL, NULL, NULL, 24, 'Custom')
ON CONFLICT (tier) DO NOTHING;

-- ---------------------------------------------------------------------------
-- sla_commitments — what was sold to each tenant
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_commitments (
    id                SERIAL,
    tenant_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tier              TEXT NOT NULL DEFAULT 'custom',
    uptime_pct        DECIMAL(5,3),
    rto_hours         INT,
    rpo_hours         INT,
    mtta_hours        INT,
    mttr_hours        INT,
    backup_freq_hours INT NOT NULL DEFAULT 24,
    effective_from    DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to      DATE,                   -- NULL = currently active
    region_id         TEXT,                   -- NULL = applies to all regions
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, effective_from)
);

-- Fast lookup for the active commitment per tenant
CREATE INDEX IF NOT EXISTS idx_sla_active
    ON sla_commitments(tenant_id)
    WHERE effective_to IS NULL;

-- ---------------------------------------------------------------------------
-- sla_compliance_monthly — monthly rollup computed by sla_worker
-- One row per tenant per month (per region if region_id != '').
-- Recomputed nightly; final at month-end.
-- region_id = '' means aggregate across all regions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_compliance_monthly (
    tenant_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    month                DATE NOT NULL,           -- first day of month
    region_id            TEXT NOT NULL DEFAULT '', -- '' = all-region aggregate
    uptime_actual_pct    DECIMAL(5,3),
    rto_worst_hours      DECIMAL(6,2),
    rpo_worst_hours      DECIMAL(6,2),
    mtta_avg_hours       DECIMAL(6,2),
    mttr_avg_hours       DECIMAL(6,2),
    backup_success_pct   DECIMAL(5,2),
    breach_fields        TEXT[] NOT NULL DEFAULT '{}',
    at_risk_fields       TEXT[] NOT NULL DEFAULT '{}',
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, month, region_id)
);

CREATE INDEX IF NOT EXISTS idx_sla_compliance_tenant
    ON sla_compliance_monthly(tenant_id, month DESC);

-- ---------------------------------------------------------------------------
-- RBAC permissions
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'sla', 'read'),
    ('operator',   'sla', 'read'),
    ('admin',      'sla', 'read'),
    ('admin',      'sla', 'write'),
    ('superadmin', 'sla', 'read'),
    ('superadmin', 'sla', 'write'),
    ('superadmin', 'sla', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
