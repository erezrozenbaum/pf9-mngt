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
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO departments (name, description, sort_order) VALUES
    ('Engineering',  'Engineering and development team',     1),
    ('Tier1 Support','Tier 1 support team',                  2),
    ('Tier2 Support','Tier 2 support team',                  3),
    ('Tier3 Support','Tier 3 support team',                  4),
    ('Sales',        'Sales team',                           5),
    ('Marketing',    'Marketing team',                       6),
    ('Management',   'Management and leadership',            7)
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
('technical',  'navigation',  'read')

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

-- Seed a default email channel
INSERT INTO notification_channels (channel_type, name, enabled, config)
VALUES ('email', 'Default SMTP', true, '{"from_name": "Platform9 Management"}')
ON CONFLICT DO NOTHING;

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
    'server' AS resource_type,
    s.id AS resource_id,
    s.name AS resource_name,
    s.project_id,
    p.name AS project_name,
    d.id AS domain_id,
    d.name AS domain_name,
    s.status,
    s.created_at,
    s.last_seen_at AS modified_at,
    NULL::TIMESTAMPTZ AS deleted_at,
    'active' AS change_type
FROM servers s
LEFT JOIN projects p ON s.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
SELECT
    'volume',
    v.id,
    v.name,
    v.project_id,
    p.name,
    d.id,
    d.name,
    v.status,
    v.created_at,
    v.last_seen_at,
    NULL,
    'active'
FROM volumes v
LEFT JOIN projects p ON v.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
SELECT
    'snapshot',
    s.id,
    s.name,
    s.project_id,
    p.name,
    d.id,
    d.name,
    s.status,
    s.created_at,
    s.last_seen_at,
    NULL,
    'active'
FROM snapshots s
LEFT JOIN projects p ON s.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
SELECT
    dh.resource_type,
    dh.resource_id,
    dh.resource_name,
    NULL AS project_id,
    dh.project_name,
    NULL AS domain_id,
    dh.domain_name,
    NULL AS status,
    NULL AS created_at,
    NULL AS modified_at,
    dh.deleted_at,
    'deleted'
