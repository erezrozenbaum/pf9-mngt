-- =====================================================================
-- MIGRATION: Add Security Groups tables, history, view, and RBAC
-- Safe to run on an existing database — all statements are idempotent.
-- Run: docker exec -i pf9_db psql -U <user> -d <db> -f /dev/stdin < db/migrate_security_groups.sql
-- =====================================================================

BEGIN;

-- 1. RBAC permissions for security_groups resource
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'security_groups', 'read'),
    ('operator',   'security_groups', 'read'),
    ('admin',      'security_groups', 'admin'),
    ('superadmin', 'security_groups', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- 2. Security Groups table
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
CREATE INDEX IF NOT EXISTS idx_security_groups_project_id   ON security_groups(project_id);
CREATE INDEX IF NOT EXISTS idx_security_groups_name         ON security_groups(name);
CREATE INDEX IF NOT EXISTS idx_security_groups_domain_name  ON security_groups(domain_name);

-- 3. Security Group Rules table
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
CREATE INDEX IF NOT EXISTS idx_sg_rules_direction         ON security_group_rules(direction);
CREATE INDEX IF NOT EXISTS idx_sg_rules_project_id        ON security_group_rules(project_id);

-- 4. Security Groups history table
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
CREATE INDEX IF NOT EXISTS idx_security_groups_history_sg_id       ON security_groups_history(security_group_id);
CREATE INDEX IF NOT EXISTS idx_security_groups_history_recorded_at ON security_groups_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_security_groups_history_change_hash ON security_groups_history(security_group_id, change_hash);

-- 5. Security Group Rules history table
CREATE TABLE IF NOT EXISTS security_group_rules_history (
    id                     BIGSERIAL PRIMARY KEY,
    security_group_rule_id TEXT NOT NULL,
    security_group_id      TEXT,
    direction              TEXT,
    ethertype              TEXT,
    protocol               TEXT,
    port_range_min         INTEGER,
    port_range_max         INTEGER,
    remote_ip_prefix       TEXT,
    remote_group_id        TEXT,
    description            TEXT,
    project_id             TEXT,
    created_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ,
    recorded_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    change_hash            TEXT NOT NULL,
    raw_json               JSONB
);
CREATE INDEX IF NOT EXISTS idx_sg_rules_history_rule_id     ON security_group_rules_history(security_group_rule_id);
CREATE INDEX IF NOT EXISTS idx_sg_rules_history_recorded_at ON security_group_rules_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_sg_rules_history_change_hash ON security_group_rules_history(security_group_rule_id, change_hash);

-- 6. View: Security groups with VM and network associations
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

COMMIT;

-- Verification
SELECT 'security_groups'         AS table_name, COUNT(*) AS row_count FROM security_groups
UNION ALL
SELECT 'security_group_rules',                  COUNT(*) FROM security_group_rules
UNION ALL
SELECT 'security_groups_history',               COUNT(*) FROM security_groups_history
UNION ALL
SELECT 'security_group_rules_history',          COUNT(*) FROM security_group_rules_history
UNION ALL
SELECT 'sg_rbac_permissions',                   COUNT(*) FROM role_permissions WHERE resource = 'security_groups';
