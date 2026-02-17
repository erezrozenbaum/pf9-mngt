-- Migration: Add reports and resources permissions
-- Version: 1.17.0

-- Reports permissions (read-only for admin+superadmin)
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'reports', 'read'),
('superadmin', 'reports', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- Resource management permissions
-- viewer: read only
INSERT INTO role_permissions (role, resource, action) VALUES
('viewer', 'resources', 'read')
ON CONFLICT (role, resource, action) DO NOTHING;

-- operator: read + write (list + create)
INSERT INTO role_permissions (role, resource, action) VALUES
('operator', 'resources', 'read'),
('operator', 'resources', 'write')
ON CONFLICT (role, resource, action) DO NOTHING;

-- admin: read + write + admin (list + create + delete)
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'resources', 'read'),
('admin', 'resources', 'write'),
('admin', 'resources', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- superadmin: full access
INSERT INTO role_permissions (role, resource, action) VALUES
('superadmin', 'resources', 'read'),
('superadmin', 'resources', 'write'),
('superadmin', 'resources', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
