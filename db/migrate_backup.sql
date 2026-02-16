-- =====================================================================
-- MIGRATION: Database Backup Management Tables
-- Run this against existing databases to add backup support.
-- For fresh installs, these tables are created by init.sql.
-- =====================================================================

-- Backup configuration (single-row table, edited via UI)
CREATE TABLE IF NOT EXISTS backup_config (
    id                  SERIAL PRIMARY KEY,
    enabled             BOOLEAN NOT NULL DEFAULT false,
    nfs_path            TEXT NOT NULL DEFAULT '/backups',
    schedule_type       TEXT NOT NULL DEFAULT 'manual'
                        CHECK (schedule_type IN ('manual', 'daily', 'weekly')),
    schedule_time_utc   TEXT NOT NULL DEFAULT '02:00',
    schedule_day_of_week INT NOT NULL DEFAULT 0
                        CHECK (schedule_day_of_week BETWEEN 0 AND 6),
    retention_count     INT NOT NULL DEFAULT 7
                        CHECK (retention_count >= 1),
    retention_days      INT NOT NULL DEFAULT 30
                        CHECK (retention_days >= 1),
    last_backup_at      TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default config row if none exists
INSERT INTO backup_config (enabled, nfs_path, schedule_type, schedule_time_utc, retention_count, retention_days)
SELECT false, '/backups', 'manual', '02:00', 7, 30
WHERE NOT EXISTS (SELECT 1 FROM backup_config LIMIT 1);

-- Backup history / job log
CREATE TABLE IF NOT EXISTS backup_history (
    id              SERIAL PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'deleted')),
    backup_type     TEXT NOT NULL DEFAULT 'manual'
                    CHECK (backup_type IN ('manual', 'scheduled', 'restore')),
    file_name       TEXT,
    file_path       TEXT,
    file_size_bytes BIGINT,
    duration_seconds FLOAT,
    initiated_by    TEXT,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backup_history_status ON backup_history(status);
CREATE INDEX IF NOT EXISTS idx_backup_history_created ON backup_history(created_at DESC);

-- RBAC permissions for backup management
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'backup', 'read'),
('admin', 'backup', 'write'),
('superadmin', 'backup', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
