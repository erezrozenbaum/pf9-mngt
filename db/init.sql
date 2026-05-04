-- Allow the script to continue past individual statement errors.
-- This is intentional: some CREATE OR REPLACE VIEW statements may reference
-- objects defined later in the file; those views will be created later or
-- fail silently, but all CREATE TABLE statements are independent and must run.
\set ON_ERROR_STOP 0

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
    running_vms      INTEGER DEFAULT 0,
    created_at       TIMESTAMPTZ,
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
    image_id         TEXT,
    os_distro        TEXT,
    os_version       TEXT,
    created_at       TIMESTAMPTZ,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_servers_os_distro ON servers(os_distro);
CREATE INDEX IF NOT EXISTS idx_servers_image_id ON servers(image_id);
-- B9.1: compound and lookups
CREATE INDEX IF NOT EXISTS idx_servers_project_status ON servers(project_id, status);
CREATE INDEX IF NOT EXISTS idx_servers_hypervisor ON servers(hypervisor_hostname);
CREATE INDEX IF NOT EXISTS idx_servers_last_seen ON servers(last_seen_at DESC);

-- Example: volumes
CREATE TABLE IF NOT EXISTS volumes (
    id               TEXT PRIMARY KEY,
    name             TEXT,
    project_id       TEXT REFERENCES projects(id),
    size_gb          INTEGER,
    status           TEXT,
    volume_type      TEXT,
    server_id        TEXT,
    bootable         BOOLEAN,
    created_at       TIMESTAMPTZ,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_volumes_server_id ON volumes(server_id);
-- B9.1: compound
CREATE INDEX IF NOT EXISTS idx_volumes_project_status ON volumes(project_id, status);

-- Example: networks / subnets / ports / routers / fips
CREATE TABLE IF NOT EXISTS networks (
    id             TEXT PRIMARY KEY,
    name           TEXT,
    project_id     TEXT REFERENCES projects(id),
    status         TEXT,
    admin_state_up BOOLEAN,
    is_shared      BOOLEAN,
    is_external    BOOLEAN,
    raw_json       JSONB,
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_networks_status ON networks(status);

CREATE TABLE IF NOT EXISTS subnets (
    id           TEXT PRIMARY KEY,
    name         TEXT,
    network_id   TEXT REFERENCES networks(id),
    cidr         TEXT,
    gateway_ip   TEXT,
    enable_dhcp  BOOLEAN,
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
    status        TEXT,
    ip_addresses  JSONB,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ports_status ON ports(status);

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
    os_distro     TEXT,
    os_version    TEXT,
    os_type       TEXT,
    min_disk      INTEGER,
    min_ram       INTEGER,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_images_os_distro ON images(os_distro);

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
-- B9.1: project-scoped listing and volume lookup
CREATE INDEX IF NOT EXISTS idx_snapshots_project_created ON snapshots(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_volume_id ON snapshots(volume_id);

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
    os_distro       TEXT,
    os_version      TEXT,
    os_type         TEXT,
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
    running_vms        INTEGER,
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
    image_id              TEXT,
    os_distro             TEXT,
    os_version            TEXT,
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
    server_id    TEXT,
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
    project_name TEXT,
    tenant_name  TEXT,
    domain_name  TEXT,
    domain_id    TEXT,
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
    id             BIGSERIAL PRIMARY KEY,
    network_id     TEXT NOT NULL,
    name           TEXT,
    project_id     TEXT,
    status         TEXT,
    admin_state_up BOOLEAN,
    is_shared      BOOLEAN,
    is_external    BOOLEAN,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash    TEXT NOT NULL,
    raw_json       JSONB
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
    enable_dhcp  BOOLEAN,
    ip_version   INTEGER,
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
    status        TEXT,
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
    v.raw_json->'attachments'->0->>'server_id' AS server_id,
    (SELECT srv.name FROM servers srv WHERE srv.id = (v.raw_json->'attachments'->0->>'server_id')) AS server_name,
    v.raw_json->'attachments'->0->>'device' AS device,
    v.raw_json->'attachments'->0->>'host_name' AS attach_host
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
    name         TEXT,
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
    detected_in_run_id BIGINT REFERENCES inventory_runs(id),
    reason       TEXT,
    raw_json_snapshot JSONB
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

-- =====================================================================
-- DEPARTMENTS — Organisational groups for nav visibility
-- (must exist before user_roles which has a FK to departments)
-- =====================================================================
CREATE TABLE IF NOT EXISTS departments (
    id                   SERIAL PRIMARY KEY,
    name                 VARCHAR(100) NOT NULL UNIQUE,
    description          TEXT,
    is_active            BOOLEAN NOT NULL DEFAULT true,
    sort_order           INTEGER NOT NULL DEFAULT 0,
    default_nav_item_key TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO departments (name, description, sort_order, default_nav_item_key) VALUES
    ('Engineering',         'Engineering and development team',                               1, NULL),
    ('Tier1 Support',       'Tier 1 support team',                                           2, NULL),
    ('Tier2 Support',       'Tier 2 support team',                                           3, NULL),
    ('Tier3 Support',       'Tier 3 support team',                                           4, NULL),
    ('Sales',               'Sales team',                                                    5, NULL),
    ('Marketing',           'Marketing team',                                                6, NULL),
    ('Management',          'Management and leadership',                                     7, NULL),
    ('Account Management',  'Client-facing account managers — per-tenant portfolio view',    8, 'account_manager_dashboard'),
    ('Executive Leadership','MSP leadership — fleet-wide executive overview',                9, 'executive_dashboard')
ON CONFLICT (name) DO NOTHING;

-- User roles for the management system (separate from OpenStack roles)
CREATE TABLE IF NOT EXISTS user_roles (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(255) NOT NULL UNIQUE,
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',
    department_id INTEGER REFERENCES departments(id),
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
    created_at TIMESTAMPTZ DEFAULT now(),
    -- Batch progress columns (v1.26.0)
    total_batches       INTEGER DEFAULT 0,
    completed_batches   INTEGER DEFAULT 0,
    current_batch       INTEGER DEFAULT 0,
    quota_blocked       INTEGER DEFAULT 0,
    batch_size_config   INTEGER DEFAULT 20,
    batch_delay_sec     NUMERIC(5,1) DEFAULT 5.0,
    progress_pct        NUMERIC(5,1) DEFAULT 0.0,
    estimated_finish_at TIMESTAMPTZ
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
-- B9.1: compound (time-range queries per VM)
CREATE INDEX IF NOT EXISTS idx_snapshot_records_vm_created ON snapshot_records(vm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_snapshot ON snapshot_records(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_action ON snapshot_records(action);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_policy ON snapshot_records(policy_name);
CREATE INDEX IF NOT EXISTS idx_snapshot_records_created_at ON snapshot_records(created_at);

-- On-demand snapshot pipeline runs (API → scheduler signaling)
CREATE TABLE IF NOT EXISTS snapshot_on_demand_runs (
    id          BIGSERIAL PRIMARY KEY,
    job_id      UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    triggered_by VARCHAR(255),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    steps       JSONB DEFAULT '[]'::jsonb,
    error       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_snapshot_on_demand_status ON snapshot_on_demand_runs(status);
CREATE INDEX IF NOT EXISTS idx_snapshot_on_demand_created ON snapshot_on_demand_runs(created_at);

-- Snapshot run batches (per-batch progress tracking, v1.26.0)
CREATE TABLE IF NOT EXISTS snapshot_run_batches (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_run_id BIGINT NOT NULL REFERENCES snapshot_runs(id) ON DELETE CASCADE,
    batch_number    INTEGER NOT NULL,
    tenant_ids      TEXT[] NOT NULL,
    tenant_names    TEXT[],
    total_volumes   INTEGER DEFAULT 0,
    completed       INTEGER DEFAULT 0,
    failed          INTEGER DEFAULT 0,
    skipped         INTEGER DEFAULT 0,
    quota_blocked   INTEGER DEFAULT 0,
    status          VARCHAR(30) DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (snapshot_run_id, batch_number)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_run_batches_run ON snapshot_run_batches(snapshot_run_id);

-- Snapshot quota blocks (volumes skipped due to quota, v1.26.0)
CREATE TABLE IF NOT EXISTS snapshot_quota_blocks (
    id              BIGSERIAL PRIMARY KEY,
    snapshot_run_id BIGINT REFERENCES snapshot_runs(id) ON DELETE CASCADE,
    volume_id       TEXT NOT NULL,
    volume_name     TEXT,
    volume_size_gb  INTEGER,
    tenant_id       TEXT NOT NULL,
    tenant_name     TEXT,
    project_id      TEXT NOT NULL,
    project_name    TEXT,
    policy_name     VARCHAR(100),
    quota_limit_gb  INTEGER,
    quota_used_gb   INTEGER,
    quota_needed_gb INTEGER,
    snapshot_quota_limit INTEGER,
    snapshot_quota_used  INTEGER,
    block_reason    TEXT,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_snapshot_quota_blocks_run ON snapshot_quota_blocks(snapshot_run_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_quota_blocks_tenant ON snapshot_quota_blocks(tenant_id);

-- Compliance reports (generated by snapshot compliance report script)
CREATE TABLE IF NOT EXISTS compliance_reports (
    id BIGSERIAL PRIMARY KEY,
    report_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    input_file TEXT,
    output_file TEXT,
    sla_days INTEGER DEFAULT 2,
    total_volumes INTEGER DEFAULT 0,
    compliant_count INTEGER DEFAULT 0,
    noncompliant_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_compliance_reports_date ON compliance_reports(report_date);

-- Compliance details (individual volume compliance records)
CREATE TABLE IF NOT EXISTS compliance_details (
    id BIGSERIAL PRIMARY KEY,
    report_id BIGINT REFERENCES compliance_reports(id) ON DELETE CASCADE,
    volume_id TEXT NOT NULL,
    volume_name TEXT,
    tenant_id TEXT,
    tenant_name TEXT,
    project_id TEXT,
    project_name TEXT,
    domain_id TEXT,
    domain_name TEXT,
    vm_id TEXT,
    vm_name TEXT,
    policy_name TEXT,
    retention_days INTEGER,
    last_snapshot_at TIMESTAMPTZ,
    days_since_snapshot NUMERIC,
    is_compliant BOOLEAN DEFAULT false,
    compliance_status TEXT,  -- 'Compliant', 'Non-Compliant', 'No Snapshots', etc.
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_compliance_details_report ON compliance_details(report_id);
CREATE INDEX IF NOT EXISTS idx_compliance_details_volume ON compliance_details(volume_id);
CREATE INDEX IF NOT EXISTS idx_compliance_details_tenant ON compliance_details(tenant_id);
CREATE INDEX IF NOT EXISTS idx_compliance_details_project ON compliance_details(project_id);
CREATE INDEX IF NOT EXISTS idx_compliance_details_compliant ON compliance_details(is_compliant);

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
('viewer', 'dashboard', 'read'),
('viewer', 'monitoring', 'read'),
('viewer', 'history', 'read'),
('viewer', 'audit', 'read'),
('viewer', 'users', 'read'),

-- Operator permissions (read + limited write operations)
('operator', 'servers', 'read'),
('operator', 'volumes', 'read'),
('operator', 'snapshots', 'read'),
('operator', 'networks', 'read'),
('operator', 'networks', 'write'),
('operator', 'subnets', 'read'),
('operator', 'ports', 'read'),
('operator', 'floatingips', 'read'),
('operator', 'domains', 'read'),
('operator', 'projects', 'read'),
('operator', 'flavors', 'read'),
('operator', 'flavors', 'write'),
('operator', 'images', 'read'),
('operator', 'hypervisors', 'read'),
('operator', 'history', 'read'),
('operator', 'snapshot_policy_sets', 'read'),
('operator', 'snapshot_assignments', 'read'),
('operator', 'snapshot_assignments', 'write'),
('operator', 'snapshot_exclusions', 'read'),
('operator', 'snapshot_exclusions', 'write'),
('operator', 'snapshot_runs', 'read'),
('operator', 'snapshot_records', 'read'),
('operator', 'dashboard', 'read'),
('operator', 'monitoring', 'read'),
('operator', 'audit', 'read'),
('operator', 'users', 'read'),

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
('admin', 'api_metrics', 'admin'),
('admin', 'system_logs', 'admin'),
('admin', 'audit', 'read'),
('admin', 'snapshot_policy_sets', 'admin'),
('admin', 'snapshot_assignments', 'admin'),
('admin', 'snapshot_exclusions', 'admin'),
('admin', 'snapshot_runs', 'admin'),
('admin', 'snapshot_records', 'admin'),
('admin', 'dashboard', 'admin'),
('admin', 'monitoring', 'write'),

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
('superadmin', 'api_metrics', 'admin'),
('superadmin', 'system_logs', 'admin'),
('superadmin', 'audit', 'admin'),
('superadmin', 'users', 'admin'),
('superadmin', 'snapshot_policy_sets', 'admin'),
('superadmin', 'snapshot_assignments', 'admin'),
('superadmin', 'snapshot_exclusions', 'admin'),
('superadmin', 'snapshot_runs', 'admin'),
('superadmin', 'snapshot_records', 'admin'),
('superadmin', 'dashboard', 'admin'),
('superadmin', 'monitoring', 'admin'),

-- Restore permissions
('viewer', 'restore', 'read'),
('operator', 'restore', 'read'),
('admin', 'restore', 'write'),
('superadmin', 'restore', 'admin'),

-- Security Groups permissions
('viewer', 'security_groups', 'read'),
('operator', 'security_groups', 'read'),
('admin', 'security_groups', 'admin'),
('superadmin', 'security_groups', 'admin'),

-- Drift Detection permissions
('viewer', 'drift', 'read'),
('operator', 'drift', 'read'),
('admin', 'drift', 'admin'),
('superadmin', 'drift', 'admin'),

-- Tenant Health View permissions
('viewer', 'tenant_health', 'read'),
('operator', 'tenant_health', 'read'),
('admin', 'tenant_health', 'read'),
('admin', 'tenant_health', 'admin'),
('superadmin', 'tenant_health', 'read'),
('superadmin', 'tenant_health', 'admin'),

-- Notification permissions (all roles can manage their own subscriptions)
('viewer', 'notifications', 'read'),
('viewer', 'notifications', 'write'),
('operator', 'notifications', 'read'),
('operator', 'notifications', 'write'),
('admin', 'notifications', 'admin'),
('superadmin', 'notifications', 'admin'),

-- Backup Management permissions
('admin', 'backup', 'read'),
('admin', 'backup', 'write'),
('superadmin', 'backup', 'admin'),

-- MFA permissions (admins can view MFA status list; users manage own MFA in code)
('admin', 'mfa', 'read'),
('admin', 'mfa', 'write'),
('superadmin', 'mfa', 'admin'),

-- Provisioning & Domain Management permissions
('admin', 'provisioning', 'read'),
('admin', 'provisioning', 'write'),
('admin', 'provisioning', 'admin'),
('superadmin', 'provisioning', 'read'),
('superadmin', 'provisioning', 'write'),
('superadmin', 'provisioning', 'admin'),

-- Granular tenant & resource deletion permissions
('admin', 'provisioning', 'tenant_disable'),
('superadmin', 'provisioning', 'tenant_disable'),
('admin', 'provisioning', 'tenant_delete'),
('superadmin', 'provisioning', 'tenant_delete'),
('admin', 'provisioning', 'resource_delete'),
('superadmin', 'provisioning', 'resource_delete'),

-- Technical role: read everything, create tenants/orgs, NO delete
('technical', 'servers', 'read'),
('technical', 'volumes', 'read'),
('technical', 'snapshots', 'read'),
('technical', 'networks', 'read'),
('technical', 'subnets', 'read'),
('technical', 'ports', 'read'),
('technical', 'floatingips', 'read'),
('technical', 'domains', 'read'),
('technical', 'projects', 'read'),
('technical', 'flavors', 'read'),
('technical', 'images', 'read'),
('technical', 'hypervisors', 'read'),
('technical', 'snapshot_policy_sets', 'read'),
('technical', 'snapshot_assignments', 'read'),
('technical', 'snapshot_exclusions', 'read'),
('technical', 'snapshot_runs', 'read'),
('technical', 'snapshot_records', 'read'),
('technical', 'dashboard', 'read'),
('technical', 'monitoring', 'read'),
('technical', 'history', 'read'),
('technical', 'audit', 'read'),
('technical', 'restore', 'read'),
('technical', 'security_groups', 'read'),
('technical', 'drift', 'read'),
('technical', 'tenant_health', 'read'),
('technical', 'notifications', 'read'),
('technical', 'notifications', 'write'),
('technical', 'backup', 'read'),
('technical', 'api_metrics', 'read'),
('technical', 'system_logs', 'read'),
('technical', 'reports', 'read'),
('technical', 'resources', 'read'),
('technical', 'metering', 'read'),
('technical', 'branding', 'read'),
('technical', 'mfa', 'read'),
-- Technical write: can create resources and provision tenants/orgs
('technical', 'resources', 'write'),
('technical', 'provisioning', 'read'),
('technical', 'provisioning', 'write'),
('technical', 'networks', 'write'),
('technical', 'flavors', 'write'),
('technical', 'snapshot_assignments', 'write'),
('technical', 'snapshot_exclusions', 'write'),
('technical', 'sla',          'read'),
('technical', 'intelligence',  'read'),

-- Missing permissions for existing roles on newer UI tabs
('viewer', 'reports', 'read'),
('viewer', 'resources', 'read'),
('viewer', 'metering', 'read'),
('viewer', 'branding', 'read'),
('operator', 'reports', 'read'),
('operator', 'resources', 'read'),
('operator', 'resources', 'write'),
('operator', 'metering', 'read'),
('operator', 'branding', 'read'),
('admin', 'reports', 'read'),
('admin', 'resources', 'read'),
('admin', 'resources', 'write'),
('admin', 'resources', 'admin'),
('admin', 'metering', 'read'),
('admin', 'metering', 'admin'),
('admin', 'branding', 'read'),
('admin', 'branding', 'write'),
('superadmin', 'reports', 'read'),
('superadmin', 'resources', 'read'),
('superadmin', 'resources', 'write'),
('superadmin', 'resources', 'admin'),
('superadmin', 'metering', 'read'),
('superadmin', 'metering', 'admin'),
('superadmin', 'branding', 'read'),
('superadmin', 'branding', 'write'),
('superadmin', 'branding', 'admin'),

-- Department & Navigation visibility permissions
('viewer',     'departments', 'read'),
('operator',   'departments', 'read'),
('admin',      'departments', 'admin'),
('superadmin', 'departments', 'admin'),
('technical',  'departments', 'read'),
('viewer',     'navigation',  'read'),
('operator',   'navigation',  'read'),
('admin',      'navigation',  'admin'),
('superadmin', 'navigation',  'admin'),
('technical',  'navigation',  'read'),

-- Copilot permissions (all roles can read/use; admin can configure)
('viewer',     'copilot', 'read'),
('operator',   'copilot', 'read'),
('technical',  'copilot', 'read'),
('admin',      'copilot', 'read'),
('admin',      'copilot', 'write'),
('admin',      'copilot', 'admin'),
('superadmin', 'copilot', 'read'),
('superadmin', 'copilot', 'write'),
('superadmin', 'copilot', 'admin'),

-- Migration Planner permissions
-- viewer: read-only access to migration projects & assessments
('viewer',     'migration', 'read'),
('operator',   'migration', 'read'),
('technical',  'migration', 'read'),
('technical',  'migration', 'write'),
-- admin: full read/write (create projects, upload, run assessment, plan waves)
('admin',      'migration', 'read'),
('admin',      'migration', 'write'),
('admin',      'migration', 'admin'),
-- superadmin: everything including approve & execute target prep
('superadmin', 'migration', 'read'),
('superadmin', 'migration', 'write'),
('superadmin', 'migration', 'admin')

ON CONFLICT (role, resource, action) DO NOTHING;

-- =====================================================================
-- EMAIL NOTIFICATION TABLES
-- =====================================================================

-- Notification channels (SMTP config; secrets stay in env vars)
CREATE TABLE IF NOT EXISTS notification_channels (
    id              SERIAL PRIMARY KEY,
    channel_type    TEXT NOT NULL DEFAULT 'email',
    name            TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default channels (email + webhook placeholders)
INSERT INTO notification_channels (channel_type, name, enabled, config)
SELECT 'email', 'Default SMTP', true, '{"from_name": "Platform9 Management"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM notification_channels WHERE channel_type = 'email' AND name = 'Default SMTP');

INSERT INTO notification_channels (channel_type, name, enabled, config)
SELECT 'slack', 'Slack Incoming Webhook', false, '{"note": "Set SLACK_WEBHOOK_URL env var to enable"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM notification_channels WHERE channel_type = 'slack' AND name = 'Slack Incoming Webhook');

INSERT INTO notification_channels (channel_type, name, enabled, config)
SELECT 'teams', 'Microsoft Teams Webhook', false, '{"note": "Set TEAMS_WEBHOOK_URL env var to enable"}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM notification_channels WHERE channel_type = 'teams' AND name = 'Microsoft Teams Webhook');

-- Per-user notification subscriptions
CREATE TABLE IF NOT EXISTS notification_preferences (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    severity_min    TEXT NOT NULL DEFAULT 'warning',
    delivery_mode   TEXT NOT NULL DEFAULT 'immediate',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (username, event_type)
);

CREATE INDEX IF NOT EXISTS idx_notification_prefs_username ON notification_preferences (username);
CREATE INDEX IF NOT EXISTS idx_notification_prefs_event    ON notification_preferences (event_type);

-- Sent notification log (with deduplication)
CREATE TABLE IF NOT EXISTS notification_log (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    event_id        TEXT,
    dedup_key       TEXT,
    subject         TEXT NOT NULL,
    body_preview    TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_notification_log_username   ON notification_log (username);
CREATE INDEX IF NOT EXISTS idx_notification_log_event_type ON notification_log (event_type);
CREATE INDEX IF NOT EXISTS idx_notification_log_dedup_key  ON notification_log (dedup_key);
CREATE INDEX IF NOT EXISTS idx_notification_log_created_at ON notification_log (created_at DESC);

-- Digest batching state per user
CREATE TABLE IF NOT EXISTS notification_digests (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL,
    email           TEXT NOT NULL,
    events_json     JSONB NOT NULL DEFAULT '[]',
    last_sent_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (username)
);

-- =====================================================================
-- SNAPSHOT RESTORE TABLES
-- =====================================================================

-- Restore jobs (each restore operation is a tracked job)
CREATE TABLE IF NOT EXISTS restore_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_by VARCHAR(255) NOT NULL,
    executed_by VARCHAR(255),
    project_id TEXT NOT NULL,
    project_name TEXT,
    vm_id TEXT NOT NULL,
    vm_name TEXT,
    restore_point_id TEXT NOT NULL,        -- Cinder snapshot ID used as restore point
    restore_point_name TEXT,
    mode VARCHAR(20) NOT NULL DEFAULT 'NEW',  -- 'NEW' (side-by-side) or 'REPLACE'
    ip_strategy VARCHAR(30) NOT NULL DEFAULT 'NEW_IPS',  -- 'NEW_IPS', 'TRY_SAME_IPS', 'SAME_IPS_OR_FAIL'
    requested_name TEXT,                    -- Name for the new VM
    boot_mode VARCHAR(30) NOT NULL DEFAULT 'BOOT_FROM_VOLUME',  -- 'BOOT_FROM_VOLUME' or 'BOOT_FROM_IMAGE'
    status VARCHAR(30) NOT NULL DEFAULT 'PLANNED',  -- PLANNED, PENDING, RUNNING, SUCCEEDED, FAILED, CANCELED, INTERRUPTED
    plan_json JSONB NOT NULL,               -- Full plan as generated and approved
    result_json JSONB,                      -- new_server_id, new_volume_id, new_port_ids, new_ips, etc.
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    last_heartbeat TIMESTAMPTZ,             -- Updated per step for staleness detection
    canceled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_project ON restore_jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_vm ON restore_jobs(vm_id);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_status ON restore_jobs(status);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_created_at ON restore_jobs(created_at);
-- B9.1: compound for active-jobs dashboard query
CREATE INDEX IF NOT EXISTS idx_restore_jobs_status_created ON restore_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_restore_jobs_created_by ON restore_jobs(created_by);
-- Prevent concurrent restores for the same VM
CREATE UNIQUE INDEX IF NOT EXISTS idx_restore_jobs_vm_running
    ON restore_jobs(vm_id) WHERE status IN ('PENDING', 'RUNNING');

-- Restore job steps (each step in the state machine)
CREATE TABLE IF NOT EXISTS restore_job_steps (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES restore_jobs(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    step_name VARCHAR(60) NOT NULL,         -- VALIDATE_LIVE_STATE, CREATE_VOLUME_FROM_SNAPSHOT, etc.
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',  -- PENDING, RUNNING, SUCCEEDED, FAILED, SKIPPED
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    details_json JSONB,                     -- Step-specific input/output data
    error_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_restore_job_steps_job ON restore_job_steps(job_id);
CREATE INDEX IF NOT EXISTS idx_restore_job_steps_status ON restore_job_steps(status);

-- =====================================================================
-- VIEW: v_recent_changes (for audit/compliance UI)
-- =====================================================================
CREATE OR REPLACE VIEW v_recent_changes AS
SELECT
    resource_type, resource_id, resource_name,
    project_id, project_name, domain_id, domain_name,
    status, created_at, modified_at, deleted_at, change_type,
    COALESCE(modified_at, created_at, deleted_at) AS recorded_at
FROM (
    SELECT
        'server'::text    AS resource_type,
        s.id              AS resource_id,
        s.name            AS resource_name,
        s.project_id      AS project_id,
        p.name            AS project_name,
        d.id              AS domain_id,
        d.name            AS domain_name,
        s.status,
        s.created_at,
        s.last_seen_at    AS modified_at,
        NULL::TIMESTAMPTZ AS deleted_at,
        'active'::text    AS change_type
    FROM servers s
    LEFT JOIN projects p ON s.project_id = p.id
    LEFT JOIN domains d ON p.domain_id = d.id
    UNION ALL
    SELECT 'volume'::text, v.id, v.name, v.project_id, p.name, d.id, d.name,
        v.status, v.created_at, v.last_seen_at, NULL::TIMESTAMPTZ, 'active'::text
    FROM volumes v
    LEFT JOIN projects p ON v.project_id = p.id
    LEFT JOIN domains d ON p.domain_id = d.id
    UNION ALL
    SELECT 'snapshot'::text, s.id, s.name, s.project_id, p.name, d.id, d.name,
        s.status, s.created_at, s.last_seen_at, NULL::TIMESTAMPTZ, 'active'::text
    FROM snapshots s
    LEFT JOIN projects p ON s.project_id = p.id
    LEFT JOIN domains d ON p.domain_id = d.id
    UNION ALL
    SELECT dh.resource_type, dh.resource_id, dh.resource_name,
        NULL::text, dh.project_name, NULL::text, dh.domain_name,
        NULL::text, NULL::TIMESTAMPTZ, NULL::TIMESTAMPTZ, dh.deleted_at, 'deleted'::text
    FROM deletions_history dh
) _base;

-- =====================================================================
-- VIEW: v_most_changed_resources (for compliance/audit UI)
-- =====================================================================
-- This view summarizes the most recently changed resources (servers, volumes, snapshots, deletions).
CREATE OR REPLACE VIEW v_most_changed_resources AS
SELECT
    resource_type,
    resource_id,
    resource_name,
    project_id,
    project_name,
    domain_id,
    domain_name,
    status,
    created_at,
    modified_at,
    deleted_at,
    change_type,
    recorded_at,
    COUNT(*) OVER (PARTITION BY resource_type, resource_id) AS change_count,
    recorded_at AS last_change
FROM v_recent_changes
ORDER BY recorded_at DESC;

-- =====================================================================
-- Security Groups (Neutron)
-- =====================================================================
CREATE TABLE IF NOT EXISTS security_groups (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    description   TEXT,
    project_id    TEXT REFERENCES projects(id),
    project_name  TEXT,
    tenant_name   TEXT,
    domain_id     TEXT,
    domain_name   TEXT,
    created_at    TIMESTAMPTZ,
    updated_at    TIMESTAMPTZ,
    raw_json      JSONB,
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_security_groups_project_id ON security_groups(project_id);
CREATE INDEX IF NOT EXISTS idx_security_groups_name ON security_groups(name);
CREATE INDEX IF NOT EXISTS idx_security_groups_domain_name ON security_groups(domain_name);
CREATE INDEX IF NOT EXISTS idx_security_groups_region ON security_groups(region_id);

-- Security Group Rules (Neutron)
CREATE TABLE IF NOT EXISTS security_group_rules (
    id                  TEXT PRIMARY KEY,
    security_group_id   TEXT REFERENCES security_groups(id) ON DELETE CASCADE,
    direction           TEXT,           -- 'ingress' or 'egress'
    ethertype           TEXT,           -- 'IPv4' or 'IPv6'
    protocol            TEXT,           -- 'tcp', 'udp', 'icmp', null (any)
    port_range_min      INTEGER,
    port_range_max      INTEGER,
    remote_ip_prefix    TEXT,
    remote_group_id     TEXT,
    description         TEXT,
    project_id          TEXT,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    raw_json            JSONB,
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sg_rules_security_group_id ON security_group_rules(security_group_id);
CREATE INDEX IF NOT EXISTS idx_sg_rules_direction ON security_group_rules(direction);
CREATE INDEX IF NOT EXISTS idx_sg_rules_project_id ON security_group_rules(project_id);

-- Security Groups history
CREATE TABLE IF NOT EXISTS security_groups_history (
    id                BIGSERIAL PRIMARY KEY,
    security_group_id TEXT NOT NULL,
    name              TEXT,
    description       TEXT,
    project_id        TEXT,
    project_name      TEXT,
    tenant_name       TEXT,
    domain_id         TEXT,
    domain_name       TEXT,
    created_at        TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash       TEXT NOT NULL,
    raw_json          JSONB
);
CREATE INDEX IF NOT EXISTS idx_security_groups_history_sg_id ON security_groups_history(security_group_id);
CREATE INDEX IF NOT EXISTS idx_security_groups_history_recorded_at ON security_groups_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_security_groups_history_change_hash ON security_groups_history(security_group_id, change_hash);

-- Security Group Rules history
CREATE TABLE IF NOT EXISTS security_group_rules_history (
    id                    BIGSERIAL PRIMARY KEY,
    security_group_rule_id TEXT NOT NULL,
    security_group_id     TEXT,
    direction             TEXT,
    ethertype             TEXT,
    protocol              TEXT,
    port_range_min        INTEGER,
    port_range_max        INTEGER,
    remote_ip_prefix      TEXT,
    remote_group_id       TEXT,
    description           TEXT,
    project_id            TEXT,
    created_at            TIMESTAMPTZ,
    updated_at            TIMESTAMPTZ,
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash           TEXT NOT NULL,
    raw_json              JSONB
);
CREATE INDEX IF NOT EXISTS idx_sg_rules_history_rule_id ON security_group_rules_history(security_group_rule_id);
CREATE INDEX IF NOT EXISTS idx_sg_rules_history_recorded_at ON security_group_rules_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_sg_rules_history_change_hash ON security_group_rules_history(security_group_rule_id, change_hash);

-- =====================================================================
-- Additional metadata tables: keypairs, server groups, aggregates,
-- volume types, project quotas
-- =====================================================================

-- Keypairs (Nova SSH keys)
CREATE TABLE IF NOT EXISTS keypairs (
    name             TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    fingerprint      TEXT,
    type             TEXT,           -- 'ssh' or 'x509'
    created_at       TIMESTAMPTZ,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (name, user_id)
);
CREATE INDEX IF NOT EXISTS idx_keypairs_user_id ON keypairs(user_id);

-- Server Groups (anti-affinity / affinity)
CREATE TABLE IF NOT EXISTS server_groups (
    id               TEXT PRIMARY KEY,
    name             TEXT,
    project_id       TEXT,
    policies         TEXT[],         -- e.g. {'anti-affinity'}
    member_count     INTEGER DEFAULT 0,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Host Aggregates
CREATE TABLE IF NOT EXISTS host_aggregates (
    id               INTEGER PRIMARY KEY,
    name             TEXT,
    availability_zone TEXT,
    host_count       INTEGER DEFAULT 0,
    metadata         JSONB,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Volume Types (Cinder storage backends)
CREATE TABLE IF NOT EXISTS volume_types (
    id               TEXT PRIMARY KEY,
    name             TEXT,
    description      TEXT,
    is_public        BOOLEAN,
    extra_specs      JSONB,
    raw_json         JSONB,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Project Quotas (unified: nova + cinder + neutron)
CREATE TABLE IF NOT EXISTS project_quotas (
    project_id       TEXT NOT NULL,
    service          TEXT NOT NULL,   -- 'nova', 'cinder', 'neutron'
    resource         TEXT NOT NULL,   -- e.g. 'instances', 'cores', 'ram', 'gigabytes'
    quota_limit      INTEGER,
    in_use           INTEGER,
    reserved         INTEGER,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, service, resource)
);
CREATE INDEX IF NOT EXISTS idx_project_quotas_project ON project_quotas(project_id);
CREATE INDEX IF NOT EXISTS idx_project_quotas_service ON project_quotas(service);

-- View: Security groups with VM and network associations
CREATE OR REPLACE VIEW v_security_groups_full AS
SELECT
    sg.id AS security_group_id,
    sg.name AS security_group_name,
    sg.description,
    sg.project_id,
    sg.project_name,
    sg.tenant_name,
    sg.domain_id,
    sg.domain_name,
    sg.created_at,
    sg.updated_at,
    sg.last_seen_at,
    -- Attached VMs (via ports with this security group in raw_json)
    (SELECT COUNT(DISTINCT p2.device_id)
     FROM ports p2
     WHERE p2.device_owner LIKE 'compute:%'
       AND p2.raw_json::jsonb->'security_groups' ? sg.id
    ) AS attached_vm_count,
    -- Attached networks
    (SELECT COUNT(DISTINCT p2.network_id)
     FROM ports p2
     WHERE p2.raw_json::jsonb->'security_groups' ? sg.id
    ) AS attached_network_count,
    -- Rule counts
    (SELECT COUNT(*) FROM security_group_rules r WHERE r.security_group_id = sg.id AND r.direction = 'ingress') AS ingress_rule_count,
    (SELECT COUNT(*) FROM security_group_rules r WHERE r.security_group_id = sg.id AND r.direction = 'egress') AS egress_rule_count
FROM security_groups sg;

-- =====================================================================
-- VIEW: v_comprehensive_changes (for history/audit endpoints)
-- Uses COALESCE(NULLIF(...,'')) to prefer history-stored names over
-- live-table JOINs, handling both NULL and empty-string names.
-- Ports/volumes/floating IPs get meaningful fallbacks when unnamed.
-- =====================================================================
CREATE OR REPLACE VIEW v_comprehensive_changes AS
-- Servers
SELECT 'server' AS resource_type,
       h.server_id AS resource_id,
       COALESCE(NULLIF(h.name,''), NULLIF(s.name,'')) AS resource_name,
       h.change_hash, h.recorded_at,
       p.name AS project_name,
       d.name AS domain_name,
       NULL::TIMESTAMPTZ AS actual_time,
       'Server state/history change' AS change_description
FROM servers_history h
LEFT JOIN servers s ON h.server_id = s.id
LEFT JOIN projects p ON COALESCE(h.project_id, s.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Volumes (fallback to volume_type + truncated ID when name is empty)
SELECT 'volume', h.volume_id,
       COALESCE(NULLIF(h.name,''), NULLIF(v.name,''), COALESCE(h.volume_type, 'vol') || ' (' || LEFT(h.volume_id, 8) || ')'),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Volume state/history change'
FROM volumes_history h
LEFT JOIN volumes v ON h.volume_id = v.id
LEFT JOIN projects p ON COALESCE(h.project_id, v.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Snapshots (has project_name/domain_name directly)
SELECT 'snapshot', h.snapshot_id,
       COALESCE(NULLIF(h.name,''), NULLIF(s.name,'')),
       h.change_hash, h.recorded_at,
       COALESCE(NULLIF(h.project_name,''), s.project_name),
       COALESCE(NULLIF(h.domain_name,''), s.domain_name),
       NULL,
       'Snapshot state/history change'
FROM snapshots_history h
LEFT JOIN snapshots s ON h.snapshot_id = s.id

UNION ALL
-- Security Groups (has project_name/domain_name directly)
SELECT 'security_group', h.security_group_id,
       COALESCE(NULLIF(h.name,''), NULLIF(sg.name,'')),
       h.change_hash, h.recorded_at,
       COALESCE(NULLIF(h.project_name,''), sg.project_name),
       COALESCE(NULLIF(h.domain_name,''), sg.domain_name),
       NULL,
       'Security group state/history change'
FROM security_groups_history h
LEFT JOIN security_groups sg ON h.security_group_id = sg.id

UNION ALL
-- Security Group Rules
SELECT 'security_group_rule', h.security_group_rule_id,
       COALESCE(sg.name, '') || ' / ' || COALESCE(h.direction, '') || ' ' || COALESCE(h.protocol, 'any'),
       h.change_hash, h.recorded_at,
       COALESCE(sg.project_name, p.name),
       COALESCE(sg.domain_name, d.name),
       NULL,
       'Security group rule state/history change'
FROM security_group_rules_history h
LEFT JOIN security_groups sg ON h.security_group_id = sg.id
LEFT JOIN projects p ON COALESCE(h.project_id, sg.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Networks
SELECT 'network', h.network_id,
       COALESCE(NULLIF(h.name,''), NULLIF(n.name,'')),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Network state/history change'
FROM networks_history h
LEFT JOIN networks n ON h.network_id = n.id
LEFT JOIN projects p ON COALESCE(h.project_id, n.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Subnets (fallback to CIDR when name is empty)
SELECT 'subnet', h.subnet_id,
       COALESCE(NULLIF(h.name,''), NULLIF(sn.name,''), COALESCE(h.cidr, sn.cidr, 'subnet (' || LEFT(h.subnet_id, 8) || ')')),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Subnet state/history change'
FROM subnets_history h
LEFT JOIN subnets sn ON h.subnet_id = sn.id
LEFT JOIN networks net ON COALESCE(h.network_id, sn.network_id) = net.id
LEFT JOIN projects p ON net.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Ports (fallback to device_owner + mac_address when name is empty)
SELECT 'port', h.port_id,
       COALESCE(NULLIF(h.name,''), NULLIF(p2.name,''),
         CASE WHEN COALESCE(h.device_owner, p2.device_owner, '') <> ''
              THEN COALESCE(h.device_owner, p2.device_owner) || ' (' || LEFT(COALESCE(h.mac_address, p2.mac_address, h.port_id), 17) || ')'
              ELSE 'port (' || LEFT(h.port_id, 8) || ')'
         END),
       h.change_hash, h.recorded_at,
       pr.name, dm.name, NULL,
       'Port state/history change'
FROM ports_history h
LEFT JOIN ports p2 ON h.port_id = p2.id
LEFT JOIN projects pr ON COALESCE(h.project_id, p2.project_id) = pr.id
LEFT JOIN domains dm ON pr.domain_id = dm.id

UNION ALL
-- Floating IPs (use floating_ip as name)
SELECT 'floating_ip', h.floating_ip_id,
       COALESCE(NULLIF(h.floating_ip,''), NULLIF(fi.floating_ip,''), 'fip (' || LEFT(h.floating_ip_id, 8) || ')'),
       h.change_hash, h.recorded_at,
       pr.name, dm.name, NULL,
       'Floating IP state/history change'
FROM floating_ips_history h
LEFT JOIN floating_ips fi ON h.floating_ip_id = fi.id
LEFT JOIN projects pr ON COALESCE(h.project_id, fi.project_id) = pr.id
LEFT JOIN domains dm ON pr.domain_id = dm.id

UNION ALL
-- Routers
SELECT 'router', h.router_id,
       COALESCE(NULLIF(h.name,''), NULLIF(rt.name,'')),
       h.change_hash, h.recorded_at,
       p.name, d.name, NULL,
       'Router state/history change'
FROM routers_history h
LEFT JOIN routers rt ON h.router_id = rt.id
LEFT JOIN projects p ON COALESCE(h.project_id, rt.project_id) = p.id
LEFT JOIN domains d ON p.domain_id = d.id

UNION ALL
-- Domains
SELECT 'domain', h.domain_id,
       COALESCE(NULLIF(h.name,''), NULLIF(dom.name,'')),
       h.change_hash, h.recorded_at,
       NULL, COALESCE(NULLIF(h.name,''), NULLIF(dom.name,'')), NULL,
       'Domain state/history change'
FROM domains_history h
LEFT JOIN domains dom ON h.domain_id = dom.id

UNION ALL
-- Projects
SELECT 'project', h.project_id,
       COALESCE(NULLIF(h.name,''), NULLIF(proj.name,'')),
       h.change_hash, h.recorded_at,
       COALESCE(NULLIF(h.name,''), NULLIF(proj.name,'')),
       d.name, NULL,
       'Project state/history change'
FROM projects_history h
LEFT JOIN projects proj ON h.project_id = proj.id
LEFT JOIN domains d ON COALESCE(h.domain_id, proj.domain_id) = d.id

UNION ALL
-- Flavors
SELECT 'flavor', h.flavor_id,
       COALESCE(NULLIF(h.name,''), NULLIF(fl.name,'')),
       h.change_hash, h.recorded_at,
       NULL, NULL, NULL,
       'Flavor state/history change'
FROM flavors_history h
LEFT JOIN flavors fl ON h.flavor_id = fl.id

UNION ALL
-- Images
SELECT 'image', h.image_id,
       COALESCE(NULLIF(h.name,''), NULLIF(img.name,'')),
       h.change_hash, h.recorded_at,
       NULL, NULL, NULL,
       'Image state/history change'
FROM images_history h
LEFT JOIN images img ON h.image_id = img.id

UNION ALL
-- Hypervisors
SELECT 'hypervisor', h.hypervisor_id,
       COALESCE(NULLIF(h.hostname,''), NULLIF(hv.hostname,'')),
       h.change_hash, h.recorded_at,
       NULL, NULL, NULL,
       'Hypervisor state/history change'
FROM hypervisors_history h
LEFT JOIN hypervisors hv ON h.hypervisor_id = hv.id

UNION ALL
-- Users
SELECT 'user', h.user_id,
       COALESCE(NULLIF(h.name,''), NULLIF(u.name,'')),
       h.change_hash, h.recorded_at,
       NULL,
       d.name, NULL,
       'User state/history change'
FROM users_history h
LEFT JOIN users u ON h.user_id = u.id
LEFT JOIN domains d ON COALESCE(h.domain_id, u.domain_id) = d.id

UNION ALL
-- Roles
SELECT 'role', h.role_id,
       COALESCE(NULLIF(h.name,''), NULLIF(r.name,'')),
       h.change_hash, h.recorded_at,
       NULL,
       d.name, NULL,
       'Role state/history change'
FROM roles_history h
LEFT JOIN roles r ON h.role_id = r.id
LEFT JOIN domains d ON COALESCE(h.domain_id, r.domain_id) = d.id

UNION ALL
-- Deletions (fallback to type + truncated ID when name is empty)
SELECT dh.resource_type AS resource_type,
       dh.resource_id,
       COALESCE(NULLIF(dh.resource_name, ''), dh.resource_type || ' (' || LEFT(dh.resource_id, 8) || ')') AS resource_name,
       'deleted-' || dh.resource_id AS change_hash,
       dh.deleted_at AS recorded_at,
       dh.project_name,
       dh.domain_name,
       dh.deleted_at AS actual_time,
       'Resource deleted' AS change_description
FROM deletions_history dh;

-- =====================================================================
-- App Settings / Branding
-- =====================================================================
CREATE TABLE IF NOT EXISTS app_settings (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by    TEXT
);

-- Default branding values
INSERT INTO app_settings (key, value) VALUES
    ('company_name', 'PF9 Management System'),
    ('company_subtitle', 'Platform9 Infrastructure Management'),
    ('login_hero_title', 'Welcome to PF9 Management'),
    ('login_hero_description', 'Comprehensive Platform9 infrastructure management with real-time monitoring, snapshot automation, security group management, and full restore capabilities.'),
    ('login_hero_features', '["Real-time VM & infrastructure monitoring","Automated snapshot policies & compliance","Security group management with human-readable rules","One-click snapshot restore with storage cleanup","RBAC with LDAP authentication","Full audit trail & history tracking"]'),
    ('company_logo_url', ''),
    ('primary_color', '#667eea'),
    ('secondary_color', '#764ba2')
ON CONFLICT (key) DO NOTHING;

-- =====================================================================
-- User Preferences  (tab ordering, etc.)
-- =====================================================================
CREATE TABLE IF NOT EXISTS user_preferences (
    username      TEXT NOT NULL,
    pref_key      TEXT NOT NULL,
    pref_value    TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (username, pref_key)
);

-- =====================================================================
-- Drift Detection Engine
-- =====================================================================

-- Drift rules: defines what field changes trigger drift detection
CREATE TABLE IF NOT EXISTS drift_rules (
    id              BIGSERIAL PRIMARY KEY,
    resource_type   TEXT NOT NULL,
    field_name      TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'warning',
    description     TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_drift_rules_unique ON drift_rules(resource_type, field_name);

-- Drift events: each detected configuration drift
CREATE TABLE IF NOT EXISTS drift_events (
    id              BIGSERIAL PRIMARY KEY,
    rule_id         BIGINT REFERENCES drift_rules(id) ON DELETE SET NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT NOT NULL,
    resource_name   TEXT,
    project_id      TEXT,
    project_name    TEXT,
    domain_id       TEXT,
    domain_name     TEXT,
    severity        TEXT NOT NULL DEFAULT 'warning',
    field_changed   TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT,
    description     TEXT,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged    BOOLEAN NOT NULL DEFAULT false,
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    acknowledge_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_drift_events_detected_at ON drift_events(detected_at);
CREATE INDEX IF NOT EXISTS idx_drift_events_resource ON drift_events(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_drift_events_severity ON drift_events(severity);
CREATE INDEX IF NOT EXISTS idx_drift_events_acknowledged ON drift_events(acknowledged);
CREATE INDEX IF NOT EXISTS idx_drift_events_project ON drift_events(project_id);
-- B9.1: domain-scoped drift queries
CREATE INDEX IF NOT EXISTS idx_drift_events_domain ON drift_events(domain_id);
CREATE INDEX IF NOT EXISTS idx_drift_events_domain_ack ON drift_events(domain_id, acknowledged);

-- B9.4: referential integrity FK constraints (NOT VALID — existing data not scanned)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY'
          AND table_name='restore_jobs'
          AND constraint_name='fk_restore_jobs_project'
    ) THEN
        ALTER TABLE restore_jobs
            ADD CONSTRAINT fk_restore_jobs_project
            FOREIGN KEY (project_id) REFERENCES projects(id)
            ON DELETE RESTRICT
            NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_type='FOREIGN KEY'
          AND table_name='snapshot_records'
          AND constraint_name='fk_snapshot_records_server'
    ) THEN
        ALTER TABLE snapshot_records
            ADD CONSTRAINT fk_snapshot_records_server
            FOREIGN KEY (vm_id) REFERENCES servers(id)
            ON DELETE SET NULL
            NOT VALID;
    END IF;
END $$;

-- Seed default drift rules
INSERT INTO drift_rules (resource_type, field_name, severity, description) VALUES
    ('servers', 'flavor_id',           'critical', 'VM flavor changed — possible unauthorized resize'),
    ('servers', 'status',              'warning',  'VM status changed unexpectedly'),
    ('servers', 'vm_state',            'warning',  'VM state changed'),
    ('servers', 'hypervisor_hostname', 'info',     'VM migrated to a different hypervisor'),

    ('volumes', 'status',              'warning',  'Volume status changed'),
    ('volumes', 'server_id',           'critical', 'Volume reattached to a different VM'),
    ('volumes', 'size_gb',             'warning',  'Volume size changed — possible extend'),
    ('volumes', 'volume_type',         'warning',  'Volume type changed'),
    ('networks', 'status',             'warning',  'Network status changed'),
    ('networks', 'admin_state_up',     'critical', 'Network admin state toggled'),
    ('networks', 'is_shared',          'critical', 'Network sharing setting changed'),
    ('ports', 'device_id',             'warning',  'Port device attachment changed'),
    ('ports', 'status',                'info',     'Port status changed'),
    ('ports', 'mac_address',           'critical', 'Port MAC address changed — possible spoofing'),
    ('floating_ips', 'port_id',        'warning',  'Floating IP reassigned to a different port'),
    ('floating_ips', 'router_id',      'warning',  'Floating IP router association changed'),
    ('floating_ips', 'status',         'info',     'Floating IP status changed'),
    ('security_groups', 'description', 'info',     'Security group description changed'),
    ('snapshots', 'status',            'warning',  'Snapshot status changed'),
    ('snapshots', 'size_gb',           'info',     'Snapshot size changed'),
    ('subnets', 'gateway_ip',          'critical', 'Subnet gateway IP changed'),
    ('subnets', 'cidr',                'critical', 'Subnet CIDR changed'),
    ('subnets', 'enable_dhcp',         'warning',  'DHCP setting changed on subnet')
ON CONFLICT (resource_type, field_name) DO NOTHING;


-- =====================================================================
-- TENANT HEALTH VIEW
-- =====================================================================

DROP VIEW IF EXISTS v_tenant_health CASCADE;
CREATE OR REPLACE VIEW v_tenant_health AS
WITH server_stats AS (
    SELECT
        s.project_id,
        COUNT(*)                                             AS total_servers,
        COUNT(*) FILTER (WHERE s.status = 'ACTIVE')          AS active_servers,
        COUNT(*) FILTER (WHERE s.status = 'SHUTOFF')         AS shutoff_servers,
        COUNT(*) FILTER (WHERE s.status = 'ERROR')           AS error_servers,
        COUNT(*) FILTER (WHERE s.status NOT IN ('ACTIVE','SHUTOFF','ERROR')) AS other_servers,
        -- Compute resource allocation from flavors
        COALESCE(SUM(f.vcpus),  0)                           AS total_vcpus,
        COALESCE(SUM(f.ram_mb), 0)                           AS total_ram_mb,
        COALESCE(SUM(f.disk_gb),0)                           AS total_flavor_disk_gb,
        -- Active-only allocation
        COALESCE(SUM(f.vcpus)  FILTER (WHERE s.status = 'ACTIVE'), 0) AS active_vcpus,
        COALESCE(SUM(f.ram_mb) FILTER (WHERE s.status = 'ACTIVE'), 0) AS active_ram_mb,
        -- Count by hypervisor (for heatmap)
        COUNT(DISTINCT s.hypervisor_hostname)                AS hypervisor_count,
        -- Power state ratio
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE s.status = 'ACTIVE')
            / NULLIF(COUNT(*), 0), 1
        )                                                    AS power_on_pct
    FROM servers s
    LEFT JOIN flavors f ON s.flavor_id = f.id
    GROUP BY s.project_id
),
volume_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_volumes,
        COALESCE(SUM(size_gb), 0)                            AS total_volume_gb,
        COUNT(*) FILTER (WHERE status = 'available')         AS available_volumes,
        COUNT(*) FILTER (WHERE status = 'in-use')            AS in_use_volumes,
        COUNT(*) FILTER (WHERE status = 'error')             AS error_volumes,
        COUNT(*) FILTER (WHERE status NOT IN ('available','in-use','error')) AS other_volumes
    FROM volumes GROUP BY project_id
),
network_stats AS (
    SELECT project_id, COUNT(*) AS total_networks
    FROM networks GROUP BY project_id
),
subnet_stats AS (
    SELECT n.project_id, COUNT(*) AS total_subnets
    FROM subnets s JOIN networks n ON s.network_id = n.id
    GROUP BY n.project_id
),
port_stats AS (
    SELECT project_id, COUNT(*) AS total_ports
    FROM ports GROUP BY project_id
),
fip_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_floating_ips,
        COUNT(*) FILTER (WHERE status = 'ACTIVE')           AS active_fips,
        COUNT(*) FILTER (WHERE status = 'DOWN')             AS down_fips
    FROM floating_ips GROUP BY project_id
),
sg_stats AS (
    SELECT project_id, COUNT(*) AS total_security_groups
    FROM security_groups GROUP BY project_id
),
snap_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_snapshots,
        COUNT(*) FILTER (WHERE status = 'available')         AS available_snapshots,
        COUNT(*) FILTER (WHERE status = 'error')             AS error_snapshots,
        COALESCE(SUM(size_gb), 0)                            AS total_snapshot_gb
    FROM snapshots GROUP BY project_id
),
drift_stats AS (
    SELECT
        project_id,
        COUNT(*)                                                                          AS total_drift_events,
        COUNT(*) FILTER (WHERE severity = 'critical')                                     AS critical_drift,
        COUNT(*) FILTER (WHERE severity = 'warning')                                      AS warning_drift,
        COUNT(*) FILTER (WHERE severity = 'info')                                         AS info_drift,
        COUNT(*) FILTER (WHERE acknowledged = FALSE)                                      AS new_drift,
        COUNT(*) FILTER (WHERE detected_at >= NOW() - INTERVAL '7 days')                  AS drift_7d,
        COUNT(*) FILTER (WHERE detected_at >= NOW() - INTERVAL '30 days')                 AS drift_30d
    FROM drift_events GROUP BY project_id
),
compliance_stats AS (
    SELECT
        project_id,
        COUNT(*)                                             AS total_compliance_items,
        COUNT(*) FILTER (WHERE is_compliant = TRUE)          AS compliant_items,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE is_compliant = TRUE)
            / NULLIF(COUNT(*), 0), 1
        )                                                    AS compliance_pct
    FROM compliance_details GROUP BY project_id
)
SELECT
    p.id                          AS project_id,
    p.name                        AS project_name,
    d.id                          AS domain_id,
    d.name                        AS domain_name,
    COALESCE(ss.total_servers, 0)     AS total_servers,
    COALESCE(ss.active_servers, 0)    AS active_servers,
    COALESCE(ss.shutoff_servers, 0)   AS shutoff_servers,
    COALESCE(ss.error_servers, 0)     AS error_servers,
    COALESCE(ss.other_servers, 0)     AS other_servers,
    -- vCPU / RAM allocation
    COALESCE(ss.total_vcpus, 0)       AS total_vcpus,
    COALESCE(ss.total_ram_mb, 0)      AS total_ram_mb,
    COALESCE(ss.total_flavor_disk_gb, 0) AS total_flavor_disk_gb,
    COALESCE(ss.active_vcpus, 0)      AS active_vcpus,
    COALESCE(ss.active_ram_mb, 0)     AS active_ram_mb,
    COALESCE(ss.hypervisor_count, 0)  AS hypervisor_count,
    COALESCE(ss.power_on_pct, 0)      AS power_on_pct,
    COALESCE(vs.total_volumes, 0)     AS total_volumes,
    COALESCE(vs.total_volume_gb, 0)   AS total_volume_gb,
    COALESCE(vs.available_volumes, 0) AS available_volumes,
    COALESCE(vs.in_use_volumes, 0)    AS in_use_volumes,
    COALESCE(vs.error_volumes, 0)     AS error_volumes,
    COALESCE(vs.other_volumes, 0)     AS other_volumes,
    COALESCE(ns.total_networks, 0)        AS total_networks,
    COALESCE(sn.total_subnets, 0)         AS total_subnets,
    COALESCE(ps.total_ports, 0)           AS total_ports,
    COALESCE(fs.total_floating_ips, 0)    AS total_floating_ips,
    COALESCE(fs.active_fips, 0)           AS active_fips,
    COALESCE(fs.down_fips, 0)             AS down_fips,
    COALESCE(sgs.total_security_groups, 0) AS total_security_groups,
    COALESCE(snp.total_snapshots, 0)       AS total_snapshots,
    COALESCE(snp.available_snapshots, 0)   AS available_snapshots,
    COALESCE(snp.error_snapshots, 0)       AS error_snapshots,
    COALESCE(snp.total_snapshot_gb, 0)     AS total_snapshot_gb,
    COALESCE(dr.total_drift_events, 0) AS total_drift_events,
    COALESCE(dr.critical_drift, 0)     AS critical_drift,
    COALESCE(dr.warning_drift, 0)      AS warning_drift,
    COALESCE(dr.info_drift, 0)         AS info_drift,
    COALESCE(dr.new_drift, 0)          AS new_drift,
    COALESCE(dr.drift_7d, 0)           AS drift_7d,
    COALESCE(dr.drift_30d, 0)          AS drift_30d,
    COALESCE(cs.total_compliance_items, 0)  AS total_compliance_items,
    COALESCE(cs.compliant_items, 0)         AS compliant_items,
    COALESCE(cs.compliance_pct, 0)          AS compliance_pct,
    GREATEST(0, LEAST(100,
        100
        - LEAST(20, COALESCE(ss.error_servers, 0) * 10)
        - LEAST(10, COALESCE(ss.shutoff_servers, 0) * 2)
        - LEAST(15, COALESCE(vs.error_volumes, 0) * 5)
        - LEAST(10, COALESCE(snp.error_snapshots, 0) * 5)
        - CASE
            WHEN COALESCE(cs.total_compliance_items, 0) = 0 THEN 0
            ELSE LEAST(20, GREATEST(0, (100 - COALESCE(cs.compliance_pct, 100)) * 0.2))
          END
        - LEAST(15, COALESCE(dr.critical_drift, 0) * 5)
        - LEAST(10, COALESCE(dr.warning_drift, 0) * 2)
    ))::INT                                  AS health_score
FROM projects p
JOIN domains d ON p.domain_id = d.id
LEFT JOIN server_stats     ss  ON ss.project_id = p.id
LEFT JOIN volume_stats     vs  ON vs.project_id = p.id
LEFT JOIN network_stats    ns  ON ns.project_id = p.id
LEFT JOIN subnet_stats     sn  ON sn.project_id = p.id
LEFT JOIN port_stats       ps  ON ps.project_id = p.id
LEFT JOIN fip_stats        fs  ON fs.project_id = p.id
LEFT JOIN sg_stats         sgs ON sgs.project_id = p.id
LEFT JOIN snap_stats       snp ON snp.project_id = p.id
LEFT JOIN drift_stats      dr  ON dr.project_id = p.id
LEFT JOIN compliance_stats cs  ON cs.project_id = p.id;

-- =====================================================================
-- DATABASE BACKUP MANAGEMENT TABLES
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
    -- LDAP backup settings
    ldap_backup_enabled  BOOLEAN NOT NULL DEFAULT false,
    ldap_retention_count INT NOT NULL DEFAULT 7 CHECK (ldap_retention_count >= 1),
    ldap_retention_days  INT NOT NULL DEFAULT 30 CHECK (ldap_retention_days >= 1),
    last_ldap_backup_at  TIMESTAMPTZ,
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
    backup_target   TEXT NOT NULL DEFAULT 'database'
                    CHECK (backup_target IN ('database', 'ldap')),
    file_name       TEXT,
    file_path       TEXT,
    file_size_bytes BIGINT,
    duration_seconds FLOAT,
    initiated_by    TEXT,
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    -- Backup integrity validation (E5)
    integrity_status     TEXT CHECK (integrity_status IN ('pending', 'valid', 'invalid', 'skipped')),
    integrity_checked_at TIMESTAMPTZ,
    integrity_notes      TEXT,
    -- H7: SHA-256 checksum computed at write time, verified before restore
    integrity_hash       VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backup_history_status ON backup_history(status);
CREATE INDEX IF NOT EXISTS idx_backup_history_created ON backup_history(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_history_target ON backup_history(backup_target);

-- =====================================================================
-- MFA / TOTP TABLE
-- =====================================================================

CREATE TABLE IF NOT EXISTS user_mfa (
    id              SERIAL PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    totp_secret     TEXT NOT NULL,
    is_enabled      BOOLEAN NOT NULL DEFAULT false,
    backup_codes    TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_mfa_username ON user_mfa(username);

-- =====================================================================
-- PASSWORD RESET TOKENS (B8.1)
-- =====================================================================

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id          BIGSERIAL    PRIMARY KEY,
    username    TEXT         NOT NULL,
    token_hash  TEXT         NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ  NOT NULL DEFAULT (now() + INTERVAL '24 hours'),
    used_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prt_username   ON password_reset_tokens(username);
CREATE INDEX IF NOT EXISTS idx_prt_token_hash ON password_reset_tokens(token_hash);

-- =====================================================================
-- CUSTOMER PROVISIONING TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS provisioning_jobs (
    id              BIGSERIAL PRIMARY KEY,
    job_id          TEXT      NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    domain_name     TEXT      NOT NULL,
    project_name    TEXT      NOT NULL,
    username        TEXT      NOT NULL,
    user_email      TEXT,
    user_role       TEXT      NOT NULL DEFAULT 'member',
    -- Legacy single-network columns (kept for backward compat; use networks_config for new rows)
    network_name    TEXT,
    network_type    TEXT      DEFAULT 'vlan',
    vlan_id         INTEGER,
    subnet_cidr     TEXT,
    gateway_ip      TEXT,
    dns_nameservers TEXT[]    DEFAULT ARRAY['8.8.8.8', '8.8.4.4'],
    -- Multi-network support
    networks_config   JSONB   DEFAULT '[]',   -- requested network list from ProvisionRequest
    networks_created  JSONB   DEFAULT '[]',   -- actual created networks (ids, kind, cidr, etc.)
    -- Quotas
    quota_compute   JSONB     DEFAULT '{}',
    quota_network   JSONB     DEFAULT '{}',
    quota_storage   JSONB     DEFAULT '{}',
    -- Status & results
    status          TEXT      NOT NULL DEFAULT 'pending',
    domain_id       TEXT,
    project_id      TEXT,
    user_id         TEXT,
    network_id      TEXT,      -- legacy: id of first network created
    subnet_id       TEXT,      -- legacy: id of first subnet created
    security_group_id TEXT,
    -- Tracking
    created_by      TEXT      NOT NULL DEFAULT 'system',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_jobs_status     ON provisioning_jobs(status);
CREATE INDEX IF NOT EXISTS idx_provisioning_jobs_created_at ON provisioning_jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_provisioning_jobs_domain     ON provisioning_jobs(domain_name);

CREATE TABLE IF NOT EXISTS provisioning_steps (
    id          BIGSERIAL PRIMARY KEY,
    job_id      TEXT        NOT NULL REFERENCES provisioning_jobs(job_id) ON DELETE CASCADE,
    step_number INTEGER     NOT NULL,
    step_name   TEXT        NOT NULL,
    description TEXT,
    status      TEXT        NOT NULL DEFAULT 'pending',
    resource_id TEXT,
    detail      JSONB       DEFAULT '{}',
    error       TEXT,
    started_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_provisioning_steps_job ON provisioning_steps(job_id, step_number);

-- =====================================================================
-- ACTIVITY LOG — Central audit trail for provisioning & domain mgmt
-- =====================================================================

CREATE TABLE IF NOT EXISTS activity_log (
    id              SERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT,
    resource_name   TEXT,
    domain_id       TEXT,
    domain_name     TEXT,
    details         JSONB DEFAULT '{}',
    ip_address      TEXT,
    result          TEXT NOT NULL DEFAULT 'success',
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_activity_log_timestamp     ON activity_log (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_actor         ON activity_log (actor);
CREATE INDEX IF NOT EXISTS idx_activity_log_action        ON activity_log (action);
CREATE INDEX IF NOT EXISTS idx_activity_log_resource_type ON activity_log (resource_type);
CREATE INDEX IF NOT EXISTS idx_activity_log_domain_id     ON activity_log (domain_id);
CREATE INDEX IF NOT EXISTS idx_activity_log_result        ON activity_log (result);

-- =====================================================================
-- RUNBOOKS — Policy-as-Code operational runbooks
-- =====================================================================

-- Runbook definitions
CREATE TABLE IF NOT EXISTS runbooks (
    id              BIGSERIAL   PRIMARY KEY,
    runbook_id      TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    name            TEXT        NOT NULL UNIQUE,
    display_name    TEXT        NOT NULL,
    description     TEXT        NOT NULL DEFAULT '',
    category        TEXT        NOT NULL DEFAULT 'general',
    risk_level      TEXT        NOT NULL DEFAULT 'low',
    supports_dry_run BOOLEAN   NOT NULL DEFAULT true,
    enabled         BOOLEAN    NOT NULL DEFAULT true,
    parameters_schema JSONB    NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runbooks_name     ON runbooks(name);
CREATE INDEX IF NOT EXISTS idx_runbooks_category ON runbooks(category);
CREATE INDEX IF NOT EXISTS idx_runbooks_enabled  ON runbooks(enabled);

-- Approval policies (flexible: who triggers → who approves)
CREATE TABLE IF NOT EXISTS runbook_approval_policies (
    id                  BIGSERIAL   PRIMARY KEY,
    policy_id           TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    runbook_name        TEXT        NOT NULL,
    trigger_role        TEXT        NOT NULL DEFAULT 'operator',
    approver_role       TEXT        NOT NULL DEFAULT 'admin',
    approval_mode       TEXT        NOT NULL DEFAULT 'single_approval',
    escalation_timeout_minutes INTEGER NOT NULL DEFAULT 60,
    max_auto_executions_per_day INTEGER NOT NULL DEFAULT 50,
    enabled             BOOLEAN    NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(runbook_name, trigger_role)
);

CREATE INDEX IF NOT EXISTS idx_rbap_runbook ON runbook_approval_policies(runbook_name);
CREATE INDEX IF NOT EXISTS idx_rbap_trigger ON runbook_approval_policies(trigger_role);

-- Executions (full audit trail)
CREATE TABLE IF NOT EXISTS runbook_executions (
    id              BIGSERIAL   PRIMARY KEY,
    execution_id    TEXT        NOT NULL UNIQUE DEFAULT gen_random_uuid()::text,
    runbook_name    TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'pending_approval',
    dry_run         BOOLEAN    NOT NULL DEFAULT false,
    parameters      JSONB      NOT NULL DEFAULT '{}',
    result          JSONB      NOT NULL DEFAULT '{}',
    triggered_by    TEXT        NOT NULL,
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT,
    items_found     INTEGER     NOT NULL DEFAULT 0,
    items_actioned  INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rbe_runbook   ON runbook_executions(runbook_name);
CREATE INDEX IF NOT EXISTS idx_rbe_status    ON runbook_executions(status);
CREATE INDEX IF NOT EXISTS idx_rbe_trigger   ON runbook_executions(triggered_by);
CREATE INDEX IF NOT EXISTS idx_rbe_created   ON runbook_executions(created_at DESC);

-- Approval records (for multi-approval workflows)
CREATE TABLE IF NOT EXISTS runbook_approvals (
    id              BIGSERIAL   PRIMARY KEY,
    execution_id    TEXT        NOT NULL REFERENCES runbook_executions(execution_id) ON DELETE CASCADE,
    approver        TEXT        NOT NULL,
    decision        TEXT        NOT NULL,
    comment         TEXT        NOT NULL DEFAULT '',
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rba_execution ON runbook_approvals(execution_id);

-- Seed built-in runbook definitions
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema) VALUES
(
    'stuck_vm_remediation',
    'Stuck VM Remediation',
    'Detects VMs stuck in BUILD, ERROR, or transitional states and remediates via soft reboot → hard reboot → escalation.',
    'vm', 'medium', true,
    '{"type":"object","properties":{"stuck_threshold_minutes":{"type":"integer","default":30,"description":"Minutes a VM must be stuck before intervention"},"action":{"type":"string","enum":["soft_reboot","hard_reboot","report_only"],"default":"report_only","description":"Remediation action to take"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
),
(
    'orphan_resource_cleanup',
    'Orphan Resource Cleanup',
    'Finds orphaned ports, volumes, floating IPs, and empty networks. Cleans up to free quota and reduce clutter.',
    'network', 'low', true,
    '{"type":"object","properties":{"resource_types":{"type":"array","items":{"type":"string","enum":["ports","volumes","floating_ips","networks"]},"default":["ports","volumes","floating_ips","networks"],"description":"Which resource types to scan (ports, volumes, floating_ips, networks)"},"age_threshold_days":{"type":"integer","default":7,"description":"Only target resources older than N days"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
),
(
    'security_group_audit',
    'Security Group Audit',
    'Scans all security groups for overly permissive rules (0.0.0.0/0 on SSH, RDP, DB ports). Flags violations.',
    'security', 'low', true,
    '{"type":"object","properties":{"flag_ports":{"type":"array","items":{"type":"integer"},"default":[22,3389,3306,5432,1433,27017],"description":"Ports to flag when open to 0.0.0.0/0"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"}}}'
),
(
    'quota_threshold_check',
    'Quota Threshold Check',
    'Checks quota utilisation and flags resources exceeding configurable thresholds (default 80%). Reports on vCPUs, RAM, and instances.',
    'quota', 'low', true,
    '{"type":"object","properties":{"warning_pct":{"type":"integer","default":80,"description":"Warning threshold percentage"},"critical_pct":{"type":"integer","default":95,"description":"Critical threshold percentage"},"target_project":{"type":"string","x-lookup":"projects_optional","default":"","description":"Filter to a specific project (empty = all)"}}}'
),
(
    'diagnostics_bundle',
    'Diagnostics Bundle',
    'Collects a comprehensive diagnostics bundle: hypervisor stats, service status, agent health, resource counts, and quota summaries.',
    'diagnostics', 'low', true,
    '{"type":"object","properties":{"include_sections":{"type":"array","items":{"type":"string","enum":["hypervisors","services","agents","errors","resources","quotas"]},"default":["hypervisors","services","resources","quotas"],"description":"Sections to include in the bundle"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    risk_level = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at = now();

-- Seed new runbooks (v1.25.0)
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema) VALUES
(
    'vm_health_quickfix',
    'VM Health Quick Fix',
    'Diagnose a VM: checks power state, hypervisor, port bindings, volumes, and network. Optionally restart.',
    'vm', 'medium', true,
    '{"type":"object","properties":{"server_id":{"type":"string","x-lookup":"vms","description":"Select the VM to diagnose"},"auto_restart":{"type":"boolean","default":false,"description":"Restart the VM if issues found"},"restart_type":{"type":"string","enum":["soft","hard","guest_os"],"default":"soft","description":"Restart method"}},"required":["server_id"]}'
),
(
    'snapshot_before_escalation',
    'Snapshot Before Escalation',
    'Create a tagged snapshot before escalating to Tier 2. Captures VM state, console log, and metadata for traceability.',
    'vm', 'low', true,
    '{"type":"object","properties":{"server_id":{"type":"string","x-lookup":"vms","description":"Select the VM to snapshot"},"reference_id":{"type":"string","default":"","description":"Ticket or incident reference ID"},"tag_prefix":{"type":"string","default":"Pre-T2-escalation","description":"Tag prefix for the snapshot"}},"required":["server_id"]}'
),
(
    'upgrade_opportunity_detector',
    'Upgrade Opportunity Detector',
    'Scan tenants for upgrade opportunities: quota pressure, small flavors, old images. Estimates revenue impact. Pricing pulled from Metering configuration.',
    'quota', 'low', false,
    '{"type":"object","properties":{"quota_threshold_pct":{"type":"integer","default":80,"description":"Quota usage % to flag"},"include_flavor_analysis":{"type":"boolean","default":true,"description":"Check for small/old flavors"},"include_image_analysis":{"type":"boolean","default":true,"description":"Check for old/deprecated images"}}}'
),
(
    'monthly_executive_snapshot',
    'Monthly Executive Snapshot',
    'Generate an executive summary: total tenants, VMs, compliance %, capacity risk, revenue estimate, top risk tenants with month-over-month deltas. Pricing pulled from Metering configuration.',
    'general', 'low', false,
    '{"type":"object","properties":{"risk_top_n":{"type":"integer","default":5,"description":"Number of top risk tenants to show"},"include_deltas":{"type":"boolean","default":true,"description":"Include month-over-month deltas"}}}'
),
(
    'cost_leakage_report',
    'Cost Leakage Report',
    'Detect idle VMs, detached volumes, unused floating IPs, and oversized instances. Calculates estimated monthly waste. Pricing pulled from Metering configuration.',
    'general', 'low', false,
    '{"type":"object","properties":{"idle_cpu_threshold_pct":{"type":"integer","default":5,"description":"CPU % below which a VM is idle"},"shutoff_days_threshold":{"type":"integer","default":30,"description":"Days a VM must be SHUTOFF to flag"},"detached_volume_days":{"type":"integer","default":7,"description":"Days a volume must be detached to flag"}}}'
),
(
    'password_reset_console',
    'Reset VM Password',
    'Reset a VM password via cloud-init metadata injection and optionally open a temporary console session. Full audit trail recorded.',
    'vm', 'medium', true,
    '{"type":"object","properties":{"vm_id":{"type":"string","x-lookup":"vms","description":"Select the VM"},"new_password":{"type":"string","default":"","description":"New password (auto-generated if blank)"},"enable_console":{"type":"boolean","default":true,"description":"Enable VNC/SPICE console"},"console_expiry_minutes":{"type":"integer","default":30,"description":"Console link expiry in minutes"}},"required":["vm_id"]}'
),
(
    'security_compliance_audit',
    'Security & Compliance Audit',
    'Comprehensive audit: overly permissive security groups, stale users with no recent activity, unencrypted volumes.',
    'security', 'low', false,
    '{"type":"object","properties":{"stale_user_days":{"type":"integer","default":90,"description":"Days of inactivity to flag a user as stale"},"flag_wide_port_ranges":{"type":"boolean","default":true,"description":"Flag rules with 0-65535 port ranges"},"check_volume_encryption":{"type":"boolean","default":true,"description":"Check for unencrypted volumes"}}}'
),
(
    'user_last_login',
    'User Last Login Report',
    'List last login time for every user in the system. Flags inactive users and accounts that have never logged in.',
    'security', 'low', false,
    '{"type":"object","properties":{"days_inactive_threshold":{"type":"integer","default":30,"description":"Days without activity to flag a user as inactive"},"include_failed_logins":{"type":"boolean","default":false,"description":"Include recent failed login attempts in the report"}}}'
),
(
    'snapshot_quota_forecast',
    'Snapshot Quota Forecast',
    'Proactive daily check: for each tenant, compare current volume sizes and snapshot policies against Cinder quotas. Identifies tenants where the next snapshot cycle will fail due to insufficient gigabyte or snapshot-count quota. Recommends exact quota increases needed.',
    'security', 'low', false,
    '{"type":"object","properties":{"include_pending_policies":{"type":"boolean","default":true,"description":"Include volumes with assigned policies even if auto_snapshot is not yet enabled"},"safety_margin_pct":{"type":"integer","default":10,"description":"Extra headroom % to add when calculating if quota is sufficient"}}}'
),
-- v1.53.0 runbooks
(
    'quota_adjustment',
    'Quota Adjustment',
    'Set Nova / Neutron / Cinder quota for a project. Supports dry-run diff, cost estimation, and billing gate approval for quota increases. Core building block for the quota-increase ticket workflow.',
    'quota', 'high', true,
    '{"type":"object","required":["project_id"],"properties":{"project_id":{"type":"string","x-lookup":"projects","description":"Select the target project"},"project_name":{"type":"string","x-hidden":true,"description":"Display name (auto-filled)"},"new_vcpus":{"type":"integer","minimum":0,"description":"New vCPU quota limit (0 = no change)"},"new_ram_mb":{"type":"integer","minimum":0,"description":"New RAM quota in MB (0 = no change)"},"new_instances":{"type":"integer","minimum":0,"description":"New instance quota limit (0 = no change)"},"new_networks":{"type":"integer","minimum":0,"description":"New Neutron network quota (0 = no change)"},"new_volumes":{"type":"integer","minimum":0,"description":"New Cinder volumes quota (0 = no change)"},"new_gigabytes":{"type":"integer","minimum":0,"description":"New Cinder gigabytes quota (0 = no change)"},"reason":{"type":"string","description":"Free-text justification (written to audit log)"},"require_billing_approval":{"type":"boolean","default":true,"description":"Call billing gate when quota is being increased"}}}'
),
(
    'org_usage_report',
    'Org Usage Report',
    'Complete read-only usage and cost report for a single project/org. Returns per-resource quota utilisation, active server breakdown, storage and snapshot totals, floating IP count, cost estimate for the period, and a pre-rendered HTML body suitable for email.',
    'general', 'low', false,
    '{"type":"object","required":["project_id"],"properties":{"project_id":{"type":"string","x-lookup":"projects","description":"Select the target project"},"include_cost_estimate":{"type":"boolean","default":true,"description":"Include cost estimate table in the report"},"include_snapshot_details":{"type":"boolean","default":true,"description":"Query Cinder snapshot list for snapshot GB total"},"period_days":{"type":"integer","default":30,"minimum":1,"description":"Billing/usage period in days for cost calculations"}}}'
),
-- v1.55.0 runbooks
(
    'vm_rightsizing',
    'VM Rightsizing',
    'Analyse VM CPU and RAM utilisation from metering data over a configurable window. Identifies over-provisioned VMs, suggests a smaller cheaper flavor, and optionally performs the resize with a pre-resize snapshot for safety.',
    'compute', 'high', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope to one project (blank = all projects)"},"server_ids":{"type":"array","items":{"type":"string"},"x-lookup":"vms_multi","description":"Specific VMs to analyse (blank = all VMs in project)"},"analysis_days":{"type":"integer","default":14,"minimum":3,"description":"Days of metering history to average"},"cpu_idle_pct":{"type":"number","default":15,"description":"Max average CPU % to qualify as over-provisioned"},"ram_idle_pct":{"type":"number","default":30,"description":"Max average RAM % to qualify as over-provisioned"},"min_savings_per_month":{"type":"number","default":5,"description":"Minimum monthly USD savings for a VM to appear in results"},"require_snapshot_first":{"type":"boolean","default":true,"description":"Create a snapshot before resizing each VM"}}}'
),
(
    'capacity_forecast',
    'Capacity Forecast',
    'Runs a linear-regression forecast on hypervisor history data to project when vCPU and RAM capacity will reach the configured warning threshold. Returns weekly trend data, current utilisation, and days-to-threshold for each dimension.',
    'general', 'low', false,
    '{"type":"object","properties":{"warn_days_threshold":{"type":"integer","default":90,"description":"Raise an alert if exhaustion is projected within this many days"},"capacity_warn_pct":{"type":"number","default":80,"description":"Capacity utilisation % treated as the warning threshold"},"trigger_ticket":{"type":"boolean","default":false,"description":"Attempt to open a capacity ticket when alerts are generated (requires ticket system)"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    risk_level = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at = now();

-- v1.56.0 runbooks
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema) VALUES
(
    'disaster_recovery_drill',
    'Disaster Recovery Drill',
    'Clone VMs tagged as DR candidates into an isolated network, verify they boot successfully within the timeout, then tear down all drill resources. Provides a safe, repeatable DR validation without touching production traffic.',
    'compute', 'medium', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope drill to one project (blank = scan all projects)"},"server_ids":{"type":"array","items":{"type":"string"},"x-lookup":"vms_multi","description":"Explicit VM IDs to drill (blank = use tag_filter)"},"tag_filter":{"type":"string","default":"dr_candidate","description":"Metadata key on VMs that marks them as DR candidates"},"boot_timeout_minutes":{"type":"integer","default":10,"minimum":1,"description":"Per-VM boot poll timeout in minutes"},"max_vms":{"type":"integer","default":10,"minimum":1,"description":"Maximum number of VMs to include in a single drill run"},"network_cidr":{"type":"string","default":"192.168.99.0/24","description":"CIDR for the ephemeral isolated DR network"},"skip_teardown_on_failure":{"type":"boolean","default":false,"description":"Leave DR resources running if a VM fails to boot (for debugging)"}}}'
),
(
    'tenant_offboarding',
    'Tenant Offboarding',
    'Safely exits a customer from the platform: releases FIPs, stops VMs, removes unattached ports, disables the Keystone project, tags resources with retention metadata, notifies CRM, and emails a final usage report. Requires confirm_project_name to match exactly.',
    'provisioning', 'critical', true,
    '{"type":"object","required":["project_id","confirm_project_name"],"properties":{"project_id":{"type":"string","x-lookup":"projects","description":"Keystone project to offboard"},"confirm_project_name":{"type":"string","description":"Must exactly match the project name (safety check)"},"retention_days":{"type":"integer","default":30,"description":"Days before final resource deletion is scheduled"},"email_final_report":{"type":"boolean","default":true,"description":"Send the usage report to the customer email"},"customer_email":{"type":"string","format":"email","description":"Recipient for the final usage report email"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    risk_level = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at = now();

-- v1.57.0 runbooks (Phase C + C2)
INSERT INTO runbooks (name, display_name, description, category, risk_level, supports_dry_run, parameters_schema) VALUES
(
    'security_group_hardening',
    'Security Group Hardening',
    'Scans all security groups for overly-permissive ingress rules (0.0.0.0/0 on sensitive ports). In dry-run mode returns a proposed replacement CIDR per rule using graph adjacency data; in execute mode deletes the violating rule and creates tighter replacements.',
    'security', 'high', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope to one project (blank = all projects)"},"flag_ports":{"type":"array","items":{"type":"integer"},"default":[22,3389,5432,3306,6379,27017],"description":"Ports to flag when open to 0.0.0.0/0"},"replacement_cidr_fallback":{"type":"string","default":"10.0.0.0/8","description":"CIDR used as replacement when no graph adjacency data is available"}}}'
),
(
    'network_isolation_audit',
    'Network Isolation Audit',
    'Read-only scan for network isolation issues: shared tenant networks, cross-tenant routers, overlapping CIDRs between networks, and FIPs assigned to non-compute devices. Returns a severity-classified findings report.',
    'security', 'low', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope to one project (blank = all projects)"},"include_fip_check":{"type":"boolean","default":true,"description":"Include check for FIPs assigned to unexpected devices"}}}'
),
(
    'image_lifecycle_audit',
    'Image Lifecycle Audit',
    'Scores Glance images by age, OS EOL risk, FIP exposure, and orphan status. Returns a risk-categorised list of images that should be rebuilt or removed. Read-only.',
    'security', 'low', true,
    '{"type":"object","properties":{"target_project":{"type":"string","x-lookup":"projects_optional","description":"Scope to one project (blank = all projects)"},"max_age_days":{"type":"integer","default":365,"description":"Images older than this are flagged for rotation"},"include_unused":{"type":"boolean","default":true,"description":"Include images not currently used by any VM"}}}'
),
(
    'hypervisor_maintenance_evacuate',
    'Hypervisor Maintenance Evacuate',
    'Drains a compute hypervisor for maintenance by live-migrating (with cold-migrate fallback) all resident VMs, ordered by graph dependency depth. Optionally disables the host in Nova after a clean drain.',
    'compute', 'high', true,
    '{"type":"object","required":["hypervisor_hostname"],"properties":{"hypervisor_hostname":{"type":"string","x-lookup":"hypervisors","description":"FQDN or short hostname of the hypervisor to drain"},"migration_strategy":{"type":"string","enum":["live_first","cold_only","live_only"],"default":"live_first","description":"Migration strategy to use"},"graceful_stop_fallback":{"type":"boolean","default":true,"description":"Stop VM before cold-migrating if live migration fails"},"disable_host_after_drain":{"type":"boolean","default":true,"description":"Set nova-compute service to disabled after all VMs are cleared"},"max_concurrent_migrations":{"type":"integer","default":3,"minimum":1,"maximum":10,"description":"Maximum number of concurrent migration operations"}}}'
)
ON CONFLICT (name) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    risk_level = EXCLUDED.risk_level,
    supports_dry_run = EXCLUDED.supports_dry_run,
    parameters_schema = EXCLUDED.parameters_schema,
    updated_at = now();

INSERT INTO runbook_approval_policies (runbook_name, trigger_role, approver_role, approval_mode) VALUES
    ('stuck_vm_remediation',   'operator',   'admin',  'single_approval'),
    ('stuck_vm_remediation',   'admin',      'admin',  'auto_approve'),
    ('stuck_vm_remediation',   'superadmin', 'admin',  'auto_approve'),
    ('orphan_resource_cleanup','operator',   'admin',  'single_approval'),
    ('orphan_resource_cleanup','admin',      'admin',  'auto_approve'),
    ('orphan_resource_cleanup','superadmin', 'admin',  'auto_approve'),
    ('security_group_audit',   'operator',   'admin',  'auto_approve'),
    ('security_group_audit',   'admin',      'admin',  'auto_approve'),
    ('security_group_audit',   'superadmin', 'admin',  'auto_approve'),
    ('quota_threshold_check',  'operator',   'admin',  'auto_approve'),
    ('quota_threshold_check',  'admin',      'admin',  'auto_approve'),
    ('quota_threshold_check',  'superadmin', 'admin',  'auto_approve'),
    ('diagnostics_bundle',     'operator',   'admin',  'auto_approve'),
    ('diagnostics_bundle',     'admin',      'admin',  'auto_approve'),
    ('diagnostics_bundle',     'superadmin', 'admin',  'auto_approve'),
    -- New runbooks (v1.25.0)
    ('vm_health_quickfix',          'operator',   'admin',  'auto_approve'),
    ('vm_health_quickfix',          'admin',      'admin',  'auto_approve'),
    ('vm_health_quickfix',          'superadmin', 'admin',  'auto_approve'),
    ('snapshot_before_escalation',  'operator',   'admin',  'auto_approve'),
    ('snapshot_before_escalation',  'admin',      'admin',  'auto_approve'),
    ('snapshot_before_escalation',  'superadmin', 'admin',  'auto_approve'),
    ('upgrade_opportunity_detector','operator',   'admin',  'single_approval'),
    ('upgrade_opportunity_detector','admin',      'admin',  'auto_approve'),
    ('upgrade_opportunity_detector','superadmin', 'admin',  'auto_approve'),
    ('monthly_executive_snapshot',  'operator',   'admin',  'auto_approve'),
    ('monthly_executive_snapshot',  'admin',      'admin',  'auto_approve'),
    ('monthly_executive_snapshot',  'superadmin', 'admin',  'auto_approve'),
    ('cost_leakage_report',         'operator',   'admin',  'auto_approve'),
    ('cost_leakage_report',         'admin',      'admin',  'auto_approve'),
    ('cost_leakage_report',         'superadmin', 'admin',  'auto_approve'),
    ('password_reset_console',      'operator',   'admin',  'single_approval'),
    ('password_reset_console',      'admin',      'admin',  'auto_approve'),
    ('password_reset_console',      'superadmin', 'admin',  'auto_approve'),
    ('security_compliance_audit',   'operator',   'admin',  'single_approval'),
    ('security_compliance_audit',   'admin',      'admin',  'single_approval'),
    ('security_compliance_audit',   'superadmin', 'admin',  'auto_approve'),
    ('user_last_login',             'operator',   'admin',  'auto_approve'),
    ('user_last_login',             'admin',      'admin',  'auto_approve'),
    ('user_last_login',             'superadmin', 'admin',  'auto_approve'),
    ('snapshot_quota_forecast',     'operator',   'admin',  'auto_approve'),
    ('snapshot_quota_forecast',     'admin',      'admin',  'auto_approve'),
    ('snapshot_quota_forecast',     'superadmin', 'admin',  'auto_approve'),
    -- v1.53.0 runbooks
    ('quota_adjustment',            'operator',   'admin',  'single_approval'),
    ('quota_adjustment',            'admin',      'admin',  'auto_approve'),
    ('quota_adjustment',            'superadmin', 'admin',  'auto_approve'),
    ('org_usage_report',            'operator',   'admin',  'auto_approve'),
    ('org_usage_report',            'admin',      'admin',  'auto_approve'),
    ('org_usage_report',            'superadmin', 'admin',  'auto_approve'),
    -- v1.55.0 runbooks
    ('vm_rightsizing',              'operator',   'admin',  'single_approval'),
    ('vm_rightsizing',              'admin',      'admin',  'single_approval'),
    ('vm_rightsizing',              'superadmin', 'admin',  'auto_approve'),
    ('capacity_forecast',           'operator',   'admin',  'auto_approve'),
    ('capacity_forecast',           'admin',      'admin',  'auto_approve'),
    ('capacity_forecast',           'superadmin', 'admin',  'auto_approve'),
    -- v1.56.0 runbooks
    ('disaster_recovery_drill',     'operator',   'admin',  'single_approval'),
    ('disaster_recovery_drill',     'admin',      'admin',  'single_approval'),
    ('disaster_recovery_drill',     'superadmin', 'admin',  'single_approval'),
    ('tenant_offboarding',          'operator',   'admin',  'single_approval'),
    ('tenant_offboarding',          'admin',      'admin',  'single_approval'),
    ('tenant_offboarding',          'superadmin', 'admin',  'single_approval'),
    -- v1.57.0 runbooks
    ('security_group_hardening',          'operator',   'admin',  'single_approval'),
    ('security_group_hardening',          'admin',      'admin',  'single_approval'),
    ('security_group_hardening',          'superadmin', 'admin',  'single_approval'),
    ('network_isolation_audit',           'operator',   'admin',  'auto_approve'),
    ('network_isolation_audit',           'admin',      'admin',  'auto_approve'),
    ('network_isolation_audit',           'superadmin', 'admin',  'auto_approve'),
    ('image_lifecycle_audit',             'operator',   'admin',  'auto_approve'),
    ('image_lifecycle_audit',             'admin',      'admin',  'auto_approve'),
    ('image_lifecycle_audit',             'superadmin', 'admin',  'auto_approve'),
    ('hypervisor_maintenance_evacuate',   'operator',   'admin',  'single_approval'),
    ('hypervisor_maintenance_evacuate',   'admin',      'admin',  'single_approval'),
    ('hypervisor_maintenance_evacuate',   'superadmin', 'admin',  'single_approval')
ON CONFLICT (runbook_name, trigger_role) DO NOTHING;

-- =====================================================================
-- NAV GROUPS — Top-level navigation groups
-- =====================================================================
CREATE TABLE IF NOT EXISTS nav_groups (
    id          SERIAL PRIMARY KEY,
    key         VARCHAR(100) NOT NULL UNIQUE,
    label       VARCHAR(150) NOT NULL,
    icon        VARCHAR(50),
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    is_default  BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO nav_groups (key, label, icon, description, sort_order) VALUES
    ('inventory',            'Inventory',                    '📦', 'Infrastructure inventory and resources',         1),
    ('snapshot_management',  'Snapshot Management',          '📸', 'Snapshot lifecycle, policies, and compliance',   2),
    ('change_logs',          'Change Management & Logs',     '📋', 'History, audit trails, and drift detection',     3),
    ('customer_onboarding',  'Customer Onboarding',          '🏢', 'Domains, projects, and tenant management',       4),
    ('metering_reporting',   'Metering & Reporting',         '📊', 'API metrics, metering, reports, and health',     5),
    ('admin_tools',          'Admin Tools',                  '⚙️', 'Authentication, roles, branding, and audit',     6),
    ('technical_tools',      'Technical Tools',              '🔧', 'Backup, provisioning, and system operations',    7),
    ('intelligence_views',   'Intelligence Views',           '🧠', 'Role-specific portfolio dashboards',             0)
ON CONFLICT (key) DO NOTHING;

-- =====================================================================
-- NAV ITEMS — Individual tabs within groups
-- =====================================================================
CREATE TABLE IF NOT EXISTS nav_items (
    id            SERIAL PRIMARY KEY,
    nav_group_id  INTEGER NOT NULL REFERENCES nav_groups(id) ON DELETE CASCADE,
    key           VARCHAR(100) NOT NULL UNIQUE,
    label         VARCHAR(150) NOT NULL,
    icon          VARCHAR(50),
    route         VARCHAR(255) NOT NULL,
    resource_key  VARCHAR(100),
    description   TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    is_action     BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Inventory group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'search',          'Ops Search',      '🔍', '/search',          'search',          0),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'dashboard',       'Dashboard',       '🏠', '/dashboard',       'dashboard',       1),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'servers',         'VMs',             '',   '/servers',         'servers',         2),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'volumes',         'Volumes',         '',   '/volumes',         'volumes',         3),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'networks',        'Networks',        '🔧', '/networks',        'networks',        4),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'subnets',         'Subnets',         '',   '/subnets',         'subnets',         5),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'ports',           'Ports',           '',   '/ports',           'ports',           6),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'floatingips',     'Floating IPs',    '',   '/floatingips',     'floatingips',     7),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'security_groups', 'Security Groups', '🔒', '/security_groups', 'security_groups', 8),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'hypervisors',     'Hypervisors',     '',   '/hypervisors',     'hypervisors',     9),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'images',          'Images',          '',   '/images',          'images',          10),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'flavors',         'Flavors',         '🔧', '/flavors',         'flavors',         11),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'keypairs',        'Keypairs',        '🔑', '/keypairs',        'keypairs',        12),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'aggregates',      'Aggregates',      '🏗️', '/aggregates',      'host_aggregates', 13),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'volume_types',    'Volume Types',    '💾', '/volume_types',    'volume_types',    14),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'server_groups',   'Server Groups',   '📦', '/server_groups',   'server_groups',   15),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'quotas',          'Quotas',          '📊', '/quotas',          'project_quotas',  16),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'system_metadata', 'System Metadata', '🗂️', '/system_metadata', 'system_metadata', 17)
ON CONFLICT (key) DO NOTHING;

-- Snapshot Management group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'snapshots',            'Snapshots',            '',   '/snapshots',            'snapshots',            1),
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'snapshot-policies',    'Snapshot Policies',    '📸', '/snapshot-policies',    'snapshot_policy_sets', 2),
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'snapshot_monitor',     'Snapshot Monitor',     '🔧', '/snapshot_monitor',     'snapshot_runs',        3),
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'snapshot_compliance',  'Snapshot Compliance',  '🔧', '/snapshot_compliance',  'snapshot_records',     4),
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'restore',              'Snapshot Restore',     '🔧', '/restore',              'restore',              5),
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'restore_audit',        'Restore Audit',        '🔧', '/restore_audit',        'restore',              6),
    ((SELECT id FROM nav_groups WHERE key='snapshot_management'), 'snapshot-audit',       'Snapshot Audit',       '📋', '/snapshot-audit',       'snapshots',            7)
ON CONFLICT (key) DO NOTHING;

-- Change Management & Logs group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'history',     'History',         '',   '/history',     'history',     1),
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'audit',       'Audit',           '',   '/audit',       'audit',       2),
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'system_logs', 'System Logs',     '',   '/system_logs', 'system_logs', 3),
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'drift',       'Drift Detection', '🔍', '/drift',       'drift',       4)
ON CONFLICT (key) DO NOTHING;

-- Customer Onboarding group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'domains',            'Domains',      '',   '/domains',            'domains',      1),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'projects',           'Projects',     '',   '/projects',           'projects',     2),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'users',              'Users',        '🔧', '/users',              'users',        3),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'provisioning',       'Provisioning', '🚀', '/provisioning',       'provisioning', 4),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'domain_management',  'Domain Mgmt',  '🏢', '/domain_management',  'provisioning', 5)
ON CONFLICT (key) DO NOTHING;

