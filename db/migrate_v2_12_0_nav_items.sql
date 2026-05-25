-- =========================================================================
-- Migration: v2.12.0 — Node Logs, Automation (CLEA), System Settings nav items
-- =========================================================================
-- Adds three new navigation items introduced in v2.12.0:
--   • node_logs      → Admin Tools group (Node Logs viewer)
--   • clea_policies  → Admin Tools group (Closed-Loop Event Automation)
--   • admin_settings → Admin Tools group (System Settings panel)
-- =========================================================================

INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
VALUES
    ((SELECT id FROM nav_groups WHERE key = 'admin_tools'),
     'clea_policies', 'Automation', '⚡', '/clea_policies', 'monitoring', 6),
    ((SELECT id FROM nav_groups WHERE key = 'admin_tools'),
     'node_logs', 'Node Logs', '📋', '/node_logs', 'monitoring', 7),
    ((SELECT id FROM nav_groups WHERE key = 'admin_tools'),
     'admin_settings', 'System Settings', '⚙️', '/admin_settings', 'admin', 8)
ON CONFLICT (key) DO NOTHING;
