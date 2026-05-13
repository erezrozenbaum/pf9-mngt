-- ============================================================
-- Migration v1.96.0: Operational Event Timeline
--
-- Adds:
--   1. operational_events         — unified chronological event store
--   2. timeline_harvest_cursors   — per-source harvest position tracking
--   3. nav_items entry            — 'operational_timeline' in Intelligence Views
--   4. role_permissions entries   — timeline:read for all roles
-- ============================================================

-- ---------------------------------------------------------------
-- 1. Operational Events
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operational_events (
    id              BIGSERIAL PRIMARY KEY,
    event_id        UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Temporal
    occurred_at     TIMESTAMPTZ NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- What happened
    event_type      TEXT NOT NULL,
    category        TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'info',
    title           TEXT NOT NULL,
    description     TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',

    -- Primary entity
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    entity_name     TEXT,

    -- Scope
    domain_id       TEXT,
    domain_name     TEXT,
    project_id      TEXT,
    project_name    TEXT,
    region_id       TEXT NOT NULL DEFAULT 'global',

    -- Source tracking
    source          TEXT NOT NULL,
    source_id       TEXT,
    actor           TEXT,

    -- Visibility / RBAC filter
    visibility      TEXT NOT NULL DEFAULT 'operational',

    CONSTRAINT chk_oe_category CHECK (category IN (
        'monitoring', 'provisioning', 'backup', 'snapshot', 'sla',
        'billing', 'security', 'ticket', 'intelligence', 'runbook', 'system'
    )),
    CONSTRAINT chk_oe_severity CHECK (severity IN ('info', 'warning', 'critical')),
    CONSTRAINT chk_oe_visibility CHECK (visibility IN (
        'operational', 'billing', 'security', 'system'
    ))
);

COMMENT ON TABLE operational_events IS
    'Unified chronological event store for the Operational Timeline feature (v1.96.0). '
    'Events are harvested from source tables by TimelineHarvester in intelligence_worker. '
    'Visibility column drives RBAC: viewer=operational only; superadmin=all.';

COMMENT ON COLUMN operational_events.visibility IS
    'operational | billing | security | system — server-side filtered by role';

COMMENT ON COLUMN operational_events.source_id IS
    'Optional opaque reference to the originating row in the source table';

-- Deduplicate: same source + source_id must not appear twice
CREATE UNIQUE INDEX IF NOT EXISTS idx_oe_source_dedup
    ON operational_events(source, source_id)
    WHERE source_id IS NOT NULL;

-- Primary query pattern: tenant timeline (domain + time)
CREATE INDEX IF NOT EXISTS idx_oe_domain_time
    ON operational_events(domain_id, occurred_at DESC);

-- Resource timeline (entity_type + entity_id + time)
CREATE INDEX IF NOT EXISTS idx_oe_entity_time
    ON operational_events(entity_type, entity_id, occurred_at DESC);

-- Region-scoped admin queries
CREATE INDEX IF NOT EXISTS idx_oe_region_time
    ON operational_events(region_id, occurred_at DESC);

-- Category filter
CREATE INDEX IF NOT EXISTS idx_oe_category_time
    ON operational_events(category, occurred_at DESC);

-- Project-level scope
CREATE INDEX IF NOT EXISTS idx_oe_project_time
    ON operational_events(project_id, occurred_at DESC);

-- Retention pruning by recorded_at
CREATE INDEX IF NOT EXISTS idx_oe_recorded_at
    ON operational_events(recorded_at);

-- Visibility filter (used in every query)
CREATE INDEX IF NOT EXISTS idx_oe_visibility_time
    ON operational_events(visibility, occurred_at DESC);


-- ---------------------------------------------------------------
-- 2. Timeline Harvest Cursors
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS timeline_harvest_cursors (
    source      TEXT PRIMARY KEY,
    last_id     BIGINT,
    last_ts     TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE timeline_harvest_cursors IS
    'Stores the harvest position (last processed id + timestamp) for each source table. '
    'Used by TimelineHarvester to fetch only new rows since the last run.';


-- ---------------------------------------------------------------
-- 3. Nav item: Operational Timeline
-- ---------------------------------------------------------------
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
VALUES (
    (SELECT id FROM nav_groups WHERE key = 'intelligence_views'),
    'operational_timeline',
    'Timeline',
    '📅',
    '/operational_timeline',
    'timeline',
    3
)
ON CONFLICT (key) DO NOTHING;


-- ---------------------------------------------------------------
-- 4. RBAC: timeline:read for all roles
-- ---------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',          'timeline', 'read'),
    ('operator',        'timeline', 'read'),
    ('technical',       'timeline', 'read'),
    ('admin',           'timeline', 'read'),
    ('superadmin',      'timeline', 'read'),
    ('superadmin',      'timeline', 'write'),
    ('superadmin',      'timeline', 'admin'),
    ('account_manager', 'timeline', 'read'),
    ('executive',       'timeline', 'read')
ON CONFLICT DO NOTHING;


-- ---------------------------------------------------------------
-- 5. Tenant portal access to operational_events
-- ---------------------------------------------------------------
GRANT SELECT ON operational_events TO tenant_portal_role;