-- Metering & Reporting group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'api_metrics',          'API Metrics',   '',   '/api_metrics',          'api_metrics',   1),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'metering',             'Metering',      '📊', '/metering',             'metering',      2),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'reports',              'Reports',       '📊', '/reports',              'reports',       3),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'resource_management',  'Resources',     '🔧', '/resource_management',  'resources',     4),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'tenant_health',        'Tenant Health', '🏥', '/tenant_health',        'tenant_health', 5),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'monitoring',           'Monitoring',    '',   '/monitoring',           'monitoring',    6),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'insights',             'Insights',      '🔍', '/insights',             'intelligence',  7)
ON CONFLICT (key) DO NOTHING;

-- Admin Tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'admin',              'Auth Management',  '⚙️', '/admin',              'users',              1),
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'notifications',      'Notifications',    '🔔', '/notifications',      'notifications',      2),
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'cluster_management', 'Cluster Management','🌐', '/cluster_management', 'cluster_management', 3),
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'tenant_portal',      'Tenant Portal',    '🏢', '/tenant_portal',      'tenant_portal',      4)
ON CONFLICT (key) DO NOTHING;

-- Technical Tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='technical_tools'), 'backup',    'Backup',    '💾', '/backup',    'backup',   1),
    ((SELECT id FROM nav_groups WHERE key='technical_tools'), 'runbooks',  'Runbooks',  '📋', '/runbooks',  'runbooks', 2),
    ((SELECT id FROM nav_groups WHERE key='technical_tools'), 'docs',      'Docs',      '📚', '/docs',      'docs',     3)
