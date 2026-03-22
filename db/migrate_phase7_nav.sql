-- Phase 7 frontend: register cluster_management tab in admin navigation
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order, is_action)
SELECT ng.id, 'cluster_management', 'Cluster Management', '🌐',
       '/cluster_management', 'cluster_management', 3, true
FROM nav_groups ng
WHERE ng.key = 'admin_tools'
ON CONFLICT (key) DO NOTHING;
