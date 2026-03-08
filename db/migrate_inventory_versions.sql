-- =====================================================================
-- Migration: Inventory Snapshots / Versions
-- Records a point-in-time snapshot of VM, tenant, and resource counts
-- on every inventory refresh so we can diff "what changed since X".
-- =====================================================================

CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id              SERIAL PRIMARY KEY,
    collected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Lightweight snapshot of key fields only (no full raw_json)
    snapshot        JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_collected_at
    ON inventory_snapshots (collected_at DESC);

-- RBAC: read access for operators and above, admin for superadmin
INSERT INTO role_permissions (role, resource, action) VALUES
('viewer',     'inventory_versions', 'read'),
('operator',   'inventory_versions', 'read'),
('admin',      'inventory_versions', 'read'),
('superadmin', 'inventory_versions', 'admin')
ON CONFLICT (role, resource, action) DO NOTHING;
