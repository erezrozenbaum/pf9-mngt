-- ============================================================
-- Separate permissions for tenant disable vs delete
-- Also adds resource_delete permission for individual resources
-- ============================================================

-- tenant_disable: allows enabling/disabling a domain/tenant
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'provisioning', 'tenant_disable'),
('superadmin', 'provisioning', 'tenant_disable')
ON CONFLICT (role, resource, action) DO NOTHING;

-- tenant_delete: allows deleting a domain/tenant entirely
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'provisioning', 'tenant_delete'),
('superadmin', 'provisioning', 'tenant_delete')
ON CONFLICT (role, resource, action) DO NOTHING;

-- resource_delete: allows deleting individual resources (VMs, volumes, networks, etc.)
INSERT INTO role_permissions (role, resource, action) VALUES
('admin', 'provisioning', 'resource_delete'),
('superadmin', 'provisioning', 'resource_delete')
ON CONFLICT (role, resource, action) DO NOTHING;
