-- =============================================================================
-- Migration Planner Phase 4D (v1.43.0)
-- Users UX Overhaul + vJailbreak Auto-Push
-- =============================================================================
-- Idempotent: safe to run multiple times.

-- 1. vJailbreak connection settings on migration_projects
ALTER TABLE migration_projects
    ADD COLUMN IF NOT EXISTS vjb_api_url      TEXT,
    ADD COLUMN IF NOT EXISTS vjb_namespace    TEXT DEFAULT 'migration',
    ADD COLUMN IF NOT EXISTS vjb_bearer_token TEXT;

-- 2. vJailbreak push task log
CREATE TABLE IF NOT EXISTS migration_vjailbreak_push_tasks (
    id             SERIAL PRIMARY KEY,
    project_id     TEXT        NOT NULL,
    cohort_id      INTEGER,
    tenant_name    TEXT,
    resource_type  TEXT        NOT NULL,   -- 'openstackcreds' | 'networkmappings' | 'vmwarecreds'
    resource_name  TEXT,
    status         VARCHAR(32) DEFAULT 'pending', -- pending | done | skipped | failed
    error_message  TEXT,
    pushed_by      TEXT,
    pushed_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_vjb_project FOREIGN KEY (project_id)
        REFERENCES migration_projects(project_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vjb_tasks_project
    ON migration_vjailbreak_push_tasks(project_id);
