-- Migration Planner: network infrastructure + tenant usage columns
-- Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)

-- Tenant in_use_gb aggregation
ALTER TABLE migration_tenants ADD COLUMN IF NOT EXISTS total_in_use_gb NUMERIC(12,2) DEFAULT 0;

-- Network infrastructure summary table
CREATE TABLE IF NOT EXISTS migration_networks (
    id              BIGSERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES migration_projects(project_id) ON DELETE CASCADE,
    network_name    TEXT NOT NULL,
    vlan_id         INT,
    network_type    TEXT DEFAULT 'standard',   -- vlan_based | nsx_t | isolated | standard
    vm_count        INT DEFAULT 0,
    subnet          TEXT,                       -- manually editable
    gateway         TEXT,                       -- manually editable
    dns_servers     TEXT,                       -- manually editable
    ip_range        TEXT,                       -- manually editable
    pcd_target      TEXT,                       -- PCD target network mapping
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, network_name)
);

CREATE INDEX IF NOT EXISTS idx_mig_networks_project ON migration_networks(project_id);
