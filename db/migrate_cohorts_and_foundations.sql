-- =============================================================================
-- Phase 2.10: Pre-Phase 3 Foundations
-- Migration Cohorts, VM Status, Mode Override, Dependencies,
-- Network Mappings, Tenant Priority, Tenant Readiness
-- =============================================================================
-- Idempotent: safe to run multiple times on an existing installation.
-- Run after all previous migrations.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 2.10B: Per-VM Migration Status
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vms' AND column_name='migration_status'
    ) THEN
        ALTER TABLE migration_vms ADD COLUMN migration_status VARCHAR DEFAULT 'not_started';
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vms' AND column_name='migration_status_note'
    ) THEN
        ALTER TABLE migration_vms ADD COLUMN migration_status_note TEXT;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vms' AND column_name='migration_status_updated_at'
    ) THEN
        ALTER TABLE migration_vms ADD COLUMN migration_status_updated_at TIMESTAMPTZ;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vms' AND column_name='migration_status_updated_by'
    ) THEN
        ALTER TABLE migration_vms ADD COLUMN migration_status_updated_by TEXT;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2.10C: Per-VM Migration Mode Override
-- NULL = use engine classification; 'warm' or 'cold' = operator forced
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_vms' AND column_name='migration_mode_override'
    ) THEN
        ALTER TABLE migration_vms ADD COLUMN migration_mode_override VARCHAR;
    END IF;
END $$;

-- Note: manual_mode_override column (earlier Phase) is retained for backwards compat.
-- migration_mode_override is the canonical Phase 2.10 column.

-- ---------------------------------------------------------------------------
-- 2.10D: Tenant Migration Priority
-- Lower integer = higher priority (runs earlier / assigned to first cohort)
-- Default 999 = unset / low priority
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_tenants' AND column_name='migration_priority'
    ) THEN
        ALTER TABLE migration_tenants ADD COLUMN migration_priority INTEGER DEFAULT 999;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2.10G: Migration Cohorts
-- Grouping layer between project and waves.
-- Hierarchy: migration_projects → migration_cohorts → migration_tenants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migration_cohorts (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    cohort_order INTEGER DEFAULT 999,       -- execution sequence (1 = first)
    status VARCHAR DEFAULT 'planning',      -- planning|ready|executing|complete|paused
    scheduled_start DATE,
    scheduled_end DATE,
    owner_name TEXT,                        -- team/person responsible
    depends_on_cohort_id INTEGER REFERENCES migration_cohorts(id) ON DELETE SET NULL,
    overcommit_profile_override TEXT,       -- optional: override project profile for this cohort
    agent_slots_override INTEGER,           -- optional: restrict concurrency for this cohort
    notes TEXT,
    approved_at TIMESTAMPTZ,
    approved_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- cohort_id on migration_tenants — NULL = unassigned (no cohorts configured)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='migration_tenants' AND column_name='cohort_id'
    ) THEN
        ALTER TABLE migration_tenants ADD COLUMN cohort_id INTEGER REFERENCES migration_cohorts(id) ON DELETE SET NULL;
    END IF;
END $$;

-- Index for cohort lookups
CREATE INDEX IF NOT EXISTS idx_migration_tenants_cohort ON migration_tenants(cohort_id);
CREATE INDEX IF NOT EXISTS idx_migration_cohorts_project ON migration_cohorts(project_id);
CREATE INDEX IF NOT EXISTS idx_migration_cohorts_order ON migration_cohorts(project_id, cohort_order);

-- ---------------------------------------------------------------------------
-- 2.10E: VM Dependency Annotations
-- VM A must complete before VM B can start migration.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migration_vm_dependencies (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    vm_id INTEGER NOT NULL REFERENCES migration_vms(id) ON DELETE CASCADE,
    depends_on_vm_id INTEGER NOT NULL REFERENCES migration_vms(id) ON DELETE CASCADE,
    dependency_type VARCHAR DEFAULT 'must_complete_before',  -- extensible future types
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(vm_id, depends_on_vm_id)
);

CREATE INDEX IF NOT EXISTS idx_migration_vm_deps_vm ON migration_vm_dependencies(vm_id);
CREATE INDEX IF NOT EXISTS idx_migration_vm_deps_depends_on ON migration_vm_dependencies(depends_on_vm_id);
CREATE INDEX IF NOT EXISTS idx_migration_vm_deps_project ON migration_vm_dependencies(project_id);

-- ---------------------------------------------------------------------------
-- 2.10F: Source Network → PCD Network Mapping
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migration_network_mappings (
    id SERIAL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    source_network_name TEXT NOT NULL,
    target_network_name TEXT,               -- NULL = unmapped (needs attention)
    target_network_id TEXT,                 -- PCD UUID if known
    vlan_id INTEGER,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, source_network_name)
);

CREATE INDEX IF NOT EXISTS idx_migration_net_mappings_project ON migration_network_mappings(project_id);

-- ---------------------------------------------------------------------------
-- 2.10H: Per-Tenant Readiness Checks
-- Auto-computed checks before waves start for each tenant.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS migration_tenant_readiness (
    id SERIAL PRIMARY KEY,
    tenant_id INTEGER NOT NULL REFERENCES migration_tenants(id) ON DELETE CASCADE,
    check_name TEXT NOT NULL,              -- 'target_mapped', 'network_mapped', etc.
    check_status VARCHAR DEFAULT 'pending', -- pending|pass|fail|skipped
    checked_at TIMESTAMPTZ,
    notes TEXT,
    UNIQUE(tenant_id, check_name)
);

CREATE INDEX IF NOT EXISTS idx_migration_tenant_readiness_tenant ON migration_tenant_readiness(tenant_id);

-- ---------------------------------------------------------------------------
-- Audit trail: log new tables for activity
-- ---------------------------------------------------------------------------
-- (activity log table already exists; no schema changes needed)
