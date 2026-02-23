-- Migration: Add additional metadata tables for comprehensive inventory
-- Tables: keypairs, server_groups, host_aggregates, volume_types, project_quotas
-- Idempotent: safe to re-run

-- Keypairs (Nova SSH keys)
CREATE TABLE IF NOT EXISTS keypairs (
    name             TEXT NOT NULL,
    user_id          TEXT NOT NULL,
    fingerprint      TEXT,
    type             TEXT,
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
    policies         TEXT[],
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
    service          TEXT NOT NULL,
    resource         TEXT NOT NULL,
    quota_limit      INTEGER,
    in_use           INTEGER,
    reserved         INTEGER,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, service, resource)
);
CREATE INDEX IF NOT EXISTS idx_project_quotas_project ON project_quotas(project_id);
CREATE INDEX IF NOT EXISTS idx_project_quotas_service ON project_quotas(service);

-- Grant permissions to all roles
DO $$ BEGIN
  EXECUTE 'GRANT SELECT ON keypairs TO pf9_viewer';
  EXECUTE 'GRANT SELECT ON server_groups TO pf9_viewer';
  EXECUTE 'GRANT SELECT ON host_aggregates TO pf9_viewer';
  EXECUTE 'GRANT SELECT ON volume_types TO pf9_viewer';
  EXECUTE 'GRANT SELECT ON project_quotas TO pf9_viewer';
EXCEPTION WHEN OTHERS THEN NULL;
END $$;

-- Navigation items under 'inventory' group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'keypairs',        'Keypairs',        '🔑', '/keypairs',        'keypairs',        12),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'aggregates',      'Aggregates',      '🏗️', '/aggregates',      'host_aggregates', 13),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'volume_types',    'Volume Types',    '💾', '/volume_types',    'volume_types',    14),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'server_groups',   'Server Groups',   '📦', '/server_groups',   'server_groups',   15),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'quotas',          'Quotas',          '📊', '/quotas',          'project_quotas',  16),
    ((SELECT id FROM nav_groups WHERE key='inventory'), 'system_metadata', 'System Metadata', '🗂️', '/system_metadata', 'system_metadata', 17)
ON CONFLICT (key) DO NOTHING;

-- Seed department visibility for new nav items
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, i.id FROM departments d CROSS JOIN nav_items i
WHERE i.key IN ('keypairs', 'aggregates', 'volume_types', 'server_groups', 'quotas', 'system_metadata')
ON CONFLICT (department_id, nav_item_id) DO NOTHING;

-- RBAC permissions
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
