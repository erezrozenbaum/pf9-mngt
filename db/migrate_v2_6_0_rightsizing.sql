-- =====================================================================
-- Migration: Workload Right-Sizing & Cost Waste Detection
-- Version:  2.6.0
-- =====================================================================

-- ---------------------------------------------------------------------------
-- rightsizing_recommendations — one recommendation per VM (upserted by engine)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rightsizing_recommendations (
    id                          BIGSERIAL PRIMARY KEY,
    vm_id                       TEXT NOT NULL,
    vm_name                     TEXT,
    project_id                  TEXT,
    project_name                TEXT,
    region_id                   TEXT,
    domain                      TEXT,

    -- Classification: idle | over_provisioned | right_sized | under_provisioned
    classification              TEXT NOT NULL,

    -- Current allocation (from flavors / metering_resources)
    current_flavor              TEXT,
    current_vcpus               INTEGER,
    current_ram_mb              INTEGER,

    -- Recommended next-smaller flavor (NULL if already right-sized or custom)
    recommended_flavor          TEXT,
    recommended_vcpus           INTEGER,
    recommended_ram_mb          INTEGER,

    -- Utilisation statistics over analysis window
    cpu_p95_7d                  NUMERIC(6,2),
    ram_p95_7d                  NUMERIC(6,2),
    cpu_avg_7d                  NUMERIC(6,2),
    ram_avg_7d                  NUMERIC(6,2),
    cpu_p95_30d                 NUMERIC(6,2),
    ram_p95_30d                 NUMERIC(6,2),
    analysis_period_days        INTEGER NOT NULL DEFAULT 7,

    -- Cost impact
    estimated_monthly_savings_usd  NUMERIC(10,2),
    currency                    TEXT NOT NULL DEFAULT 'USD',

    -- Lifecycle
    status                      TEXT NOT NULL DEFAULT 'open',  -- open | snoozed | dismissed | actioned
    snooze_until                TIMESTAMPTZ,
    actioned_at                 TIMESTAMPTZ,
    actioned_by                 TEXT,

    computed_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT rsr_valid_classification CHECK (
        classification IN ('idle', 'over_provisioned', 'right_sized', 'under_provisioned')
    ),
    CONSTRAINT rsr_valid_status CHECK (
        status IN ('open', 'snoozed', 'dismissed', 'actioned')
    )
);

-- One active recommendation per VM
CREATE UNIQUE INDEX IF NOT EXISTS idx_rsr_vm_active
    ON rightsizing_recommendations (vm_id)
    WHERE status IN ('open', 'snoozed');

CREATE INDEX IF NOT EXISTS idx_rsr_project
    ON rightsizing_recommendations (project_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_rsr_region
    ON rightsizing_recommendations (region_id, computed_at DESC);
CREATE INDEX IF NOT EXISTS idx_rsr_classification
    ON rightsizing_recommendations (classification, status);
CREATE INDEX IF NOT EXISTS idx_rsr_computed_at
    ON rightsizing_recommendations (computed_at DESC);

-- ---------------------------------------------------------------------------
-- Grants
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    -- Admin API role
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pf9_api') THEN
        GRANT SELECT, INSERT, UPDATE ON rightsizing_recommendations TO pf9_api;
        GRANT USAGE, SELECT ON SEQUENCE rightsizing_recommendations_id_seq TO pf9_api;
    END IF;

    -- Tenant portal role (read-only, own projects only enforced via RLS/filter)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tenant_portal_role') THEN
        GRANT SELECT ON rightsizing_recommendations TO tenant_portal_role;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- RBAC permissions
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',      'rightsizing', 'read'),
    ('admin',      'rightsizing', 'write'),
    ('superadmin', 'rightsizing', 'read'),
    ('superadmin', 'rightsizing', 'write')
ON CONFLICT DO NOTHING;
