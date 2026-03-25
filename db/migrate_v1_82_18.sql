-- =============================================================================
-- migrate_v1_82_18.sql — v1.82.18 schema additions
--
-- 1. system_settings table  – generic key/value store for runtime config
-- 2. departments.default_nav_item_key – per-department default landing tab
-- 3. Re-seed any missing nav_items (idempotent) so existing clusters pick up
--    items added after initial deployment
-- 4. Back-fill department_nav_groups / department_nav_items for any new items
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. system_settings — generic key/value configuration store
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_settings (
    key         VARCHAR(200) PRIMARY KEY,
    value       TEXT         NOT NULL DEFAULT '',
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Seed default retention value (only if not already present)
INSERT INTO system_settings (key, value, description)
VALUES ('rvtools_retention_days', '30', 'Number of days to keep RVTools Excel exports on disk')
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. departments.default_nav_item_key — the nav item key to land on at login
-- ---------------------------------------------------------------------------
ALTER TABLE departments
    ADD COLUMN IF NOT EXISTS default_nav_item_key TEXT;

-- ---------------------------------------------------------------------------
-- 3. Re-seed any nav_items that may be missing on existing clusters
--    (init.sql uses ON CONFLICT DO NOTHING so items added after initial deploy
--     don't appear in running databases; this migration ensures they're present)
-- ---------------------------------------------------------------------------

-- Inventory group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'search',          'Ops Search',      '🔍', '/search',          'search',          0  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'dashboard',       'Dashboard',       '🏠', '/dashboard',       'dashboard',       1  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'servers',         'VMs',             '',   '/servers',         'servers',         2  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'volumes',         'Volumes',         '',   '/volumes',         'volumes',         3  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'networks',        'Networks',        '🔧', '/networks',        'networks',        4  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'subnets',         'Subnets',         '',   '/subnets',         'subnets',         5  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'ports',           'Ports',           '',   '/ports',           'ports',           6  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'floatingips',     'Floating IPs',    '',   '/floatingips',     'floatingips',     7  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'security_groups', 'Security Groups', '🔒', '/security_groups', 'security_groups', 8  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'hypervisors',     'Hypervisors',     '',   '/hypervisors',     'hypervisors',     9  FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'images',          'Images',          '',   '/images',          'images',          10 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'flavors',         'Flavors',         '🔧', '/flavors',         'flavors',         11 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'keypairs',        'Keypairs',        '🔑', '/keypairs',        'keypairs',        12 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'aggregates',      'Aggregates',      '🏗️', '/aggregates',      'host_aggregates', 13 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'volume_types',    'Volume Types',    '💾', '/volume_types',    'volume_types',    14 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'server_groups',   'Server Groups',   '📦', '/server_groups',   'server_groups',   15 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'quotas',          'Quotas',          '📊', '/quotas',          'project_quotas',  16 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'system_metadata', 'System Metadata', '🗂️', '/system_metadata', 'system_metadata', 17 FROM nav_groups WHERE key='inventory'
ON CONFLICT (key) DO NOTHING;

-- Snapshot Management group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'snapshots',           'Snapshots',           '',   '/snapshots',           'snapshots',            1 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'snapshot-policies',   'Snapshot Policies',   '📸', '/snapshot-policies',   'snapshot_policy_sets', 2 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'snapshot_monitor',    'Snapshot Monitor',    '🔧', '/snapshot_monitor',    'snapshot_runs',        3 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'snapshot_compliance', 'Snapshot Compliance', '🔧', '/snapshot_compliance', 'snapshot_records',     4 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'restore',             'Snapshot Restore',    '🔧', '/restore',             'restore',              5 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'restore_audit',       'Restore Audit',       '🔧', '/restore_audit',       'restore',              6 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'snapshot-audit',      'Snapshot Audit',      '📋', '/snapshot-audit',      'snapshots',            7 FROM nav_groups WHERE key='snapshot_management'
ON CONFLICT (key) DO NOTHING;

-- Change Management & Logs group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'history',     'History',         '',   '/history',     'history',     1 FROM nav_groups WHERE key='change_logs'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'audit',       'Audit',           '',   '/audit',       'audit',       2 FROM nav_groups WHERE key='change_logs'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'system_logs', 'System Logs',     '',   '/system_logs', 'system_logs', 3 FROM nav_groups WHERE key='change_logs'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'drift',       'Drift Detection', '🔍', '/drift',       'drift',       4 FROM nav_groups WHERE key='change_logs'
ON CONFLICT (key) DO NOTHING;

-- Customer Onboarding group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'domains',           'Domains',      '',   '/domains',           'domains',      1 FROM nav_groups WHERE key='customer_onboarding'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'projects',          'Projects',     '',   '/projects',          'projects',     2 FROM nav_groups WHERE key='customer_onboarding'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'users',             'Users',        '🔧', '/users',             'users',        3 FROM nav_groups WHERE key='customer_onboarding'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'provisioning',      'Provisioning', '🚀', '/provisioning',      'provisioning', 4 FROM nav_groups WHERE key='customer_onboarding'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'domain_management', 'Domain Mgmt',  '🏢', '/domain_management', 'provisioning', 5 FROM nav_groups WHERE key='customer_onboarding'
ON CONFLICT (key) DO NOTHING;

-- Metering & Reporting group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'api_metrics',         'API Metrics',   '',   '/api_metrics',         'api_metrics',   1 FROM nav_groups WHERE key='metering_reporting'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'metering',            'Metering',      '📊', '/metering',            'metering',      2 FROM nav_groups WHERE key='metering_reporting'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'reports',             'Reports',       '📊', '/reports',             'reports',       3 FROM nav_groups WHERE key='metering_reporting'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'resource_management', 'Resources',     '🔧', '/resource_management', 'resources',     4 FROM nav_groups WHERE key='metering_reporting'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'tenant_health',       'Tenant Health', '🏥', '/tenant_health',       'tenant_health', 5 FROM nav_groups WHERE key='metering_reporting'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'monitoring',          'Monitoring',    '',   '/monitoring',          'monitoring',    6 FROM nav_groups WHERE key='metering_reporting'
ON CONFLICT (key) DO NOTHING;

-- Admin Tools group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'admin',              'Auth Management',   '⚙️', '/admin',              'users',              1 FROM nav_groups WHERE key='admin_tools'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'notifications',      'Notifications',     '🔔', '/notifications',      'notifications',      2 FROM nav_groups WHERE key='admin_tools'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'cluster_management', 'Cluster Management','🌐', '/cluster_management', 'cluster_management', 3 FROM nav_groups WHERE key='admin_tools'
ON CONFLICT (key) DO NOTHING;

-- Technical Tools group items
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'backup',   'Backup',   '💾', '/backup',   'backup',   1 FROM nav_groups WHERE key='technical_tools'
ON CONFLICT (key) DO NOTHING;
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT id, 'runbooks', 'Runbooks', '📋', '/runbooks', 'runbooks', 2 FROM nav_groups WHERE key='technical_tools'
ON CONFLICT (key) DO NOTHING;

-- Ensure nav_groups exist (idempotent)
INSERT INTO nav_groups (key, label, icon, description, sort_order) VALUES
    ('inventory',            'Inventory',            '📦', 'Infrastructure inventory and resources',       1),
    ('snapshot_management',  'Snapshot Management',  '📸', 'Snapshot lifecycle, policies, and compliance', 2),
    ('change_logs',          'Change Management & Logs','📋','History, audit trails, and drift detection',  3),
    ('customer_onboarding',  'Customer Onboarding',  '🏢', 'Domains, projects, and tenant management',    4),
    ('metering_reporting',   'Metering & Reporting', '📊', 'API metrics, metering, reports, and health',  5),
    ('admin_tools',          'Admin Tools',          '⚙️', 'Authentication, roles, branding, and audit',  6),
    ('technical_tools',      'Technical Tools',      '🔧', 'Backup, provisioning, and system operations', 7)
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Back-fill department_nav_groups and department_nav_items with any items
--    that were added in this migration (new items for existing departments)
-- ---------------------------------------------------------------------------
INSERT INTO department_nav_groups (department_id, nav_group_id)
SELECT d.id, g.id
FROM departments d
CROSS JOIN nav_groups g
ON CONFLICT (department_id, nav_group_id) DO NOTHING;

INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, i.id
FROM departments d
CROSS JOIN nav_items i
ON CONFLICT (department_id, nav_item_id) DO NOTHING;
