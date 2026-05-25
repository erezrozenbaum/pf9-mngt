-- Migration v2.12.1 → v2.12.2
-- Fixes:
--   1. Add 'admin' resource permissions for superadmin and admin roles
--      (required by GET /api/admin/system/config — System Settings tab)
--   2. No schema changes — permission rows only

-- Admin resource permissions
-- superadmin gets full admin access to the 'admin' resource
-- admin role gets read-only access to admin config (System Settings tab)
INSERT INTO role_permissions (role, resource, action)
VALUES
    ('superadmin', 'admin', 'admin'),
    ('admin',      'admin', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;
