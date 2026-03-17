-- =============================================================================
-- Phase T: Migration Planner v1.67
-- Wave Approval Gates, Dependency Auto-Import, Maintenance Windows
-- =============================================================================
-- Idempotent: safe to run multiple times on an existing installation.
-- Run after migrate_wave_planning.sql
--
-- Apply:
--   docker exec -i pf9_db psql -U $POSTGRES_USER -d $POSTGRES_DB \
--     < db/migrate_wave_approvals.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- T.A: Wave Approval Gate columns on migration_waves
-- ---------------------------------------------------------------------------

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='approval_status'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN approval_status TEXT DEFAULT 'pending_approval';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='approved_by'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN approved_by TEXT;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='approved_at'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN approved_at TIMESTAMPTZ;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='approval_comment'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN approval_comment TEXT;
    END IF;
END $$;

-- Back-fill existing wave rows so they all start with a defined state
UPDATE migration_waves SET approval_status = 'pending_approval'
WHERE approval_status IS NULL;

-- ---------------------------------------------------------------------------
-- T.B: Dependency source and confidence on migration_vm_dependencies
-- ---------------------------------------------------------------------------

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vm_dependencies' AND column_name='dep_source'
    ) THEN
        ALTER TABLE migration_vm_dependencies
            ADD COLUMN dep_source TEXT DEFAULT 'manual';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vm_dependencies' AND column_name='confidence'
    ) THEN
        ALTER TABLE migration_vm_dependencies
            ADD COLUMN confidence NUMERIC(5,2) DEFAULT 1.0;
    END IF;
END $$;

-- Back-fill existing rows as manual / full confidence
UPDATE migration_vm_dependencies
SET dep_source = 'manual', confidence = 1.0
WHERE dep_source IS NULL;

-- ---------------------------------------------------------------------------
-- T.C: Maintenance windows table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS maintenance_windows (
    id              SERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    cohort_id       INTEGER REFERENCES migration_cohorts(id) ON DELETE SET NULL,
    label           TEXT NOT NULL,
    -- NULL day_of_week means "any day of the week"
    day_of_week     INTEGER CHECK (day_of_week BETWEEN 0 AND 6),
    start_time      TIME NOT NULL,
    end_time        TIME NOT NULL,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_maint_windows_project
    ON maintenance_windows(project_id);

CREATE INDEX IF NOT EXISTS idx_maint_windows_cohort
    ON maintenance_windows(cohort_id);

-- ---------------------------------------------------------------------------
-- T.C: use_maintenance_windows flag on migration_projects
-- ---------------------------------------------------------------------------

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_projects' AND column_name='use_maintenance_windows'
    ) THEN
        ALTER TABLE migration_projects
            ADD COLUMN use_maintenance_windows BOOLEAN NOT NULL DEFAULT false;
    END IF;
END $$;
