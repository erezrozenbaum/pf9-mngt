-- =========================================================================
-- Migration: v2.7.0 — Platform Health nav item
-- =========================================================================
-- Adds the "Platform Health" navigation item to the Admin Tools group.
-- No new tables — all tables required by v2.7.0 already exist.
-- =========================================================================

INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
VALUES (
    (SELECT id FROM nav_groups WHERE key = 'admin_tools'),
    'platform_health',
    'Platform Health',
    '💚',
    '/platform_health',
    'monitoring',
    5
)
ON CONFLICT (key) DO NOTHING;
