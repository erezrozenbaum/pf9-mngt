-- Ensure superadmin has dashboard:read permission
INSERT INTO role_permissions (role, resource, action)
VALUES ('superadmin', 'dashboard', 'read')
ON CONFLICT DO NOTHING;