ON CONFLICT (key) DO NOTHING;

-- Intelligence Views group (Phase 6 — persona dashboards)
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='intelligence_views'),
     'account_manager_dashboard', 'My Portfolio',    '📋', '/account_manager_dashboard', 'sla', 1),
    ((SELECT id FROM nav_groups WHERE key='intelligence_views'),
     'executive_dashboard',       'Portfolio Health', '📊', '/executive_dashboard',       'sla', 2)
ON CONFLICT (key) DO NOTHING;

-- Mark action/config items (displayed with accent color in nav)
UPDATE nav_items SET is_action = true
WHERE key IN (
    'networks', 'security_groups', 'flavors', 'users', 'admin',
    'snapshot_monitor', 'snapshot_compliance', 'restore', 'restore_audit',
    'snapshot-policies', 'backup', 'metering', 'provisioning',
    'domain_management', 'reports', 'resource_management',
    'notifications', 'cluster_management', 'tenant_portal'
);

-- =====================================================================
-- DEPARTMENT ↔ NAV GROUP visibility (many-to-many)
-- =====================================================================
CREATE TABLE IF NOT EXISTS department_nav_groups (
    id              SERIAL PRIMARY KEY,
    department_id   INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    nav_group_id    INTEGER NOT NULL REFERENCES nav_groups(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (department_id, nav_group_id)
);

-- =====================================================================
-- DEPARTMENT ↔ NAV ITEM visibility (many-to-many, fine-grained)
-- =====================================================================
CREATE TABLE IF NOT EXISTS department_nav_items (
    id              SERIAL PRIMARY KEY,
    department_id   INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    nav_item_id     INTEGER NOT NULL REFERENCES nav_items(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (department_id, nav_item_id)
);

-- =====================================================================
-- PER-USER VISIBILITY OVERRIDES
-- =====================================================================
CREATE TABLE IF NOT EXISTS user_nav_overrides (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(255) NOT NULL,
    nav_item_id     INTEGER NOT NULL REFERENCES nav_items(id) ON DELETE CASCADE,
    override_type   VARCHAR(10) NOT NULL CHECK (override_type IN ('grant', 'deny')),
    reason          TEXT,
    created_by      VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (username, nav_item_id)
);

-- Seed: all departments can see all nav groups and items (backward compatible)
INSERT INTO department_nav_groups (department_id, nav_group_id)
SELECT d.id, g.id FROM departments d CROSS JOIN nav_groups g
ON CONFLICT (department_id, nav_group_id) DO NOTHING;

INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, i.id FROM departments d CROSS JOIN nav_items i
ON CONFLICT (department_id, nav_item_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_department_nav_groups_dept   ON department_nav_groups(department_id);
CREATE INDEX IF NOT EXISTS idx_department_nav_groups_group  ON department_nav_groups(nav_group_id);
CREATE INDEX IF NOT EXISTS idx_department_nav_items_dept    ON department_nav_items(department_id);
CREATE INDEX IF NOT EXISTS idx_department_nav_items_item    ON department_nav_items(nav_item_id);
CREATE INDEX IF NOT EXISTS idx_user_nav_overrides_user      ON user_nav_overrides(username);
CREATE INDEX IF NOT EXISTS idx_nav_items_group              ON nav_items(nav_group_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_department        ON user_roles(department_id);

-- ============================================================
-- Ops Assistant — Search & Similarity (v1 + v2)
-- Unified search_documents table with tsvector + pg_trgm
-- ============================================================

-- Enable trigram extension for similarity matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Unified search documents table ──────────────────────────
CREATE TABLE IF NOT EXISTS search_documents (
    doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type        TEXT NOT NULL,
    tenant_id       TEXT,
    tenant_name     TEXT,
    domain_id       TEXT,
    domain_name     TEXT,
    resource_id     TEXT NOT NULL,
    resource_name   TEXT,
    title           TEXT NOT NULL,
    body_text       TEXT NOT NULL DEFAULT '',
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}',
    body_tsv        TSVECTOR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_documents_tsv        ON search_documents USING GIN (body_tsv);
CREATE INDEX IF NOT EXISTS idx_search_documents_title_trgm ON search_documents USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_search_documents_body_trgm  ON search_documents USING GIN (body_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_search_documents_resource   ON search_documents (doc_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_search_documents_tenant     ON search_documents (tenant_id);
CREATE INDEX IF NOT EXISTS idx_search_documents_domain     ON search_documents (domain_id);
CREATE INDEX IF NOT EXISTS idx_search_documents_ts         ON search_documents (ts DESC);
CREATE INDEX IF NOT EXISTS idx_search_documents_type       ON search_documents (doc_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_search_documents_upsert ON search_documents (doc_type, resource_id, ts);

-- Auto-update tsvector trigger
CREATE OR REPLACE FUNCTION search_documents_tsv_trigger()
RETURNS TRIGGER AS $$
BEGIN
    NEW.body_tsv := setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A')
                 || setweight(to_tsvector('english', COALESCE(NEW.resource_name, '')), 'B')
                 || setweight(to_tsvector('english', COALESCE(NEW.body_text, '')), 'C');
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_search_documents_tsv ON search_documents;
CREATE TRIGGER trg_search_documents_tsv
    BEFORE INSERT OR UPDATE ON search_documents
    FOR EACH ROW
    EXECUTE FUNCTION search_documents_tsv_trigger();

-- Indexer state tracking
CREATE TABLE IF NOT EXISTS search_indexer_state (
    doc_type        TEXT PRIMARY KEY,
    last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01T00:00:00Z',
    docs_count      INTEGER NOT NULL DEFAULT 0,
    last_run_at     TIMESTAMPTZ,
    last_run_duration_ms INTEGER
);

INSERT INTO search_indexer_state (doc_type) VALUES
    ('vm'), ('volume'), ('snapshot'), ('hypervisor'),
    ('network'), ('subnet'), ('router'), ('floating_ip'), ('port'),
    ('image'), ('flavor'), ('user'), ('security_group'),
    ('audit'), ('activity'), ('drift_event'),
    ('snapshot_run'), ('snapshot_record'),
    ('restore_job'), ('backup'),
    ('notification'), ('provisioning'),
    ('deletion'),
    ('domain'), ('project'),
    ('role'), ('role_assignment'), ('group'), ('snapshot_policy')
ON CONFLICT (doc_type) DO NOTHING;

-- Ranked search function
CREATE OR REPLACE FUNCTION search_ranked(
    query_text TEXT,
    filter_types TEXT[] DEFAULT NULL,
    filter_tenant TEXT DEFAULT NULL,
    filter_domain TEXT DEFAULT NULL,
    filter_from TIMESTAMPTZ DEFAULT NULL,
    filter_to TIMESTAMPTZ DEFAULT NULL,
    result_limit INTEGER DEFAULT 50,
    result_offset INTEGER DEFAULT 0
)
RETURNS TABLE (
    doc_id UUID, doc_type TEXT, tenant_id TEXT, tenant_name TEXT,
    domain_id TEXT, domain_name TEXT, resource_id TEXT, resource_name TEXT,
    title TEXT, ts TIMESTAMPTZ, metadata JSONB, rank REAL,
    headline_title TEXT, headline_body TEXT
) AS $$
DECLARE
    tsq tsquery;
BEGIN
    tsq := websearch_to_tsquery('english', query_text);
    RETURN QUERY
    SELECT sd.doc_id, sd.doc_type, sd.tenant_id, sd.tenant_name,
           sd.domain_id, sd.domain_name, sd.resource_id, sd.resource_name,
           sd.title, sd.ts, sd.metadata,
           ts_rank_cd(sd.body_tsv, tsq, 32) AS rank,
           ts_headline('english', sd.title, tsq,
               'MaxFragments=1, MaxWords=20, MinWords=5, StartSel=<mark>, StopSel=</mark>') AS headline_title,
           ts_headline('english', sd.body_text, tsq,
               'MaxFragments=3, MaxWords=35, MinWords=10, StartSel=<mark>, StopSel=</mark>') AS headline_body
    FROM search_documents sd
    WHERE sd.body_tsv @@ tsq
      AND (filter_types IS NULL OR sd.doc_type = ANY(filter_types))
      AND (filter_tenant IS NULL OR sd.tenant_id = filter_tenant)
      AND (filter_domain IS NULL OR sd.domain_id = filter_domain)
      AND (filter_from IS NULL OR sd.ts >= filter_from)
      AND (filter_to IS NULL OR sd.ts <= filter_to)
    ORDER BY rank DESC, sd.ts DESC
    LIMIT result_limit OFFSET result_offset;
END;
$$ LANGUAGE plpgsql;

-- Similarity search function
CREATE OR REPLACE FUNCTION search_similar(
    target_doc_id UUID,
    similarity_threshold REAL DEFAULT 0.15,
    result_limit INTEGER DEFAULT 20
)
RETURNS TABLE (
    doc_id UUID, doc_type TEXT, tenant_id TEXT, tenant_name TEXT,
    domain_id TEXT, domain_name TEXT, resource_id TEXT, resource_name TEXT,
    title TEXT, ts TIMESTAMPTZ, metadata JSONB,
    title_similarity REAL, body_similarity REAL, combined_score REAL
) AS $$
DECLARE
    target_title TEXT;
    target_body TEXT;
BEGIN
    SELECT sd.title, sd.body_text INTO target_title, target_body
    FROM search_documents sd WHERE sd.doc_id = target_doc_id;
    IF target_title IS NULL THEN
        RAISE EXCEPTION 'Document not found: %', target_doc_id;
    END IF;
    RETURN QUERY
    SELECT sd.doc_id, sd.doc_type, sd.tenant_id, sd.tenant_name,
           sd.domain_id, sd.domain_name, sd.resource_id, sd.resource_name,
           sd.title, sd.ts, sd.metadata,
           similarity(sd.title, target_title) AS title_similarity,
           similarity(sd.body_text, target_body) AS body_similarity,
           (similarity(sd.title, target_title) * 0.6 + similarity(sd.body_text, target_body) * 0.4) AS combined_score
    FROM search_documents sd
    WHERE sd.doc_id != target_doc_id
      AND (similarity(sd.title, target_title) >= similarity_threshold
           OR similarity(sd.body_text, target_body) >= similarity_threshold)
    ORDER BY combined_score DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql;

-- Search RBAC permissions
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'search', 'read'),
    ('operator',   'search', 'read'),
    ('admin',      'search', 'admin'),
    ('superadmin', 'search', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Runbook RBAC permissions
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'runbooks', 'read'),
    ('operator',   'runbooks', 'read'),
    ('operator',   'runbooks', 'write'),
    ('admin',      'runbooks', 'read'),
    ('admin',      'runbooks', 'write'),
    ('admin',      'runbooks', 'admin'),
    ('superadmin', 'runbooks', 'read'),
    ('superadmin', 'runbooks', 'write'),
    ('superadmin', 'runbooks', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Metadata inventory RBAC permissions (keypairs, host_aggregates, volume_types, server_groups, project_quotas)
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'keypairs', 'read'),
    ('operator',   'keypairs', 'read'),
    ('admin',      'keypairs', 'read'),
    ('superadmin', 'keypairs', 'admin'),
    ('viewer',     'host_aggregates', 'read'),
    ('operator',   'host_aggregates', 'read'),
    ('admin',      'host_aggregates', 'read'),
    ('superadmin', 'host_aggregates', 'admin'),
    ('viewer',     'volume_types', 'read'),
    ('operator',   'volume_types', 'read'),
    ('admin',      'volume_types', 'read'),
    ('superadmin', 'volume_types', 'admin'),
    ('viewer',     'server_groups', 'read'),
    ('operator',   'server_groups', 'read'),
    ('admin',      'server_groups', 'read'),
    ('superadmin', 'server_groups', 'admin'),
    ('viewer',     'project_quotas', 'read'),
    ('operator',   'project_quotas', 'read'),
    ('admin',      'project_quotas', 'read'),
    ('superadmin', 'project_quotas', 'admin'),
    ('viewer',     'system_metadata', 'read'),
    ('operator',   'system_metadata', 'read'),
    ('admin',      'system_metadata', 'read'),
    ('superadmin', 'system_metadata', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- =====================================================================
-- Inventory Snapshots (E6 — Phase E)
-- =====================================================================
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id              SERIAL PRIMARY KEY,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    snapshot        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_collected_at
    ON inventory_snapshots (collected_at DESC);

INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'inventory_versions', 'read'),
    ('operator',   'inventory_versions', 'read'),
    ('admin',      'inventory_versions', 'read'),
    ('superadmin', 'inventory_versions', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- =====================================================================
-- RUNBOOK DEPT VISIBILITY + EXTERNAL INTEGRATIONS (v1.52.0 / Phase A)
-- =====================================================================

-- Runbook department visibility
-- Absence of rows for a runbook = visible to ALL departments.
-- Superadmin always sees all runbooks regardless.
CREATE TABLE IF NOT EXISTS runbook_dept_visibility (
    id           SERIAL PRIMARY KEY,
    runbook_name TEXT NOT NULL REFERENCES runbooks(name) ON DELETE CASCADE,
    dept_id      INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    UNIQUE(runbook_name, dept_id)
);

CREATE INDEX IF NOT EXISTS idx_rdv_runbook ON runbook_dept_visibility(runbook_name);
CREATE INDEX IF NOT EXISTS idx_rdv_dept    ON runbook_dept_visibility(dept_id);

-- External integrations framework
-- auth_credential is Fernet-encrypted at rest (key = sha256(JWT_SECRET)).
CREATE TABLE IF NOT EXISTS external_integrations (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT UNIQUE NOT NULL,
    display_name            TEXT NOT NULL,
    integration_type        TEXT NOT NULL DEFAULT 'webhook',
    base_url                TEXT NOT NULL,
    auth_type               TEXT NOT NULL DEFAULT 'bearer',
    auth_credential         TEXT,
    auth_header_name        TEXT NOT NULL DEFAULT 'Authorization',
    request_template        JSONB NOT NULL DEFAULT '{}',
    response_approval_path  TEXT NOT NULL DEFAULT 'approved',
    response_reason_path    TEXT NOT NULL DEFAULT 'reason',
    response_charge_id_path TEXT NOT NULL DEFAULT 'charge_id',
    enabled                 BOOLEAN NOT NULL DEFAULT false,
    timeout_seconds         INTEGER NOT NULL DEFAULT 10,
    verify_ssl              BOOLEAN NOT NULL DEFAULT true,
    last_tested_at          TIMESTAMPTZ,
    last_test_status        TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ext_integ_name    ON external_integrations(name);
CREATE INDEX IF NOT EXISTS idx_ext_integ_type    ON external_integrations(integration_type);
CREATE INDEX IF NOT EXISTS idx_ext_integ_enabled ON external_integrations(enabled);

-- Role permissions for integrations resource
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',      'integrations', 'read'),
    ('admin',      'integrations', 'admin'),
    ('superadmin', 'integrations', 'read'),
    ('superadmin', 'integrations', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Seed dept visibility for the 14 shipped runbooks
-- Uses name-based lookup to be safe against ID differences across installs.
DO $$
DECLARE
    d_eng  INTEGER := (SELECT id FROM departments WHERE name = 'Engineering'   LIMIT 1);
    d_t1   INTEGER := (SELECT id FROM departments WHERE name = 'Tier1 Support' LIMIT 1);
    d_t2   INTEGER := (SELECT id FROM departments WHERE name = 'Tier2 Support' LIMIT 1);
    d_t3   INTEGER := (SELECT id FROM departments WHERE name = 'Tier3 Support' LIMIT 1);
    d_sal  INTEGER := (SELECT id FROM departments WHERE name = 'Sales'         LIMIT 1);
    d_mgmt INTEGER := (SELECT id FROM departments WHERE name = 'Management'    LIMIT 1);
BEGIN
    INSERT INTO runbook_dept_visibility (runbook_name, dept_id) VALUES
        -- stuck_vm_remediation: Engineering, Tier1, Tier2, Tier3
        ('stuck_vm_remediation', d_eng), ('stuck_vm_remediation', d_t1),
        ('stuck_vm_remediation', d_t2),  ('stuck_vm_remediation', d_t3),
        -- vm_health_quickfix: Engineering, Tier1, Tier2, Tier3
        ('vm_health_quickfix', d_eng), ('vm_health_quickfix', d_t1),
        ('vm_health_quickfix', d_t2),  ('vm_health_quickfix', d_t3),
        -- password_reset_console: Engineering, Tier1, Tier2, Tier3
        ('password_reset_console', d_eng), ('password_reset_console', d_t1),
        ('password_reset_console', d_t2),  ('password_reset_console', d_t3),
        -- snapshot_before_escalation: Engineering, Tier1, Tier2, Tier3
        ('snapshot_before_escalation', d_eng), ('snapshot_before_escalation', d_t1),
        ('snapshot_before_escalation', d_t2),  ('snapshot_before_escalation', d_t3),
        -- orphan_resource_cleanup: Engineering, Tier2, Tier3
        ('orphan_resource_cleanup', d_eng), ('orphan_resource_cleanup', d_t2),
        ('orphan_resource_cleanup', d_t3),
        -- security_group_audit: Engineering, Tier2, Tier3
        ('security_group_audit', d_eng), ('security_group_audit', d_t2),
        ('security_group_audit', d_t3),
        -- security_compliance_audit: Engineering, Tier3
        ('security_compliance_audit', d_eng), ('security_compliance_audit', d_t3),
        -- quota_threshold_check: Engineering, Tier2, Tier3, Sales, Management
        ('quota_threshold_check', d_eng), ('quota_threshold_check', d_t2),
        ('quota_threshold_check', d_t3),  ('quota_threshold_check', d_sal),
        ('quota_threshold_check', d_mgmt),
        -- snapshot_quota_forecast: Engineering, Tier3
        ('snapshot_quota_forecast', d_eng), ('snapshot_quota_forecast', d_t3),
        -- diagnostics_bundle: Engineering, Tier1, Tier2, Tier3
        ('diagnostics_bundle', d_eng), ('diagnostics_bundle', d_t1),
        ('diagnostics_bundle', d_t2),  ('diagnostics_bundle', d_t3),
        -- upgrade_opportunity_detector: Engineering, Sales, Management
        ('upgrade_opportunity_detector', d_eng), ('upgrade_opportunity_detector', d_sal),
        ('upgrade_opportunity_detector', d_mgmt),
        -- monthly_executive_snapshot: Sales, Management
        ('monthly_executive_snapshot', d_sal), ('monthly_executive_snapshot', d_mgmt),
        -- cost_leakage_report: Engineering, Tier3, Sales, Management
        ('cost_leakage_report', d_eng), ('cost_leakage_report', d_t3),
        ('cost_leakage_report', d_sal), ('cost_leakage_report', d_mgmt),
        -- user_last_login: Engineering, Management
        ('user_last_login', d_eng), ('user_last_login', d_mgmt),
        -- quota_adjustment: Tier2, Tier3, Engineering, Management
        ('quota_adjustment', d_t2),  ('quota_adjustment', d_t3),
        ('quota_adjustment', d_eng), ('quota_adjustment', d_mgmt),
        -- org_usage_report: Sales, Tier2, Tier3, Engineering, Management
        ('org_usage_report', d_sal), ('org_usage_report', d_t2),
        ('org_usage_report', d_t3),  ('org_usage_report', d_eng),
        ('org_usage_report', d_mgmt),
        -- vm_rightsizing: Engineering, Tier3, Management
        ('vm_rightsizing', d_eng), ('vm_rightsizing', d_t3), ('vm_rightsizing', d_mgmt),
        -- capacity_forecast: Engineering, Tier3, Management
        ('capacity_forecast', d_eng), ('capacity_forecast', d_t3), ('capacity_forecast', d_mgmt),
        -- disaster_recovery_drill: Engineering only
        ('disaster_recovery_drill', d_eng),
        -- tenant_offboarding: Management + Engineering
        ('tenant_offboarding', d_mgmt), ('tenant_offboarding', d_eng),
        -- v1.57.0 Phase C runbooks
        -- security_group_hardening: Engineering, Tier3
        ('security_group_hardening', d_eng), ('security_group_hardening', d_t3),
        -- network_isolation_audit: Engineering, Tier3
        ('network_isolation_audit', d_eng), ('network_isolation_audit', d_t3),
        -- image_lifecycle_audit: Engineering, Management
        ('image_lifecycle_audit', d_eng), ('image_lifecycle_audit', d_mgmt),
        -- hypervisor_maintenance_evacuate: Engineering only
        ('hypervisor_maintenance_evacuate', d_eng)
    ON CONFLICT (runbook_name, dept_id) DO NOTHING;
END $$;

-- =====================================================================
-- SUPPORT TICKET SYSTEM  (v1.58.0 — Phase T1 + T2)
-- =====================================================================

-- Ticket sequence (human-readable refs: TKT-2026-00001)
CREATE TABLE IF NOT EXISTS ticket_sequence (
    year     INT PRIMARY KEY,
    last_seq INT NOT NULL DEFAULT 0
);

-- Core tickets table
CREATE TABLE IF NOT EXISTS support_tickets (
    id                    BIGSERIAL PRIMARY KEY,
    ticket_ref            TEXT UNIQUE NOT NULL,
    title                 TEXT NOT NULL,
    description           TEXT NOT NULL DEFAULT '',
    ticket_type           TEXT NOT NULL DEFAULT 'service_request',
    status                TEXT NOT NULL DEFAULT 'open',
    priority              TEXT NOT NULL DEFAULT 'normal',
    from_dept_id          INTEGER REFERENCES departments(id),
    to_dept_id            INTEGER NOT NULL REFERENCES departments(id),
    assigned_to           TEXT,
    opened_by             TEXT NOT NULL,
    customer_name         TEXT,
    customer_email        TEXT,
    auto_notify_customer  BOOLEAN NOT NULL DEFAULT false,
    resource_type         TEXT,
    resource_id           TEXT,
    resource_name         TEXT,
    project_id            TEXT,
    project_name          TEXT,
    domain_id             TEXT,
    domain_name           TEXT,
    auto_source           TEXT,
    auto_source_id        TEXT,
    auto_blocked          BOOLEAN NOT NULL DEFAULT false,
    linked_execution_id   TEXT,
    linked_job_id         TEXT,
    linked_migration_id   TEXT,
    requires_approval     BOOLEAN NOT NULL DEFAULT false,
    approved_by           TEXT,
    approved_at           TIMESTAMPTZ,
    rejected_by           TEXT,
    rejected_at           TIMESTAMPTZ,
    approval_note         TEXT,
    sla_response_hours    INTEGER,
    sla_resolve_hours     INTEGER,
    sla_response_at       TIMESTAMPTZ,
    sla_resolve_at        TIMESTAMPTZ,
    sla_response_breached BOOLEAN NOT NULL DEFAULT false,
    sla_resolve_breached  BOOLEAN NOT NULL DEFAULT false,
    first_response_at     TIMESTAMPTZ,
    resolved_by           TEXT,
    resolved_at           TIMESTAMPTZ,
    resolution_note       TEXT,
    customer_notified_at  TIMESTAMPTZ,
    last_email_subject    TEXT,
    slack_ts              TEXT,
    slack_channel         TEXT,
    escalation_count      INTEGER NOT NULL DEFAULT 0,
    prev_dept_id          INTEGER REFERENCES departments(id),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tickets_status      ON support_tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_to_dept     ON support_tickets(to_dept_id);
CREATE INDEX IF NOT EXISTS idx_tickets_opened_by   ON support_tickets(opened_by);
CREATE INDEX IF NOT EXISTS idx_tickets_assigned_to ON support_tickets(assigned_to);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at  ON support_tickets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_ticket_ref  ON support_tickets(ticket_ref);
CREATE INDEX IF NOT EXISTS idx_tickets_auto_source ON support_tickets(auto_source, auto_source_id);
CREATE INDEX IF NOT EXISTS idx_tickets_project_id  ON support_tickets(project_id);

-- Comments / activity thread
CREATE TABLE IF NOT EXISTS ticket_comments (
    id           BIGSERIAL PRIMARY KEY,
    ticket_id    BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    author       TEXT NOT NULL,
    body         TEXT NOT NULL,
    is_internal  BOOLEAN NOT NULL DEFAULT false,
    comment_type TEXT NOT NULL DEFAULT 'comment',
    metadata     JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ticket_comments_ticket_id  ON ticket_comments(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_comments_created_at ON ticket_comments(created_at);

-- SLA policies
CREATE TABLE IF NOT EXISTS ticket_sla_policies (
    id                       SERIAL PRIMARY KEY,
    to_dept_id               INTEGER NOT NULL REFERENCES departments(id),
    ticket_type              TEXT NOT NULL DEFAULT 'incident',
    priority                 TEXT NOT NULL DEFAULT 'normal',
    response_sla_hours       INTEGER NOT NULL DEFAULT 24,
    resolution_sla_hours     INTEGER NOT NULL DEFAULT 72,
    auto_escalate_on_breach  BOOLEAN NOT NULL DEFAULT false,
    escalate_to_dept_id      INTEGER REFERENCES departments(id),
    UNIQUE(to_dept_id, ticket_type, priority)
);

-- Email templates
CREATE TABLE IF NOT EXISTS ticket_email_templates (
    id            SERIAL PRIMARY KEY,
    template_name TEXT UNIQUE NOT NULL,
    subject       TEXT NOT NULL,
    html_body     TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- RBAC permissions for tickets
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'tickets', 'read'),
    ('viewer',     'tickets', 'write'),
    ('operator',   'tickets', 'read'),
    ('operator',   'tickets', 'write'),
    ('admin',      'tickets', 'admin'),
    ('superadmin', 'tickets', 'admin'),
    ('technical',  'tickets', 'read'),
    ('technical',  'tickets', 'write')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Inventory resource (required by /system-metadata-summary endpoint)
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'inventory', 'read'),
    ('operator',   'inventory', 'read'),
    ('admin',      'inventory', 'admin'),
    ('superadmin', 'inventory', 'admin'),
    ('technical',  'inventory', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Navigation: Operations & Support group
INSERT INTO nav_groups (key, label, icon, description, sort_order)
VALUES ('operations', 'Operations & Support', '🎫',
        'Support tickets, incident management, and escalations', 9)
ON CONFLICT (key) DO NOTHING;

INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
VALUES
    ((SELECT id FROM nav_groups WHERE key = 'operations'), 'tickets',  'Support Tickets', '🎫', '/tickets',  'tickets', 1),
    ((SELECT id FROM nav_groups WHERE key = 'operations'), 'my_queue', 'My Queue',        '📥', '/my_queue', 'tickets', 2)
ON CONFLICT (key) DO NOTHING;

-- Grant Operations & Support group + items visibility to all departments
INSERT INTO department_nav_groups (department_id, nav_group_id)
SELECT d.id, (SELECT id FROM nav_groups WHERE key = 'operations')
FROM departments d
ON CONFLICT DO NOTHING;

INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM departments d, nav_items ni
WHERE ni.key IN ('tickets', 'my_queue')
ON CONFLICT DO NOTHING;
DO $$
DECLARE
    d_t1   INTEGER := (SELECT id FROM departments WHERE name = 'Tier1 Support' LIMIT 1);
    d_t2   INTEGER := (SELECT id FROM departments WHERE name = 'Tier2 Support' LIMIT 1);
    d_t3   INTEGER := (SELECT id FROM departments WHERE name = 'Tier3 Support' LIMIT 1);
    d_eng  INTEGER := (SELECT id FROM departments WHERE name = 'Engineering'   LIMIT 1);
    d_mgmt INTEGER := (SELECT id FROM departments WHERE name = 'Management'    LIMIT 1);
BEGIN
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t1, 'incident', 'critical', 1,  4,  true,  d_t2) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t1, 'incident', 'high',     4,  8,  true,  d_t2) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_t1, 'incident', 'normal',   8,  24)              ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_t1, 'service_request', 'normal', 8, 48)          ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'incident', 'critical', 2,  6,  true,  d_eng) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'critical', 4, 24, true, d_eng) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'high',    4, 24, true,  d_eng) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'normal',  4, 24, true,  d_eng) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t2, 'escalation', 'low',     4, 24, true,  d_eng) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours, auto_escalate_on_breach, escalate_to_dept_id)
    VALUES (d_t3, 'incident', 'critical',  1,  4, true,  d_eng) ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_eng, 'change_request',     'high',     8,  24)    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_eng, 'auto_change_request','high',     4,  16)    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_eng, 'auto_incident',      'critical', 2,   8)    ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt,'change_request','critical',24,72)           ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt,'change_request','high',    24,72)           ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt,'change_request','normal',  24,72)           ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;

