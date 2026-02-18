-- =====================================================================
-- Migration: Departments + Navigation Visibility Layer
-- Adds 3-layer authorization model:
--   Layer 1: Authentication (LDAP) - already exists
--   Layer 2: Authorization (RBAC roles/permissions) - already exists
--   Layer 3: Visibility (departments + nav groups/items) - NEW
-- =====================================================================

-- =====================================================================
-- 1. DEPARTMENTS
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

-- Seed default departments
INSERT INTO departments (name, description, sort_order) VALUES
    ('Engineering',  'Engineering and development team',     1),
    ('Tier1 Support','Tier 1 support team',                  2),
    ('Tier2 Support','Tier 2 support team',                  3),
    ('Tier3 Support','Tier 3 support team',                  4),
    ('Sales',        'Sales team',                           5),
    ('Marketing',    'Marketing team',                       6),
    ('Management',   'Management and leadership',            7)
ON CONFLICT (name) DO NOTHING;

-- =====================================================================
-- 2. NAV GROUPS (top-level navigation groups)
-- =====================================================================
CREATE TABLE IF NOT EXISTS nav_groups (
    id          SERIAL PRIMARY KEY,
    key         VARCHAR(100) NOT NULL UNIQUE,   -- e.g. 'inventory', 'snapshot_management'
    label       VARCHAR(150) NOT NULL,          -- Display name
    icon        VARCHAR(50),                    -- Emoji or icon name
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed default nav groups
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
-- 3. NAV ITEMS (individual tabs within groups)
-- =====================================================================
CREATE TABLE IF NOT EXISTS nav_items (
    id            SERIAL PRIMARY KEY,
    nav_group_id  INTEGER NOT NULL REFERENCES nav_groups(id) ON DELETE CASCADE,
    key           VARCHAR(100) NOT NULL UNIQUE,   -- matches ActiveTab id, e.g. 'servers'
    label         VARCHAR(150) NOT NULL,           -- Display name
    icon          VARCHAR(50),                     -- Emoji or icon name
    route         VARCHAR(255) NOT NULL,           -- Frontend route path
    resource_key  VARCHAR(100),                    -- Maps to role_permissions.resource (for permission checks)
    description   TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    is_action     BOOLEAN NOT NULL DEFAULT false,  -- true = action/config item (orange accent in nav)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed nav items mapped to existing tabs
-- Inventory group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
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
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'history',  'History',         '',   '/history',  'history', 1),
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'audit',    'Audit',           '',   '/audit',    'audit',   2),
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'system_logs', 'System Logs',  '',   '/system_logs', 'system_logs', 3),
    ((SELECT id FROM nav_groups WHERE key='change_logs'), 'drift',    'Drift Detection', '🔍', '/drift',    'drift',   4)
ON CONFLICT (key) DO NOTHING;

-- Customer Onboarding group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'domains',            'Domains',         '',   '/domains',            'domains',       1),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'projects',           'Projects',        '',   '/projects',           'projects',      2),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'users',              'Users',           '🔧', '/users',              'users',         3),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'provisioning',       'Provisioning',    '🚀', '/provisioning',       'provisioning',  4),
    ((SELECT id FROM nav_groups WHERE key='customer_onboarding'), 'domain_management',  'Domain Mgmt',    '🏢', '/domain_management',  'provisioning',  5)
ON CONFLICT (key) DO NOTHING;

-- Metering & Reporting group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'api_metrics',          'API Metrics',     '',   '/api_metrics',          'api_metrics',     1),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'metering',             'Metering',        '📊', '/metering',             'metering',        2),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'reports',              'Reports',         '📊', '/reports',              'reports',         3),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'resource_management',  'Resources',       '🔧', '/resource_management',  'resources',       4),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'tenant_health',        'Tenant Health',   '🏥', '/tenant_health',        'tenant_health',   5),
    ((SELECT id FROM nav_groups WHERE key='metering_reporting'), 'monitoring',           'Monitoring',      '',   '/monitoring',           'monitoring',      6)
ON CONFLICT (key) DO NOTHING;

-- Admin Tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'admin',          'Auth Management',  '⚙️', '/admin',          'users',       1),
    ((SELECT id FROM nav_groups WHERE key='admin_tools'), 'notifications',  'Notifications',    '🔔', '/notifications',  'notifications', 2)
ON CONFLICT (key) DO NOTHING;

-- Technical Tools group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key='technical_tools'), 'backup',  'Backup',  '💾', '/backup',  'backup', 1)
ON CONFLICT (key) DO NOTHING;

-- =====================================================================
-- 4. DEPARTMENT ↔ NAV GROUP visibility (many-to-many)
-- =====================================================================
CREATE TABLE IF NOT EXISTS department_nav_groups (
    id              SERIAL PRIMARY KEY,
    department_id   INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    nav_group_id    INTEGER NOT NULL REFERENCES nav_groups(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (department_id, nav_group_id)
);

-- =====================================================================
-- 5. DEPARTMENT ↔ NAV ITEM visibility (many-to-many, optional fine-grained)
-- =====================================================================
CREATE TABLE IF NOT EXISTS department_nav_items (
    id              SERIAL PRIMARY KEY,
    department_id   INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    nav_item_id     INTEGER NOT NULL REFERENCES nav_items(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (department_id, nav_item_id)
);

-- =====================================================================
-- 6. PER-USER VISIBILITY OVERRIDES
--    override_type: 'grant' = show even if department hides it
--                   'deny'  = hide even if department shows it
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

-- =====================================================================
-- 7. ADD department_id TO user_roles
-- =====================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'user_roles' AND column_name = 'department_id'
    ) THEN
        ALTER TABLE user_roles ADD COLUMN department_id INTEGER REFERENCES departments(id);
    END IF;
END $$;

-- =====================================================================
-- 8. SEED: Give ALL departments access to ALL nav groups and ALL nav items
--    (backward compatible — nothing hidden until admin changes it)
-- =====================================================================
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

-- =====================================================================
-- 9. USEFUL INDEXES
-- =====================================================================
CREATE INDEX IF NOT EXISTS idx_department_nav_groups_dept   ON department_nav_groups(department_id);
CREATE INDEX IF NOT EXISTS idx_department_nav_groups_group  ON department_nav_groups(nav_group_id);
CREATE INDEX IF NOT EXISTS idx_department_nav_items_dept    ON department_nav_items(department_id);
CREATE INDEX IF NOT EXISTS idx_department_nav_items_item    ON department_nav_items(nav_item_id);
CREATE INDEX IF NOT EXISTS idx_user_nav_overrides_user      ON user_nav_overrides(username);
CREATE INDEX IF NOT EXISTS idx_nav_items_group              ON nav_items(nav_group_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_department        ON user_roles(department_id);

-- =====================================================================
-- 10. ADD navigation permissions for new roles
-- =====================================================================
INSERT INTO role_permissions (role, resource, action) VALUES
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
-- 11. ADD is_action column for existing installations & mark action items
-- =====================================================================
ALTER TABLE nav_items ADD COLUMN IF NOT EXISTS is_action BOOLEAN NOT NULL DEFAULT false;

UPDATE nav_items SET is_action = true
WHERE key IN (
    'networks', 'security_groups', 'flavors', 'users', 'admin',
    'snapshot_monitor', 'snapshot_compliance', 'restore', 'restore_audit',
    'snapshot-policies', 'backup', 'metering', 'provisioning',
    'domain_management', 'reports', 'resource_management'
);
