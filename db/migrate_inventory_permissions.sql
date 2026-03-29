-- Migration: Add inventory resource permissions
-- Required by GET /system-metadata-summary endpoint (require_permission("inventory", "read"))
-- Safe to run multiple times (ON CONFLICT DO NOTHING)

INSERT INTO role_permissions (role, resource, action) VALUES
('viewer',     'inventory', 'read'),
('operator',   'inventory', 'read'),
('admin',      'inventory', 'admin'),
('superadmin', 'inventory', 'admin'),
('technical',  'inventory', 'read')
ON CONFLICT DO NOTHING;
