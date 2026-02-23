-- Migration: Add 7 new operational runbooks
-- VM Health Quick Fix, Snapshot Before Escalation, Upgrade Opportunity Detector,
-- Monthly Executive Snapshot, Cost Leakage Report, Password Reset + Console,
-- Security & Compliance Audit

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
   'Scan tenants for upgrade opportunities: quota pressure, small flavors, old images. Estimates revenue impact.',
   'quota', 'low', false, true,
   '{"type":"object","properties":{"quota_threshold_pct":{"type":"integer","default":80,"description":"Quota usage % to flag"},"price_per_vcpu":{"type":"number","default":15.0,"description":"Monthly price per vCPU ($)"},"price_per_gb_ram":{"type":"number","default":5.0,"description":"Monthly price per GB RAM ($)"},"include_flavor_analysis":{"type":"boolean","default":true,"description":"Check for small/old flavors"},"include_image_analysis":{"type":"boolean","default":true,"description":"Check for old/deprecated images"}}}'::jsonb),

  (gen_random_uuid()::text, 'monthly_executive_snapshot', 'Monthly Executive Snapshot',
   'Generate an executive summary: total tenants, VMs, compliance %, capacity risk, revenue estimate, top risk tenants with month-over-month deltas.',
   'general', 'low', false, true,
   '{"type":"object","properties":{"price_per_vcpu":{"type":"number","default":15.0,"description":"Monthly price per vCPU ($)"},"price_per_gb_storage":{"type":"number","default":2.0,"description":"Monthly price per GB storage ($)"},"risk_top_n":{"type":"integer","default":5,"description":"Number of top risk tenants to show"},"include_deltas":{"type":"boolean","default":true,"description":"Include month-over-month deltas"}}}'::jsonb),

  (gen_random_uuid()::text, 'cost_leakage_report', 'Cost Leakage Report',
   'Detect idle VMs, detached volumes, unused floating IPs, and oversized instances. Calculates estimated monthly waste.',
   'general', 'low', false, true,
   '{"type":"object","properties":{"idle_cpu_threshold_pct":{"type":"integer","default":5,"description":"CPU % below which a VM is idle"},"shutoff_days_threshold":{"type":"integer","default":30,"description":"Days a VM must be SHUTOFF to flag"},"detached_volume_days":{"type":"integer","default":7,"description":"Days a volume must be detached to flag"},"price_per_vcpu_month":{"type":"number","default":15.0,"description":"Monthly price per vCPU ($)"},"price_per_gb_volume_month":{"type":"number","default":2.0,"description":"Monthly price per GB volume ($)"},"price_per_floating_ip_month":{"type":"number","default":5.0,"description":"Monthly price per floating IP ($)"}}}'::jsonb),

  (gen_random_uuid()::text, 'password_reset_console', 'Password Reset + Console Access',
   'Reset a VM password via metadata injection and enable temporary console access. Logs full audit trail.',
   'vm', 'high', true, true,
   '{"type":"object","properties":{"server_id":{"type":"string","description":"ID of the VM"},"new_password":{"type":"string","default":"","description":"New password (auto-generated if blank)"},"enable_console":{"type":"boolean","default":true,"description":"Enable VNC/SPICE console"},"console_expiry_minutes":{"type":"integer","default":30,"description":"Console link expiry in minutes"}},"required":["server_id"]}'::jsonb),

  (gen_random_uuid()::text, 'security_compliance_audit', 'Security & Compliance Audit',
   'Comprehensive audit: overly permissive security groups, stale users with no recent activity, unencrypted volumes.',
   'security', 'low', false, true,
   '{"type":"object","properties":{"stale_user_days":{"type":"integer","default":90,"description":"Days of inactivity to flag a user as stale"},"flag_wide_port_ranges":{"type":"boolean","default":true,"description":"Flag rules with 0-65535 port ranges"},"check_volume_encryption":{"type":"boolean","default":true,"description":"Check for unencrypted volumes"}}}'::jsonb)

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
-- Medium/Low risk: operator triggers, auto-approved
-- High risk (password_reset_console): operator triggers, admin must approve
-- =====================================================================

INSERT INTO runbook_approval_policies (policy_id, runbook_name, trigger_role, approver_role, approval_mode, escalation_timeout_minutes, max_auto_executions_per_day, enabled)
VALUES
  (gen_random_uuid()::text, 'vm_health_quickfix',          'operator', 'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'snapshot_before_escalation',  'operator', 'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'upgrade_opportunity_detector','operator', 'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'monthly_executive_snapshot',  'operator', 'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'cost_leakage_report',         'operator', 'admin', 'auto_approve',    60, 50, true),
  (gen_random_uuid()::text, 'password_reset_console',      'operator', 'admin', 'single_approval', 60, 10, true),
  (gen_random_uuid()::text, 'security_compliance_audit',   'operator', 'admin', 'auto_approve',    60, 50, true)
ON CONFLICT DO NOTHING;
