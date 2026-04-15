-- v1.84.9: Register tenant_portal tab in admin_tools navigation group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order, is_action)
SELECT ng.id, 'tenant_portal', 'Tenant Portal', '🏢',
       '/tenant_portal', 'tenant_portal', 4, true
FROM nav_groups ng
WHERE ng.key = 'admin_tools'
ON CONFLICT (key) DO NOTHING;

-- Grant visibility to all existing departments (mirrors init.sql CROSS JOIN pattern)
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM departments d
CROSS JOIN nav_items ni
WHERE ni.key = 'tenant_portal'
ON CONFLICT (department_id, nav_item_id) DO NOTHING;
