-- Migration: Snapshot Quota-Aware Batching (v1.26.0)
-- Adds quota pre-check, tenant-grouped batching, progress tracking, and
-- quota-blocked status to snapshot compliance.

-- =====================================================================
-- 1. Extend snapshot_runs with batch progress columns
-- =====================================================================
ALTER TABLE snapshot_runs
    ADD COLUMN IF NOT EXISTS total_batches       INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS completed_batches   INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS current_batch       INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS quota_blocked       INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS batch_size_config   INTEGER DEFAULT 20,
    ADD COLUMN IF NOT EXISTS batch_delay_sec     NUMERIC(5,1) DEFAULT 5.0,
    ADD COLUMN IF NOT EXISTS progress_pct        NUMERIC(5,1) DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS estimated_finish_at TIMESTAMPTZ;

-- =====================================================================
-- 2. Table for per-batch tracking (progress UI)
-- =====================================================================
CREATE TABLE IF NOT EXISTS snapshot_run_batches (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_run_id BIGINT NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
    batch_number    INTEGER NOT NULL,
    tenant_ids      TEXT[] NOT NULL,             -- project IDs in this batch
    tenant_names    TEXT[],                      -- human-readable names
    total_volumes   INTEGER DEFAULT 0,
    completed       INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    quota_blocked   INTEGER DEFAULT 0,
    status          VARCHAR(30) DEFAULT 'pending', -- pending, running, completed, failed
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (snapshot_run_id, batch_number)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_run_batches_run
    ON snapshot_run_batches (snapshot_run_id);

-- =====================================================================
-- 3. Table for quota-blocked volume records
-- =====================================================================
CREATE TABLE IF NOT EXISTS snapshot_quota_blocks (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_run_id BIGINT REFERENCES snapshot_runs(id) ON DELETE CASCADE,
    volume_id       TEXT NOT NULL,
    volume_name     TEXT,
    volume_size_gb  INTEGER,
    tenant_id       TEXT NOT NULL,
    tenant_name     TEXT,
    project_id      TEXT NOT NULL,
    project_name    TEXT,
    policy_name     VARCHAR(100),
    quota_limit_gb  INTEGER,
    quota_used_gb   INTEGER,
    quota_needed_gb INTEGER,       -- how much extra quota is needed
    snapshot_quota_limit INTEGER,
    snapshot_quota_used  INTEGER,
    block_reason    TEXT,           -- gigabytes_exceeded | snapshots_exceeded
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_snapshot_quota_blocks_run
    ON snapshot_quota_blocks (snapshot_run_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_quota_blocks_tenant
    ON snapshot_quota_blocks (tenant_id);

-- =====================================================================
-- 4. Runbook: snapshot_quota_forecast
-- =====================================================================
INSERT INTO runbooks (runbook_id, name, display_name, description, category, risk_level, supports_dry_run, enabled, parameters_schema)
VALUES
  (gen_random_uuid()::text, 'snapshot_quota_forecast', 'Snapshot Quota Forecast',
   'Proactive daily check: for each tenant, compare current volume sizes and snapshot policies against Cinder quotas. Identifies tenants where the next snapshot cycle will fail due to insufficient gigabyte or snapshot-count quota. Recommends exact quota increases needed.',
   'security', 'low', false, true,
   '{"type":"object","properties":{"include_pending_policies":{"type":"boolean","default":true,"description":"Include volumes with assigned policies even if auto_snapshot is not yet enabled"},"safety_margin_pct":{"type":"integer","default":10,"description":"Extra headroom % to add when calculating if quota is sufficient"}}}'::jsonb)
ON CONFLICT (name) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  description = EXCLUDED.description,
  category = EXCLUDED.category,
  risk_level = EXCLUDED.risk_level,
  supports_dry_run = EXCLUDED.supports_dry_run,
  parameters_schema = EXCLUDED.parameters_schema,
  updated_at = now();

-- Approval policies: read-only, auto-approve for all roles
INSERT INTO runbook_approval_policies (policy_id, runbook_name, trigger_role, approver_role, approval_mode, escalation_timeout_minutes, max_auto_executions_per_day, enabled)
VALUES
  (gen_random_uuid()::text, 'snapshot_quota_forecast', 'operator',   'admin', 'auto_approve', 60, 50, true),
  (gen_random_uuid()::text, 'snapshot_quota_forecast', 'admin',      'admin', 'auto_approve', 60, 50, true),
  (gen_random_uuid()::text, 'snapshot_quota_forecast', 'superadmin', 'admin', 'auto_approve', 60, 50, true)
ON CONFLICT DO NOTHING;