-- =====================================================================
-- DOCS VIEWER  (v1.83.12)
-- Controls which markdown files in /docs are visible to each department.
-- Empty table means all docs are visible to everyone.
-- admin/superadmin always see all docs.
-- =====================================================================
CREATE TABLE IF NOT EXISTS doc_page_visibility (
    id          SERIAL PRIMARY KEY,
    filename    TEXT NOT NULL,
    dept_id     INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(filename, dept_id)
);

CREATE INDEX IF NOT EXISTS idx_dpv_filename ON doc_page_visibility(filename);
CREATE INDEX IF NOT EXISTS idx_dpv_dept     ON doc_page_visibility(dept_id);

-- Docs nav item under technical_tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT ng.id, 'docs', 'Docs', '📚', '/docs', 'docs', 3
FROM   nav_groups ng WHERE ng.key = 'technical_tools'
ON CONFLICT (key) DO NOTHING;

-- Seed dept visibility for all departments (all docs visible by default — no rows needed).
-- The table starts empty; admin can restrict visibility later through the UI.
    INSERT INTO ticket_sla_policies (to_dept_id, ticket_type, priority, response_sla_hours, resolution_sla_hours)
    VALUES (d_mgmt,'change_request','low',     24,72)           ON CONFLICT (to_dept_id, ticket_type, priority) DO NOTHING;
