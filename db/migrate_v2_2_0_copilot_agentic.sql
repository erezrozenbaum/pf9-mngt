-- Migration: v2.2.0 — Copilot Agentic Execution
-- Creates copilot_execution_log table and system settings for agentic control.
-- Run this once against pf9_mgmt database.

-- ── Audit table for Copilot-triggered runbook executions ─────────────────────
CREATE TABLE IF NOT EXISTS copilot_execution_log (
    id           BIGSERIAL    PRIMARY KEY,
    username     VARCHAR(255) NOT NULL,
    intent_key   VARCHAR(100) NOT NULL,
    runbook_name VARCHAR(100) NOT NULL,
    execution_id TEXT,
    dry_run      BOOLEAN      NOT NULL DEFAULT true,
    executed_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_copilot_exec_log_user_ts
    ON copilot_execution_log (username, executed_at DESC);

-- ── System settings ───────────────────────────────────────────────────────────
INSERT INTO system_settings (key, value, description) VALUES
  ('copilot.agentic_enabled',
   'true',
   'Allow Copilot to trigger runbook executions. Set to false to disable agentic mode platform-wide.'),
  ('copilot.execution_quota_per_hour',
   '10',
   'Maximum number of runbook executions a single user can trigger via Copilot per hour.')
ON CONFLICT (key) DO NOTHING;

-- ── Schema version record ─────────────────────────────────────────────────────
INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v2_2_0_copilot_agentic.sql', now())
ON CONFLICT DO NOTHING;
