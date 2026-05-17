-- =============================================================================
-- v2.0.0 – vJailbreak Execution Feedback Loop schema
-- =============================================================================
-- Adds:
--   1. migration_webhook_events table – receives event callbacks from vJailbreak
--   2. webhook_secret column on migration_projects
--   3. migration_status, failure_reason, migrated_at columns on migration_vms
-- =============================================================================

-- 1. Webhook events log
CREATE TABLE IF NOT EXISTS migration_webhook_events (
    id           BIGSERIAL PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type   TEXT NOT NULL,
    vm_id        TEXT,
    wave_id      INTEGER,
    payload      JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_mwe_project_received
    ON migration_webhook_events(project_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_mwe_project_event
    ON migration_webhook_events(project_id, event_type);

-- 2. Webhook secret on projects (HMAC key for vJailbreak callbacks)
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS webhook_secret TEXT;

-- 3. Per-VM execution state
ALTER TABLE migration_vms
    ADD COLUMN IF NOT EXISTS migration_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE migration_vms
    ADD COLUMN IF NOT EXISTS failure_reason TEXT;

ALTER TABLE migration_vms
    ADD COLUMN IF NOT EXISTS migrated_at TIMESTAMPTZ;
