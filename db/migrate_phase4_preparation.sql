-- ============================================================================
-- Migration Planner Phase 4A — Data Enrichment  (v1.35.0)
-- Idempotent: all ALTER TABLE use ADD COLUMN IF NOT EXISTS
--             all CREATE TABLE use IF NOT EXISTS
-- ============================================================================

-- ── 1. migration_network_mappings: subnet detail columns + network_kind ─────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'migration_network_mappings' AND column_name = 'network_kind'
    ) THEN
        ALTER TABLE migration_network_mappings
            ADD COLUMN network_kind              VARCHAR DEFAULT 'physical_managed',
            ADD COLUMN cidr                      TEXT,
            ADD COLUMN gateway_ip                TEXT,
            ADD COLUMN dns_nameservers           TEXT[],
            ADD COLUMN allocation_pool_start     TEXT,
            ADD COLUMN allocation_pool_end       TEXT,
            ADD COLUMN dhcp_enabled              BOOLEAN DEFAULT true,
            ADD COLUMN is_external               BOOLEAN DEFAULT false,
            ADD COLUMN subnet_details_confirmed  BOOLEAN DEFAULT false;

        -- Default: rows that already have a vlan_id are physical_managed (common case);
        -- rows with no vlan_id default to virtual.
        UPDATE migration_network_mappings
           SET network_kind = CASE WHEN vlan_id IS NOT NULL THEN 'physical_managed' ELSE 'virtual' END
         WHERE network_kind IS NULL OR network_kind = 'physical_managed';

        RAISE NOTICE 'Added subnet-detail columns + network_kind to migration_network_mappings';
    END IF;
END $$;

-- ── 2. migration_flavor_staging ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_flavor_staging (
    id                  SERIAL PRIMARY KEY,
    project_id          TEXT    NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    source_shape        TEXT    NOT NULL,          -- e.g. "4vCPU-8GB-50GB" (auto-label)
    vcpus               INTEGER NOT NULL,
    ram_mb              INTEGER NOT NULL,
    disk_gb             INTEGER NOT NULL,
    target_flavor_name  TEXT,                      -- operator edits this
    pcd_flavor_id       TEXT,                      -- filled after creation in Phase 4B
    vm_count            INTEGER DEFAULT 0,          -- VMs using this shape
    confirmed           BOOLEAN DEFAULT false,
    skip                BOOLEAN DEFAULT false,     -- map to existing flavor instead
    existing_flavor_id  TEXT,                      -- if skip=true, PCD flavor UUID to use
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, source_shape)
);

CREATE INDEX IF NOT EXISTS idx_flavor_staging_project
    ON migration_flavor_staging(project_id);

-- ── 3. migration_image_requirements ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_image_requirements (
    id                  SERIAL PRIMARY KEY,
    project_id          TEXT    NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    os_family           TEXT    NOT NULL,          -- 'windows', 'linux-ubuntu', 'linux-rhel', etc.
    os_version_hint     TEXT,                      -- e.g. "Windows Server 2019", "Ubuntu 22.04"
    vm_count            INTEGER DEFAULT 0,
    glance_image_id     TEXT,                      -- operator pastes Glance UUID after upload
    glance_image_name   TEXT,
    confirmed           BOOLEAN DEFAULT false,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (project_id, os_family)
);

CREATE INDEX IF NOT EXISTS idx_image_requirements_project
    ON migration_image_requirements(project_id);

-- ── 4. migration_tenant_users ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS migration_tenant_users (
    id                    SERIAL PRIMARY KEY,
    tenant_id             INTEGER NOT NULL REFERENCES migration_tenants(id) ON DELETE CASCADE,
    project_id            TEXT    NOT NULL,        -- denormalised for easy project-level queries
    user_type             VARCHAR NOT NULL,        -- 'service_account' | 'tenant_owner'
    username              TEXT    NOT NULL,
    email                 TEXT,
    role                  VARCHAR NOT NULL DEFAULT 'admin',  -- 'admin' | 'member' | 'reader'
    is_existing_user      BOOLEAN DEFAULT false,   -- true = user already exists in Keystone/LDAP
    temp_password         TEXT,                    -- stored encrypted; service accounts only
    password_must_change  BOOLEAN DEFAULT true,
    pcd_user_id           TEXT,                    -- PCD UUID — filled after creation in Phase 4B
    confirmed             BOOLEAN DEFAULT false,
    notes                 TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, username)
);

CREATE INDEX IF NOT EXISTS idx_migration_tenant_users_tenant
    ON migration_tenant_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_migration_tenant_users_project
    ON migration_tenant_users(project_id);
