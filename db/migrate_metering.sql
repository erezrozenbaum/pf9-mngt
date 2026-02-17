-- =====================================================================
-- Migration: Operational Metering Tables
-- Version:  1.15.0
-- =====================================================================

-- ---------------------------------------------------------------------------
-- metering_config – single-row global metering settings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_config (
    id                       INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    enabled                  BOOLEAN NOT NULL DEFAULT TRUE,
    collection_interval_min  INTEGER NOT NULL DEFAULT 15,
    retention_days           INTEGER NOT NULL DEFAULT 90,
    -- Cost model (used by chargeback export)
    cost_per_vcpu_hour       NUMERIC(10,4) NOT NULL DEFAULT 0.00,
    cost_per_gb_ram_hour     NUMERIC(10,4) NOT NULL DEFAULT 0.00,
    cost_per_gb_storage_month NUMERIC(10,4) NOT NULL DEFAULT 0.00,
    cost_per_snapshot_gb_month NUMERIC(10,4) NOT NULL DEFAULT 0.00,
    cost_per_api_call        NUMERIC(10,6) NOT NULL DEFAULT 0.00,
    cost_currency            TEXT NOT NULL DEFAULT 'USD',
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO metering_config (id) VALUES (1)
    ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- metering_resources – periodic per-VM resource snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_resources (
    id                BIGSERIAL PRIMARY KEY,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    vm_id             TEXT NOT NULL,
    vm_name           TEXT,
    project_name      TEXT,
    domain            TEXT,
    host              TEXT,
    flavor            TEXT,
    -- Allocation (from OpenStack / flavors)
    vcpus_allocated   INTEGER,
    ram_allocated_mb  INTEGER,
    disk_allocated_gb INTEGER,
    -- Actual usage (from monitoring/PCD)
    cpu_usage_percent NUMERIC(6,2),
    ram_usage_mb      NUMERIC(10,2),
    ram_usage_percent NUMERIC(6,2),
    disk_used_gb      NUMERIC(10,2),
    disk_usage_percent NUMERIC(6,2),
    -- Network I/O
    network_rx_bytes  BIGINT,
    network_tx_bytes  BIGINT,
    -- Storage I/O
    storage_read_bytes  BIGINT,
    storage_write_bytes BIGINT
);

CREATE INDEX IF NOT EXISTS idx_metering_resources_vm
    ON metering_resources (vm_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_resources_project
    ON metering_resources (project_name, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_resources_collected
    ON metering_resources (collected_at DESC);

-- ---------------------------------------------------------------------------
-- metering_snapshots – per-snapshot metering records
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    snapshot_id       TEXT NOT NULL,
    snapshot_name     TEXT,
    volume_id         TEXT,
    volume_name       TEXT,
    project_name      TEXT,
    domain            TEXT,
    size_gb           NUMERIC(10,2),
    status            TEXT,
    policy_name       TEXT,
    is_compliant      BOOLEAN,
    created_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_metering_snapshots_project
    ON metering_snapshots (project_name, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_snapshots_collected
    ON metering_snapshots (collected_at DESC);

-- ---------------------------------------------------------------------------
-- metering_restores – per-restore operation metering
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_restores (
    id                BIGSERIAL PRIMARY KEY,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    restore_id        TEXT,
    snapshot_id       TEXT,
    snapshot_name     TEXT,
    target_server_id  TEXT,
    target_server_name TEXT,
    project_name      TEXT,
    domain            TEXT,
    status            TEXT,
    duration_seconds  INTEGER,
    initiated_by      TEXT,
    initiated_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_metering_restores_project
    ON metering_restores (project_name, collected_at DESC);

-- ---------------------------------------------------------------------------
-- metering_api_usage – API call aggregations per interval
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_api_usage (
    id                BIGSERIAL PRIMARY KEY,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    interval_start    TIMESTAMPTZ NOT NULL,
    interval_end      TIMESTAMPTZ NOT NULL,
    endpoint          TEXT NOT NULL,
    method            TEXT NOT NULL,
    total_calls       INTEGER NOT NULL DEFAULT 0,
    error_count       INTEGER NOT NULL DEFAULT 0,
    avg_latency_ms    NUMERIC(10,2),
    p95_latency_ms    NUMERIC(10,2),
    p99_latency_ms    NUMERIC(10,2),
    caller_user       TEXT
);

CREATE INDEX IF NOT EXISTS idx_metering_api_usage_collected
    ON metering_api_usage (collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_api_usage_endpoint
    ON metering_api_usage (endpoint, interval_start DESC);

-- ---------------------------------------------------------------------------
-- metering_quotas – per-project quota snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_quotas (
    id                BIGSERIAL PRIMARY KEY,
    collected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    project_id        TEXT NOT NULL,
    project_name      TEXT,
    domain            TEXT,
    -- Compute
    vcpus_quota       INTEGER,
    vcpus_used        INTEGER,
    ram_quota_mb      INTEGER,
    ram_used_mb       INTEGER,
    instances_quota   INTEGER,
    instances_used    INTEGER,
    -- Storage
    volumes_quota     INTEGER,
    volumes_used      INTEGER,
    storage_quota_gb  INTEGER,
    storage_used_gb   INTEGER,
    snapshots_quota   INTEGER,
    snapshots_used    INTEGER,
    -- Network
    floating_ips_quota INTEGER,
    floating_ips_used  INTEGER,
    networks_quota    INTEGER,
    networks_used     INTEGER,
    ports_quota       INTEGER,
    ports_used        INTEGER,
    security_groups_quota INTEGER,
    security_groups_used  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_metering_quotas_project
    ON metering_quotas (project_id, collected_at DESC);

-- ---------------------------------------------------------------------------
-- metering_efficiency – per-VM efficiency scores
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_efficiency (
    id                  BIGSERIAL PRIMARY KEY,
    collected_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    vm_id               TEXT NOT NULL,
    vm_name             TEXT,
    project_name        TEXT,
    domain              TEXT,
    -- Component scores (0-100)
    cpu_efficiency      NUMERIC(5,2),
    ram_efficiency      NUMERIC(5,2),
    storage_efficiency  NUMERIC(5,2),
    -- Weighted overall score (0-100)
    overall_score       NUMERIC(5,2),
    -- Classification: excellent / good / fair / poor / idle
    classification      TEXT,
    -- Recommendation text
    recommendation      TEXT
);

CREATE INDEX IF NOT EXISTS idx_metering_efficiency_vm
    ON metering_efficiency (vm_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_metering_efficiency_project
    ON metering_efficiency (project_name, collected_at DESC);

-- ---------------------------------------------------------------------------
-- Add vm_ip column to metering_resources (v1.16.0)
-- ---------------------------------------------------------------------------
ALTER TABLE metering_resources ADD COLUMN IF NOT EXISTS vm_ip TEXT;

-- ---------------------------------------------------------------------------
-- metering_flavor_pricing – per-flavor cost model for chargeback
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_flavor_pricing (
    id            SERIAL PRIMARY KEY,
    flavor_name   TEXT NOT NULL UNIQUE,
    vcpus         INTEGER NOT NULL DEFAULT 0,
    ram_gb        NUMERIC(10,2) NOT NULL DEFAULT 0,
    disk_gb       NUMERIC(10,2) NOT NULL DEFAULT 0,
    cost_per_hour NUMERIC(12,6) NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'USD',
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- metering_pricing – unified multi-category pricing for chargeback
-- Categories: flavor, storage_gb, snapshot_gb, restore, volume, network, custom
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS metering_pricing (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL DEFAULT 'custom',
    item_name       TEXT NOT NULL,
    unit            TEXT NOT NULL DEFAULT 'per hour',
    cost_per_hour   NUMERIC(12, 6) NOT NULL DEFAULT 0,
    cost_per_month  NUMERIC(12, 6) NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'USD',
    notes           TEXT,
    vcpus           INTEGER,
    ram_gb          NUMERIC(10, 2),
    disk_gb         NUMERIC(10, 2),
    auto_populated  BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category, item_name)
);

-- ---------------------------------------------------------------------------
-- RBAC: Grant metering permissions to admin / superadmin
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    -- admin: read metering data
    INSERT INTO role_permissions (role, resource, action) VALUES ('admin', 'metering', 'read')
        ON CONFLICT (role, resource, action) DO NOTHING;
    -- superadmin: read + write metering config
    INSERT INTO role_permissions (role, resource, action) VALUES ('superadmin', 'metering', 'read')
        ON CONFLICT (role, resource, action) DO NOTHING;
    INSERT INTO role_permissions (role, resource, action) VALUES ('superadmin', 'metering', 'write')
        ON CONFLICT (role, resource, action) DO NOTHING;
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'role_permissions table not found – skipping metering RBAC';
END $$;
