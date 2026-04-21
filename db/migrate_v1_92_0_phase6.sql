-- =============================================================================
-- v1.92.0 — Phase 6: Role-Based Dashboard Layer
-- Idempotent: all statements guarded by IF NOT EXISTS / ON CONFLICT DO NOTHING.
--
-- Adds:
--   • unit_price column on msp_contract_entitlements (nullable, non-breaking)
--   • Two new departments: Account Management, Executive Leadership
--   • New nav group: intelligence_views
--   • New nav items: account_manager_dashboard, executive_dashboard
--   • RBAC rows for account_manager and executive roles
--   • Department nav group + item visibility seeding
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. unit_price on msp_contract_entitlements
--    Nullable: existing rows are unaffected. Revenue leakage dollar totals
--    are skipped (return null) where unit_price IS NULL.
-- ---------------------------------------------------------------------------
ALTER TABLE msp_contract_entitlements
    ADD COLUMN IF NOT EXISTS unit_price DECIMAL(10,4);

-- ---------------------------------------------------------------------------
-- 2. New departments
-- ---------------------------------------------------------------------------
INSERT INTO departments (name, description, sort_order, default_nav_item_key) VALUES
    ('Account Management',   'Client-facing account managers — per-tenant portfolio view', 8, 'account_manager_dashboard'),
    ('Executive Leadership', 'MSP leadership — fleet-wide executive overview',              9, 'executive_dashboard')
ON CONFLICT (name) DO UPDATE SET
    default_nav_item_key = EXCLUDED.default_nav_item_key,
    updated_at           = NOW();

-- ---------------------------------------------------------------------------
-- 3. New nav group: intelligence_views
-- ---------------------------------------------------------------------------
INSERT INTO nav_groups (key, label, icon, description, sort_order, is_default) VALUES
    ('intelligence_views', 'Intelligence Views', '🧠', 'Role-specific portfolio dashboards', 0, false)
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. New nav items
-- ---------------------------------------------------------------------------
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order) VALUES
    ((SELECT id FROM nav_groups WHERE key = 'intelligence_views'),
     'account_manager_dashboard', 'My Portfolio', '📋', '/account_manager_dashboard', 'sla', 1),
    ((SELECT id FROM nav_groups WHERE key = 'intelligence_views'),
     'executive_dashboard', 'Portfolio Health', '📊', '/executive_dashboard', 'sla', 2)
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. RBAC — account_manager role
--    Read: intelligence, sla, servers, volumes, snapshots, networks,
--          domains, projects, tenant_health, reports, dashboard
--    Write: qbr (quarterly business reviews)
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
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
    ('account_manager', 'dashboard',      'read')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. RBAC — executive role (read-only portfolio view)
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('executive', 'intelligence',   'read'),
    ('executive', 'sla',            'read'),
    ('executive', 'domains',        'read'),
    ('executive', 'projects',       'read'),
    ('executive', 'tenant_health',  'read'),
    ('executive', 'monitoring',     'read'),
    ('executive', 'dashboard',      'read')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7. Department ↔ Nav Group visibility for new departments
-- ---------------------------------------------------------------------------
INSERT INTO department_nav_groups (department_id, nav_group_id)
SELECT d.id, ng.id
FROM   departments d
CROSS JOIN nav_groups ng
WHERE  d.name IN ('Account Management', 'Executive Leadership')
ON CONFLICT (department_id, nav_group_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 8. Department ↔ Nav Item visibility seeding
-- ---------------------------------------------------------------------------

-- Account Management: persona dashboard + supporting operational views
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM   departments d
CROSS JOIN nav_items ni
WHERE  d.name = 'Account Management'
  AND  ni.key IN (
      'account_manager_dashboard',
      'insights',
      'tenant_health',
      'reports',
      'search',
      'servers',
      'volumes',
      'snapshots',
      'snapshot_compliance',
      'metering',
      'monitoring'
  )
ON CONFLICT (department_id, nav_item_id) DO NOTHING;

-- Executive Leadership: high-level portfolio view only
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM   departments d
CROSS JOIN nav_items ni
WHERE  d.name = 'Executive Leadership'
  AND  ni.key IN (
      'executive_dashboard',
      'tenant_health',
      'insights',
      'reports',
      'monitoring',
      'search'
  )
ON CONFLICT (department_id, nav_item_id) DO NOTHING;
