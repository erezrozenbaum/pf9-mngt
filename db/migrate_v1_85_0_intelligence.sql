-- =============================================================================
-- Operational Intelligence — operational_insights table + RBAC
-- Version: v1.85.0
-- =============================================================================
-- Idempotent: all guarded by IF NOT EXISTS / ON CONFLICT DO NOTHING.

-- Single source of truth for all generated insights.
-- The unique index on (type, entity_type, entity_id) for non-resolved rows
-- lets engines do INSERT … ON CONFLICT DO UPDATE SET last_seen_at = NOW()
-- without creating duplicates.
CREATE TABLE IF NOT EXISTS operational_insights (
    id              SERIAL PRIMARY KEY,
    type            TEXT NOT NULL,
    severity        TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    entity_name     TEXT,
    title           TEXT NOT NULL,
    message         TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'open',
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    snooze_until    TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_severity CHECK (severity IN ('low','medium','high','critical')),
    CONSTRAINT valid_status   CHECK (status   IN ('open','acknowledged','snoozed','resolved','suppressed'))
);

CREATE INDEX IF NOT EXISTS idx_insights_status_severity
    ON operational_insights(status, severity);

CREATE INDEX IF NOT EXISTS idx_insights_entity
    ON operational_insights(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_insights_type
    ON operational_insights(type);

CREATE INDEX IF NOT EXISTS idx_insights_detected_at
    ON operational_insights(detected_at DESC);

-- Deduplication: one live (open/ack/snoozed) insight per (type, entity_type, entity_id).
-- Engines upsert with ON CONFLICT DO UPDATE — never duplicate an unresolved insight.
CREATE UNIQUE INDEX IF NOT EXISTS idx_insights_dedup
    ON operational_insights(type, entity_type, entity_id)
    WHERE status IN ('open','acknowledged','snoozed');

-- ---------------------------------------------------------------------------
-- RBAC permissions
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
