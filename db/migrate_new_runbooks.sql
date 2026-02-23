-- Migration: Add 8 new operational runbooks
-- VM Health Quick Fix, Snapshot Before Escalation, Upgrade Opportunity Detector,
-- Monthly Executive Snapshot, Cost Leakage Report, Password Reset + Console,
-- Security & Compliance Audit, User Last Login Report

-- =====================================================================
-- Runbook definitions
-- =====================================================================

INSERT INTO runbooks (runbook_id, name, display_name, description, category, risk_level, supports_dry_run, enabled, parameters_schema)
VALUES
  (gen_random_uuid()::text, 'vm_health_quickfix', 'VM Health Quick Fix',
   'Diagnose a VM: checks power state, hypervisor, port bindings, volumes, and network. Optionally restart.',
   'vm', 'medium', true, true,
   '{"type":"object","properties":{"server_id":{"type":"string","description":"ID of the VM to diagnose"},"auto_restart":{"type":"boolean","default":false,"description":"Restart the VM if issues found"},"restart_type":{"type":"string","enum":["soft","hard","guest_os"],"default":"soft","description":"Restart method"}},"required":["server_id"]}'::jsonb),

  (gen_random_uuid()::text, 'snapshot_before_escalation', 'Snapshot Before Escalation',
   'Create a tagged snapshot before escalating to Tier 2. Captures VM state, console log, and metadata for traceability.',
   'vm', 'low', true, true,
   '{"type":"object","properties":{"server_id":{"type":"string","description":"ID of the VM to snapshot"},"reference_id":{"type":"string","default":"","description":"Ticket or incident reference ID"},"tag_prefix":{"type":"string","default":"Pre-T2-escalation","description":"Tag prefix for the snapshot"}},"required":["server_id"]}'::jsonb),

  (gen_random_uuid()::text, 'upgrade_opportunity_detector', 'Upgrade Opportunity Detector',
   'Scan tenants for upgrade opportunities: quota pressure, small flavors, old images. Estimates revenue impact. Pricing pulled from Metering configuration.',
   'quota', 'low', false, true,
   '{"type":"object","properties":{"quota_threshold_pct":{"type":"integer","default":80,"description":"Quota usage % to flag"},"include_flavor_analysis":{"type":"boolean","default":true,"description":"Check for small/old flavors"},"include_image_analysis":{"type":"boolean","default":true,"description":"Check for old/deprecated images"}}}'::jsonb),

  (gen_random_uuid()::text, 'monthly_executive_snapshot', 'Monthly Executive Snapshot',
   'Generate an executive summary: total tenants, VMs, compliance %, capacity risk, revenue estimate, top risk tenants with month-over-month deltas. Pricing pulled from Metering configuration.',
   'general', 'low', false, true,
   '{"type":"object","properties":{"risk_top_n":{"type":"integer","default":5,"description":"Number of top risk tenants to show"},"include_deltas":{"type":"boolean","default":true,"description":"Include month-over-month deltas"}}}'::jsonb),

  (gen_random_uuid()::text, 'cost_leakage_report', 'Cost Leakage Report',
   'Detect idle VMs, detached volumes, unused floating IPs, and oversized instances. Calculates estimated monthly waste. Pricing pulled from Metering configuration.',
   'general', 'low', false, true,
   '{"type":"object","properties":{"idle_cpu_threshold_pct":{"type":"integer","default":5,"description":"CPU % below which a VM is idle"},"shutoff_days_threshold":{"type":"integer","default":30,"description":"Days a VM must be SHUTOFF to flag"},"detached_volume_days":{"type":"integer","default":7,"description":"Days a volume must be detached to flag"}}}'::jsonb),

  (gen_random_uuid()::text, 'password_reset_console', 'Password Reset + Console Access',
   'Reset a VM password via metadata injection and enable temporary console access. Logs full audit trail.',
   'vm', 'high', true, true,
   '{"type":"object","properties":{"server_id":{"type":"string","description":"ID of the VM"},"new_password":{"type":"string","default":"","description":"New password (auto-generated if blank)"},"enable_console":{"type":"boolean","default":true,"description":"Enable VNC/SPICE console"},"console_expiry_minutes":{"type":"integer","default":30,"description":"Console link expiry in minutes"}},"required":["server_id"]}'::jsonb),

  (gen_random_uuid()::text, 'security_compliance_audit', 'Security & Compliance Audit',
   'Comprehensive audit: overly permissive security groups, stale users with no recent activity, unencrypted volumes.',
   'security', 'low', false, true,
   '{"type":"object","properties":{"stale_user_days":{"type":"integer","default":90,"description":"Days of inactivity to flag a user as stale"},"flag_wide_port_ranges":{"type":"boolean","default":true,"description":"Flag rules with 0-65535 port ranges"},"check_volume_encryption":{"type":"boolean","default":true,"description":"Check for unencrypted volumes"}}}'::jsonb),

  (gen_random_uuid()::text, 'user_last_login', 'User Last Login Report',
   'List last login time for every user in the system. Flags inactive users and accounts that have never logged in.',
   'security', 'low', false, true,
   '{"type":"object","properties":{"days_inactive_threshold":{"type":"integer","default":30,"description":"Days without activity to flag a user as inactive"},"include_failed_logins":{"type":"boolean","default":false,"description":"Include recent failed login attempts in the report"}}}'::jsonb)

