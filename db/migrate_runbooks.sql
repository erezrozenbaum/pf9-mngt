-- ============================================================
-- Runbook tables  –  Policy-as-Code operational runbooks
-- ============================================================

-- ── Runbook definitions ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS runbooks (
    id              BIGSERIAL   PRIMARY KEY,
    runbook_id      TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    name            TEXT        NOT NULL UNIQUE,
    display_name    TEXT        NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    category        TEXT        NOT NULL DEFAULT 'general',  -- e.g. 'vm', 'network', 'security', 'quota', 'diagnostics'
    risk_level      TEXT        NOT NULL DEFAULT 'low',      -- 'low', 'medium', 'high'
    supports_dry_run BOOLEAN   NOT NULL DEFAULT true,
    enabled         BOOLEAN    NOT NULL DEFAULT true,
    parameters_schema JSONB    NOT NULL DEFAULT '{}',        -- JSON Schema for runbook parameters
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runbooks_name     ON runbooks(name);
CREATE INDEX IF NOT EXISTS idx_runbooks_category ON runbooks(category);
CREATE INDEX IF NOT EXISTS idx_runbooks_enabled  ON runbooks(enabled);

-- ── Approval policies (flexible: who triggers → who approves) ───
CREATE TABLE IF NOT EXISTS runbook_approval_policies (
    id                  BIGSERIAL   PRIMARY KEY,
    policy_id           TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    runbook_name        TEXT        NOT NULL,
    trigger_role        TEXT        NOT NULL DEFAULT 'operator',    -- role that can trigger
    approver_role       TEXT        NOT NULL DEFAULT 'admin',       -- role that must approve
    approval_mode       TEXT        NOT NULL DEFAULT 'single_approval',  -- 'auto_approve', 'single_approval', 'multi_approval'
    escalation_timeout_minutes INTEGER NOT NULL DEFAULT 60,        -- auto-escalate after N minutes
    max_auto_executions_per_day INTEGER NOT NULL DEFAULT 50,       -- rate limit for auto-approved runs
    enabled             BOOLEAN    NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(runbook_name, trigger_role)
);

CREATE INDEX IF NOT EXISTS idx_rbap_runbook ON runbook_approval_policies(runbook_name);
CREATE INDEX IF NOT EXISTS idx_rbap_trigger ON runbook_approval_policies(trigger_role);

-- ── Executions (full audit trail) ───────────────────────────────
CREATE TABLE IF NOT EXISTS runbook_executions (
    id              BIGSERIAL   PRIMARY KEY,
    execution_id    TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    runbook_name    TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending_approval',  -- pending_approval, approved, rejected, executing, completed, failed, cancelled, timed_out
    dry_run         BOOLEAN    NOT NULL DEFAULT false,
    parameters      JSONB      NOT NULL DEFAULT '{}',
    result          JSONB      NOT NULL DEFAULT '{}',
    triggered_by    TEXT        NOT NULL,               -- username
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by     TEXT,                               -- username (null if auto-approved or pending)
    approved_at     TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    items_found     INTEGER     NOT NULL DEFAULT 0,     -- e.g. orphan ports found
    items_actioned  INTEGER     NOT NULL DEFAULT 0,     -- e.g. ports deleted
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rbe_runbook   ON runbook_executions(runbook_name);
CREATE INDEX IF NOT EXISTS idx_rbe_status    ON runbook_executions(status);
CREATE INDEX IF NOT EXISTS idx_rbe_trigger   ON runbook_executions(triggered_by);
CREATE INDEX IF NOT EXISTS idx_rbe_created   ON runbook_executions(created_at DESC);

-- ── Approval records (for multi-approval workflows) ─────────────
CREATE TABLE IF NOT EXISTS runbook_approvals (
    id              BIGSERIAL   PRIMARY KEY,
    execution_id    TEXT        NOT NULL REFERENCES runbook_executions(execution_id) ON DELETE CASCADE,
    approver        TEXT        NOT NULL,
    decision        TEXT        NOT NULL,   -- 'approved', 'rejected'
    comment         TEXT        NOT NULL DEFAULT '',
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rba_execution ON runbook_approvals(execution_id);

-- ── Seed built-in runbook definitions ───────────────────────────
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema) VALUES
(
    'stuck_vm_remediation',
    'Stuck VM Remediation',
    'Detects VMs stuck in BUILD, ERROR, or transitional states and remediates via soft reboot → hard reboot → escalation. Identifies VMs stuck for longer than a configurable threshold.',
    'vm',
    'medium',
    true,
    '{"type":"object","properties":{"stuck_threshold_minutes":{"type":"integer","default":30,"description":"Minutes a VM must be stuck before intervention"},"action":{"type":"string","enum":["soft_reboot","hard_reboot","report_only"],"default":"report_only","description":"Remediation action to take"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
),
(
    'orphan_resource_cleanup',
    'Orphan Resource Cleanup',
    'Finds orphaned ports (no device owner), orphaned volumes (available, no attachments, older than threshold), and orphaned floating IPs (not associated). Cleans up to free quota and reduce clutter.',
    'network',
    'low',
    true,
    '{"type":"object","properties":{"resource_types":{"type":"array","items":{"type":"string","enum":["ports","volumes","floating_ips"]},"default":["ports","volumes","floating_ips"],"description":"Which resource types to scan (ports, volumes, floating_ips)"},"age_threshold_days":{"type":"integer","default":7,"description":"Only target resources older than N days"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
),
(
    'security_group_audit',
    'Security Group Audit',
    'Scans all security groups for overly permissive rules: 0.0.0.0/0 ingress on SSH (22), RDP (3389), database ports (3306, 5432, 1433, 27017). Flags violations for review or auto-remediation.',
    'security',
    'low',
    true,
    '{"type":"object","properties":{"flag_ports":{"type":"array","items":{"type":"integer"},"default":[22,3389,3306,5432,1433,27017],"description":"Ports to flag when open to 0.0.0.0/0"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"}}}'
),
(
    'quota_threshold_check',
    'Quota Threshold Check',
    'Checks per-project quota utilisation and flags projects exceeding configurable thresholds (default 80%). Reports on vCPUs, RAM, instances, volumes, storage, floating IPs.',
    'quota',
    'low',
    true,
    '{"type":"object","properties":{"warning_pct":{"type":"integer","default":80,"description":"Warning threshold percentage"},"critical_pct":{"type":"integer","default":95,"description":"Critical threshold percentage"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"}}}'
),
(
    'diagnostics_bundle',
    'Diagnostics Bundle',
    'Collects a comprehensive diagnostics bundle: hypervisor stats, service status, agent health, recent errors, resource counts, and quota summaries. Useful for incident triage.',
    'diagnostics',
    'low',
    true,
    '{"type":"object","properties":{"include_sections":{"type":"array","items":{"type":"string","enum":["hypervisors","services","agents","errors","resources","quotas"]},"default":["hypervisors","services","resources","quotas"],"description":"Sections to include in the bundle"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    risk_level = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at = now();

-- ── Seed default approval policies ──────────────────────────────
-- Operators can trigger everything; approval varies by risk
INSERT INTO runbook_approval_policies (runbook_name, trigger_role, approver_role, approval_mode) VALUES
    ('stuck_vm_remediation',   'operator',   'admin',  'single_approval'),
    ('stuck_vm_remediation',   'admin',      'admin',  'auto_approve'),
    ('stuck_vm_remediation',   'superadmin', 'admin',  'auto_approve'),
    ('orphan_resource_cleanup','operator',   'admin',  'single_approval'),
    ('orphan_resource_cleanup','admin',      'admin',  'auto_approve'),
    ('orphan_resource_cleanup','superadmin', 'admin',  'auto_approve'),
    ('security_group_audit',   'operator',   'admin',  'auto_approve'),
    ('security_group_audit',   'admin',      'admin',  'auto_approve'),
    ('security_group_audit',   'superadmin', 'admin',  'auto_approve'),
    ('quota_threshold_check',  'operator',   'admin',  'auto_approve'),
    ('quota_threshold_check',  'admin',      'admin',  'auto_approve'),
    ('quota_threshold_check',  'superadmin', 'admin',  'auto_approve'),
    ('diagnostics_bundle',     'operator',   'admin',  'auto_approve'),
    ('diagnostics_bundle',     'admin',      'admin',  'auto_approve'),
    ('diagnostics_bundle',     'superadmin', 'admin',  'auto_approve')
ON CONFLICT (runbook_name, trigger_role) DO NOTHING;

-- ── RBAC permissions ────────────────────────────────────────────
INSERT INTO role_permissions (role, resource, action) VALUES
    ('operator',   'runbooks', 'read'),
    ('operator',   'runbooks', 'write'),   -- trigger
    ('admin',      'runbooks', 'read'),
    ('admin',      'runbooks', 'write'),
    ('admin',      'runbooks', 'admin'),   -- approve + configure policies
    ('superadmin', 'runbooks', 'read'),
    ('superadmin', 'runbooks', 'write'),
    ('superadmin', 'runbooks', 'admin'),
    ('viewer',     'runbooks', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ── Navigation registration ────────────────────────────────────
-- Add runbooks to the technical_tools nav group (operator-facing)
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, description, sort_order, is_active, is_action)
SELECT ng.id, 'runbooks', 'Runbooks', '📋', '/runbooks', 'runbooks',
       'Policy-as-code runbooks with approval workflows', 2, true, false
FROM nav_groups ng WHERE ng.key = 'technical_tools'
ON CONFLICT DO NOTHING;

-- Make runbooks visible in every department that has the technical_tools group
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT dng.department_id, ni.id
FROM department_nav_groups dng
JOIN nav_groups ng ON dng.nav_group_id = ng.id AND ng.key = 'technical_tools'
CROSS JOIN nav_items ni
WHERE ni.key = 'runbooks'
ON CONFLICT DO NOTHING;
