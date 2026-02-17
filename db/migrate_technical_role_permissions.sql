-- Migration: Add 'technical' role + missing permissions for all roles
-- v1.17.1 — Adds technical role, fixes permission coverage for all UI tabs

-- =====================================================================
-- 1. Add missing resource permissions for existing roles
-- =====================================================================

-- Viewer: read access to new tabs
INSERT INTO role_permissions (role, resource, action) VALUES
('viewer', 'reports', 'read'),
('viewer', 'resources', 'read'),
('viewer', 'metering', 'read'),
('viewer', 'branding', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Operator: read + limited write for new tabs
INSERT INTO role_permissions (role, resource, action) VALUES
('operator', 'reports', 'read'),
('operator', 'resources', 'read'),
('operator', 'resources', 'write'),
('operator', 'metering', 'read'),
('operator', 'notifications', 'read'),
('operator', 'notifications', 'write'),
('operator', 'branding', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Admin: full access to new tabs
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'reports', 'read'),
('admin', 'resources', 'read'),
('admin', 'resources', 'write'),
('admin', 'resources', 'admin'),
('admin', 'metering', 'read'),
('admin', 'metering', 'admin'),
('admin', 'branding', 'read'),
('admin', 'branding', 'write')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Superadmin: admin on everything new
INSERT INTO role_permissions (role, resource, action) VALUES
('superadmin', 'reports', 'read'),
('superadmin', 'resources', 'read'),
('superadmin', 'resources', 'write'),
('superadmin', 'resources', 'admin'),
('superadmin', 'metering', 'read'),
('superadmin', 'metering', 'admin'),
('superadmin', 'branding', 'read'),
('superadmin', 'branding', 'write'),
('superadmin', 'branding', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;


-- =====================================================================
-- 2. Technical role: read everything, create tenants/orgs, NO delete
-- =====================================================================

-- Read access on all main resources (same as viewer baseline)
INSERT INTO role_permissions (role, resource, action) VALUES
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

-- Write access: can create resources and provision tenants/orgs
('technical', 'resources', 'write'),
('technical', 'provisioning', 'read'),
('technical', 'provisioning', 'write'),

-- Write on network/flavor (like operator)
('technical', 'networks', 'write'),
('technical', 'flavors', 'write'),
('technical', 'snapshot_assignments', 'write'),
('technical', 'snapshot_exclusions', 'write')

ON CONFLICT (role, resource, action) DO NOTHING;
