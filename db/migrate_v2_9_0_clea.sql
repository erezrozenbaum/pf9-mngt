-- =============================================================================
-- migrate_v2_9_0_clea.sql
-- CLEA — Closed-Loop Event Automation (v2.9.0)
--
-- Creates the clea_policies and clea_executions tables and seeds two demo
-- policies.  All statements are idempotent (IF NOT EXISTS / ON CONFLICT).
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1.  Policy table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clea_policies (
    id              SERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    condition_expr  JSONB NOT NULL DEFAULT '{}',
    runbook_name    TEXT NOT NULL REFERENCES runbooks(name) ON DELETE RESTRICT,
    approval_mode   TEXT NOT NULL DEFAULT 'single_approval'
                    CHECK (approval_mode IN ('auto', 'single_approval', 'disabled')),
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clea_policies_event_type
    ON clea_policies(event_type) WHERE enabled = true;

-- ---------------------------------------------------------------------------
-- 2.  Execution log table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clea_executions (
    id              SERIAL PRIMARY KEY,
    policy_id       INTEGER NOT NULL REFERENCES clea_policies(id) ON DELETE CASCADE,
    event_id        BIGINT  REFERENCES operational_events(id) ON DELETE SET NULL,
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    approval_status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (approval_status IN ('pending', 'approved', 'rejected', 'skipped', 'executed')),
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    execution_id    TEXT REFERENCES runbook_executions(execution_id) ON DELETE SET NULL,
    result          JSONB
);

CREATE INDEX IF NOT EXISTS idx_clea_executions_policy_id
    ON clea_executions(policy_id);

CREATE INDEX IF NOT EXISTS idx_clea_executions_triggered_at
    ON clea_executions(triggered_at DESC);

-- ---------------------------------------------------------------------------
-- 3.  Role permissions
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',      'clea', 'read'),
    ('superadmin', 'clea', 'read'),
    ('superadmin', 'clea', 'write'),
    ('superadmin', 'clea', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4.  Navigation item  (admin_tools group)
-- ---------------------------------------------------------------------------
INSERT INTO nav_items (nav_group_id, key, label, icon, route, resource_key, sort_order)
VALUES (
    (SELECT id FROM nav_groups WHERE key = 'admin_tools'),
    'clea_policies',
    'Automation',
    '⚡',
    '/clea_policies',
    'clea',
    6
)
ON CONFLICT (key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5.  Demo seed policies  (safe to apply on any DB)
-- ---------------------------------------------------------------------------
INSERT INTO clea_policies (event_type, condition_expr, runbook_name, approval_mode, enabled, created_by) VALUES
    (
        'drift.resource_orphaned',
        '{}',
        'orphan_resource_cleanup',
        'single_approval',
        true,
        'system'
    ),
    (
        'quota.warning',
        '{}',
        'quota_threshold_check',
        'auto',
        true,
        'system'
    )
ON CONFLICT DO NOTHING;