END $$;

-- Seed email templates
INSERT INTO ticket_email_templates (template_name, subject, html_body) VALUES
('ticket_created',
 '[{{ticket_ref}}] Your support request has been received — {{title}}',
 '<p>Dear {{customer_name}},</p><p>We have received your support request and assigned it reference number <strong>{{ticket_ref}}</strong>.</p><p><strong>Subject:</strong> {{title}}<br><strong>Priority:</strong> {{priority}}<br><strong>Assigned team:</strong> {{to_dept}}</p><p>We will contact you as soon as possible.</p><p>Thank you,<br>Support Team</p>'),
('ticket_resolved',
 '[{{ticket_ref}}] Your support request has been resolved — {{title}}',
 '<p>Dear {{customer_name}},</p><p>Your support request <strong>{{ticket_ref}}</strong> has been resolved.</p><p><strong>Resolution:</strong><br>{{resolution_note}}</p><p>If you have any further questions, please don''t hesitate to contact us.</p><p>Thank you,<br>Support Team</p>'),
('ticket_escalated',
 '[{{ticket_ref}}] Ticket escalated — {{title}}',
 '<p>Hello,</p><p>Ticket <strong>{{ticket_ref}}</strong> — <em>{{title}}</em> — has been escalated to your team.</p><p><strong>Escalation reason:</strong> {{escalation_reason}}<br><strong>Priority:</strong> {{priority}}<br><strong>Current status:</strong> {{status}}</p><p>Please review and take action.</p><p>Thank you,<br>Support Team</p>'),
