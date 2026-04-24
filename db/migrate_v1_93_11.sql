-- v1.93.11: Fix users_history.name NOT NULL constraint
-- OpenStack can return users with no name (service accounts, etc.), which caused
-- a NotNullViolation that aborted the inventory transaction and broke all
-- subsequent rvtools sync runs.

ALTER TABLE users_history ALTER COLUMN name DROP NOT NULL;

-- v1.93.11: Grant SELECT on hypervisors to tenant_portal_role
-- The tenant portal DB allocation fallback JOINs servers → hypervisors to estimate
-- cpu_pct and memory_pct. Without this grant the JOIN raises a permission error
-- that is silently caught, leaving the allocation path with zero rows and the
-- Current Usage tab empty even when VMs are present.
GRANT SELECT ON hypervisors TO tenant_portal_role;

-- v1.93.11: Add compatibility alias column pf9_regions.enabled → is_enabled
-- The v1.93.10 db_writer.py referenced "WHERE enabled = TRUE" which threw
-- UndefinedColumn, silently aborting the PostgreSQL transaction before
-- upsert_servers ran. The generated column makes both names work, so old
-- and new code are both safe across rolling deployments.
ALTER TABLE pf9_regions ADD COLUMN IF NOT EXISTS enabled boolean GENERATED ALWAYS AS (is_enabled) STORED;

-- v1.93.11: Insert default alert rule settings
-- New system_settings keys drive the rvtools failure alert emails sent from
-- the scheduler worker when consecutive failures exceed the threshold.
INSERT INTO system_settings (key, value, description) VALUES
  ('alert.rvtools_enabled',           'true',  'Enable rvtools failure alert emails'),
  ('alert.rvtools_recipients',        '',       'Comma-separated email addresses for rvtools alerts'),
  ('alert.rvtools_failure_threshold', '3',      'Number of consecutive failures before sending an alert'),
  ('alert.rvtools_recovery_enabled',  'true',   'Send a recovery email when rvtools succeeds after failures'),
  ('alert.rvtools_in_alert_state',    'false',  'Auto-managed: true while consecutive failures >= threshold'),
  ('alert.rvtools_last_alert_run_id', '',       'Auto-managed: run ID when last alert email was sent')
ON CONFLICT (key) DO NOTHING;
