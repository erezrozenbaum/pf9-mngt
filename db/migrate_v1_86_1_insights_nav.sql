-- =============================================================================
-- v1.86.1 — Add 'insights' nav item to navigation catalog
-- =============================================================================
-- Idempotent: guarded by ON CONFLICT DO NOTHING.
--
-- The v1.86.0 intelligence migration added RBAC permissions for the
-- 'intelligence' and 'sla' resources but did not register the Insights tab
-- in the nav_items catalog.  Without this entry the grouped navigation
-- system never surfaces the tab for any department.
-- =============================================================================

-- Add the Insights tab to the Metering & Reporting nav group
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
SELECT ng.id, 'insights', 'Insights', '🔍', '/insights', 'intelligence', 7
FROM   nav_groups ng
WHERE  ng.key = 'metering_reporting'
ON CONFLICT (key) DO NOTHING;

-- Seed department visibility — all departments (same pattern as init.sql blanket seed)
INSERT INTO department_nav_items (department_id, nav_item_id)
SELECT d.id, ni.id
FROM   departments d
CROSS JOIN nav_items ni
WHERE  ni.key = 'insights'
ON CONFLICT (department_id, nav_item_id) DO NOTHING;
