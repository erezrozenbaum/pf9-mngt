-- Basic tenants/projects/domains
CREATE TABLE IF NOT EXISTS domains (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    raw_json    JSONB,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    domain_id    TEXT REFERENCES domains(id),
    raw_json     JSONB,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Example: hypervisors
CREATE TABLE IF NOT EXISTS hypervisors (
    id               TEXT PRIMARY KEY,
    hostname         TEXT,
    hypervisor_type  TEXT,
    vcpus            INTEGER,
    memory_mb        INTEGER,
    local_gb         INTEGER,
    state            TEXT,
    status           TEXT,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Example: servers (instances)
CREATE TABLE IF NOT EXISTS servers (
    id               TEXT PRIMARY KEY,
    name             TEXT,
    project_id       TEXT REFERENCES projects(id),
    status           TEXT,
    vm_state         TEXT,
    flavor_id        TEXT,
    hypervisor_hostname TEXT,
    created_at       TIMESTAMPTZ,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Example: volumes
CREATE TABLE IF NOT EXISTS volumes (
    id               TEXT PRIMARY KEY,
    name             TEXT,
    project_id       TEXT REFERENCES projects(id),
    size_gb          INTEGER,
    status           TEXT,
    volume_type      TEXT,
    bootable         BOOLEAN,
    created_at       TIMESTAMPTZ,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Example: networks / subnets / ports / routers / fips
CREATE TABLE IF NOT EXISTS networks (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    project_id   TEXT REFERENCES projects(id),
    is_shared    BOOLEAN,
    is_external  BOOLEAN,
    raw_json     JSONB,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subnets (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    network_id   TEXT REFERENCES networks(id),
    cidr         TEXT,
    gateway_ip   TEXT,
    raw_json     JSONB,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS routers (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    project_id    TEXT REFERENCES projects(id),
    external_net_id TEXT,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ports (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    network_id    TEXT REFERENCES networks(id),
    project_id    TEXT REFERENCES projects(id),
    device_id     TEXT,
    device_owner  TEXT,
    mac_address   TEXT,
    ip_addresses  JSONB,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS floating_ips (
    id            TEXT PRIMARY KEY,
    floating_ip   TEXT,
    fixed_ip      TEXT,
    port_id       TEXT REFERENCES ports(id),
    project_id    TEXT REFERENCES projects(id),
    router_id     TEXT REFERENCES routers(id),
    status        TEXT,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Missing core tables
CREATE TABLE IF NOT EXISTS flavors (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    vcpus         INTEGER,
    ram_mb        INTEGER,
    disk_gb       INTEGER,
    ephemeral_gb  INTEGER,
    swap_mb       INTEGER,
    is_public     BOOLEAN,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS images (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    status        TEXT,
    visibility    TEXT,
    protected     BOOLEAN,
    size_bytes    BIGINT,
    disk_format   TEXT,
    container_format TEXT,
    checksum      TEXT,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS snapshots (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    description   TEXT,
    project_id    TEXT,
    project_name  TEXT,
    tenant_name   TEXT,
    domain_name   TEXT,
    domain_id     TEXT,
    volume_id     TEXT REFERENCES volumes(id),
    size_gb       INTEGER,
    status        TEXT,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Track inventory runs (for history/compliance later)
CREATE TABLE IF NOT EXISTS inventory_runs (
    id               BIGSERIAL PRIMARY KEY,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           TEXT,                 -- success / failure / partial
    source           TEXT,                 -- e.g. 'pf9_rvtools'
    host_name        TEXT,
    duration_seconds INTEGER,
    notes            TEXT
);

-- =====================================================================
-- HISTORY TABLES - Track changes over time for each RVTOOLS run
-- =====================================================================

-- Domains history
CREATE TABLE IF NOT EXISTS domains_history (
    id           BIGSERIAL PRIMARY KEY,
    domain_id    TEXT NOT NULL,
    name         TEXT,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_domains_history_domain_id ON domains_history(domain_id);
CREATE INDEX IF NOT EXISTS idx_domains_history_recorded_at ON domains_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_domains_history_change_hash ON domains_history(domain_id, change_hash);

-- Projects history  
CREATE TABLE IF NOT EXISTS projects_history (
    id           BIGSERIAL PRIMARY KEY,
    project_id   TEXT NOT NULL,
    name         TEXT,
    domain_id    TEXT,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_projects_history_project_id ON projects_history(project_id);
CREATE INDEX IF NOT EXISTS idx_projects_history_recorded_at ON projects_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_projects_history_change_hash ON projects_history(project_id, change_hash);

-- Flavors history
CREATE TABLE IF NOT EXISTS flavors_history (
    id           BIGSERIAL PRIMARY KEY,
    flavor_id    TEXT NOT NULL,
    name         TEXT,
    vcpus        INTEGER,
    ram_mb       INTEGER,
    disk_gb      INTEGER,
    ephemeral_gb INTEGER,
    swap_mb      INTEGER,
    is_public    BOOLEAN,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_flavors_history_flavor_id ON flavors_history(flavor_id);
CREATE INDEX IF NOT EXISTS idx_flavors_history_recorded_at ON flavors_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_flavors_history_change_hash ON flavors_history(flavor_id, change_hash);

-- Images history
CREATE TABLE IF NOT EXISTS images_history (
    id              BIGSERIAL PRIMARY KEY,
    image_id        TEXT NOT NULL,
    name            TEXT,
    status          TEXT,
    visibility      TEXT,
    protected       BOOLEAN,
    size_bytes      BIGINT,
    disk_format     TEXT,
    container_format TEXT,
    checksum        TEXT,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash     TEXT NOT NULL,
    raw_json        JSONB
);
CREATE INDEX IF NOT EXISTS idx_images_history_image_id ON images_history(image_id);
CREATE INDEX IF NOT EXISTS idx_images_history_recorded_at ON images_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_images_history_change_hash ON images_history(image_id, change_hash);

-- Hypervisors history
CREATE TABLE IF NOT EXISTS hypervisors_history (
    id                 BIGSERIAL PRIMARY KEY,
    hypervisor_id      TEXT NOT NULL,
    hostname           TEXT,
    hypervisor_type    TEXT,
    vcpus              INTEGER,
    memory_mb          INTEGER,
    local_gb           INTEGER,
    state              TEXT,
    status             TEXT,
    recorded_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash        TEXT NOT NULL,
    raw_json           JSONB
);
CREATE INDEX IF NOT EXISTS idx_hypervisors_history_hypervisor_id ON hypervisors_history(hypervisor_id);
CREATE INDEX IF NOT EXISTS idx_hypervisors_history_recorded_at ON hypervisors_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_hypervisors_history_change_hash ON hypervisors_history(hypervisor_id, change_hash);

-- Servers history (already referenced in db_writer.py)
CREATE TABLE IF NOT EXISTS servers_history (
    id                    BIGSERIAL PRIMARY KEY,
    server_id             TEXT NOT NULL,
    name                  TEXT,
    project_id            TEXT,
    status                TEXT,
    vm_state              TEXT,
    flavor_id             TEXT,
    hypervisor_hostname   TEXT,
    created_at            TIMESTAMPTZ,
    last_seen_at          TIMESTAMPTZ,
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash           TEXT NOT NULL,
    raw_json              JSONB
);
CREATE INDEX IF NOT EXISTS idx_servers_history_server_id ON servers_history(server_id);
CREATE INDEX IF NOT EXISTS idx_servers_history_recorded_at ON servers_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_servers_history_change_hash ON servers_history(server_id, change_hash);

-- Volumes history (already referenced in db_writer.py)
CREATE TABLE IF NOT EXISTS volumes_history (
    id           BIGSERIAL PRIMARY KEY,
    volume_id    TEXT NOT NULL,
    name         TEXT,
    project_id   TEXT,
    size_gb      INTEGER,
    status       TEXT,
    volume_type  TEXT,
    bootable     BOOLEAN,
    created_at   TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_volumes_history_volume_id ON volumes_history(volume_id);
CREATE INDEX IF NOT EXISTS idx_volumes_history_recorded_at ON volumes_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_volumes_history_change_hash ON volumes_history(volume_id, change_hash);

-- Snapshots history  
CREATE TABLE IF NOT EXISTS snapshots_history (
    id           BIGSERIAL PRIMARY KEY,
    snapshot_id  TEXT NOT NULL,
    name         TEXT,
    description  TEXT,
    run_id       BIGINT REFERENCES inventory_runs(id),
    project_id   TEXT,
    volume_id    TEXT,
    size_gb      INTEGER,
    status       TEXT,
    created_at   TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_snapshots_history_snapshot_id ON snapshots_history(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_history_recorded_at ON snapshots_history(recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_history_change_hash ON snapshots_history(snapshot_id, change_hash);

-- Networks history
CREATE TABLE IF NOT EXISTS networks_history (
    id           BIGSERIAL PRIMARY KEY,
    network_id   TEXT NOT NULL,
    name         TEXT,
    project_id   TEXT,
    is_shared    BOOLEAN,
    is_external  BOOLEAN,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_networks_history_network_id ON networks_history(network_id);
CREATE INDEX IF NOT EXISTS idx_networks_history_recorded_at ON networks_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_networks_history_change_hash ON networks_history(network_id, change_hash);

-- Subnets history
CREATE TABLE IF NOT EXISTS subnets_history (
    id           BIGSERIAL PRIMARY KEY,
    subnet_id    TEXT NOT NULL,
    name         TEXT,
    network_id   TEXT,
    cidr         TEXT,
    gateway_ip   TEXT,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_subnets_history_subnet_id ON subnets_history(subnet_id);
CREATE INDEX IF NOT EXISTS idx_subnets_history_recorded_at ON subnets_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_subnets_history_change_hash ON subnets_history(subnet_id, change_hash);

-- Routers history
CREATE TABLE IF NOT EXISTS routers_history (
    id              BIGSERIAL PRIMARY KEY,
    router_id       TEXT NOT NULL,
    name            TEXT,
    project_id      TEXT,
    external_net_id TEXT,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash     TEXT NOT NULL,
    raw_json        JSONB
);
CREATE INDEX IF NOT EXISTS idx_routers_history_router_id ON routers_history(router_id);
CREATE INDEX IF NOT EXISTS idx_routers_history_recorded_at ON routers_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_routers_history_change_hash ON routers_history(router_id, change_hash);

-- Ports history
CREATE TABLE IF NOT EXISTS ports_history (
    id            BIGSERIAL PRIMARY KEY,
    port_id       TEXT NOT NULL,
    name          TEXT,
    network_id    TEXT,
    project_id    TEXT,
    device_id     TEXT,
    device_owner  TEXT,
    mac_address   TEXT,
    ip_addresses  JSONB,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash   TEXT NOT NULL,
    raw_json      JSONB
);
CREATE INDEX IF NOT EXISTS idx_ports_history_port_id ON ports_history(port_id);
CREATE INDEX IF NOT EXISTS idx_ports_history_recorded_at ON ports_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_ports_history_change_hash ON ports_history(port_id, change_hash);

-- Floating IPs history
CREATE TABLE IF NOT EXISTS floating_ips_history (
    id           BIGSERIAL PRIMARY KEY,
    floating_ip_id TEXT NOT NULL,
    floating_ip  TEXT,
    fixed_ip     TEXT,
    port_id      TEXT,
    project_id   TEXT,
    router_id    TEXT,
    status       TEXT,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_floating_ips_history_floating_ip_id ON floating_ips_history(floating_ip_id);
CREATE INDEX IF NOT EXISTS idx_floating_ips_history_recorded_at ON floating_ips_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_floating_ips_history_change_hash ON floating_ips_history(floating_ip_id, change_hash);

-- Views for enriched volume data with attachment and tenant information
-- This view provides the legacy v_volumes_full interface for backward compatibility
CREATE OR REPLACE VIEW v_volumes_full AS
SELECT 
    v.id,
    v.name AS volume_name,
    v.status,
    v.size_gb,
    v.volume_type,
    v.bootable,
    v.created_at,
    p.id AS tenant_id,
    p.name AS tenant_name,
    d.id AS domain_id,
    d.name AS domain_name,
    v.raw_json->>'server_id' AS server_id,
    v.raw_json->>'server_name' AS server_name,
    v.raw_json->>'device' AS device,
    v.raw_json->>'attach_host' AS attach_host
FROM volumes v
LEFT JOIN projects p ON p.id = v.project_id
LEFT JOIN domains d ON d.id = p.domain_id;

-- ===== User and Role Management Tables =====

-- Users (from Keystone)
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT,
    enabled       BOOLEAN DEFAULT true,
    domain_id     TEXT REFERENCES domains(id),
    description   TEXT,
    default_project_id TEXT REFERENCES projects(id),
    password_expires_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ,
    last_login    TIMESTAMPTZ,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_users_domain_id ON users(domain_id);
CREATE INDEX IF NOT EXISTS idx_users_enabled ON users(enabled);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Roles (from Keystone)
CREATE TABLE IF NOT EXISTS roles (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    description   TEXT,
    domain_id     TEXT REFERENCES domains(id),
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_roles_name ON roles(name);
CREATE INDEX IF NOT EXISTS idx_roles_domain_id ON roles(domain_id);

-- Role Assignments (from Keystone)
CREATE TABLE IF NOT EXISTS role_assignments (
    id            BIGSERIAL PRIMARY KEY,
    role_id       TEXT NOT NULL REFERENCES roles(id),
    user_id       TEXT REFERENCES users(id),
    group_id      TEXT,  -- For group assignments (optional)
    project_id    TEXT REFERENCES projects(id),
    domain_id     TEXT REFERENCES domains(id),
    inherited     BOOLEAN DEFAULT false,
    -- Derived fields from Keystone API include_names=true response
    user_name     TEXT,
    role_name     TEXT,
    project_name  TEXT,
    domain_name   TEXT,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Constraints: must have either project_id OR domain_id as scope
    CONSTRAINT role_assignments_scope_check CHECK (
        (project_id IS NOT NULL AND domain_id IS NULL) OR
        (project_id IS NULL AND domain_id IS NOT NULL)
    ),
    -- Unique constraint to prevent duplicate assignments
    UNIQUE(role_id, user_id, project_id, domain_id, group_id)
);
CREATE INDEX IF NOT EXISTS idx_role_assignments_user_id ON role_assignments(user_id);
CREATE INDEX IF NOT EXISTS idx_role_assignments_role_id ON role_assignments(role_id);
CREATE INDEX IF NOT EXISTS idx_role_assignments_project_id ON role_assignments(project_id);
CREATE INDEX IF NOT EXISTS idx_role_assignments_domain_id ON role_assignments(domain_id);

-- Groups (optional - for group-based role assignments)
CREATE TABLE IF NOT EXISTS groups (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    domain_id     TEXT REFERENCES domains(id),
    description   TEXT,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_groups_domain_id ON groups(domain_id);
CREATE INDEX IF NOT EXISTS idx_groups_name ON groups(name);

-- User access patterns tracking (for monitoring and analytics)
CREATE TABLE IF NOT EXISTS user_access_logs (
    id            BIGSERIAL PRIMARY KEY,
    user_id       TEXT REFERENCES users(id),
    user_name     TEXT NOT NULL,
    action        TEXT NOT NULL,  -- 'login', 'api_call', 'resource_access'
    resource_type TEXT,           -- 'server', 'volume', 'network', etc.
    resource_id   TEXT,
    project_id    TEXT REFERENCES projects(id),
    success       BOOLEAN DEFAULT true,
    ip_address    INET,
    user_agent    TEXT,
    timestamp     TIMESTAMPTZ NOT NULL DEFAULT now(),
    details       JSONB
);
CREATE INDEX IF NOT EXISTS idx_user_access_logs_user_id ON user_access_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_user_access_logs_timestamp ON user_access_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_user_access_logs_action ON user_access_logs(action);
CREATE INDEX IF NOT EXISTS idx_user_access_logs_resource ON user_access_logs(resource_type, resource_id);

-- User activity summary view for dashboard and reporting
CREATE OR REPLACE VIEW v_user_activity_summary AS
SELECT 
    u.id,
    u.name AS user_name,
    u.email,
    u.enabled,
    u.last_login,
    d.name AS domain_name,
    p.name AS default_project_name,
    -- Role information
    COUNT(DISTINCT ra.role_id) AS role_count,
    STRING_AGG(DISTINCT r.name, ', ') AS roles,
    -- Project access
    COUNT(DISTINCT ra.project_id) AS project_access_count,
    -- Recent activity
    MAX(ual.timestamp) AS last_activity,
    COUNT(ual.id) FILTER (WHERE ual.timestamp > now() - INTERVAL '30 days') AS activity_last_30d,
    COUNT(ual.id) FILTER (WHERE ual.timestamp > now() - INTERVAL '7 days') AS activity_last_7d
FROM users u
LEFT JOIN domains d ON d.id = u.domain_id
LEFT JOIN projects p ON p.id = u.default_project_id
LEFT JOIN role_assignments ra ON ra.user_id = u.id
LEFT JOIN roles r ON r.id = ra.role_id
LEFT JOIN user_access_logs ual ON ual.user_id = u.id
GROUP BY u.id, u.name, u.email, u.enabled, u.last_login, d.name, p.name;

-- ===== History Tables for User and Role Management =====

-- Users history
CREATE TABLE IF NOT EXISTS users_history (
    id           BIGSERIAL PRIMARY KEY,
    user_id      TEXT NOT NULL,
    run_id       BIGINT REFERENCES inventory_runs(id),
    name         TEXT NOT NULL,
    email        TEXT,
    enabled      BOOLEAN DEFAULT true,
    domain_id    TEXT,
    description  TEXT,
    default_project_id TEXT,
    password_expires_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ,
    last_login   TIMESTAMPTZ,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_users_history_user_id ON users_history(user_id);
CREATE INDEX IF NOT EXISTS idx_users_history_recorded_at ON users_history(recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_history_change_hash ON users_history(user_id, change_hash);

-- Roles history
CREATE TABLE IF NOT EXISTS roles_history (
    id           BIGSERIAL PRIMARY KEY,
    role_id      TEXT NOT NULL,
    run_id       BIGINT REFERENCES inventory_runs(id),
    name         TEXT NOT NULL,
    description  TEXT,
    domain_id    TEXT,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash  TEXT NOT NULL,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_roles_history_role_id ON roles_history(role_id);
CREATE INDEX IF NOT EXISTS idx_roles_history_recorded_at ON roles_history(recorded_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_roles_history_change_hash ON roles_history(role_id, change_hash);

-- Deletions history
CREATE TABLE IF NOT EXISTS deletions_history (
    id           BIGSERIAL PRIMARY KEY,
    resource_type TEXT NOT NULL,
    resource_id  TEXT NOT NULL,
    resource_name TEXT,
    deleted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id       BIGINT REFERENCES inventory_runs(id),
    project_name TEXT,
    domain_name  TEXT,
    last_seen_before_deletion TIMESTAMPTZ,
    reason       TEXT,
    raw_json     JSONB
);
CREATE INDEX IF NOT EXISTS idx_deletions_history_resource_type ON deletions_history(resource_type);
CREATE INDEX IF NOT EXISTS idx_deletions_history_resource_id ON deletions_history(resource_id);
CREATE INDEX IF NOT EXISTS idx_deletions_history_deleted_at ON deletions_history(deleted_at);
CREATE INDEX IF NOT EXISTS idx_deletions_history_run_id ON deletions_history(run_id);

-- =====================================================================
-- AUTHENTICATION AND AUTHORIZATION TABLES
-- =====================================================================

-- User sessions and JWT token management
CREATE TABLE IF NOT EXISTS user_sessions (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    token_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity TIMESTAMPTZ DEFAULT now(),
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_user_sessions_username ON user_sessions(username);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash ON user_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_user_sessions_active ON user_sessions(is_active, expires_at);

-- User roles for the management system (separate from OpenStack roles)
CREATE TABLE IF NOT EXISTS user_roles (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    granted_by VARCHAR(255),
    granted_at TIMESTAMPTZ DEFAULT now(),
    last_modified TIMESTAMPTZ DEFAULT now(),
    is_active BOOLEAN DEFAULT true
);
CREATE INDEX IF NOT EXISTS idx_user_roles_username ON user_roles(username);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role);
CREATE INDEX IF NOT EXISTS idx_user_roles_active ON user_roles(is_active);

-- =====================================================================
-- SNAPSHOT MANAGEMENT TABLES
-- =====================================================================

-- Snapshot policy sets (global and tenant-specific)
CREATE TABLE IF NOT EXISTS snapshot_policy_sets (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_global BOOLEAN DEFAULT false,
    tenant_id TEXT,  -- NULL for global policies, specific tenant_id for tenant policies
    tenant_name TEXT,
    policies JSONB NOT NULL,  -- Array of policy names like ["daily_5", "weekly_4"]
    retention_map JSONB NOT NULL,  -- {"daily_5": 5, "weekly_4": 28, ...}
    priority INTEGER DEFAULT 0,  -- Higher priority = applied first
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    created_by VARCHAR(255),
    updated_at TIMESTAMPTZ DEFAULT now(),
    updated_by VARCHAR(255),
    CONSTRAINT unique_global_policy_name UNIQUE NULLS NOT DISTINCT (name, tenant_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_policy_sets_tenant ON snapshot_policy_sets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_policy_sets_global ON snapshot_policy_sets(is_global);
CREATE INDEX IF NOT EXISTS idx_snapshot_policy_sets_active ON snapshot_policy_sets(is_active);

-- Snapshot policy assignments (which volumes get which policies)
CREATE TABLE IF NOT EXISTS snapshot_assignments (
    id BIGSERIAL PRIMARY KEY,
    volume_id TEXT NOT NULL,
    volume_name TEXT,
    tenant_id TEXT NOT NULL,
    tenant_name TEXT,
    project_id TEXT NOT NULL,
    project_name TEXT,
    vm_id TEXT,  -- Attached VM (can be NULL for unattached volumes)
    vm_name TEXT,
    policy_set_id BIGINT REFERENCES snapshot_policy_sets(id) ON DELETE CASCADE,
    auto_snapshot BOOLEAN DEFAULT true,
    policies JSONB NOT NULL,  -- ["daily_5", "weekly_4"]
    retention_map JSONB NOT NULL,  -- {"daily_5": 5, "weekly_4": 28}
    assignment_source VARCHAR(50) DEFAULT 'manual',  -- 'manual', 'rule-based', 'api'
    matched_rules JSONB,  -- Store which rules matched for audit
    created_at TIMESTAMPTZ DEFAULT now(),
    created_by VARCHAR(255),
    updated_at TIMESTAMPTZ DEFAULT now(),
    updated_by VARCHAR(255),
    last_verified_at TIMESTAMPTZ,
    CONSTRAINT unique_volume_assignment UNIQUE (volume_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_assignments_volume ON snapshot_assignments(volume_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_assignments_tenant ON snapshot_assignments(tenant_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_assignments_project ON snapshot_assignments(project_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_assignments_vm ON snapshot_assignments(vm_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_assignments_policy_set ON snapshot_assignments(policy_set_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_assignments_auto_snapshot ON snapshot_assignments(auto_snapshot);

-- Snapshot exclusions (volumes explicitly excluded from snapshots)
CREATE TABLE IF NOT EXISTS snapshot_exclusions (
    id BIGSERIAL PRIMARY KEY,
    volume_id TEXT NOT NULL,
    volume_name TEXT,
    tenant_id TEXT,
    tenant_name TEXT,
    project_id TEXT,
    project_name TEXT,
    exclusion_reason TEXT,
    exclusion_source VARCHAR(50) DEFAULT 'manual',  -- 'manual', 'metadata-tag', 'api'
    created_at TIMESTAMPTZ DEFAULT now(),
    created_by VARCHAR(255),
    expires_at TIMESTAMPTZ,  -- Optional expiration for temporary exclusions
    CONSTRAINT unique_volume_exclusion UNIQUE (volume_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_exclusions_volume ON snapshot_exclusions(volume_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_exclusions_tenant ON snapshot_exclusions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_exclusions_expires ON snapshot_exclusions(expires_at);

-- Snapshot runs (execution tracking)
CREATE TABLE IF NOT EXISTS snapshot_runs (
    id BIGSERIAL PRIMARY KEY,
    run_type VARCHAR(50) NOT NULL,  -- 'daily_5', 'weekly_4', 'monthly_1st', 'manual'
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status VARCHAR(50) DEFAULT 'running',  -- 'running', 'completed', 'failed', 'partial'
    total_volumes INTEGER DEFAULT 0,
    snapshots_created INTEGER DEFAULT 0,
    snapshots_deleted INTEGER DEFAULT 0,
    snapshots_failed INTEGER DEFAULT 0,
    volumes_skipped INTEGER DEFAULT 0,
    dry_run BOOLEAN DEFAULT false,
    triggered_by VARCHAR(255),  -- User or system that triggered
    trigger_source VARCHAR(50) DEFAULT 'scheduled',  -- 'scheduled', 'manual', 'api'
    execution_host VARCHAR(255),
    error_summary TEXT,
    raw_logs TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_snapshot_runs_started_at ON snapshot_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_snapshot_runs_run_type ON snapshot_runs(run_type);
CREATE INDEX IF NOT EXISTS idx_snapshot_runs_status ON snapshot_runs(status);
CREATE INDEX IF NOT EXISTS idx_snapshot_runs_trigger_source ON snapshot_runs(trigger_source);

-- Snapshot records (individual snapshot creation/deletion events)
CREATE TABLE IF NOT EXISTS snapshot_records (
    id BIGSERIAL PRIMARY KEY,
    snapshot_run_id BIGINT REFERENCES snapshot_runs(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,  -- 'created', 'deleted', 'failed', 'skipped'
    snapshot_id TEXT,  -- OpenStack snapshot ID (NULL for skipped/failed)
    snapshot_name TEXT,
    volume_id TEXT NOT NULL,
    volume_name TEXT,
    tenant_id TEXT NOT NULL,
    tenant_name TEXT,
    project_id TEXT NOT NULL,
    project_name TEXT,
    vm_id TEXT,
    vm_name TEXT,
    policy_name VARCHAR(100),  -- Which policy this snapshot belongs to
    size_gb INTEGER,
    created_at TIMESTAMPTZ DEFAULT now(),
    deleted_at TIMESTAMPTZ,  -- For cleanup tracking
    retention_days INTEGER,  -- How many days to keep
    status VARCHAR(50) DEFAULT 'pending',  -- 'pending', 'available', 'error', 'deleted'
    error_message TEXT,
    openstack_created_at TIMESTAMPTZ,  -- Timestamp from OpenStack
    raw_snapshot_json JSONB  -- Full OpenStack snapshot object
);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_run ON snapshot_records(snapshot_run_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_volume ON snapshot_records(volume_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_tenant ON snapshot_records(tenant_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_project ON snapshot_records(project_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_vm ON snapshot_records(vm_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_snapshot ON snapshot_records(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_action ON snapshot_records(action);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_policy ON snapshot_records(policy_name);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_created_at ON snapshot_records(created_at);

-- Role permissions matrix
CREATE TABLE IF NOT EXISTS role_permissions (
    id BIGSERIAL PRIMARY KEY,
    role VARCHAR(50) NOT NULL,
    resource VARCHAR(100) NOT NULL, -- 'servers', 'volumes', 'users', etc.
    action VARCHAR(50) NOT NULL, -- 'read', 'write', 'admin'
    conditions JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role);
CREATE INDEX IF NOT EXISTS idx_role_permissions_resource ON role_permissions(resource);
CREATE UNIQUE INDEX IF NOT EXISTS idx_role_permissions_unique ON role_permissions(role, resource, action);

-- Authentication audit log
CREATE TABLE IF NOT EXISTS auth_audit_log (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255),
    action VARCHAR(50), -- 'login', 'logout', 'failed_login', 'permission_denied', 'api_access'
    resource VARCHAR(100),
    endpoint VARCHAR(255),
    ip_address INET,
    user_agent TEXT,
    timestamp TIMESTAMPTZ DEFAULT now(),
    success BOOLEAN DEFAULT true,
    details JSONB
);
CREATE INDEX IF NOT EXISTS idx_auth_audit_log_username ON auth_audit_log(username);
CREATE INDEX IF NOT EXISTS idx_auth_audit_log_timestamp ON auth_audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_auth_audit_log_action ON auth_audit_log(action);

-- Insert default role permissions
INSERT INTO role_permissions (role, resource, action) VALUES
-- Viewer permissions (read-only access to most resources)
('viewer', 'servers', 'read'),
('viewer', 'volumes', 'read'),
('viewer', 'snapshots', 'read'),
('viewer', 'networks', 'read'),
('viewer', 'subnets', 'read'),
('viewer', 'ports', 'read'),
('viewer', 'floatingips', 'read'),
('viewer', 'domains', 'read'),
('viewer', 'projects', 'read'),
('viewer', 'flavors', 'read'),
('viewer', 'images', 'read'),
('viewer', 'hypervisors', 'read'),
('viewer', 'snapshot_policy_sets', 'read'),
('viewer', 'snapshot_assignments', 'read'),
('viewer', 'snapshot_exclusions', 'read'),
('viewer', 'snapshot_runs', 'read'),
('viewer', 'snapshot_records', 'read'),

-- Operator permissions (read + limited write operations)
('operator', 'servers', 'read'),
('operator', 'volumes', 'read'),
('operator', 'snapshots', 'read'),
('operator', 'networks', 'write'),
('operator', 'subnets', 'read'),
('operator', 'ports', 'read'),
('operator', 'floatingips', 'read'),
('operator', 'domains', 'read'),
('operator', 'projects', 'read'),
('operator', 'flavors', 'write'),
('operator', 'images', 'read'),
('operator', 'hypervisors', 'read'),
('operator', 'history', 'read'),
('operator', 'snapshot_policy_sets', 'read'),
('operator', 'snapshot_assignments', 'write'),
('operator', 'snapshot_exclusions', 'write'),
('operator', 'snapshot_runs', 'read'),
('operator', 'snapshot_records', 'read'),

-- Admin permissions (full access except user management)
('admin', 'servers', 'admin'),
('admin', 'volumes', 'admin'),
('admin', 'snapshots', 'admin'),
('admin', 'networks', 'admin'),
('admin', 'subnets', 'admin'),
('admin', 'ports', 'admin'),
('admin', 'floatingips', 'admin'),
('admin', 'domains', 'admin'),
('admin', 'projects', 'admin'),
('admin', 'flavors', 'admin'),
('admin', 'images', 'admin'),
('admin', 'hypervisors', 'admin'),
('admin', 'history', 'admin'),
('admin', 'audit', 'read'),
('admin', 'snapshot_policy_sets', 'admin'),
('admin', 'snapshot_assignments', 'admin'),
('admin', 'snapshot_exclusions', 'admin'),
('admin', 'snapshot_runs', 'admin'),
('admin', 'snapshot_records', 'admin'),

-- Super Admin permissions (everything including user management)
('superadmin', 'servers', 'admin'),
('superadmin', 'volumes', 'admin'),
('superadmin', 'snapshots', 'admin'),
('superadmin', 'networks', 'admin'),
('superadmin', 'subnets', 'admin'),
('superadmin', 'ports', 'admin'),
('superadmin', 'floatingips', 'admin'),
('superadmin', 'domains', 'admin'),
('superadmin', 'projects', 'admin'),
('superadmin', 'flavors', 'admin'),
('superadmin', 'images', 'admin'),
('superadmin', 'hypervisors', 'admin'),
('superadmin', 'history', 'admin'),
('superadmin', 'audit', 'admin'),
('superadmin', 'users', 'admin'),
('superadmin', 'snapshot_policy_sets', 'admin'),
('superadmin', 'snapshot_assignments', 'admin'),
('superadmin', 'snapshot_exclusions', 'admin'),
('superadmin', 'snapshot_runs', 'admin'),
('superadmin', 'snapshot_records', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