ON CONFLICT (name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  category = EXCLUDED.category,
  risk_level = EXCLUDED.risk_level,
  supports_dry_run = EXCLUDED.supports_dry_run,
  parameters_schema = EXCLUDED.parameters_schema,
  updated_at = now();

-- =====================================================================
-- Approval policies — using the existing approval workflow
-- Read-only/diagnostic runbooks: auto-approve for all roles
-- Business-impact runbooks (upgrade_opportunity_detector): single_approval for operator
-- Security-sensitive (security_compliance_audit, password_reset_console): single_approval for operator+admin
-- =====================================================================

INSERT INTO runbook_approval_policies (policy_id, runbook_name, trigger_role, approver_role, approval_mode, escalation_timeout_minutes, max_auto_executions_per_day, enabled)
VALUES
  -- vm_health_quickfix: diagnostic, auto-approve for all
  (gen_random_uuid()::text, 'vm_health_quickfix',          'operator',   'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'vm_health_quickfix',          'admin',      'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'vm_health_quickfix',          'superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- snapshot_before_escalation: creates snapshot, auto-approve for all
  (gen_random_uuid()::text, 'snapshot_before_escalation',  'operator',   'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'snapshot_before_escalation',  'admin',      'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'snapshot_before_escalation',  'superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- upgrade_opportunity_detector: business-impact, operator needs approval
  (gen_random_uuid()::text, 'upgrade_opportunity_detector','operator',   'admin', 'single_approval', 60, 20, true),
  (gen_random_uuid()::text, 'upgrade_opportunity_detector','admin',      'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'upgrade_opportunity_detector','superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- monthly_executive_snapshot: read-only report, auto-approve for all
  (gen_random_uuid()::text, 'monthly_executive_snapshot',  'operator',   'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'monthly_executive_snapshot',  'admin',      'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'monthly_executive_snapshot',  'superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- cost_leakage_report: read-only report, auto-approve for all
  (gen_random_uuid()::text, 'cost_leakage_report',         'operator',   'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'cost_leakage_report',         'admin',      'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'cost_leakage_report',         'superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- password_reset_console: high-risk, requires approval for operator+admin
  (gen_random_uuid()::text, 'password_reset_console',      'operator',   'admin', 'single_approval', 60, 10, true),
  (gen_random_uuid()::text, 'password_reset_console',      'admin',      'admin', 'single_approval', 60, 10, true),
  (gen_random_uuid()::text, 'password_reset_console',      'superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- security_compliance_audit: security-sensitive, requires approval for operator+admin
  (gen_random_uuid()::text, 'security_compliance_audit',   'operator',   'admin', 'single_approval', 60, 20, true),
  (gen_random_uuid()::text, 'security_compliance_audit',   'admin',      'admin', 'single_approval', 60, 20, true),
  (gen_random_uuid()::text, 'security_compliance_audit',   'superadmin', 'admin', 'auto_approve',    60, 50, true),
  -- user_last_login: read-only report, auto-approve for all
  (gen_random_uuid()::text, 'user_last_login',             'operator',   'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'user_last_login',             'admin',      'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'user_last_login',             'superadmin', 'admin', 'auto_approve',    60, 50, true)
ON CONFLICT DO NOTHING;
