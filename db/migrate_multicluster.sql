-- =============================================================================
-- migrate_multicluster.sql - Phase 1: Multi-Region / Multi-Cluster Schema
-- =============================================================================
-- Applied automatically at API startup via startup_event() in api/main.py.
-- Fully idempotent: safe to run multiple times (all statements use IF NOT EXISTS
-- / IF EXISTS / ADD COLUMN IF NOT EXISTS).
-- Run with: psql -v ON_ERROR_STOP=0 -f migrate_multicluster.sql
--
-- Design:
--   Level 1: pf9_control_planes - one row per PF9 installation (one Keystone)
--   Level 2: pf9_regions        - one row per OpenStack region within a control plane
--
-- All new FK columns on existing tables are NULLABLE so existing single-cluster
-- deployments continue working with zero operator changes. On first startup after
-- this migration is applied, api/main.py seeds the default control plane + region
-- from PF9_AUTH_URL / PF9_REGION_NAME env vars and backfills all existing rows.
--
-- PK changes on resource tables (servers, volumes, etc.) are intentionally deferred
-- to Phase 5 (when db_writer.py is also updated) to keep this migration non-breaking.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Level 1: pf9_control_planes
-- One row per PF9 installation (one Keystone, one set of admin credentials).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pf9_control_planes (
    id                  TEXT PRIMARY KEY,
    -- e.g. "default", "corp-pf9", "lab-pf9"
    name                TEXT NOT NULL,
    -- Human-readable label shown in the UI
    auth_url            TEXT NOT NULL,
    -- https://pf9.company.com/keystone/v3
    username            TEXT NOT NULL,
    password_enc        TEXT NOT NULL,
    -- AES-256-GCM encrypted. Seeded from PF9_PASSWORD env var (encrypted at seed time).
    -- NEVER stored or returned in plaintext. Encryption key = CLUSTER_ENC_KEY secret.
    user_domain         TEXT NOT NULL DEFAULT 'Default',
    project_name        TEXT NOT NULL DEFAULT 'service',
    project_domain      TEXT NOT NULL DEFAULT 'Default',
    login_url           TEXT,
    -- Portal base URL for welcome emails and UI deep-links
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    display_color       TEXT,
    -- Hex color code for visual grouping in the UI, e.g. "#3b82f6"
    tags                JSONB NOT NULL DEFAULT '{}',
    allow_private_network BOOLEAN NOT NULL DEFAULT FALSE,
    -- Per-record SSRF exception. Only settable by superadmin. FALSE by default.
    -- When FALSE, auth_url and any URLs in cluster_tasks.payload are validated
    -- against RFC-1918 and loopback blocklists before any outbound connection.
    supported_types     TEXT[] NOT NULL DEFAULT '{openstack}',
    -- Future: '{openstack,kubernetes}'. Added now so K8s support needs no schema change.
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by          TEXT
);

