-- =============================================================================
-- v2.8.0: Retire _ensure_tables() — move all inline DDL into proper SQL files
-- =============================================================================
-- This migration covers two groups of tables that were previously created
-- exclusively via _ensure_tables() calls inside route modules, making fresh
-- installs non-deterministic.  With this migration, run_migration.py handles
-- them idempotently on every deployment.
--
-- All statements use CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS —
-- fully idempotent on existing installs.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Bulk Customer Onboarding tables
--    (previously inline in api/onboarding_routes.py _ensure_tables())
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS onboarding_batches (
    id                  SERIAL PRIMARY KEY,
    batch_id            UUID NOT NULL DEFAULT gen_random_uuid(),
    batch_name          TEXT NOT NULL,
    uploaded_by         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'validating',
    validation_errors   JSONB DEFAULT '[]'::jsonb,
    dry_run_result      JSONB,
    approval_status     TEXT DEFAULT 'not_submitted',
    approved_by         TEXT,
    approved_at         TIMESTAMPTZ,
    rejection_comment   TEXT,
    execution_result    JSONB,
    total_customers     INT DEFAULT 0,
    total_projects      INT DEFAULT 0,
    total_networks      INT DEFAULT 0,
    total_users         INT DEFAULT 0,
    execution_log       JSONB DEFAULT '[]'::jsonb,
    rerun_count         INT DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_onboarding_batches_batch_id
    ON onboarding_batches (batch_id);

CREATE TABLE IF NOT EXISTS onboarding_customers (
    id              SERIAL PRIMARY KEY,
    batch_id        UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    domain_name     TEXT NOT NULL,
    display_name    TEXT,
    description     TEXT,
    contact_email   TEXT,
    department_tag  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    pcd_domain_id   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_customers_batch
    ON onboarding_customers (batch_id);

CREATE TABLE IF NOT EXISTS onboarding_projects (
    id                      SERIAL PRIMARY KEY,
    batch_id                UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    customer_id             INT REFERENCES onboarding_customers(id) ON DELETE CASCADE,
    domain_name             TEXT NOT NULL,
    project_name            TEXT NOT NULL,
    subscription_id         TEXT DEFAULT '',
    description             TEXT,
    quota_vcpu              INT DEFAULT 20,
    quota_ram_mb            INT DEFAULT 51200,
    quota_instances         INT DEFAULT 10,
    quota_server_groups     INT DEFAULT 10,
    quota_networks          INT DEFAULT 10,
    quota_subnets           INT DEFAULT 20,
    quota_routers           INT DEFAULT 5,
    quota_ports             INT DEFAULT 200,
    quota_floatingips       INT DEFAULT 20,
    quota_security_groups   INT DEFAULT 10,
    quota_volumes           INT DEFAULT 20,
    quota_snapshots         INT DEFAULT 20,
    quota_disk_gb           INT DEFAULT 1000,
    status                  TEXT NOT NULL DEFAULT 'pending',
    error_msg               TEXT,
    pcd_project_id          TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_projects_batch
    ON onboarding_projects (batch_id);

CREATE TABLE IF NOT EXISTS onboarding_networks (
    id                      SERIAL PRIMARY KEY,
    batch_id                UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    project_id              INT REFERENCES onboarding_projects(id) ON DELETE CASCADE,
    domain_name             TEXT NOT NULL,
    project_name            TEXT NOT NULL,
    network_name            TEXT NOT NULL,
    network_kind            TEXT DEFAULT 'physical_managed',
    network_type            TEXT DEFAULT 'vlan',
    physical_network        TEXT DEFAULT 'physnet1',
    cidr                    TEXT,
    gateway                 TEXT,
    dns1                    TEXT DEFAULT '8.8.8.8',
    vlan_id                 INT,
    dhcp_enabled            BOOLEAN DEFAULT TRUE,
    is_external             BOOLEAN DEFAULT FALSE,
    shared                  BOOLEAN DEFAULT FALSE,
    allocation_pool_start   TEXT,
    allocation_pool_end     TEXT,
    status                  TEXT NOT NULL DEFAULT 'pending',
    error_msg               TEXT,
    pcd_network_id          TEXT,
    pcd_subnet_id           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_networks_batch
    ON onboarding_networks (batch_id);

CREATE TABLE IF NOT EXISTS onboarding_users (
    id                  SERIAL PRIMARY KEY,
    batch_id            UUID NOT NULL REFERENCES onboarding_batches(batch_id) ON DELETE CASCADE,
    project_id          INT REFERENCES onboarding_projects(id) ON DELETE CASCADE,
    domain_name         TEXT NOT NULL,
    project_name        TEXT NOT NULL,
    username            TEXT NOT NULL,
    email               TEXT,
    role                TEXT NOT NULL DEFAULT 'member',
    user_password       TEXT,
    send_welcome_email  BOOLEAN DEFAULT TRUE,
    status              TEXT NOT NULL DEFAULT 'pending',
    error_msg           TEXT,
    pcd_user_id         TEXT,
    temp_password       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_users_batch
    ON onboarding_users (batch_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Migration Flavor Staging table
--    (previously inline in api/migration_routes.py _ensure_phase4_tables()
--     referencing the never-committed db/migrate_phase4_preparation.sql)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS migration_flavor_staging (
    id                  SERIAL PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    source_shape        TEXT NOT NULL,
    vcpus               INTEGER NOT NULL,
    ram_mb              INTEGER NOT NULL,
    disk_gb             INTEGER NOT NULL,
    target_flavor_name  TEXT,
    pcd_flavor_id       TEXT,
    vm_count            INTEGER DEFAULT 0,
    confirmed           BOOLEAN DEFAULT FALSE,
    skip                BOOLEAN DEFAULT FALSE,
    existing_flavor_id  TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, source_shape)
);
CREATE INDEX IF NOT EXISTS idx_flavor_staging_project
    ON migration_flavor_staging (project_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. VM Provisioning tables
--    (previously inline in api/vm_provisioning_routes.py _ensure_tables())
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS vm_provisioning_batches (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'validated',
    approval_status TEXT NOT NULL DEFAULT 'pending_approval',
    require_approval BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      TEXT,
    domain_name     TEXT NOT NULL,
    project_name    TEXT NOT NULL,
    dry_run_results JSONB,
    region_id       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vm_provisioning_vms (
    id              SERIAL PRIMARY KEY,
    batch_id        INTEGER NOT NULL REFERENCES vm_provisioning_batches(id) ON DELETE CASCADE,
    vm_name_suffix  TEXT NOT NULL,
    count           INTEGER NOT NULL DEFAULT 1,
    image_name      TEXT,
    image_id        TEXT,
    flavor_name     TEXT,
    flavor_id       TEXT,
    volume_gb       INTEGER NOT NULL DEFAULT 20,
    network_name    TEXT,
    network_id      TEXT,
    security_groups JSONB DEFAULT '[]',
    fixed_ip        TEXT,
    hostname        TEXT,
    os_username     TEXT NOT NULL,
    os_password     TEXT NOT NULL,
    extra_cloudinit TEXT,
    os_type         TEXT NOT NULL DEFAULT 'linux',
    delete_on_termination BOOLEAN NOT NULL DEFAULT TRUE,
    pcd_server_ids  JSONB DEFAULT '[]',
    assigned_ips    JSONB DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    error_msg       TEXT,
    console_log     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