('ticket_assigned',
 '[{{ticket_ref}}] You have been assigned a ticket — {{title}}',
 '<p>Hello {{assigned_to}},</p><p>Ticket <strong>{{ticket_ref}}</strong> has been assigned to you.</p><p><strong>Subject:</strong> {{title}}<br><strong>Priority:</strong> {{priority}}<br><strong>Type:</strong> {{ticket_type}}</p><p>Please review and take action at your earliest convenience.</p><p>Thank you,<br>Support Team</p>'),
('ticket_pending_approval',
 '[{{ticket_ref}}] Approval required — {{title}}',
 '<p>Hello,</p><p>Ticket <strong>{{ticket_ref}}</strong> requires your approval before work can proceed.</p><p><strong>Subject:</strong> {{title}}<br><strong>Requested by:</strong> {{opened_by}}<br><strong>Priority:</strong> {{priority}}</p><p>Please log in to review and approve or reject this request.</p><p>Thank you,<br>Support Team</p>'),
('ticket_sla_breach',
 '[{{ticket_ref}}] SLA BREACH — {{title}}',
 '<p><strong>SLA Breach Alert</strong></p><p>Ticket <strong>{{ticket_ref}}</strong> has breached its SLA.</p><p><strong>Subject:</strong> {{title}}<br><strong>Breached SLA:</strong> {{breach_type}}<br><strong>Priority:</strong> {{priority}}<br><strong>Assigned to:</strong> {{assigned_to}}</p><p>Immediate action is required.</p><p>Support Team</p>')