FROM deletions_history dh;

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
-- =====================================================================
CREATE OR REPLACE VIEW v_comprehensive_changes AS
-- Servers
SELECT 'server' AS resource_type, h.server_id AS resource_id, s.name AS resource_name, h.change_hash, h.recorded_at, p.name AS project_name, d.name AS domain_name, NULL::TIMESTAMPTZ AS actual_time, 'Server state/history change' AS change_description
FROM servers_history h
LEFT JOIN servers s ON h.server_id = s.id
LEFT JOIN projects p ON s.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
-- Volumes
SELECT 'volume', h.volume_id, v.name, h.change_hash, h.recorded_at, p.name, d.name, NULL, 'Volume state/history change'
FROM volumes_history h
LEFT JOIN volumes v ON h.volume_id = v.id
LEFT JOIN projects p ON v.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
-- Snapshots
SELECT 'snapshot', h.snapshot_id, s.name, h.change_hash, h.recorded_at, s.project_name, s.domain_name, NULL, 'Snapshot state/history change'
FROM snapshots_history h
LEFT JOIN snapshots s ON h.snapshot_id = s.id
UNION ALL
-- Security Groups
SELECT 'security_group', h.security_group_id, sg.name, h.change_hash, h.recorded_at, sg.project_name, sg.domain_name, NULL, 'Security group state/history change'
FROM security_groups_history h
LEFT JOIN security_groups sg ON h.security_group_id = sg.id
UNION ALL
-- Security Group Rules
SELECT 'security_group_rule', h.security_group_rule_id, COALESCE(sg.name, '') || ' / ' || COALESCE(h.direction, '') || ' ' || COALESCE(h.protocol, 'any'), h.change_hash, h.recorded_at, sg.project_name, sg.domain_name, NULL, 'Security group rule state/history change'
FROM security_group_rules_history h
LEFT JOIN security_groups sg ON h.security_group_id = sg.id
UNION ALL
-- Networks
SELECT 'network', h.network_id, n.name, h.change_hash, h.recorded_at, p.name, d.name, NULL, 'Network state/history change'
FROM networks_history h
LEFT JOIN networks n ON h.network_id = n.id
LEFT JOIN projects p ON n.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
-- Subnets
SELECT 'subnet', h.subnet_id, sn.name, h.change_hash, h.recorded_at, p.name, d.name, NULL, 'Subnet state/history change'
FROM subnets_history h
LEFT JOIN subnets sn ON h.subnet_id = sn.id
LEFT JOIN networks net ON sn.network_id = net.id
LEFT JOIN projects p ON net.project_id = p.id
LEFT JOIN domains d ON p.domain_id = d.id
UNION ALL
-- Ports
SELECT 'port', h.port_id, p2.name, h.change_hash, h.recorded_at, pr.name, dm.name, NULL, 'Port state/history change'
FROM ports_history h
LEFT JOIN ports p2 ON h.port_id = p2.id
LEFT JOIN projects pr ON p2.project_id = pr.id
LEFT JOIN domains dm ON pr.domain_id = dm.id
UNION ALL
-- Floating IPs
SELECT 'floating_ip', h.floating_ip_id, fi.floating_ip, h.change_hash, h.recorded_at, pr.name, dm.name, NULL, 'Floating IP state/history change'
FROM floating_ips_history h
LEFT JOIN floating_ips fi ON h.floating_ip_id = fi.id
LEFT JOIN projects pr ON fi.project_id = pr.id
LEFT JOIN domains dm ON pr.domain_id = dm.id
UNION ALL
-- Domains
SELECT 'domain', h.domain_id, dom.name, h.change_hash, h.recorded_at, NULL, dom.name, NULL, 'Domain state/history change'
FROM domains_history h
LEFT JOIN domains dom ON h.domain_id = dom.id
UNION ALL
-- Projects
SELECT 'project', h.project_id, proj.name, h.change_hash, h.recorded_at, proj.name, d.name, NULL, 'Project state/history change'
FROM projects_history h
LEFT JOIN projects proj ON h.project_id = proj.id
LEFT JOIN domains d ON proj.domain_id = d.id
UNION ALL
-- Flavors
SELECT 'flavor', h.flavor_id, fl.name, h.change_hash, h.recorded_at, NULL, NULL, NULL, 'Flavor state/history change'
FROM flavors_history h
LEFT JOIN flavors fl ON h.flavor_id = fl.id
UNION ALL
-- Images
SELECT 'image', h.image_id, img.name, h.change_hash, h.recorded_at, NULL, NULL, NULL, 'Image state/history change'
FROM images_history h
LEFT JOIN images img ON h.image_id = img.id
UNION ALL
-- Hypervisors
SELECT 'hypervisor', h.hypervisor_id, hv.hostname, h.change_hash, h.recorded_at, NULL, NULL, NULL, 'Hypervisor state/history change'
FROM hypervisors_history h
LEFT JOIN hypervisors hv ON h.hypervisor_id = hv.id
UNION ALL
-- Users
SELECT 'user', h.user_id, u.name, h.change_hash, h.recorded_at, NULL, d.name, NULL, 'User state/history change'
FROM users_history h
LEFT JOIN users u ON h.user_id = u.id
LEFT JOIN domains d ON u.domain_id = d.id
UNION ALL
-- Roles
SELECT 'role', h.role_id, r.name, h.change_hash, h.recorded_at, NULL, d.name, NULL, 'Role state/history change'
FROM roles_history h
LEFT JOIN roles r ON h.role_id = r.id
LEFT JOIN domains d ON r.domain_id = d.id
UNION ALL
-- Deletions
SELECT 'deletion', dh.resource_id, dh.resource_name, 'deleted-' || dh.resource_id AS change_hash, dh.deleted_at AS recorded_at, dh.project_name, dh.domain_name, dh.deleted_at AS actual_time, 'Resource deleted'
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

