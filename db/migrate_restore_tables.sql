-- =====================================================================
-- MIGRATION: Add Snapshot Restore tables and RBAC permissions
-- Safe to run on an existing database — all statements are idempotent.
-- Run: docker exec -i pf9_db psql -U <user> -d <db> -f /dev/stdin < db/migrate_restore_tables.sql
-- =====================================================================

BEGIN;

-- 1. RBAC permissions for the restore resource
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',    'restore', 'read'),
    ('operator',  'restore', 'read'),
    ('admin',     'restore', 'write'),
    ('superadmin', 'restore', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- 2. Restore jobs table
CREATE TABLE IF NOT EXISTS restore_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by VARCHAR(255) NOT NULL,
    executed_by VARCHAR(255),
    project_id TEXT NOT NULL,
    project_name TEXT,
    vm_id TEXT NOT NULL,
    vm_name TEXT,
    restore_point_id TEXT NOT NULL,
    restore_point_name TEXT,
    mode VARCHAR(20) NOT NULL DEFAULT 'NEW',
    ip_strategy VARCHAR(30) NOT NULL DEFAULT 'NEW_IPS',
    requested_name TEXT,
    boot_mode VARCHAR(30) NOT NULL DEFAULT 'BOOT_FROM_VOLUME',
    status VARCHAR(30) NOT NULL DEFAULT 'PLANNED',
    plan_json JSONB NOT NULL,
    result_json JSONB,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_heartbeat TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ
);

-- 3. Indexes on restore_jobs
CREATE INDEX IF NOT EXISTS idx_restore_jobs_project    ON restore_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_vm         ON restore_jobs(vm_id);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_status     ON restore_jobs(status);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_created_at ON restore_jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_created_by ON restore_jobs(created_by);

-- Concurrency guard: only one PENDING/RUNNING restore per VM
CREATE UNIQUE INDEX IF NOT EXISTS idx_restore_jobs_vm_running
    ON restore_jobs(vm_id) WHERE status IN ('PENDING', 'RUNNING');

-- 4. Restore job steps table
CREATE TABLE IF NOT EXISTS restore_job_steps (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES restore_jobs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_name VARCHAR(60) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    details_json JSONB,
    error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_restore_job_steps_job    ON restore_job_steps(job_id);
CREATE INDEX IF NOT EXISTS idx_restore_job_steps_status ON restore_job_steps(status);

COMMIT;

-- Verification
SELECT 'restore_jobs' AS table_name, COUNT(*) AS row_count FROM restore_jobs
UNION ALL
SELECT 'restore_job_steps', COUNT(*) FROM restore_job_steps
UNION ALL
SELECT 'restore_permissions', COUNT(*) FROM role_permissions WHERE resource = 'restore';