-- ---------------------------------------------------------------------------
-- Level 2: pf9_regions
-- One row per OpenStack region within a control plane.
    -- (auth_url, region_name) -> unique set of Nova/Neutron/Cinder/Glance endpoints.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pf9_regions (
    id                      TEXT PRIMARY KEY,
    -- Convention: "{control_plane_id}:{region_name}", e.g. "default:region-one"
    control_plane_id        TEXT NOT NULL REFERENCES pf9_control_planes(id) ON DELETE CASCADE,
    region_name             TEXT NOT NULL,
    -- OpenStack region_id as returned in the Keystone catalog, e.g. "region-one"
    display_name            TEXT NOT NULL,
    -- Human label: "Region One (Default)"
    is_default              BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    sync_interval_minutes   INTEGER NOT NULL DEFAULT 30,
    last_sync_at            TIMESTAMPTZ,
    last_sync_status        TEXT,
    -- 'success' | 'partial' | 'failed'
    last_sync_vm_count      INTEGER,
    health_status           TEXT NOT NULL DEFAULT 'unknown',
    -- 'healthy' | 'degraded' | 'unreachable' | 'auth_failed' | 'unknown'
    -- auth_failed = Keystone returned 401/403 (requires operator action to rotate creds)
    -- degraded    = sync completed with partial errors, or avg_api_latency > threshold
    -- unreachable = TCP/HTTP connection failed (worker will retry next cycle)
    health_checked_at       TIMESTAMPTZ,
    priority                INTEGER NOT NULL DEFAULT 100,
    -- Lower number = higher priority. Controls failover order, worker scheduling, cost routing.
    -- Example: prod = 10, DR = 50, lab = 200
    capabilities            JSONB NOT NULL DEFAULT '{}',
    -- Refreshed at each sync from live Nova/Cinder/Glance responses.
    -- Example: {"gpu": true, "nvme": true, "max_volume_size_gb": 16000}
    -- Migration planner reads this for eligibility checks without live API calls.
    latency_threshold_ms    INTEGER NOT NULL DEFAULT 2000,
    -- Per-region configurable threshold. Exceeding it during sync marks health 'degraded'.
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (control_plane_id, region_name)
);

-- Partial unique index: at most one default region across the entire table.
-- More portable than EXCLUDE — a concurrent INSERT of two defaults will fail on one.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pf9_regions_one_default
    ON pf9_regions (is_default)
    WHERE (is_default = TRUE);

-- ---------------------------------------------------------------------------
-- Add region_id FK to resource tables (all NULLABLE - backward compat)
-- These columns map each resource row to the region it came from.
-- ---------------------------------------------------------------------------

-- Core inventory tables
ALTER TABLE hypervisors         ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE servers             ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE volumes             ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE networks            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE subnets             ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE routers             ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE ports               ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE floating_ips        ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE flavors             ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE images              ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshots           ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE inventory_runs      ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE security_groups     ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- Metering tables (defined in migrate_metering.sql - safe to apply here too)
ALTER TABLE metering_resources  ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE metering_efficiency ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- Keystone identity tables: scoped to control_plane (shared across regions on a control plane)
ALTER TABLE domains             ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE projects            ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE users               ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE roles               ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE role_assignments    ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);

-- Application operation tables
ALTER TABLE provisioning_jobs           ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE provisioning_steps          ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshot_policy_sets        ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshot_assignments        ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshot_records            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE deletions_history           ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- vm_provisioning_batches is created inline in api/vm_provisioning_routes.py
-- The ALTER is applied here so it runs after table creation on first startup.
-- IF NOT EXISTS makes it safe even if the column was already added previously.
ALTER TABLE vm_provisioning_batches     ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- Per-cluster RBAC scoping (nullable - NULL = global, current behavior unchanged).
-- Enforcement is deferred to Phase 5 — columns added now to avoid a later data migration.
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS region_id        TEXT REFERENCES pf9_regions(id);
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);

-- Snapshot DR replication mode (used by snapshot_worker in Phase 4)
ALTER TABLE snapshot_policy_sets ADD COLUMN IF NOT EXISTS replication_mode TEXT;
-- 'image_copy' | 'volume_transfer' | 'backup_restore' | NULL (no replication)
ALTER TABLE snapshot_policy_sets ADD COLUMN IF NOT EXISTS replication_region_id TEXT REFERENCES pf9_regions(id);

-- History tables: no FK constraint, just for audit trail context
ALTER TABLE servers_history    ADD COLUMN IF NOT EXISTS region_id TEXT;
ALTER TABLE volumes_history    ADD COLUMN IF NOT EXISTS region_id TEXT;
ALTER TABLE domains_history    ADD COLUMN IF NOT EXISTS control_plane_id TEXT;
ALTER TABLE projects_history   ADD COLUMN IF NOT EXISTS control_plane_id TEXT;

