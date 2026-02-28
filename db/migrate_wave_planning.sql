-- =============================================================================
-- Phase 3: Migration Wave Planning
-- Extends existing migration_waves + migration_wave_vms tables (from Phase 1)
-- Adds per-wave pre-flight checklist table
-- =============================================================================
-- Idempotent: safe to run multiple times on an existing installation.
-- Run after migrate_cohorts_and_foundations.sql
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 3A: Extend migration_waves
-- ---------------------------------------------------------------------------

-- Link wave to a cohort (nullable = project-level wave with no cohort)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='cohort_id'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN cohort_id INTEGER REFERENCES migration_cohorts(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='status'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN status VARCHAR DEFAULT 'planned'
            CHECK (status IN ('planned','pre_checks_passed','executing','validating','complete','failed','cancelled'));
    END IF;
END $$;

-- pilot | regular | cleanup
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='wave_type'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN wave_type VARCHAR DEFAULT 'regular'
            CHECK (wave_type IN ('pilot','regular','cleanup'));
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='agent_slots_override'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN agent_slots_override INTEGER;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='scheduled_start'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN scheduled_start DATE;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='scheduled_end'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN scheduled_end DATE;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='owner_name'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN owner_name TEXT;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='notes'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN notes TEXT;
    END IF;
END $$;

-- execution timestamps
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='started_at'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN started_at TIMESTAMPTZ;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_waves' AND column_name='completed_at'
    ) THEN
        ALTER TABLE migration_waves ADD COLUMN completed_at TIMESTAMPTZ;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_mig_waves_cohort ON migration_waves(cohort_id);

-- ---------------------------------------------------------------------------
-- 3B: Extend migration_wave_vms
-- ---------------------------------------------------------------------------

-- vm_id FK to migration_vms (preferred, replaces vm_name for new entries)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_wave_vms' AND column_name='vm_id'
    ) THEN
        ALTER TABLE migration_wave_vms ADD COLUMN vm_id INTEGER REFERENCES migration_vms(id) ON DELETE CASCADE;
    END IF;
END $$;

-- order within the wave (for dependency-respecting sequencing)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_wave_vms' AND column_name='migration_order'
    ) THEN
        ALTER TABLE migration_wave_vms ADD COLUMN migration_order INTEGER DEFAULT 0;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_wave_vms' AND column_name='assigned_at'
    ) THEN
        ALTER TABLE migration_wave_vms ADD COLUMN assigned_at TIMESTAMPTZ DEFAULT now();
    END IF;
END $$;

-- per-VM status within the wave (more granular than vm-level migration_status)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_wave_vms' AND column_name='wave_vm_status'
    ) THEN
        ALTER TABLE migration_wave_vms ADD COLUMN wave_vm_status VARCHAR DEFAULT 'pending'
            CHECK (wave_vm_status IN ('pending','in_progress','complete','failed','skipped'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_mig_wave_vms_vm_id ON migration_wave_vms(vm_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mig_wave_vms_unique ON migration_wave_vms(project_id, vm_id)
    WHERE vm_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3C: Per-wave pre-flight checklist
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migration_wave_preflights (
    id              SERIAL PRIMARY KEY,
    wave_id         BIGINT NOT NULL REFERENCES migration_waves(id) ON DELETE CASCADE,
    check_name      TEXT NOT NULL,
    check_label     TEXT NOT NULL,
    check_status    VARCHAR DEFAULT 'pending'
        CHECK (check_status IN ('pending','pass','fail','skipped','na')),
    severity        VARCHAR DEFAULT 'warning'
        CHECK (severity IN ('info','warning','blocker')),
    notes           TEXT,
    checked_at      TIMESTAMPTZ,
    checked_by      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (wave_id, check_name)
);

CREATE INDEX IF NOT EXISTS idx_wave_preflights_wave ON migration_wave_preflights(wave_id);
