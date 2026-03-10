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

-- ── 3b. Insert new runbooks for v1.53.0 (quota_adjustment + org_usage_report) ──
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema)
VALUES
(
    'quota_adjustment',
    'Quota Adjustment',
    'Set Nova / Neutron / Cinder quota for a project. Supports dry-run diff, cost estimation, and billing gate approval for quota increases. Core building block for the quota-increase ticket workflow.',
    'quota', 'high', true,
    '{"type":"object","required":["project_id"],"properties":{"project_id":{"type":"string","description":"Target project UUID"},"project_name":{"type":"string","description":"Display name (audit only)"},"new_vcpus":{"type":"integer","minimum":0,"description":"New vCPU quota limit (0 = no change)"},"new_ram_mb":{"type":"integer","minimum":0,"description":"New RAM quota in MB (0 = no change)"},"new_instances":{"type":"integer","minimum":0,"description":"New instance quota limit (0 = no change)"},"new_networks":{"type":"integer","minimum":0,"description":"New Neutron network quota (0 = no change)"},"new_volumes":{"type":"integer","minimum":0,"description":"New Cinder volumes quota (0 = no change)"},"new_gigabytes":{"type":"integer","minimum":0,"description":"New Cinder gigabytes quota (0 = no change)"},"reason":{"type":"string","description":"Free-text justification (written to audit log)"},"require_billing_approval":{"type":"boolean","default":true,"description":"Call billing gate when quota is being increased"}}}'
),
(
    'org_usage_report',
    'Org Usage Report',
    'Complete read-only usage and cost report for a single project/org. Returns per-resource quota utilisation, active server breakdown, storage and snapshot totals, floating IP count, cost estimate for the period, and a pre-rendered HTML body suitable for email.',
    'general', 'low', false,
    '{"type":"object","required":["project_id"],"properties":{"project_id":{"type":"string","description":"Target project UUID"},"include_cost_estimate":{"type":"boolean","default":true,"description":"Include cost estimate table in the report"},"include_snapshot_details":{"type":"boolean","default":true,"description":"Query Cinder snapshot list for snapshot GB total"},"period_days":{"type":"integer","default":30,"minimum":1,"description":"Billing/usage period in days for cost calculations"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description  = EXCLUDED.description,
    category     = EXCLUDED.category,
    risk_level   = EXCLUDED.risk_level,
    supports_dry_run  = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at   = now();

-- Approval policies for the new runbooks
INSERT INTO runbook_approval_policies (runbook_name, trigger_role, approver_role, approval_mode) VALUES
    ('quota_adjustment', 'operator',   'admin', 'single_approval'),
    ('quota_adjustment', 'admin',      'admin', 'auto_approve'),
    ('quota_adjustment', 'superadmin', 'admin', 'auto_approve'),
    ('org_usage_report', 'operator',   'admin', 'auto_approve'),
    ('org_usage_report', 'admin',      'admin', 'auto_approve'),
    ('org_usage_report', 'superadmin', 'admin', 'auto_approve')
ON CONFLICT (runbook_name, trigger_role) DO NOTHING;

-- ── 3c. Patch parameters_schema — add x-lookup hints (v1.54.0 UX) ───────────
-- Idempotent: ON CONFLICT DO UPDATE — safe to run on any existing install.
UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"stuck_threshold_minutes":{"type":"integer","default":30,"description":"Minutes a VM must be stuck before intervention"},"action":{"type":"string","enum":["soft_reboot","hard_reboot","report_only"],"default":"report_only","description":"Remediation action to take"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
    WHERE name = 'stuck_vm_remediation';

UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"resource_types":{"type":"array","items":{"type":"string","enum":["ports","volumes","floating_ips"]},"default":["ports","volumes","floating_ips"],"description":"Which resource types to scan (ports, volumes, floating_ips)"},"age_threshold_days":{"type":"integer","default":7,"description":"Only target resources older than N days"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
    WHERE name = 'orphan_resource_cleanup';

UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"flag_ports":{"type":"array","items":{"type":"integer"},"default":[22,3389,3306,5432,1433,27017],"description":"Ports to flag when open to 0.0.0.0/0"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"}}}'
    WHERE name = 'security_group_audit';

UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"warning_pct":{"type":"integer","default":80,"description":"Warning threshold percentage"},"critical_pct":{"type":"integer","default":95,"description":"Critical threshold percentage"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"}}}'
    WHERE name = 'quota_threshold_check';

UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"server_id":{"type":"string","x-lookup":"vms","description":"Select the VM to diagnose"},"auto_restart":{"type":"boolean","default":false,"description":"Restart the VM if issues found"},"restart_type":{"type":"string","enum":["soft","hard","guest_os"],"default":"soft","description":"Restart method"}},"required":["server_id"]}'
    WHERE name = 'vm_health_quickfix';

UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"server_id":{"type":"string","x-lookup":"vms","description":"Select the VM to snapshot"},"reference_id":{"type":"string","default":"","description":"Ticket or incident reference ID"},"tag_prefix":{"type":"string","default":"Pre-T2-escalation","description":"Tag prefix for the snapshot"}},"required":["server_id"]}'
    WHERE name = 'snapshot_before_escalation';

UPDATE runbooks SET parameters_schema = '{"type":"object","properties":{"server_id":{"type":"string","x-lookup":"vms","description":"Select the VM"},"new_password":{"type":"string","default":"","description":"New password (auto-generated if blank)"},"enable_console":{"type":"boolean","default":true,"description":"Enable VNC/SPICE console"},"console_expiry_minutes":{"type":"integer","default":30,"description":"Console link expiry in minutes"}},"required":["server_id"]}'
    WHERE name = 'password_reset_console';

UPDATE runbooks SET parameters_schema = '{"type":"object","required":["project_id"],"properties":{"project_id":{"type":"string","x-lookup":"projects","description":"Select the target project"},"project_name":{"type":"string","x-hidden":true,"description":"Display name (auto-filled)"},"new_vcpus":{"type":"integer","minimum":0,"description":"New vCPU quota limit (0 = no change)"},"new_ram_mb":{"type":"integer","minimum":0,"description":"New RAM quota in MB (0 = no change)"},"new_instances":{"type":"integer","minimum":0,"description":"New instance quota limit (0 = no change)"},"new_networks":{"type":"integer","minimum":0,"description":"New Neutron network quota (0 = no change)"},"new_volumes":{"type":"integer","minimum":0,"description":"New Cinder volumes quota (0 = no change)"},"new_gigabytes":{"type":"integer","minimum":0,"description":"New Cinder gigabytes quota (0 = no change)"},"reason":{"type":"string","description":"Free-text justification (written to audit log)"},"require_billing_approval":{"type":"boolean","default":true,"description":"Call billing gate when quota is being increased"}}}'
    WHERE name = 'quota_adjustment';

UPDATE runbooks SET parameters_schema = '{"type":"object","required":["project_id"],"properties":{"project_id":{"type":"string","x-lookup":"projects","description":"Select the target project"},"include_cost_estimate":{"type":"boolean","default":true,"description":"Include cost estimate table in the report"},"include_snapshot_details":{"type":"boolean","default":true,"description":"Query Cinder snapshot list for snapshot GB total"},"period_days":{"type":"integer","default":30,"minimum":1,"description":"Billing/usage period in days for cost calculations"}}}'
    WHERE name = 'org_usage_report';

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

    -- quota_adjustment: Tier2, Tier3, Engineering, Management  (v1.53.0)
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('quota_adjustment', d_t2),  ('quota_adjustment', d_t3),
        ('quota_adjustment', d_eng), ('quota_adjustment', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;

    -- org_usage_report: Sales, Tier2, Tier3, Engineering, Management  (v1.53.0)
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('org_usage_report', d_sal), ('org_usage_report', d_t2),
        ('org_usage_report', d_t3),  ('org_usage_report', d_eng),
        ('org_usage_report', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;
END $$;

-- ── 3d. Insert new runbooks for v1.55.0 (vm_rightsizing + capacity_forecast) ──
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema)
VALUES
(
    'vm_rightsizing',
    'VM Rightsizing',
    'Analyse VM CPU and RAM utilisation from metering data over a configurable window. Identifies over-provisioned VMs, suggests a smaller cheaper flavor, and optionally performs the resize with a pre-resize snapshot for safety.',
    'compute', 'high', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope to one project (blank = all projects)"},"server_ids":{"type":"array","items":{"type":"string"},"x-lookup":"vms_multi","description":"Specific VMs to analyse (blank = all VMs in project)"},"analysis_days":{"type":"integer","default":14,"minimum":3,"description":"Days of metering history to average"},"cpu_idle_pct":{"type":"number","default":15,"description":"Max average CPU % to qualify as over-provisioned"},"ram_idle_pct":{"type":"number","default":30,"description":"Max average RAM % to qualify as over-provisioned"},"min_savings_per_month":{"type":"number","default":5,"description":"Minimum monthly USD savings for a VM to appear in results"},"require_snapshot_first":{"type":"boolean","default":true,"description":"Create a snapshot before resizing each VM"}}}'
),
(
    'capacity_forecast',
    'Capacity Forecast',
    'Runs a linear-regression forecast on hypervisor history data to project when vCPU and RAM capacity will reach the configured warning threshold. Returns weekly trend data, current utilisation, and days-to-threshold for each dimension.',
    'general', 'low', false,
    '{"type":"object","properties":{"warn_days_threshold":{"type":"integer","default":90,"description":"Raise an alert if exhaustion is projected within this many days"},"capacity_warn_pct":{"type":"number","default":80,"description":"Capacity utilisation % treated as the warning threshold"},"trigger_ticket":{"type":"boolean","default":false,"description":"Attempt to open a capacity ticket when alerts are generated (requires ticket system)"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description  = EXCLUDED.description,
    category     = EXCLUDED.category,
    risk_level   = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at   = now();

INSERT INTO runbook_approval_policies (runbook_name, trigger_role, approver_role, approval_mode) VALUES
    ('vm_rightsizing',  'operator',   'admin', 'single_approval'),
    ('vm_rightsizing',  'admin',      'admin', 'single_approval'),
    ('vm_rightsizing',  'superadmin', 'admin', 'auto_approve'),
    ('capacity_forecast','operator',  'admin', 'auto_approve'),
    ('capacity_forecast','admin',     'admin', 'auto_approve'),
    ('capacity_forecast','superadmin','admin', 'auto_approve')
ON CONFLICT (runbook_name, trigger_role) DO NOTHING;

-- Dept visibility for v1.55.0 runbooks (must follow runbooks INSERT above)
DO $$
DECLARE
    d_eng  int; d_t3 int; d_mgmt int;
BEGIN
    SELECT id INTO d_eng  FROM departments WHERE name = 'Engineering' LIMIT 1;
    SELECT id INTO d_t3   FROM departments WHERE name = 'Tier3 Support' LIMIT 1;
    SELECT id INTO d_mgmt FROM departments WHERE name = 'Management' LIMIT 1;

    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        ('vm_rightsizing', d_eng),    ('vm_rightsizing', d_t3),    ('vm_rightsizing', d_mgmt),
        ('capacity_forecast', d_eng), ('capacity_forecast', d_t3), ('capacity_forecast', d_mgmt)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;
END $$;

-- ============================================================
-- Section 3e: Phase B3 runbooks (v1.56.0)
-- disaster_recovery_drill + tenant_offboarding
-- ============================================================

-- Runbook definitions
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema) VALUES
(
    'disaster_recovery_drill',
    'Disaster Recovery Drill',
    'Clone VMs tagged as DR candidates into an isolated network, verify they boot successfully within the timeout, then tear down all drill resources. Provides a safe, repeatable DR validation without touching production traffic.',
    'compute', 'medium', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope drill to one project (blank = scan all projects)"},"server_ids":{"type":"array","items":{"type":"string"},"x-lookup":"vms_multi","description":"Explicit VM IDs to drill (blank = use tag_filter)"},"tag_filter":{"type":"string","default":"dr_candidate","description":"Metadata key on VMs that marks them as DR candidates"},"boot_timeout_minutes":{"type":"integer","default":10,"minimum":1,"description":"Per-VM boot poll timeout in minutes"},"max_vms":{"type":"integer","default":10,"minimum":1,"description":"Maximum number of VMs to include in a single drill run"},"network_cidr":{"type":"string","default":"192.168.99.0/24","description":"CIDR for the ephemeral isolated DR network"},"skip_teardown_on_failure":{"type":"boolean","default":false,"description":"Leave DR resources running if a VM fails to boot (for debugging)"}}}'
),
(
    'tenant_offboarding',
    'Tenant Offboarding',
    'Safely exits a customer from the platform: releases FIPs, stops VMs, removes unattached ports, disables the Keystone project, tags resources with retention metadata, notifies CRM, and emails a final usage report. Requires confirm_project_name to match exactly.',
    'provisioning', 'critical', true,
    '{"type":"object","required":["project_id","confirm_project_name"],"properties":{"project_id":{"type":"string","x-lookup":"projects","description":"Keystone project to offboard"},"confirm_project_name":{"type":"string","description":"Must exactly match the project name (safety check)"},"retention_days":{"type":"integer","default":30,"description":"Days before final resource deletion is scheduled"},"email_final_report":{"type":"boolean","default":true,"description":"Send the usage report to the customer email"},"customer_email":{"type":"string","format":"email","description":"Recipient for the final usage report email"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    risk_level = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at = now();

-- Approval policies for B3 runbooks
INSERT INTO runbook_approval_policies (runbook_name, trigger_role, approver_role, approval_mode) VALUES
    ('disaster_recovery_drill', 'operator',   'admin', 'single_approval'),
    ('disaster_recovery_drill', 'admin',      'admin', 'single_approval'),
    ('disaster_recovery_drill', 'superadmin', 'admin', 'single_approval'),
    ('tenant_offboarding',      'operator',   'admin', 'single_approval'),
    ('tenant_offboarding',      'admin',      'admin', 'single_approval'),
    ('tenant_offboarding',      'superadmin', 'admin', 'single_approval')
ON CONFLICT (runbook_name, trigger_role) DO NOTHING;

-- Dept visibility for B3 runbooks
DO $$
DECLARE
    d_eng int; d_mgmt int;
BEGIN
    SELECT id INTO d_eng  FROM departments WHERE name = 'Engineering' LIMIT 1;
    SELECT id INTO d_mgmt FROM departments WHERE name = 'Management'  LIMIT 1;

    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        -- disaster_recovery_drill: Engineering only
        ('disaster_recovery_drill', d_eng),
        -- tenant_offboarding: Management + Engineering
        ('tenant_offboarding', d_mgmt),
        ('tenant_offboarding', d_eng)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;
END $$;
