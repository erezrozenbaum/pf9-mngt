-- =============================================================================
-- Intelligence v3 — Capacity Forecasting, Cross-Region, Anomaly Detection
-- Idempotent: all statements guarded by IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- =============================================================================
-- No new tables required for this version.
-- All new insight types (capacity_compute, capacity_quota_*, cross_region_*,
-- anomaly_*) are stored in the existing operational_insights table using
-- the TEXT type column.
-- This migration records the new RBAC entries and an updated dedup index
-- that tolerates the new sub-type naming convention.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Ensure the dedup partial index exists (idempotent re-create guard).
-- The existing idx_insights_dedup already covers all types via (type, entity_type, entity_id).
-- We add a secondary index on type prefix for efficient department filtering.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_insights_type_prefix
    ON operational_insights (type text_pattern_ops);

-- ---------------------------------------------------------------------------
-- RBAC — no new permissions needed; forecast and regions are sub-paths of
-- the intelligence resource which already grants read/write.
-- Ensure operator also has forecast read access (same as intelligence:read).
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'intelligence', 'read'),
    ('operator',   'intelligence', 'read'),
    ('admin',      'intelligence', 'read'),
    ('admin',      'intelligence', 'write'),
    ('superadmin', 'intelligence', 'read'),
    ('superadmin', 'intelligence', 'write'),
    ('superadmin', 'intelligence', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Record migration in schema_migrations
-- ---------------------------------------------------------------------------
INSERT INTO schema_migrations (filename, applied_at)
VALUES ('migrate_v1_89_0_intelligence_p3.sql', NOW())
ON CONFLICT (filename) DO NOTHING;