-- ---------------------------------------------------------------------------
-- cluster_sync_metrics - per-region sync outcomes (feeds health_status)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cluster_sync_metrics (
    id                  BIGSERIAL PRIMARY KEY,
    region_id           TEXT NOT NULL REFERENCES pf9_regions(id) ON DELETE CASCADE,
    sync_type           TEXT NOT NULL,
    -- 'inventory' | 'metering' | 'snapshot' | 'backup'
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ,
    duration_ms         INTEGER,
    resource_count      INTEGER,
    error_count         INTEGER NOT NULL DEFAULT 0,
    api_calls_made      INTEGER NOT NULL DEFAULT 0,
    avg_api_latency_ms  INTEGER,
    -- Average PF9 API round-trip time. Compared against pf9_regions.latency_threshold_ms.
    -- Exceeding the threshold marks health as 'degraded' even if sync otherwise succeeded.
    status              TEXT NOT NULL
    -- 'success' | 'partial' | 'failed'
);

CREATE INDEX IF NOT EXISTS idx_cluster_sync_metrics_region_started
    ON cluster_sync_metrics (region_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_sync_metrics_status_started
    ON cluster_sync_metrics (status, started_at DESC);

-- ---------------------------------------------------------------------------
-- cluster_tasks - state machine for long-running cross-cluster operations
-- (snapshot replication, cross-region migration, DR failover)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cluster_tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type           TEXT NOT NULL,
    -- 'snapshot_replication' | 'cross_region_migration' | 'dr_failover' | 'image_copy'
    operation_scope     TEXT NOT NULL DEFAULT 'cross_cluster',
    -- 'single' | 'cross_cluster'
    source_region_id    TEXT REFERENCES pf9_regions(id),
    target_region_id    TEXT REFERENCES pf9_regions(id),
    replication_mode    TEXT,
    -- 'image_copy' | 'volume_transfer' | 'backup_restore'
    status              TEXT NOT NULL DEFAULT 'pending',
    -- 'pending' | 'in_progress' | 'partial' | 'completed' | 'failed'
    payload             JSONB NOT NULL DEFAULT '{}',
    result              JSONB NOT NULL DEFAULT '{}',
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ,
    retry_count         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cluster_tasks_status_retry
    ON cluster_tasks (status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_cluster_tasks_source_type
    ON cluster_tasks (source_region_id, task_type);
CREATE INDEX IF NOT EXISTS idx_cluster_tasks_target_type
    ON cluster_tasks (target_region_id, task_type);

-- ---------------------------------------------------------------------------
-- Indexes on new FK columns for query performance
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_servers_region_id       ON servers(region_id);
CREATE INDEX IF NOT EXISTS idx_hypervisors_region_id   ON hypervisors(region_id);
CREATE INDEX IF NOT EXISTS idx_volumes_region_id       ON volumes(region_id);
CREATE INDEX IF NOT EXISTS idx_networks_region_id      ON networks(region_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_region_id     ON snapshots(region_id);
CREATE INDEX IF NOT EXISTS idx_security_groups_region  ON security_groups(region_id);
CREATE INDEX IF NOT EXISTS idx_domains_cp_id           ON domains(control_plane_id);
CREATE INDEX IF NOT EXISTS idx_projects_cp_id          ON projects(control_plane_id);
CREATE INDEX IF NOT EXISTS idx_users_cp_id             ON users(control_plane_id);
CREATE INDEX IF NOT EXISTS idx_prov_jobs_region_id     ON provisioning_jobs(region_id);
CREATE INDEX IF NOT EXISTS idx_snap_policy_region_id   ON snapshot_policy_sets(region_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_region_id    ON user_roles(region_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_cp_id        ON user_roles(control_plane_id);

-- =============================================================================
-- NOTE: PRIMARY KEY changes on resource tables (servers, volumes, etc.) to
-- (id, region_id) are deferred to Phase 5 when db_writer.py ON CONFLICT
-- clauses are simultaneously updated. Applying the DDL without the matching
-- application change would break every inventory write.
-- =============================================================================
