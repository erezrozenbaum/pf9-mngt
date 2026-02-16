-- =====================================================================
-- Migration: Drift Detection Engine
-- Idempotent — safe to re-run
-- =====================================================================

-- Drift rules: defines what field changes on which resource types
-- should be flagged as configuration drift.
CREATE TABLE IF NOT EXISTS drift_rules (
    id              BIGSERIAL PRIMARY KEY,
    resource_type   TEXT NOT NULL,          -- 'servers', 'volumes', 'networks', etc.
    field_name      TEXT NOT NULL,          -- 'flavor_id', 'status', 'network_id', etc.
    severity        TEXT NOT NULL DEFAULT 'warning',  -- 'critical', 'warning', 'info'
    description     TEXT NOT NULL,
    enabled         BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_drift_rules_unique ON drift_rules(resource_type, field_name);

-- Drift events: each detected configuration drift occurrence
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

-- =====================================================================
-- Seed default drift rules
-- =====================================================================
INSERT INTO drift_rules (resource_type, field_name, severity, description) VALUES
    -- Server drift rules
    ('servers', 'flavor_id',               'critical', 'VM flavor changed — possible unauthorized resize'),
    ('servers', 'status',                  'warning',  'VM status changed unexpectedly'),
    ('servers', 'vm_state',                'warning',  'VM state changed'),
    ('servers', 'hypervisor_hostname',     'info',     'VM migrated to a different hypervisor'),
    ('servers', 'host_id',                 'info',     'VM host assignment changed'),
    -- Volume drift rules
    ('volumes', 'status',                  'warning',  'Volume status changed'),
    ('volumes', 'server_id',              'critical', 'Volume reattached to a different VM'),
    ('volumes', 'size',                    'warning',  'Volume size changed — possible extend'),
    ('volumes', 'volume_type',            'warning',  'Volume type changed'),
    -- Network drift rules
    ('networks', 'status',                 'warning',  'Network status changed'),
    ('networks', 'admin_state_up',         'critical', 'Network admin state toggled'),
    ('networks', 'shared',                 'critical', 'Network sharing setting changed'),
    -- Port drift rules
    ('ports', 'device_id',                'warning',  'Port device attachment changed'),
    ('ports', 'status',                    'info',     'Port status changed'),
    ('ports', 'mac_address',              'critical', 'Port MAC address changed — possible spoofing'),
    -- Floating IP drift rules
    ('floating_ips', 'port_id',           'warning',  'Floating IP reassigned to a different port'),
    ('floating_ips', 'router_id',         'warning',  'Floating IP router association changed'),
    ('floating_ips', 'status',            'info',     'Floating IP status changed'),
    -- Security group drift rules
    ('security_groups', 'description',     'info',     'Security group description changed'),
    -- Snapshot drift rules
    ('snapshots', 'status',               'warning',  'Snapshot status changed'),
    ('snapshots', 'size',                 'info',     'Snapshot size changed'),
    -- Subnet drift rules
    ('subnets', 'gateway_ip',            'critical', 'Subnet gateway IP changed'),
    ('subnets', 'cidr',                  'critical', 'Subnet CIDR changed'),
    ('subnets', 'enable_dhcp',           'warning',  'DHCP setting changed on subnet')
ON CONFLICT (resource_type, field_name) DO NOTHING;

-- =====================================================================
-- RBAC permissions for drift detection
-- =====================================================================
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',    'drift', 'read'),
    ('operator',  'drift', 'read'),
    ('admin',     'drift', 'admin'),
    ('superadmin','drift', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