-- Seed default drift rules
INSERT INTO drift_rules (resource_type, field_name, severity, description) VALUES
    ('servers', 'flavor_id',           'critical', 'VM flavor changed — possible unauthorized resize'),
    ('servers', 'status',              'warning',  'VM status changed unexpectedly'),
    ('servers', 'vm_state',            'warning',  'VM state changed'),
    ('servers', 'hypervisor_hostname', 'info',     'VM migrated to a different hypervisor'),
    ('servers', 'host_id',             'info',     'VM host assignment changed'),
    ('volumes', 'status',              'warning',  'Volume status changed'),
    ('volumes', 'server_id',           'critical', 'Volume reattached to a different VM'),
    ('volumes', 'size',                'warning',  'Volume size changed — possible extend'),
    ('volumes', 'volume_type',         'warning',  'Volume type changed'),
    ('networks', 'status',             'warning',  'Network status changed'),
    ('networks', 'admin_state_up',     'critical', 'Network admin state toggled'),
    ('networks', 'shared',             'critical', 'Network sharing setting changed'),
    ('ports', 'device_id',             'warning',  'Port device attachment changed'),
    ('ports', 'status',                'info',     'Port status changed'),
    ('ports', 'mac_address',           'critical', 'Port MAC address changed — possible spoofing'),
    ('floating_ips', 'port_id',        'warning',  'Floating IP reassigned to a different port'),
    ('floating_ips', 'router_id',      'warning',  'Floating IP router association changed'),
    ('floating_ips', 'status',         'info',     'Floating IP status changed'),
    ('security_groups', 'description', 'info',     'Security group description changed'),
    ('snapshots', 'status',            'warning',  'Snapshot status changed'),
    ('snapshots', 'size',              'info',     'Snapshot size changed'),
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
    network_name    TEXT,
    network_type    TEXT      DEFAULT 'vlan',
    vlan_id         INTEGER,
    subnet_cidr     TEXT,
    gateway_ip      TEXT,
    dns_nameservers TEXT[]    DEFAULT ARRAY['8.8.8.8', '8.8.4.4'],
    quota_compute   JSONB     DEFAULT '{}',
    quota_network   JSONB     DEFAULT '{}',
    quota_storage   JSONB     DEFAULT '{}',
    status          TEXT      NOT NULL DEFAULT 'pending',
    domain_id       TEXT,
    project_id      TEXT,
    user_id         TEXT,
    network_id      TEXT,
    subnet_id       TEXT,
    security_group_id TEXT,
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
    '{"type":"object","properties":{"stuck_threshold_minutes":{"type":"integer","default":30,"description":"Minutes a VM must be stuck before intervention"},"action":{"type":"string","enum":["soft_reboot","hard_reboot","report_only"],"default":"report_only","description":"Remediation action to take"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
),
(
    'orphan_resource_cleanup',
    'Orphan Resource Cleanup',
    'Finds orphaned ports, volumes, and floating IPs. Cleans up to free quota and reduce clutter.',
    'network', 'low', true,
    '{"type":"object","properties":{"resource_types":{"type":"array","items":{"type":"string","enum":["ports","volumes","floating_ips"]},"default":["ports"],"description":"Which resource types to scan"},"age_threshold_days":{"type":"integer","default":7,"description":"Only target resources older than N days"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"},"target_domain":{"type":"string","default":"","description":"Limit to specific domain (empty = all)"}}}'
),
(
    'security_group_audit',
    'Security Group Audit',
    'Scans all security groups for overly permissive rules (0.0.0.0/0 on SSH, RDP, DB ports). Flags violations.',
    'security', 'low', true,
    '{"type":"object","properties":{"flag_ports":{"type":"array","items":{"type":"integer"},"default":[22,3389,3306,5432,1433,27017],"description":"Ports to flag when open to 0.0.0.0/0"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"}}}'
),
(
    'quota_threshold_check',
    'Quota Threshold Check',
    'Checks per-project quota utilisation and flags projects exceeding configurable thresholds.',
    'quota', 'low', true,
    '{"type":"object","properties":{"warning_pct":{"type":"integer","default":80,"description":"Warning threshold percentage"},"critical_pct":{"type":"integer","default":95,"description":"Critical threshold percentage"},"target_project":{"type":"string","default":"","description":"Limit to specific project (empty = all)"}}}'
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

-- Seed default approval policies
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
    ('diagnostics_bundle',     'superadmin', 'admin',  'auto_approve')
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
    ('technical_tools',      'Technical Tools',              '🔧', 'Backup, provisioning, and system operations',    7)
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
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'flavors',         'Flavors',         '🔧', '/flavors',         'flavors',         11)
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
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'monitoring',           'Monitoring',    '',   '/monitoring',           'monitoring',    6)
ON CONFLICT (key) DO NOTHING;

-- Admin Tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'admin',          'Auth Management', '⚙️', '/admin',          'users',         1),
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'notifications',  'Notifications',   '🔔', '/notifications',  'notifications', 2)
ON CONFLICT (key) DO NOTHING;

-- Technical Tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='technical_tools'), 'backup',    'Backup',    '💾', '/backup',    'backup',   1),
    ((SELECT id FROM nav_groups WHERE key='technical_tools'), 'runbooks',  'Runbooks',  '📋', '/runbooks',  'runbooks', 2)
ON CONFLICT (key) DO NOTHING;

-- Mark action/config items (displayed with accent color in nav)
UPDATE nav_items SET is_action = true
WHERE key IN (
    'networks', 'security_groups', 'flavors', 'users', 'admin',
    'snapshot_monitor', 'snapshot_compliance', 'restore', 'restore_audit',
    'snapshot-policies', 'backup', 'metering', 'provisioning',
    'domain_management', 'reports', 'resource_management',
    'notifications'
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
