-- ============================================================
-- Migration Planner Phase 2: Tenant Scoping, Target Mapping
--                            Quota/Overcommit, Node Sizing
-- Idempotent — safe to re-run (IF NOT EXISTS, ADD COLUMN IF NOT EXISTS)
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- 2A — Tenant Exclusion & Scoping columns
-- ─────────────────────────────────────────────────────────────
ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS include_in_plan     BOOLEAN DEFAULT true;
ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS exclude_reason       TEXT;

-- ─────────────────────────────────────────────────────────────
-- 2B — Target Mapping columns
-- ─────────────────────────────────────────────────────────────
ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS target_domain_name    TEXT;
ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS target_project_name   TEXT;
ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS target_display_name   TEXT;

-- Back-fill from old target_domain / target_project if they were set
UPDATE migration_tenants
SET    target_domain_name  = target_domain,
       target_project_name = target_project
WHERE  target_domain_name IS NULL AND target_domain IS NOT NULL;

-- ─────────────────────────────────────────────────────────────
-- 2A — Pattern-based auto-exclude rules
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_tenant_filters (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    pattern         TEXT NOT NULL,       -- glob, e.g. "LAB-%" or "%-TEST"
    reason          TEXT,
    auto_exclude    BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, pattern)
);

CREATE INDEX IF NOT EXISTS idx_mig_tenant_filters_project ON migration_tenant_filters(project_id);

-- ─────────────────────────────────────────────────────────────
-- 2C — Overcommit profiles (seeded with 3 presets)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_overcommit_profiles (
    id                      BIGSERIAL PRIMARY KEY,
    profile_name            TEXT NOT NULL UNIQUE,
    display_name            TEXT NOT NULL,
    description             TEXT,
    cpu_ratio               NUMERIC(4,1) NOT NULL DEFAULT 4.0,   -- e.g. 4:1
    ram_ratio               NUMERIC(4,2) NOT NULL DEFAULT 1.5,   -- e.g. 1.5:1
    disk_snapshot_factor    NUMERIC(4,2) NOT NULL DEFAULT 1.5,   -- disk * factor for quota
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO migration_overcommit_profiles (profile_name, display_name, description, cpu_ratio, ram_ratio, disk_snapshot_factor)
VALUES
  ('aggressive',   'Aggressive',   'High density: 8:1 CPU, 2:1 RAM, 1.3× disk. Best for dev/test workloads.', 8.0, 2.0, 1.3),
  ('balanced',     'Balanced',     'Typical production: 4:1 CPU, 1.5:1 RAM, 1.5× disk.', 4.0, 1.5, 1.5),
  ('conservative', 'Conservative', 'Low density / DB workloads: 2:1 CPU, 1:1 RAM, 2× disk.', 2.0, 1.0, 2.0)
ON CONFLICT (profile_name) DO NOTHING;

-- Per-project selected overcommit profile (default: balanced)
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS overcommit_profile_name TEXT DEFAULT 'balanced';

-- ─────────────────────────────────────────────────────────────
-- 2D — PCD hardware node profiles
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_pcd_node_profiles (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    profile_name        TEXT NOT NULL,
    cpu_cores           INTEGER NOT NULL DEFAULT 48,       -- physical cores per node
    cpu_threads         INTEGER NOT NULL DEFAULT 96,       -- SMT threads (HT on)
    ram_gb              NUMERIC(8,1) NOT NULL DEFAULT 384.0,
    storage_tb          NUMERIC(8,2) NOT NULL DEFAULT 20.0,
    max_cpu_util_pct    NUMERIC(5,1) DEFAULT 70.0,
    max_ram_util_pct    NUMERIC(5,1) DEFAULT 75.0,
    max_disk_util_pct   NUMERIC(5,1) DEFAULT 70.0,
    is_default          BOOLEAN DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, profile_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_node_profiles_project ON migration_pcd_node_profiles(project_id);

-- ─────────────────────────────────────────────────────────────
-- 2D — PCD node inventory (existing nodes in PCD cluster)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_pcd_node_inventory (
    id                  BIGSERIAL PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    profile_id          BIGINT REFERENCES migration_pcd_node_profiles(id) ON DELETE SET NULL,
    current_nodes       INTEGER NOT NULL DEFAULT 0,
    current_vcpu_used   INTEGER DEFAULT 0,
    current_ram_gb_used NUMERIC(10,2) DEFAULT 0,
    current_disk_tb_used NUMERIC(10,2) DEFAULT 0,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id)
);

CREATE INDEX IF NOT EXISTS idx_mig_node_inventory_project ON migration_pcd_node_inventory(project_id);

-- ─────────────────────────────────────────────────────────────
-- 2E — PCD gap analysis results
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_pcd_gaps (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    gap_type        TEXT NOT NULL,   -- flavor | network | image | security_group | quota
    resource_name   TEXT NOT NULL,
    tenant_name     TEXT,
    details         JSONB DEFAULT '{}',
    severity        TEXT DEFAULT 'warning',  -- info | warning | critical
    resolution      TEXT,
    resolved        BOOLEAN DEFAULT false,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, gap_type, resource_name, tenant_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_pcd_gaps_project ON migration_pcd_gaps(project_id);
CREATE INDEX IF NOT EXISTS idx_mig_pcd_gaps_resolved ON migration_pcd_gaps(project_id, resolved);

-- ─────────────────────────────────────────────────────────────
-- 2E — PCD connection settings per project
-- ─────────────────────────────────────────────────────────────
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS pcd_auth_url       TEXT;
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS pcd_username        TEXT;
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS pcd_password_hint   TEXT;   -- display only; actual creds from .env
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS pcd_region          TEXT DEFAULT 'region-one';
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS pcd_last_checked_at TIMESTAMPTZ;
ALTER TABLE migration_projects ADD COLUMN IF NOT EXISTS pcd_readiness_score NUMERIC(5,1);  -- 0–100
