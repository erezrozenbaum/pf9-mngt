-- v1.93.37: Add missing sla + intelligence read permissions for technical role
-- The v1.85 migrations seeded these permissions for viewer/operator/admin/superadmin
-- but omitted the technical role (added in v1.17.1). Users with the technical role
-- received 403 Forbidden when accessing the Insights / SLA tabs.

INSERT INTO role_permissions (role, resource, action) VALUES
    ('technical', 'sla',          'read'),
    ('technical', 'intelligence',  'read')
ON CONFLICT (role, resource, action) DO NOTHING;