ON CONFLICT (template_name) DO NOTHING;

-- =============================================================================
-- Multi-region / Multi-cluster schema (Phase 1 — v1.73.0)
-- Canonical definitions for fresh installs.  Existing deployments upgrading
-- from < v1.73.0 should run db/migrate_multicluster.sql (or wait for
-- startup_event() in api/main.py to apply it automatically).
-- All ALTER TABLE statements use ADD COLUMN IF NOT EXISTS so this block is
-- fully idempotent when re-run against a DB that already has the columns.
-- Tables not yet created at this point (metering_*, vm_provisioning_batches)
-- will produce an ignorable error thanks to \set ON_ERROR_STOP 0 at the top.
-- =============================================================================

-- -------------------------------------------------------------------------
-- Level 1: pf9_control_planes
-- One row per PF9 installation (one Keystone, one set of admin credentials).
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pf9_control_planes (
    id                    TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    auth_url              TEXT NOT NULL,
    username              TEXT NOT NULL,
    password_enc          TEXT NOT NULL,
    user_domain           TEXT NOT NULL DEFAULT 'Default',
    project_name          TEXT NOT NULL DEFAULT 'service',
    project_domain        TEXT NOT NULL DEFAULT 'Default',
    login_url             TEXT,
    is_enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    display_color         TEXT,
    tags                  JSONB NOT NULL DEFAULT '{}',
    allow_private_network BOOLEAN NOT NULL DEFAULT FALSE,
    supported_types       TEXT[] NOT NULL DEFAULT '{openstack}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by            TEXT
);

-- -------------------------------------------------------------------------
-- Level 2: pf9_regions
-- One row per OpenStack region within a control plane.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pf9_regions (
    id                    TEXT PRIMARY KEY,
    control_plane_id      TEXT NOT NULL REFERENCES pf9_control_planes(id) ON DELETE CASCADE,
    region_name           TEXT NOT NULL,
    display_name          TEXT NOT NULL,
    is_default            BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    sync_interval_minutes INTEGER NOT NULL DEFAULT 30,
    last_sync_at          TIMESTAMPTZ,
    last_sync_status      TEXT,
    last_sync_vm_count    INTEGER,
    health_status         TEXT NOT NULL DEFAULT 'unknown',
    health_checked_at     TIMESTAMPTZ,
    priority              INTEGER NOT NULL DEFAULT 100,
    capabilities          JSONB NOT NULL DEFAULT '{}',
    latency_threshold_ms  INTEGER NOT NULL DEFAULT 2000,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (control_plane_id, region_name)
);

-- At most one default region across the entire table.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pf9_regions_one_default
    ON pf9_regions (is_default)
    WHERE (is_default = TRUE);

-- -------------------------------------------------------------------------
-- Add region_id / control_plane_id FK columns to existing resource tables.
-- All nullable — zero-regression for single-cluster deployments.
-- -------------------------------------------------------------------------

-- Core inventory
ALTER TABLE hypervisors        ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE servers            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE volumes            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE networks           ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE subnets            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE routers            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE ports              ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE floating_ips       ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE flavors            ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE images             ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshots          ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE inventory_runs     ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE security_groups    ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- Metering tables (created by migrate_metering.sql; may not exist yet on first run)
ALTER TABLE metering_resources  ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE metering_efficiency ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- Keystone identity tables: scoped to control_plane (shared across all regions)
ALTER TABLE domains          ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE projects         ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE users            ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE roles            ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);
ALTER TABLE role_assignments ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);

-- Application operation tables
ALTER TABLE provisioning_jobs    ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE provisioning_steps   ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshot_policy_sets ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshot_assignments ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE snapshot_records     ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
ALTER TABLE deletions_history    ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);

-- vm_provisioning_batches is created dynamically by vm_provisioning_routes.py on first API call.
-- Guard: skip if the table doesn't exist yet — _ensure_tables() in the API adds the column on creation.
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_name = 'vm_provisioning_batches' AND table_schema = 'public'
  ) THEN
    ALTER TABLE vm_provisioning_batches ADD COLUMN IF NOT EXISTS region_id TEXT REFERENCES pf9_regions(id);
  END IF;
END $$;

-- Per-cluster RBAC scoping (NULL = global; enforcement deferred to Phase 5)
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS region_id        TEXT REFERENCES pf9_regions(id);
ALTER TABLE user_roles ADD COLUMN IF NOT EXISTS control_plane_id TEXT REFERENCES pf9_control_planes(id);

-- Snapshot DR replication
ALTER TABLE snapshot_policy_sets ADD COLUMN IF NOT EXISTS replication_mode      TEXT;
ALTER TABLE snapshot_policy_sets ADD COLUMN IF NOT EXISTS replication_region_id TEXT REFERENCES pf9_regions(id);

-- History tables: no FK constraint, contextual audit trail only
ALTER TABLE servers_history  ADD COLUMN IF NOT EXISTS region_id        TEXT;
ALTER TABLE volumes_history  ADD COLUMN IF NOT EXISTS region_id        TEXT;
ALTER TABLE domains_history  ADD COLUMN IF NOT EXISTS control_plane_id TEXT;
ALTER TABLE projects_history ADD COLUMN IF NOT EXISTS control_plane_id TEXT;

