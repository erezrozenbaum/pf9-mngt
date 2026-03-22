-- Phase 7 frontend: register cluster_management tab in admin navigation
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order, is_action)
SELECT ng.id, 'cluster_management', 'Cluster Management', '🌐',
       '/cluster_management', 'cluster_management', 3, true
FROM nav_groups ng
WHERE ng.key = 'admin_tools'
ON CONFLICT (key) DO NOTHING;

-- Grant visibility to all existing departments (mirrors init.sql CROSS JOIN pattern)
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM departments d
CROSS JOIN nav_items ni
WHERE ni.key = 'cluster_management'
ON CONFLICT (department_id, nav_item_id) DO NOTHING;
