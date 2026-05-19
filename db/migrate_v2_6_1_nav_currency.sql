-- ---------------------------------------------------------------------------
-- v2.6.1 — Post-deploy fixes
-- 1. Register the Right-Sizing nav item (missing from nav_items seed)
-- 2. Assign it to all departments that have the 'insights' nav item
--    (mirrors the pattern used for other intelligence-layer features)
-- ---------------------------------------------------------------------------

-- 1. Insert rightsizing nav item under Intelligence Views group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, description, sort_order, is_active, is_action)
SELECT id, 'rightsizing', 'Right-Sizing', '💡', '/rightsizing', 'rightsizing',
       'Workload right-sizing and cost waste detection', 20, true, true
FROM nav_groups WHERE key = 'intelligence_views'
ON CONFLICT (key) DO NOTHING;

-- 2. Assign to every department that already has 'insights'
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT dni.department_id, (SELECT id FROM nav_items WHERE key = 'rightsizing')
FROM department_nav_items dni
JOIN nav_items ni ON ni.id = dni.nav_item_id
WHERE ni.key = 'insights'
ON CONFLICT DO NOTHING;