-- -------------------------------------------------------------------------
-- cluster_sync_metrics
-- Per-region sync outcomes; feeds pf9_regions.health_status updates.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cluster_sync_metrics (
    id                 BIGSERIAL PRIMARY KEY,
    region_id          TEXT NOT NULL REFERENCES pf9_regions(id) ON DELETE CASCADE,
    sync_type          TEXT NOT NULL,
    started_at         TIMESTAMPTZ NOT NULL,
    finished_at        TIMESTAMPTZ,
    duration_ms        INTEGER,
    resource_count     INTEGER,
    error_count        INTEGER NOT NULL DEFAULT 0,
    api_calls_made     INTEGER NOT NULL DEFAULT 0,
    avg_api_latency_ms INTEGER,
    status             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cluster_sync_metrics_region_started
    ON cluster_sync_metrics (region_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cluster_sync_metrics_status_started
    ON cluster_sync_metrics (status, started_at DESC);

-- -------------------------------------------------------------------------
-- cluster_tasks
-- State machine for long-running cross-cluster operations.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cluster_tasks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_type        TEXT NOT NULL,
    operation_scope  TEXT NOT NULL DEFAULT 'cross_cluster',
    source_region_id TEXT REFERENCES pf9_regions(id),
    target_region_id TEXT REFERENCES pf9_regions(id),
    replication_mode TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    payload          JSONB NOT NULL DEFAULT '{}',
    result           JSONB NOT NULL DEFAULT '{}',
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    next_retry_at    TIMESTAMPTZ,
    retry_count      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cluster_tasks_status_retry
    ON cluster_tasks (status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_cluster_tasks_source_type
    ON cluster_tasks (source_region_id, task_type);
CREATE INDEX IF NOT EXISTS idx_cluster_tasks_target_type
    ON cluster_tasks (target_region_id, task_type);

-- -------------------------------------------------------------------------
-- Performance indexes on new FK columns
-- -------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_servers_region_id      ON servers(region_id);
CREATE INDEX IF NOT EXISTS idx_hypervisors_region_id  ON hypervisors(region_id);

-- -------------------------------------------------------------------------
-- Operational Intelligence (v1.85.0 / v1.88.0)
-- Populated by intelligence_worker and sla_worker.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operational_insights (
    id              SERIAL PRIMARY KEY,
    type            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    entity_name     TEXT,
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'open',
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    snooze_until    TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_severity CHECK (severity IN ('low','medium','high','critical')),
    CONSTRAINT valid_status   CHECK (status   IN ('open','acknowledged','snoozed','resolved','suppressed'))
);

CREATE INDEX IF NOT EXISTS idx_insights_status_severity
    ON operational_insights(status, severity);
CREATE INDEX IF NOT EXISTS idx_insights_entity
    ON operational_insights(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_insights_type
    ON operational_insights(type);
CREATE INDEX IF NOT EXISTS idx_insights_detected_at
    ON operational_insights(detected_at DESC);
-- One live insight per (type, entity_type, entity_id) — deduplication
CREATE UNIQUE INDEX IF NOT EXISTS idx_insights_dedup
    ON operational_insights(type, entity_type, entity_id)
    WHERE status IN ('open','acknowledged','snoozed');
-- Prefix index for efficient department-based type filtering (e.g. anomaly_*)
CREATE INDEX IF NOT EXISTS idx_insights_type_prefix
    ON operational_insights (type text_pattern_ops);

-- -------------------------------------------------------------------------
-- Insight Recommendations (v1.88.0 — Phase 2)
-- Actionable recommendations generated by intelligence engines.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insight_recommendations (
    id               SERIAL PRIMARY KEY,
    insight_id       INT NOT NULL REFERENCES operational_insights(id) ON DELETE CASCADE,
    action_type      TEXT NOT NULL,              -- runbook | resize | cleanup | migrate | ticket
    runbook_id       INT REFERENCES runbooks(id),
    action_payload   JSONB NOT NULL DEFAULT '{}',
    estimated_impact TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',  -- pending | executed | dismissed
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    executed_at      TIMESTAMPTZ,
    execution_id     INT REFERENCES runbook_executions(id)
);

CREATE INDEX IF NOT EXISTS idx_recs_insight ON insight_recommendations(insight_id);
CREATE INDEX IF NOT EXISTS idx_recs_status  ON insight_recommendations(status);

-- -------------------------------------------------------------------------
-- SLA Tier Templates (v1.85.0)
-- Pre-defined bronze / silver / gold / custom defaults.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_tier_templates (
    tier              TEXT PRIMARY KEY,
    uptime_pct        DECIMAL(5,3),
    rto_hours         INT,
    rpo_hours         INT,
    mtta_hours        INT,
    mttr_hours        INT,
    backup_freq_hours INT NOT NULL DEFAULT 24,
    display_name      TEXT NOT NULL
);

INSERT INTO sla_tier_templates
    (tier, uptime_pct, rto_hours, rpo_hours, mtta_hours, mttr_hours, backup_freq_hours, display_name)
VALUES
    ('bronze', 99.0,  8,  24, 8,  72, 24, 'Bronze'),
    ('silver', 99.5,  4,  12, 4,  48, 12, 'Silver'),
    ('gold',   99.9,  2,   4, 2,  24,  4, 'Gold'),
    ('custom', NULL, NULL, NULL, NULL, NULL, 24, 'Custom')
ON CONFLICT (tier) DO NOTHING;

-- -------------------------------------------------------------------------
-- SLA Commitments (v1.85.0)
-- Per-tenant SLA terms sold by the MSP.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_commitments (
    id                SERIAL,
    tenant_id         TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tier              TEXT NOT NULL DEFAULT 'custom',
    uptime_pct        DECIMAL(5,3),
    rto_hours         INT,
    rpo_hours         INT,
    mtta_hours        INT,
    mttr_hours        INT,
    backup_freq_hours INT NOT NULL DEFAULT 24,
    effective_from    DATE NOT NULL DEFAULT CURRENT_DATE,
    effective_to      DATE,
    region_id         TEXT,
    notes             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, effective_from)
);

CREATE INDEX IF NOT EXISTS idx_sla_active
    ON sla_commitments(tenant_id)
    WHERE effective_to IS NULL;

-- -------------------------------------------------------------------------
-- SLA Compliance Monthly (v1.85.0)
-- Monthly KPI rollup computed by sla_worker.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sla_compliance_monthly (
    tenant_id            TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    month                DATE NOT NULL,
    region_id            TEXT NOT NULL DEFAULT '',
    uptime_actual_pct    DECIMAL(5,3),
    rto_worst_hours      DECIMAL(6,2),
    rpo_worst_hours      DECIMAL(6,2),
    mtta_avg_hours       DECIMAL(6,2),
    mttr_avg_hours       DECIMAL(6,2),
    backup_success_pct   DECIMAL(5,2),
    breach_fields        TEXT[] NOT NULL DEFAULT '{}',
    at_risk_fields       TEXT[] NOT NULL DEFAULT '{}',
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, month, region_id)
);

CREATE INDEX IF NOT EXISTS idx_sla_compliance_tenant
    ON sla_compliance_monthly(tenant_id, month DESC);

-- -------------------------------------------------------------------------
-- MSP contract entitlements (v1.90.0)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS msp_contract_entitlements (
    id              BIGSERIAL    PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sku_name        TEXT NOT NULL DEFAULT '',
    resource        TEXT NOT NULL,
    contracted      INT  NOT NULL,
    unit_price      DECIMAL(10,4),
    region_id       TEXT,
    billing_id      TEXT,
    effective_from  DATE NOT NULL,
    effective_to    DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_entitlements_active_with_region
    ON msp_contract_entitlements(tenant_id, resource, effective_from, region_id)
    WHERE region_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_entitlements_active_global
    ON msp_contract_entitlements(tenant_id, resource, effective_from)
    WHERE region_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_entitlements_tenant
    ON msp_contract_entitlements(tenant_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_active
    ON msp_contract_entitlements(tenant_id, resource, region_id)
    WHERE effective_to IS NULL;

-- -------------------------------------------------------------------------
-- MSP labor rates (v1.90.0)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS msp_labor_rates (
    insight_type    TEXT PRIMARY KEY,
    hours_saved     DECIMAL(5,2) NOT NULL DEFAULT 0.50,
    rate_per_hour   DECIMAL(8,2) NOT NULL DEFAULT 150.00,
    description     TEXT
);
INSERT INTO msp_labor_rates (insight_type, hours_saved, rate_per_hour, description) VALUES
    ('capacity',   1.50, 150.00, 'Storage capacity planning + ticket triage'),
    ('waste',      0.50, 150.00, 'Idle VM or volume cleanup per resource'),
    ('risk',       2.00, 150.00, 'Snapshot/backup gap remediation + RCA'),
    ('drift',      1.00, 150.00, 'Drift investigation + compliance note'),
    ('anomaly',    1.50, 150.00, 'Anomaly investigation + root cause analysis'),
    ('health',     0.75, 150.00, 'Health score decline review + action'),
    ('leakage',    1.00, 150.00, 'Contract entitlement review + billing reconciliation'),
    ('sla_risk',   2.00, 150.00, 'SLA breach prevention + client communication')
ON CONFLICT (insight_type) DO NOTHING;

-- -------------------------------------------------------------------------
-- PSA webhook config (v1.90.0)
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS psa_webhook_config (
    id              SERIAL PRIMARY KEY,
    psa_name        TEXT NOT NULL,
    webhook_url     TEXT NOT NULL,
    auth_header     TEXT NOT NULL,
    min_severity    TEXT NOT NULL DEFAULT 'high',
    insight_types   TEXT[] NOT NULL DEFAULT '{}',
    region_ids      TEXT[] NOT NULL DEFAULT '{}',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -------------------------------------------------------------------------
-- RBAC: intelligence + sla permissions (v1.85.0)
-- -------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'intelligence', 'read'),
    ('operator',   'intelligence', 'read'),
    ('admin',      'intelligence', 'read'),
    ('admin',      'intelligence', 'write'),
    ('superadmin', 'intelligence', 'read'),
    ('superadmin', 'intelligence', 'write'),
    ('superadmin', 'intelligence', 'admin'),
    ('viewer',     'sla', 'read'),
    ('operator',   'sla', 'read'),
    ('admin',      'sla', 'read'),
    ('admin',      'sla', 'write'),
    ('superadmin', 'sla', 'read'),
    ('superadmin', 'sla', 'write'),
    ('superadmin', 'sla', 'admin'),
    ('superadmin', 'intelligence_settings', 'read'),
    ('superadmin', 'intelligence_settings', 'write'),
    ('admin',      'intelligence_settings', 'read'),
    ('admin',      'intelligence_settings', 'write'),
    ('superadmin', 'qbr', 'read'),
    ('superadmin', 'qbr', 'write'),
    ('admin',      'qbr', 'read'),
    ('admin',      'qbr', 'write'),
    ('operator',   'qbr', 'read'),
    ('superadmin', 'psa', 'read'),
    ('superadmin', 'psa', 'write'),
    ('admin',      'psa', 'read'),
    ('admin',      'psa', 'write'),
    -- Phase 6: account_manager role
    ('account_manager', 'intelligence',   'read'),
    ('account_manager', 'sla',            'read'),
    ('account_manager', 'servers',        'read'),
    ('account_manager', 'volumes',        'read'),
    ('account_manager', 'snapshots',      'read'),
    ('account_manager', 'networks',       'read'),
    ('account_manager', 'domains',        'read'),
    ('account_manager', 'projects',       'read'),
    ('account_manager', 'tenant_health',  'read'),
    ('account_manager', 'reports',        'read'),
    ('account_manager', 'metering',       'read'),
    ('account_manager', 'monitoring',     'read'),
    ('account_manager', 'qbr',            'write'),
    ('account_manager', 'dashboard',      'read'),
    -- Phase 6: executive role
    ('executive', 'intelligence',   'read'),
    ('executive', 'sla',            'read'),
    ('executive', 'domains',        'read'),
    ('executive', 'projects',       'read'),
    ('executive', 'tenant_health',  'read'),
    ('executive', 'monitoring',     'read'),
    ('executive', 'dashboard',      'read')
ON CONFLICT (role, resource, action) DO NOTHING;
CREATE INDEX IF NOT EXISTS idx_volumes_region_id      ON volumes(region_id);
CREATE INDEX IF NOT EXISTS idx_networks_region_id     ON networks(region_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_region_id    ON snapshots(region_id);
CREATE INDEX IF NOT EXISTS idx_domains_cp_id          ON domains(control_plane_id);
CREATE INDEX IF NOT EXISTS idx_projects_cp_id         ON projects(control_plane_id);
CREATE INDEX IF NOT EXISTS idx_users_cp_id            ON users(control_plane_id);
CREATE INDEX IF NOT EXISTS idx_prov_jobs_region_id    ON provisioning_jobs(region_id);
CREATE INDEX IF NOT EXISTS idx_snap_policy_region_id  ON snapshot_policy_sets(region_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_region_id   ON user_roles(region_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_cp_id       ON user_roles(control_plane_id);

-- =====================================================================
-- SYSTEM SETTINGS — generic key/value runtime configuration store
-- (added v1.82.18)
-- =====================================================================
CREATE TABLE IF NOT EXISTS system_settings (
    key         VARCHAR(200) PRIMARY KEY,
    value       TEXT         NOT NULL DEFAULT '',
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

INSERT INTO system_settings (key, value, description)
VALUES ('rvtools_retention_days', '30', 'Number of days to keep RVTools Excel exports on disk')
ON CONFLICT (key) DO NOTHING;

INSERT INTO system_settings (key, value, description) VALUES
  ('alert.rvtools_enabled',           'true',  'Enable rvtools failure alert emails'),
  ('alert.rvtools_recipients',        '',       'Comma-separated email addresses for rvtools alerts'),
  ('alert.rvtools_failure_threshold', '3',      'Number of consecutive failures before sending an alert'),
  ('alert.rvtools_recovery_enabled',  'true',   'Send a recovery email when rvtools succeeds after failures'),
  ('alert.rvtools_in_alert_state',    'false',  'Auto-managed: true while consecutive failures >= threshold'),
  ('alert.rvtools_last_alert_run_id', '',       'Auto-managed: run ID when last alert email was sent')
ON CONFLICT (key) DO NOTHING;

-- =========================================================================
-- TENANT PORTAL — v1.84.0 (Phase P0 + P1)
-- Added by migrate_tenant_portal.sql; mirrored here for fresh installs.
-- =========================================================================

-- Tenant action log (permanent audit trail; ephemeral Redis not sufficient)
CREATE TABLE IF NOT EXISTS tenant_action_log (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    username         VARCHAR(255) NOT NULL,
    control_plane_id TEXT         NOT NULL,
    action           VARCHAR(100) NOT NULL,
    resource_type    VARCHAR(50),
    resource_id      TEXT,
    project_id       TEXT,
    region_id        TEXT,
    ip_address       INET,
    user_agent       TEXT,
    timestamp        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    success          BOOLEAN      NOT NULL DEFAULT true,
    details          JSONB
);
CREATE INDEX IF NOT EXISTS idx_tenant_action_log_user_ts ON tenant_action_log (keystone_user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_action_log_cp_ts   ON tenant_action_log (control_plane_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_action_log_action  ON tenant_action_log (action, timestamp DESC);

-- Per-user, per-CP access allowlist (default-deny model)
CREATE TABLE IF NOT EXISTS tenant_portal_access (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    user_name        TEXT,                                    -- friendly display name for the user
    control_plane_id TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    tenant_name      TEXT,                                    -- friendly name for the tenant / org
    enabled          BOOLEAN      NOT NULL DEFAULT false,
    mfa_required     BOOLEAN      NOT NULL DEFAULT false,
    notes            TEXT,
    granted_by       TEXT,
    granted_at       TIMESTAMPTZ,
    revoked_by       TEXT,
    revoked_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (keystone_user_id, control_plane_id)
);
CREATE INDEX IF NOT EXISTS idx_tenant_portal_access_cp_enabled
    ON tenant_portal_access (control_plane_id, enabled);

-- Per-CP / per-project branding (served unauthenticated; runtime-configurable)
-- project_id = '' means global CP-level default; a Keystone project UUID
-- means an override for that specific tenant organisation.
CREATE TABLE IF NOT EXISTS tenant_portal_branding (
    control_plane_id TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    project_id       TEXT         NOT NULL DEFAULT '',
    company_name     VARCHAR(255) NOT NULL DEFAULT 'Cloud Portal',
    logo_url         TEXT,
    favicon_url      TEXT,
    primary_color    CHAR(7)      NOT NULL DEFAULT '#1A73E8',
    accent_color     CHAR(7)      NOT NULL DEFAULT '#F29900',
    support_email    TEXT,
    support_url      TEXT,
    welcome_message  TEXT,
    footer_text      TEXT,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (control_plane_id, project_id)
);

-- Tenant TOTP MFA secrets (separate from staff user_mfa; RLS-protected)
CREATE TABLE IF NOT EXISTS tenant_portal_mfa (
    id               BIGSERIAL    PRIMARY KEY,
    keystone_user_id TEXT         NOT NULL,
    control_plane_id TEXT         NOT NULL REFERENCES pf9_control_planes(id),
    totp_secret      TEXT         NOT NULL,
    backup_codes     TEXT[]       NOT NULL,
    enrolled_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_used_at     TIMESTAMPTZ,
    used_backup_codes INT[]       NOT NULL DEFAULT '{}',
    UNIQUE (keystone_user_id, control_plane_id)
);

-- Opt-in column on runbooks (default false — safe for existing data)
ALTER TABLE runbooks
    ADD COLUMN IF NOT EXISTS is_tenant_visible BOOLEAN NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS idx_runbooks_tenant_visible
    ON runbooks (is_tenant_visible) WHERE is_tenant_visible = true;

-- All enabled runbooks should be visible to tenant portal by default
UPDATE runbooks SET is_tenant_visible = true WHERE enabled = true AND is_tenant_visible = false;
-- Admin-only runbooks that tenants should NOT see
UPDATE runbooks SET is_tenant_visible = false WHERE name IN (
    -- Infrastructure / platform-admin operations
    'hypervisor_maintenance_evacuate',
    'cluster_capacity_planner',
    'capacity_forecast',
    'diagnostics_bundle',
    -- Tenant account management (admin perspective)
    'tenant_offboarding',
    'quota_adjustment',
    -- Admin-scoped reporting / intelligence tools
    'upgrade_opportunity_detector',
    'monthly_executive_snapshot',
    'cost_leakage_report',
    'org_usage_report',
    -- Forecasting tools that scan across all tenants
    'snapshot_quota_forecast',
    -- Security / compliance tools that scan ALL tenants/users (not scoped to one project)
    'image_lifecycle_audit',
    'network_isolation_audit',
    'security_compliance_audit',
    'user_last_login',
    -- Operational runbooks scoped to admin-level infrastructure actions
    'disaster_recovery_drill',
    'orphan_resource_cleanup',
    'stuck_vm_remediation'
);

-- Project-scoped runbook tags (NULL project_id = visible to all CP tenants)
CREATE TABLE IF NOT EXISTS runbook_project_tags (
    runbook_name TEXT NOT NULL REFERENCES runbooks(name) ON DELETE CASCADE,
    project_id   TEXT NOT NULL,
    PRIMARY KEY (runbook_name, project_id)
);
CREATE INDEX IF NOT EXISTS idx_runbook_project_tags_project
    ON runbook_project_tags (project_id);

-- Safe view over pf9_control_planes (hides username + password_enc)
CREATE OR REPLACE VIEW tenant_cp_view AS
    SELECT id, name, auth_url, is_enabled, display_color, tags
    FROM   pf9_control_planes
    WHERE  is_enabled = TRUE;

-- RLS: inventory tables (project_id + region_id double-scoped)
ALTER TABLE servers          ENABLE ROW LEVEL SECURITY;
ALTER TABLE volumes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots        ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshot_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE restore_jobs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_portal_mfa ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_portal_isolation ON servers;
CREATE POLICY tenant_portal_isolation ON servers
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids',  true), ','))
    );

DROP POLICY IF EXISTS tenant_portal_isolation ON volumes;
CREATE POLICY tenant_portal_isolation ON volumes
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids',  true), ','))
    );

DROP POLICY IF EXISTS tenant_portal_isolation ON snapshots;
CREATE POLICY tenant_portal_isolation ON snapshots
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids',  true), ','))
    );

DROP POLICY IF EXISTS tenant_portal_isolation ON snapshot_records;
CREATE POLICY tenant_portal_isolation ON snapshot_records
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (
        project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ','))
        AND region_id = ANY(string_to_array(current_setting('app.tenant_region_ids',  true), ','))
    );

DROP POLICY IF EXISTS tenant_portal_isolation_select ON restore_jobs;
CREATE POLICY tenant_portal_isolation_select ON restore_jobs
    AS PERMISSIVE FOR SELECT TO tenant_portal_role
    USING (project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ',')));

DROP POLICY IF EXISTS tenant_portal_isolation_insert ON restore_jobs;
CREATE POLICY tenant_portal_isolation_insert ON restore_jobs
    AS PERMISSIVE FOR INSERT TO tenant_portal_role
    WITH CHECK (project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ',')));

DROP POLICY IF EXISTS tenant_portal_isolation_update ON restore_jobs;
CREATE POLICY tenant_portal_isolation_update ON restore_jobs
    AS PERMISSIVE FOR UPDATE TO tenant_portal_role
    USING (project_id = ANY(string_to_array(current_setting('app.tenant_project_ids', true), ',')));

DROP POLICY IF EXISTS tenant_mfa_isolation ON tenant_portal_mfa;
CREATE POLICY tenant_mfa_isolation ON tenant_portal_mfa
    AS PERMISSIVE FOR ALL TO tenant_portal_role
    USING (
        keystone_user_id = current_setting('app.tenant_keystone_user_id', true)
        AND control_plane_id = current_setting('app.tenant_cp_id', true)
    )
    WITH CHECK (
        keystone_user_id = current_setting('app.tenant_keystone_user_id', true)
        AND control_plane_id = current_setting('app.tenant_cp_id', true)
    );

-- Role + grants for fresh installs
-- (Password set post-deploy from secret; see migrate_tenant_portal.sql header)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_portal_role') THEN
        CREATE ROLE tenant_portal_role LOGIN;
    END IF;
END $$;

DO $$
DECLARE v_dbname TEXT := current_database();
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO tenant_portal_role', v_dbname);
END $$;

GRANT USAGE ON SCHEMA public TO tenant_portal_role;

GRANT SELECT ON servers, volumes, snapshots, snapshot_records TO tenant_portal_role;
GRANT SELECT ON hypervisors TO tenant_portal_role;
GRANT SELECT ON flavors, inventory_runs TO tenant_portal_role;
GRANT SELECT ON networks, subnets, ports TO tenant_portal_role;
GRANT SELECT ON security_groups, security_group_rules TO tenant_portal_role;
GRANT SELECT ON images TO tenant_portal_role;
GRANT SELECT, INSERT, UPDATE ON restore_jobs TO tenant_portal_role;
GRANT SELECT ON pf9_regions TO tenant_portal_role;
GRANT SELECT ON role_assignments TO tenant_portal_role;
GRANT SELECT ON projects TO tenant_portal_role;
GRANT SELECT ON users TO tenant_portal_role;
GRANT SELECT ON runbooks, runbook_project_tags TO tenant_portal_role;
GRANT SELECT ON tenant_cp_view TO tenant_portal_role;
GRANT SELECT ON tenant_portal_access TO tenant_portal_role;
GRANT SELECT ON tenant_portal_branding TO tenant_portal_role;
GRANT SELECT, INSERT ON tenant_action_log TO tenant_portal_role;
GRANT USAGE, SELECT ON SEQUENCE tenant_action_log_id_seq TO tenant_portal_role;
GRANT INSERT ON auth_audit_log TO tenant_portal_role;
GRANT INSERT ON notification_log TO tenant_portal_role;
GRANT SELECT, INSERT, UPDATE ON tenant_portal_mfa TO tenant_portal_role;
GRANT USAGE, SELECT ON SEQUENCE tenant_portal_mfa_id_seq TO tenant_portal_role;
GRANT SELECT ON metering_resources, metering_config, metering_pricing TO tenant_portal_role;

-- Tenant role permissions
INSERT INTO role_permissions (role, resource, action) VALUES
    ('tenant', 'snapshots', 'read'),
    ('tenant', 'restore',   'write'),
    ('tenant', 'servers',   'read'),
    ('tenant', 'volumes',   'read')
ON CONFLICT DO NOTHING;

-- =====================================================================
-- Enhanced Billing & Metering System (v1.95)
-- =====================================================================

-- ---------------------------------------------------------------------------
-- Tenant billing configuration - Prepaid vs Pay-as-you-go billing models
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenant_billing_config (
    tenant_id UUID PRIMARY KEY REFERENCES domains(id),
    billing_model TEXT NOT NULL CHECK (billing_model IN ('prepaid', 'pay_as_you_go')),
    currency_code TEXT DEFAULT 'USD',
    onboarding_date DATE NOT NULL,
    billing_start_date DATE,
    billing_cycle_day INTEGER GENERATED ALWAYS AS (EXTRACT(DAY FROM COALESCE(billing_start_date, onboarding_date))::INTEGER) STORED,
    sales_person_id TEXT REFERENCES users(username),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to update updated_at on tenant billing config changes
CREATE OR REPLACE FUNCTION update_tenant_billing_config_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tenant_billing_config_updated_at
    BEFORE UPDATE ON tenant_billing_config
    FOR EACH ROW EXECUTE FUNCTION update_tenant_billing_config_updated_at();

-- ---------------------------------------------------------------------------
-- Prepaid account management - Balance tracking for prepaid tenants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prepaid_accounts (
    tenant_id UUID PRIMARY KEY REFERENCES domains(id),
    current_balance DECIMAL(15,2) DEFAULT 0.00,
    last_charge_date DATE,
    next_billing_date DATE,
    currency_code TEXT DEFAULT 'USD',
    quota_enforcement BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to update updated_at on prepaid account changes
CREATE TRIGGER prepaid_accounts_updated_at
    BEFORE UPDATE ON prepaid_accounts
    FOR EACH ROW EXECUTE FUNCTION update_tenant_billing_config_updated_at();

-- ---------------------------------------------------------------------------
-- Regional pricing overrides - Optional region-specific pricing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regional_pricing_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES domains(id),
    region_name TEXT NOT NULL,
    category TEXT NOT NULL,
    subcategory TEXT,
    price_per_hour DECIMAL(15,4),
    price_per_month DECIMAL(15,2),
    currency_code TEXT DEFAULT 'USD',
    effective_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, region_name, category, subcategory)
);

-- Index for efficient regional pricing lookups
CREATE INDEX IF NOT EXISTS idx_regional_pricing_tenant_region 
    ON regional_pricing_overrides(tenant_id, region_name);
CREATE INDEX IF NOT EXISTS idx_regional_pricing_category 
    ON regional_pricing_overrides(category, subcategory);

-- ---------------------------------------------------------------------------
-- Webhook registrations - External system integration
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS webhook_registrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES domains(id),
    webhook_url TEXT NOT NULL,
    event_types TEXT[] NOT NULL,
    auth_token TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    last_success_at TIMESTAMPTZ,
    failure_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger to update updated_at on webhook registration changes
CREATE TRIGGER webhook_registrations_updated_at
    BEFORE UPDATE ON webhook_registrations
    FOR EACH ROW EXECUTE FUNCTION update_tenant_billing_config_updated_at();

-- Index for efficient webhook lookups
CREATE INDEX IF NOT EXISTS idx_webhook_registrations_tenant 
    ON webhook_registrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhook_registrations_active 
    ON webhook_registrations(is_active) WHERE is_active = TRUE;

-- ---------------------------------------------------------------------------
-- Resource lifecycle events log - Track resource creation/deletion for billing
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS resource_lifecycle_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_data JSONB,
    billing_impact JSONB,
    webhook_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient lifecycle event queries
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_tenant 
    ON resource_lifecycle_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_type 
    ON resource_lifecycle_events(resource_type);
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_webhook 
    ON resource_lifecycle_events(webhook_sent) WHERE webhook_sent = FALSE;
CREATE INDEX IF NOT EXISTS idx_resource_lifecycle_created 
    ON resource_lifecycle_events(created_at);

-- ---------------------------------------------------------------------------
-- Historical data archival tracking - 7-year compliance management
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_archival_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_name TEXT NOT NULL,
    archive_date DATE NOT NULL,
    records_archived INTEGER,
    archive_location TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for archival log queries
CREATE INDEX IF NOT EXISTS idx_data_archival_table 
    ON data_archival_log(table_name);
CREATE INDEX IF NOT EXISTS idx_data_archival_date 
    ON data_archival_log(archive_date);

-- Enhanced billing system permissions for tenant portal (tables now exist)
GRANT SELECT ON tenant_billing_config TO tenant_portal_role;
GRANT SELECT ON prepaid_accounts TO tenant_portal_role;
GRANT SELECT ON regional_pricing_overrides TO tenant_portal_role;
GRANT SELECT ON resource_lifecycle_events TO tenant_portal_role;

-- Role-based access permissions for billing API (v1.95)
INSERT INTO role_permissions (role, resource, action) VALUES
    ('superadmin', 'billing', 'write'),
    ('admin',      'billing', 'read'),
    ('technical',  'billing', 'read')
ON CONFLICT DO NOTHING;


-- Dashboard health trend snapshots (daily aggregate for sparklines)
CREATE TABLE IF NOT EXISTS dashboard_health_snapshots (
    id             BIGSERIAL PRIMARY KEY,
    snapshot_date  DATE        NOT NULL UNIQUE,
    total_vms      INTEGER     NOT NULL DEFAULT 0,
    running_vms    INTEGER     NOT NULL DEFAULT 0,
    total_hosts    INTEGER     NOT NULL DEFAULT 0,
    critical_count INTEGER     NOT NULL DEFAULT 0,
    recorded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dashboard_health_snapshots_date
    ON dashboard_health_snapshots(snapshot_date DESC);
