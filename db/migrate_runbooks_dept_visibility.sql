-- =====================================================================
-- Migration: Runbook Department Visibility + External Integrations
-- Version: v1.52.0 / Phase A
-- Run on: pf9_mgmt database
-- Idempotent: uses IF NOT EXISTS / ON CONFLICT DO NOTHING throughout.
-- =====================================================================

-- ── 1. Runbook department visibility ─────────────────────────────────
-- Absence of rows for a runbook = visible to ALL departments.
-- Superadmin always sees all runbooks regardless.
CREATE TABLE IF NOT EXISTS runbook_dept_visibility (
    id           SERIAL PRIMARY KEY,
    runbook_name TEXT NOT NULL REFERENCES runbooks(name) ON DELETE CASCADE,
    dept_id      INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    UNIQUE(runbook_name, dept_id)
);

CREATE INDEX IF NOT EXISTS idx_rdv_runbook ON runbook_dept_visibility(runbook_name);
CREATE INDEX IF NOT EXISTS idx_rdv_dept    ON runbook_dept_visibility(dept_id);

-- ── 2. External integrations framework ───────────────────────────────
-- Supports billing_gate, crm, and generic webhook integrations.
-- auth_credential is AES-256 (Fernet) encrypted at rest.
-- The encryption key is derived from JWT_SECRET at the API layer.
CREATE TABLE IF NOT EXISTS external_integrations (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT UNIQUE NOT NULL,
    display_name            TEXT NOT NULL,
    integration_type        TEXT NOT NULL DEFAULT 'webhook',
    -- Valid values: billing_gate | crm | webhook
    base_url                TEXT NOT NULL,
    auth_type               TEXT NOT NULL DEFAULT 'bearer',
    -- Valid values: bearer | basic | api_key
    auth_credential         TEXT,
    -- Encrypted with Fernet(sha256(JWT_SECRET)). Never stored or logged in plaintext.
    auth_header_name        TEXT NOT NULL DEFAULT 'Authorization',
    request_template        JSONB NOT NULL DEFAULT '{}',
    response_approval_path  TEXT NOT NULL DEFAULT 'approved',
    response_reason_path    TEXT NOT NULL DEFAULT 'reason',
    response_charge_id_path TEXT NOT NULL DEFAULT 'charge_id',
    enabled                 BOOLEAN NOT NULL DEFAULT false,
    timeout_seconds         INTEGER NOT NULL DEFAULT 10,
    verify_ssl              BOOLEAN NOT NULL DEFAULT true,
    last_tested_at          TIMESTAMPTZ,
    last_test_status        TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ext_integ_name    ON external_integrations(name);
CREATE INDEX IF NOT EXISTS idx_ext_integ_type    ON external_integrations(integration_type);
CREATE INDEX IF NOT EXISTS idx_ext_integ_enabled ON external_integrations(enabled);

-- ── 3. Role permissions for integrations resource ────────────────────
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',      'integrations', 'read'),
    ('admin',      'integrations', 'admin'),
    ('superadmin', 'integrations', 'read'),
    ('superadmin', 'integrations', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ── 4. Seed dept visibility for the 14 shipped runbooks ──────────────
-- Department IDs match the seed order in init.sql:
--   1 = Engineering
--   2 = Tier1 Support
--   3 = Tier2 Support
--   4 = Tier3 Support
--   5 = Sales
--   6 = Marketing
--   7 = Management
--
-- These are looked up by name to be safe against ID drift on fresh installs:
DO $$
DECLARE
    d_eng  INTEGER := (SELECT id FROM departments WHERE name = 'Engineering'  LIMIT 1);
    d_t1   INTEGER := (SELECT id FROM departments WHERE name = 'Tier1 Support' LIMIT 1);
    d_t2   INTEGER := (SELECT id FROM departments WHERE name = 'Tier2 Support' LIMIT 1);
    d_t3   INTEGER := (SELECT id FROM departments WHERE name = 'Tier3 Support' LIMIT 1);
    d_sal  INTEGER := (SELECT id FROM departments WHERE name = 'Sales'         LIMIT 1);
    d_mgmt INTEGER := (SELECT id FROM departments WHERE name = 'Management'    LIMIT 1);
BEGIN
    -- stuck_vm_remediation: Engineering, Tier1, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('stuck_vm_remediation', d_eng), ('stuck_vm_remediation', d_t1),
        ('stuck_vm_remediation', d_t2),  ('stuck_vm_remediation', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- vm_health_quickfix: Engineering, Tier1, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('vm_health_quickfix', d_eng), ('vm_health_quickfix', d_t1),
        ('vm_health_quickfix', d_t2),  ('vm_health_quickfix', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- password_reset_console: Engineering, Tier1, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('password_reset_console', d_eng), ('password_reset_console', d_t1),
        ('password_reset_console', d_t2),  ('password_reset_console', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- snapshot_before_escalation: Engineering, Tier1, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('snapshot_before_escalation', d_eng), ('snapshot_before_escalation', d_t1),
        ('snapshot_before_escalation', d_t2),  ('snapshot_before_escalation', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- orphan_resource_cleanup: Engineering, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('orphan_resource_cleanup', d_eng), ('orphan_resource_cleanup', d_t2),
        ('orphan_resource_cleanup', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- security_group_audit: Engineering, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('security_group_audit', d_eng), ('security_group_audit', d_t2),
        ('security_group_audit', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- security_compliance_audit: Engineering, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('security_compliance_audit', d_eng), ('security_compliance_audit', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- quota_threshold_check: Engineering, Tier2, Tier3, Sales, Management
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('quota_threshold_check', d_eng), ('quota_threshold_check', d_t2),
        ('quota_threshold_check', d_t3),  ('quota_threshold_check', d_sal),
        ('quota_threshold_check', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- snapshot_quota_forecast: Engineering, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('snapshot_quota_forecast', d_eng), ('snapshot_quota_forecast', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- diagnostics_bundle: Engineering, Tier1, Tier2, Tier3
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('diagnostics_bundle', d_eng), ('diagnostics_bundle', d_t1),
        ('diagnostics_bundle', d_t2),  ('diagnostics_bundle', d_t3)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- upgrade_opportunity_detector: Engineering, Sales, Management
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('upgrade_opportunity_detector', d_eng), ('upgrade_opportunity_detector', d_sal),
        ('upgrade_opportunity_detector', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- monthly_executive_snapshot: Sales, Management
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('monthly_executive_snapshot', d_sal), ('monthly_executive_snapshot', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- cost_leakage_report: Engineering, Tier3, Sales, Management
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('cost_leakage_report', d_eng), ('cost_leakage_report', d_t3),
        ('cost_leakage_report', d_sal), ('cost_leakage_report', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- user_last_login: Engineering, Management
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('user_last_login', d_eng), ('user_last_login', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;
END $$;
