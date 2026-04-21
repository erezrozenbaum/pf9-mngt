-- =============================================================================
-- Phase 5 — Client Transparency Layer (v1.91.0)
-- Idempotent: all statements guarded by IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. portal_role on tenant_portal_access
--    Values: 'manager' (default — can do everything) | 'observer' (read-only)
-- ---------------------------------------------------------------------------
ALTER TABLE tenant_portal_access
    ADD COLUMN IF NOT EXISTS portal_role TEXT NOT NULL DEFAULT 'manager'
        CONSTRAINT chk_portal_role CHECK (portal_role IN ('manager', 'observer'));

-- ---------------------------------------------------------------------------
-- 2. portal_invite_tokens — one-time tokens for observer invite flow
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portal_invite_tokens (
    id            BIGSERIAL    PRIMARY KEY,
    token         TEXT         NOT NULL UNIQUE,
    control_plane_id TEXT      NOT NULL REFERENCES pf9_control_planes(id) ON DELETE CASCADE,
    project_id    TEXT         NOT NULL,            -- which project the observer will see
    invited_email TEXT         NOT NULL,
    portal_role   TEXT         NOT NULL DEFAULT 'observer',
    created_by    TEXT         NOT NULL,            -- admin username who created it
    expires_at    TIMESTAMPTZ  NOT NULL,
    used_at       TIMESTAMPTZ,                      -- NULL = not yet used
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invite_tokens_token ON portal_invite_tokens (token);
CREATE INDEX IF NOT EXISTS idx_invite_tokens_cp ON portal_invite_tokens (control_plane_id);

-- ---------------------------------------------------------------------------
-- 3. insight_history view — resolved insights per tenant, for trend sub-view
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_insight_history AS
SELECT
    id,
    type,
    severity,
    entity_type,
    entity_id,
    entity_name,
    metadata,
    status,
    detected_at,
    resolved_at,
    last_seen_at,
    metadata->>'tenant_name' AS tenant_name,
    metadata->>'project'     AS project_name
FROM operational_insights
WHERE status = 'resolved'
  AND resolved_at IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. RBAC — observer_invite resource for admin panel
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('admin',      'observer_invite', 'read'),
    ('admin',      'observer_invite', 'write'),
    ('superadmin', 'observer_invite', 'read'),
    ('superadmin', 'observer_invite', 'write')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 5. client_health permission (extends existing intelligence)
--    already covered by intelligence:read — no new row needed.
--    Record in role_permissions for explicitness only.
-- ---------------------------------------------------------------------------
INSERT INTO role_permissions (role, resource, action) VALUES
    ('viewer',     'client_health', 'read'),
    ('operator',   'client_health', 'read'),
    ('admin',      'client_health', 'read'),
    ('superadmin', 'client_health', 'read')
ON CONFLICT DO NOTHING;
